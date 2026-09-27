import json
import re
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.errors import AdapterError
from app.services.excel.material_store import ExcelMaterialStore
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

TASK_TYPE = "excel.material_ledger"
CLIENT_JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
DEFAULT_HEADERS = ["工作事项", "责任部门", "完成时间", "交付物验收"]
MAX_REQUEST_BYTES = 64 * 1024


def _fragment_chapters(catalog: dict) -> dict:
    chapters = {}
    current = {}
    for block in catalog.get("blocks", []):
        material_id = block.get("materialId", "")
        if block.get("kind") == "heading":
            current[material_id] = block.get("text") or "正文"
        chapters[(material_id, block.get("blockId"))] = current.get(material_id, "正文")
    return chapters


class ExcelMaterialLedgerCoordinator:
    def __init__(
        self,
        store: Optional[ExcelMaterialStore] = None,
        provider: Optional[ProviderClient] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.store = store or ExcelMaterialStore()
        self.provider = provider or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._lock = threading.Lock()

    def submit_job(self, payload: dict, trace_id: str = "") -> dict:
        if not isinstance(payload, dict):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "请求参数无效。", status_code=422)

        session_id = str(
            payload.get("documentSessionId") or payload.get("document_session_id") or ""
        ).strip()
        if not session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效文档会话编号。", status_code=422)

        client_job_id = str(
            payload.get("clientJobId") or payload.get("client_job_id") or ""
        ).strip()
        if not client_job_id:
            client_job_id = "job_{0}".format(secrets.token_hex(16))
        elif not CLIENT_JOB_ID_PATTERN.match(client_job_id):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "任务编号格式无效。", status_code=422)

        raw_headers = payload.get("headers")
        if raw_headers is None:
            headers = list(DEFAULT_HEADERS)
        elif isinstance(raw_headers, list) and raw_headers and all(isinstance(h, str) and h.strip() for h in raw_headers):
            headers = [h.strip() for h in raw_headers]
        else:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "表头必须为包含有效字段名称的非空数组。", status_code=422)

        instruction = str(payload.get("instruction") or "").strip()
        user_facts = str(payload.get("userFacts") or payload.get("user_facts") or "").strip()
        conflict_resolutions = payload.get("conflictResolutions") or payload.get("conflict_resolutions") or []
        if not isinstance(conflict_resolutions, list):
            raise AdapterError("REQUEST_VALIDATION_FAILED", "冲突选择格式无效。", status_code=422)

        request_repr = {
            "documentSessionId": session_id,
            "clientJobId": client_job_id,
            "headers": headers,
            "instruction": instruction,
            "userFacts": user_facts,
            "conflictResolutions": conflict_resolutions,
        }
        fingerprint = json.dumps(request_repr, ensure_ascii=False, sort_keys=True)

        with self._lock, self.store._lock:
            existing = self.coordinator.get(client_job_id, task_type=TASK_TYPE)
            if existing:
                if self.coordinator.get_request_fingerprint(client_job_id, task_type=TASK_TYPE) != fingerprint:
                    raise AdapterError("MATERIAL_LEDGER_JOB_CONFLICT", "任务编号已绑定其他请求。", status_code=409)
                return existing

            self.store._check_busy(session_id)
            catalog = self.store.get_catalog(session_id)
            if not catalog.get("documents"):
                raise AdapterError("MATERIAL_NOT_FOUND", "当前工作簿尚未导入或复用参考资料，请先添加资料。", status_code=400)
            conflicts = detect_material_conflicts(catalog, user_facts=user_facts)
            normalized_choices = []
            for conflict in conflicts:
                choices = [choice for choice in conflict_resolutions
                           if isinstance(choice, dict) and choice.get("conflictId") == conflict["conflictId"]]
                if len(choices) != 1:
                    raise AdapterError("MATERIAL_LEDGER_CONFLICT_UNRESOLVED", "资料存在事实差异，请先核对并选择依据。", status_code=409)
                choice = choices[0]
                candidates = [option for option in conflict["options"]
                              if option["optionId"] == choice.get("chosenCandidateId")
                              and option["value"] == choice.get("chosenValue")]
                if len(candidates) != 1:
                    raise AdapterError("REQUEST_VALIDATION_FAILED", "冲突选择已失效，请重新核对。", status_code=422)
                option = candidates[0]
                normalized_choices.append(dict(conflictId=conflict["conflictId"], topic=conflict["topic"],
                                               chosenCandidateId=option["optionId"], chosenValue=option["value"],
                                               sourceId=option["sourceId"], sourceType=option["sourceType"]))
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
                "headers": headers,
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
                failure_code="MATERIAL_LEDGER_FAILED",
                failure_message="从资料生成任务台账失败，请检查模型结果或资料内容。",
                public_metadata={"documentSessionId": session_id, "streamingEnabled": False},
                safe_failure_codes={
                    "MATERIAL_NOT_FOUND",
                    "MATERIAL_LEDGER_INVALID_SOURCE",
                    "MATERIAL_LEDGER_INVALID_SCHEMA",
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
            raise AdapterError("MODEL_CONFIG_INCOMPLETE", "任务台账尚未配置模型，请前往设置。", status_code=400)
        body = self.provider.post_task(
            TASK_TYPE, trace_id, {}, system_prompt + "\n" + user_content,
            task_auth=auth, progress_callback=progress,
        )
        return extract_answer(body)

    def _build_user_prompt(
        self,
        headers: List[str],
        instruction: str,
        user_facts: str,
        conflict_resolutions: list,
        fragments: list,
    ) -> str:
        prompt_parts = [
            "【表头字段】\n{0}".format(", ".join(headers)),
        ]
        if instruction:
            prompt_parts.append("【提取要求】\n{0}".format(instruction))
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

        headers = snapshot["headers"]
        instruction = snapshot.get("instruction", "")
        user_facts = snapshot.get("userFacts", "")
        conflict_resolutions = snapshot.get("conflictResolutions", [])
        catalog = snapshot["catalog"]
        system_prompt = snapshot["systemPrompt"]

        # Select fragments
        raw_fragments = catalog.get("fragmentsList")
        if raw_fragments is None:
            raw_frags = catalog.get("fragments", {})
            raw_fragments = list(raw_frags.values()) if isinstance(raw_frags, dict) else raw_frags
        chapters = _fragment_chapters(catalog)
        fragments = [dict(fragment, chapter=chapters.get((fragment.get("materialId", ""), fragment.get("blockId")), "正文"))
                     for fragment in raw_fragments or []]

        user_content = self._build_user_prompt(
            headers=headers,
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
        raw_response = self._call_provider_model(system_prompt, user_content,
                                                 task_auth=auth, trace_id=snapshot["traceId"], progress=progress)

        check_cancel()
        progress("parsing")
        validated_result = self._parse_and_validate_ledger(raw_response, headers, catalog, user_facts=user_facts)
        return validated_result

    def _parse_and_validate_ledger(self, raw_response: str, headers: List[str], catalog: dict, user_facts: str = "") -> dict:
        try:
            payload = _extract_json_payload(raw_response)
        except Exception as e:
            raise AdapterError(
                "MATERIAL_LEDGER_INVALID_SCHEMA",
                "模型输出格式非有效JSON，无法提取任务台账。",
                status_code=502,
            ) from e

        if not isinstance(payload, dict):
            raise AdapterError(
                "MATERIAL_LEDGER_INVALID_SCHEMA",
                "模型输出顶层非对象结构。",
                status_code=502,
            )

        if payload.get("schemaVersion") != "excel.material_ledger.v1":
            raise AdapterError(
                "MATERIAL_LEDGER_INVALID_SCHEMA",
                "模型输出版本不匹配，预期 excel.material_ledger.v1。",
                status_code=502,
            )

        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, list):
            raise AdapterError(
                "MATERIAL_LEDGER_INVALID_SCHEMA",
                "模型输出缺少 rows 数组。",
                status_code=502,
            )

        existing_frags = catalog.get("fragments") or {}
        if not isinstance(existing_frags, dict):
            existing_frags = {str(f.get("fragmentId")): f for f in catalog.get("fragmentsList", [])}

        chapters = _fragment_chapters(catalog)
        _, user_fact_map = parse_user_facts(user_facts)
        validated_rows = []
        for idx, row in enumerate(raw_rows):
            if not isinstance(row, dict):
                continue
            raw_values = row.get("values") or {}
            values = {}
            missing_fields = []
            for h in headers:
                val = raw_values.get(h)
                if val is None or not str(val).strip():
                    values[h] = ""
                    missing_fields.append(h)
                else:
                    values[h] = str(val).strip()

            is_duplicate = bool(row.get("isDuplicate", False))
            duplicate_of = row.get("duplicateOfIndex")
            duplicate_reason = str(row.get("duplicateReason") or "").strip()
            if not is_duplicate:
                duplicate_of = None
                duplicate_reason = ""
            elif duplicate_of is not None:
                try:
                    duplicate_of = int(duplicate_of)
                except Exception:
                    duplicate_of = None

            raw_fids = row.get("fragmentIds") or []
            if not isinstance(raw_fids, list):
                raw_fids = []

            if not raw_fids:
                raise AdapterError("MATERIAL_LEDGER_INVALID_SOURCE", "任务行没有真实出处，无法核验。", status_code=502)
            sources = []
            for fid in raw_fids:
                fid_str = str(fid)
                if fid_str in user_fact_map:
                    sources.append({
                        "sourceId": fid_str,
                        "sourceType": "user",
                        "fileName": "用户补充事实",
                        "chapter": "补充事实",
                        "text": user_fact_map[fid_str],
                    })
                    continue

                frag = None
                if fid_str in existing_frags:
                    frag = existing_frags[fid_str]
                elif f"frag-{fid_str}" in existing_frags:
                    frag = existing_frags[f"frag-{fid_str}"]
                elif fid_str.startswith("frag-") and fid_str[5:] in existing_frags:
                    frag = existing_frags[fid_str[5:]]

                if not frag:
                    raise AdapterError(
                        "MATERIAL_LEDGER_INVALID_SOURCE",
                        f"引用的片段编号 {fid} 不存在于资料库中，无法核验真实出处。",
                        status_code=502,
                    )
                sources.append({
                    "fragmentId": fid,
                    "materialId": frag.get("materialId", ""),
                    "fileName": frag.get("fileName", "参考资料"),
                    "chapter": chapters.get((frag.get("materialId", ""), frag.get("blockId")), frag.get("heading") or frag.get("chapter") or "正文"),
                    "text": frag.get("text", ""),
                })

            validated_rows.append({
                "rowIndex": idx,
                "values": values,
                "missingFields": missing_fields,
                "isDuplicate": is_duplicate,
                "duplicateOfIndex": duplicate_of,
                "duplicateReason": duplicate_reason,
                "fragmentIds": raw_fids,
                "sources": sources,
            })

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        basis_materials = [
            {
                "materialId": d["materialId"],
                "fileName": d["fileName"],
                "updatedAt": d.get("updatedAt", d.get("importedAt", "")),
            }
            for d in catalog.get("documents", [])
            if "materialId" in d
        ]

        return {
            "schemaVersion": "excel.material_ledger.v1",
            "headers": headers,
            "rows": validated_rows,
            "basisMaterials": basis_materials,
            "generatedAt": now_iso,
            "totalRows": len(validated_rows),
            "duplicateCount": sum(1 for r in validated_rows if r.get("isDuplicate")),
            "missingCount": sum(len(r.get("missingFields", [])) for r in validated_rows),
        }

    def query_job(self, job_id: str, document_session_id: str) -> dict:
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if not job or not document_session_id or job.get("documentSessionId") != document_session_id:
            raise AdapterError("MATERIAL_LEDGER_JOB_NOT_FOUND", "当前工作簿会话没有该任务。", status_code=404)
        return job

    def wait_job(self, job_id: str, document_session_id: str) -> dict:
        self.query_job(job_id, document_session_id)
        return self.coordinator.wait(job_id, task_type=TASK_TYPE)

    def cancel_job(self, job_id: str, document_session_id: str) -> dict:
        self.query_job(job_id, document_session_id)
        return self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)

    def detect_conflicts(self, document_session_id: str, user_facts: str = "") -> list:
        if not document_session_id:
            raise AdapterError("REQUEST_VALIDATION_FAILED", "缺少有效文档会话编号。", status_code=422)
        catalog = self.store.get_catalog(document_session_id)
        if not catalog or not catalog.get("documents"):
            return []
        return detect_material_conflicts(catalog, user_facts=user_facts)
