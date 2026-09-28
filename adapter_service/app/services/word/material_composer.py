"""Read-only, source-grounded single-section material composition."""
import json
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone

from app.core.errors import AdapterError
from app.services.long_task_coordinator import get_long_task_coordinator, PRIORITY_INTERACTIVE
from app.services.provider_client import ProviderClient, extract_answer, _extract_json_payload, _estimate_direct_tokens
from app.services.word.writing_jobs import CLIENT_JOB_ID_PATTERN

from app.services.model_configurations import direct_model_input_budget, DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_RESERVED_OUTPUT_TOKENS
from app.services.system_prompts import SystemPromptStore

TASK_TYPE = 'word.material_composer'
MATERIAL_COMPOSER_REQUEST_MAX_BYTES = 64 * 1024
_FACT_DATE = re.compile(r'20\d{2}(?:年(?:\d{1,2}月)?(?:\d{1,2}日)?|[-/]\d{1,2}[-/]\d{1,2})')
_FACT_NUMBER = re.compile(
    r'[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?\s*(?:万|亿)?'
    r'(?:元|%|人|条|台|套|个月|个|项|月|年|天|周|次|分钟|小时|毫秒|秒|节点)')


def _date_parts(value):
    return tuple(int(part) for part in re.findall(r'\d+', value))


def _compact_fact(value):
    return re.sub(r'\s+', '', value)


def parse_user_facts(raw_user_facts: str):
    if not raw_user_facts or not isinstance(raw_user_facts, str) or not raw_user_facts.strip():
        return [], {}
    text = raw_user_facts.strip()
    parts = [p.strip() for p in re.split(r'[\r\n]+|[。；]+', text) if p.strip()]
    if not parts:
        parts = [text]
    facts_list = [{'factId': 'user-fact-{0}'.format(i + 1), 'text': part} for i, part in enumerate(parts)]
    fact_map = {item['factId']: item['text'] for item in facts_list}
    fact_map['user-fact'] = text
    fact_map['user_fact'] = text
    return facts_list, fact_map


def _conflict_fact_matches(text):
    patterns = [
        ('项目预算', re.compile(
            r'(?:预算|经费|资金|造价|金额|费用)(?:为|是|达|经核定|确认|调整)?(?:为)?\s*'
            r'(?P<value>[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?\s*(?:万|亿)?元)')),
        ('交付时间', re.compile(
            r'(?P<event>交付|完成|验收|初验|终验|核验|竣工|上线|实施)(?:时间|日期|节点)?'
            r'(?:为|是|至|于|确定为|确认为)?\s*'
            r'(?P<value>20\d{2}年\d{1,2}月(?:\d{1,2}日)?|\d{1,2}个月|20\d{2}-\d{1,2}-\d{1,2})')),
        ('建设工期', re.compile(
            r'(?:工期|周期|历时)(?:为|是)?\s*(?P<value>[0-9]+\s*(?:个?月|天|周|年))')),
        ('负责主体', re.compile(
            r'(?:由|归)(?P<value>[\u4e00-\u9fa5a-zA-Z0-9]+?)(?:负责|承担|牵头|统筹|实施)')),
    ]
    for default_topic, pattern in patterns:
        for match in pattern.finditer(text):
            topic = default_topic
            event = match.groupdict().get('event')
            if event:
                topic = event + '时间'
            # A phase belongs to its own fact: an initial acceptance is not
            # final acceptance, and a second-phase budget is not phase one.
            prefix = re.split(r'[。；;，,\n]', text[:match.start()])[-1]
            phases = re.findall(r'(?:[一二三四五六七八九十]+|[0-9]+)期', prefix)
            if phases:
                topic = phases[-1] + topic
            value = match.group('value').strip()
            snippet = text[max(0, match.start() - 15):min(len(text), match.end() + 15)].strip()
            yield topic, value, snippet


def _conflict_value_key(value):
    if _FACT_DATE.fullmatch(value):
        return _date_parts(value)
    return _compact_fact(value).replace(',', '')


def detect_material_conflicts(catalog: dict, user_facts: str = None, section_title: str = "", instruction: str = "") -> list:
    cat = catalog or {}
    fragments = cat.get('fragmentsList')
    if fragments is None:
        raw_frags = cat.get('fragments', [])
        fragments = list(raw_frags.values()) if isinstance(raw_frags, dict) else raw_frags
    names = {d.get('materialId'): d.get('fileName') or '资料文档' for d in cat.get('documents', [])}
    sources = {}
    for fragment in fragments or []:
        material_id = fragment.get('materialId')
        name = fragment.get('fileName') or names.get(material_id) or '参考资料'
        key = (material_id or name, 'material')
        source = sources.setdefault(key, {'name': name, 'texts': []})
        source['texts'].append(fragment.get('text', ''))
    if isinstance(user_facts, str) and user_facts.strip():
        sources[('user', 'user')] = {'name': '用户补充事实', 'texts': [user_facts.strip()]}

    fact_options = {}
    for (source_id, source_type), source in sources.items():
        for topic, value, snippet in _conflict_fact_matches(' '.join(source['texts'])):
            options = fact_options.setdefault(topic, [])
            value_key = _conflict_value_key(value)
            if any(o['sourceId'] == source_id and o['sourceType'] == source_type and
                   _conflict_value_key(o['value']) == value_key for o in options):
                continue
            options.append({'sourceId': source_id, 'sourceType': source_type,
                            'sourceName': source['name'], 'value': value,
                            'text': '{0}：{1}'.format(source['name'], snippet)})

    conflicts = []
    for topic, options in fact_options.items():
        if len({_conflict_value_key(o['value']) for o in options}) < 2:
            continue
        index = len(conflicts) + 1
        for option_index, option in enumerate(options, 1):
            option['optionId'] = 'opt-{0}-{1}'.format(index, option_index)
        conflicts.append({
            'conflictId': 'conflict-{0}'.format(index), 'topic': topic,
            'difference': '；'.join('{0}（{1}）'.format(o['sourceName'], o['value']) for o in options) + '存在差异',
            'options': options,
        })
    return conflicts


def verify_key_facts(text: str, cited_sources_text: str) -> list:
    if not text or not isinstance(text, str):
        return []
    unverified = []
    sources = cited_sources_text or ''
    # Compare complete tokens; 1500万元 cannot substantiate 500万元.
    source_numbers = {
        _compact_fact(m.group()).replace(',', '')
        for m in _FACT_NUMBER.finditer(_FACT_DATE.sub('', sources))
    }
    for m in _FACT_NUMBER.finditer(_FACT_DATE.sub('', text)):
        val = m.group().strip()
        if _compact_fact(val).replace(',', '') not in source_numbers:
            item_msg = "{0}（待核对：引文中未见此数值）".format(val)
            if item_msg not in unverified:
                unverified.append(item_msg)

    source_dates = [_date_parts(m.group()) for m in _FACT_DATE.finditer(sources)]
    for m in _FACT_DATE.finditer(text):
        d_val = m.group()
        parts = _date_parts(d_val)
        if not any(parts == source_date[:len(parts)] for source_date in source_dates):
            item_msg = "{0}（待核对：引文中未见此日期）".format(d_val)
            if item_msg not in unverified:
                unverified.append(item_msg)

    # These statements need their subject and obligation, not just a name or
    # amount somewhere in the quotes. Paraphrases we cannot align stay visible
    # as items for human review rather than being declared verified.
    statement_markers = re.compile(
        r'名称|命名|称为|负责|责任|牵头|承担|统筹|担任|项目经理|'
        r'组织实施|主持|承诺|保证|保障|免费|终身|永久|'
        r'不超过|不少于|不低于|至少|最多|不得|必须|应当|须')
    source_clauses = [_compact_fact(c) for c in re.split(r'[，,。；;\n]', sources) if c.strip()]
    clean_text = re.sub(r'〔待补充：[^〕]*〕', '', text)
    for clause in re.split(r'[，,。；;\n]', clean_text):
        clause = clause.strip()
        if clause and statement_markers.search(clause):
            normalized = _compact_fact(clause)
            if normalized not in source_clauses:
                item_msg = '{0}（待核对：名称、责任或承诺未与引文原文对齐）'.format(clause)
                if item_msg not in unverified:
                    unverified.append(item_msg)
    return unverified


