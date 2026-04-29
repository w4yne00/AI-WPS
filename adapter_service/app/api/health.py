from fastapi import APIRouter
import os

from app.core.config import load_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    settings = load_settings()
    return {
        "success": True,
        "data": {
            "service": "wps-ai-adapter",
            "status": "ok",
            "version": "0.1.0",
            "providerType": settings.provider_type,
            "providerConfigured": bool(os.getenv(settings.provider_api_key_env)),
        },
    }
