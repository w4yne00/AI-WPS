import os
import threading
import time
from collections import deque
from copy import deepcopy
from typing import Callable, Deque, Dict, Optional

from app.core.errors import AdapterError


DEFAULT_MAX_RUNNING = 2
DEFAULT_MAX_QUEUED = 8
DEFAULT_TERMINAL_TTL_SECONDS = 2 * 60 * 60
DEFAULT_MAX_TERMINAL_JOBS = 50
PUBLIC_PHASES = {
    "queued",
    "preparing",
    "uploading",
    "provider_processing",
    "parsing",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class LongTaskCoordinator:
    """Bounded in-memory coordinator for blocking long-running task runners."""

    def __init__(
        self,
        max_running: int = DEFAULT_MAX_RUNNING,
        max_queued: int = DEFAULT_MAX_QUEUED,
        terminal_ttl_seconds: int = DEFAULT_TERMINAL_TTL_SECONDS,
        max_terminal_jobs: int = DEFAULT_MAX_TERMINAL_JOBS,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_running = max(int(max_running), 1)
        self.max_queued = max(int(max_queued), 1)
        self.terminal_ttl_seconds = max(int(terminal_ttl_seconds), 1)
        self.max_terminal_jobs = max(int(max_terminal_jobs), 1)
        self._monotonic = monotonic_clock
        self._wall_clock = wall_clock
        self._jobs: Dict[str, Dict] = {}
        self._queue: Deque[str] = deque()
        self._running_count = 0
        self._lock = threading.Lock()

    def submit(
        self,
        job_id: str,
        trace_id: str,
        task_type: str,
        runner: Callable[[Dict, Callable[[str], None]], Dict],
        snapshot: Dict,
        failure_code: str,
        failure_message: str,
        public_metadata: Optional[Dict] = None,
    ) -> Dict:
        worker_job_id = ""
        now_mono = self._monotonic()
        now_wall = self._wall_clock()
        with self._lock:
            self._cleanup_locked(now_mono)
            existing = self._jobs.get(job_id)
            if existing is not None:
                return self._public_job_locked(existing, now_mono)
            if self._running_count >= self.max_running and len(self._queue) >= self.max_queued:
                raise AdapterError(
                    "LONG_TASK_QUEUE_FULL",
                    "当前后台任务较多，排队已满，请等待已有任务完成后重试。",
                    status_code=429,
                )

            status = "running" if self._running_count < self.max_running else "queued"
            phase = "preparing" if status == "running" else "queued"
            job = {
                "jobId": job_id,
                "traceId": trace_id,
                "taskType": task_type,
                "status": status,
                "phase": phase,
                "createdAt": now_wall,
                "updatedAt": now_wall,
                "_createdMonotonic": now_mono,
                "_updatedMonotonic": now_mono,
                "_phaseStartedMonotonic": now_mono,
                "_phaseDurations": {},
                "_terminalAtMonotonic": None,
                "_runner": runner,
                "_snapshot": deepcopy(snapshot),
                "_failureCode": failure_code,
                "_failureMessage": failure_message,
                "_publicMetadata": deepcopy(public_metadata or {}),
                "result": None,
                "error": None,
            }
            job["_snapshot"].setdefault("traceId", trace_id)
            self._jobs[job_id] = job
            if status == "running":
                self._running_count += 1
                worker_job_id = job_id
            else:
                self._queue.append(job_id)
            public_job = self._public_job_locked(job, now_mono)

        if worker_job_id:
            self._start_worker(worker_job_id)
        return public_job

    def get(self, job_id: str) -> Optional[Dict]:
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            job = self._jobs.get(job_id)
            return self._public_job_locked(job, now_mono) if job else None

    def cancel(self, job_id: str) -> Optional[Dict]:
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] != "queued":
                raise AdapterError(
                    "LONG_TASK_NOT_CANCELLABLE",
                    "只有仍在排队的任务可以取消；任务一旦开始运行，模型后台无法可靠取消。",
                    status_code=409,
                )
            try:
                self._queue.remove(job_id)
            except ValueError:
                raise AdapterError(
                    "LONG_TASK_NOT_CANCELLABLE",
                    "任务已离开排队队列，无法取消。",
                    status_code=409,
                )
            self._finish_locked(job, "cancelled", now_mono)
            self._trim_terminal_locked()
            return self._public_job_locked(job, now_mono)

    def diagnostics(self) -> Dict:
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            terminal_jobs = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job["status"] in TERMINAL_STATUSES
                ),
                key=lambda item: item.get("_terminalAtMonotonic") or 0,
                reverse=True,
            )
            return {
                "maxRunning": self.max_running,
                "maxQueued": self.max_queued,
                "runningCount": self._running_count,
                "queuedCount": len(self._queue),
                "terminalCount": len(terminal_jobs),
                "terminalTtlSeconds": self.terminal_ttl_seconds,
                "maxTerminalJobs": self.max_terminal_jobs,
                "recentTerminalJobs": [
                    self._terminal_diagnostic(job) for job in terminal_jobs[:10]
                ],
            }

    def _start_worker(self, job_id: str) -> None:
        worker = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        worker.start()

    def _run(self, job_id: str) -> None:
        next_job_id = ""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "running":
                return
            runner = job["_runner"]
            snapshot = job["_snapshot"]

        def progress(phase: str) -> None:
            if phase not in PUBLIC_PHASES or phase in {"queued", "completed", "failed", "cancelled"}:
                return
            now = self._monotonic()
            with self._lock:
                current = self._jobs.get(job_id)
                if current is not None and current["status"] == "running":
                    self._transition_phase_locked(current, phase, now)

        result = None
        error = None
        try:
            result = runner(snapshot, progress)
        except Exception:
            error = {
                "code": str(job.get("_failureCode") or "LONG_TASK_FAILED"),
                "message": str(job.get("_failureMessage") or "后台任务执行失败。"),
            }
        finally:
            snapshot = None
            runner = None

        now_mono = self._monotonic()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "running":
                return
            if error is None:
                job["result"] = result
                self._finish_locked(job, "completed", now_mono)
            else:
                job["error"] = error
                self._finish_locked(job, "failed", now_mono)
            self._running_count = max(self._running_count - 1, 0)
            next_job_id = self._promote_next_locked(now_mono)
            self._trim_terminal_locked()

        if next_job_id:
            self._start_worker(next_job_id)

    def _promote_next_locked(self, now_mono: float) -> str:
        while self._queue and self._running_count < self.max_running:
            job_id = self._queue.popleft()
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "queued":
                continue
            job["status"] = "running"
            self._transition_phase_locked(job, "preparing", now_mono)
            self._running_count += 1
            return job_id
        return ""

    def _transition_phase_locked(self, job: Dict, phase: str, now_mono: float) -> None:
        current_phase = job.get("phase", "")
        if current_phase == phase:
            return
        phase_started = job.get("_phaseStartedMonotonic", now_mono)
        if current_phase:
            durations = job["_phaseDurations"]
            durations[current_phase] = durations.get(current_phase, 0.0) + max(
                now_mono - phase_started,
                0.0,
            )
        job["phase"] = phase
        job["_phaseStartedMonotonic"] = now_mono
        job["_updatedMonotonic"] = now_mono
        job["updatedAt"] = self._wall_clock()

    def _finish_locked(self, job: Dict, status: str, now_mono: float) -> None:
        job["status"] = status
        self._transition_phase_locked(job, status, now_mono)
        job["_terminalAtMonotonic"] = now_mono
        job["_runner"] = None
        job["_snapshot"] = None

    def _cleanup_locked(self, now_mono: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job["status"] in TERMINAL_STATUSES
            and job.get("_terminalAtMonotonic") is not None
            and now_mono - job["_terminalAtMonotonic"] > self.terminal_ttl_seconds
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)
        self._trim_terminal_locked()

    def _trim_terminal_locked(self) -> None:
        terminal = sorted(
            (
                job
                for job in self._jobs.values()
                if job["status"] in TERMINAL_STATUSES
            ),
            key=lambda item: item.get("_terminalAtMonotonic") or 0,
        )
        while len(terminal) > self.max_terminal_jobs:
            self._jobs.pop(terminal.pop(0)["jobId"], None)

    def _public_job_locked(self, job: Dict, now_mono: float) -> Dict:
        terminal_at = job.get("_terminalAtMonotonic")
        elapsed_until = terminal_at if terminal_at is not None else now_mono
        phase_elapsed = 0.0
        if terminal_at is None:
            phase_elapsed = max(now_mono - job.get("_phaseStartedMonotonic", now_mono), 0.0)
        durations = dict(job.get("_phaseDurations", {}))
        if phase_elapsed:
            phase = job.get("phase", "")
            durations[phase] = durations.get(phase, 0.0) + phase_elapsed
        queue_position = None
        if job["status"] == "queued":
            try:
                queue_position = list(self._queue).index(job["jobId"]) + 1
            except ValueError:
                queue_position = None
        public_job = {
            "jobId": job["jobId"],
            "traceId": job["traceId"],
            "status": job["status"],
            "phase": job["phase"],
            "createdAt": job["createdAt"],
            "updatedAt": job["updatedAt"],
            "elapsedSeconds": int(max(elapsed_until - job["_createdMonotonic"], 0.0)),
            "phaseElapsedSeconds": int(phase_elapsed),
            "phaseDurations": {
                phase: int(max(duration, 0.0))
                for phase, duration in durations.items()
            },
            "heartbeatAgeSeconds": int(
                max(now_mono - job.get("_updatedMonotonic", now_mono), 0.0)
            ),
            "queuePosition": queue_position,
            "canCancel": job["status"] == "queued",
        }
        public_job.update(job.get("_publicMetadata", {}))
        if job["status"] in TERMINAL_STATUSES:
            public_job.pop("runningMessage", None)
        if job.get("result") is not None:
            public_job["result"] = job["result"]
        if job.get("error") is not None:
            public_job["error"] = job["error"]
        return public_job

    def _terminal_diagnostic(self, job: Dict) -> Dict:
        terminal_at = job.get("_terminalAtMonotonic")
        elapsed_until = (
            terminal_at
            if terminal_at is not None
            else job.get("_updatedMonotonic", job["_createdMonotonic"])
        )
        error = job.get("error") if isinstance(job.get("error"), dict) else {}
        return {
            "jobId": job["jobId"],
            "traceId": job["traceId"],
            "taskType": job["taskType"],
            "status": job["status"],
            "phase": job["phase"],
            "elapsedSeconds": int(
                max(elapsed_until - job["_createdMonotonic"], 0.0)
            ),
            "phaseDurations": {
                phase: int(max(duration, 0.0))
                for phase, duration in job.get("_phaseDurations", {}).items()
            },
            "errorCode": str(error.get("code", "")),
        }


_SHARED_COORDINATOR = LongTaskCoordinator(
    max_running=_positive_int_from_env(
        "AI_WPS_LONG_TASK_MAX_RUNNING", DEFAULT_MAX_RUNNING
    ),
    max_queued=_positive_int_from_env(
        "AI_WPS_LONG_TASK_MAX_QUEUED", DEFAULT_MAX_QUEUED
    ),
    terminal_ttl_seconds=_positive_int_from_env(
        "AI_WPS_LONG_TASK_TERMINAL_TTL_SECONDS", DEFAULT_TERMINAL_TTL_SECONDS
    ),
    max_terminal_jobs=_positive_int_from_env(
        "AI_WPS_LONG_TASK_MAX_TERMINAL_JOBS", DEFAULT_MAX_TERMINAL_JOBS
    ),
)


def get_long_task_coordinator() -> LongTaskCoordinator:
    return _SHARED_COORDINATOR
