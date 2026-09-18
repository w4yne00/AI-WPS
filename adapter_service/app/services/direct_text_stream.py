import codecs
import json
import re
import time
from typing import Callable, Dict, Optional

from app.core.errors import (
    AdapterError,
    ProviderMidStreamDisconnectError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

MAX_DIRECT_STREAM_RESPONSE_BYTES = 5 * 1024 * 1024


class StreamingUnsupportedError(Exception):
    """Raised when streaming probe or request receives non-streaming or unsupported response."""
    pass


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

    try:
        # Read chunks
        for raw_chunk in response:
            if time.monotonic() - started_at > timeout:
                raise ProviderTimeoutError("模型服务流式响应读取超时。")
            if cancel_checker and cancel_checker():
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
            lines = line_buffer.split("\n")
            line_buffer = lines.pop()  # Keep trailing incomplete line in buffer

            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_content = line[5:].strip()
                    if data_content == "[DONE]":
                        terminated = True
                        break
                    try:
                        chunk = json.loads(data_content)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict) and isinstance(chunk.get("error"), dict):
                        err_msg = chunk["error"].get("message") or "模型后台在流式响应期间返回错误。"
                        raise ProviderUnavailableError(err_msg)

                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        choice = choices[0] if isinstance(choices[0], dict) else {}
                        delta = choice.get("delta") if isinstance(choice, dict) else {}
                        if isinstance(delta, dict):
                            # Filter out reasoning_content, thought, tool_calls
                            content = delta.get("content") or delta.get("text") or ""
                            if content:
                                filtered = think_filter.feed(content)
                                if filtered:
                                    emit_text(filtered)
                        if choice.get("finish_reason"):
                            finish_reason = choice.get("finish_reason")
                            terminated = True
                            break

            if terminated:
                break

        # Process any final remaining line in line_buffer
        if not terminated and line_buffer:
            line = line_buffer.strip()
            if line.startswith("data:"):
                data_content = line[5:].strip()
                if data_content == "[DONE]":
                    terminated = True
                else:
                    try:
                        chunk = json.loads(data_content)
                        choices = chunk.get("choices") if isinstance(chunk, dict) else None
                        if choices and isinstance(choices, list) and len(choices) > 0:
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
                    except json.JSONDecodeError:
                        pass

        # Flush filter
        tail = think_filter.flush()
        if tail:
            emit_text(tail)

        if not terminated:
            raise ProviderMidStreamDisconnectError("模型后台在流式响应完成前断开连接。")

        return {
            "rewrittenText": "".join(accumulated_chunks),
            "finishReason": finish_reason or "stop",
        }
    finally:
        if hasattr(response, "close"):
            response.close()
