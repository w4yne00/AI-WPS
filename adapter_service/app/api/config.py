from fastapi import APIRouter

from app.core.config import AppSettings, load_settings

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    settings = load_settings()
    return {
        "success": True,
        "data": {
            "servicePort": settings.service_port,
            "providerType": settings.provider_type,
            "providerBaseUrl": settings.provider_base_url,
            "providerChatPath": settings.provider_chat_path,
            "providerMode": settings.provider_mode,
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
        },
    }
