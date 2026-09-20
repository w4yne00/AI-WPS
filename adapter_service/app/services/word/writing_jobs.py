import re
import threading
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.features import (
    direct_streaming_enabled,
    streaming_capability_validated,
)
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import (
    MAX_EVENT_WAIT_MS,
    PRIORITY_INTERACTIVE,
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import INTERACTIVE_WRITING_TIMEOUT_SECONDS
from app.services.task_history import (
    TaskHistoryError,
    get_task_history_store,
    sanitize_audit_for_history,
    sanitize_usage_for_history,
)
from app.services.word.rewriter import WordRewriter
from app.services.word.smart_imitator import WordSmartImitator


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
WRITING_EVENTS_QUERY_INVALID_MESSAGE = "afterSequence 和 waitMs 必须为整数。"


def normalize_writing_events_query(after_sequence="0", wait_ms="0") -> Tuple[int, int]:
    try:
        parsed_after_sequence = int(after_sequence)
        parsed_wait_ms = int(wait_ms)
    except (TypeError, ValueError):
        raise AdapterError(
            "REQUEST_VALIDATION_FAILED",
            WRITING_EVENTS_QUERY_INVALID_MESSAGE,
            status_code=422,
        )
    return (
        max(0, parsed_after_sequence),
        max(0, min(parsed_wait_ms, MAX_EVENT_WAIT_MS)),
    )


def _normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    return text if CLIENT_JOB_ID_PATTERN.match(text) else ""


def _copy_request(request: WordDocumentRequest) -> WordDocumentRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(deep=True)
    if hasattr(request, "copy"):
        return request.copy(deep=True)
    return deepcopy(request)


class WritingJobStore:
    def __init__(
        self,
        task_type: str,
        worker,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.task_type = task_type
        self.worker = worker
        self.coordinator = coordinator or get_long_task_coordinator()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions: Dict[Tuple[str, str, str], str] = {}

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job_id = _normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        doc_session = str(getattr(request, "document_session_id", "") or "").strip()
        host = str(getattr(request, "host", "") or "wps").strip()

        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type=self.task_type)
            if existing is not None:
                return existing

            # Document session active slot guard: reject duplicate concurrent task in same document session
            if doc_session:
                slot_key = (host, self.task_type, doc_session)
                active_job_id = self._active_doc_sessions.get(slot_key)
                if active_job_id:
                    active_job = self.coordinator.get(active_job_id, task_type=self.task_type)
                    if active_job and active_job.get("status") in {"queued", "running"}:
                        if active_job_id != job_id:
                            label = "智能编写" if self.task_type == "word.smart_write" else "智能仿写"
                            raise AdapterError(
                                "WORD_WRITING_DOCUMENT_TASK_BUSY",
                                "当前文档已存在进行中的{0}任务，请等待其完成。".format(label),
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            task_auth = self.worker.snapshot_task_auth() if hasattr(self.worker, "snapshot_task_auth") else None
            streaming_enabled = direct_streaming_enabled()
            if isinstance(task_auth, dict):
                task_auth = deepcopy(task_auth)
                task_auth["directStreamingEnabled"] = streaming_enabled
            is_streaming = bool(
                streaming_enabled
                and isinstance(task_auth, dict)
                and streaming_capability_validated(
                    task_auth.get("streamingCapability")
                )
            )
            snapshot = {
                "request": _copy_request(request),
                "taskAuth": task_auth,
                "jobId": job_id,
                "host": host,
                "documentSessionId": doc_session,
                "traceId": trace_id,
            }
            label = "智能编写" if self.task_type == "word.smart_write" else "智能仿写"
            submitted = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=self.task_type,
                runner=self._run,
                success_committer=self._commit_success,
                snapshot=snapshot,
                failure_code="WRITING_JOB_FAILED",
                failure_message="{0}后台任务执行失败，请查看最近一次任务诊断。".format(label),
                public_metadata={
                    "runningMessage": "模型后台正在处理{0}，Adapter 会继续等待结果。".format(label),
                    "providerTimeoutSeconds": INTERACTIVE_WRITING_TIMEOUT_SECONDS,
                    "streamingEnabled": is_streaming,
                },
                safe_failure_codes={
                    "MODEL_CONFIG_INCOMPLETE",
                    "MODEL_INPUT_OVER_BUDGET",
                    "MODEL_RESPONSE_SIZE_LIMIT",
                    "MODEL_FINAL_CONTENT_MISSING",
                    "PROVIDER_AUTH_FAILED",
                    "PROVIDER_TIMEOUT",
                    "PROVIDER_UNREACHABLE",
                    "MODEL_RATE_LIMITED",
                    "MODEL_OR_PATH_UNAVAILABLE",
                    "SYSTEM_PROMPT_MISSING",
                    "SYSTEM_PROMPT_DAMAGED",
                },
                priority_class=PRIORITY_INTERACTIVE,
                allow_running_cancel=is_streaming,
            )
            if doc_session:
                self._active_doc_sessions[(host, self.task_type, doc_session)] = job_id
            return submitted

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type=self.task_type)

    def wait_events(
        self,
        job_id: str,
        after_sequence: int = 0,
        wait_ms: int = 0,
    ) -> Optional[Dict]:
        return self.coordinator.wait_events(
            job_id,
            task_type=self.task_type,
            after_sequence=after_sequence,
            wait_ms=wait_ms,
        )

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.request_cancel(job_id, task_type=self.task_type)

    def run_sync(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job = self.start(request, trace_id)
        return self.coordinator.wait_result(
            job["jobId"],
            task_type=self.task_type,
            not_found_code="WRITING_JOB_NOT_FOUND",
            not_found_message="后台写作任务不存在或已过期。",
            cancelled_message="排队中的写作任务已取消。",
            failure_code="WRITING_JOB_FAILED",
            failure_message="后台写作任务执行失败。",
            safe_error_statuses={
                "MODEL_CONFIG_INCOMPLETE": 400,
                "MODEL_INPUT_OVER_BUDGET": 413,
                "MODEL_RESPONSE_SIZE_LIMIT": 502,
                "PROVIDER_AUTH_FAILED": 401,
                "MODEL_RATE_LIMITED": 429,
                "PROVIDER_TIMEOUT": 504,
            },
        )

    def _run(self, snapshot: Dict, progress) -> Dict:
        kwargs = {
            "trace_id": snapshot.get("traceId", ""),
            "task_auth": snapshot.get("taskAuth"),
            "progress_callback": progress,
        }
        if self.task_type == "word.smart_write":
            result = self.worker.smart_write(snapshot["request"], **kwargs)
        else:
            result = self.worker.imitate(snapshot["request"], **kwargs)

        return result

    def _commit_success(self, snapshot: Dict, result: Dict) -> None:
        try:
            req = snapshot.get("request")
            doc_name = (
                getattr(req, "document_display_name", "")
                or getattr(req, "document_id", "")
                or "文档"
            )
            auth = snapshot.get("taskAuth") or {}
            service_name = auth.get("serviceName") or auth.get("providerName") or "模型服务"
            model_name = auth.get("modelName") or result.get("provider") or "model"
            job_id = str(snapshot.get("jobId") or snapshot.get("traceId") or "")
            rewritten_text = result.get("rewrittenText", "")
            archived_result = {
                "rewrittenText": rewritten_text,
                "rewriteMode": result.get("rewriteMode", ""),
                "diffHints": result.get("diffHints") or [],
                "plainText": rewritten_text,
                "writingPolicyUsage": sanitize_usage_for_history(result.get("writingPolicyUsage")),
                "writingPolicyAudit": sanitize_audit_for_history(result.get("writingPolicyAudit")),
            }
            get_task_history_store().record_success(
                task_type=self.task_type,
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


class SmartWriteJobStore(WritingJobStore):
    def __init__(
        self,
        worker: Optional[WordRewriter] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        super().__init__("word.smart_write", worker or WordRewriter(), coordinator)


class SmartImitationJobStore(WritingJobStore):
    def __init__(
        self,
        worker: Optional[WordSmartImitator] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        super().__init__(
            "word.smart_imitation", worker or WordSmartImitator(), coordinator
        )
