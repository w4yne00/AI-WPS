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
            "version": "0.6.1-alpha",
            "providerType": settings.provider_type,
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
        },
    }
