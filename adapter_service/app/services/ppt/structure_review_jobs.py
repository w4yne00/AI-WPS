import re
import threading
import time
from copy import deepcopy
from typing import Dict, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import PptStructureReviewRequest
from app.services.long_task_coordinator import LongTaskCoordinator, get_long_task_coordinator
from app.services.ppt.structure_review import PptStructureReviewer
from app.services.provider_client import PPT_STRUCTURE_REVIEW_TIMEOUT_SECONDS
from app.services.task_history import TaskHistoryError, get_task_history_store


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
JOB_FAILED_MESSAGE = "结构审查后台任务执行失败，请稍后重试或查看最近一次任务诊断。"
SAFE_ERROR_CODES = {
    "PPT_STRUCTURE_RANGE_INVALID",
    "PPT_STRUCTURE_RANGE_TOO_LARGE",
    "PPT_STRUCTURE_SLIDES_INCOMPLETE",
    "PPT_STRUCTURE_AUTH_SNAPSHOT_FAILED",
}


def _job_id(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    return text if CLIENT_JOB_ID_PATTERN.match(text) else fallback


def _copy_request(request: PptStructureReviewRequest) -> PptStructureReviewRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(deep=True)
    if hasattr(request, "copy"):
        return request.copy(deep=True)
    return deepcopy(request)


class PptStructureReviewJobStore:
    def __init__(
        self,
        reviewer: Optional[PptStructureReviewer] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.reviewer = reviewer or PptStructureReviewer()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions: Dict[Tuple[str, str, str], str] = {}
        self._job_identities: Dict[str, Tuple[str, str, str]] = {}

    def start(self, request: PptStructureReviewRequest, trace_id: str) -> Dict:
        job_id = _job_id(request.client_job_id, trace_id)
        doc_session = str(
            getattr(request, "document_session_id", "")
            or getattr(request, "presentation_id", "")
            or "active-presentation"
        ).strip()
        host = str(getattr(request, "host", "") or "wpp").strip()
        task_type = "ppt.structure_review"
        identity = (host, task_type, doc_session)

        with self._submission_lock:
            existing = self.get(job_id)
            if existing is not None:
                recorded_identity = self._job_identities.get(job_id)
                if recorded_identity is not None and recorded_identity != identity:
                    raise AdapterError(
                        "PPT_STRUCTURE_REVIEW_TASK_CONFLICT",
                        "任务编号已绑定到其他文档会话。",
                        status_code=409,
                    )
                return existing

            # Document session active slot guard: reject duplicate concurrent task in same document session
            if doc_session:
                slot_key = (host, task_type, doc_session)
                active_job_id = self._active_doc_sessions.get(slot_key)
                if active_job_id:
                    active_job = self.coordinator.get(active_job_id, task_type=task_type)
                    if active_job and active_job.get("status") in {"queued", "running"}:
                        if active_job_id != job_id:
                            raise AdapterError(
                                "PPT_STRUCTURE_REVIEW_DOCUMENT_TASK_BUSY",
                                "当前演示文稿已存在进行中的结构审查任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            self._job_identities[job_id] = identity
            snapshot_auth = getattr(self.reviewer, "snapshot_task_auth", None)
            task_auth = snapshot_auth() if callable(snapshot_auth) else None
            submitted = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=task_type,
                runner=self._run,
                success_committer=self._commit_success,
                snapshot={
                    "request": _copy_request(request),
                    "taskAuth": task_auth,
                    "jobId": job_id,
                    "host": host,
                    "documentSessionId": doc_session,
                },
                failure_code="PPT_STRUCTURE_JOB_FAILED",
                failure_message=JOB_FAILED_MESSAGE,
                public_metadata={
                    "runningMessage": "模型后台正在处理 PPT 结构审查，adapter 会继续等待结果。",
                    "providerTimeoutSeconds": PPT_STRUCTURE_REVIEW_TIMEOUT_SECONDS,
                },
                safe_failure_codes=SAFE_ERROR_CODES,
                request_fingerprint=f"{host}::{task_type}::{doc_session}",
                request_conflict_code="PPT_STRUCTURE_REVIEW_TASK_CONFLICT",
                request_conflict_message="任务编号已绑定到其他文档会话。",
            )
            if doc_session and submitted.get("status") in {"queued", "running"}:
                self._active_doc_sessions[(host, task_type, doc_session)] = job_id
            return submitted

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="ppt.structure_review")

    def cancel(self, job_id: str) -> Optional[Dict]:
        job = self.coordinator.cancel(job_id, task_type="ppt.structure_review")
        if job is not None and job.get("status") == "cancelled":
            with self._submission_lock:
                for key, val in list(self._active_doc_sessions.items()):
                    if val == job_id:
                        self._active_doc_sessions.pop(key, None)
                self._job_identities.pop(job_id, None)
        return job

    def _run(self, snapshot: Dict, progress) -> Dict:
        kwargs = {"progress_callback": progress}
        if snapshot.get("taskAuth") is not None:
            kwargs["task_auth"] = snapshot["taskAuth"]
        try:
            result = self.reviewer.review(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                **kwargs
            )
            return result
        finally:
            doc_session = str(snapshot.get("documentSessionId") or "")
            host = str(snapshot.get("host") or "wpp")
            if doc_session:
                with self._submission_lock:
                    slot_key = (host, "ppt.structure_review", doc_session)
                    if self._active_doc_sessions.get(slot_key) == snapshot.get("jobId"):
                        self._active_doc_sessions.pop(slot_key, None)

    @staticmethod
    def _commit_success(snapshot: Dict, result: Dict) -> None:
        try:
            req = snapshot.get("request")
            doc_name = (
                getattr(req, "document_display_name", "")
                or getattr(req, "presentation_id", "")
                or "演示文稿"
            )
            auth = snapshot.get("taskAuth") or {}
            service_name = auth.get("serviceName") or auth.get("providerName") or "模型服务"
            model_name = auth.get("modelName") or result.get("provider") or "model"
            job_id = str(snapshot.get("jobId") or snapshot.get("traceId") or "")
            archived_result = {
                "resultType": "structure_review",
                "reportId": job_id,
                "jobId": job_id,
                "reviewedRange": result.get("reviewedRange"),
                "overallStoryline": result.get("overallStoryline", ""),
                "reviewConclusion": result.get("reviewConclusion", ""),
                "highPriorityIssueCount": len(result.get("highPriorityIssues") or []),
                "generalSuggestionCount": len(result.get("generalSuggestions") or []),
                "slideRecommendationCount": len(result.get("slideRecommendations") or []),
                "reportExpiresAt": float(time.time() + 7200),
            }
            get_task_history_store().record_success(
                task_type="ppt.structure_review",
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
