import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryStore
from app.services.word.writing_jobs import SmartImitationJobStore, SmartWriteJobStore


def make_request(
    client_job_id,
    document_session_id="",
    document_display_name="",
    host="wps",
):
    payload = {
        "documentId": "writing-test.docx",
        "scene": "word",
        "selectionMode": "selection",
        "clientJobId": client_job_id,
        "documentSessionId": document_session_id,
        "documentDisplayName": document_display_name,
        "host": host,
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
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.history_store = TaskHistoryStore(Path(self.tmp_dir.name) / "history")
        self.history_patch = patch(
            "app.services.word.writing_jobs.get_task_history_store",
            return_value=self.history_store,
        )
        self.history_patch.start()

    def tearDown(self):
        self.history_patch.stop()
        self.tmp_dir.cleanup()

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

    def test_model_response_size_limit_remains_public_failure_code(self):
        class SizeLimitWorker:
            def snapshot_task_auth(self):
                return {"configurationId": "size-limit-config"}

            def smart_write(self, _request, **_kwargs):
                raise AdapterError(
                    "MODEL_RESPONSE_SIZE_LIMIT",
                    "模型流式响应超过 5 MiB 上限。",
                    status_code=502,
                )

        store = SmartWriteJobStore(
            worker=SizeLimitWorker(),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )
        store.start(make_request("client-size-limit-error"), "trace-size-limit-error")

        terminal = None
        for _ in range(100):
            terminal = store.get("client-size-limit-error")
            if terminal and terminal["status"] == "failed":
                break
            time.sleep(0.01)

        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["error"]["code"], "MODEL_RESPONSE_SIZE_LIMIT")
        self.assertEqual(
            terminal["error"]["message"], "模型流式响应超过 5 MiB 上限。"
        )

    def test_job_store_rejects_concurrent_submission_in_same_document_session(self):
        worker = BlockingWritingWorker()
        coordinator = LongTaskCoordinator(max_running=2, max_queued=4)
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)

        req1 = make_request("client-smart-write-sess-1", document_session_id="doc-session-test")
        req2 = make_request("client-smart-write-sess-2", document_session_id="doc-session-test")
        req_diff = make_request("client-smart-write-sess-diff", document_session_id="doc-session-other")

        started1 = store.start(req1, "trace-sess-1")
        self.assertEqual(started1["jobId"], "client-smart-write-sess-1")
        self.assertTrue(worker.started.wait(timeout=1))

        # Concurrent submission under the same document session must be rejected with 409
        with self.assertRaises(AdapterError) as err:
            store.start(req2, "trace-sess-2")
        self.assertEqual(err.exception.code, "WORD_WRITING_DOCUMENT_TASK_BUSY")
        self.assertEqual(err.exception.status_code, 409)

        # Different document session is accepted
        started_diff = store.start(req_diff, "trace-sess-diff")
        self.assertEqual(started_diff["jobId"], "client-smart-write-sess-diff")

        worker.release.set()
        self.wait_completed(store, started1["jobId"])
        self.wait_completed(store, started_diff["jobId"])

    def test_job_store_records_sanitized_history_and_handles_oversize_notice(self):
        class CustomWritingWorker:
            def __init__(self, oversize=False):
                self.oversize = oversize

            def snapshot_task_auth(self):
                return {"serviceName": "测试编写服务", "modelName": "write-v1"}

            def smart_write(self, req, **kwargs):
                if self.oversize:
                    return {
                        "originalText": "绝密原选区内容",
                        "rewrittenText": "X" * (6 * 1024 * 1024),
                        "rewriteMode": "rewrite",
                        "diffHints": [],
                        "prompt": "secret prompt",
                    }
                return {
                    "originalText": "绝密原选区内容",
                    "rewrittenText": "公开改写成果文本",
                    "rewriteMode": "rewrite",
                    "diffHints": ["Text content changed"],
                    "prompt": "secret prompt",
                }

            def imitate(self, req, **kwargs):
                return self.smart_write(req, **kwargs)

        # 1. Normal run: originalText and prompt stripped
        store = SmartWriteJobStore(worker=CustomWritingWorker(oversize=False))
        req = make_request(
            "client-write-hist-normal",
            document_session_id="doc-session-hist",
            document_display_name="方案汇报.docx",
        )
        store.start(req, "trace-hist-normal")

        res = None
        for _ in range(50):
            res = store.get("client-write-hist-normal")
            if res and res.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "completed")

        histories = self.history_store.list_history("word.smart_write")
        self.assertEqual(len(histories), 1)
        entry = histories[0]
        self.assertEqual(entry["documentDisplayName"], "方案汇报.docx")
        self.assertEqual(entry["serviceName"], "测试编写服务")
        self.assertEqual(entry["modelName"], "write-v1")
        # Privacy verification: originalText and prompt MUST NOT be saved
        self.assertNotIn("originalText", entry["result"])
        self.assertNotIn("prompt", entry["result"])
        self.assertEqual(entry["result"]["rewrittenText"], "公开改写成果文本")
        self.assertEqual(entry["result"]["plainText"], "公开改写成果文本")

        # 2. Oversized run: notice set, not written to history
        store_over = SmartWriteJobStore(worker=CustomWritingWorker(oversize=True))
        req_over = make_request(
            "client-write-hist-over",
            document_session_id="doc-session-over",
            document_display_name="超大文档.docx",
        )
        store_over.start(req_over, "trace-hist-over")

        res_over = None
        for _ in range(50):
            res_over = store_over.get("client-write-hist-over")
            if res_over and res_over.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertIsNotNone(res_over)
        self.assertEqual(res_over["status"], "completed")
        self.assertIn("未写入历史记录", res_over["result"].get("historyNotice", ""))

        # Still only 1 entry in history
        histories_after = self.history_store.list_history("word.smart_write")
        self.assertEqual(len(histories_after), 1)

    def test_smart_write_streaming_with_validated_capability_publishes_deltas(self):
        from app.services.word.rewriter import WordRewriter
        from app.services.provider_client import ProviderClient

        captured_requests = []

        class FakeStreamingProviderClient:
            def resolve_task_auth(self, task_type):
                return {
                    "accessMethod": "direct_model",
                    "providerBaseUrl": "http://127.0.0.1:19999",
                    "apiKey": "test-key",
                    "modelName": "test-model",
                    "streamingCapability": "validated",
                }

            def smart_write(self, text, action, trace_id, progress_callback=None, task_auth=None, **kwargs):
                if progress_callback and hasattr(progress_callback, "publish_text"):
                    progress_callback("streaming")
                    progress_callback.publish_text("流式增量第一段 ")
                    progress_callback.publish_text("流式增量第二段。")
                    progress_callback.flush()
                return {
                    "rewrittenText": "流式增量第一段 流式增量第二段。",
                    "provider": "direct_model",
                    "prompt": "prompt",
                }

        worker = WordRewriter(provider_client=FakeStreamingProviderClient())
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)

        req = make_request(
            "client-write-stream-1",
            document_session_id="doc-stream-1",
            document_display_name="流式测试.docx",
        )

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            store.start(req, "trace-stream-1")
            res = self.wait_completed(store, "client-write-stream-1")

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["result"]["rewrittenText"], "流式增量第一段 流式增量第二段。")

        # Verify coordinator events contain delta events
        events_resp = store.wait_events("client-write-stream-1", after_sequence=0)
        deltas = [e for e in events_resp["events"] if e.get("type") == "delta"]
        self.assertGreaterEqual(len(deltas), 1)
        combined = "".join(d["delta"] for d in deltas)
        self.assertEqual(combined, "流式增量第一段 流式增量第二段。")


    def test_smart_write_streaming_end_to_end_with_real_provider_client(self):
        from unittest.mock import patch
        from app.services.word.rewriter import WordRewriter
        from app.services.provider_client import ProviderClient
        from tests.test_direct_text_stream import FakeHTTPResponse

        client = ProviderClient()
        task_auth = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-test12345",
            "modelName": "gpt-4o",
            "streamingCapability": "validated",
            "contextWindowTokens": 100000,
            "maxOutputTokens": 4096,
        }

        sse_payload = (
            'data: {"choices":[{"delta":{"content":"全链路流式正文"}}]}\n\n'
            'data: [DONE]\n\n'
        ).encode("utf-8")

        sent_requests = []

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([sse_payload])

        worker = WordRewriter(provider_client=client)
        # Mock snapshot_task_auth to return validated direct_model auth
        worker.snapshot_task_auth = lambda: task_auth

        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = SmartWriteJobStore(worker=worker, coordinator=coordinator)

        req = make_request(
            "client-write-e2e-1",
            document_session_id="doc-e2e-1",
            document_display_name="全链路.docx",
        )

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            store.start(req, "trace-e2e-1")
            res = self.wait_completed(store, "client-write-e2e-1")

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["result"]["rewrittenText"], "全链路流式正文")

        events_resp = store.wait_events("client-write-e2e-1", after_sequence=0)
        deltas = [e for e in events_resp["events"] if e.get("type") == "delta"]
        self.assertGreaterEqual(len(deltas), 1)
        self.assertEqual("".join(d["delta"] for d in deltas), "全链路流式正文")
        self.assertEqual(events_resp["previewSnapshot"]["text"], "全链路流式正文")

    def test_streaming_job_allows_running_cancel_while_blocking_does_not(self):
        blocking_worker = BlockingWritingWorker()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        blocking_store = SmartWriteJobStore(worker=blocking_worker, coordinator=coordinator)

        req_blocking = make_request("client-block-cancel-1")
        blocking_store.start(req_blocking, "trace-block-1")
        self.assertTrue(blocking_worker.started.wait(timeout=2))

        # While running, blocking job should reject cancellation with LONG_TASK_NOT_CANCELLABLE
        with self.assertRaises(AdapterError) as ctx:
            blocking_store.cancel("client-block-cancel-1")
        self.assertEqual(ctx.exception.code, "LONG_TASK_NOT_CANCELLABLE")
        self.assertEqual(ctx.exception.status_code, 409)
        blocking_worker.release.set()
        self.wait_completed(blocking_store, "client-block-cancel-1")

        # Now test streaming job with validated streaming capability
        class StreamingWorker:
            def __init__(self):
                self.started = threading.Event()
                self.cancelled_observed = threading.Event()
                self.release = threading.Event()

            def snapshot_task_auth(self):
                return {
                    "accessMethod": "direct_model",
                    "providerBaseUrl": "http://127.0.0.1:19999",
                    "apiKey": "test-key",
                    "modelName": "test-model",
                    "streamingCapability": "validated",
                }

            def smart_write(self, request, trace_id, progress_callback=None, **kwargs):
                progress_callback("streaming")
                if hasattr(progress_callback, "publish_text"):
                    progress_callback.publish_text("流式首段文本。")
                    progress_callback.flush()
                self.started.set()
                # Wait until cancel requested or release
                for _ in range(50):
                    if hasattr(progress_callback, "cancel_requested") and progress_callback.cancel_requested():
                        self.cancelled_observed.set()
                        from app.services.long_task_coordinator import LongTaskCancelled
                        raise LongTaskCancelled(partial_result={
                            "plainText": "流式首段文本。",
                            "rewrittenText": "流式首段文本。",
                            "partial": True,
                            "stopReason": "cancelled",
                        })
                    time.sleep(0.02)
                return {"rewrittenText": "最终文本", "plainText": "最终文本"}

        streaming_worker = StreamingWorker()
        streaming_store = SmartWriteJobStore(worker=streaming_worker, coordinator=coordinator)
        req_streaming = make_request("client-stream-cancel-1")

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}):
            streaming_store.start(req_streaming, "trace-stream-cancel-1")
            self.assertTrue(streaming_worker.started.wait(timeout=2))

            # Calling cancel while running MUST be accepted for streaming job
            cancel_resp = streaming_store.cancel("client-stream-cancel-1")
            self.assertEqual(cancel_resp["status"], "running")
            self.assertEqual(cancel_resp["phase"], "stopping")

            self.assertTrue(streaming_worker.cancelled_observed.wait(timeout=2))

            # Wait for job to settle into terminal state
            terminal_job = None
            for _ in range(50):
                terminal_job = streaming_store.get("client-stream-cancel-1")
                if terminal_job and terminal_job["status"] == "cancelled":
                    break
                time.sleep(0.02)

            self.assertIsNotNone(terminal_job)
            self.assertEqual(terminal_job["status"], "cancelled")
            self.assertIsNotNone(terminal_job.get("result"))
            self.assertTrue(terminal_job["result"].get("partial"))
            self.assertEqual(terminal_job["result"].get("plainText"), "流式首段文本。")

            # Check history: cancelled jobs MUST NOT be written to task history
            history_entries = self.history_store.list_history("word.smart_write")
            self.assertEqual(len(history_entries), 1)  # only the blocking completed one
            self.assertEqual(history_entries[0]["jobId"], "client-block-cancel-1")


if __name__ == "__main__":
    unittest.main()
