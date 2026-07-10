from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import save_provider_base_url
from app.core.errors import AdapterError
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    get_last_provider_debug,
    normalize_task_api_key_ref,
    save_local_api_key,
)
from app.services.workflow_profiles import WorkflowProfileError, WorkflowProfileStore

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


class WorkflowProfileCreateRequest(BaseModel):
    task_type: str = Field(alias="taskType")
    name: str
    api_key: str = Field(alias="apiKey")
    note: str = ""
    activate: bool = False


class WorkflowProfileUpdateRequest(BaseModel):
    name: str
    note: str = ""


class WorkflowProfileApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


def get_workflow_profile_store() -> WorkflowProfileStore:
    return WorkflowProfileStore()


def _raise_profile_error(exc: WorkflowProfileError) -> None:
    if exc.code == "WORKFLOW_PROFILE_NOT_FOUND":
        status_code = 404
    elif exc.code in {
        "WORKFLOW_PROFILE_ACTIVE",
        "WORKFLOW_PROFILE_LIMIT",
        "WORKFLOW_PROFILE_NAME_DUPLICATE",
    }:
        status_code = 409
    else:
        status_code = 400
    raise AdapterError(exc.code, exc.message, status_code=status_code)


def _task_key_status(task_type: str, profile_data: dict) -> dict:
    client_status = ProviderClient().build_task_api_key_status().get(task_type, {})
    active_id = str(profile_data.get("activeProfileId", ""))
    active_profile = next(
        (item for item in profile_data.get("profiles", []) if item.get("id") == active_id),
        {},
    )
    task_configured = bool(active_profile.get("keyConfigured"))
    result = dict(client_status)
    result.update(
        {
            "taskType": task_type,
            "taskKeyConfigured": task_configured,
            "configured": task_configured or bool(client_status.get("configured")),
            "activeProfileId": active_id,
            "activeProfileName": str(active_profile.get("name", "")),
            "profileCount": int(profile_data.get("profileCount", 0)),
        }
    )
    return result


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


@router.get("/provider/workflow-profiles")
def get_workflow_profiles(task_type: str = Query(alias="taskType")) -> dict:
    try:
        data = get_workflow_profile_store().list_for_task(task_type)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "data": data}


@router.post("/provider/workflow-profiles")
def create_workflow_profile(request: WorkflowProfileCreateRequest) -> dict:
    try:
        profile = get_workflow_profile_store().create_profile(
            request.task_type,
            request.name,
            request.api_key,
            note=request.note,
            activate=request.activate,
        )
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "message": "saved", "data": {"profile": profile}}


@router.patch("/provider/workflow-profiles/{profile_id}")
def update_workflow_profile(profile_id: str, request: WorkflowProfileUpdateRequest) -> dict:
    try:
        profile = get_workflow_profile_store().update_profile(profile_id, request.name, request.note)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "message": "saved", "data": {"profile": profile}}


@router.post("/provider/workflow-profiles/{profile_id}/api-key")
def replace_workflow_profile_api_key(profile_id: str, request: WorkflowProfileApiKeyRequest) -> dict:
    try:
        profile = get_workflow_profile_store().replace_api_key(profile_id, request.api_key)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "message": "saved", "data": {"profile": profile}}


@router.post("/provider/workflow-profiles/{profile_id}/activate")
def activate_workflow_profile(profile_id: str) -> dict:
    try:
        data = get_workflow_profile_store().activate_profile(profile_id)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "message": "activated", "data": data}


@router.delete("/provider/workflow-profiles/{profile_id}")
def delete_workflow_profile(profile_id: str) -> dict:
    try:
        data = get_workflow_profile_store().delete_profile(profile_id)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {"success": True, "message": "deleted", "data": data}


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
    try:
        profile_data = get_workflow_profile_store().save_legacy_task_api_key(
            request.task_type,
            api_key_ref,
            request.api_key,
        )
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": _task_key_status(request.task_type, profile_data),
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
    try:
        profile_data = get_workflow_profile_store().clear_active_api_key(task_type)
    except WorkflowProfileError as exc:
        _raise_profile_error(exc)
    return {
        "success": True,
        "message": "cleared",
        "data": _task_key_status(task_type, profile_data),
    }
