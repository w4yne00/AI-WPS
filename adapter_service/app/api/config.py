from fastapi import APIRouter

from app.core.config import AppSettings, load_config_payload, load_settings, normalize_providers
from app.services.provider_client import ProviderClient

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    settings = load_settings()
    provider = ProviderClient(settings)
    config_payload = load_config_payload()
    providers = []
    for item in normalize_providers(config_payload):
        provider_settings = AppSettings(
            service_port=settings.service_port,
            provider_id=item["id"],
            provider_name=item["name"],
            provider_type=item["type"],
            provider_base_url=item["baseUrl"],
            provider_api_key_env=item["apiKeyEnv"],
            provider_chat_path=item["chatPath"],
            provider_mode=item["mode"],
            log_path=settings.log_path,
            template_root=settings.template_root,
            timeout_seconds=settings.timeout_seconds,
        )
        provider_client = ProviderClient(provider_settings)
        providers.append(
            {
                "id": item["id"],
                "name": item["name"],
                "type": item["type"],
                "baseUrl": item["baseUrl"],
                "chatPath": item["chatPath"],
                "mode": item["mode"],
                "active": item["id"] == settings.provider_id,
                "configured": provider_client.is_configured(),
                "authSource": provider_client.get_auth_source(),
            }
        )
    return {
        "success": True,
        "data": {
            "servicePort": settings.service_port,
            "activeProviderId": settings.provider_id,
            "providerName": settings.provider_name,
            "providerType": settings.provider_type,
            "providerBaseUrl": settings.provider_base_url,
            "providerChatPath": settings.provider_chat_path,
            "providerMode": settings.provider_mode,
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
            "providers": providers,
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
        },
    }
