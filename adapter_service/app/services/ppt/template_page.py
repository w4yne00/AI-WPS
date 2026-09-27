import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import List, Optional

from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore, ppt_material_store
from app.services.long_task_coordinator import (
    get_long_task_coordinator,
    LongTaskCancelled,
    LongTaskCoordinator,
    PRIORITY_INTERACTIVE,
)
from app.services.model_configurations import (
    direct_model_input_budget,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
)
from app.services.provider_client import (
    ProviderClient,
    _extract_json_payload,
    _estimate_direct_tokens,
    extract_answer,
)
from app.services.system_prompts import SystemPromptStore
from app.services.word.material_composer import (
    parse_user_facts,
)

TASK_TYPE = "ppt.template_page"
CLIENT_JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_REQUEST_BYTES = 64 * 1024
MAX_KEY_POINTS = 4
MAX_CHARACTERS = 260
MAX_ESTIMATED_LINES = 8


def evaluate_template_page_capacity(key_points: List[str]) -> dict:
    points = [str(p).strip() for p in (key_points or []) if str(p).strip()]
    point_count = len(points)
    total_chars = sum(len(p) for p in points)
    estimated_lines = sum(
        max(1, (len(line) + 31) // 32)
        for point in points for line in re.split(r"\r\n|\r|\n", point)
    )
    is_overflow = (
        point_count > MAX_KEY_POINTS
        or total_chars > MAX_CHARACTERS
        or estimated_lines > MAX_ESTIMATED_LINES
    )
    return {
        "is_overflow": is_overflow,
        "total_characters": total_chars,
        "estimated_lines": estimated_lines,
        "point_count": point_count,
        "max_characters": MAX_CHARACTERS,
        "max_lines": MAX_ESTIMATED_LINES,
        "max_points": MAX_KEY_POINTS,
    }


def _fragment_chapters(catalog: dict) -> dict:
    chapters = {}
    current = {}
    for block in catalog.get("blocks", []):
        material_id = block.get("materialId", "")
        if block.get("kind") == "heading":
            current[material_id] = block.get("text") or "正文"
        chapters[(material_id, block.get("blockId"))] = current.get(material_id, "正文")
    return chapters


class PptTemplatePageCoordinator:
    def __init__(
        self,
        store: Optional[PptMaterialStore] = None,
        provider: Optional[ProviderClient] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.store = store or ppt_material_store
        self.provider = provider or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()

    def submit_job(self, payload: dict, trace_id: str = "") -> dict:
        if not isinstance(payload, dict):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "请求参数无效。", status_code=422)

        session_id = str(
            payload.get("documentSessionId") or payload.get("document_session_id") or ""
        ).strip()
        if not session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效演示文稿会话编号。", status_code=422)

        client_job_id = str(
            payload.get("clientJobId") or payload.get("client_job_id") or ""
        ).strip()
        if not client_job_id:
            client_job_id = "job_{0}".format(secrets.token_hex(16))
        elif not CLIENT_JOB_ID_PATTERN.match(client_job_id):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "任务编号格式无效。", status_code=422)

        try:
            page_index = int(payload.get("pageIndex") or payload.get("page_index") or 1)
        except (ValueError, TypeError):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "页码必须为正整数。", status_code=422)
        if page_index < 1:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "页码必须为正整数。", status_code=422)
        page_role = str(payload.get("pageRole") or payload.get("page_role") or "content").strip()
        outline_title = str(payload.get("outlineTitle") or payload.get("outline_title") or "").strip()
        outline_key_points = payload.get("outlineKeyPoints") or payload.get("outline_key_points") or []
        if isinstance(outline_key_points, str):
            outline_key_points = [p.strip() for p in outline_key_points.split("\n") if p.strip()]
        outline_fragment_ids = payload.get("outlineFragmentIds") or payload.get("outline_fragment_ids") or []
        instruction = str(payload.get("instruction") or "").strip()
        user_facts = str(payload.get("userFacts") or payload.get("user_facts") or "").strip()

        fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        existing = self.coordinator.get(client_job_id, task_type=TASK_TYPE)
        if existing:
            if self.coordinator.get_request_fingerprint(client_job_id, task_type=TASK_TYPE) != fingerprint:
                raise AdapterError("PPT_TEMPLATE_PAGE_JOB_CONFLICT", "同一任务编号已用于不同请求，请使用新编号重试。", status_code=409)
            return existing
        with self.store._lock:
            catalog = deepcopy(self.store.get_catalog(session_id))
        snapshot = {
            "catalog": catalog,
            "systemPrompt": SystemPromptStore().load(TASK_TYPE)["content"],
            "taskAuth": deepcopy(self.provider.resolve_task_auth(TASK_TYPE)),
            "traceId": trace_id or client_job_id,
            "pageIndex": page_index,
            "pageRole": page_role,
            "outlineTitle": outline_title,
            "outlineKeyPoints": outline_key_points,
            "outlineFragmentIds": outline_fragment_ids,
            "instruction": instruction,
            "userFacts": user_facts,
        }
        return self.coordinator.submit(
            job_id=client_job_id,
            trace_id=trace_id or client_job_id,
            task_type=TASK_TYPE,
            runner=self._run_job,
            snapshot=snapshot,
            request_fingerprint=fingerprint,
            request_conflict_code="PPT_TEMPLATE_PAGE_JOB_CONFLICT",
            failure_code="PPT_TEMPLATE_PAGE_FAILED",
            failure_message="模板正文页生成失败，请检查模型结果或资料内容。",
            public_metadata={"documentSessionId": session_id, "clientJobId": client_job_id, "taskType": TASK_TYPE},
            safe_failure_codes={"PPT_TEMPLATE_PAGE_INVALID_SOURCE", "PPT_TEMPLATE_PAGE_INVALID_SCHEMA", "MODEL_CONFIG_INCOMPLETE", "MODEL_INPUT_OVER_BUDGET", "PROVIDER_TIMEOUT"},
            priority_class=PRIORITY_INTERACTIVE,
            allow_running_cancel=True,
        )

    def get_job(self, job_id: str, document_session_id: str = "") -> dict:
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if not job:
            raise AdapterError("PPT_TEMPLATE_PAGE_NOT_FOUND", "任务不存在或已过期。", status_code=404)
        if document_session_id and job.get("documentSessionId") != document_session_id:
            raise AdapterError("PPT_TEMPLATE_PAGE_SESSION_MISMATCH", "会话不匹配。", status_code=403)
        return job

    query_job = get_job

    def wait_job(self, job_id: str, document_session_id: str = "") -> dict:
        self.get_job(job_id, document_session_id)
        return self.coordinator.wait(job_id, task_type=TASK_TYPE)

    def cancel_job(self, job_id: str, document_session_id: str = "") -> dict:
        self.get_job(job_id, document_session_id)
        return self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)

    def _call_provider_model(
        self,
        system_prompt: str,
        user_content: str,
        task_auth=None,
        trace_id: str = "",
        progress=None,
    ) -> str:
        auth = task_auth if task_auth is not None else self.provider.resolve_task_auth(TASK_TYPE)
        if not auth.get("providerBaseUrl") or not auth.get("apiKey"):
            raise AdapterError("MODEL_CONFIG_INCOMPLETE", "模板正文页任务尚未配置模型，请前往设置。", status_code=400)
        body = self.provider.post_task(
            task_type=TASK_TYPE,
            system_prompt=system_prompt,
            user_content=user_content,
            trace_id=trace_id,
            progress=progress,
            task_auth=auth,
        )
        return extract_answer(body)

    def _run_job(self, snapshot: dict, progress) -> dict:
        def check_cancel():
            if hasattr(progress, "cancel_requested") and progress.cancel_requested():
                raise LongTaskCancelled()

        check_cancel()
        progress("preparing")
        catalog = snapshot["catalog"]
        system_prompt = snapshot["systemPrompt"]
        page_index = snapshot["pageIndex"]
        page_role = snapshot["pageRole"]
        outline_title = snapshot["outlineTitle"]
        outline_key_points = snapshot["outlineKeyPoints"]
        outline_fragment_ids = snapshot["outlineFragmentIds"]
        instruction = snapshot["instruction"]
        user_facts = snapshot["userFacts"]
        basis_materials = [
            {"materialId": doc.get("materialId", ""), "fileName": doc.get("fileName", "参考资料"), "updatedAt": doc.get("updatedAt", "")}
            for doc in catalog.get("documents", [])
        ]
        materials_payload = []
        for fid, frag in (catalog.get("fragments") or {}).items():
            materials_payload.append({
                "fragmentId": frag.get("fragmentId", fid),
                "fileName": frag.get("fileName", "参考资料"),
                "text": frag.get("text", ""),
            })

        user_content = json.dumps({
            "pageIndex": page_index,
            "pageRole": page_role,
            "outlineTitle": outline_title,
            "outlineKeyPoints": outline_key_points,
            "outlineFragmentIds": outline_fragment_ids,
            "instruction": instruction,
            "userFacts": user_facts,
            "materials": materials_payload,
        }, ensure_ascii=False)

        auth = snapshot["taskAuth"]
        budget, _ = direct_model_input_budget(
            int(auth.get("contextWindowTokens") or DEFAULT_CONTEXT_WINDOW_TOKENS),
            int(auth.get("maxOutputTokens") or DEFAULT_RESERVED_OUTPUT_TOKENS),
        )
        if _estimate_direct_tokens(system_prompt, system_prompt + "\n" + user_content) > budget:
            raise AdapterError("MODEL_INPUT_OVER_BUDGET", "资料超过单次模型预算，请缩小资料范围；未截断资料。", status_code=413)
        check_cancel()
        progress("provider_processing")
        raw_answer = self._call_provider_model(system_prompt, user_content, task_auth=auth, trace_id=snapshot["traceId"], progress=progress)
        check_cancel()

        progress("parsing")
        parsed_data = _extract_json_payload(raw_answer)
        if not isinstance(parsed_data, dict):
            raise AdapterError(
                "PPT_TEMPLATE_PAGE_INVALID_SCHEMA",
                "模型未输出有效 JSON 格式对象。",
                status_code=502,
            )

        if parsed_data.get("schemaVersion") != "ppt.template_page.v1":
            raise AdapterError(
                "PPT_TEMPLATE_PAGE_INVALID_SCHEMA",
                "模型输出版本不匹配，预期 ppt.template_page.v1。",
                status_code=502,
            )

        title = str(parsed_data.get("title") or outline_title or "第 {0} 页".format(page_index)).strip()
        raw_points = parsed_data.get("keyPoints") or outline_key_points or []
        if isinstance(raw_points, list):
            key_points = [str(p).strip() for p in raw_points if str(p).strip()]
        else:
            key_points = [str(raw_points).strip()] if str(raw_points).strip() else []

        speaker_notes = str(parsed_data.get("speakerNotes") or "").strip()
        missing_items = [str(m).strip() for m in (parsed_data.get("missingItems") or []) if str(m).strip()]
        fids = parsed_data.get("fragmentIds") or outline_fragment_ids or []
        if not isinstance(fids, list):
            fids = [fids] if fids else []

        existing_frags = catalog.get("fragments") or {}
        chapters = _fragment_chapters(catalog)
        _, user_fact_map = parse_user_facts(user_facts)
        if user_fact_map:
            user_fact_map["user"] = user_facts.strip()

        sources = []
        for fid in fids:
            clean_fid = str(fid).strip()
            if clean_fid.lower() in user_fact_map:
                sources.append({
                    "sourceId": clean_fid,
                    "sourceType": "user",
                    "fileName": "用户补充事实",
                    "chapter": "用户补充",
                    "text": user_fact_map[clean_fid.lower()],
                })
                continue

            frag = None
            if clean_fid in existing_frags:
                frag = existing_frags[clean_fid]
            elif "frag-{0}".format(clean_fid) in existing_frags:
                frag = existing_frags["frag-{0}".format(clean_fid)]
            elif clean_fid.startswith("frag-") and clean_fid[5:] in existing_frags:
                frag = existing_frags[clean_fid[5:]]

            if not frag:
                raise AdapterError(
                    "PPT_TEMPLATE_PAGE_INVALID_SOURCE",
                    "模型引用的出处片段编号不存在（编号：{0}）。".format(clean_fid),
                    status_code=502,
                )

            chap = chapters.get((frag.get("materialId", ""), frag.get("blockId")), frag.get("heading") or "正文")
            sources.append({
                "sourceId": frag.get("fragmentId", clean_fid),
                "sourceType": "material",
                "materialId": frag.get("materialId", ""),
                "fileName": frag.get("fileName", "参考资料"),
                "chapter": chap,
                "text": frag.get("text", ""),
            })

        capacity = evaluate_template_page_capacity(key_points)

        result = {
            "schemaVersion": "ppt.template_page.v1",
            "pageIndex": page_index,
            "pageRole": page_role,
            "title": title,
            "keyPoints": key_points,
            "speakerNotes": speaker_notes,
            "fragmentIds": fids,
            "sources": sources,
            "missingItems": missing_items,
            "estimatedLines": capacity["estimated_lines"],
            "totalCharacters": capacity["total_characters"],
            "isOverflow": capacity["is_overflow"],
            "basisMaterials": basis_materials,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        check_cancel()
        return result


ppt_template_page_coordinator = PptTemplatePageCoordinator()
