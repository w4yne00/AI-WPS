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
            "difyBaseUrl": settings.dify_base_url,
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
        },
    }
