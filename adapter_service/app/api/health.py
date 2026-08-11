from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.health import (
    SERVICE_MODE,
    SERVICE_NAME,
    SERVICE_VERSION,
    get_health_snapshot,
)


router = APIRouter()


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data}


@router.get("/health/live")
def live_health() -> dict:
    return _envelope(
        {
            "service": SERVICE_NAME,
            "status": "live",
            "version": SERVICE_VERSION,
            "mode": SERVICE_MODE,
        }
    )


@router.get("/health/ready")
def ready_health():
    data = get_health_snapshot()
    return JSONResponse(
        status_code=503 if data["status"] == "recovery" else 200,
        content=_envelope(data),
    )


@router.get("/health")
def health() -> dict:
    return _envelope(get_health_snapshot())
