import json
import threading
import time
import unittest

from app.core.errors import AdapterError, ProviderTimeoutError
from app.services.long_task_coordinator import (
    PRIORITY_INTERACTIVE,
    LongTaskContinuation,
    LongTaskCoordinator,
)


class FakeClock:
    def __init__(self, initial=100.0):
        self.value = float(initial)
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.value

    def advance(self, seconds):
        with self._lock:
            self.value += float(seconds)


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def __call__(self, snapshot, progress):
        self.calls.append(snapshot["value"])
        progress("provider_processing")
        self.started.set()
        self.release.wait(timeout=3)
        progress("parsing")
        return {"value": snapshot["value"]}


def wait_for_status(coordinator, job_id, expected, timeout=2):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest = coordinator.get(job_id)
        if latest and latest["status"] == expected:
            return latest
        time.sleep(0.01)
    raise AssertionError(
        "job {0} did not reach {1}; latest={2}".format(job_id, expected, latest)
    )


class LongTaskCoordinatorTests(unittest.TestCase):
    def test_continuation_releases_slot_and_interactive_job_runs_before_resume(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        first_slice_ready = threading.Event()
        release_first_slice = threading.Event()
        calls = []

        def review_runner(snapshot, _progress):
            calls.append("review-{0}".format(snapshot["slice"]))
            if snapshot["slice"] == 0:
                first_slice_ready.set()
                self.assertTrue(release_first_slice.wait(timeout=1))
                return LongTaskContinuation({"slice": 1}, phase="queued")
            return {"status": "review-complete"}

        def interactive_runner(snapshot, _progress):
            calls.append(snapshot["name"])
            return {"status": "interactive-complete"}

        coordinator.submit(
            job_id="review-job",
            trace_id="trace-review",
            task_type="word.document_review.full",
            runner=review_runner,
            snapshot={"slice": 0},
            failure_code="REVIEW_FAILED",
            failure_message="review failed",
        )
        self.assertTrue(first_slice_ready.wait(timeout=1))
        queued = coordinator.submit(
            job_id="interactive-job",
            trace_id="trace-interactive",
            task_type="word.smart_write",
            runner=interactive_runner,
            snapshot={"name": "interactive"},
            failure_code="INTERACTIVE_FAILED",
            failure_message="interactive failed",
            priority_class=PRIORITY_INTERACTIVE,
        )
        self.assertEqual(queued["status"], "queued")
        release_first_slice.set()

        review = coordinator.wait("review-job", task_type="word.document_review.full")
        interactive = coordinator.wait("interactive-job", task_type="word.smart_write")
        self.assertEqual(review["status"], "completed")
        self.assertEqual(interactive["status"], "completed")
        self.assertEqual(calls, ["review-0", "interactive", "review-1"])
        self.assertEqual(coordinator.diagnostics()["queuedCount"], 0)

    def test_interactive_jobs_are_prioritized_without_starving_regular_jobs(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=5)
        runners = [BlockingRunner() for _ in range(6)]
        coordinator.submit(
            "running-regular",
            "trace-running",
            "word.document_review",
            runners[0],
            {"value": 0},
            "LONG_TASK_FAILED",
            "后台任务执行失败。",
        )
        self.assertTrue(runners[0].started.wait(timeout=1))
        coordinator.submit(
            "queued-regular",
            "trace-regular",
            "word.document_review",
            runners[1],
            {"value": 1},
            "LONG_TASK_FAILED",
            "后台任务执行失败。",
        )
        for index in range(2, 6):
            coordinator.submit(
                "queued-interactive-{0}".format(index),
                "trace-interactive-{0}".format(index),
                "word.smart_write",
                runners[index],
                {"value": index},
                "LONG_TASK_FAILED",
                "后台任务执行失败。",
                priority_class=PRIORITY_INTERACTIVE,
            )

        self.assertEqual(coordinator.get("queued-interactive-2")["queuePosition"], 1)
        self.assertEqual(coordinator.get("queued-regular")["queuePosition"], 4)

        runners[0].release.set()
        self.assertTrue(runners[2].started.wait(timeout=1))
        runners[2].release.set()
        self.assertTrue(runners[3].started.wait(timeout=1))
        runners[3].release.set()
        self.assertTrue(runners[4].started.wait(timeout=1))
        runners[4].release.set()

        self.assertTrue(runners[1].started.wait(timeout=1))
        self.assertFalse(runners[5].started.is_set())
        runners[1].release.set()
        self.assertTrue(runners[5].started.wait(timeout=1))
        runners[5].release.set()

    def test_mixed_hosts_share_capacity_fifo_cancellation_and_rejection_metrics(self):
        coordinator = LongTaskCoordinator()
        task_types = [
            "word.document_review",
            "excel.analysis",
            "ppt.slide_assistant",
        ]
        runners = [BlockingRunner() for _ in range(11)]

        for index in range(10):
            coordinator.submit(
                job_id="client-cross-host-{0:02d}".format(index),
                trace_id="trace-cross-host-{0:02d}".format(index),
                task_type=task_types[index % len(task_types)],
                runner=runners[index],
                snapshot={"value": index},
                failure_code="LONG_TASK_FAILED",
                failure_message="后台任务执行失败。",
            )

        self.assertTrue(runners[0].started.wait(timeout=1))
        self.assertTrue(runners[1].started.wait(timeout=1))
        self.assertFalse(runners[2].started.is_set())
        self.assertEqual(
            coordinator.get(
                "client-cross-host-02", task_type="ppt.slide_assistant"
            )["queuePosition"],
            1,
        )

        with self.assertRaises(AdapterError) as raised:
            coordinator.submit(
                job_id="client-cross-host-full",
                trace_id="trace-cross-host-full",
                task_type="excel.analysis",
                runner=runners[10],
                snapshot={"value": 10},
                failure_code="LONG_TASK_FAILED",
                failure_message="后台任务执行失败。",
            )
        self.assertEqual(raised.exception.code, "LONG_TASK_QUEUE_FULL")

        cancelled = coordinator.cancel(
            "client-cross-host-03", task_type="word.document_review"
        )
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(
            coordinator.get(
                "client-cross-host-04", task_type="excel.analysis"
            )["queuePosition"],
            2,
        )

        runners[0].release.set()
        self.assertTrue(runners[2].started.wait(timeout=1))
        self.assertFalse(runners[4].started.is_set())

        diagnostics = coordinator.diagnostics()
        self.assertEqual(diagnostics["runningCount"], 2)
        self.assertEqual(diagnostics["queuedCount"], 6)
        self.assertEqual(diagnostics["cancelledCount"], 1)
        self.assertEqual(diagnostics["rejectedCount"], 1)
        self.assertEqual(diagnostics["timedOutCount"], 0)

        for runner in runners:
            runner.release.set()

    def test_defaults_run_two_and_queue_eight_in_fifo_order(self):
        coordinator = LongTaskCoordinator()
        runners = [BlockingRunner() for _ in range(10)]

        for index, runner in enumerate(runners):
            coordinator.submit(
                job_id="client-job-{0:02d}".format(index),
                trace_id="trace-{0:02d}".format(index),
                task_type="word.document_review",
                runner=runner,
                snapshot={"value": index},
                failure_code="DOCUMENT_REVIEW_JOB_FAILED",
                failure_message="文档审查后台任务执行失败。",
            )

        self.assertTrue(runners[0].started.wait(timeout=1))
        self.assertTrue(runners[1].started.wait(timeout=1))
        self.assertEqual(coordinator.get("client-job-00")["status"], "running")
        self.assertEqual(coordinator.get("client-job-01")["status"], "running")
        for index in range(2, 10):
            queued = coordinator.get("client-job-{0:02d}".format(index))
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(queued["queuePosition"], index - 1)
            self.assertTrue(queued["canCancel"])

        with self.assertRaises(AdapterError) as raised:
            coordinator.submit(
                job_id="client-job-full",
                trace_id="trace-full",
                task_type="word.document_review",
                runner=BlockingRunner(),
                snapshot={"value": "full"},
                failure_code="DOCUMENT_REVIEW_JOB_FAILED",
                failure_message="文档审查后台任务执行失败。",
            )
        self.assertEqual(raised.exception.code, "LONG_TASK_QUEUE_FULL")
        self.assertEqual(raised.exception.status_code, 429)

        runners[0].release.set()
        self.assertTrue(runners[2].started.wait(timeout=1))
        self.assertEqual(coordinator.get("client-job-02")["status"], "running")
        self.assertEqual(coordinator.get("client-job-03")["queuePosition"], 1)

        for runner in runners:
            runner.release.set()

    def test_each_completed_runner_promotes_the_next_fifo_job(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        runners = [BlockingRunner() for _ in range(3)]

        for index, runner in enumerate(runners):
            coordinator.submit(
                job_id="client-fifo-{0}".format(index),
                trace_id="trace-fifo-{0}".format(index),
                task_type="word.document_review",
                runner=runner,
                snapshot={"value": index},
                failure_code="DOCUMENT_REVIEW_JOB_FAILED",
                failure_message="文档审查后台任务执行失败。",
            )

        self.assertTrue(runners[0].started.wait(timeout=1))
        runners[0].release.set()
        self.assertTrue(runners[1].started.wait(timeout=1))
        wait_for_status(coordinator, "client-fifo-0", "completed")

        runners[1].release.set()
        self.assertTrue(runners[2].started.wait(timeout=1))
        wait_for_status(coordinator, "client-fifo-1", "completed")

        runners[2].release.set()
        wait_for_status(coordinator, "client-fifo-2", "completed")
        diagnostics = coordinator.diagnostics()
        self.assertEqual(diagnostics["runningCount"], 0)
        self.assertEqual(diagnostics["queuedCount"], 0)

    def test_duplicate_submission_returns_existing_job_without_second_run(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        runner = BlockingRunner()
        first = coordinator.submit(
            job_id="client-idempotent",
            trace_id="trace-first",
            task_type="word.document_review",
            runner=runner,
            snapshot={"value": "first"},
            failure_code="DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="文档审查后台任务执行失败。",
        )
        duplicate = coordinator.submit(
            job_id="client-idempotent",
            trace_id="trace-second",
            task_type="word.document_review",
            runner=runner,
            snapshot={"value": "second"},
            failure_code="DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="文档审查后台任务执行失败。",
        )

        self.assertTrue(runner.started.wait(timeout=1))
        self.assertEqual(first["jobId"], duplicate["jobId"])
        self.assertEqual(duplicate["traceId"], "trace-first")
        self.assertEqual(runner.calls, ["first"])
        runner.release.set()

    def test_running_cancel_race_does_not_discard_completed_runner_result(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        started = threading.Event()
        release = threading.Event()

        def runner(_snapshot, _progress):
            started.set()
            self.assertTrue(release.wait(timeout=1))
            return {"value": "completed-before-cancel-observed"}

        accepted = coordinator.submit(
            job_id="client-cancel-race",
            trace_id="trace-cancel-race",
            task_type="excel.smart_fill",
            runner=runner,
            snapshot={},
            failure_code="SMART_FILL_FAILED",
            failure_message="智能填写失败。",
            allow_running_cancel=True,
        )
        self.assertTrue(started.wait(timeout=1))
        requested = coordinator.request_cancel(
            accepted["jobId"], task_type="excel.smart_fill"
        )
        self.assertTrue(requested["cancelRequested"])
        release.set()

        terminal = coordinator.wait(accepted["jobId"], task_type="excel.smart_fill")
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(
            terminal["result"]["value"], "completed-before-cancel-observed"
        )

    def test_only_queued_job_can_be_cancelled(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        running_runner = BlockingRunner()
        queued_runner = BlockingRunner()
        coordinator.submit(
            "client-running",
            "trace-running",
            "word.document_review",
            running_runner,
            {"value": "running"},
            "DOCUMENT_REVIEW_JOB_FAILED",
            "文档审查后台任务执行失败。",
        )
        self.assertTrue(running_runner.started.wait(timeout=1))
        coordinator.submit(
            "client-queued",
            "trace-queued",
            "word.document_review",
            queued_runner,
            {"value": "queued"},
            "DOCUMENT_REVIEW_JOB_FAILED",
            "文档审查后台任务执行失败。",
        )

        cancelled = coordinator.cancel("client-queued")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["phase"], "cancelled")
        self.assertFalse(cancelled["canCancel"])
        self.assertFalse(queued_runner.started.is_set())

        with self.assertRaises(AdapterError) as raised:
            coordinator.cancel("client-running")
        self.assertEqual(raised.exception.code, "LONG_TASK_NOT_CANCELLABLE")
        self.assertEqual(raised.exception.status_code, 409)
        running_runner.release.set()

    def test_snapshot_phase_timing_and_secret_are_not_exposed(self):
        clock = FakeClock()
        coordinator = LongTaskCoordinator(
            max_running=1,
            max_queued=1,
            monotonic_clock=clock,
            wall_clock=clock,
        )
        release = threading.Event()
        observed = {}

        def runner(snapshot, progress):
            observed.update(snapshot)
            clock.advance(3)
            progress("provider_processing")
            release.wait(timeout=2)
            clock.advance(5)
            progress("parsing")
            clock.advance(2)
            return {"profileId": snapshot["profileId"]}

        original = {
            "profileId": "profile-original",
            "apiKey": "super-secret-key",
            "input": {"plainText": "原始内容"},
        }
        started = coordinator.submit(
            "client-snapshot",
            "trace-snapshot",
            "word.document_review",
            runner,
            original,
            "DOCUMENT_REVIEW_JOB_FAILED",
            "文档审查后台任务执行失败。",
            {"runningMessage": "正在处理。"},
        )
        original["profileId"] = "profile-changed"
        original["apiKey"] = "changed-secret"
        original["input"]["plainText"] = "修改后的内容"

        running = wait_for_status(coordinator, started["jobId"], "running")
        self.assertEqual(running["runningMessage"], "正在处理。")
        self.assertNotIn("super-secret-key", json.dumps(running, ensure_ascii=False))
        release.set()
        completed = wait_for_status(coordinator, started["jobId"], "completed")

        self.assertEqual(observed["profileId"], "profile-original")
        self.assertEqual(observed["apiKey"], "super-secret-key")
        self.assertEqual(observed["input"]["plainText"], "原始内容")
        self.assertEqual(completed["result"]["profileId"], "profile-original")
        self.assertEqual(completed["phase"], "completed")
        self.assertEqual(completed["elapsedSeconds"], 10)
        self.assertEqual(completed["phaseDurations"]["preparing"], 3)
        self.assertEqual(completed["phaseDurations"]["provider_processing"], 5)
        self.assertEqual(completed["phaseDurations"]["parsing"], 2)
        self.assertNotIn("runningMessage", completed)
        self.assertNotIn("super-secret-key", json.dumps(completed, ensure_ascii=False))
        self.assertNotIn("changed-secret", json.dumps(completed, ensure_ascii=False))

    def test_terminal_jobs_expire_by_monotonic_ttl_and_capacity(self):
        clock = FakeClock()
        coordinator = LongTaskCoordinator(
            max_running=1,
            max_queued=1,
            terminal_ttl_seconds=7200,
            max_terminal_jobs=2,
            monotonic_clock=clock,
            wall_clock=clock,
        )

        def finish(value):
            job_id = "client-terminal-{0}".format(value)
            coordinator.submit(
                job_id,
                "trace-terminal-{0}".format(value),
                "word.document_review",
                lambda snapshot, progress: {"value": snapshot["value"]},
                {"value": value},
                "DOCUMENT_REVIEW_JOB_FAILED",
                "文档审查后台任务执行失败。",
            )
            wait_for_status(coordinator, job_id, "completed")
            clock.advance(1)
            return job_id

        first = finish(1)
        second = finish(2)
        third = finish(3)

        self.assertIsNone(coordinator.get(first))
        self.assertIsNotNone(coordinator.get(second))
        self.assertIsNotNone(coordinator.get(third))

        clock.advance(7201)
        self.assertIsNone(coordinator.get(second))
        self.assertIsNone(coordinator.get(third))

    def test_terminal_cleanup_never_evicts_running_or_queued_jobs(self):
        clock = FakeClock()
        coordinator = LongTaskCoordinator(
            max_running=1,
            max_queued=2,
            terminal_ttl_seconds=1,
            max_terminal_jobs=1,
            monotonic_clock=clock,
            wall_clock=clock,
        )
        running = BlockingRunner()
        queued = BlockingRunner()

        coordinator.submit(
            "client-active-running",
            "trace-active-running",
            "word.document_review",
            running,
            {"value": "running"},
            "DOCUMENT_REVIEW_JOB_FAILED",
            "文档审查后台任务执行失败。",
        )
        self.assertTrue(running.started.wait(timeout=1))
        coordinator.submit(
            "client-active-queued",
            "trace-active-queued",
            "excel.analysis",
            queued,
            {"value": "queued"},
            "EXCEL_ANALYSIS_JOB_FAILED",
            "智能分析后台任务执行失败。",
        )

        clock.advance(7201)
        diagnostics = coordinator.diagnostics()

        self.assertEqual(diagnostics["runningCount"], 1)
        self.assertEqual(diagnostics["queuedCount"], 1)
        self.assertEqual(
            coordinator.get(
                "client-active-running", task_type="word.document_review"
            )["status"],
            "running",
        )
        self.assertEqual(
            coordinator.get(
                "client-active-queued", task_type="excel.analysis"
            )["status"],
            "queued",
        )

        running.release.set()
        queued.release.set()

    def test_runner_failure_does_not_expose_exception_or_snapshot_secret(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def fail(snapshot, progress):
            raise RuntimeError("failed with {0}".format(snapshot["apiKey"]))

        coordinator.submit(
            "client-secret-failure",
            "trace-secret-failure",
            "word.document_review",
            fail,
            {"apiKey": "never-expose-this-key"},
            "DOCUMENT_REVIEW_JOB_FAILED",
            "文档审查后台任务执行失败。",
        )
        failed = wait_for_status(
            coordinator, "client-secret-failure", "failed"
        )
        public_text = json.dumps(failed, ensure_ascii=False)
        diagnostics_text = json.dumps(coordinator.diagnostics(), ensure_ascii=False)

        self.assertEqual(failed["error"]["code"], "DOCUMENT_REVIEW_JOB_FAILED")
        self.assertNotIn("never-expose-this-key", public_text)
        self.assertNotIn("never-expose-this-key", diagnostics_text)
        diagnostics = coordinator.diagnostics()
        self.assertEqual(diagnostics["maxRunning"], 1)
        self.assertEqual(diagnostics["maxQueued"], 1)
        self.assertEqual(
            diagnostics["recentTerminalJobs"][0]["errorCode"],
            "DOCUMENT_REVIEW_JOB_FAILED",
        )
        self.assertNotIn("result", diagnostics["recentTerminalJobs"][0])
        self.assertNotIn("error", diagnostics["recentTerminalJobs"][0])

    def test_timeout_diagnostics_count_sanitized_provider_error_code(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def fail(snapshot, progress):
            raise ProviderTimeoutError(
                "处理 {0} 和文件 {1} 时超时".format(
                    snapshot["plainText"], snapshot["fileName"]
                )
            )

        coordinator.submit(
            "client-timeout",
            "trace-timeout",
            "ppt.slide_assistant",
            fail,
            {
                "apiKey": "never-expose-timeout-key",
                "plainText": "不应出现在诊断中的文档正文",
                "formula": "=SUM(A1:A99)",
                "fileName": "完整上传文件名-机密项目.docx",
            },
            "PPT_SLIDE_JOB_FAILED",
            "智能总结后台任务执行失败。",
        )
        failed = wait_for_status(coordinator, "client-timeout", "failed")
        diagnostics = coordinator.diagnostics()
        diagnostic_text = json.dumps(diagnostics, ensure_ascii=False)

        self.assertEqual(failed["error"]["code"], "PPT_SLIDE_JOB_FAILED")
        self.assertEqual(diagnostics["timedOutCount"], 1)
        self.assertEqual(
            diagnostics["recentTerminalJobs"][0]["errorCode"],
            "PROVIDER_TIMEOUT",
        )
        self.assertNotIn("never-expose-timeout-key", diagnostic_text)
        self.assertNotIn("不应出现在诊断中的文档正文", diagnostic_text)
        self.assertNotIn("=SUM(A1:A99)", diagnostic_text)
        self.assertNotIn("完整上传文件名-机密项目.docx", diagnostic_text)


if __name__ == "__main__":
    unittest.main()
