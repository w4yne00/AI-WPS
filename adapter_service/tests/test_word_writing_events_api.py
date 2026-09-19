import json
import threading
import time
import unittest
from io import BytesIO
from unittest.mock import patch

from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.writing_jobs import SmartWriteJobStore


class BlockingWritingWorker:
    def __init__(self):
        self.started = threading.Event()
        self.step_event = threading.Event()
        self.release_event = threading.Event()

    def snapshot_task_auth(self):
        return {"configurationId": "test-config"}

    def smart_write(self, request, trace_id="", task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        self.started.set()
        self.step_event.wait(timeout=2)
        if progress_callback:
            progress_callback("parsing")
        self.release_event.wait(timeout=2)
        return {
            "originalText": request.content.plain_text,
            "rewrittenText": "处理完成结果。",
            "rewriteMode": "rewrite",
        }

    imitate = smart_write



def make_request_dict(client_job_id):
    return {
        "documentId": "test-doc.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": client_job_id,
        "documentSessionId": "session-1",
        "documentDisplayName": "test.docx",
        "host": "wps",
        "content": {
            "plainText": "原文",
            "paragraphs": [],
            "headings": [],
        },
        "options": {},
    }


class WordWritingEventsApiTests(unittest.TestCase):
    def setUp(self):
        import app.api.word as word_api
        import standalone_adapter

        self.worker = BlockingWritingWorker()
        self.coordinator = LongTaskCoordinator(max_running=2, max_queued=4)
        self.store = SmartWriteJobStore(worker=self.worker, coordinator=self.coordinator)

        self.orig_fastapi_store = word_api.smart_write_jobs
        self.orig_standalone_store = standalone_adapter.SMART_WRITE_JOB_STORE

        word_api.smart_write_jobs = self.store
        standalone_adapter.SMART_WRITE_JOB_STORE = self.store

    def tearDown(self):
        import app.api.word as word_api
        import standalone_adapter

        self.worker.step_event.set()
        self.worker.release_event.set()

        word_api.smart_write_jobs = self.orig_fastapi_store
        standalone_adapter.SMART_WRITE_JOB_STORE = self.orig_standalone_store

    def _invoke_standalone(self, method, path, payload=None):
        import standalone_adapter

        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)
        getattr(handler, method)()
        return captured

    def _invoke_fastapi(self, method, path, payload=None):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        if method == "GET":
            resp = client.get(path)
        elif method == "POST":
            resp = client.post(path, json=payload)
        elif method == "DELETE":
            resp = client.delete(path)
        else:
            raise ValueError(method)
        return {
            "status": resp.status_code,
            "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
        }

    def test_missing_job_returns_404_on_fastapi_and_standalone(self):
        # 1. FastAPI 404
        fa_res = self._invoke_fastapi("GET", "/word/smart-write/jobs/non-existent-job-id/events")
        self.assertEqual(fa_res["status"], 404)
        self.assertFalse(fa_res["body"]["success"])
        self.assertEqual(fa_res["body"]["data"]["status"], "not_found")
        self.assertIn("NOT_FOUND", fa_res["body"]["errors"][0]["code"])

        # 2. Standalone 404
        sa_res = self._invoke_standalone("do_GET", "/word/smart-write/jobs/non-existent-job-id/events")
        self.assertEqual(sa_res["status"], 404)
        self.assertFalse(sa_res["body"]["success"])
        self.assertEqual(sa_res["body"]["data"]["status"], "not_found")
        self.assertIn("NOT_FOUND", sa_res["body"]["errors"][0]["code"])
        self.assertEqual(sa_res["body"], fa_res["body"])

    def test_invalid_event_query_returns_equivalent_validation_error(self):
        paths = (
            "/word/smart-write/jobs/non-existent-job-id/events?afterSequence=invalid",
            "/word/smart-write/jobs/non-existent-job-id/events?waitMs=invalid",
        )
        for path in paths:
            with self.subTest(path=path):
                fa_res = self._invoke_fastapi("GET", path)
                sa_res = self._invoke_standalone("do_GET", path)

                self.assertEqual(fa_res["status"], 422)
                self.assertEqual(sa_res["status"], 422)
                self.assertEqual(
                    fa_res["body"]["errors"][0]["code"],
                    "REQUEST_VALIDATION_FAILED",
                )
                self.assertEqual(
                    sa_res["body"]["errors"][0]["code"],
                    "REQUEST_VALIDATION_FAILED",
                )
                self.assertEqual(sa_res["body"]["taskType"], fa_res["body"]["taskType"])
                self.assertEqual(sa_res["body"]["message"], fa_res["body"]["message"])

    def test_events_long_polling_parity_between_fastapi_and_standalone(self):
        job_req = make_request_dict("smart-write-events-job-001")
        req_obj = WordDocumentRequest(**job_req)
        self.store.start(req_obj, "trace-events-001")
        self.assertTrue(self.worker.started.wait(timeout=2))

        # Initial query (afterSequence=0) on FastAPI
        fa_init = self._invoke_fastapi("GET", "/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence=0")
        self.assertEqual(fa_init["status"], 200)
        fa_data = fa_init["body"]["data"]
        self.assertEqual(fa_data["jobId"], "smart-write-events-job-001")
        self.assertFalse(fa_data["resetRequired"])
        self.assertFalse(fa_data["terminal"])
        self.assertIsNotNone(fa_data["previewSnapshot"])
        self.assertGreater(len(fa_data["events"]), 0)
        seq_fa = fa_data["latestSequence"]

        # Initial query (afterSequence=0) on Standalone
        sa_init = self._invoke_standalone("do_GET", "/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence=0")
        self.assertEqual(sa_init["status"], 200)
        sa_data = sa_init["body"]["data"]
        self.assertEqual(sa_data["jobId"], "smart-write-events-job-001")
        self.assertFalse(sa_data["resetRequired"])
        self.assertFalse(sa_data["terminal"])
        self.assertIsNotNone(sa_data["previewSnapshot"])
        self.assertEqual(sa_data["latestSequence"], seq_fa)

        # Timeout query with afterSequence=latestSequence on Standalone
        sa_timeout = self._invoke_standalone("do_GET", f"/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence={seq_fa}&waitMs=20")
        self.assertEqual(sa_timeout["status"], 200)
        self.assertEqual(sa_timeout["body"]["data"]["events"], [])
        self.assertEqual(sa_timeout["body"]["data"]["latestSequence"], seq_fa)

        # Timeout query on FastAPI
        fa_timeout = self._invoke_fastapi("GET", f"/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence={seq_fa}&waitMs=20")
        self.assertEqual(fa_timeout["status"], 200)
        self.assertEqual(fa_timeout["body"]["data"]["events"], [])
        self.assertEqual(fa_timeout["body"]["data"]["latestSequence"], seq_fa)

        # Release worker and verify terminal events on both
        self.worker.step_event.set()
        self.worker.release_event.set()
        self.coordinator.wait("smart-write-events-job-001")

        fa_term = self._invoke_fastapi("GET", f"/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence={seq_fa}&waitMs=50")
        self.assertEqual(fa_term["status"], 200)
        self.assertTrue(fa_term["body"]["data"]["terminal"])
        self.assertEqual(fa_term["body"]["data"]["status"], "completed")
        self.assertNotIn("result", fa_term["body"]["data"])

        sa_term = self._invoke_standalone("do_GET", f"/word/smart-write/jobs/smart-write-events-job-001/events?afterSequence={seq_fa}&waitMs=50")
        self.assertEqual(sa_term["status"], 200)
        self.assertTrue(sa_term["body"]["data"]["terminal"])
        self.assertEqual(sa_term["body"]["data"]["status"], "completed")
        self.assertNotIn("result", sa_term["body"]["data"])

    def test_smart_imitation_events_and_waitms_clamping(self):
        import app.api.word as word_api
        import standalone_adapter

        orig_im_fa = word_api.smart_imitation_jobs
        orig_im_sa = standalone_adapter.SMART_IMITATION_JOB_STORE
        try:
            word_api.smart_imitation_jobs = self.store
            standalone_adapter.SMART_IMITATION_JOB_STORE = self.store

            # Missing job 404
            fa_404 = self._invoke_fastapi("GET", "/word/smart-imitation/jobs/missing-im-id/events")
            self.assertEqual(fa_404["status"], 404)
            self.assertEqual(fa_404["body"]["taskType"], "word.smart_imitation")

            sa_404 = self._invoke_standalone("do_GET", "/word/smart-imitation/jobs/missing-im-id/events")
            self.assertEqual(sa_404["status"], 404)
            self.assertEqual(sa_404["body"]["taskType"], "word.smart_imitation")

            # waitMs clamping: 99999 waitMs does not fail
            fa_clamp = self._invoke_fastapi("GET", "/word/smart-imitation/jobs/missing-im-id/events?afterSequence=0&waitMs=99999")
            self.assertEqual(fa_clamp["status"], 404)
        finally:
            word_api.smart_imitation_jobs = orig_im_fa
            standalone_adapter.SMART_IMITATION_JOB_STORE = orig_im_sa

    def test_smart_imitation_events_long_polling_and_delete_cancellation_parity(self):
        import app.api.word as word_api
        import standalone_adapter
        from app.services.word.writing_jobs import SmartImitationJobStore

        class ImitationStreamingWorker:
            def __init__(self):
                self.started = threading.Event()
                self.cancelled = threading.Event()

            def snapshot_task_auth(self):
                return {
                    "accessMethod": "direct_model",
                    "providerBaseUrl": "http://127.0.0.1:19999",
                    "apiKey": "test-key",
                    "modelName": "test-model",
                    "streamingCapability": "validated",
                }

            def imitate(self, request, trace_id, progress_callback=None, **kwargs):
                progress_callback("streaming")
                if hasattr(progress_callback, "publish_text"):
                    progress_callback.publish_text("仿写增量内容。")
                    progress_callback.flush()
                self.started.set()
                for _ in range(50):
                    if hasattr(progress_callback, "cancel_requested") and progress_callback.cancel_requested():
                        self.cancelled.set()
                        from app.services.long_task_coordinator import LongTaskCancelled
                        raise LongTaskCancelled(partial_result={
                            "plainText": "仿写增量内容。",
                            "rewrittenText": "仿写增量内容。",
                            "partial": True,
                        })
                    time.sleep(0.02)
                return {"rewrittenText": "完整仿写", "plainText": "完整仿写"}

        coordinator = LongTaskCoordinator(max_running=2, max_queued=4)
        im_worker = ImitationStreamingWorker()
        im_store = SmartImitationJobStore(worker=im_worker, coordinator=coordinator)

        orig_im_fa = word_api.smart_imitation_jobs
        orig_im_sa = standalone_adapter.SMART_IMITATION_JOB_STORE
        try:
            word_api.smart_imitation_jobs = im_store
            standalone_adapter.SMART_IMITATION_JOB_STORE = im_store

            job_req = make_request_dict("imitation-events-job-001")
            req_obj = WordDocumentRequest(**job_req)
            with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
                im_store.start(req_obj, "trace-im-events-001")
            self.assertTrue(im_worker.started.wait(timeout=2))

            # Query events on FastAPI
            fa_events = self._invoke_fastapi("GET", "/word/smart-imitation/jobs/imitation-events-job-001/events?afterSequence=0")
            self.assertEqual(fa_events["status"], 200)
            self.assertEqual(fa_events["body"]["data"]["taskType"], "word.smart_imitation")
            self.assertEqual(fa_events["body"]["data"]["previewSnapshot"]["text"], "仿写增量内容。")

            # Query events on Standalone
            sa_events = self._invoke_standalone("do_GET", "/word/smart-imitation/jobs/imitation-events-job-001/events?afterSequence=0")
            self.assertEqual(sa_events["status"], 200)
            self.assertEqual(sa_events["body"]["data"]["taskType"], "word.smart_imitation")
            self.assertEqual(sa_events["body"]["data"]["previewSnapshot"]["text"], "仿写增量内容。")

            # Standalone and FastAPI event payloads match structure
            self.assertEqual(sa_events["body"]["data"]["latestSequence"], fa_events["body"]["data"]["latestSequence"])

            # Cancel via FastAPI DELETE
            fa_del = self._invoke_fastapi("DELETE", "/word/smart-imitation/jobs/imitation-events-job-001")
            self.assertEqual(fa_del["status"], 200)
            self.assertIn(fa_del["body"]["data"]["status"], {"running", "cancelled"})

            self.assertTrue(im_worker.cancelled.wait(timeout=2))
            final_job = coordinator.wait("imitation-events-job-001", task_type="word.smart_imitation")
            self.assertEqual(final_job["status"], "cancelled")

            # Test Standalone DELETE on a second running streaming job
            im_worker_2 = ImitationStreamingWorker()
            im_store_2 = SmartImitationJobStore(worker=im_worker_2, coordinator=coordinator)
            word_api.smart_imitation_jobs = im_store_2
            standalone_adapter.SMART_IMITATION_JOB_STORE = im_store_2

            job_req_2 = make_request_dict("imitation-events-job-002")
            req_obj_2 = WordDocumentRequest(**job_req_2)
            with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
                im_store_2.start(req_obj_2, "trace-im-events-002")
            self.assertTrue(im_worker_2.started.wait(timeout=2))

            sa_del = self._invoke_standalone("do_DELETE", "/word/smart-imitation/jobs/imitation-events-job-002")
            self.assertEqual(sa_del["status"], 200)
            self.assertIn(sa_del["body"]["data"]["status"], {"running", "cancelled"})
            self.assertEqual(
                sa_del["body"]["message"], sa_del["body"]["data"]["status"]
            )

            self.assertTrue(im_worker_2.cancelled.wait(timeout=2))
            final_job_2 = coordinator.wait("imitation-events-job-002", task_type="word.smart_imitation")
            self.assertEqual(final_job_2["status"], "cancelled")

            # Blocking job cancel returns 409 LONG_TASK_NOT_CANCELLABLE on both
            blocking_worker = BlockingWritingWorker()
            blocking_store = SmartImitationJobStore(worker=blocking_worker, coordinator=coordinator)
            word_api.smart_imitation_jobs = blocking_store
            standalone_adapter.SMART_IMITATION_JOB_STORE = blocking_store

            job_req_block = make_request_dict("imitation-block-job-003")
            req_obj_block = WordDocumentRequest(**job_req_block)
            blocking_store.start(req_obj_block, "trace-im-block-003")
            self.assertTrue(blocking_worker.started.wait(timeout=2))

            fa_block_del = self._invoke_fastapi("DELETE", "/word/smart-imitation/jobs/imitation-block-job-003")
            self.assertEqual(fa_block_del["status"], 409)
            self.assertEqual(fa_block_del["body"]["errors"][0]["code"], "LONG_TASK_NOT_CANCELLABLE")

            sa_block_del = self._invoke_standalone("do_DELETE", "/word/smart-imitation/jobs/imitation-block-job-003")
            self.assertEqual(sa_block_del["status"], 409)
            self.assertEqual(sa_block_del["body"]["errors"][0]["code"], "LONG_TASK_NOT_CANCELLABLE")

            blocking_worker.release_event.set()
            coordinator.wait("imitation-block-job-003", task_type="word.smart_imitation")
        finally:
            word_api.smart_imitation_jobs = orig_im_fa
            standalone_adapter.SMART_IMITATION_JOB_STORE = orig_im_sa


if __name__ == "__main__":
    unittest.main()
