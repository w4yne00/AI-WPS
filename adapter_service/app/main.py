from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.config import router as config_router
from app.api.writing_policies import router as writing_policy_router
from app.api.excel import router as excel_router
from app.api.health import router as health_router
from app.api.ppt import router as ppt_router
from app.api.provider import router as provider_router
from app.api.templates import router as templates_router
from app.api.word import router as word_router
from app.core.errors import AdapterError
from app.core.logging import get_logger
from app.core.tracing import new_trace_id
from app.services.provider_client import record_provider_debug

app = FastAPI(title="wps-ai-adapter", version="0.19.1-alpha")
app.include_router(health_router)
app.include_router(config_router)
app.include_router(provider_router)
app.include_router(templates_router)
app.include_router(word_router)
app.include_router(excel_router)
app.include_router(ppt_router)
app.include_router(writing_policy_router)

logger = get_logger(__name__)
PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES = 15 * 1024 * 1024
WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES = 7 * 1024 * 1024


class WritingPolicyImportBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope, receive, send) -> None:
        if not self._is_preview_request(scope):
            await self.app(scope, receive, send)
            return

        buffered_body = bytearray()
        content_length = self._content_length(scope)
        saw_request = False
        disconnected = False

        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "http.disconnect":
                disconnected = True
                del message
                break
            if message_type != "http.request":
                del message
                continue

            saw_request = True
            chunk = message.get("body", b"")
            next_received_bytes = len(buffered_body) + len(chunk)
            if next_received_bytes > self.max_bytes:
                del chunk, message
                await self._reject(
                    scope,
                    receive,
                    send,
                    self._trace_id(scope),
                    next_received_bytes,
                )
                return

            buffered_body.extend(chunk)
            more_body = bool(message.get("more_body", False))
            del chunk, message
            if not more_body:
                if content_length > self.max_bytes:
                    await self._reject(
                        scope,
                        receive,
                        send,
                        self._trace_id(scope),
                        content_length,
                    )
                    return
                break

        consolidated_body = bytes(buffered_body)
        del buffered_body
        replay_step = 0

        async def replay_receive():
            nonlocal replay_step
            if saw_request and replay_step == 0:
                replay_step = 1
                return {
                    "type": "http.request",
                    "body": consolidated_body,
                    "more_body": disconnected,
                }
            if disconnected:
                replay_step = 2
                return {"type": "http.disconnect"}
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _is_preview_request(scope) -> bool:
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/writing-policies/imports/preview"
        )

    @staticmethod
    def _header(scope, name: bytes):
        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value.decode("latin-1")
        return None

    @classmethod
    def _trace_id(cls, scope) -> str:
        state_trace_id = scope.get("state", {}).get("request_trace_id")
        if state_trace_id is not None:
            return str(state_trace_id)
        header_trace_id = cls._header(scope, b"x-trace-id")
        if header_trace_id is not None:
            return header_trace_id
        return new_trace_id("http")

    @classmethod
    def _content_length(cls, scope) -> int:
        try:
            return int(cls._header(scope, b"content-length") or "")
        except (TypeError, ValueError):
            return 0

    async def _reject(
        self,
        scope,
        receive,
        send,
        trace_id: str,
        content_length: int,
    ) -> None:
        scope.setdefault("state", {})["writing_policy_body_limit_rejected"] = True
        message = "写作规范导入预览请求超过 7 MB 限制。"
        logger.warning(
            "traceId=%s method=%s path=%s status=413 contentLength=%s",
            trace_id,
            scope.get("method", ""),
            scope.get("path", ""),
            content_length,
        )
        response = JSONResponse(
            status_code=413,
            content={
                "success": False,
                "traceId": trace_id,
                "taskType": "writing_policy",
                "message": message,
                "data": {},
                "errors": [
                    {"code": "IMPORT_REQUEST_TOO_LARGE", "message": message}
                ],
            },
        )
        response.headers["X-Trace-Id"] = trace_id
        await response(scope, receive, send)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", new_trace_id("http"))
    request.state.request_trace_id = trace_id
    if request.url.path == "/ppt/document-files":
        try:
            content_length = int(request.headers.get("Content-Length", ""))
        except (TypeError, ValueError):
            content_length = 0
        if content_length <= 0 or request.headers.get("Transfer-Encoding"):
            message = "上传请求缺少有效的 Content-Length，请重新选择文件。"
            response = JSONResponse(
                status_code=411,
                content={
                    "success": False,
                    "traceId": trace_id,
                    "taskType": "ppt.slide_assistant",
                    "message": message,
                    "data": {},
                    "errors": [{"code": "CONTENT_LENGTH_REQUIRED", "message": message}],
                },
            )
            response.headers["X-Trace-Id"] = trace_id
            return response
        if content_length > PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES:
            message = "上传请求超过 15 MB 限制，请重新选择文件。"
            logger.warning(
                "traceId=%s method=%s path=%s status=413 contentLength=%s",
                trace_id,
                request.method,
                request.url.path,
                content_length,
            )
            response = JSONResponse(
                status_code=413,
                content={
                    "success": False,
                    "traceId": trace_id,
                    "taskType": "ppt.slide_assistant",
                    "message": message,
                    "data": {},
                    "errors": [{"code": "PPT_DOCUMENT_TOO_LARGE", "message": message}],
                },
            )
            response.headers["X-Trace-Id"] = trace_id
            return response
    try:
        response = await call_next(request)
    except Exception:
        if not getattr(
            request.state, "writing_policy_body_limit_rejected", False
        ):
            logger.exception(
                "traceId=%s method=%s path=%s status=500",
                trace_id,
                request.method,
                request.url.path,
            )
        raise

    response.headers["X-Trace-Id"] = trace_id
    if getattr(request.state, "writing_policy_body_limit_rejected", False):
        return response
    logger.info(
        "traceId=%s method=%s path=%s status=%s",
        trace_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


app.add_middleware(
    WritingPolicyImportBodyLimitMiddleware,
    max_bytes=WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AdapterError)
async def handle_adapter_error(request: Request, exc: AdapterError) -> JSONResponse:
    trace_id = request.headers.get("X-Trace-Id", new_trace_id("error"))
    logger.error(
        "traceId=%s method=%s path=%s code=%s message=%s",
        trace_id,
        request.method,
        request.url.path,
        exc.code,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "traceId": trace_id,
            "taskType": _task_type_from_path(request.url.path),
            "message": exc.message,
            "data": {},
            "errors": [{"code": exc.code, "message": exc.message}],
        },
    )


