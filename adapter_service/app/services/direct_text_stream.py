import codecs
import json
import time
from typing import Callable, Dict, Optional

from app.core.errors import (
    AdapterError,
    ProviderMidStreamDisconnectError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

MAX_DIRECT_STREAM_RESPONSE_BYTES = 5 * 1024 * 1024
DIRECT_STREAM_READ_BYTES = 64 * 1024


class StreamingUnsupportedError(Exception):
    """Raised when streaming probe or request receives non-streaming or unsupported response."""
    pass


def _set_response_read_timeout(response, timeout_seconds: float) -> None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    settimeout = getattr(sock, "settimeout", None)
    if callable(settimeout):
        settimeout(max(0.001, timeout_seconds))


class StreamingThinkFilter:
    """Incremental filter that suppresses <think>...</think> tags across streaming chunks."""

    def __init__(self) -> None:
        self._state = "NORMAL"  # NORMAL, INSIDE_OPEN_TAG, INSIDE_THINK, INSIDE_CLOSE_TAG
        self._buffer = ""
        self._held_prefix = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        output = []

        while self._buffer:
            if self._state == "NORMAL":
                idx = self._buffer.find("<")
                if idx == -1:
                    output.append(self._buffer)
                    self._buffer = ""
                    break
                if idx > 0:
                    output.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx:]

                # Now self._buffer starts with '<'
                # Check if it could be a think tag
                prefix = self._buffer[:7].lower()
                target = "<think"
                if len(prefix) < len(target) and target.startswith(prefix):
                    # Buffer might be a partial "<think", need more characters
                    break
                elif prefix.startswith("<think"):
                    # Confirmed think tag start
                    close_bracket = self._buffer.find(">")
                    if close_bracket == -1:
                        self._state = "INSIDE_OPEN_TAG"
                        self._buffer = ""
                        break
                    else:
                        self._state = "INSIDE_THINK"
                        self._buffer = self._buffer[close_bracket + 1:]
                else:
                    # Not a think tag! Emit the '<' and continue
                    output.append(self._buffer[0])
                    self._buffer = self._buffer[1:]

            elif self._state == "INSIDE_OPEN_TAG":
                close_bracket = self._buffer.find(">")
                if close_bracket == -1:
                    self._buffer = ""
                    break
                else:
                    self._state = "INSIDE_THINK"
                    self._buffer = self._buffer[close_bracket + 1:]

            elif self._state == "INSIDE_THINK":
                idx = self._buffer.lower().find("</")
                if idx == -1:
                    # Check if trailing '<' might be start of '</'
                    if self._buffer.endswith("<"):
                        self._buffer = "<"
                    else:
                        self._buffer = ""
                    break

                self._buffer = self._buffer[idx:]
                prefix = self._buffer[:8].lower()
                target = "</think"
                if len(prefix) < len(target) and target.startswith(prefix):
                    # Incomplete '</think' tag, wait for more text
                    break
                elif prefix.startswith("</think"):
                    close_bracket = self._buffer.find(">")
                    if close_bracket == -1:
                        self._state = "INSIDE_CLOSE_TAG"
                        self._buffer = ""
                        break
                    else:
                        self._state = "NORMAL"
                        self._buffer = self._buffer[close_bracket + 1:]
                else:
                    # Not '</think', discard '</' and keep searching
                    self._buffer = self._buffer[2:]

            elif self._state == "INSIDE_CLOSE_TAG":
                close_bracket = self._buffer.find(">")
                if close_bracket == -1:
                    self._buffer = ""
                    break
                else:
                    self._state = "NORMAL"
                    self._buffer = self._buffer[close_bracket + 1:]

        return "".join(output)

    def flush(self) -> str:
        res = ""
        if self._state == "NORMAL" and self._buffer:
            res = self._buffer
        self._buffer = ""
        return res


