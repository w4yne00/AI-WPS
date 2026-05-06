from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import save_active_provider, save_provider_base_url
from app.services.provider_client import ProviderClient, clear_local_api_key, save_local_api_key

router = APIRouter()


class ProviderApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")
    provider_id: Optional[str] = Field(default=None, alias="providerId")


class ProviderBaseUrlRequest(BaseModel):
    base_url: str = Field(alias="baseUrl")
    provider_id: Optional[str] = Field(default=None, alias="providerId")
    provider_name: Optional[str] = Field(default=None, alias="providerName")


class ActiveProviderRequest(BaseModel):
    provider_id: str = Field(alias="providerId")


@router.get("/provider/status")
def get_provider_status() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
            "providerId": client.settings.provider_id,
            "providerName": client.settings.provider_name,
            "providerType": client.settings.provider_type,
        },
    }


@router.post("/provider/api-key")
def save_provider_api_key(request: ProviderApiKeyRequest) -> dict:
    client_before = ProviderClient()
    provider_id = request.provider_id or client_before.settings.provider_id
    save_local_api_key(request.api_key, provider_id=provider_id)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "providerId": provider_id,
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }


@router.post("/provider/base-url")
def save_provider_url(request: ProviderBaseUrlRequest) -> dict:
    save_provider_base_url(
        request.base_url,
        provider_id=request.provider_id,
        provider_name=request.provider_name,
    )
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "providerId": client.settings.provider_id,
            "providerName": client.settings.provider_name,
            "providerBaseUrl": client.settings.provider_base_url,
            "providerType": client.settings.provider_type,
        },
    }


@router.post("/provider/active")
def set_active_provider(request: ActiveProviderRequest) -> dict:
    save_active_provider(request.provider_id)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "providerId": client.settings.provider_id,
            "providerName": client.settings.provider_name,
            "providerBaseUrl": client.settings.provider_base_url,
            "providerType": client.settings.provider_type,
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }


@router.delete("/provider/api-key")
def delete_provider_api_key() -> dict:
    client = ProviderClient()
    clear_local_api_key(provider_id=client.settings.provider_id)
    client = ProviderClient()
    return {
        "success": True,
        "message": "cleared",
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }
