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
        self._active_doc_sessions: Dict[Tuple[str, str, str], str] = {}

    def start(self, request: PptSlideAssistantRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        doc_session = str(getattr(request, "document_session_id", "") or "").strip()
        host = str(getattr(request, "host", "") or "wpp").strip()
        task_type = "ppt.slide_assistant"

        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type=task_type)
            if existing is not None:
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
                                "PPT_SLIDE_ASSISTANT_DOCUMENT_TASK_BUSY",
                                "当前演示文稿已存在进行中的智能总结任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

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
                submitted = self.coordinator.submit(
                    job_id=job_id,
                    trace_id=trace_id,
                    task_type=task_type,
                    runner=self._run,
                    snapshot={
                        "request": _copy_request(request),
                        "taskAuth": task_auth,
                        "stagedDocument": staged_document,
                        "documentOwnerId": job_id if staged_document is not None else "",
                        "jobId": job_id,
                        "host": host,
                        "documentSessionId": doc_session,
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
                if doc_session:
                    self._active_doc_sessions[(host, task_type, doc_session)] = job_id
                return submitted
            except Exception:
                if staged_document is not None:
                    self.document_file_store.release(job_id)
                raise

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="ppt.slide_assistant")

    def cancel(self, job_id: str) -> Optional[Dict]:
        job = self.coordinator.cancel(job_id, task_type="ppt.slide_assistant")
        if job is not None and job.get("status") == "cancelled":
            if self.document_file_store:
                self.document_file_store.release(job_id)
            with self._submission_lock:
                for key, val in list(self._active_doc_sessions.items()):
                    if val == job_id:
                        self._active_doc_sessions.pop(key, None)
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
            result = self.assistant.assist(
                snapshot["request"],
                trace_id=snapshot.get("traceId", "") or "",
                **kwargs,
            )
            try:
                from app.services.task_history import (
                    TaskHistoryError,
                    get_task_history_store,
                )

                req = snapshot.get("request")
                doc_name = (
                    getattr(req, "document_display_name", "")
                    or getattr(req, "presentation_id", "")
                    or "演示文稿"
                )
                auth = snapshot.get("taskAuth") or {}
                service_name = auth.get("serviceName") or auth.get("providerName") or "模型服务"
                model_name = auth.get("modelName") or result.get("provider") or "model"
                job_id = str(snapshot.get("jobId") or snapshot.get("documentOwnerId") or snapshot.get("traceId") or "")

                # Strict allowlist sanitization: strip prompt, userInstruction, fileToken, rawAnswer
                source_mode = getattr(req, "source_mode", "slide")
                if source_mode == "document":
                    archived_result = {
                        "resultType": "document",
                        "deckTitle": result.get("deckTitle", ""),
                        "documentSummary": result.get("documentSummary", ""),
                        "recommendedSlideCount": result.get("recommendedSlideCount", 10),
                        "slides": result.get("slides") or [],
                        "globalStyleAdvice": result.get("globalStyleAdvice", ""),
                        "plainText": result.get("plainText", ""),
                    }
                else:
                    archived_result = {
                        "resultType": "slide",
                        "summary": result.get("summary", ""),
                        "actionItems": result.get("actionItems") or [],
                        "bulletPoints": result.get("bulletPoints") or [],
                        "plainText": result.get("plainText", ""),
                    }

                get_task_history_store().record_success(
                    task_type="ppt.slide_assistant",
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
            if owner_id and self.document_file_store is not None:
                self.document_file_store.release(owner_id)
            doc_session = str(snapshot.get("documentSessionId") or "")
            host = str(snapshot.get("host") or "wpp")
            if doc_session:
                with self._submission_lock:
                    slot_key = (host, "ppt.slide_assistant", doc_session)
                    if self._active_doc_sessions.get(slot_key) == snapshot.get("jobId"):
                        self._active_doc_sessions.pop(slot_key, None)
