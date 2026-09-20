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

    def test_publish_text_flushes_after_50ms_without_another_delta(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        buffered_event = threading.Event()
        finish_event = threading.Event()

        def paused_runner(_snapshot, control):
            control("streaming")
            control.publish_text("first visible text")
            buffered_event.set()
            finish_event.wait(timeout=2)
            return {"result": "done"}

        coordinator.submit(
            job_id="paused-stream-1",
            trace_id="trace-paused-stream-1",
            task_type="word.smart_write",
            runner=paused_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )

        self.assertTrue(buffered_event.wait(timeout=1))
        time.sleep(0.12)
        events_resp = coordinator.wait_events(
            "paused-stream-1",
            task_type="word.smart_write",
            after_sequence=0,
        )
        self.assertEqual(
            events_resp["previewSnapshot"]["text"],
            "first visible text",
        )

        finish_event.set()
        coordinator.wait("paused-stream-1", task_type="word.smart_write")

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
        self.assertTrue(snapshot["previewTruncated"])
        self.assertTrue(events_resp["previewTruncated"])

        follow_up = coordinator.wait_events(
            "limit-job-1",
            task_type="word.smart_write",
            after_sequence=events_resp["latestSequence"],
        )
        self.assertIsNone(follow_up["previewSnapshot"])
        self.assertTrue(follow_up["previewTruncated"])

    def test_delta_event_response_does_not_repeat_accumulated_preview(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def stream_runner(_snapshot, control):
            control("streaming")
            for _ in range(32):
                control.publish_text("x" * 4096)
            return {"result": "done"}

        coordinator.submit(
            job_id="bounded-events-1",
            trace_id="trace-bounded-events-1",
            task_type="word.smart_write",
            runner=stream_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )
        coordinator.wait("bounded-events-1", task_type="word.smart_write")

        events_resp = coordinator.wait_events(
            "bounded-events-1",
            task_type="word.smart_write",
            after_sequence=0,
        )
        serialized_events = json.dumps(events_resp["events"]).encode("utf-8")
        self.assertLess(len(serialized_events), 160 * 1024)

    def test_preview_limit_does_not_emit_empty_utf8_delta_events(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)

        def boundary_runner(_snapshot, control):
            control("streaming")
            control.publish_text("x" * ((512 * 1024) - 2))
            control.flush()
            control.publish_text("你")
            control.flush()
            control.publish_text("好")
            control.flush()
            return {"result": "done"}

        coordinator.submit(
            job_id="utf8-limit-1",
            trace_id="trace-utf8-limit-1",
            task_type="word.smart_write",
            runner=boundary_runner,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
        )
        coordinator.wait("utf8-limit-1", task_type="word.smart_write")

        events_resp = coordinator.wait_events(
            "utf8-limit-1",
            task_type="word.smart_write",
            after_sequence=0,
        )
        delta_events = [
            event for event in events_resp["events"] if event.get("type") == "delta"
        ]
        self.assertTrue(delta_events)
        self.assertTrue(all(event.get("delta") for event in delta_events))

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
    def test_running_cancel_interrupts_silent_upstream_read(self):
        from unittest.mock import patch
        from app.services.provider_client import ProviderClient

        client = ProviderClient()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        read_started = threading.Event()
        read_released = threading.Event()

        class SilentSseResponse:
            status = 200
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self.closed = False

            def read1(self, _amount):
                read_started.set()
                read_released.wait(timeout=1.0)
                return b""

            def close(self):
                self.closed = True
                read_released.set()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                self.close()

        response = SilentSseResponse()
        task_auth = {
            "providerBaseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-test12345",
            "modelName": "gpt-4o",
            "streamingCapability": "validated",
            "contextWindowTokens": 100000,
            "maxOutputTokens": 4096,
        }

        def runner(_snapshot, control):
            return client._post_direct_task(
                task_type="word.smart_write",
                trace_id="trace-silent-cancel",
                query="改写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                prompt_asset={
                    "content": "system prompt",
                    "version": "test-v1",
                    "hashPrefix": "testhash",
                },
                progress_callback=control,
            )

        with patch.dict(
            "os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}
        ), patch("urllib.request.urlopen", return_value=response):
            coordinator.submit(
                job_id="silent-cancel-job",
                trace_id="trace-silent-cancel",
                task_type="word.smart_write",
                runner=runner,
                snapshot={},
                failure_code="WRITING_JOB_FAILED",
                failure_message="智能编写失败。",
                allow_running_cancel=True,
            )
            self.assertTrue(read_started.wait(timeout=1))
            cancel_started = time.monotonic()
            coordinator.request_cancel(
                "silent-cancel-job", task_type="word.smart_write"
            )
            terminal = coordinator.wait(
                "silent-cancel-job", task_type="word.smart_write"
            )

        self.assertEqual(terminal["status"], "cancelled")
        self.assertLess(time.monotonic() - cancel_started, 0.5)
        self.assertTrue(response.closed)

    def test_post_direct_task_uses_frozen_streaming_protocol_when_validated(self):
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
            "streamingCapability": {
                "status": "validated",
                "serviceId": "direct_svc_test",
                "serviceRevision": 1,
                "serviceBaseUrl": "https://api.openai.com/v1",
                "apiKeyFingerprint": "sha256:test",
                "modelName": "gpt-4o",
                "testedAt": "2026-09-20T00:00:00Z",
            },
            "directStreamingEnabled": True,
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

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "0"}), patch("urllib.request.urlopen", fake_urlopen):
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

        class MockControl:
            def __init__(self):
                self.running_cancel_disabled = False

            def __call__(self, _phase):
                pass

            def record_provider_attempt(self, _metrics):
                pass

            def disable_running_cancel(self):
                self.running_cancel_disabled = True

        control = MockControl()

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
                progress_callback=control,
            )

        self.assertEqual(len(sent_requests), 2)
        # First request was streaming
        req1_body = json.loads(sent_requests[0].data.decode("utf-8"))
        self.assertTrue(req1_body.get("stream"))
        # Second request was blocking fallback
        req2_body = json.loads(sent_requests[1].data.decode("utf-8"))
        self.assertFalse(req2_body.get("stream"))
        self.assertTrue(control.running_cancel_disabled)

    def test_post_direct_task_falls_back_when_stream_response_is_not_sse(self):
        from unittest.mock import patch
        from app.services.provider_client import (
            ProviderClient,
            get_last_provider_debug,
            reset_provider_debug,
        )
        from tests.test_direct_text_stream import FakeHTTPResponse

        client = ProviderClient()
        reset_provider_debug()
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
        first_response = None
        provider_attempts = []
        blocking_response_json = json.dumps({
            "choices": [{
                "message": {"role": "assistant", "content": "阻塞回退结果"},
                "finish_reason": "stop",
            }]
        }).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            nonlocal first_response
            sent_requests.append(req)
            if first_response is not None:
                self.assertTrue(first_response.closed)
            response = FakeHTTPResponse(
                [blocking_response_json],
                headers={"Content-Type": "application/json"},
            )
            if first_response is None:
                first_response = response
            return response

        class MockControl:
            def __init__(self):
                self.running_cancel_disabled = False

            def __call__(self, phase):
                pass

            def publish_text(self, text):
                pass

            def record_metric(self, name, value):
                pass

            def record_provider_attempt(self, metrics):
                provider_attempts.append(metrics)

            def cancel_requested(self):
                return False

            def disable_running_cancel(self):
                self.running_cancel_disabled = True

        control = MockControl()

        with patch.dict(
            "os.environ",
            {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"},
        ), patch("urllib.request.urlopen", fake_urlopen):
            result = client._post_direct_task(
                task_type="word.smart_write",
                trace_id="trace-stream-fallback-content-type",
                query="改写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                progress_callback=control,
            )

        self.assertEqual(result["answer"], "阻塞回退结果")
        self.assertEqual(len(sent_requests), 2)
        self.assertEqual(len(provider_attempts), 2)
        debug = get_last_provider_debug("trace-stream-fallback-content-type")
        self.assertEqual(debug["performance"]["providerAttempts"], 2)
        self.assertTrue(json.loads(sent_requests[0].data.decode("utf-8"))["stream"])
        self.assertFalse(json.loads(sent_requests[1].data.decode("utf-8"))["stream"])
        self.assertTrue(control.running_cancel_disabled)

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

    def test_cancel_and_completion_race_first_committed_wins(self):
        coordinator = LongTaskCoordinator(max_running=2, max_queued=2)
        step_event = threading.Event()
        finish_event = threading.Event()

        # Job A: Cancelled before completion
        def runner_a(_snapshot, control):
            control("streaming")
            control.publish_text("部分文本A")
            control.flush()
            step_event.set()
            for _ in range(50):
                if control.cancel_requested():
                    from app.services.long_task_coordinator import LongTaskCancelled
                    raise LongTaskCancelled()
                time.sleep(0.01)
            return {"result": "A done"}

        coordinator.submit(
            job_id="race-job-a",
            trace_id="trace-race-a",
            task_type="word.smart_write",
            runner=runner_a,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
            allow_running_cancel=True,
        )

        self.assertTrue(step_event.wait(timeout=2))
        cancel_res = coordinator.request_cancel("race-job-a", task_type="word.smart_write")
        self.assertEqual(cancel_res["status"], "running")
        self.assertEqual(cancel_res["phase"], "stopping")

        final_a = coordinator.wait("race-job-a", task_type="word.smart_write")
        self.assertEqual(final_a["status"], "cancelled")
        self.assertIsNotNone(final_a["result"])
        self.assertEqual(final_a["result"]["plainText"], "部分文本A")
        self.assertTrue(final_a["result"]["partial"])

        # Job B: Completion committed before cancel requested
        def runner_b(_snapshot, control):
            control("streaming")
            control.publish_text("完整文本B")
            control.flush()
            return {"rewrittenText": "完整文本B", "plainText": "完整文本B"}

        coordinator.submit(
            job_id="race-job-b",
            trace_id="trace-race-b",
            task_type="word.smart_write",
            runner=runner_b,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
            allow_running_cancel=True,
        )

        final_b = coordinator.wait("race-job-b", task_type="word.smart_write")
        self.assertEqual(final_b["status"], "completed")

        # Now late cancel arrives after job has completed
        late_cancel = coordinator.request_cancel("race-job-b", task_type="word.smart_write")
        self.assertEqual(late_cancel["status"], "completed")
        self.assertEqual(late_cancel["result"]["plainText"], "完整文本B")

    def test_cancellation_delta_stop_p95_under_500ms_and_slot_release_under_2s(self):
        # 20 samples to calculate p95
        delta_stop_latencies = []
        slot_release_latencies = []

        for i in range(20):
            coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
            started_event = threading.Event()
            last_delta_mono = [0.0]

            def streaming_runner(_snapshot, control):
                control("streaming")
                started_event.set()
                while not control.cancel_requested():
                    control.publish_text(f"iter-{i}-chunk ")
                    control.flush()
                    last_delta_mono[0] = time.monotonic()
                    time.sleep(0.01)
                from app.services.long_task_coordinator import LongTaskCancelled
                raise LongTaskCancelled(partial_result={"plainText": "partial", "partial": True})

            job_id = f"perf-cancel-job-{i}"
            coordinator.submit(
                job_id=job_id,
                trace_id=f"trace-perf-{i}",
                task_type="word.smart_write",
                runner=streaming_runner,
                snapshot={},
                failure_code="FAILED",
                failure_message="failed",
                allow_running_cancel=True,
            )

            self.assertTrue(started_event.wait(timeout=2))
            time.sleep(0.02)  # allow at least one delta to be emitted

            t_cancel_called = time.monotonic()
            coordinator.request_cancel(job_id, task_type="word.smart_write")

            # Wait for job to reach terminal cancelled
            terminal_job = coordinator.wait(job_id, task_type="word.smart_write")
            t_slot_released = time.monotonic()

            self.assertEqual(terminal_job["status"], "cancelled")

            # The time deltas stopped is bounded by last_delta_mono or immediately
            t_last_delta = max(last_delta_mono[0], t_cancel_called)
            delta_stop_latencies.append(t_last_delta - t_cancel_called)
            slot_release_latencies.append(t_slot_released - t_cancel_called)

        # Sort to find p95 (19th element of 20 samples)
        delta_stop_latencies.sort()
        slot_release_latencies.sort()
        p95_delta_stop = delta_stop_latencies[int(0.95 * len(delta_stop_latencies))]
        max_slot_release = max(slot_release_latencies)

        # Verify acceptance criteria: p95 <= 500ms (0.5s), slot release <= 2s
        self.assertLessEqual(p95_delta_stop, 0.5)
        self.assertLessEqual(max_slot_release, 2.0)


class SmartImitationStreamingTests(unittest.TestCase):
    def test_post_direct_task_uses_streaming_for_smart_imitation(self):
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
            b'data: {"choices":[{"delta":{"content":"\xe4\xbb\xbf\xe5\x86\x99\xe6\xb5\x81\xe5\xbc\x8f\xe7\xbb\x93\xe6\x9e\x9c"}}]}\n\n'
            b'data: [DONE]\n\n'
        )

        sent_requests = []

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([sse_payload])

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            res = client._post_direct_task(
                task_type="word.smart_imitation",
                trace_id="trace-stream-imitation-1",
                query="仿写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                progress_callback=control,
            )

        self.assertEqual(len(sent_requests), 1)
        req_body = json.loads(sent_requests[0].data.decode("utf-8"))
        self.assertTrue(req_body.get("stream"))
        self.assertEqual("".join(published), "仿写流式结果")
        self.assertIn("仿写流式结果", res["answer"])
        self.assertIn("streaming", phase_transitions)

    def test_smart_imitation_running_cancel_interrupts_silent_upstream_read(self):
        from unittest.mock import patch
        from app.services.provider_client import ProviderClient

        client = ProviderClient()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        read_started = threading.Event()
        read_released = threading.Event()

        class SilentSseResponse:
            status = 200
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self.closed = False

            def read1(self, _amount):
                read_started.set()
                read_released.wait(timeout=1.0)
                return b""

            def close(self):
                self.closed = True
                read_released.set()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                self.close()

        response = SilentSseResponse()
        task_auth = {
            "providerBaseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-test12345",
            "modelName": "gpt-4o",
            "streamingCapability": "validated",
            "contextWindowTokens": 100000,
            "maxOutputTokens": 4096,
        }

        def runner(_snapshot, control):
            return client._post_direct_task(
                task_type="word.smart_imitation",
                trace_id="trace-silent-cancel-imitation",
                query="仿写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                prompt_asset={
                    "content": "system prompt",
                    "version": "test-v1",
                    "hashPrefix": "testhash",
                },
                progress_callback=control,
            )

        with patch.dict(
            "os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}
        ), patch("urllib.request.urlopen", return_value=response):
            coordinator.submit(
                job_id="silent-cancel-imitation-job",
                trace_id="trace-silent-cancel-imitation",
                task_type="word.smart_imitation",
                runner=runner,
                snapshot={},
                failure_code="WRITING_JOB_FAILED",
                failure_message="智能仿写失败。",
                allow_running_cancel=True,
            )
            self.assertTrue(read_started.wait(timeout=1))
            cancel_started = time.monotonic()
            coordinator.request_cancel(
                "silent-cancel-imitation-job", task_type="word.smart_imitation"
            )
            terminal = coordinator.wait(
                "silent-cancel-imitation-job", task_type="word.smart_imitation"
            )

        self.assertEqual(terminal["status"], "cancelled")
        self.assertLess(time.monotonic() - cancel_started, 0.5)
        self.assertTrue(response.closed)

    def test_smart_imitation_stream_fallback_to_blocking(self):
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

        class MockControl:
            def __init__(self):
                self.running_cancel_disabled = False

            def __call__(self, phase):
                pass

            def publish_text(self, text):
                pass

            def record_metric(self, name, val):
                pass

            def record_provider_attempt(self, attempt_metrics):
                pass

            def cancel_requested(self):
                return False

            def disable_running_cancel(self):
                self.running_cancel_disabled = True

        control = MockControl()

        blocking_response_json = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "仿写阻塞回退结果"}, "finish_reason": "stop"}]
        }).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            sent_requests.append(req)
            call_count += 1
            if call_count == 1:
                raise HTTPError(req.full_url, 415, "Unsupported Media Type", {}, None)
            return FakeHTTPResponse([blocking_response_json], headers={"Content-Type": "application/json"})

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            res = client._post_direct_task(
                task_type="word.smart_imitation",
                trace_id="trace-stream-imitation-fallback-1",
                query="仿写以下内容",
                resolved_task_auth=task_auth,
                timeout=30,
                progress_callback=control,
            )

        self.assertEqual(len(sent_requests), 2)
        req1_body = json.loads(sent_requests[0].data.decode("utf-8"))
        self.assertTrue(req1_body.get("stream"))
        req2_body = json.loads(sent_requests[1].data.decode("utf-8"))
        self.assertFalse(req2_body.get("stream"))
        self.assertTrue(control.running_cancel_disabled)
        self.assertIn("仿写阻塞回退结果", res["answer"])

    def test_smart_imitation_post_delta_disconnect_fails_without_blocking_retry(self):
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
        sse_payload = (
            'data: {"choices":[{"delta":{"content":"部分仿写文本"}}]}\n\n'
        ).encode("utf-8")

        sent_requests = []

        def fake_urlopen(req, timeout=None):
            sent_requests.append(req)
            return FakeHTTPResponse([sse_payload])

        with patch.dict("os.environ", {"AI_WPS_ENABLE_DIRECT_STREAMING": "1"}), patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ProviderMidStreamDisconnectError):
                client._post_direct_task(
                    task_type="word.smart_imitation",
                    trace_id="trace-stream-imitation-abort-1",
                    query="仿写以下内容",
                    resolved_task_auth=task_auth,
                    timeout=30,
                    progress_callback=control,
                )

        self.assertEqual(len(sent_requests), 1)
        self.assertIn("部分仿写文本", "".join(published))

    def test_smart_imitation_cancel_and_completion_race(self):
        coordinator = LongTaskCoordinator(max_running=2, max_queued=2)
        step_event = threading.Event()

        def runner_imitation(_snapshot, control):
            control("streaming")
            control.publish_text("部分仿写文本A")
            control.flush()
            step_event.set()
            for _ in range(50):
                if control.cancel_requested():
                    from app.services.long_task_coordinator import LongTaskCancelled
                    raise LongTaskCancelled(partial_result={"plainText": "部分仿写文本A", "partial": True})
                time.sleep(0.01)
            return {"result": "imitation done"}

        coordinator.submit(
            job_id="race-imitation-a",
            trace_id="trace-race-imitation-a",
            task_type="word.smart_imitation",
            runner=runner_imitation,
            snapshot={},
            failure_code="FAILED",
            failure_message="failed",
            allow_running_cancel=True,
        )

        self.assertTrue(step_event.wait(timeout=2))
        cancel_res = coordinator.request_cancel("race-imitation-a", task_type="word.smart_imitation")
        self.assertEqual(cancel_res["status"], "running")
        self.assertEqual(cancel_res["phase"], "stopping")

        final_a = coordinator.wait("race-imitation-a", task_type="word.smart_imitation")
        self.assertEqual(final_a["status"], "cancelled")
        self.assertIsNotNone(final_a["result"])
        self.assertEqual(final_a["result"]["plainText"], "部分仿写文本A")
        self.assertTrue(final_a["result"]["partial"])


if __name__ == "__main__":
    unittest.main()
