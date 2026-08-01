import re
from copy import deepcopy
from typing import Dict, Optional

from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import DOCUMENT_REVIEW_TIMEOUT_SECONDS
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

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        existing = self.coordinator.get(job_id, task_type="word.document_review")
        if existing is not None:
            return existing
        snapshot = {
            "request": _copy_request(request),
            "taskAuth": self.reviewer.snapshot_task_auth(),
        }
        return self.coordinator.submit(
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

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="word.document_review")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="word.document_review")

    def _run(self, snapshot: Dict, progress) -> Dict:
        return self.reviewer.review(
            snapshot["request"],
            trace_id=snapshot.get("traceId", "") or "",
            task_auth=snapshot.get("taskAuth"),
            progress_callback=progress,
        )
