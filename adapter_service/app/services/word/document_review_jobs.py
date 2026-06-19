import re
import threading
import time
from typing import Dict, Optional

from app.core.models import WordDocumentRequest
from app.services.provider_client import DOCUMENT_REVIEW_TIMEOUT_SECONDS
from app.services.word.document_reviewer import WordDocumentReviewer


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理文档审查，adapter 会继续等待结果。"


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


class DocumentReviewJobStore:
    def __init__(self, reviewer: Optional[WordDocumentReviewer] = None, max_jobs: int = 30) -> None:
        self.reviewer = reviewer or WordDocumentReviewer()
        self.max_jobs = max_jobs
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        job = {
            "jobId": job_id,
            "traceId": trace_id,
            "status": "running",
            "createdAt": time.time(),
            "updatedAt": time.time(),
            "runningMessage": RUNNING_MESSAGE,
            "providerTimeoutSeconds": DOCUMENT_REVIEW_TIMEOUT_SECONDS,
            "result": None,
            "error": None,
        }
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing:
                return self._public_job(existing)
            self._jobs[job_id] = job
            self._trim_locked()
        worker = threading.Thread(target=self._run, args=(job_id, request, trace_id), daemon=True)
        worker.start()
        return self.get(job_id) or job

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._public_job(job)

    def _run(self, job_id: str, request: WordDocumentRequest, trace_id: str) -> None:
        try:
            result = self.reviewer.review(request, trace_id=trace_id)
            self._update(job_id, status="completed", result=result, runningMessage="")
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                runningMessage="",
                error={
                    "code": "DOCUMENT_REVIEW_JOB_FAILED",
                    "message": str(exc) or "文档审查后台任务执行失败。",
                },
            )

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updatedAt"] = time.time()

    def _trim_locked(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: item.get("createdAt", 0))
        for job in ordered[: max(len(self._jobs) - self.max_jobs, 0)]:
            self._jobs.pop(job["jobId"], None)

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
            "providerTimeoutSeconds": job.get("providerTimeoutSeconds", DOCUMENT_REVIEW_TIMEOUT_SECONDS),
        }
        if job.get("runningMessage"):
            data["runningMessage"] = job["runningMessage"]
        if job.get("result") is not None:
            data["result"] = job["result"]
        if job.get("error") is not None:
            data["error"] = job["error"]
        return data
