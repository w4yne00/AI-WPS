import os
import re
import threading
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelAnalysisRequest
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import EXCEL_ANALYSIS_TIMEOUT_SECONDS
from app.services.task_history import TaskHistoryError, get_task_history_store


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理智能分析，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_ANALYSIS_TABLE_REQUIRED": 400,
    "EXCEL_ANALYSIS_DOCUMENT_TASK_BUSY": 409,
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


class ExcelAnalysisJobStore:
    def __init__(
        self,
        analyzer: Optional[ExcelAnalyzer] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.analyzer = analyzer or ExcelAnalyzer()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions: Dict[tuple, str] = {}

    def start(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        doc_session = str(getattr(request, "document_session_id", "") or "").strip()
        host = str(getattr(request, "host", "") or "et").strip()
        raw_doc_name = str(
            getattr(request, "document_display_name", "")
            or getattr(request, "workbook_id", "")
            or "工作簿.xlsx"
        ).strip()
        doc_name = os.path.basename(raw_doc_name) or "工作簿.xlsx"
        task_type = "excel.analysis"

        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type=task_type)
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
                                "EXCEL_ANALYSIS_DOCUMENT_TASK_BUSY",
                                "当前工作簿已存在进行中的智能分析任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            snapshot_task_auth = getattr(self.analyzer, "snapshot_task_auth", None)
            task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
            submitted = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=task_type,
                runner=self._run,
                snapshot={
                    "request": request,
                    "taskAuth": task_auth,
                    "jobId": job_id,
                    "traceId": trace_id,
                    "host": host,
                    "documentSessionId": doc_session,
                    "documentDisplayName": doc_name,
                },
                failure_code="EXCEL_ANALYSIS_JOB_FAILED",
                failure_message="智能分析后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
                public_metadata={
                    "runningMessage": RUNNING_MESSAGE,
                    "providerTimeoutSeconds": EXCEL_ANALYSIS_TIMEOUT_SECONDS,
                },
                safe_failure_codes=set(SAFE_ERROR_STATUSES),
            )
            if doc_session:
                self._active_doc_sessions[(host, task_type, doc_session)] = job_id
            return submitted

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="excel.analysis")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="excel.analysis")

    def run_sync(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        job = self.start(request, trace_id)
        return self.coordinator.wait_result(
            job["jobId"],
            task_type="excel.analysis",
            not_found_code="EXCEL_ANALYSIS_JOB_NOT_FOUND",
            not_found_message="智能分析后台任务不存在或已过期。",
            cancelled_message="排队中的智能分析任务已取消。",
            failure_code="EXCEL_ANALYSIS_JOB_FAILED",
            failure_message="智能分析后台任务执行失败。",
            safe_error_statuses=SAFE_ERROR_STATUSES,
        )

    def _run(self, snapshot: Dict, progress) -> Dict:
        doc_session = str(snapshot.get("documentSessionId") or "").strip()
        host = str(snapshot.get("host") or "et").strip()
        job_id = str(snapshot.get("jobId") or "").strip()
        try:
            analyzer_kwargs = {"progress_callback": progress}
            if snapshot.get("taskAuth") is not None:
                analyzer_kwargs["task_auth"] = snapshot["taskAuth"]
            result = self.analyzer.analyze(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                **analyzer_kwargs
            )
            # Record success history
            try:
                task_auth = snapshot.get("taskAuth") or {}
                service_name = str(task_auth.get("serviceName") or "").strip()
                model_name = str(task_auth.get("modelName") or "").strip()
                doc_name = str(snapshot.get("documentDisplayName") or "工作簿.xlsx").strip()
                archived_result = {
                    "structuredReport": {
                        "overview": str((result.get("structuredReport") or {}).get("overview") or ""),
                        "findings": list((result.get("structuredReport") or {}).get("findings") or []),
                        "risks": list((result.get("structuredReport") or {}).get("risks") or []),
                        "actions": list((result.get("structuredReport") or {}).get("actions") or []),
                    },
                    "plainText": str(result.get("plainText") or ""),
                }
                get_task_history_store().record_success(
                    task_type="excel.analysis",
                    job_id=job_id,
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
            return result
        finally:
            if doc_session:
                with self._submission_lock:
                    slot_key = (host, "excel.analysis", doc_session)
                    if self._active_doc_sessions.get(slot_key) == job_id:
                        self._active_doc_sessions.pop(slot_key, None)
