from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional
import time

from app.core.config import save_provider_base_url
from app.core.errors import AdapterError
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    get_last_provider_debug,
    normalize_task_api_key_ref,
    save_local_api_key,
)
from app.services.long_task_coordinator import get_long_task_coordinator
from app.services.workflow_profiles import WorkflowProfileError
from app.services.model_configurations import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    ModelConfigurationError,
    ModelConfigurationStore,
    WorkflowProfileCompatibilityStore,
)
from app.services.system_prompts import SystemPromptError, SystemPromptStore

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


class ModelConfigurationCreateRequest(BaseModel):
    task_type: str = Field(alias="taskType")
    name: str
    access_method: str = Field(alias="accessMethod")
    note: str = ""
    service_base_url: str = Field(default="", alias="serviceBaseUrl")
    model_name: str = Field(default="", alias="modelName")
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = Field(default=None, alias="maxOutputTokens")
    context_window_tokens: int = Field(
        default=DEFAULT_CONTEXT_WINDOW_TOKENS, alias="contextWindowTokens"
    )


class ModelConfigurationUpdateRequest(BaseModel):
    name: str
    access_method: str = Field(alias="accessMethod")
    note: str = ""
    service_base_url: str = Field(default="", alias="serviceBaseUrl")
    model_name: str = Field(default="", alias="modelName")
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = Field(default=None, alias="maxOutputTokens")
    context_window_tokens: int = Field(
        default=DEFAULT_CONTEXT_WINDOW_TOKENS, alias="contextWindowTokens"
    )


class ModelConfigurationApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


class ModelConfigurationCopyRequest(BaseModel):
    target_task_type: Optional[str] = Field(default=None, alias="targetTaskType")
    name: str = ""


def get_workflow_profile_store() -> WorkflowProfileCompatibilityStore:
    return WorkflowProfileCompatibilityStore()


def get_model_configuration_store() -> ModelConfigurationStore:
    return ModelConfigurationStore()


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


def _raise_model_configuration_error(exc: ModelConfigurationError) -> None:
    if exc.code == "MODEL_CONFIG_NOT_FOUND":
        status_code = 404
    elif exc.code in {
        "MODEL_CONFIG_ACTIVE",
        "MODEL_CONFIG_LIMIT",
        "MODEL_CONFIG_NAME_DUPLICATE",
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
    data = client.build_route_diagnostics()
    data["longTaskCoordinator"] = get_long_task_coordinator().diagnostics()
    return {
        "success": True,
        "data": data,
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


@router.get("/provider/model-configurations")
def get_model_configurations(task_type: str = Query(alias="taskType")) -> dict:
    try:
        data = get_model_configuration_store().list_for_task(task_type)
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {"success": True, "data": data}


@router.post("/provider/model-configurations")
def create_model_configuration(request: ModelConfigurationCreateRequest) -> dict:
    try:
        configuration = get_model_configuration_store().create_configuration(
            request.task_type,
            request.name,
            request.access_method,
            note=request.note,
            service_base_url=request.service_base_url,
            model_name=request.model_name,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            context_window_tokens=request.context_window_tokens,
        )
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": {"configuration": configuration},
    }


@router.patch("/provider/model-configurations/{configuration_id}")
def update_model_configuration(
    configuration_id: str, request: ModelConfigurationUpdateRequest
) -> dict:
    try:
        configuration = get_model_configuration_store().update_configuration(
            configuration_id,
            name=request.name,
            access_method=request.access_method,
            note=request.note,
            service_base_url=request.service_base_url,
            model_name=request.model_name,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            context_window_tokens=request.context_window_tokens,
        )
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": {"configuration": configuration},
    }


@router.post("/provider/model-configurations/{configuration_id}/api-key")
def replace_model_configuration_api_key(
    configuration_id: str, request: ModelConfigurationApiKeyRequest
) -> dict:
    try:
        configuration = get_model_configuration_store().replace_api_key(
            configuration_id, request.api_key
        )
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": {"configuration": configuration},
    }


@router.post("/provider/model-configurations/{configuration_id}/copy")
def copy_model_configuration(
    configuration_id: str, request: ModelConfigurationCopyRequest
) -> dict:
    try:
        configuration = get_model_configuration_store().copy_configuration(
            configuration_id,
            target_task_type=request.target_task_type,
            name=request.name,
        )
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {
        "success": True,
        "message": "copied",
        "data": {"configuration": configuration},
    }


@router.post("/provider/model-configurations/{configuration_id}/activate")
def activate_model_configuration(configuration_id: str) -> dict:
    try:
        data = get_model_configuration_store().activate_configuration(configuration_id)
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {"success": True, "message": "activated", "data": data}


@router.post("/provider/model-configurations/{configuration_id}/validate")
def validate_model_configuration(configuration_id: str) -> dict:
    store = get_model_configuration_store()
    client = ProviderClient(model_configuration_store=store)
    trace_id = "model-config-validation-{0}".format(int(time.time() * 1000))
    started = time.monotonic()
    try:
        result = client.validate_model_configuration(configuration_id, trace_id)
    except AdapterError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            store.record_validation(
                configuration_id,
                {
                    "success": False,
                    "durationMs": duration_ms,
                    "errorCode": exc.code,
                    "message": exc.message,
                },
            )
        except ModelConfigurationError:
            pass
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    configuration = store.record_validation(
        configuration_id,
        {
            "success": True,
            "durationMs": duration_ms,
            "message": "验证调用成功。",
            "promptVersion": result.get("promptVersion", ""),
        },
    )
    return {
        "success": True,
        "message": "validated",
        "data": {**result, "durationMs": duration_ms, "configuration": configuration},
    }


@router.get("/provider/model-configurations/{configuration_id}/system-prompt")
def get_model_configuration_system_prompt(configuration_id: str) -> dict:
    try:
        configuration = get_model_configuration_store().get_configuration(configuration_id)
        prompt = SystemPromptStore().load(configuration["taskType"])
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    except SystemPromptError as exc:
        raise AdapterError(exc.code, exc.message, status_code=500)
    return {
        "success": True,
        "data": {
            "taskType": configuration["taskType"],
            "version": prompt["version"],
            "sha256": prompt["sha256"],
            "content": prompt["content"],
        },
    }


@router.delete("/provider/model-configurations/{configuration_id}")
def delete_model_configuration(
    configuration_id: str, deactivate: bool = False
) -> dict:
    try:
        data = get_model_configuration_store().delete_configuration(
            configuration_id, deactivate=deactivate
        )
    except ModelConfigurationError as exc:
        _raise_model_configuration_error(exc)
    return {"success": True, "message": "deleted", "data": data}


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
