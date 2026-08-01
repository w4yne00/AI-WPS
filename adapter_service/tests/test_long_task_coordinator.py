import json
import threading
import time
import unittest

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskCoordinator


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
        )
        original["profileId"] = "profile-changed"
        original["apiKey"] = "changed-secret"
        original["input"]["plainText"] = "修改后的内容"

        running = wait_for_status(coordinator, started["jobId"], "running")
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


if __name__ == "__main__":
    unittest.main()
