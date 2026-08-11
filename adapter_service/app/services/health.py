import json
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.config import default_config_path
from app.core.runtime_paths import resolve_runtime_paths
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS
from app.services.writing_policy import get_writing_policy_service


SERVICE_NAME = "wps-ai-adapter"
SERVICE_VERSION = "0.23.1-alpha"
SERVICE_MODE = "uvicorn"
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _CoreHealthError(ValueError):
    pass


def _subsystem(
    status: str,
    error_code: str = "",
    stage: str = "",
    allowed_actions=(),
) -> dict:
    return {
        "status": status,
        "errorCode": error_code,
        "stage": stage,
        "allowedActions": list(allowed_actions),
    }


def _ready_subsystem() -> dict:
    return _subsystem("ready", allowed_actions=("read", "write"))


def _recovery_subsystem(error_code: str, stage: str) -> dict:
    return _subsystem(
        "recovery",
        error_code=error_code,
        stage=stage,
        allowed_actions=("retry", "create_backup", "export_diagnostics"),
    )


def _degraded_writing_policy_subsystem(error_code: str) -> dict:
    return _subsystem(
        "degraded",
        error_code=error_code,
        stage="load_writing_policies",
        allowed_actions=("retry", "read_only", "run_core_tasks"),
    )


def _read_config_payload() -> dict:
    path = Path(default_config_path())
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise _CoreHealthError("configuration root must be an object")
    return payload


def _require_mapping(payload: dict, field: str) -> dict:
    value = payload.get(field, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _CoreHealthError("{0} must be an object".format(field))
    return value


def _validate_ref(value: object) -> str:
    ref = str(value or "").strip()
    if not ref or not _SAFE_REF.fullmatch(ref):
        raise _CoreHealthError("unsafe reference")
    return ref


def _validate_model_configuration_data(payload: dict) -> None:
    configurations = _require_mapping(payload, "modelConfigurations")
    normalized = {}
    for configuration_id, item in configurations.items():
        if not isinstance(item, dict):
            raise _CoreHealthError("model configuration must be an object")
        item_id = str(item.get("id", configuration_id)).strip()
        task_type = str(item.get("taskType", "")).strip()
        if not item_id or task_type not in SUPPORTED_WORKFLOW_TASKS:
            raise _CoreHealthError("model configuration identity is invalid")
        if item.get("apiKeyRef") not in (None, ""):
            _validate_ref(item.get("apiKeyRef"))
        normalized[item_id] = task_type

    active = _require_mapping(payload, "activeModelConfigurations")
    for task_type, configuration_id in active.items():
        task = str(task_type).strip()
        target = str(configuration_id).strip()
        if task not in SUPPORTED_WORKFLOW_TASKS:
            raise _CoreHealthError("active model task is invalid")
        if normalized.get(target) != task:
            raise _CoreHealthError("active model reference is invalid")

    legacy = _require_mapping(payload, "workflowProfiles")
    legacy_ids = set()
    for profile_id, item in legacy.items():
        if not isinstance(item, dict):
            raise _CoreHealthError("workflow profile must be an object")
        item_id = str(item.get("id", profile_id)).strip()
        task_type = str(item.get("taskType", "")).strip()
        if not item_id or task_type not in SUPPORTED_WORKFLOW_TASKS:
            raise _CoreHealthError("workflow profile identity is invalid")
        _validate_ref(item.get("apiKeyRef"))
        legacy_ids.add((task_type, item_id))

    legacy_active = _require_mapping(payload, "activeWorkflowProfiles")
    for task_type, profile_id in legacy_active.items():
        task = str(task_type).strip()
        target = str(profile_id).strip()
        if (task, target) not in legacy_ids and normalized.get(target) != task:
            raise _CoreHealthError("active workflow profile reference is invalid")

    task_key_refs = _require_mapping(payload, "taskApiKeyRefs")
    for task_type, ref in task_key_refs.items():
        if str(task_type).strip() not in SUPPORTED_WORKFLOW_TASKS:
            raise _CoreHealthError("task key task is invalid")
        _validate_ref(ref)


def _validate_task_route_data(payload: dict) -> None:
    routes = _require_mapping(payload, "taskRoutes")
    for task_type, item in routes.items():
        task = str(task_type).strip()
        if task not in SUPPORTED_WORKFLOW_TASKS or not isinstance(item, dict):
            raise _CoreHealthError("task route is invalid")
        api_key_ref = item.get("apiKeyRef")
        if api_key_ref not in (None, ""):
            _validate_ref(api_key_ref)
        path = str(item.get("path", ""))
        if _CONTROL_CHAR_RE.search(path):
            raise _CoreHealthError("task route path is invalid")


def _core_subsystems() -> Tuple[dict, dict, dict]:
    try:
        payload = _read_config_payload()
    except Exception:
        return (
            _recovery_subsystem(
                "MODEL_CONFIGURATION_DATA_UNAVAILABLE",
                "load_model_configurations",
            ),
            _recovery_subsystem("TASK_ROUTE_DATA_UNAVAILABLE", "load_task_routes"),
            {},
        )

    try:
        _validate_model_configuration_data(payload)
        model_status = _ready_subsystem()
    except Exception:
        model_status = _recovery_subsystem(
            "MODEL_CONFIGURATION_DATA_INVALID",
            "validate_model_configurations",
        )

    try:
        _validate_task_route_data(payload)
        route_status = _ready_subsystem()
    except Exception:
        route_status = _recovery_subsystem(
            "TASK_ROUTE_DATA_INVALID",
            "validate_task_routes",
        )
    return model_status, route_status, payload


def _writing_policy_subsystem() -> dict:
    store = None
    try:
        service = get_writing_policy_service()
        store = service.store
        summary = store.summary()
        if not isinstance(summary, dict) or summary.get("status") != "ready":
            raise RuntimeError("writing policy summary is not ready")
        return _ready_subsystem()
    except Exception:
        raw_code = str(getattr(store, "error_code", "") or "").strip()
        if not _SAFE_REF.fullmatch(raw_code):
            raw_code = "writing_policy_unavailable"
        return _degraded_writing_policy_subsystem(raw_code.upper())


def _provider_metadata(payload: dict) -> dict:
    routes = payload.get("taskRoutes", {})
    if not isinstance(routes, dict):
        routes = {}
    provider_base_url = str(
        payload.get("providerBaseUrl", payload.get("difyBaseUrl", "")) or ""
    ).strip()
    configurations = payload.get("modelConfigurations", {})
    active = payload.get("activeModelConfigurations", {})
    if not isinstance(configurations, dict):
        configurations = {}
    if not isinstance(active, dict):
        active = {}
    try:
        runtime_paths = resolve_runtime_paths()
        key_dir = runtime_paths.api_key_dir
        local_key_path = runtime_paths.local_api_key_path
    except Exception:
        key_dir = None
        local_key_path = None

    def key_is_configured(ref: object) -> bool:
        value = str(ref or "").strip()
        if key_dir is None or not _SAFE_REF.fullmatch(value):
            return False
        try:
            return bool((key_dir / value).read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            return False

    task_labels = {
        "word.smart_write": "智能编写",
        "word.smart_imitation": "智能仿写",
        "word.document_review": "文档审查",
        "word.format_review": "格式审查",
        "excel.analysis": "智能分析",
        "excel.formula_assistant": "公式助手",
        "ppt.slide_assistant": "智能总结",
        "ppt.structure_review": "结构审查",
    }
    task_api_keys = {}
    for task_type, label in task_labels.items():
        configuration_id = str(active.get(task_type, ""))
        configuration = configurations.get(configuration_id, {})
        if not isinstance(configuration, dict):
            configuration = {}
        key_ref = str(configuration.get("apiKeyRef", ""))
        key_configured = key_is_configured(key_ref)
        access_method = str(configuration.get("accessMethod", "workflow_platform"))
        complete = bool(
            configuration
            and str(configuration.get("serviceBaseUrl", "")).strip()
            and key_configured
            and (
                access_method != "direct_model"
                or str(configuration.get("modelName", "")).strip()
            )
        )
        task_api_keys[task_type] = {
            "label": label,
            "apiKeyRef": key_ref,
            "taskKeyConfigured": key_configured,
            "configured": complete,
            "authSource": "task-file" if key_configured else "none",
        }

    provider_configured = any(
        item["configured"] for item in task_api_keys.values()
    )
    provider_auth_source = "task-file" if provider_configured else "none"
    if not configurations:
        provider_key_env = str(
            payload.get("providerApiKeyEnv", payload.get("difyApiKeyEnv", "ENTERPRISE_AI_API_KEY"))
        )
        env_configured = bool(provider_key_env and os.getenv(provider_key_env))
        file_configured = False
        if local_key_path is not None:
            try:
                file_configured = bool(
                    local_key_path.read_text(encoding="utf-8").strip()
                )
            except (OSError, UnicodeError):
                file_configured = False
        provider_configured = bool(
            provider_base_url and (env_configured or file_configured)
        )
        provider_auth_source = (
            "env" if env_configured else ("file" if file_configured else "none")
        )
    return {
        "providerName": str(payload.get("providerName", "企业大模型接口")),
        "providerType": str(payload.get("providerType", "enterprise-dify-chat")),
        "providerBaseUrlConfigured": bool(provider_base_url),
        "providerConfigured": provider_configured,
        "providerAuthSource": provider_auth_source,
        "taskApiKeys": task_api_keys,
        "taskRouteCount": len(routes),
        "taskRouteConfiguredCount": sum(
            1 for item in routes.values() if isinstance(item, dict) and item.get("enabled", True)
        ),
    }


def get_health_snapshot() -> dict:
    model_status, route_status, payload = _core_subsystems()
    writing_policy_status = _writing_policy_subsystem()
    recovery = (
        model_status["status"] == "recovery"
        or route_status["status"] == "recovery"
    )
    status = (
        "recovery"
        if recovery
        else (
            "degraded"
            if writing_policy_status["status"] == "degraded"
            else "ready"
        )
    )
    return {
        "service": SERVICE_NAME,
        "status": status,
        "version": SERVICE_VERSION,
        "mode": SERVICE_MODE,
        **_provider_metadata(payload),
        "subsystems": {
            "modelConfigurations": model_status,
            "taskRoutes": route_status,
            "writingPolicies": writing_policy_status,
        },
        "operationPolicy": {
            "configurationMutationsAllowed": not recovery,
            "modelTasksAllowed": not recovery,
            "writingPolicyMutationsAllowed": (
                not recovery and writing_policy_status["status"] == "ready"
            ),
        },
    }


def _is_core_guarded_operation(method: str, path: str) -> bool:
    if method in _MUTATING_METHODS and path.startswith("/provider/"):
        return True
    if method == "POST" and path.startswith(("/word/", "/excel/", "/ppt/")):
        return True
    return False


def get_operation_block(method: str, path: str) -> Optional[Dict[str, str]]:
    normalized_method = str(method or "").upper()
    normalized_path = str(path or "")
    writing_policy_mutation = (
        normalized_method in _MUTATING_METHODS
        and normalized_path.startswith("/writing-policies/")
    )
    if not _is_core_guarded_operation(
        normalized_method, normalized_path
    ) and not writing_policy_mutation:
        return None

    model_status, route_status, unused_payload = _core_subsystems()
    del unused_payload
    if (
        model_status["status"] == "recovery"
        or route_status["status"] == "recovery"
    ):
        return {
            "code": "ADAPTER_RECOVERY_MODE",
            "message": "Adapter 已连接但处于恢复模式，当前操作已被安全阻止。",
        }

    if writing_policy_mutation:
        writing_policy_status = _writing_policy_subsystem()
        if writing_policy_status["status"] != "ready":
            return {
                "code": "WRITING_POLICY_READ_ONLY",
                "message": "写作规范增强能力当前处于降级状态，仅允许只读查看。",
            }
    return None
