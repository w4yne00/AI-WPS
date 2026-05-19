from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import save_provider_base_url
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    clear_route_api_key,
    save_local_api_key,
    save_route_api_key,
)

router = APIRouter()


class ProviderApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


class ProviderTaskApiKeyRequest(BaseModel):
    api_key_ref: str = Field(alias="apiKeyRef")
    api_key: str = Field(alias="apiKey")


class ProviderBaseUrlRequest(BaseModel):
    base_url: str = Field(alias="baseUrl")
    provider_name: Optional[str] = Field(default=None, alias="providerName")


@router.get("/provider/status")
def get_provider_status() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
            "providerName": client.settings.provider_name,
            "providerType": client.settings.provider_type,
        },
    }


@router.get("/provider/route-diagnostics")
def get_provider_route_diagnostics() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": client.build_route_diagnostics(),
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


@router.post("/provider/task-api-key")
def save_provider_task_api_key(request: ProviderTaskApiKeyRequest) -> dict:
    api_key = request.api_key.strip()
    save_route_api_key(request.api_key_ref, api_key)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "apiKeyRef": request.api_key_ref,
            "configured": bool(api_key),
            "authSource": client.get_route_auth_source(request.api_key_ref),
        },
    }


@router.post("/provider/base-url")
def save_provider_url(request: ProviderBaseUrlRequest) -> dict:
    save_provider_base_url(
        request.base_url,
        provider_name=request.provider_name,
    )
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "providerName": client.settings.provider_name,
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


@router.delete("/provider/task-api-key/{api_key_ref}")
def delete_provider_task_api_key(api_key_ref: str) -> dict:
    clear_route_api_key(api_key_ref)
    client = ProviderClient()
    return {
        "success": True,
        "message": "cleared",
        "data": {
            "apiKeyRef": api_key_ref,
            "configured": bool(client.get_api_key(api_key_ref)) if api_key_ref == "default" else False,
            "authSource": client.get_route_auth_source(api_key_ref),
        },
    }
