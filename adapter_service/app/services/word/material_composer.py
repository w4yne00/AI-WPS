"""Read-only, source-grounded single-section material composition."""
import json
import threading
from copy import deepcopy

from app.core.errors import AdapterError
from app.services.long_task_coordinator import get_long_task_coordinator, PRIORITY_INTERACTIVE
from app.services.provider_client import ProviderClient, extract_answer, _extract_json_payload, _estimate_direct_tokens
from app.services.word.writing_jobs import CLIENT_JOB_ID_PATTERN

from app.services.model_configurations import direct_model_input_budget, DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_RESERVED_OUTPUT_TOKENS
from app.services.system_prompts import SystemPromptStore

TASK_TYPE = 'word.material_composer'
MATERIAL_COMPOSER_REQUEST_MAX_BYTES = 64 * 1024


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
                safe_failure_codes={'MODEL_INPUT_OVER_BUDGET', 'MATERIAL_COMPOSER_INVALID_RESULT', 'PROVIDER_TIMEOUT', 'MODEL_CONFIG_INCOMPLETE'},
                priority_class=PRIORITY_INTERACTIVE, allow_running_cancel=True)

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
        return SystemPromptStore().load(TASK_TYPE)['content'] + '\n' + json.dumps({
            'sectionTitle': request['sectionTitle'],
            'instruction': request['instruction'],
            'materials': fragments,
        }, ensure_ascii=False)

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

            result, missing = [], []
            for paragraph in paragraphs:
                text = paragraph['text']
                ids = paragraph['fragmentIds']
                items = paragraph.get('missingItems', [])
                if not isinstance(text, str) or not text.strip() or not isinstance(ids, list) or not isinstance(items, list):
                    raise ValueError()
                if any(not isinstance(item, str) or not item.strip() for item in items):
                    raise ValueError()
                if not ids:
                    remainder = text
                    for item in items:
                        remainder = remainder.replace('〔待补充：' + item.strip() + '〕', '')
                    if not items or remainder.strip():
                        raise ValueError()

                sources = []
                for fragment_id in ids:
                    if fragment_id not in extracted_frag_map:
                        raise ValueError("fragment not in extracted set")
                    fragment = extracted_frag_map[fragment_id]
                    b_file = fragment.get('fileName', '')
                    b_material = fragment.get('materialId') or b_file
                    sec_name = sections.get((b_material, fragment.get('blockId'))) or sections.get(fragment.get('blockId'), '正文')
                    sources.append({
                        'fragmentId': fragment_id,
                        'fileName': b_file or (catalog.get('documents') and catalog['documents'][0].get('fileName')) or '',
                        'section': sec_name,
                        'quote': fragment.get('text', ''),
                    })

                for item in items:
                    marker = '〔待补充：' + item.strip() + '〕'
                    if marker not in text:
                        text += marker
                    if item.strip() not in missing:
                        missing.append(item.strip())
                result.append({'text': text, 'sources': sources, 'missingItems': items})
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise AdapterError('MATERIAL_COMPOSER_INVALID_RESULT', '模型结果缺少有效出处或缺项说明，已拒绝展示。', status_code=502) from exc

        return {
            'plainText': '\n\n'.join(p['text'] for p in result),
            'paragraphs': result,
            'missingItems': missing,
            'taskType': TASK_TYPE,
            'documentSessionId': request['documentSessionId']
        }
