import json
import re
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
    # Estimate wrapped lines in a 11.5" container (~36 Chinese chars per line at 18-20pt)
    estimated_lines = sum(max(1, (len(p) + 35) // 36) for p in points)
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
        self._lock = threading.Lock()
        self._jobs: Dict[str, dict] = {}
        self._client_job_map: Dict[str, str] = {}
        self._active_sessions: Dict[str, str] = {}

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

        page_index = int(payload.get("pageIndex") or payload.get("page_index") or 1)
        page_role = str(payload.get("pageRole") or payload.get("page_role") or "content").strip()
        outline_title = str(payload.get("outlineTitle") or payload.get("outline_title") or "").strip()
        outline_key_points = payload.get("outlineKeyPoints") or payload.get("outline_key_points") or []
        if isinstance(outline_key_points, str):
            outline_key_points = [p.strip() for p in outline_key_points.split("\n") if p.strip()]
        outline_fragment_ids = payload.get("outlineFragmentIds") or payload.get("outline_fragment_ids") or []
        instruction = str(payload.get("instruction") or "").strip()
        user_facts = str(payload.get("userFacts") or payload.get("user_facts") or "").strip()

        with self._lock:
            existing_job_id = self._client_job_map.get((session_id, client_job_id))
            if existing_job_id and existing_job_id in self._jobs:
                existing_job = self._jobs[existing_job_id]
                if existing_job.get("requestPayload") == payload:
                    return deepcopy(existing_job)
                raise AdapterError(
                    "PPT_TEMPLATE_PAGE_JOB_CONFLICT",
                    "同一任务编号已用于不同请求，请使用新编号重试。",
                    status_code=409,
                )

            active_job_id = self._active_sessions.get(session_id)
            if active_job_id:
                active_job = self._jobs.get(active_job_id)
                if active_job and active_job.get("status") in ("queued", "running"):
                    return deepcopy(active_job)

            job_id = "ppt_tp_{0}".format(secrets.token_hex(12))
            job = {
                "jobId": job_id,
                "clientJobId": client_job_id,
                "taskType": TASK_TYPE,
                "documentSessionId": session_id,
                "traceId": trace_id or job_id,
                "status": "queued",
                "phase": "queued",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "result": None,
                "error": None,
                "requestPayload": payload,
            }
            self._jobs[job_id] = job
            self._client_job_map[(session_id, client_job_id)] = job_id
            self._active_sessions[session_id] = job_id

        # Execute job
        self._execute_job(
            job_id,
            session_id,
            page_index,
            page_role,
            outline_title,
            outline_key_points,
            outline_fragment_ids,
            instruction,
            user_facts,
        )
        return deepcopy(self._jobs[job_id])

    def get_job(self, job_id: str, document_session_id: str = "") -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise AdapterError("PPT_TEMPLATE_PAGE_NOT_FOUND", "任务不存在或已过期。", status_code=404)
            if document_session_id and job.get("documentSessionId") != document_session_id:
                raise AdapterError("PPT_TEMPLATE_PAGE_SESSION_MISMATCH", "会话不匹配。", status_code=403)
            return deepcopy(job)

    def cancel_job(self, job_id: str, document_session_id: str = "") -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise AdapterError("PPT_TEMPLATE_PAGE_NOT_FOUND", "任务不存在或已过期。", status_code=404)
            if document_session_id and job.get("documentSessionId") != document_session_id:
                raise AdapterError("PPT_TEMPLATE_PAGE_SESSION_MISMATCH", "会话不匹配。", status_code=403)
            if job["status"] in ("queued", "running"):
                job["status"] = "cancelled"
                job["phase"] = "cancelled"
                job["cancelledAt"] = datetime.now(timezone.utc).isoformat()
            if self._active_sessions.get(job["documentSessionId"]) == job_id:
                self._active_sessions.pop(job["documentSessionId"], None)
            return deepcopy(job)

    def _execute_job(
        self,
        job_id: str,
        session_id: str,
        page_index: int,
        page_role: str,
        outline_title: str,
        outline_key_points: List[str],
        outline_fragment_ids: List[int],
        instruction: str,
        user_facts: str,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"
        job["phase"] = "preparing"

        try:
            with self.store._lock:
                catalog = self.store.get_catalog(session_id)
                basis_materials = [
                    {
                        "materialId": doc.get("materialId", ""),
                        "fileName": doc.get("fileName", "参考资料"),
                        "updatedAt": doc.get("updatedAt", ""),
                    }
                    for doc in catalog.get("documents", [])
                ]

            job["phase"] = "provider_processing"
            prompt_item = SystemPromptStore().load(TASK_TYPE)
            system_prompt = prompt_item["content"]

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

            response = self.provider.post_task(
                TASK_TYPE,
                system_prompt=system_prompt,
                user_prompt=user_content,
            )
            raw_answer = extract_answer(response)

            job["phase"] = "parsing"
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

            job["status"] = "completed"
            job["phase"] = "completed"
            job["result"] = result
            job["completedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            job["status"] = "failed"
            job["phase"] = "failed"
            err_code = getattr(e, "code", "PPT_TEMPLATE_PAGE_FAILED")
            err_msg = getattr(e, "message", str(e))
            job["error"] = {"code": err_code, "message": err_msg}

        finally:
            with self._lock:
                if self._active_sessions.get(session_id) == job_id:
                    self._active_sessions.pop(session_id, None)


ppt_template_page_coordinator = PptTemplatePageCoordinator()
