import re
import threading
import time
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import PptSlideAssistantRequest
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.provider_client import PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理当前页智能总结，adapter 会继续等待结果。"
DOCUMENT_RUNNING_MESSAGE = "已接收文档，adapter 正在准备模型后台任务。"
JOB_FAILED_MESSAGE = "智能总结后台任务执行失败，请稍后重试或查看最近一次任务诊断。"
SAFE_DOCUMENT_ERROR_CODES = {
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


class PptSlideAssistantJobStore:
    def __init__(self, assistant: Optional[PptSlideAssistant] = None, max_jobs: int = 30) -> None:
        self.assistant = assistant or PptSlideAssistant()
        self.max_jobs = max_jobs
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def start(self, request: PptSlideAssistantRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        job = {
            "jobId": job_id,
            "traceId": trace_id,
            "status": "running",
            "createdAt": time.time(),
            "updatedAt": time.time(),
            "runningMessage": (
                DOCUMENT_RUNNING_MESSAGE if request.source_mode == "document" else RUNNING_MESSAGE
            ),
            "providerTimeoutSeconds": PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS,
            "result": None,
            "error": None,
        }
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing:
                return self._public_job(existing)
            self._make_room_for_new_job_locked()
            self._jobs[job_id] = job
            self._trim_locked()
        worker = threading.Thread(target=self._run, args=(job_id, request, trace_id), daemon=True)
        worker.start()
        return self.get(job_id) or job

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._public_job(job) if job else None

    def _run(self, job_id: str, request: PptSlideAssistantRequest, trace_id: str) -> None:
        try:
            result = self.assistant.assist(
                request,
                trace_id=trace_id,
                progress_callback=lambda message: self._update(job_id, runningMessage=message),
            )
            self._update(job_id, status="completed", result=result, runningMessage="")
        except Exception as exc:
            code = "PPT_SLIDE_JOB_FAILED"
            message = JOB_FAILED_MESSAGE
            if isinstance(exc, AdapterError) and exc.code in SAFE_DOCUMENT_ERROR_CODES:
                code = exc.code
                message = exc.message
            self._update(
                job_id,
                status="failed",
                runningMessage="",
                error={
                    "code": code,
                    "message": message,
                },
            )

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updatedAt"] = time.time()
            self._trim_locked()

    def _trim_locked(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(
            (job for job in self._jobs.values() if job.get("status") != "running"),
            key=lambda item: item.get("createdAt", 0),
        )
        for job in ordered[: max(len(self._jobs) - self.max_jobs, 0)]:
            self._jobs.pop(job["jobId"], None)

    def _make_room_for_new_job_locked(self) -> None:
        if len(self._jobs) < self.max_jobs:
            return
        completed = sorted(
            (job for job in self._jobs.values() if job.get("status") != "running"),
            key=lambda item: item.get("createdAt", 0),
        )
        while len(self._jobs) >= self.max_jobs and completed:
            self._jobs.pop(completed.pop(0)["jobId"], None)
        if len(self._jobs) >= self.max_jobs:
            raise AdapterError(
                "PPT_SLIDE_JOB_CAPACITY",
                "当前智能总结任务较多，请等待已有任务完成后重试。",
                status_code=429,
            )

    def _public_job(self, job: Dict) -> Dict:
        now = time.time()
        data = {
            "jobId": job["jobId"],
            "traceId": job["traceId"],
            "status": job["status"],
            "createdAt": job["createdAt"],
            "updatedAt": job["updatedAt"],
            "elapsedSeconds": int(max(now - job.get("createdAt", now), 0)),
            "heartbeatAgeSeconds": int(max(now - job.get("updatedAt", now), 0)),
            "providerTimeoutSeconds": job.get(
                "providerTimeoutSeconds",
                PPT_SLIDE_ASSISTANT_TIMEOUT_SECONDS,
            ),
        }
        if job.get("runningMessage"):
            data["runningMessage"] = job["runningMessage"]
        if job.get("result") is not None:
            data["result"] = job["result"]
        if job.get("error") is not None:
            data["error"] = job["error"]
        return data
