import os
import re
import threading
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelFormulaAssistantRequest
from app.services.excel.formula_assistant import ExcelFormulaAssistant
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import EXCEL_FORMULA_ASSISTANT_TIMEOUT_SECONDS
from app.services.task_history import TaskHistoryError, get_task_history_store


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理公式任务，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_FORMULA_REQUIREMENT_REQUIRED": 400,
    "EXCEL_FORMULA_SELECTION_REQUIRED": 400,
    "EXCEL_FORMULA_SELECTION_TOO_LARGE": 400,
    "EXCEL_FORMULA_TO_EXPLAIN_REQUIRED": 400,
    "EXCEL_FORMULA_DOCUMENT_TASK_BUSY": 409,
    "PROVIDER_AUTH_FAILED": 401,
    "PROVIDER_UNREACHABLE": 502,
    "PROVIDER_TIMEOUT": 504,
    "DIFY_AUTH_FAILED": 401,
    "DIFY_UNREACHABLE": 502,
    "DIFY_TIMEOUT": 504,
}


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


class ExcelFormulaAssistantJobStore:
    def __init__(
        self,
        assistant: Optional[ExcelFormulaAssistant] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.assistant = assistant or ExcelFormulaAssistant()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions: Dict[tuple, str] = {}

    def start(self, request: ExcelFormulaAssistantRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        doc_session = str(getattr(request, "document_session_id", "") or "").strip()
        host = str(getattr(request, "host", "") or "et").strip()
        raw_doc_name = str(
            getattr(request, "document_display_name", "")
            or getattr(request, "workbook_id", "")
            or "工作簿.xlsx"
        ).strip()
        doc_name = os.path.basename(raw_doc_name) or "工作簿.xlsx"
        task_type = "excel.formula_assistant"

        with self._submission_lock:
            existing = self.coordinator.get(
                job_id, task_type=task_type
            )
            if existing is not None:
                return existing

            if doc_session:
                slot_key = (host, task_type, doc_session)
                active_job_id = self._active_doc_sessions.get(slot_key)
                if active_job_id:
                    active_job = self.coordinator.get(active_job_id, task_type=task_type)
                    if active_job and active_job.get("status") in {"queued", "running"}:
                        if active_job_id != job_id:
                            raise AdapterError(
                                "EXCEL_FORMULA_DOCUMENT_TASK_BUSY",
                                "当前工作簿已存在进行中的公式助手任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            snapshot_task_auth = getattr(self.assistant, "snapshot_task_auth", None)
            task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
            submitted = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=task_type,
                runner=self._run,
                success_committer=self._commit_success,
                snapshot={
                    "request": request,
                    "taskAuth": task_auth,
                    "jobId": job_id,
                    "traceId": trace_id,
                    "host": host,
                    "documentSessionId": doc_session,
                    "documentDisplayName": doc_name,
                },
                failure_code="EXCEL_FORMULA_JOB_FAILED",
                failure_message="公式助手后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
                public_metadata={
                    "runningMessage": RUNNING_MESSAGE,
                    "providerTimeoutSeconds": EXCEL_FORMULA_ASSISTANT_TIMEOUT_SECONDS,
                },
                safe_failure_codes=set(SAFE_ERROR_STATUSES),
            )
            if doc_session:
                self._active_doc_sessions[(host, task_type, doc_session)] = job_id
            return submitted

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="excel.formula_assistant")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="excel.formula_assistant")

    def _run(self, snapshot: Dict, progress) -> Dict:
        doc_session = str(snapshot.get("documentSessionId") or "").strip()
        host = str(snapshot.get("host") or "et").strip()
        job_id = str(snapshot.get("jobId") or "").strip()
        try:
            kwargs = {"progress_callback": progress}
            if snapshot.get("taskAuth") is not None:
                kwargs["task_auth"] = snapshot["taskAuth"]
            result = self.assistant.generate(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                **kwargs
            )
            return result
        finally:
            if doc_session:
                with self._submission_lock:
                    slot_key = (host, "excel.formula_assistant", doc_session)
                    if self._active_doc_sessions.get(slot_key) == job_id:
                        self._active_doc_sessions.pop(slot_key, None)

    @staticmethod
    def _commit_success(snapshot: Dict, result: Dict) -> None:
        if result.get("parseDiagnostic"):
            result["historyNotice"] = "诊断降级结果未保存至历史记录。"
            return
        try:
            task_auth = snapshot.get("taskAuth") or {}
            service_name = str(task_auth.get("serviceName") or "").strip()
            model_name = str(task_auth.get("modelName") or "").strip()
            doc_name = str(snapshot.get("documentDisplayName") or "工作簿.xlsx").strip()
            primary_formula = str(result.get("primaryFormula") or "").strip()
            archived_result = {
                "mode": str(result.get("mode") or "generate"),
                "primaryFormula": primary_formula,
                "alternativeFormula": str(result.get("alternativeFormula") or ""),
                "suggestedTarget": str(result.get("suggestedTarget") or ""),
                "explanation": str(result.get("explanation") or ""),
                "components": list(result.get("components") or []),
                "referenceRanges": list(result.get("referenceRanges") or []),
                "issues": list(result.get("issues") or []),
                "assumptions": list(result.get("assumptions") or []),
                "compatibilityNotes": list(result.get("compatibilityNotes") or []),
                "copyText": primary_formula,
            }
            get_task_history_store().record_success(
                task_type="excel.formula_assistant",
                job_id=str(snapshot.get("jobId") or "").strip(),
                result=archived_result,
                document_display_name=doc_name,
                service_name=service_name,
                model_name=model_name,
            )
        except TaskHistoryError as exc:
            if exc.code == "HISTORY_ENTRY_TOO_LARGE":
                result["historyNotice"] = "任务结果超过 5 MiB，未写入历史记录。"
            else:
                result["historyNotice"] = "历史记录写入失败，未保存至历史列表。"
        except Exception:
            result["historyNotice"] = "历史记录写入失败，未保存至历史列表。"
