from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {
        "success": True,
        "data": {
            "service": "wps-ai-adapter",
            "status": "ok",
            "version": "0.1.0",
        },
    }
