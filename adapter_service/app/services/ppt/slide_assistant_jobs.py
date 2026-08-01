import re
import threading
from copy import deepcopy
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import PptSlideAssistantRequest
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.provider_client import PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理当前页智能总结，adapter 会继续等待结果。"
DOCUMENT_RUNNING_MESSAGE = "已接收文档，adapter 正在准备模型后台任务。"
JOB_FAILED_MESSAGE = "智能总结后台任务执行失败，请稍后重试或查看最近一次任务诊断。"
SAFE_ERROR_CODES = {
    "PPT_DOCUMENT_FILE_REQUIRED",
    "PPT_DOCUMENT_FILE_EXPIRED",
    "PPT_SLIDE_REQUIRED",
    "PPT_SLIDE_INSTRUCTION_REQUIRED",
}


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


def _copy_request(request: PptSlideAssistantRequest) -> PptSlideAssistantRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(deep=True)
    if hasattr(request, "copy"):
        return request.copy(deep=True)
    return deepcopy(request)


class PptSlideAssistantJobStore:
    def __init__(
        self,
        assistant: Optional[PptSlideAssistant] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.assistant = assistant or PptSlideAssistant()
        self.coordinator = coordinator or get_long_task_coordinator()
        self.document_file_store = getattr(self.assistant, "document_file_store", None)
        self._submission_lock = threading.Lock()

    def start(self, request: PptSlideAssistantRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type="ppt.slide_assistant")
            if existing is not None:
                return existing

            staged_document = None
            if request.source_mode == "document":
                token = str(getattr(request, "file_token", "") or "").strip()
                if not token:
                    raise AdapterError(
                        "PPT_DOCUMENT_FILE_REQUIRED",
                        "请先选择并上传 Markdown 或 Word 文档。",
                        status_code=400,
                    )
                if self.document_file_store is None:
                    raise AdapterError(
                        "PPT_DOCUMENT_FILE_EXPIRED",
                        "文档上传凭证已过期，请重新选择文件。",
                        status_code=400,
                    )
                staged_document = self.document_file_store.claim(token, job_id)

            try:
                snapshot_task_auth = getattr(self.assistant, "snapshot_task_auth", None)
                task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
                return self.coordinator.submit(
                    job_id=job_id,
                    trace_id=trace_id,
                    task_type="ppt.slide_assistant",
                    runner=self._run,
                    snapshot={
                        "request": _copy_request(request),
                        "taskAuth": task_auth,
                        "stagedDocument": staged_document,
                        "documentOwnerId": job_id if staged_document is not None else "",
                    },
                    failure_code="PPT_SLIDE_JOB_FAILED",
                    failure_message=JOB_FAILED_MESSAGE,
                    public_metadata={
                        "runningMessage": (
                            DOCUMENT_RUNNING_MESSAGE
                            if request.source_mode == "document"
                            else RUNNING_MESSAGE
                        ),
                        "providerTimeoutSeconds": PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS,
                        "sourceMode": request.source_mode,
                    },
                    safe_failure_codes=SAFE_ERROR_CODES,
                )
            except Exception:
                if staged_document is not None:
                    self.document_file_store.release(job_id)
                raise

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="ppt.slide_assistant")

    def cancel(self, job_id: str) -> Optional[Dict]:
        job = self.coordinator.cancel(job_id, task_type="ppt.slide_assistant")
        if job is not None and job.get("status") == "cancelled" and self.document_file_store:
            self.document_file_store.release(job_id)
        return job

    def close(self) -> None:
        if self.document_file_store is not None:
            self.document_file_store.close()

    def _run(self, snapshot: Dict, progress) -> Dict:
        owner_id = str(snapshot.get("documentOwnerId", ""))
        kwargs = {"progress_callback": progress}
        if snapshot.get("taskAuth") is not None:
            kwargs["task_auth"] = snapshot["taskAuth"]
        if snapshot.get("stagedDocument") is not None:
            kwargs["staged_document"] = snapshot["stagedDocument"]
        try:
            return self.assistant.assist(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                **kwargs,
            )
        finally:
            if owner_id and self.document_file_store is not None:
                self.document_file_store.release(owner_id)
