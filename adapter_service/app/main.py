from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.config import router as config_router
from app.api.health import router as health_router
from app.api.provider import router as provider_router
from app.api.templates import router as templates_router
from app.api.word import router as word_router
from app.core.errors import AdapterError
from app.core.logging import get_logger
from app.core.tracing import new_trace_id
from app.services.provider_client import record_provider_debug

app = FastAPI(title="wps-ai-adapter", version="0.12.10-alpha")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(config_router)
app.include_router(provider_router)
app.include_router(templates_router)
app.include_router(word_router)

logger = get_logger(__name__)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", new_trace_id("http"))
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "traceId=%s method=%s path=%s status=500",
            trace_id,
            request.method,
            request.url.path,
        )
        raise

    response.headers["X-Trace-Id"] = trace_id
    logger.info(
        "traceId=%s method=%s path=%s status=%s",
        trace_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


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
            "taskType": "adapter.error",
            "message": exc.message,
            "data": {},
            "errors": [{"code": exc.code, "message": exc.message}],
        },
    )


def _task_type_from_path(path: str) -> str:
    return {
        "/word/smart-write": "word.smart_write",
        "/word/document-review": "word.document_review",
        "/word/format-review": "word.format_review",
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
    logger.warning(
        "traceId=%s method=%s path=%s status=422 validationErrors=%s",
        trace_id,
        request.method,
        request.url.path,
        errors,
    )
    return JSONResponse(
        status_code=422,
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