def _task_type_from_path(path: str) -> str:
    if path.startswith("/writing-policies/"):
        return "writing_policy"
    return {
        "/word/smart-write": "word.smart_write",
        "/word/smart-imitation": "word.smart_imitation",
        "/word/document-review": "word.document_review",
        "/word/document-review/jobs": "word.document_review",
        "/word/format-review": "word.format_review",
        "/excel/analysis": "excel.analysis",
        "/excel/analysis/jobs": "excel.analysis",
        "/ppt/slide-assistant/jobs": "ppt.slide_assistant",
        "/ppt/document-files": "ppt.slide_assistant",
    }.get(path, "adapter.validation")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = request.headers.get("X-Trace-Id", new_trace_id("validation"))
    task_type = _task_type_from_path(request.url.path)
    errors = [
        {
            "loc": ".".join(str(part) for part in item.get("loc", [])),
            "type": str(item.get("type", "")),
            "message": str(item.get("msg", ""))[:160],
        }
        for item in exc.errors()[:8]
    ]
    record_provider_debug(
        {
            "traceId": trace_id,
            "taskType": task_type,
            "provider": "adapter",
            "skipReason": "request_validation_failed",
            "validation": {
                "path": request.url.path,
                "errorCount": len(exc.errors()),
                "errors": errors,
            },
        }
    )
    status_code = 400 if request.url.path.startswith("/writing-policies/") else 422
    logger.warning(
        "traceId=%s method=%s path=%s status=%s validationErrors=%s",
        trace_id,
        request.method,
        request.url.path,
        status_code,
        errors,
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "traceId": trace_id,
            "taskType": task_type,
            "message": "Request payload validation failed.",
            "data": {"validation": {"errorCount": len(exc.errors()), "errors": errors}},
            "errors": [{"code": "REQUEST_VALIDATION_FAILED", "message": "请求数据格式不符合 adapter 入参要求。"}],
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    trace_id = request.headers.get("X-Trace-Id", new_trace_id("error"))
    logger.exception(
        "traceId=%s method=%s path=%s code=UNEXPECTED_ERROR",
        trace_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "traceId": trace_id,
            "taskType": "adapter.error",
            "message": "Unexpected adapter failure.",
            "data": {},
            "errors": [{"code": "UNEXPECTED_ERROR", "message": str(exc)}],
        },
    )