def read_direct_text_stream(
    response,
    publish_callback: Callable[[str], None],
    record_metric_callback: Optional[Callable[[str, int], None]] = None,
    start_mono: Optional[float] = None,
    timeout: float = 600.0,
    max_bytes: int = MAX_DIRECT_STREAM_RESPONSE_BYTES,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> Dict:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    think_filter = StreamingThinkFilter()
    started_at = time.monotonic()
    received_bytes = 0
    accumulated_chunks = []
    first_visible_recorded = False
    terminated = False
    finish_reason = None
    line_buffer = ""
    event_data_lines = []
    usage = {}
    response_id = ""
    response_model = ""

    def emit_text(text: str) -> None:
        nonlocal first_visible_recorded
        if not text:
            return
        if not first_visible_recorded:
            first_visible_recorded = True
            if record_metric_callback and start_mono is not None:
                first_visible_ms = int((time.monotonic() - start_mono) * 1000)
                record_metric_callback("providerFirstVisibleMs", max(0, first_visible_ms))
        publish_callback(text)
        accumulated_chunks.append(text)

    def process_event() -> None:
        nonlocal terminated, finish_reason, usage, response_id, response_model
        if not event_data_lines:
            return
        data_content = "\n".join(event_data_lines)
        event_data_lines[:] = []
        if not data_content:
            return
        if data_content.strip() == "[DONE]":
            terminated = True
            return
        try:
            chunk = json.loads(data_content)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                "MODEL_RESULT_INVALID",
                "模型后台返回了无法解析的流式事件。",
                status_code=502,
            ) from exc

        if not isinstance(chunk, dict):
            return
        if isinstance(chunk.get("error"), dict):
            err_msg = chunk["error"].get("message") or "模型后台在流式响应期间返回错误。"
            raise ProviderUnavailableError(err_msg)

        raw_usage = chunk.get("usage")
        if isinstance(raw_usage, dict):
            usage = {
                key: value
                for key, value in raw_usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            }
        if chunk.get("id") is not None:
            response_id = str(chunk.get("id"))
        if chunk.get("model") is not None:
            response_model = str(chunk.get("model"))

        choices = chunk.get("choices")
        if not choices or not isinstance(choices, list):
            return
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice, dict) else {}
        if isinstance(delta, dict):
            content = delta.get("content") or delta.get("text") or ""
            if content:
                filtered = think_filter.feed(content)
                if filtered:
                    emit_text(filtered)
        if choice.get("finish_reason"):
            finish_reason = choice.get("finish_reason")
            terminated = True

    def process_line(raw_line: str) -> None:
        if raw_line.endswith("\r"):
            raw_line = raw_line[:-1]
        if raw_line == "":
            process_event()
            return
        if raw_line.startswith(":"):
            return
        if raw_line.startswith("data:"):
            value = raw_line[5:]
            if value.startswith(" "):
                value = value[1:]
            event_data_lines.append(value)

    try:
        read_chunk = getattr(response, "read1", None)
        if not callable(read_chunk):
            read_chunk = response.read

        while not terminated:
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                raise ProviderTimeoutError("模型服务流式响应读取超时。")
            if cancel_checker and cancel_checker():
                from app.services.long_task_coordinator import LongTaskCancelled

                raise LongTaskCancelled(
                    partial_result={
                        "plainText": "".join(accumulated_chunks),
                        "rewrittenText": "".join(accumulated_chunks),
                        "partial": True,
                        "stopReason": "cancelled",
                    }
                )

            remaining_bytes = max_bytes - received_bytes
            read_size = min(DIRECT_STREAM_READ_BYTES, max(1, remaining_bytes + 1))
            _set_response_read_timeout(response, timeout - elapsed)
            raw_chunk = read_chunk(read_size)
            if time.monotonic() - started_at >= timeout:
                raise ProviderTimeoutError("模型服务流式响应读取超时。")
            if not raw_chunk:
                break
            if isinstance(raw_chunk, bytes):
                received_bytes += len(raw_chunk)
                chunk_str = decoder.decode(raw_chunk)
            else:
                chunk_str = str(raw_chunk)
                received_bytes += len(chunk_str.encode("utf-8"))

            if received_bytes > max_bytes:
                raise AdapterError(
                    "MODEL_RESPONSE_SIZE_LIMIT",
                    "模型流式响应超过 5 MiB 上限。",
                    status_code=502,
                )

            line_buffer += chunk_str
            while "\n" in line_buffer and not terminated:
                if cancel_checker and cancel_checker():
                    from app.services.long_task_coordinator import LongTaskCancelled

                    raise LongTaskCancelled(
                        partial_result={
                            "plainText": "".join(accumulated_chunks),
                            "rewrittenText": "".join(accumulated_chunks),
                            "partial": True,
                            "stopReason": "cancelled",
                        }
                    )
                raw_line, line_buffer = line_buffer.split("\n", 1)
                process_line(raw_line)

        if not terminated:
            line_buffer += decoder.decode(b"", final=True)
            if line_buffer:
                process_line(line_buffer)
            if event_data_lines:
                process_event()

        # Flush filter
        tail = think_filter.flush()
        if tail:
            emit_text(tail)

        if not terminated:
            raise ProviderMidStreamDisconnectError("模型后台在流式响应完成前断开连接。")

        return {
            "rewrittenText": "".join(accumulated_chunks),
            "finishReason": finish_reason or "stop",
            "usage": usage,
            "id": response_id,
            "model": response_model,
        }
    finally:
        if hasattr(response, "close"):
            response.close()