def extract_relevant_fragments(catalog: dict, section_title: str, instruction: str, max_tokens: int) -> list:
    cat = catalog or {}
    fragments = cat.get("fragmentsList")
    if fragments is None:
        raw_frags = cat.get("fragments")
        if isinstance(raw_frags, dict):
            fragments = list(raw_frags.values())
        elif isinstance(raw_frags, list):
            fragments = list(raw_frags)
        else:
            fragments = []
    if not fragments:
        return []

    import re
    serialized = json.dumps(fragments, ensure_ascii=False)
    if max(len(serialized), (len(serialized.encode("utf-8")) + 3) // 4) <= max_tokens:
        return list(fragments)

    query_text = "{0} {1}".format(section_title or "", instruction or "")

    sections = {}
    section = ""
    last_material = None
    for block in cat.get("blocks", []):
        curr_material = block.get("materialId") or block.get("fileName", "")
        if curr_material != last_material:
            section = ""
            last_material = curr_material
        if block.get("kind") == "heading":
            section = block.get("text", "")
        sections[(curr_material, block.get("blockId"))] = section
        sections[block.get("blockId")] = section

    clean_inst = re.sub(r"^(整理|列出|汇总|总结|查找|编写|说明|提取)", "", (instruction or "").strip())
    chunks = [c for c in re.split(r"[与和及的在于按对把让请依据等以或，。、；：\s\-_/]+", clean_inst) if c]
    inst_phrases = set()
    for c in chunks:
        inst_phrases.add(c)
        for w in re.findall(r"[a-zA-Z0-9]+", c):
            if len(w) >= 2:
                inst_phrases.add(w)
        for w in re.findall(r"[\u4e00-\u9fff]+", c):
            for n in (4, 3, 2):
                for i in range(len(w) - n + 1):
                    inst_phrases.add(w[i:i+n])

    section_phrases = [p for p in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", section_title or "") if p]
    query_terms = re.findall(r"[a-zA-Z0-9]+", query_text)

    matched_sections = set()
    for toc_entry in cat.get("toc", []):
        toc_title = toc_entry.get("sectionTitle", "")
        if toc_title:
            if any(phrase in toc_title for phrase in section_phrases):
                matched_sections.add(toc_title)
            elif any(phrase in toc_title for phrase in inst_phrases):
                matched_sections.add(toc_title)

    row_text_map = {}
    for frag in fragments:
        if frag.get("kind") == "table_cell":
            b_material = frag.get("materialId") or frag.get("fileName", "")
            b_id = frag.get("blockId", "")
            r_idx = frag.get("source", {}).get("row")
            if r_idx is not None:
                key = (b_material, b_id, r_idx)
                row_text_map[key] = row_text_map.get(key, "") + " " + frag.get("text", "")

    scored = []
    for idx, frag in enumerate(fragments):
        text = frag.get("text", "")
        b_material = frag.get("materialId") or frag.get("fileName", "")
        b_id = frag.get("blockId", "")
        sec = frag.get("section") or sections.get((b_material, b_id)) or sections.get(b_id, "")
        score = 0.0

        if sec and sec in matched_sections:
            score += 50.0
        elif any(phrase in sec for phrase in section_phrases):
            score += 40.0
        elif any(phrase in sec for phrase in inst_phrases):
            score += 30.0

        eval_text = text
        if frag.get("kind") == "table_cell":
            r_idx = frag.get("source", {}).get("row")
            if r_idx is not None:
                eval_text = row_text_map.get((b_material, b_id, r_idx), text)

        for phrase in inst_phrases:
            if phrase in eval_text:
                score += len(phrase) * 2.0

        for phrase in section_phrases:
            if phrase in eval_text:
                score += 15.0

        for term in query_terms:
            if term in eval_text:
                score += 1.0

        if frag.get("kind") in ("table", "table_cell") and score > 0:
            score += 5.0

        scored.append({"index": idx, "fragment": frag, "score": score, "section": sec})

    n = len(scored)
    for i in range(n):
        if scored[i]["score"] >= 20.0:
            sec_i = scored[i]["section"]
            if i > 0 and scored[i-1]["section"] == sec_i:
                scored[i-1]["score"] += 15.0
            if i + 1 < n and scored[i+1]["section"] == sec_i:
                scored[i+1]["score"] += 15.0

    ranked = sorted(scored, key=lambda x: (x["score"], -x["index"]), reverse=True)

    budget_limit = int(max_tokens * 0.90)
    current_tokens = 0
    selected_indices = set()

    for item in ranked:
        serialized_item = json.dumps(item["fragment"], ensure_ascii=False)
        t_tokens = max(len(serialized_item), (len(serialized_item.encode("utf-8")) + 3) // 4) + 1
        if current_tokens + t_tokens <= budget_limit:
            selected_indices.add(item["index"])
            current_tokens += t_tokens

    result = [fragments[i] for i in sorted(selected_indices)]
    return result


class MaterialComposerJobs:
    def __init__(self, materials, provider=None, coordinator=None):
        self.materials = materials
        self.provider = provider or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.Lock()

    def start(self, payload, trace_id):
        if not isinstance(payload, dict):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '请选择资料并填写目标章节和要求。', status_code=422)
        required_fields = ('documentSessionId', 'clientJobId', 'sectionTitle', 'instruction')
        if any(not isinstance(payload.get(k), str) or not payload[k].strip() for k in required_fields):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '请选择资料并填写目标章节和要求。', status_code=422)
        request = {key: payload[key].strip() for key in required_fields}
        if payload.get('userFacts') and isinstance(payload['userFacts'], str) and payload['userFacts'].strip():
            request['userFacts'] = payload['userFacts'].strip()
        if 'conflictResolutions' in payload:
            if not isinstance(payload['conflictResolutions'], list):
                raise AdapterError('REQUEST_VALIDATION_FAILED', '冲突选择格式无效，请重新核对。', status_code=422)
            if payload['conflictResolutions']:
                request['conflictResolutions'] = deepcopy(payload['conflictResolutions'])
        job_id = request['clientJobId']
        if not CLIENT_JOB_ID_PATTERN.match(job_id):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '任务编号格式无效。', status_code=422)

        session_id = request['documentSessionId']
        raw_mids = payload.get('materialIds')
        if raw_mids is not None:
            if not isinstance(raw_mids, list) or not raw_mids or any(not isinstance(m, str) or not m.strip() for m in raw_mids):
                raise AdapterError('REQUEST_VALIDATION_FAILED', 'materialIds 必须为包含有效资料编号的非空数组。', status_code=422)
            material_ids = [m.strip() for m in raw_mids]
        elif payload.get('materialId') and isinstance(payload['materialId'], str) and payload['materialId'].strip():
            material_ids = [payload['materialId'].strip()]
        else:
            material_ids = []

        request_repr = dict(request)
        if material_ids:
            request_repr['materialIds'] = sorted(material_ids)
        fingerprint = json.dumps(request_repr, ensure_ascii=False, sort_keys=True)

        with self._lock:
            existing = self.coordinator.get(job_id, task_type=TASK_TYPE)
            if existing:
                self.get(job_id, session_id)
                if self.coordinator.get_request_fingerprint(job_id, task_type=TASK_TYPE) != fingerprint:
                    raise AdapterError('MATERIAL_COMPOSER_JOB_CONFLICT', '任务编号已绑定其他请求。', status_code=409)
                return existing

            session_cat = self.materials.get_session_catalog(session_id)
            if material_ids:
                target_docs = []
                for mid in material_ids:
                    m = self.materials.view_material(mid)
                    if m.get('documentSessionId') != session_id:
                        raise AdapterError('MATERIAL_NOT_FOUND', '当前文档会话没有该资料，请重新导入。', status_code=404)
                    target_docs.append(m)
                target_mids = set(material_ids)
                catalog_view = {
                    'documentSessionId': session_id,
                    'documents': [d for d in (session_cat.get('documents', []) if session_cat else target_docs) if d['materialId'] in target_mids],
                    'toc': [t for t in (session_cat.get('toc', []) if session_cat else []) if t['materialId'] in target_mids],
                    'blocks': [b for m in target_docs for b in m.get('blocks', [])],
                    'fragments': {f['fragmentId']: f for m in target_docs for f in m.get('fragments', [])},
                    'fragmentsList': [f for m in target_docs for f in m.get('fragments', [])],
                }
            elif session_cat and session_cat.get('documents'):
                catalog_view = deepcopy(session_cat)
            else:
                raise AdapterError('MATERIAL_NOT_FOUND', '当前文档会话没有该资料，请重新导入。', status_code=404)

            if request.get('conflictResolutions'):
                conflicts = {c['conflictId']: c for c in detect_material_conflicts(
                    catalog_view, request.get('userFacts', ''), request['sectionTitle'], request['instruction'])}
                resolved = []
                for choice in request['conflictResolutions']:
                    conflict_id = choice.get('conflictId') if isinstance(choice, dict) else None
                    conflict = conflicts.get(conflict_id) if isinstance(conflict_id, str) else None
                    if not conflict:
                        raise AdapterError('REQUEST_VALIDATION_FAILED', '冲突选择已失效，请重新核对并选择。', status_code=422)
                    candidates = [o for o in conflict['options'] if o['value'] == choice.get('chosenValue')]
                    for field, key in [('chosenCandidateId', 'optionId'), ('chosenSource', 'sourceName'),
                                       ('sourceId', 'sourceId'), ('sourceType', 'sourceType')]:
                        if field in choice:
                            candidates = [o for o in candidates if o[key] == choice[field]]
                    if len(candidates) != 1 or ('topic' in choice and choice['topic'] != conflict['topic']):
                        raise AdapterError('REQUEST_VALIDATION_FAILED', '冲突选择已失效，请重新核对并选择。', status_code=422)
                    option = candidates[0]
                    resolved.append(dict(conflictId=conflict['conflictId'], topic=conflict['topic'],
                                         chosenCandidateId=option['optionId'], chosenValue=option['value'],
                                         chosenSource=option['sourceName'], sourceId=option['sourceId'],
                                         sourceType=option['sourceType']))
                request['conflictResolutions'] = resolved

            auth = self.provider.resolve_task_auth(TASK_TYPE)
            if not auth.get('providerBaseUrl') or not auth.get('apiKey'):
                raise AdapterError('MODEL_CONFIG_INCOMPLETE', '资料编写尚未配置模型，请前往设置。', status_code=400)

            asset = SystemPromptStore().load(TASK_TYPE)
            budget, _ = direct_model_input_budget(
                int(auth.get('contextWindowTokens') or DEFAULT_CONTEXT_WINDOW_TOKENS),
                int(auth.get('maxOutputTokens') or DEFAULT_RESERVED_OUTPUT_TOKENS)
            )
            overhead = _estimate_direct_tokens(asset['content'], self._prompt(request, []))
            if overhead >= budget:
                raise AdapterError('MODEL_INPUT_OVER_BUDGET', '资料超过单次模型预算，请缩小资料范围；未截断资料。', status_code=413)

            return self.coordinator.submit(
                job_id=job_id, trace_id=trace_id, task_type=TASK_TYPE, runner=self._run,
                snapshot={
                    'request': request,
                    'catalog': catalog_view,
                    'taskAuth': deepcopy(auth),
                    'traceId': trace_id,
                    'budget': budget,
                    'systemPrompt': asset['content'],
                },
                request_fingerprint=fingerprint, failure_code='MATERIAL_COMPOSER_FAILED',
                failure_message='资料编写失败，请检查模型结果或缩小资料范围。',
                public_metadata={'documentSessionId': session_id, 'streamingEnabled': False},
                safe_failure_codes={'MODEL_INPUT_OVER_BUDGET', 'MATERIAL_COMPOSER_INVALID_RESULT', 'PROVIDER_TIMEOUT', 'MODEL_CONFIG_INCOMPLETE', 'MODEL_FINAL_CONTENT_TOKEN_LIMIT'},
                priority_class=PRIORITY_INTERACTIVE, allow_running_cancel=True)

    def detect_conflicts(self, payload):
        if not isinstance(payload, dict):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '请求参数格式错误。', status_code=422)
        session_id = payload.get('documentSessionId')
        if not session_id or not isinstance(session_id, str):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '缺少有效文档会话编号。', status_code=422)
        session_cat = self.materials.get_session_catalog(session_id)
        user_facts = payload.get('userFacts', '')
        section_title = payload.get('sectionTitle', '')
        instruction = payload.get('instruction', '')
        conflicts = detect_material_conflicts(session_cat, user_facts=user_facts,
                                              section_title=section_title, instruction=instruction)
        return {'conflicts': conflicts}

    def get(self, job_id, document_session_id):
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if not job or not document_session_id or job.get('documentSessionId') != document_session_id:
            raise AdapterError('MATERIAL_COMPOSER_JOB_NOT_FOUND', '当前文档会话没有该任务。', status_code=404)
        return job

    def cancel(self, job_id, document_session_id):
        self.get(job_id, document_session_id)
        return self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)

    @staticmethod
    def _prompt(request, material_or_fragments):
        fragments = material_or_fragments if isinstance(material_or_fragments, list) else material_or_fragments.get('fragments', [])
        payload = {
            'sectionTitle': request['sectionTitle'],
            'instruction': request['instruction'],
            'materials': fragments,
        }
        if request.get('userFacts'):
            payload['userFacts'] = request['userFacts']
            payload['userFactItems'] = parse_user_facts(request['userFacts'])[0]
        if request.get('conflictResolutions'):
            payload['conflictResolutions'] = request['conflictResolutions']
        return SystemPromptStore().load(TASK_TYPE)['content'] + '\n' + json.dumps(payload, ensure_ascii=False)

    def _run(self, snapshot, progress):
        progress('preparing')
        request = snapshot['request']
        catalog = snapshot['catalog']
        budget = snapshot['budget']
        system_prompt = snapshot['systemPrompt']

        progress('extracting')
        overhead = _estimate_direct_tokens(system_prompt, self._prompt(request, []))
        available_tokens = budget - overhead
        selected_fragments = extract_relevant_fragments(
            catalog, request['sectionTitle'], request['instruction'], available_tokens
        )
        prompt = self._prompt(request, selected_fragments)
        while selected_fragments and _estimate_direct_tokens(system_prompt, prompt) > budget:
            available_tokens = int(available_tokens * 0.75)
            selected_fragments = extract_relevant_fragments(
                catalog, request['sectionTitle'], request['instruction'], available_tokens
            )
            prompt = self._prompt(request, selected_fragments)
        if not selected_fragments or _estimate_direct_tokens(system_prompt, prompt) > budget:
            raise AdapterError('MODEL_INPUT_OVER_BUDGET', '资料超过单次模型预算，请缩小资料范围；未截断资料。', status_code=413)

        progress('provider_processing')
        body = self.provider.post_task(TASK_TYPE, snapshot['traceId'], {}, prompt,
                                       task_auth=snapshot['taskAuth'], progress_callback=progress)

        progress('parsing')
        try:
            answer = _extract_json_payload(extract_answer(body))
            paragraphs = answer['paragraphs']
            if not isinstance(paragraphs, list) or not paragraphs:
                raise ValueError()

            user_facts_raw = request.get('userFacts', '')
            user_facts_items, user_fact_map = parse_user_facts(user_facts_raw)

            extracted_frag_map = {f['fragmentId']: f for f in selected_fragments}
            sections = {}
            section = '正文'
            last_material = None
            for block in catalog.get('blocks', []):
                curr_material = block.get('materialId') or block.get('fileName', '')
                if curr_material != last_material:
                    section = '正文'
                    last_material = curr_material
                if block.get('kind') == 'heading':
                    section = block.get('text', '正文')
                sections[(curr_material, block.get('blockId'))] = section
                sections[block.get('blockId')] = section

            result, missing, all_unverified = [], [], []
            for paragraph in paragraphs:
                text = paragraph['text']
                ids = paragraph.get('fragmentIds', [])
                items = paragraph.get('missingItems', [])
                unverified = list(paragraph.get('unverifiedItems', []))
                if not isinstance(text, str) or not text.strip() or not isinstance(ids, list) or not isinstance(items, list):
                    raise ValueError()
                if any(not isinstance(item, str) or not item.strip() for item in items):
                    raise ValueError()

                sources = []
                for fragment_id in ids:
                    if not isinstance(fragment_id, str):
                        raise ValueError('invalid fragment id')
                    if fragment_id in user_fact_map:
                        quote = user_fact_map[fragment_id]
                        sources.append({
                            'fragmentId': fragment_id,
                            'sourceType': 'user',
                            'fileName': '用户补充事实',
                            'section': '用户提供',
                            'quote': quote,
                        })
                    elif fragment_id in extracted_frag_map:
                        fragment = extracted_frag_map[fragment_id]
                        b_file = fragment.get('fileName', '')
                        b_material = fragment.get('materialId') or b_file
                        sec_name = sections.get((b_material, fragment.get('blockId'))) or sections.get(fragment.get('blockId'), '正文')
                        sources.append({
                            'fragmentId': fragment_id,
                            'sourceType': 'material',
                            'fileName': b_file or (catalog.get('documents') and catalog['documents'][0].get('fileName')) or '',
                            'section': sec_name,
                            'quote': fragment.get('text', ''),
                        })
                    else:
                        raise ValueError("fragment not in extracted set")

                if not ids and not sources:
                    remainder = text
                    for item in items:
                        remainder = remainder.replace('〔待补充：' + item.strip() + '〕', '')
                    for item in unverified:
                        remainder = remainder.replace(item, '')
                    if (not items and not unverified) or remainder.strip():
                        raise ValueError()

                # Post-verification on key facts
                cited_sources_text = " ".join(s.get('quote', '') for s in sources)
                detected_unverified = verify_key_facts(text, cited_sources_text)
                for topic, value, _ in _conflict_fact_matches(text):
                    for choice in request.get('conflictResolutions', []):
                        if topic == choice['topic'] and _conflict_value_key(value) != _conflict_value_key(choice['chosenValue']):
                            detected_unverified.append('{0}：{1}（待核对：与用户采纳的{2}不一致）'.format(
                                topic, value, choice['chosenValue']))
                for u in detected_unverified:
                    if u not in unverified:
                        unverified.append(u)

                for item in items:
                    marker = '〔待补充：' + item.strip() + '〕'
                    if marker not in text:
                        text += marker
                    if item.strip() not in missing:
                        missing.append(item.strip())

                for u in unverified:
                    if u not in all_unverified:
                        all_unverified.append(u)

                result.append({'text': text, 'sources': sources, 'missingItems': items, 'unverifiedItems': unverified})
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise AdapterError('MATERIAL_COMPOSER_INVALID_RESULT', '模型结果缺少有效出处或缺项说明，已拒绝展示。', status_code=502) from exc

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        basis_materials = []
        for doc in catalog.get('documents', []):
            basis_materials.append({
                'materialId': doc.get('materialId'),
                'fileName': doc.get('fileName'),
                'updatedAt': doc.get('updatedAt') or doc.get('importedAt') or now_iso,
            })

        return {
            'plainText': '\n\n'.join(p['text'] for p in result),
            'paragraphs': result,
            'missingItems': missing,
            'unverifiedItems': all_unverified,
            'conflictResolutions': request.get('conflictResolutions', []),
            'userFacts': user_facts_raw,
            'taskType': TASK_TYPE,
            'documentSessionId': request['documentSessionId'],
            'basisMaterials': basis_materials,
            'generatedAt': now_iso,
        }
