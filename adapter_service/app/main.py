from fastapi import FastAPI, Request
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

app = FastAPI(title="wps-ai-adapter", version="0.5.1-alpha")
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
