import io
import json
import time
import unittest

from app.core.errors import (
    AdapterError,
    ProviderAuthError,
    ProviderMidStreamDisconnectError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.direct_text_stream import (
    StreamingThinkFilter,
    StreamingUnsupportedError,
    read_direct_text_stream,
)


class FakeHTTPResponse:
    def __init__(self, chunks, headers=None, status=200):
        self._chunks = list(chunks)
        self._index = 0
        self.status = status
        self.headers = headers or {"Content-Type": "text/event-stream; charset=utf-8"}
        self.closed = False

    def read(self, amt=None):
        if self._index >= len(self._chunks):
            return b""
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    def __iter__(self):
        return self

    def __next__(self):
        data = self.read()
        if not data:
            raise StopIteration
        return data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.closed = True


class BoundedReadOnlyResponse:
    def __init__(self, content):
        self._content = content
        self._offset = 0
        self.closed = False

    def read1(self, amt):
        chunk = self._content[self._offset:self._offset + amt]
        self._offset += len(chunk)
        return chunk

    def __iter__(self):
        raise AssertionError("stream parser must not use unbounded line iteration")

    def close(self):
        self.closed = True


class ClockAdvancingResponse(BoundedReadOnlyResponse):
    def __init__(self, content, advance_clock):
        super().__init__(content)
        self._advance_clock = advance_clock

    def read1(self, amt):
        self._advance_clock()
        return super().read1(amt)


class StreamingThinkFilterTests(unittest.TestCase):
    def test_passthrough_normal_text(self):
        filter_ = StreamingThinkFilter()
        out1 = filter_.feed("Hello ")
        out2 = filter_.feed("world!")
        out3 = filter_.flush()
        self.assertEqual(out1 + out2 + out3, "Hello world!")

    def test_strip_single_chunk_think_tag(self):
        filter_ = StreamingThinkFilter()
        out = filter_.feed("<think>This is reasoning</think>Actual answer")
        out += filter_.flush()
        self.assertEqual(out, "Actual answer")

    def test_strip_think_tag_split_across_chunks(self):
        filter_ = StreamingThinkFilter()
        chunks = ["Hello <th", "ink>internal reasoning", " step 2</th", "ink> world!"]
        output = []
        for c in chunks:
            output.append(filter_.feed(c))
        output.append(filter_.flush())
        self.assertEqual("".join(output), "Hello  world!")

    def test_think_tag_with_attributes(self):
        filter_ = StreamingThinkFilter()
        chunks = ['<think class="test" id=\'1\'>reasoning</think>Done']
        out = "".join(filter_.feed(c) for c in chunks) + filter_.flush()
        self.assertEqual(out, "Done")

    def test_unclosed_think_tag_at_end_discards_reasoning(self):
        filter_ = StreamingThinkFilter()
        chunks = ["Start <think>thinking forever without close"]
        out = "".join(filter_.feed(c) for c in chunks) + filter_.flush()
        self.assertEqual(out, "Start ")

    def test_non_think_less_than_bracket(self):
        filter_ = StreamingThinkFilter()
        chunks = ["if 3 <", " 5 and 4 > 2: pass"]
        out = "".join(filter_.feed(c) for c in chunks) + filter_.flush()
        self.assertEqual(out, "if 3 < 5 and 4 > 2: pass")

    def test_case_insensitive_think_tags(self):
        filter_ = StreamingThinkFilter()
        chunks = ["<THINK>Reasoning</THINK>Result"]
        out = "".join(filter_.feed(c) for c in chunks) + filter_.flush()
        self.assertEqual(out, "Result")


class DirectTextStreamTests(unittest.TestCase):
    def test_utf8_split_across_chunks_and_events(self):
        # Chinese characters "你好世界" encoded in UTF-8
        chunk1 = b'data: {"choices":[{"delta":{"content":"\xe4\xbd'
        chunk2 = b'\xa0\xe5\xa5\xbd"}}]}\n\n'
        chunk3 = b'data: {"choices":[{"delta":{"content":"\xe4\xb8\x96\xe7\x95\x8c"}}]}\n\n'
        chunk4 = b'data: [DONE]\n\n'

        response = FakeHTTPResponse([chunk1, chunk2, chunk3, chunk4])
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "你好世界")
        self.assertEqual("".join(published), "你好世界")
        self.assertTrue(response.closed)

    def test_multiple_data_lines_in_single_chunk(self):
        payload = (
            b'data: {"choices":[{"delta":{"content":"Line 1 "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"Line 2 "}}]}\n\n'
            b'data: [DONE]\n\n'
        )
        response = FakeHTTPResponse([payload])
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Line 1 Line 2 ")
        self.assertEqual("".join(published), "Line 1 Line 2 ")

    def test_multiple_data_fields_form_one_sse_event(self):
        payload = (
            b'data: {"choices":\n'
            b'data: [{"delta":{"content":"joined event"}}]}\n\n'
            b'data: [DONE]\n\n'
        )
        response = FakeHTTPResponse([payload])
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "joined event")
        self.assertEqual(published, ["joined event"])

    def test_heartbeat_comments_and_empty_deltas_ignored(self):
        payloads = [
            b": ping\n\n",
            b'data: {"choices":[{"delta":{}}]}\n\n',
            b"\n",
            b'data: {"choices":[{"delta":{"content":""}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"Actual content"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Actual content")
        self.assertEqual("".join(published), "Actual content")

    def test_reasoning_content_and_thought_suppressed(self):
        payloads = [
            b'data: {"choices":[{"delta":{"reasoning_content":"Step 1: thinking"}}]}\n\n',
            b'data: {"choices":[{"delta":{"thought":"Step 2: more thinking"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"Visible answer"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Visible answer")
        self.assertEqual("".join(published), "Visible answer")

    def test_tool_calls_ignored(self):
        payloads = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_1"}]}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Hello")
        self.assertEqual("".join(published), "Hello")

    def test_usage_chunk_handled_cleanly(self):
        payloads = [
            b'data: {"choices":[{"delta":{"content":"Result"}}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
            b'data: [DONE]\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Result")
        self.assertEqual("".join(published), "Result")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 10, "completion_tokens": 5},
        )

    def test_finish_reason_terminates_stream(self):
        payloads = [
            b'data: {"choices":[{"delta":{"content":"Final piece"},"finish_reason":"stop"}]}\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        result = read_direct_text_stream(
            response=response,
            publish_callback=published.append,
            timeout=5.0,
        )

        self.assertEqual(result["rewrittenText"], "Final piece")
        self.assertEqual(result["finishReason"], "stop")

    def test_premature_disconnect_raises_error(self):
        payloads = [
            b'data: {"choices":[{"delta":{"content":"Incomplete..."}}]}\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        published = []

        with self.assertRaises(ProviderMidStreamDisconnectError):
            read_direct_text_stream(
                response=response,
                publish_callback=published.append,
                timeout=5.0,
            )

    def test_response_size_limit_5mib(self):
        large_chunk = b'data: {"choices":[{"delta":{"content":"' + (b'x' * (5 * 1024 * 1024 + 10)) + b'"}}]}\n\n'
        response = FakeHTTPResponse([large_chunk])

        with self.assertRaises(AdapterError) as ctx:
            read_direct_text_stream(
                response=response,
                publish_callback=lambda text: None,
                timeout=5.0,
            )
        self.assertEqual(ctx.exception.code, "MODEL_RESPONSE_SIZE_LIMIT")
        self.assertEqual(ctx.exception.status_code, 502)

    def test_response_size_limit_uses_bounded_reads_without_newlines(self):
        response = BoundedReadOnlyResponse(b"x" * 65)

        with self.assertRaises(AdapterError) as ctx:
            read_direct_text_stream(
                response=response,
                publish_callback=lambda text: None,
                timeout=5.0,
                max_bytes=64,
            )

        self.assertEqual(ctx.exception.code, "MODEL_RESPONSE_SIZE_LIMIT")
        self.assertTrue(response.closed)

    def test_total_timeout_is_checked_after_each_bounded_read(self):
        from unittest.mock import patch

        clock = [100.0]
        response = ClockAdvancingResponse(
            b"data: [DONE]\n\n",
            lambda: clock.__setitem__(0, 106.0),
        )

        with patch(
            "app.services.direct_text_stream.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            with self.assertRaises(ProviderTimeoutError):
                read_direct_text_stream(
                    response=response,
                    publish_callback=lambda text: None,
                    timeout=5.0,
                )

        self.assertTrue(response.closed)

    def test_each_read_uses_only_the_remaining_total_deadline(self):
        from unittest.mock import patch

        class RecordingSocket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

        class SocketResponse(BoundedReadOnlyResponse):
            def __init__(self, content):
                super().__init__(content)
                self.socket = RecordingSocket()
                self.fp = type("Buffered", (), {})()
                self.fp.raw = type("Raw", (), {"_sock": self.socket})()

        response = SocketResponse(b"data: [DONE]\n\n")
        clock_values = iter((100.0, 104.5, 104.5))

        with patch(
            "app.services.direct_text_stream.time.monotonic",
            side_effect=lambda: next(clock_values),
        ):
            read_direct_text_stream(
                response=response,
                publish_callback=lambda text: None,
                timeout=5.0,
            )

        self.assertEqual(len(response.socket.timeouts), 1)
        self.assertGreater(response.socket.timeouts[0], 0)
        self.assertLessEqual(response.socket.timeouts[0], 0.5)

    def test_first_visible_metric_timing(self):
        payloads = [
            b'data: {"choices":[{"delta":{"reasoning_content":"skip this"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"<think>skip this</think>"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"First visible!"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        response = FakeHTTPResponse(payloads)
        metrics = {}

        def record_metric(name, val):
            metrics[name] = val

        read_direct_text_stream(
            response=response,
            publish_callback=lambda text: None,
            record_metric_callback=record_metric,
            start_mono=time.monotonic() - 0.100,
            timeout=5.0,
        )

        self.assertIn("providerFirstVisibleMs", metrics)
        self.assertGreaterEqual(metrics["providerFirstVisibleMs"], 90)


if __name__ == "__main__":
    unittest.main()
