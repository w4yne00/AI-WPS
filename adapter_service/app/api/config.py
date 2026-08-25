from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import default_config_path, load_settings
from app.core.features import (
    deterministic_format_review_enabled,
    full_document_review_enabled,
    image_semantics_enabled,
)
from app.services.provider_client import ProviderClient
from app.services.word.image_semantics import ImageSemanticConfigStore

router = APIRouter()


class ImageSemanticSettingsRequest(BaseModel):
    enabled: bool


@router.get("/config")
def get_config() -> dict:
    settings = load_settings()
    provider = ProviderClient(settings)
    image_semantic_settings = ImageSemanticConfigStore(default_config_path()).get()
    return {
        "success": True,
        "data": {
            "servicePort": settings.service_port,
            "providerName": settings.provider_name,
            "providerType": settings.provider_type,
            "providerBaseUrl": settings.provider_base_url,
            "providerChatPath": settings.provider_chat_path,
            "providerMode": settings.provider_mode,
            "providerBaseUrlConfigured": bool(settings.provider_base_url.strip()),
            "providerConfigured": provider.is_configured(),
            "providerAuthSource": provider.get_auth_source(),
            "taskApiKeys": provider.build_task_api_key_status(),
            "taskRouteConfiguredCount": 0,
            "taskRoutes": {},
            "logPath": settings.log_path,
            "templateRoot": settings.template_root,
            "timeoutSeconds": settings.timeout_seconds,
            "features": {
                "fullDocumentReviewEnabled": full_document_review_enabled(),
                "deterministicFormatReviewEnabled": deterministic_format_review_enabled(),
                "imageSemanticsEnabled": image_semantics_enabled(),
            },
            "formatReview": {
                "imageSemantics": image_semantic_settings,
            },
        },
    }


@router.get("/config/image-semantics")
def get_image_semantic_settings() -> dict:
    return {
        "success": True,
        "data": ImageSemanticConfigStore(default_config_path()).get(),
    }


@router.put("/config/image-semantics")
def update_image_semantic_settings(request: ImageSemanticSettingsRequest) -> dict:
    store = ImageSemanticConfigStore(default_config_path())
    data = store.set_enabled(request.enabled)
    return {"success": True, "message": "saved", "data": data}
