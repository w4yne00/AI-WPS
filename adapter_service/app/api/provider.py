from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional
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
from app.services.direct_services import (
    DirectServiceError,
    DirectServiceStore,
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
    context_window_tokens: Optional[int] = Field(
        default=None, alias="contextWindowTokens"
    )
    image_input_mode: Optional[str] = Field(default=None, alias="imageInputMode")


class ModelConfigurationUpdateRequest(BaseModel):
    name: str
    access_method: str = Field(alias="accessMethod")
    note: str = ""
    service_base_url: str = Field(default="", alias="serviceBaseUrl")
    model_name: str = Field(default="", alias="modelName")
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = Field(default=None, alias="maxOutputTokens")
    context_window_tokens: Optional[int] = Field(
        default=None, alias="contextWindowTokens"
    )
    image_input_mode: Optional[str] = Field(default=None, alias="imageInputMode")


class ModelConfigurationApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


class ModelConfigurationImageAuthorizationRequest(BaseModel):
    authorized: bool


class ModelConfigurationCopyRequest(BaseModel):
    target_task_type: Optional[str] = Field(default=None, alias="targetTaskType")
    name: str = ""


class DirectServiceCreateRequest(BaseModel):
    name: str
    service_base_url: str = Field(default="", alias="serviceBaseUrl")
    default_model: str = Field(default="", alias="defaultModel")
    api_key: Optional[str] = Field(default=None, alias="apiKey")


class DirectServiceUpdateRequest(BaseModel):
    name: str
    expected_revision: int = Field(alias="expectedRevision")
    service_base_url: str = Field(default="", alias="serviceBaseUrl")
    default_model: str = Field(default="", alias="defaultModel")


class DirectServiceApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")
    expected_revision: int = Field(alias="expectedRevision")


class DirectServiceClearApiKeyRequest(BaseModel):
    expected_revision: int = Field(alias="expectedRevision")


class DirectServiceModelListUpdateRequest(BaseModel):
    model_list: List[str] = Field(alias="modelList")
    expected_revision: int = Field(alias="expectedRevision")
    fetched_at: Optional[str] = Field(default=None, alias="fetchedAt")


class TaskModelSelectionUpdateRequest(BaseModel):
    service_id: str = Field(default="", alias="serviceId")
    model_name: str = Field(default="", alias="modelName")
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = Field(default=None, alias="maxOutputTokens")
    context_window_tokens: Optional[int] = Field(
        default=None, alias="contextWindowTokens"
    )
    image_input_mode: Optional[str] = Field(default=None, alias="imageInputMode")
    custom_model: bool = Field(default=False, alias="customModel")
    custom_model_validated: bool = Field(
        default=False, alias="customModelValidated"
    )


class DirectServiceRefreshRequest(BaseModel):
    expected_revision: int = Field(alias="expectedRevision")


class DirectServiceValidateRequest(BaseModel):
    expected_revision: int = Field(alias="expectedRevision")


class DirectServiceActivateRequest(BaseModel):
    task_type: str = Field(..., alias="taskType")


class TaskModelSelectionValidateRequest(BaseModel):
    service_id: Optional[str] = Field(default=None, alias="serviceId")
    model_name: Optional[str] = Field(default=None, alias="modelName")
    custom_model: Optional[bool] = Field(default=False, alias="customModel")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(
        default=None, ge=1, le=16384, alias="maxOutputTokens"
    )
    context_window_tokens: Optional[int] = Field(
        default=None, ge=1, le=2000000, alias="contextWindowTokens"
    )
    image_input_mode: Optional[str] = Field(
        default="disabled", alias="imageInputMode"
    )


def get_workflow_profile_store() -> WorkflowProfileCompatibilityStore:
    return WorkflowProfileCompatibilityStore()


def get_model_configuration_store() -> ModelConfigurationStore:
    return ModelConfigurationStore()


def get_direct_service_store() -> DirectServiceStore:
    return DirectServiceStore()


def _raise_direct_service_error(exc: DirectServiceError) -> None:
    if exc.code == "DIRECT_SERVICE_NOT_FOUND":
        status_code = 404
    elif exc.code in {
        "DIRECT_SERVICE_LIMIT",
        "DIRECT_SERVICE_NAME_DUPLICATE",
        "DIRECT_SERVICE_REVISION_CONFLICT",
        "DIRECT_SERVICE_CONFIG_CHANGED",
        "DIRECT_SERVICE_IN_USE",
    }:
        status_code = 409
    else:
        status_code = 400
    raise AdapterError(
        exc.code,
        exc.message,
        status_code=status_code,
        referenced_tasks=exc.referenced_tasks,
    )


def _refresh_direct_service_after_mutation(
    store: DirectServiceStore, service: dict
) -> tuple:
    result = store.refresh_models_best_effort(
        service["id"], expected_revision=service.get("revision")
    )
    return result["directService"], result["modelCatalogRefresh"]


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
            image_input_mode=request.image_input_mode,
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
            image_input_mode=request.image_input_mode,
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


@router.post("/provider/model-configurations/{configuration_id}/image-authorization")
def set_model_configuration_image_authorization(
    configuration_id: str, request: ModelConfigurationImageAuthorizationRequest
) -> dict:
    try:
        configuration = get_model_configuration_store().set_image_external_authorization(
            configuration_id, request.authorized
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
            current = store.get_configuration(configuration_id)
            if current.get("taskType") == "word.format_review":
                store.record_format_semantic_validation(
                    configuration_id,
                    {
                        "success": False,
                        "protocolVersion": "format_semantics.v1",
                        "durationMs": duration_ms,
                        "errorCode": exc.code,
                        "message": "格式语义协议验证失败，格式审查仅运行确定性规则。",
                    },
                )
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
    if isinstance(result.get("formatSemanticValidation"), dict):
        store.record_format_semantic_validation(
            configuration_id,
            {
                **result["formatSemanticValidation"],
            },
        )
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


@router.get("/provider/direct-services")
def get_direct_services() -> dict:
    try:
        data = get_direct_service_store().list_services()
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {"success": True, "data": data}


@router.post("/provider/direct-services")
def create_direct_service(request: DirectServiceCreateRequest) -> dict:
    store = get_direct_service_store()
    try:
        service = store.create_service(
            request.name,
            service_base_url=request.service_base_url,
            default_model=request.default_model,
            api_key=request.api_key,
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    service, catalog_refresh = _refresh_direct_service_after_mutation(store, service)
    return {
        "success": True,
        "message": "saved",
        "data": {
            "directService": service,
            "modelCatalogRefresh": catalog_refresh,
        },
    }


@router.get("/provider/direct-services/{service_id}")
def get_direct_service(service_id: str) -> dict:
    try:
        service = get_direct_service_store().get_service(service_id)
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {"success": True, "data": {"directService": service}}


@router.patch("/provider/direct-services/{service_id}")
def update_direct_service(
    service_id: str, request: DirectServiceUpdateRequest
) -> dict:
    store = get_direct_service_store()
    try:
        service = store.update_service(
            service_id,
            name=request.name,
            expected_revision=request.expected_revision,
            service_base_url=request.service_base_url,
            default_model=request.default_model,
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    service, catalog_refresh = _refresh_direct_service_after_mutation(store, service)
    return {
        "success": True,
        "message": "saved",
        "data": {
            "directService": service,
            "modelCatalogRefresh": catalog_refresh,
        },
    }


@router.delete("/provider/direct-services/{service_id}")
def delete_direct_service(
    service_id: str,
    expected_revision: int = Query(..., alias="expectedRevision"),
) -> dict:
    try:
        data = get_direct_service_store().delete_service(
            service_id, expected_revision=expected_revision
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "deleted",
        "data": data,
    }


@router.post("/provider/direct-services/{service_id}/api-key")
def replace_direct_service_api_key(
    service_id: str, request: DirectServiceApiKeyRequest
) -> dict:
    store = get_direct_service_store()
    try:
        service = store.replace_api_key(
            service_id,
            request.api_key,
            expected_revision=request.expected_revision,
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    service, catalog_refresh = _refresh_direct_service_after_mutation(store, service)
    return {
        "success": True,
        "message": "saved",
        "data": {
            "directService": service,
            "modelCatalogRefresh": catalog_refresh,
        },
    }


@router.delete("/provider/direct-services/{service_id}/api-key")
def clear_direct_service_api_key(
    service_id: str,
    expected_revision: int = Query(..., alias="expectedRevision"),
) -> dict:
    try:
        service = get_direct_service_store().clear_api_key(
            service_id, expected_revision=expected_revision
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "cleared",
        "data": {"directService": service},
    }


@router.post("/provider/direct-services/{service_id}/models")
def update_direct_service_models(
    service_id: str, request: DirectServiceModelListUpdateRequest
) -> dict:
    try:
        service = get_direct_service_store().update_model_list(
            service_id,
            request.model_list,
            expected_revision=request.expected_revision,
            trusted=False,
            source="client",
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": {"directService": service},
    }


@router.get("/provider/task-model-selections")
def get_task_model_selections(
    host: Optional[str] = None,
    task_type: Optional[str] = Query(default=None, alias="taskType"),
) -> dict:
    # Direct Python callers do not receive FastAPI's injected default value.
    # Normalize that Query object before passing the value to the store.
    if not isinstance(task_type, str):
        task_type = None
    try:
        data = get_direct_service_store().list_task_model_selections(
            host=host, task_type=task_type
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {"success": True, "data": data}


@router.get("/provider/task-model-selections/{task_type}")
def get_task_model_selection(task_type: str) -> dict:
    try:
        data = get_direct_service_store().get_task_model_selection(task_type)
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {"success": True, "data": {"taskModelSelection": data}}


@router.put("/provider/task-model-selections/{task_type}")
def update_task_model_selection_route(
    task_type: str, request: TaskModelSelectionUpdateRequest
) -> dict:
    try:
        selection = get_direct_service_store().update_task_model_selection(
            task_type,
            service_id=request.service_id,
            model_name=request.model_name,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            context_window_tokens=request.context_window_tokens,
            image_input_mode=request.image_input_mode,
            custom_model=request.custom_model,
            custom_model_validated=request.custom_model_validated,
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "saved",
        "data": {"taskModelSelection": selection},
    }


@router.post("/provider/direct-services/{service_id}/refresh-models")
def refresh_direct_service_models(
    service_id: str, request: DirectServiceRefreshRequest
) -> dict:
    try:
        service = get_direct_service_store().refresh_models(
            service_id, expected_revision=request.expected_revision
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "refreshed",
        "data": {
            "directService": service,
            "models": service.get("modelList", []),
            "revision": service.get("revision", 1),
        },
    }


@router.post("/provider/direct-services/{service_id}/validate")
def validate_direct_service_route(
    service_id: str, request: DirectServiceValidateRequest
) -> dict:
    try:
        result = get_direct_service_store().validate_service(
            service_id, expected_revision=request.expected_revision
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "validated",
        "data": result,
    }


@router.post("/provider/direct-services/{service_id}/activate")
def activate_direct_service_route(
    service_id: str, request: DirectServiceActivateRequest
) -> dict:
    try:
        result = get_direct_service_store().activate_direct_service(
            service_id, request.task_type
        )
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    return {
        "success": True,
        "message": "activated",
        "data": result,
    }


@router.post("/provider/task-model-selections/{task_type}/validate")
def validate_task_model_selection_route(
    task_type: str, request: Optional[TaskModelSelectionValidateRequest] = None
) -> dict:
    store = get_direct_service_store()
    model_store = get_model_configuration_store()
    client = ProviderClient(
        model_configuration_store=model_store, direct_service_store=store
    )
    trace_id = "task-model-selection-validation-{0}".format(int(time.time() * 1000))
    started = time.monotonic()
    payload = request.dict(by_alias=True, exclude_unset=True) if request else {}
    try:
        result = client.validate_task_model_selection(task_type, payload, trace_id)
    except DirectServiceError as exc:
        _raise_direct_service_error(exc)
    except AdapterError:
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    result["durationMs"] = duration_ms
    return {
        "success": True,
        "message": "validated",
        "data": result,
    }
