import os
import threading
import time
from collections import deque
from copy import deepcopy
from typing import Callable, Deque, Dict, Optional, Set, Tuple

from app.core.errors import AdapterError


DEFAULT_MAX_RUNNING = 2
DEFAULT_MAX_QUEUED = 8
DEFAULT_TERMINAL_TTL_SECONDS = 2 * 60 * 60
DEFAULT_MAX_TERMINAL_JOBS = 50
PUBLIC_PHASES = {
    "queued",
    "preparing",
    "extracting",
    "confirming",
    "chunking",
    "uploading",
    "provider_processing",
    "retrying",
    "splitting",
    "parsing",
    "aggregating",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
PRIORITY_REGULAR = "regular"
PRIORITY_INTERACTIVE = "interactive"
INTERACTIVE_BURST_LIMIT = 3
JobKey = Tuple[str, str]


class LongTaskCancelled(Exception):
    """Signals cooperative cancellation after an in-flight call returns."""

    def __init__(self, partial_result: Optional[Dict] = None) -> None:
        super().__init__()
        self.partial_result = deepcopy(partial_result) if partial_result is not None else None


class LongTaskContinuation:
    """Requests that a running task yield its slot and resume with new state."""

    def __init__(self, snapshot: Dict, phase: str = "queued") -> None:
        self.snapshot = deepcopy(snapshot)
        self.phase = phase if phase in PUBLIC_PHASES else "queued"


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
        self._jobs: Dict[JobKey, Dict] = {}
        self._queue: Deque[JobKey] = deque()
        self._deferred: Deque[JobKey] = deque()
        self._running_count = 0
        self._cancelled_count = 0
        self._rejected_count = 0
        self._timed_out_count = 0
        self._interactive_dispatch_streak = 0
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

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
        safe_failure_codes: Optional[Set[str]] = None,
        priority_class: str = PRIORITY_REGULAR,
        allow_running_cancel: bool = False,
        request_fingerprint: Optional[str] = None,
        request_conflict_code: str = "LONG_TASK_JOB_ID_CONFLICT",
        request_conflict_message: str = "相同任务编号已绑定其他请求，请使用新的任务编号。",
    ) -> Dict:
        worker_job_key: Optional[JobKey] = None
        now_mono = self._monotonic()
        now_wall = self._wall_clock()
        job_key = (task_type, job_id)
        normalized_priority = (
            PRIORITY_INTERACTIVE
            if priority_class == PRIORITY_INTERACTIVE
            else PRIORITY_REGULAR
        )
        with self._lock:
            self._cleanup_locked(now_mono)
            existing = self._jobs.get(job_key)
            if existing is not None:
                stored_fingerprint = existing.get("_requestFingerprint")
                if (
                    request_fingerprint
                    and stored_fingerprint
                    and stored_fingerprint != request_fingerprint
                ):
                    raise AdapterError(
                        request_conflict_code,
                        request_conflict_message,
                        status_code=409,
                    )
                return self._public_job_locked(existing, now_mono)
            if self._running_count >= self.max_running and len(self._queue) >= self.max_queued:
                self._rejected_count += 1
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
                "_safeFailureCodes": set(safe_failure_codes or set()),
                "_publicMetadata": deepcopy(public_metadata or {}),
                "_priorityClass": normalized_priority,
                "_requestFingerprint": request_fingerprint or "",
                "_allowRunningCancel": bool(allow_running_cancel),
                "_cancelRequested": False,
                "_occupiesSlot": status == "running",
                "result": None,
                "error": None,
            }
            job["_snapshot"].setdefault("traceId", trace_id)
            self._jobs[job_key] = job
            if status == "running":
                self._running_count += 1
                worker_job_key = job_key
            else:
                self._queue.append(job_key)
            public_job = self._public_job_locked(job, now_mono)

        if worker_job_key is not None:
            self._start_worker(worker_job_key)
        return public_job

    def get(self, job_id: str, task_type: Optional[str] = None) -> Optional[Dict]:
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            job_key = self._find_job_key_locked(job_id, task_type)
            job = self._jobs.get(job_key) if job_key is not None else None
            return self._public_job_locked(job, now_mono) if job else None

    def get_request_fingerprint(
        self, job_id: str, task_type: Optional[str] = None
    ) -> Optional[str]:
        """Return an internal idempotency fingerprint without exposing job data."""
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            job_key = self._find_job_key_locked(job_id, task_type)
            job = self._jobs.get(job_key) if job_key is not None else None
            if job is None:
                return None
            return str(job.get("_requestFingerprint") or "") or None

    def wait(self, job_id: str, task_type: Optional[str] = None) -> Optional[Dict]:
        """Wait for one accepted job without bypassing the shared capacity boundary."""
        with self._condition:
            while True:
                now_mono = self._monotonic()
                self._cleanup_locked(now_mono)
                job_key = self._find_job_key_locked(job_id, task_type)
                job = self._jobs.get(job_key) if job_key is not None else None
                if job is None:
                    return None
                if job["status"] in TERMINAL_STATUSES:
                    return self._public_job_locked(job, now_mono)
                self._condition.wait()

    def wait_result(
        self,
        job_id: str,
        task_type: str,
        not_found_code: str,
        not_found_message: str,
        cancelled_message: str,
        failure_code: str,
        failure_message: str,
        safe_error_statuses: Optional[Dict[str, int]] = None,
    ) -> Dict:
        """Wait for a terminal job and translate its public terminal state once."""
        terminal = self.wait(job_id, task_type=task_type)
        if terminal is None:
            raise AdapterError(not_found_code, not_found_message, status_code=404)
        if terminal["status"] == "completed":
            return terminal.get("result") or {}
        if terminal["status"] == "cancelled":
            raise AdapterError(
                "LONG_TASK_CANCELLED", cancelled_message, status_code=409
            )
        error = terminal.get("error") or {}
        code = str(error.get("code") or failure_code)
        message = str(error.get("message") or failure_message)
        status_code = (safe_error_statuses or {}).get(code, 502)
        raise AdapterError(code, message, status_code=status_code)

    def cancel(self, job_id: str, task_type: Optional[str] = None) -> Optional[Dict]:
        now_mono = self._monotonic()
        with self._lock:
            self._cleanup_locked(now_mono)
            job_key = self._find_job_key_locked(job_id, task_type)
            job = self._jobs.get(job_key) if job_key is not None else None
            if job is None:
                return None
            if job["status"] != "queued":
                raise AdapterError(
                    "LONG_TASK_NOT_CANCELLABLE",
                    "只有仍在排队的任务可以取消；任务一旦开始运行，模型后台无法可靠取消。",
                    status_code=409,
                )
            try:
                self._queue.remove(job_key)
            except ValueError:
                raise AdapterError(
                    "LONG_TASK_NOT_CANCELLABLE",
                    "任务已离开排队队列，无法取消。",
                    status_code=409,
                )
            self._finish_locked(job, "cancelled", now_mono)
            self._cancelled_count += 1
            self._trim_terminal_locked()
            self._condition.notify_all()
            return self._public_job_locked(job, now_mono)

    def request_cancel(
        self, job_id: str, task_type: Optional[str] = None
    ) -> Optional[Dict]:
        """Atomically cancel a queued job or request cooperative running cancellation."""
        now_mono = self._monotonic()
        next_job_key: Optional[JobKey] = None
        public_job: Optional[Dict] = None
        with self._lock:
            self._cleanup_locked(now_mono)
            job_key = self._find_job_key_locked(job_id, task_type)
            job = self._jobs.get(job_key) if job_key is not None else None
            if job is None:
                return None
            if job["status"] == "queued":
                try:
                    self._queue.remove(job_key)
                except ValueError:
                    raise AdapterError(
                        "LONG_TASK_NOT_CANCELLABLE",
                        "任务已离开排队队列，无法取消。",
                        status_code=409,
                    )
                self._finish_locked(job, "cancelled", now_mono)
                self._cancelled_count += 1
                self._trim_terminal_locked()
                self._condition.notify_all()
                return self._public_job_locked(job, now_mono)
            if job["status"] == "running" and job.get("_allowRunningCancel"):
                if not job.get("_occupiesSlot"):
                    try:
                        self._deferred.remove(job_key)
                    except ValueError:
                        pass
                    self._finish_locked(job, "cancelled", now_mono)
                    self._cancelled_count += 1
                    next_job_key = self._promote_next_locked(now_mono)
                else:
                    job["_cancelRequested"] = True
                    job["_updatedMonotonic"] = now_mono
                    job["updatedAt"] = self._wall_clock()
                public_job = self._public_job_locked(job, now_mono)
            elif job["status"] in TERMINAL_STATUSES:
                return self._public_job_locked(job, now_mono)
            else:
                raise AdapterError(
                    "LONG_TASK_NOT_CANCELLABLE",
                    "当前任务状态不允许取消。",
                    status_code=409,
                )
            self._trim_terminal_locked()
            self._condition.notify_all()
        if next_job_key is not None:
            self._start_worker(next_job_key)
        return public_job

    def is_cancel_requested(
        self, job_id: str, task_type: Optional[str] = None
    ) -> bool:
        with self._lock:
            job_key = self._find_job_key_locked(job_id, task_type)
            job = self._jobs.get(job_key) if job_key is not None else None
            return bool(
                job
                and job.get("status") == "running"
                and job.get("_cancelRequested")
            )

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
                "deferredCount": sum(
                    1
                    for job_key in self._deferred
                    if self._jobs.get(job_key, {}).get("status") == "running"
                ),
                "interactiveQueuedCount": sum(
                    1
                    for job_key in self._queue
                    if self._jobs.get(job_key, {}).get("_priorityClass")
                    == PRIORITY_INTERACTIVE
                ),
                "regularQueuedCount": sum(
                    1
                    for job_key in self._queue
                    if self._jobs.get(job_key, {}).get("_priorityClass")
                    != PRIORITY_INTERACTIVE
                ),
                "terminalCount": len(terminal_jobs),
                "terminalTtlSeconds": self.terminal_ttl_seconds,
                "maxTerminalJobs": self.max_terminal_jobs,
                "cancelledCount": self._cancelled_count,
                "rejectedCount": self._rejected_count,
                "timedOutCount": self._timed_out_count,
                "recentTerminalJobs": [
                    self._terminal_diagnostic(job) for job in terminal_jobs[:10]
                ],
            }

    def _start_worker(self, job_key: JobKey) -> None:
        worker = threading.Thread(target=self._run, args=(job_key,), daemon=True)
        worker.start()

    def _run(self, job_key: JobKey) -> None:
        next_job_key: Optional[JobKey] = None
        with self._lock:
            job = self._jobs.get(job_key)
            if job is None or job["status"] != "running":
                return
            runner = job["_runner"]
            snapshot = job["_snapshot"]

        def progress(phase: str) -> None:
            if phase not in PUBLIC_PHASES or phase in {"queued", "completed", "failed", "cancelled"}:
                return
            now = self._monotonic()
            with self._lock:
                current = self._jobs.get(job_key)
                if current is not None and current["status"] == "running":
                    self._transition_phase_locked(current, phase, now)

        result = None
        error = None
        cancelled = False
        cancelled_result = None
        continuation = None
        try:
            result = runner(snapshot, progress)
            if isinstance(result, LongTaskContinuation):
                continuation = result
        except LongTaskCancelled as exc:
            cancelled = True
            cancelled_result = exc.partial_result
        except Exception as exc:
            diagnostic_error_code = (
                exc.code if isinstance(exc, AdapterError) else ""
            )
            partial_result = getattr(exc, "partial_result", None)
            if (
                isinstance(exc, AdapterError)
                and exc.code in job.get("_safeFailureCodes", set())
            ):
                error = {"code": exc.code, "message": exc.message}
            else:
                error = {
                    "code": str(job.get("_failureCode") or "LONG_TASK_FAILED"),
                    "message": str(job.get("_failureMessage") or "后台任务执行失败。"),
                }
            if partial_result is not None:
                error["_partialResult"] = deepcopy(partial_result)
            if diagnostic_error_code:
                error["_diagnosticCode"] = diagnostic_error_code
        finally:
            snapshot = None
            runner = None

        now_mono = self._monotonic()
        with self._lock:
            job = self._jobs.get(job_key)
            if job is None or job["status"] != "running":
                return
            cancel_requested = bool(job.get("_cancelRequested"))
            if (
                not cancelled
                and cancel_requested
                and continuation is None
                and error is None
                and result is not None
            ):
                # The runner completed before the cancellation request was
                # observed at commit time. Keep the completed result instead
                # of converting it into a cancelled job with no payload.
                job["result"] = result
                self._finish_locked(job, "completed", now_mono)
                self._running_count = max(self._running_count - 1, 0)
            elif cancelled or cancel_requested:
                job["result"] = cancelled_result
                self._finish_locked(job, "cancelled", now_mono)
                self._cancelled_count += 1
                self._running_count = max(self._running_count - 1, 0)
            elif continuation is not None:
                job["_snapshot"] = continuation.snapshot
                job["_occupiesSlot"] = False
                self._transition_phase_locked(job, continuation.phase, now_mono)
                self._running_count = max(self._running_count - 1, 0)
                self._deferred.append(job_key)
                next_job_key = self._promote_next_locked(now_mono)
            elif error is None:
                job["result"] = result
                self._finish_locked(job, "completed", now_mono)
                self._running_count = max(self._running_count - 1, 0)
            else:
                diagnostic_error_code = str(error.pop("_diagnosticCode", ""))
                partial_result = error.pop("_partialResult", None)
                if partial_result is not None:
                    job["result"] = partial_result
                job["error"] = error
                job["_diagnosticErrorCode"] = diagnostic_error_code
                if "TIMEOUT" in diagnostic_error_code.upper():
                    self._timed_out_count += 1
                self._finish_locked(job, "failed", now_mono)
                self._running_count = max(self._running_count - 1, 0)
            if continuation is None:
                next_job_key = self._promote_next_locked(now_mono)
            self._trim_terminal_locked()
            self._condition.notify_all()

        if next_job_key is not None:
            self._start_worker(next_job_key)

    def _promote_next_locked(self, now_mono: float) -> Optional[JobKey]:
        while (self._queue or self._deferred) and self._running_count < self.max_running:
            ordered = self._ordered_queue_locked()
            if not ordered:
                return None
            job_key = ordered[0]
            removed = False
            try:
                self._queue.remove(job_key)
                removed = True
            except ValueError:
                try:
                    self._deferred.remove(job_key)
                    removed = True
                except ValueError:
                    pass
            if not removed:
                continue
            job = self._jobs.get(job_key)
            if job is None or job["status"] not in {"queued", "running"}:
                continue
            if job["status"] == "running" and job.get("_occupiesSlot"):
                continue
            if job.get("_priorityClass") == PRIORITY_INTERACTIVE:
                self._interactive_dispatch_streak += 1
            else:
                self._interactive_dispatch_streak = 0
            job["status"] = "running"
            job["_occupiesSlot"] = True
            self._transition_phase_locked(job, "preparing", now_mono)
            self._running_count += 1
            return job_key
        return None

    def _ordered_queue_locked(self):
        pending = [
            job_key
            for job_key in list(self._deferred) + list(self._queue)
            if (
                self._jobs.get(job_key, {}).get("status") == "queued"
                or (
                    self._jobs.get(job_key, {}).get("status") == "running"
                    and not self._jobs.get(job_key, {}).get("_occupiesSlot")
                )
            )
        ]
        ordered = []
        streak = self._interactive_dispatch_streak
        while pending:
            interactive = [
                key
                for key in pending
                if self._jobs.get(key, {}).get("_priorityClass")
                == PRIORITY_INTERACTIVE
            ]
            regular = [key for key in pending if key not in interactive]
            if interactive and regular:
                if streak >= INTERACTIVE_BURST_LIMIT:
                    selected = regular[0]
                    streak = 0
                else:
                    selected = interactive[0]
                    streak += 1
            elif interactive:
                selected = interactive[0]
                streak += 1
            else:
                selected = regular[0]
                streak = 0
            ordered.append(selected)
            pending.remove(selected)
        return ordered

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
        job["_occupiesSlot"] = False
        self._transition_phase_locked(job, status, now_mono)
        job["_terminalAtMonotonic"] = now_mono
        job["_runner"] = None
        job["_snapshot"] = None

    def _cleanup_locked(self, now_mono: float) -> None:
        expired = [
            job_key
            for job_key, job in self._jobs.items()
            if job["status"] in TERMINAL_STATUSES
            and job.get("_terminalAtMonotonic") is not None
            and now_mono - job["_terminalAtMonotonic"] > self.terminal_ttl_seconds
        ]
        for job_key in expired:
            self._jobs.pop(job_key, None)
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
            job = terminal.pop(0)
            self._jobs.pop((job["taskType"], job["jobId"]), None)

    def _find_job_key_locked(
        self, job_id: str, task_type: Optional[str]
    ) -> Optional[JobKey]:
        if task_type is not None:
            return (task_type, job_id)
        matches = [
            job_key for job_key in self._jobs if job_key[1] == job_id
        ]
        return matches[0] if len(matches) == 1 else None

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
                job_key = (job["taskType"], job["jobId"])
                queued_order = [
                    key
                    for key in self._ordered_queue_locked()
                    if self._jobs.get(key, {}).get("status") == "queued"
                ]
                queue_position = queued_order.index(job_key) + 1
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
            "canCancel": job["status"] == "queued" or bool(
                job["status"] == "running"
                and job.get("_allowRunningCancel")
                and not job.get("_cancelRequested")
            ),
        }
        if job.get("_allowRunningCancel"):
            public_job["cancelRequested"] = bool(job.get("_cancelRequested"))
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
            "errorCode": str(
                job.get("_diagnosticErrorCode") or error.get("code", "")
            ),
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
