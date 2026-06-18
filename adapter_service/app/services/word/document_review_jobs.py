import threading
import time
from typing import Dict, Optional

from app.core.models import WordDocumentRequest
from app.services.word.document_reviewer import WordDocumentReviewer


class DocumentReviewJobStore:
    def __init__(self, reviewer: Optional[WordDocumentReviewer] = None, max_jobs: int = 30) -> None:
        self.reviewer = reviewer or WordDocumentReviewer()
        self.max_jobs = max_jobs
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def start(self, request: WordDocumentRequest, trace_id: str) -> Dict:
        job = {
            "jobId": trace_id,
            "traceId": trace_id,
            "status": "running",
            "createdAt": time.time(),
            "updatedAt": time.time(),
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[trace_id] = job
            self._trim_locked()
        worker = threading.Thread(target=self._run, args=(trace_id, request), daemon=True)
        worker.start()
        return self.get(trace_id) or job

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._public_job(job)

    def _run(self, job_id: str, request: WordDocumentRequest) -> None:
        try:
            result = self.reviewer.review(request, trace_id=job_id)
            self._update(job_id, status="completed", result=result)
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
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
        data = {
            "jobId": job["jobId"],
            "traceId": job["traceId"],
            "status": job["status"],
            "createdAt": job["createdAt"],
            "updatedAt": job["updatedAt"],
        }
        if job.get("result") is not None:
            data["result"] = job["result"]
        if job.get("error") is not None:
            data["error"] = job["error"]
        return data
