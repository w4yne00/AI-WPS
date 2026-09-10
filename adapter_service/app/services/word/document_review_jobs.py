import re
import threading
from copy import deepcopy
from typing import Dict, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import DOCUMENT_REVIEW_TIMEOUT_SECONDS
from app.services.task_history import (
    TaskHistoryError,
    get_task_history_store,
    sanitize_audit_for_history,
    sanitize_usage_for_history,
)
from app.services.word.document_reviewer import WordDocumentReviewer


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理文档审查，adapter 会继续等待结果。"


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


def _copy_request(request: WordDocumentRequest) -> WordDocumentRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(deep=True)
    if hasattr(request, "copy"):
        return request.copy(deep=True)
    return deepcopy(request)


class DocumentReviewJobStore:
    def __init__(
        self,
        reviewer: Optional[WordDocumentReviewer] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.reviewer = reviewer or WordDocumentReviewer()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions: Dict[Tuple[str, str, str], str] = {}
        self._job_identities: Dict[str, Tuple[str, str, str]] = {}

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job_id = (
            normalize_client_job_id(
                getattr(request, "client_job_id", "")
                or getattr(request, "clientJobId", "")
            )
            or trace_id
        )
        doc_session = str(
            getattr(request, "document_session_id", "")
            or getattr(request, "documentSessionId", "")
            or ""
        ).strip()
        host = str(getattr(request, "host", "") or "wps").strip()
        identity = (host, "word.document_review", doc_session)

        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type="word.document_review")
            if existing is not None:
                recorded_identity = self._job_identities.get(job_id)
                if recorded_identity is not None and recorded_identity != identity:
                    raise AdapterError(
                        "WORD_DOCUMENT_REVIEW_TASK_CONFLICT",
                        "任务编号已绑定到其他文档会话。",
                        status_code=409,
                    )
                return existing

            if doc_session:
                slot_key = (host, "word.document_review", doc_session)
                active_job_id = self._active_doc_sessions.get(slot_key)
                if active_job_id:
                    active_job = self.coordinator.get(active_job_id, task_type="word.document_review")
                    if active_job and active_job.get("status") in {"queued", "running"}:
                        if active_job_id != job_id:
                            raise AdapterError(
                                "WORD_DOCUMENT_REVIEW_TASK_BUSY",
                                "当前文档已存在进行中的文档审查任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            self._job_identities[job_id] = identity
            snapshot = {
                "request": _copy_request(request),
                "jobId": job_id,
                "traceId": trace_id,
                "taskAuth": self.reviewer.snapshot_task_auth(),
            }
            res = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type="word.document_review",
                runner=self._run,
                snapshot=snapshot,
                failure_code="DOCUMENT_REVIEW_JOB_FAILED",
                failure_message="文档审查后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
                public_metadata={
                    "runningMessage": RUNNING_MESSAGE,
                    "providerTimeoutSeconds": DOCUMENT_REVIEW_TIMEOUT_SECONDS,
                },
            )
            if doc_session and res.get("status") in {"queued", "running"}:
                self._active_doc_sessions[(host, "word.document_review", doc_session)] = job_id
            return res

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="word.document_review")

    def cancel(self, job_id: str) -> Optional[Dict]:
        res = self.coordinator.cancel(job_id, task_type="word.document_review")
        with self._submission_lock:
            for key, val in list(self._active_doc_sessions.items()):
                if val == job_id:
                    self._active_doc_sessions.pop(key, None)
            self._job_identities.pop(job_id, None)
        return res

    def run_sync(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job = self.start(request, trace_id)
        return self.coordinator.wait_result(
            job["jobId"],
            task_type="word.document_review",
            not_found_code="DOCUMENT_REVIEW_JOB_NOT_FOUND",
            not_found_message="文档审查后台任务不存在或已过期。",
            cancelled_message="排队中的文档审查任务已取消。",
            failure_code="DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="文档审查后台任务执行失败。",
        )

    def _run(self, snapshot: Dict, progress) -> Dict:
        try:
            result = self.reviewer.review(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                task_auth=snapshot.get("taskAuth"),
                progress_callback=progress,
            )
            try:
                req = snapshot["request"]
                doc_name = (
                    getattr(req, "document_display_name", None)
                    or getattr(req, "documentDisplayName", None)
                    or getattr(req, "document_id", None)
                    or getattr(req, "documentId", None)
                    or ""
                )
                task_auth = snapshot.get("taskAuth") or {}
                service_name = str(task_auth.get("serviceName") or "")
                model_name = str(task_auth.get("modelName") or "")
                job_id = str(snapshot.get("jobId") or snapshot.get("traceId") or "")

                issues = result.get("issues") or []
                category_counts = {}
                severity_counts = {}
                for iss in issues:
                    cat = str(iss.get("category", "")).strip()
                    if cat:
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                    sev = str(iss.get("severity", "")).strip()
                    if sev:
                        severity_counts[sev] = severity_counts.get(sev, 0) + 1

                archived_result = {
                    "reportType": "document_review",
                    "jobId": job_id,
                    "summary": result.get("summary", ""),
                    "issueCount": len(issues),
                    "categoryCounts": category_counts,
                    "severityCounts": severity_counts,
                    "documentType": result.get("documentType", ""),
                    "scope": result.get("scope", ""),
                    "writingPolicyUsage": sanitize_usage_for_history(result.get("writingPolicyUsage")),
                    "writingPolicyAudit": sanitize_audit_for_history(result.get("writingPolicyAudit")),
                }
                get_task_history_store().record_success(
                    task_type="word.document_review",
                    job_id=job_id,
                    result=archived_result,
                    document_display_name=doc_name,
                    service_name=service_name,
                    model_name=model_name,
                )
            except TaskHistoryError as exc:
                if exc.code == "HISTORY_ENTRY_TOO_LARGE":
                    result["historyNotice"] = "任务结果超过 5 MiB，未写入历史记录。"
            except Exception:
                pass

            return result
        finally:
            req = snapshot.get("request")
            doc_session = str(
                getattr(req, "document_session_id", "")
                or getattr(req, "documentSessionId", "")
                or ""
            ).strip()
            host = str(getattr(req, "host", "") or "wps").strip()
            if doc_session:
                slot_key = (host, "word.document_review", doc_session)
                with self._submission_lock:
                    if self._active_doc_sessions.get(slot_key) == snapshot.get("jobId"):
                        self._active_doc_sessions.pop(slot_key, None)
