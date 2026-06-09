from fastapi import APIRouter
from app.core.config import load_settings
from app.services.provider_client import ProviderClient

router = APIRouter()


@router.get("/health")
def health() -> dict:
    settings = load_settings()
    provider = ProviderClient(settings)
    return {
        "success": True,
        "data": {
            "service": "wps-ai-adapter",
            "status": "ok",
            "version": "0.12.16-alpha",
            "mode": "uvicorn",
            "providerName": settings.provider_name,
            "providerType": settings.provider_type,
            "providerBaseUrlConfigured": bool(settings.provider_base_url.strip()),
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
            "taskApiKeys": provider.build_task_api_key_status(),
            "taskRouteCount": 0,
            "taskRouteConfiguredCount": 0,
        },
    }
