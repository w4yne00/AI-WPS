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
    all_text = " ".join(f.get("text", "") for f in fragments)
    if _estimate_direct_tokens("", all_text) <= max_tokens:
        return list(fragments)

    query_text = "{0} {1}".format(section_title or "", instruction or "")
    section_phrases = [p for p in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", section_title or "") if p]
    query_terms = [p for p in re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", query_text) if p]

    matched_sections = set()
    for toc_entry in cat.get("toc", []):
        toc_title = toc_entry.get("sectionTitle", "")
        if toc_title:
            if any(phrase in toc_title for phrase in section_phrases):
                matched_sections.add(toc_title)
            elif any(term in toc_title for term in query_terms):
                matched_sections.add(toc_title)

    scored = []
    for idx, frag in enumerate(fragments):
        text = frag.get("text", "")
        sec = frag.get("section", "")
        score = 0.0

        if sec and sec in matched_sections:
            score += 50.0
        elif any(phrase in sec for phrase in section_phrases):
            score += 40.0

        for phrase in section_phrases:
            if phrase in text:
                score += 20.0

        for term in query_terms:
            if term in text:
                score += 1.0

        if frag.get("kind") == "table" and score > 0:
            score += 5.0

        scored.append({"index": idx, "fragment": frag, "score": score})

    n = len(scored)
    for i in range(n):
        if scored[i]["score"] >= 20.0:
            if i > 0 and scored[i-1]["fragment"].get("section") == scored[i]["fragment"].get("section"):
                scored[i-1]["score"] += 15.0
            if i + 1 < n and scored[i+1]["fragment"].get("section") == scored[i]["fragment"].get("section"):
                scored[i+1]["score"] += 15.0

    ranked = sorted(scored, key=lambda x: (x["score"], -x["index"]), reverse=True)

    budget_limit = int(max_tokens * 0.90)
    current_tokens = 0
    selected_indices = set()

    for item in ranked:
        t = item["fragment"].get("text", "")
        t_tokens = max(len(t), (len(t.encode("utf-8")) + 3) // 4) + 16
        if current_tokens + t_tokens <= budget_limit:
            selected_indices.add(item["index"])
            current_tokens += t_tokens
        elif not selected_indices:
            selected_indices.add(item["index"])
            break

    result = [fragments[i] for i in sorted(selected_indices)]
    return result


class MaterialComposerJobs:
    def __init__(self, materials, provider=None, coordinator=None):
        self.materials = materials
        self.provider = provider or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.Lock()

    def start(self, payload, trace_id):
        fields = ('materialId', 'documentSessionId', 'clientJobId', 'sectionTitle', 'instruction')
        if not isinstance(payload, dict) or any(not isinstance(payload.get(k), str) or not payload[k].strip() for k in fields):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '请选择资料并填写目标章节和要求。', status_code=422)
        request = {key: payload[key].strip() for key in fields}
        job_id = request['clientJobId']
        if not CLIENT_JOB_ID_PATTERN.match(job_id):
            raise AdapterError('REQUEST_VALIDATION_FAILED', '任务编号格式无效。', status_code=422)
        fingerprint = json.dumps(request, ensure_ascii=False, sort_keys=True)
        with self._lock:
            existing = self.coordinator.get(job_id, task_type=TASK_TYPE)
            if existing:
                self.get(job_id, request['documentSessionId'])
                if self.coordinator.get_request_fingerprint(job_id, task_type=TASK_TYPE) != fingerprint:
                    raise AdapterError('MATERIAL_COMPOSER_JOB_CONFLICT', '任务编号已绑定其他请求。', status_code=409)
                return existing
            material = deepcopy(self.materials.view_material(request['materialId']))
            if material['documentSessionId'] != request['documentSessionId']:
                raise AdapterError('MATERIAL_NOT_FOUND', '当前文档会话没有该资料，请重新导入。', status_code=404)
            auth = self.provider.resolve_task_auth(TASK_TYPE)
            if not auth.get('providerBaseUrl') or not auth.get('apiKey'):
                raise AdapterError('MODEL_CONFIG_INCOMPLETE', '资料编写尚未配置模型，请前往设置。', status_code=400)
            prompt = self._prompt(request, material)
            asset = SystemPromptStore().load(TASK_TYPE)
            budget, _ = direct_model_input_budget(int(auth.get('contextWindowTokens') or DEFAULT_CONTEXT_WINDOW_TOKENS), int(auth.get('maxOutputTokens') or DEFAULT_RESERVED_OUTPUT_TOKENS))
            if _estimate_direct_tokens(asset['content'], prompt) > budget:
                raise AdapterError('MODEL_INPUT_OVER_BUDGET', '资料超过单次模型预算，请缩小资料范围；未截断资料。', status_code=413)
            return self.coordinator.submit(
                job_id=job_id, trace_id=trace_id, task_type=TASK_TYPE, runner=self._run,
                snapshot={'request': request, 'material': material, 'taskAuth': deepcopy(auth), 'traceId': trace_id},
                request_fingerprint=fingerprint, failure_code='MATERIAL_COMPOSER_FAILED',
                failure_message='资料编写失败，请检查模型结果或缩小资料范围。',
                public_metadata={'documentSessionId': request['documentSessionId'], 'streamingEnabled': False},
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
    def _prompt(request, material):
        return SystemPromptStore().load(TASK_TYPE)['content'] + '\n' + json.dumps({'sectionTitle': request['sectionTitle'], 'instruction': request['instruction'],
                           'materials': material['fragments']}, ensure_ascii=False)

    def _run(self, snapshot, progress):
        progress('preparing')
        request, material = snapshot['request'], snapshot['material']
        prompt = self._prompt(request, material)
        progress('provider_processing')
        body = self.provider.post_task(TASK_TYPE, snapshot['traceId'], {}, prompt,
                                       task_auth=snapshot['taskAuth'], progress_callback=progress)
        progress('parsing')
        try:
            answer = _extract_json_payload(extract_answer(body))
            paragraphs = answer['paragraphs']
            if not isinstance(paragraphs, list) or not paragraphs:
                raise ValueError()
            fragments = {f['fragmentId']: f for f in material['fragments']}
            sections = {}
            section = '正文'
            for block in material['blocks']:
                if block['kind'] == 'heading':
                    section = block['text']
                sections[block['blockId']] = section
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
                    fragment = fragments[fragment_id]
                    sources.append({'fragmentId': fragment_id, 'fileName': material['fileName'],
                                    'section': sections[fragment['blockId']], 'quote': fragment['text']})
                for item in items:
                    marker = '〔待补充：' + item.strip() + '〕'
                    if marker not in text:
                        text += marker
                    if item.strip() not in missing:
                        missing.append(item.strip())
                result.append({'text': text, 'sources': sources, 'missingItems': items})
        except (KeyError, TypeError, ValueError, IndexError):
            raise AdapterError('MATERIAL_COMPOSER_INVALID_RESULT', '模型结果缺少有效出处或缺项说明，已拒绝展示。', status_code=502)
        return {'plainText': '\n\n'.join(p['text'] for p in result), 'paragraphs': result,
                'missingItems': missing, 'taskType': TASK_TYPE, 'documentSessionId': request['documentSessionId']}
