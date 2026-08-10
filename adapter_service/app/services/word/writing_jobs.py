import re
from copy import deepcopy
from typing import Dict, Optional

from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import (
    PRIORITY_INTERACTIVE,
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import INTERACTIVE_WRITING_TIMEOUT_SECONDS
from app.services.word.rewriter import WordRewriter
from app.services.word.smart_imitator import WordSmartImitator


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")


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

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job_id = _normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        existing = self.coordinator.get(job_id, task_type=self.task_type)
        if existing is not None:
            return existing
        snapshot = {
            "request": _copy_request(request),
            "taskAuth": self.worker.snapshot_task_auth(),
        }
        label = "智能编写" if self.task_type == "word.smart_write" else "智能仿写"
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type=self.task_type,
            runner=self._run,
            snapshot=snapshot,
            failure_code="WRITING_JOB_FAILED",
            failure_message="{0}后台任务执行失败，请查看最近一次任务诊断。".format(label),
            public_metadata={
                "runningMessage": "模型后台正在处理{0}，Adapter 会继续等待结果。".format(label),
                "providerTimeoutSeconds": INTERACTIVE_WRITING_TIMEOUT_SECONDS,
            },
            safe_failure_codes={
                "MODEL_CONFIG_INCOMPLETE",
                "MODEL_INPUT_OVER_BUDGET",
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
        )

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type=self.task_type)

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type=self.task_type)

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
            return self.worker.smart_write(snapshot["request"], **kwargs)
        return self.worker.imitate(snapshot["request"], **kwargs)


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
