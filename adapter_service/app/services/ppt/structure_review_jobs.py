import re
import threading
from copy import deepcopy
from typing import Dict, Optional

from app.core.models import PptStructureReviewRequest
from app.services.long_task_coordinator import LongTaskCoordinator, get_long_task_coordinator
from app.services.ppt.structure_review import PptStructureReviewer
from app.services.provider_client import PPT_STRUCTURE_REVIEW_TIMEOUT_SECONDS


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

    def start(self, request: PptStructureReviewRequest, trace_id: str) -> Dict:
        job_id = _job_id(request.client_job_id, trace_id)
        with self._submission_lock:
            existing = self.get(job_id)
            if existing is not None:
                return existing
            snapshot_auth = getattr(self.reviewer, "snapshot_task_auth", None)
            task_auth = snapshot_auth() if callable(snapshot_auth) else None
            return self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type="ppt.structure_review",
                runner=self._run,
                snapshot={"request": _copy_request(request), "taskAuth": task_auth},
                failure_code="PPT_STRUCTURE_JOB_FAILED",
                failure_message=JOB_FAILED_MESSAGE,
                public_metadata={
                    "runningMessage": "模型后台正在处理 PPT 结构审查，adapter 会继续等待结果。",
                    "providerTimeoutSeconds": PPT_STRUCTURE_REVIEW_TIMEOUT_SECONDS,
                },
                safe_failure_codes=SAFE_ERROR_CODES,
            )

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="ppt.structure_review")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="ppt.structure_review")

    def _run(self, snapshot: Dict, progress) -> Dict:
        kwargs = {"progress_callback": progress}
        if snapshot.get("taskAuth") is not None:
            kwargs["task_auth"] = snapshot["taskAuth"]
        return self.reviewer.review(
            snapshot["request"],
            trace_id=snapshot.get("traceId", "") or "",
            **kwargs
        )
