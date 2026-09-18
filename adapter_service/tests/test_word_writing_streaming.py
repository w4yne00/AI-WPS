import json
import threading
import time
import unittest

from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator


class LongTaskTextPublishingTests(unittest.TestCase):
    def test_publish_text_continuous_sequence_and_preview_snapshot(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        step_event = threading.Event()
        finish_event = threading.Event()

        def stream_runner(_snapshot, control):
            control("streaming")
            control.publish_text("Hello ")
            control.publish_text("world!")
            control.flush()
            step_event.set()
            finish_event.wait(timeout=2)
            return {"result": "done"}

        coordinator.submit(
            job_id="stream-job-1",
            trace_id="trace-stream-1",
            task_type="word.smart_write",
            runner=stream_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        self.assertTrue(step_event.wait(timeout=2))

        # Query events from sequence 0
        events_resp = coordinator.wait_events("stream-job-1", task_type="word.smart_write", after_sequence=0)
        self.assertIsNotNone(events_resp)
        self.assertFalse(events_resp["resetRequired"])
        events = events_resp["events"]
        delta_events = [e for e in events if e.get("type") == "delta"]
        self.assertGreaterEqual(len(delta_events), 1)

        # Sequences must be strictly monotonic
        sequences = [e["sequence"] for e in events]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))

        # Combined delta text must equal "Hello world!"
        combined_deltas = "".join(e["delta"] for e in delta_events)
        self.assertEqual(combined_deltas, "Hello world!")

        # Preview snapshot text must equal "Hello world!"
        snapshot = events_resp["previewSnapshot"]
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["text"], "Hello world!")

        finish_event.set()
        final_job = coordinator.wait("stream-job-1", task_type="word.smart_write")
        self.assertEqual(final_job["status"], "completed")

    def test_publish_text_batches_under_50ms_and_flushes_on_complete(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def rapid_runner(_snapshot, control):
            control("streaming")
            # Rapid calls within < 10ms
            for i in range(10):
                control.publish_text(f"chunk{i} ")
            # Don't call flush() manually; runner completion must auto-flush
            return {"result": "done"}

        coordinator.submit(
            job_id="rapid-job-1",
            trace_id="trace-rapid-1",
            task_type="word.smart_write",
            runner=rapid_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        final_job = coordinator.wait("rapid-job-1", task_type="word.smart_write")
        self.assertEqual(final_job["status"], "completed")

        events_resp = coordinator.wait_events("rapid-job-1", task_type="word.smart_write", after_sequence=0)
        delta_events = [e for e in events_resp["events"] if e.get("type") == "delta"]

        # Because of 50ms batching, 10 rapid small calls should coalesce into very few events (< 5)
        self.assertLess(len(delta_events), 10)
        combined_deltas = "".join(e["delta"] for e in delta_events)
        expected = "".join(f"chunk{i} " for i in range(10))
        self.assertEqual(combined_deltas, expected)

    def test_publish_text_flushes_at_4kib(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def large_batch_runner(_snapshot, control):
            control("streaming")
            # Send two 3 KiB chunks in same millisecond
            part1 = "a" * 3072
            part2 = "b" * 3072
            control.publish_text(part1)  # 3 KiB (buffered)
            control.publish_text(part2)  # Total 6 KiB (should trigger flush of >= 4 KiB)
            return {"result": "done"}

        coordinator.submit(
            job_id="size-job-1",
            trace_id="trace-size-1",
            task_type="word.smart_write",
            runner=large_batch_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        coordinator.wait("size-job-1", task_type="word.smart_write")
        events_resp = coordinator.wait_events("size-job-1", task_type="word.smart_write", after_sequence=0)
        delta_events = [e for e in events_resp["events"] if e.get("type") == "delta"]
        # Must have flushed in parts because 3072 + 3072 exceeded 4096 bytes
        self.assertGreaterEqual(len(delta_events), 2)
        total_len = sum(len(e["delta"]) for e in delta_events)
        self.assertEqual(total_len, 6144)

    def test_publish_text_enforces_512kib_preview_limit(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def overflow_runner(_snapshot, control):
            control("streaming")
            # Publish 600 KiB
            chunk = "x" * 64 * 1024  # 64 KiB
            for _ in range(10):
                control.publish_text(chunk)
                control.flush()
            return {"result": "done"}

        coordinator.submit(
            job_id="limit-job-1",
            trace_id="trace-limit-1",
            task_type="word.smart_write",
            runner=overflow_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        final_job = coordinator.wait("limit-job-1", task_type="word.smart_write")
        self.assertEqual(final_job["status"], "completed")

        events_resp = coordinator.wait_events("limit-job-1", task_type="word.smart_write", after_sequence=0)
        snapshot = events_resp["previewSnapshot"]
        # Preview text length must be capped at 512 KiB (524288 bytes)
        self.assertLessEqual(len(snapshot["text"].encode("utf-8")), 512 * 1024)

    def test_wait_events_condition_wakes_up_on_publish_text(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        start_gate = threading.Event()
        finish_gate = threading.Event()

        def stream_runner(_snapshot, control):
            control("streaming")
            start_gate.wait(timeout=2)
            control.publish_text("Instant wake up!")
            control.flush()
            finish_gate.wait(timeout=2)
            return {"done": True}

        coordinator.submit(
            job_id="wake-stream-1",
            trace_id="trace-wake-1",
            task_type="word.smart_write",
            runner=stream_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        initial = coordinator.wait_events("wake-stream-1", after_sequence=0)
        initial_seq = initial["latestSequence"]

        result_box = []

        def wait_worker():
            resp = coordinator.wait_events("wake-stream-1", after_sequence=initial_seq, wait_ms=5000)
            result_box.append(resp)

        thread = threading.Thread(target=wait_worker)
        thread.start()

        time.sleep(0.05)
        # Trigger publish_text
        start_gate.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), "wait_events did not wake up promptly on text delta")
        self.assertEqual(len(result_box), 1)
        resp = result_box[0]
        self.assertGreater(resp["latestSequence"], initial_seq)
        delta_events = [e for e in resp["events"] if e.get("type") == "delta"]
        self.assertTrue(any("Instant wake up!" in e.get("delta", "") for e in delta_events))

        finish_gate.set()
        coordinator.wait("wake-stream-1")


class ProviderClientDirectStreamingIntegrationTests(unittest.TestCase):
    def test_post_direct_task_uses_streaming_when_feature_enabled_and_validated(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
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

        published = []
        phase_transitions = []

        class MockControl:
            def __call__(self, phase):
                phase_transitions.append(phase)

            def publish_text(self, text):
                published.append(text)

            def record_metric(self, name, val):
                pass

            def record_provider_attempt(self, attempt_metrics):
                pass

            def cancel_requested(self):
                return False

        control = MockControl()
        sse_payload = (
            b'data: {"choices":[{"delta":{"content":"\xe6\xb5\x81\xe5\xbc\x8f\xe6\x94\xb9\xe5\x86\x99\xe7\xbb\x93\xe6\x9e\x9c"}}]}\n\n'
            b'data: [DONE]\n\n'
        )

        sent_requests = []

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([sse_payload])

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            res = client._post_direct_task(
                task_type="word.smart_write",
                trace_id="trace-stream-direct-1",
                query="改写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                progress_callback=control,
            )

        self.assertEqual(len(sent_requests), 1)
        req = sent_requests[0]
        # Must request text/event-stream
        self.assertEqual(req.headers.get("Accept"), "text/event-stream")
        import json
        body = json.loads(req.data.decode("utf-8"))
        self.assertTrue(body.get("stream"))

        # Must have published deltas and transitioned phases
        self.assertIn("流式改写结果", "".join(published))
        self.assertIn("streaming", phase_transitions)

    def test_post_direct_task_falls_back_to_blocking_when_streaming_unsupported(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
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

        sent_requests = []
        call_count = 0

        blocking_response_json = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "阻塞回退结果"}, "finish_reason": "stop"}]
        }).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            sent_requests.append(req)
            call_count += 1
            if call_count == 1:
                # First call (streaming) fails with 415 Unsupported Media Type
                raise HTTPError(req.full_url, 415, "Unsupported Media Type", {}, None)
            return FakeHTTPResponse([blocking_response_json], headers={"Content-Type": "application/json"})

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            res = client._post_direct_task(
                task_type="word.smart_write",
                trace_id="trace-stream-fallback-1",
                query="改写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
            )

        self.assertEqual(len(sent_requests), 2)
        # First request was streaming
        req1_body = json.loads(sent_requests[0].data.decode("utf-8"))
        self.assertTrue(req1_body.get("stream"))
        # Second request was blocking fallback
        req2_body = json.loads(sent_requests[1].data.decode("utf-8"))
        self.assertFalse(req2_body.get("stream"))

    def test_post_direct_task_uses_blocking_when_feature_flag_disabled(self):
        from unittest.mock import patch
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

        sent_requests = []
        blocking_response_json = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "阻塞结果"}, "finish_reason": "stop"}]
        }).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([blocking_response_json], headers={"Content-Type": "application/json"})

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "0"}), patch("urllib.request.urlopen", fake_urlopen):
            res = client._post_direct_task(
                task_type="word.smart_write",
                trace_id="trace-blocking-1",
                query="改写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
            )

        self.assertEqual(len(sent_requests), 1)
        req_body = json.loads(sent_requests[0].data.decode("utf-8"))
        self.assertFalse(req_body.get("stream"))

    def test_post_direct_task_does_not_fallback_after_visible_delta_emitted(self):
        from unittest.mock import patch
        from app.core.errors import ProviderMidStreamDisconnectError
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

        published = []

        class MockControl:
            def __call__(self, phase):
                pass
            def publish_text(self, text):
                published.append(text)
            def record_metric(self, name, val):
                pass
            def record_provider_attempt(self, attempt_metrics):
                pass
            def cancel_requested(self):
                return False

        control = MockControl()
        # Stream emits one delta and then truncates without [DONE]
        sse_payload = (
            'data: {"choices":[{"delta":{"content":"部分文本"}}]}\n\n'
        ).encode("utf-8")

        sent_requests = []

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([sse_payload])

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ProviderMidStreamDisconnectError):
                client._post_direct_task(
                    task_type="word.smart_write",
                    trace_id="trace-stream-abort-1",
                    query="改写以下内容",
                    resolved_task_auth=task_auth,
                    timeout=30,
                    progress_callback=control,
                )

        # Must NOT have made a second fallback request because visible delta was already emitted
        self.assertEqual(len(sent_requests), 1)
        self.assertIn("部分文本", "".join(published))


if __name__ == "__main__":
    unittest.main()

