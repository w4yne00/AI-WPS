from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import save_provider_base_url, save_task_api_key_ref
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    clear_route_api_key,
    get_last_provider_debug,
    normalize_task_api_key_ref,
    save_route_api_key,
    save_local_api_key,
)

router = APIRouter()


class ProviderApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


class ProviderBaseUrlRequest(BaseModel):
    base_url: str = Field(alias="baseUrl")
    provider_name: Optional[str] = Field(default=None, alias="providerName")


class ProviderTaskApiKeyRequest(BaseModel):
    task_type: str = Field(alias="taskType")
    api_key: str = Field(alias="apiKey")
    api_key_ref: Optional[str] = Field(default=None, alias="apiKeyRef")


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


@router.get("/provider/task-api-keys")
def get_provider_task_api_keys() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": client.build_task_api_key_status(),
    }


@router.get("/provider/debug-last")
def get_provider_debug_last() -> dict:
    return {
        "success": True,
        "data": get_last_provider_debug(),
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
    api_key_ref = (request.api_key_ref or normalize_task_api_key_ref(request.task_type)).strip()
    save_task_api_key_ref(request.task_type, api_key_ref)
    save_route_api_key(api_key_ref, request.api_key)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": client.build_task_api_key_status().get(request.task_type, {}),
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


@router.delete("/provider/task-api-key/{task_type}")
def delete_provider_task_api_key(task_type: str) -> dict:
    client = ProviderClient()
    api_key_ref = client.get_task_api_key_ref(task_type)
    clear_route_api_key(api_key_ref)
    return {
        "success": True,
        "message": "cleared",
        "data": ProviderClient().build_task_api_key_status().get(task_type, {}),
    }
