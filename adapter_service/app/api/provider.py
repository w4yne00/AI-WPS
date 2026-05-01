from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import save_provider_base_url
from app.services.provider_client import ProviderClient, clear_local_api_key, save_local_api_key

router = APIRouter()


class ProviderApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


class ProviderBaseUrlRequest(BaseModel):
    base_url: str = Field(alias="baseUrl")


@router.get("/provider/status")
def get_provider_status() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
            "providerType": client.settings.provider_type,
        },
    }


@router.post("/provider/api-key")
def save_provider_api_key(request: ProviderApiKeyRequest) -> dict:
    save_local_api_key(request.api_key)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }


@router.post("/provider/base-url")
def save_provider_url(request: ProviderBaseUrlRequest) -> dict:
    save_provider_base_url(request.base_url)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "providerBaseUrl": client.settings.provider_base_url,
            "providerType": client.settings.provider_type,
        },
    }


@router.delete("/provider/api-key")
def delete_provider_api_key() -> dict:
    clear_local_api_key()
    client = ProviderClient()
    return {
        "success": True,
        "message": "cleared",
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }
