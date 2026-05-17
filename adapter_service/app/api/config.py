from fastapi import APIRouter

from app.core.config import load_settings, task_routes_to_dict
from app.services.provider_client import ProviderClient

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    settings = load_settings()
    provider = ProviderClient(settings)
    task_routes = task_routes_to_dict(settings)
    for task_type, route_summary in task_routes.items():
        route = settings.task_routes.get(task_type)
        api_key_ref = route.api_key_ref if route else route_summary.get("apiKeyRef", "default")
        route_summary["configured"] = bool(provider.get_task_api_key(route)) if route else bool(provider.get_api_key(api_key_ref))
        route_summary["authSource"] = provider.get_route_auth_source(api_key_ref)
    return {
        "success": True,
        "data": {
            "servicePort": settings.service_port,
            "providerName": settings.provider_name,
            "providerType": settings.provider_type,
            "providerBaseUrl": settings.provider_base_url,
            "providerChatPath": settings.provider_chat_path,
            "providerMode": settings.provider_mode,
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
            "taskRoutes": task_routes,
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
        },
    }
