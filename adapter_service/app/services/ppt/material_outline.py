import json
import re
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
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
    detect_material_conflicts,
    parse_user_facts,
)

TASK_TYPE = "ppt.material_outline"
CLIENT_JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
DEFAULT_AUDIENCE = "公司高管与业务领导"
DEFAULT_SLIDE_COUNT = 8
MIN_SLIDE_COUNT = 3
MAX_SLIDE_COUNT = 30
MAX_REQUEST_BYTES = 64 * 1024

VALID_PAGE_ROLES = {
    "cover",
    "agenda",
    "transition",
    "content",
    "summary",
    "backcover",
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


class PptMaterialOutlineCoordinator:
    def __init__(
        self,
        store: Optional[PptMaterialStore] = None,
        provider: Optional[ProviderClient] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.store = store or PptMaterialStore()
        self.provider = provider or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.Lock()

    def detect_conflicts(self, document_session_id: str, user_facts: str = "") -> List[dict]:
        with self._lock, self.store._lock:
            catalog = self.store.get_catalog(document_session_id)
            return detect_material_conflicts(catalog, user_facts=user_facts)

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

        audience = str(payload.get("audience") or "").strip()
        if not audience:
            audience = DEFAULT_AUDIENCE

        raw_slide_count = payload.get("slideCount") or payload.get("slide_count")
        if raw_slide_count is None:
            slide_count = DEFAULT_SLIDE_COUNT
        else:
            try:
                slide_count = int(raw_slide_count)
            except (ValueError, TypeError):
                raise AdapterError("REQUEST_VALIDATION_FAILED", "页数必须为整数。", status_code=422)
            if slide_count < MIN_SLIDE_COUNT or slide_count > MAX_SLIDE_COUNT:
                raise AdapterError(
                    "REQUEST_VALIDATION_FAILED",
                    "预定页数超出合理范围（{0}~{1}页）。".format(MIN_SLIDE_COUNT, MAX_SLIDE_COUNT),
                    status_code=422,
                )

        instruction = str(payload.get("instruction") or "").strip()
        user_facts = str(payload.get("userFacts") or payload.get("user_facts") or "").strip()
        conflict_resolutions = payload.get("conflictResolutions") or payload.get("conflict_resolutions") or []
        if not isinstance(conflict_resolutions, list):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "冲突选择格式无效。", status_code=422)

        request_repr = {
            "documentSessionId": session_id,
            "clientJobId": client_job_id,
            "audience": audience,
            "slideCount": slide_count,
            "instruction": instruction,
            "userFacts": user_facts,
            "conflictResolutions": conflict_resolutions,
        }
        fingerprint = json.dumps(request_repr, ensure_ascii=False, sort_keys=True)

        with self._lock, self.store._lock:
            existing = self.coordinator.get(client_job_id, task_type=TASK_TYPE)
            if existing:
                if self.coordinator.get_request_fingerprint(client_job_id, task_type=TASK_TYPE) != fingerprint:
                    raise AdapterError("MATERIAL_OUTLINE_JOB_CONFLICT", "任务编号已绑定其他请求。", status_code=409)
                return existing

            self.store._check_busy(session_id)
            catalog = self.store.get_catalog(session_id)
            if not catalog.get("documents"):
                raise AdapterError("MATERIAL_NOT_FOUND", "当前演示文稿尚未导入或复用参考资料，请先添加资料。", status_code=400)

            conflicts = detect_material_conflicts(catalog, user_facts=user_facts)
            normalized_choices = []
            for conflict in conflicts:
                choices = [choice for choice in conflict_resolutions
                           if isinstance(choice, dict) and choice.get("conflictId") == conflict["conflictId"]]
                if len(choices) != 1:
                    raise AdapterError("MATERIAL_OUTLINE_CONFLICT_UNRESOLVED", "资料存在事实差异，请先核对并选择依据。", status_code=409)
                choice = choices[0]
                candidates = [option for option in conflict["options"]
                              if option["optionId"] == choice.get("chosenCandidateId")
                              and option["value"] == choice.get("chosenValue")]
                if len(candidates) != 1:
                    raise AdapterError("REQUEST_VALIDATION_FAILED", "冲突选择已失效，请重新核对。", status_code=422)
                option = candidates[0]
                normalized_choices.append(dict(
                    conflictId=conflict["conflictId"],
                    topic=conflict["topic"],
                    chosenCandidateId=option["optionId"],
                    chosenValue=option["value"],
                    sourceId=option["sourceId"],
                    sourceType=option["sourceType"],
                ))
            if len(normalized_choices) != len(conflict_resolutions):
                raise AdapterError("REQUEST_VALIDATION_FAILED", "冲突选择已失效，请重新核对。", status_code=422)
            conflict_resolutions = normalized_choices

            system_prompt_asset = SystemPromptStore().load(TASK_TYPE)
            system_prompt = system_prompt_asset["content"]

            auth = self.provider.resolve_task_auth(TASK_TYPE)

            snapshot = {
                "request": request_repr,
                "catalog": deepcopy(catalog),
                "systemPrompt": system_prompt,
                "audience": audience,
                "slideCount": slide_count,
                "instruction": instruction,
                "userFacts": user_facts,
                "conflictResolutions": conflict_resolutions,
                "traceId": trace_id or client_job_id,
                "taskAuth": deepcopy(auth),
            }

            return self.coordinator.submit(
                job_id=client_job_id,
                trace_id=trace_id or client_job_id,
                task_type=TASK_TYPE,
                runner=self._run_job,
                snapshot=snapshot,
                request_fingerprint=fingerprint,
                failure_code="MATERIAL_OUTLINE_FAILED",
                failure_message="根据资料生成逐页大纲失败，请检查模型结果或资料内容。",
                public_metadata={"documentSessionId": session_id, "streamingEnabled": False},
                safe_failure_codes={
                    "MATERIAL_NOT_FOUND",
                    "MATERIAL_OUTLINE_INVALID_SOURCE",
                    "MATERIAL_OUTLINE_INVALID_SCHEMA",
                    "MODEL_INPUT_OVER_BUDGET",
                    "PROVIDER_TIMEOUT",
                },
                priority_class=PRIORITY_INTERACTIVE,
                allow_running_cancel=True,
            )

    def _call_provider_model(self, system_prompt: str, user_content: str,
                             task_auth=None, trace_id: str = "", progress=None) -> str:
        auth = task_auth if task_auth is not None else self.provider.resolve_task_auth(TASK_TYPE)
        if not auth.get("providerBaseUrl") or not auth.get("apiKey"):
            raise AdapterError("MODEL_CONFIG_INCOMPLETE", "逐页大纲任务尚未配置模型，请前往设置。", status_code=400)
        body = self.provider.post_task(
            task_type=TASK_TYPE,
            system_prompt=system_prompt,
            user_content=user_content,
            trace_id=trace_id,
            progress=progress,
            task_auth=auth,
        )
        return extract_answer(body)

    def _build_user_prompt(
        self,
        audience: str,
        slide_count: int,
        instruction: str,
        user_facts: str,
        conflict_resolutions: list,
        fragments: list,
    ) -> str:
        prompt_parts = [
            "【任务要求】",
            "- 汇报对象：{0}".format(audience),
            "- 预定页数：{0} 页（必须严格输出 {0} 页大纲，不多不少）".format(slide_count),
        ]
        if instruction:
            prompt_parts.append("- 重点要求：{0}".format(instruction))
        if user_facts:
            prompt_parts.append("【用户补充事实】\n{0}".format(json.dumps(parse_user_facts(user_facts)[0], ensure_ascii=False)))
        if conflict_resolutions:
            prompt_parts.append("【事实冲突裁决】\n{0}".format(json.dumps(conflict_resolutions, ensure_ascii=False)))

        fragments_repr = []
        for f in fragments:
            fid = f.get("fragmentId")
            fname = f.get("fileName", "资料")
            fhead = f.get("heading") or f.get("chapter") or "正文"
            ftext = f.get("text", "")
            fragments_repr.append("[片段编号 {0}] 《{1}》- {2}：\n{3}".format(fid, fname, fhead, ftext))

        prompt_parts.append("【参考资料片段】\n" + "\n\n".join(fragments_repr))
        return "\n\n".join(prompt_parts)

    def _run_job(self, snapshot: dict, progress) -> dict:
        def check_cancel():
            if hasattr(progress, "cancel_requested") and progress.cancel_requested():
                raise LongTaskCancelled()

        check_cancel()
        progress("preparing")

        audience = snapshot["audience"]
        slide_count = snapshot["slideCount"]
        instruction = snapshot.get("instruction", "")
        user_facts = snapshot.get("userFacts", "")
        conflict_resolutions = snapshot.get("conflictResolutions", [])
        catalog = snapshot["catalog"]
        system_prompt = snapshot["systemPrompt"]

        raw_fragments = catalog.get("fragmentsList")
        if raw_fragments is None:
            raw_frags = catalog.get("fragments", {})
            raw_fragments = list(raw_frags.values()) if isinstance(raw_frags, dict) else raw_frags
        chapters = _fragment_chapters(catalog)
        fragments = [
            dict(fragment, chapter=chapters.get((fragment.get("materialId", ""), fragment.get("blockId")), "正文"))
            for fragment in raw_fragments or []
        ]

        user_content = self._build_user_prompt(
            audience=audience,
            slide_count=slide_count,
            instruction=instruction,
            user_facts=user_facts,
            conflict_resolutions=conflict_resolutions,
            fragments=fragments,
        )

        auth = snapshot["taskAuth"]
        budget, _ = direct_model_input_budget(
            int(auth.get("contextWindowTokens") or DEFAULT_CONTEXT_WINDOW_TOKENS),
            int(auth.get("maxOutputTokens") or DEFAULT_RESERVED_OUTPUT_TOKENS),
        )
        if _estimate_direct_tokens(system_prompt, system_prompt + "\n" + user_content) > budget:
            raise AdapterError("MODEL_INPUT_OVER_BUDGET", "资料超过单次模型预算，请缩小资料范围；未截断资料。", status_code=413)

        check_cancel()
        progress("provider_processing")
        raw_response = self._call_provider_model(
            system_prompt,
            user_content,
            task_auth=auth,
            trace_id=snapshot["traceId"],
            progress=progress,
        )

        check_cancel()
        progress("parsing")
        validated_result = self._parse_and_validate_outline(
            raw_response,
            expected_audience=audience,
            expected_slide_count=slide_count,
            expected_instruction=instruction,
            catalog=catalog,
            user_facts=user_facts,
        )
        return validated_result

    def _parse_and_validate_outline(
        self,
        raw_response: str,
        expected_audience: str,
        expected_slide_count: int,
        expected_instruction: str,
        catalog: dict,
        user_facts: str = "",
    ) -> dict:
        try:
            payload = _extract_json_payload(raw_response)
        except Exception as e:
            raise AdapterError(
                "MATERIAL_OUTLINE_INVALID_SCHEMA",
                "模型输出格式非有效 JSON，无法提取演示大纲。",
                status_code=502,
            ) from e

        if not isinstance(payload, dict):
            raise AdapterError(
                "MATERIAL_OUTLINE_INVALID_SCHEMA",
                "模型输出顶层非对象结构。",
                status_code=502,
            )

        if payload.get("schemaVersion") != "ppt.material_outline.v1":
            raise AdapterError(
                "MATERIAL_OUTLINE_INVALID_SCHEMA",
                "模型输出版本不匹配，预期 ppt.material_outline.v1。",
                status_code=502,
            )

        raw_slides = payload.get("slides")
        if not isinstance(raw_slides, list):
            raise AdapterError(
                "MATERIAL_OUTLINE_INVALID_SCHEMA",
                "模型输出缺少 slides 数组。",
                status_code=502,
            )

        if len(raw_slides) != expected_slide_count:
            raise AdapterError(
                "MATERIAL_OUTLINE_INVALID_SCHEMA",
                "模型输出页数不匹配，预期 {0} 页，实际返回 {1} 页。".format(expected_slide_count, len(raw_slides)),
                status_code=502,
            )

        existing_frags = catalog.get("fragments") or {}
        if not isinstance(existing_frags, dict):
            existing_frags = {str(f.get("fragmentId")): f for f in catalog.get("fragmentsList", [])}

        chapters = _fragment_chapters(catalog)
        validated_slides = []
        user_facts_items = parse_user_facts(user_facts)[0] if user_facts else []

        for idx, slide in enumerate(raw_slides):
            if not isinstance(slide, dict):
                raise AdapterError(
                    "MATERIAL_OUTLINE_INVALID_SCHEMA",
                    "第 {0} 页大纲数据非对象结构。".format(idx + 1),
                    status_code=502,
                )

            page_role = str(slide.get("pageRole") or "content").strip().lower()
            if page_role not in VALID_PAGE_ROLES:
                page_role = "content"

            title = str(slide.get("title") or "").strip()
            if not title:
                title = "第 {0} 页".format(idx + 1)

            raw_points = slide.get("keyPoints") or []
            if isinstance(raw_points, list):
                key_points = [str(p).strip() for p in raw_points if str(p).strip()]
            else:
                key_points = [str(raw_points).strip()] if str(raw_points).strip() else []

            raw_missing = slide.get("missingItems") or []
            if isinstance(raw_missing, list):
                missing_items = [str(m).strip() for m in raw_missing if str(m).strip()]
            else:
                missing_items = [str(raw_missing).strip()] if str(raw_missing).strip() else []

            fids = slide.get("fragmentIds") or []
            if not isinstance(fids, list):
                fids = [fids] if fids else []

            sources = []
            normalized_fids = []
            for fid in fids:
                if str(fid).lower() in ("user", "user-fact", "user_fact"):
                    if user_facts_items:
                        for uf in user_facts_items:
                            sources.append({
                                "sourceId": "user",
                                "sourceType": "user",
                                "fileName": "用户补充事实",
                                "chapter": "用户补充",
                                "text": uf.get("text", ""),
                            })
                    normalized_fids.append("user-fact")
                    continue

                clean_fid = str(fid).strip()
                frag = None
                if clean_fid in existing_frags:
                    frag = existing_frags[clean_fid]
                elif "frag-{0}".format(clean_fid) in existing_frags:
                    frag = existing_frags["frag-{0}".format(clean_fid)]
                elif clean_fid.startswith("frag-") and clean_fid[5:] in existing_frags:
                    frag = existing_frags[clean_fid[5:]]

                if not frag:
                    raise AdapterError(
                        "MATERIAL_OUTLINE_INVALID_SOURCE",
                        "模型引用的出处片段编号不存在（编号：{0}）。".format(clean_fid),
                        status_code=502,
                    )

                chap = chapters.get((frag.get("materialId", ""), frag.get("blockId")), frag.get("heading") or frag.get("chapter") or "正文")
                sources.append({
                    "sourceId": frag.get("fragmentId", clean_fid),
                    "sourceType": "material",
                    "materialId": frag.get("materialId", ""),
                    "fileName": frag.get("fileName", "参考资料"),
                    "chapter": chap,
                    "text": frag.get("text", ""),
                })
                normalized_fids.append(fid)

            validated_slides.append({
                "pageIndex": idx + 1,
                "pageRole": page_role,
                "title": title,
                "keyPoints": key_points,
                "missingItems": missing_items,
                "fragmentIds": normalized_fids,
                "sources": sources,
            })

        basis_materials = [
            {
                "materialId": d.get("materialId"),
                "fileName": d.get("fileName"),
                "updatedAt": d.get("updatedAt", ""),
            }
            for d in catalog.get("documents", [])
        ]

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "schemaVersion": "ppt.material_outline.v1",
            "audience": expected_audience,
            "slideCount": expected_slide_count,
            "instruction": expected_instruction,
            "slides": validated_slides,
            "basisMaterials": basis_materials,
            "generatedAt": now_iso,
        }

    def query_job(self, job_id: str, document_session_id: str = "") -> dict:
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if not job or (document_session_id and job.get("documentSessionId") != document_session_id):
            raise AdapterError("MATERIAL_OUTLINE_JOB_NOT_FOUND", "当前演示文稿会话没有该任务。", status_code=404)
        return job

    def wait_job(self, job_id: str, document_session_id: str = "") -> dict:
        self.query_job(job_id, document_session_id)
        return self.coordinator.wait(job_id, task_type=TASK_TYPE)

    def cancel_job(self, job_id: str, document_session_id: str = "") -> dict:
        self.query_job(job_id, document_session_id)
        return self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)


ppt_material_outline = PptMaterialOutlineCoordinator()
