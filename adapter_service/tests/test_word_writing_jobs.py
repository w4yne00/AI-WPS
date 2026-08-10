import threading
import time
import unittest

from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.writing_jobs import SmartImitationJobStore, SmartWriteJobStore


def make_request(client_job_id):
    payload = {
        "documentId": "writing-test.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": client_job_id,
        "content": {
            "plainText": "待处理文本。",
            "paragraphs": [],
            "headings": [],
        },
        "options": {},
    }
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class BlockingWritingWorker:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def snapshot_task_auth(self):
        return {"configurationId": "snapshot-config"}

    def _run(self, request, trace_id, task_auth, progress_callback):
        self.calls.append((request.client_job_id, trace_id, task_auth))
        progress_callback("provider_processing")
        self.started.set()
        self.release.wait(timeout=2)
        progress_callback("parsing")
        return {
            "originalText": request.content.plain_text,
            "rewrittenText": "处理完成。",
            "rewriteMode": "rewrite",
        }

    def smart_write(self, request, **kwargs):
        return self._run(request, **kwargs)

    def imitate(self, request, **kwargs):
        return self._run(request, **kwargs)


class WritingJobStoreTests(unittest.TestCase):
    def wait_completed(self, store, job_id):
        latest = None
        for _ in range(100):
            latest = store.get(job_id)
            if latest and latest["status"] == "completed":
                return latest
            time.sleep(0.01)
        self.fail("writing job did not complete: {0}".format(latest))

    def test_smart_write_job_is_idempotent_and_uses_submission_snapshot(self):
        worker = BlockingWritingWorker()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)
        request = make_request("client-smart-write-test-1234")

        started = store.start(request, "trace-first")
        duplicate = store.start(request, "trace-second")

        self.assertEqual(started["jobId"], "client-smart-write-test-1234")
        self.assertEqual(duplicate["traceId"], "trace-first")
        self.assertTrue(worker.started.wait(timeout=1))
        worker.release.set()
        completed = self.wait_completed(store, started["jobId"])
        self.assertEqual(completed["result"]["rewrittenText"], "处理完成。")
        self.assertEqual(worker.calls[0][2], {"configurationId": "snapshot-config"})

    def test_smart_imitation_job_returns_completed_result(self):
        worker = BlockingWritingWorker()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = SmartImitationJobStore(worker=worker, coordinator=coordinator)
        request = make_request("client-imitation-test-1234")

        started = store.start(request, "trace-imitation")
        self.assertTrue(worker.started.wait(timeout=1))
        worker.release.set()
        completed = self.wait_completed(store, started["jobId"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["rewrittenText"], "处理完成。")


if __name__ == "__main__":
    unittest.main()
