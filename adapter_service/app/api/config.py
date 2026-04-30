from fastapi import APIRouter

from app.core.config import AppSettings, load_settings
from app.services.provider_client import ProviderClient

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    settings = load_settings()
    provider = ProviderClient(settings)
    return {
        "success": True,
        "data": {
            "servicePort": settings.service_port,
            "providerType": settings.provider_type,
            "providerBaseUrl": settings.provider_base_url,
            "providerChatPath": settings.provider_chat_path,
            "providerMode": settings.provider_mode,
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
        },
    }
