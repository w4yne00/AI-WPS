import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from app.core.config import default_config_path, load_config_payload, save_config_payload
from app.core.runtime_paths import resolve_runtime_paths
from app.services.workflow_profiles import (
    MAX_PROFILES_PER_TASK,
    SUPPORTED_WORKFLOW_TASKS,
    WorkflowProfileError,
)


ACCESS_WORKFLOW_PLATFORM = "workflow_platform"
ACCESS_DIRECT_MODEL = "direct_model"
SUPPORTED_ACCESS_METHODS = (ACCESS_WORKFLOW_PLATFORM, ACCESS_DIRECT_MODEL)
DEFAULT_CONTEXT_WINDOW_TOKENS = 40000
DEFAULT_RESERVED_OUTPUT_TOKENS = 8000
MAX_CONFIGURATION_NAME_LENGTH = 40
MAX_CONFIGURATION_NOTE_LENGTH = 200
KNOWN_CALL_SUFFIXES = ("/chat-messages", "/files/upload", "/chat/completions")
_SAFE_KEY_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_STORE_LOCK = threading.RLock()


class ModelConfigurationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def host_for_task(task_type: str) -> str:
    prefix = str(task_type).split(".", 1)[0]
    if prefix not in {"word", "excel", "ppt"}:
        raise ModelConfigurationError("MODEL_CONFIG_TASK_UNSUPPORTED", "不支持的任务类型。")
    return prefix


def normalize_service_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if _CONTROL_CHAR_RE.search(raw):
        raise ModelConfigurationError("MODEL_CONFIG_URL_INVALID", "服务地址包含无效字符。")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ModelConfigurationError("MODEL_CONFIG_URL_INVALID", "服务地址格式无效。") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ModelConfigurationError(
            "MODEL_CONFIG_URL_INVALID", "服务地址必须是有效的 http 或 https 地址。"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ModelConfigurationError(
            "MODEL_CONFIG_URL_INVALID", "服务地址不能包含账号、密码、查询参数或片段。"
        )
    path = (parts.path or "").rstrip("/")
    lowered = path.lower()
    for suffix in KNOWN_CALL_SUFFIXES:
        if lowered.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


class ModelConfigurationStore:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        key_dir: Optional[Path] = None,
    ) -> None:
        self.config_path = (
            Path(config_path) if config_path is not None else default_config_path()
        )
        self.key_dir = (
            Path(key_dir)
            if key_dir is not None
            else resolve_runtime_paths().api_key_dir
        )

    def list_for_task(self, task_type: str) -> dict:
        task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = [
                self._sanitize(item)
                for item in self._configuration_map(payload).values()
                if item.get("taskType") == task
            ]
            configurations.sort(key=lambda item: (item.get("createdAt", ""), item["id"]))
            active_id = str(self._active_map(payload).get(task, ""))
            if not any(item["id"] == active_id and item["complete"] for item in configurations):
                active_id = ""
            return {
                "host": host_for_task(task),
                "taskType": task,
                "activeConfigurationId": active_id,
                "configurationCount": len(configurations),
                "configurations": configurations,
            }

    def create_configuration(
        self,
        task_type: str,
        name: str,
        access_method: str,
        note: str = "",
        service_base_url: str = "",
        model_name: str = "",
        temperature=None,
        max_output_tokens=None,
        context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
    ) -> dict:
        task = self._validate_task_type(task_type)
        clean = self._validated_fields(
            name=name,
            note=note,
            access_method=access_method,
            service_base_url=service_base_url,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            context_window_tokens=context_window_tokens,
        )
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            same_task = [item for item in configurations.values() if item.get("taskType") == task]
            if len(same_task) >= MAX_PROFILES_PER_TASK:
                raise ModelConfigurationError(
                    "MODEL_CONFIG_LIMIT",
                    "每个功能最多保存 {0} 个模型配置。".format(MAX_PROFILES_PER_TASK),
                )
            self._ensure_unique_name(same_task, clean["name"])
            token = uuid.uuid4().hex
            now = _utc_now()
            configuration = {
                "id": "config_{0}".format(token),
                "host": host_for_task(task),
                "taskType": task,
                "apiKeyRef": "model_{0}".format(token),
                "configVersion": 1,
                "createdAt": now,
                "updatedAt": now,
                **clean,
            }
            configurations[configuration["id"]] = configuration
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            return self._sanitize(configuration)

    def update_configuration(self, configuration_id: str, **fields) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            merged = {
                "name": fields.get("name", configuration.get("name", "")),
                "note": fields.get("note", configuration.get("note", "")),
                "access_method": fields.get("access_method", configuration.get("accessMethod", "")),
                "service_base_url": fields.get("service_base_url", configuration.get("serviceBaseUrl", "")),
                "model_name": fields.get("model_name", configuration.get("modelName", "")),
                "temperature": fields.get("temperature", configuration.get("temperature")),
                "max_output_tokens": fields.get(
                    "max_output_tokens", configuration.get("maxOutputTokens")
                ),
                "context_window_tokens": fields.get(
                    "context_window_tokens",
                    configuration.get("contextWindowTokens", DEFAULT_CONTEXT_WINDOW_TOKENS),
                ),
            }
            clean = self._validated_fields(**merged)
            same_task = [
                item
                for item in configurations.values()
                if item.get("taskType") == configuration["taskType"]
                and item.get("id") != configuration["id"]
            ]
            self._ensure_unique_name(same_task, clean["name"])
            old_method = configuration.get("accessMethod")
            old_ref = ""
            if old_method and old_method != clean["accessMethod"]:
                old_ref = str(configuration.get("apiKeyRef", ""))
                configuration["apiKeyRef"] = "model_{0}".format(uuid.uuid4().hex)
                if clean["accessMethod"] == ACCESS_WORKFLOW_PLATFORM:
                    clean["modelName"] = ""
                    clean["temperature"] = None
                    clean["maxOutputTokens"] = None
                else:
                    clean["modelName"] = ""
            configuration.update(clean)
            self._touch(configuration)
            configurations[configuration["id"]] = configuration
            payload["modelConfigurations"] = configurations
            self._deactivate_if_incomplete(payload, configuration)
            save_config_payload(payload, self.config_path)
            if old_ref:
                self._delete_key(old_ref)
            return self._sanitize(configuration)

    def replace_api_key(self, configuration_id: str, api_key: str) -> dict:
        clean_key = self._validate_api_key(api_key)
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            self._write_key(configuration["apiKeyRef"], clean_key)
            self._touch(configuration)
            configurations[configuration["id"]] = configuration
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            return self._sanitize(configuration)

    def clear_api_key(self, configuration_id: str) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            self._touch(configuration)
            configurations[configuration["id"]] = configuration
            payload["modelConfigurations"] = configurations
            active = self._active_map(payload)
            if active.get(configuration["taskType"]) == configuration["id"]:
                active.pop(configuration["taskType"], None)
                payload["activeModelConfigurations"] = active
            save_config_payload(payload, self.config_path)
            self._delete_key(str(configuration.get("apiKeyRef", "")))
            return self._sanitize(configuration)

    def activate_configuration(self, configuration_id: str) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            sanitized = self._sanitize(configuration)
            if not sanitized["complete"]:
                raise ModelConfigurationError(
                    "MODEL_CONFIG_INCOMPLETE", "该模型配置尚不完整，不能启用。"
                )
            active = self._active_map(payload)
            active[configuration["taskType"]] = configuration["id"]
            payload["activeModelConfigurations"] = active
            save_config_payload(payload, self.config_path)
            return self.list_for_task(configuration["taskType"])

    def copy_configuration(
        self, source_id: str, target_task_type: Optional[str] = None, name: str = ""
    ) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            source = self._require_configuration(configurations, source_id)
            target_task = self._validate_task_type(target_task_type or source["taskType"])
            if host_for_task(target_task) != source.get("host", host_for_task(source["taskType"])):
                raise ModelConfigurationError(
                    "MODEL_CONFIG_COPY_HOST_MISMATCH", "只能复制当前宿主内的模型配置。"
                )
            same_task = [item for item in configurations.values() if item.get("taskType") == target_task]
            if len(same_task) >= MAX_PROFILES_PER_TASK:
                raise ModelConfigurationError("MODEL_CONFIG_LIMIT", "该功能的模型配置数量已达上限。")
            copy_name = self._copy_name(same_task, name or str(source.get("name", "")))
            token = uuid.uuid4().hex
            now = _utc_now()
            copied = {
                key: value
                for key, value in source.items()
                if key
                not in {
                    "id",
                    "taskType",
                    "host",
                    "apiKeyRef",
                    "createdAt",
                    "updatedAt",
                    "lastValidation",
                    "configVersion",
                }
            }
            copied.update(
                {
                    "id": "config_{0}".format(token),
                    "host": host_for_task(target_task),
                    "taskType": target_task,
                    "name": copy_name,
                    "apiKeyRef": "model_{0}".format(token),
                    "configVersion": 1,
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
            source_key = self._read_key(str(source.get("apiKeyRef", "")))
            if source_key:
                self._write_key(copied["apiKeyRef"], source_key)
            configurations[copied["id"]] = copied
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            return self._sanitize(copied)

    def delete_configuration(self, configuration_id: str, deactivate: bool = False) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            active = self._active_map(payload)
            if active.get(configuration["taskType"]) == configuration["id"]:
                if not deactivate:
                    raise ModelConfigurationError(
                        "MODEL_CONFIG_ACTIVE",
                        "当前模型配置不能直接删除，请先切换配置或明确停用后删除。",
                    )
                active.pop(configuration["taskType"], None)
                payload["activeModelConfigurations"] = active
            configurations.pop(configuration["id"], None)
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            self._delete_key(str(configuration.get("apiKeyRef", "")))
            return self.list_for_task(configuration["taskType"])

    def get_active_configuration(self, task_type: str, include_secret: bool = False) -> Optional[dict]:
        task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configuration_id = str(self._active_map(payload).get(task, ""))
            configuration = self._configuration_map(payload).get(configuration_id)
            if not isinstance(configuration, dict) or configuration.get("taskType") != task:
                return None
            result = self._sanitize(configuration)
            if not result["complete"]:
                return None
            if include_secret:
                result["apiKey"] = self._read_key(str(configuration.get("apiKeyRef", "")))
            return result

    def get_configuration(self, configuration_id: str, include_secret: bool = False) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configuration = self._require_configuration(
                self._configuration_map(payload), configuration_id
            )
            result = self._sanitize(configuration)
            if include_secret:
                result["apiKey"] = self._read_key(str(configuration.get("apiKeyRef", "")))
            return result

    def record_validation(self, configuration_id: str, summary: dict) -> dict:
        with _STORE_LOCK:
            payload = self._load_and_migrate()
            configurations = self._configuration_map(payload)
            configuration = self._require_configuration(configurations, configuration_id)
            configuration["lastValidation"] = {
                "success": bool(summary.get("success")),
                "completedAt": str(summary.get("completedAt") or _utc_now()),
                "durationMs": max(int(summary.get("durationMs") or 0), 0),
                "errorCode": str(summary.get("errorCode") or "")[:80],
                "message": str(summary.get("message") or "")[:200],
                "configVersion": int(configuration.get("configVersion") or 1),
                "promptVersion": str(summary.get("promptVersion") or ""),
            }
            configurations[configuration["id"]] = configuration
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            return self._sanitize(configuration)

    def _load_and_migrate(self) -> dict:
        payload = load_config_payload(self.config_path)
        configurations = self._configuration_map(payload)
        active = self._active_map(payload)
        changed = False
        legacy_profiles = payload.get("workflowProfiles", {})
        if isinstance(legacy_profiles, dict):
            for legacy_id, legacy in legacy_profiles.items():
                if not isinstance(legacy, dict):
                    continue
                task = str(legacy.get("taskType", "")).strip()
                if task not in SUPPORTED_WORKFLOW_TASKS:
                    continue
                profile_id = str(legacy.get("id", legacy_id)).strip()
                if not profile_id or profile_id in configurations:
                    continue
                api_key_ref = str(legacy.get("apiKeyRef", "")).strip()
                if not api_key_ref or not _SAFE_KEY_REF.fullmatch(api_key_ref):
                    continue
                now = _utc_now()
                configurations[profile_id] = {
                    "id": profile_id,
                    "host": host_for_task(task),
                    "taskType": task,
                    "name": str(legacy.get("name", "当前配置")).strip() or "当前配置",
                    "note": str(legacy.get("note", "")).strip(),
                    "accessMethod": ACCESS_WORKFLOW_PLATFORM,
                    "serviceBaseUrl": normalize_service_base_url(
                        str(payload.get("providerBaseUrl", ""))
                    ),
                    "modelName": "",
                    "temperature": None,
                    "maxOutputTokens": None,
                    "contextWindowTokens": DEFAULT_CONTEXT_WINDOW_TOKENS,
                    "apiKeyRef": api_key_ref,
                    "configVersion": 1,
                    "createdAt": str(legacy.get("createdAt", now)),
                    "updatedAt": str(legacy.get("updatedAt", now)),
                }
                changed = True
        legacy_active = payload.get("activeWorkflowProfiles", {})
        if isinstance(legacy_active, dict):
            for task, profile_id in legacy_active.items():
                if task not in active and str(profile_id) in configurations:
                    active[str(task)] = str(profile_id)
                    changed = True
        if changed or "modelConfigurations" not in payload:
            payload["modelConfigurations"] = configurations
            payload["activeModelConfigurations"] = active
            save_config_payload(payload, self.config_path)
        return payload

    def _sanitize(self, configuration: dict) -> dict:
        access_method = str(configuration.get("accessMethod", ACCESS_WORKFLOW_PLATFORM))
        service_base_url = str(configuration.get("serviceBaseUrl", ""))
        model_name = str(configuration.get("modelName", ""))
        key_configured = self._key_exists(str(configuration.get("apiKeyRef", "")))
        missing = []
        if not service_base_url:
            missing.append("serviceBaseUrl")
        if not key_configured:
            missing.append("apiKey")
        if access_method == ACCESS_DIRECT_MODEL and not model_name:
            missing.append("modelName")
        last_validation = configuration.get("lastValidation")
        if not isinstance(last_validation, dict):
            last_validation = None
        elif int(last_validation.get("configVersion") or 0) != int(
            configuration.get("configVersion") or 1
        ):
            last_validation = {**last_validation, "stale": True}
        else:
            last_validation = {**last_validation, "stale": False}
        return {
            "id": str(configuration.get("id", "")),
            "host": str(configuration.get("host", "")),
            "taskType": str(configuration.get("taskType", "")),
            "name": str(configuration.get("name", "")),
            "note": str(configuration.get("note", "")),
            "accessMethod": access_method,
            "serviceBaseUrl": service_base_url,
            "callPath": "/chat/completions"
            if access_method == ACCESS_DIRECT_MODEL
            else "/chat-messages",
            "modelName": model_name,
            "temperature": configuration.get("temperature"),
            "maxOutputTokens": configuration.get("maxOutputTokens"),
            "contextWindowTokens": int(
                configuration.get("contextWindowTokens") or DEFAULT_CONTEXT_WINDOW_TOKENS
            ),
            "apiKeyRef": str(configuration.get("apiKeyRef", "")),
            "keyConfigured": key_configured,
            "complete": not missing,
            "missingFields": missing,
            "configVersion": int(configuration.get("configVersion") or 1),
            "lastValidation": last_validation,
            "createdAt": str(configuration.get("createdAt", "")),
            "updatedAt": str(configuration.get("updatedAt", "")),
        }

    def _validated_fields(
        self,
        name,
        note,
        access_method,
        service_base_url,
        model_name,
        temperature,
        max_output_tokens,
        context_window_tokens,
    ) -> dict:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ModelConfigurationError("MODEL_CONFIG_NAME_REQUIRED", "请输入配置名称。")
        if len(clean_name) > MAX_CONFIGURATION_NAME_LENGTH:
            raise ModelConfigurationError("MODEL_CONFIG_NAME_TOO_LONG", "配置名称不能超过 40 个字符。")
        clean_note = str(note or "").strip()
        if len(clean_note) > MAX_CONFIGURATION_NOTE_LENGTH:
            raise ModelConfigurationError("MODEL_CONFIG_NOTE_TOO_LONG", "配置备注不能超过 200 个字符。")
        method = str(access_method or "").strip()
        if method not in SUPPORTED_ACCESS_METHODS:
            raise ModelConfigurationError("MODEL_CONFIG_ACCESS_METHOD_INVALID", "请选择有效的模型调用方式。")
        service_url = normalize_service_base_url(service_base_url)
        clean_model = str(model_name or "").strip()
        if _CONTROL_CHAR_RE.search(clean_model) or len(clean_model) > 160:
            raise ModelConfigurationError("MODEL_CONFIG_MODEL_INVALID", "模型标识格式无效。")
        if method == ACCESS_WORKFLOW_PLATFORM:
            clean_model = ""
            temperature = None
            max_output_tokens = None
        clean_temperature = self._optional_float(temperature, 0.0, 2.0, "温度参数")
        clean_max_output = self._optional_int(max_output_tokens, 1, 200000, "最大输出 Token")
        clean_context = self._optional_int(
            context_window_tokens, 1000, 2000000, "上下文容量"
        )
        if clean_context is None:
            clean_context = DEFAULT_CONTEXT_WINDOW_TOKENS
        if clean_max_output is not None and clean_max_output >= clean_context:
            raise ModelConfigurationError(
                "MODEL_CONFIG_TOKEN_BUDGET_INVALID", "最大输出 Token 必须小于上下文容量。"
            )
        return {
            "name": clean_name,
            "note": clean_note,
            "accessMethod": method,
            "serviceBaseUrl": service_url,
            "modelName": clean_model,
            "temperature": clean_temperature,
            "maxOutputTokens": clean_max_output,
            "contextWindowTokens": clean_context,
        }

    @staticmethod
    def _optional_float(value, minimum: float, maximum: float, label: str):
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ModelConfigurationError("MODEL_CONFIG_PARAMETER_INVALID", "{0}格式无效。".format(label)) from exc
        if numeric < minimum or numeric > maximum:
            raise ModelConfigurationError("MODEL_CONFIG_PARAMETER_INVALID", "{0}超出允许范围。".format(label))
        return numeric

    @staticmethod
    def _optional_int(value, minimum: int, maximum: int, label: str):
        if value in (None, ""):
            return None
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:
            raise ModelConfigurationError("MODEL_CONFIG_PARAMETER_INVALID", "{0}格式无效。".format(label)) from exc
        if numeric < minimum or numeric > maximum:
            raise ModelConfigurationError("MODEL_CONFIG_PARAMETER_INVALID", "{0}超出允许范围。".format(label))
        return numeric

    @staticmethod
    def _configuration_map(payload: dict) -> Dict[str, dict]:
        source = payload.get("modelConfigurations", {})
        if not isinstance(source, dict):
            return {}
        result = {}
        for configuration_id, item in source.items():
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            copied["id"] = str(copied.get("id", configuration_id)).strip()
            task = str(copied.get("taskType", "")).strip()
            if not copied["id"] or task not in SUPPORTED_WORKFLOW_TASKS:
                continue
            copied["taskType"] = task
            copied["host"] = host_for_task(task)
            result[copied["id"]] = copied
        return result

    @staticmethod
    def _active_map(payload: dict) -> Dict[str, str]:
        source = payload.get("activeModelConfigurations", {})
        if not isinstance(source, dict):
            return {}
        return {str(task): str(configuration_id) for task, configuration_id in source.items()}

    @staticmethod
    def _require_configuration(configurations: Dict[str, dict], configuration_id: str) -> dict:
        configuration = configurations.get(str(configuration_id).strip())
        if not isinstance(configuration, dict):
            raise ModelConfigurationError("MODEL_CONFIG_NOT_FOUND", "未找到指定的模型配置。")
        return configuration

    @staticmethod
    def _validate_task_type(task_type: str) -> str:
        task = str(task_type or "").strip()
        if task not in SUPPORTED_WORKFLOW_TASKS:
            raise ModelConfigurationError("MODEL_CONFIG_TASK_UNSUPPORTED", "不支持的任务类型。")
        return task

    @staticmethod
    def _validate_api_key(api_key: str) -> str:
        clean = str(api_key or "").strip()
        if not clean or _CONTROL_CHAR_RE.search(clean):
            raise ModelConfigurationError("MODEL_CONFIG_KEY_REQUIRED", "请输入有效的 API Key。")
        return clean

    @staticmethod
    def _ensure_unique_name(configurations, name: str) -> None:
        target = name.strip().casefold()
        if any(str(item.get("name", "")).strip().casefold() == target for item in configurations):
            raise ModelConfigurationError("MODEL_CONFIG_NAME_DUPLICATE", "该功能下的配置名称已存在。")

    def _copy_name(self, configurations, base_name: str) -> str:
        root = "{0} 副本".format(str(base_name).strip() or "模型配置")
        existing = {str(item.get("name", "")).strip().casefold() for item in configurations}
        if root.casefold() not in existing:
            return root[:MAX_CONFIGURATION_NAME_LENGTH]
        index = 2
        while True:
            suffix = " {0}".format(index)
            candidate = root[: MAX_CONFIGURATION_NAME_LENGTH - len(suffix)] + suffix
            if candidate.casefold() not in existing:
                return candidate
            index += 1

    def _touch(self, configuration: dict) -> None:
        configuration["configVersion"] = int(configuration.get("configVersion") or 0) + 1
        configuration["updatedAt"] = _utc_now()

    def _deactivate_if_incomplete(self, payload: dict, configuration: dict) -> None:
        if self._sanitize(configuration)["complete"]:
            return
        active = self._active_map(payload)
        if active.get(configuration["taskType"]) == configuration["id"]:
            active.pop(configuration["taskType"], None)
            payload["activeModelConfigurations"] = active

    def _key_path(self, api_key_ref: str) -> Path:
        ref = str(api_key_ref or "").strip()
        if not ref or not _SAFE_KEY_REF.fullmatch(ref):
            raise ModelConfigurationError("MODEL_CONFIG_KEY_REF_INVALID", "API Key 引用格式无效。")
        return self.key_dir / ref

    def _key_exists(self, api_key_ref: str) -> bool:
        try:
            return bool(self._read_key(api_key_ref))
        except ModelConfigurationError:
            return False

    def _read_key(self, api_key_ref: str) -> str:
        path = self._key_path(api_key_ref)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _write_key(self, api_key_ref: str, api_key: str) -> None:
        path = self._key_path(api_key_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(str(path.parent), 0o700)
        temporary = path.parent / ".{0}.{1}.tmp".format(path.name, uuid.uuid4().hex)
        try:
            temporary.write_text(api_key.strip() + "\n", encoding="utf-8")
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _delete_key(self, api_key_ref: str) -> None:
        try:
            path = self._key_path(api_key_ref)
        except ModelConfigurationError:
            return
        if path.exists():
            path.unlink()


class WorkflowProfileCompatibilityStore:
    """One-release compatibility facade backed by workflow-platform model configs."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        key_dir: Optional[Path] = None,
    ) -> None:
        self.store = ModelConfigurationStore(config_path, key_dir)
        self.config_path = self.store.config_path
        self.key_dir = self.store.key_dir

    @staticmethod
    def _profile(configuration: dict) -> dict:
        return {
            "id": configuration["id"],
            "taskType": configuration["taskType"],
            "name": configuration["name"],
            "apiKeyRef": configuration["apiKeyRef"],
            "note": configuration.get("note", ""),
            "createdAt": configuration.get("createdAt", ""),
            "updatedAt": configuration.get("updatedAt", ""),
            "keyConfigured": bool(configuration.get("keyConfigured")),
        }

    @staticmethod
    def _raise(exc: ModelConfigurationError) -> None:
        code_map = {
            "MODEL_CONFIG_NOT_FOUND": "WORKFLOW_PROFILE_NOT_FOUND",
            "MODEL_CONFIG_ACTIVE": "WORKFLOW_PROFILE_ACTIVE",
            "MODEL_CONFIG_LIMIT": "WORKFLOW_PROFILE_LIMIT",
            "MODEL_CONFIG_NAME_DUPLICATE": "WORKFLOW_PROFILE_NAME_DUPLICATE",
            "MODEL_CONFIG_NAME_REQUIRED": "WORKFLOW_PROFILE_NAME_REQUIRED",
            "MODEL_CONFIG_NAME_TOO_LONG": "WORKFLOW_PROFILE_NAME_TOO_LONG",
            "MODEL_CONFIG_NOTE_TOO_LONG": "WORKFLOW_PROFILE_NOTE_TOO_LONG",
            "MODEL_CONFIG_KEY_REQUIRED": "WORKFLOW_PROFILE_KEY_REQUIRED",
            "MODEL_CONFIG_INCOMPLETE": "WORKFLOW_PROFILE_KEY_MISSING",
            "MODEL_CONFIG_TASK_UNSUPPORTED": "WORKFLOW_PROFILE_TASK_UNSUPPORTED",
        }
        raise WorkflowProfileError(code_map.get(exc.code, exc.code), exc.message) from exc

    def _platform_configurations(
        self, task_type: str
    ) -> Tuple[Dict, List]:
        try:
            data = self.store.list_for_task(task_type)
        except ModelConfigurationError as exc:
            self._raise(exc)
        configurations = [
            item
            for item in data["configurations"]
            if item.get("accessMethod") == ACCESS_WORKFLOW_PLATFORM
        ]
        return data, configurations

    def list_for_task(self, task_type: str) -> dict:
        data, configurations = self._platform_configurations(task_type)
        active_id = str(data.get("activeConfigurationId", ""))
        if not any(item["id"] == active_id for item in configurations):
            active_id = ""
        return {
            "taskType": data["taskType"],
            "activeProfileId": active_id,
            "profileCount": len(configurations),
            "profiles": [self._profile(item) for item in configurations],
        }

    def _global_service_base_url(self) -> str:
        payload = load_config_payload(self.config_path)
        return str(payload.get("providerBaseUrl", ""))

    def create_profile(
        self,
        task_type: str,
        name: str,
        api_key: str,
        note: str = "",
        activate: bool = False,
    ) -> dict:
        try:
            configuration = self.store.create_configuration(
                task_type,
                name,
                ACCESS_WORKFLOW_PLATFORM,
                note=note,
                service_base_url=self._global_service_base_url(),
            )
            configuration = self.store.replace_api_key(configuration["id"], api_key)
            if activate:
                self.store.activate_configuration(configuration["id"])
            return self._profile(configuration)
        except ModelConfigurationError as exc:
            self._raise(exc)

    def _require_platform(self, profile_id: str, include_secret: bool = False) -> dict:
        try:
            configuration = self.store.get_configuration(
                profile_id, include_secret=include_secret
            )
        except ModelConfigurationError as exc:
            self._raise(exc)
        if configuration.get("accessMethod") != ACCESS_WORKFLOW_PLATFORM:
            raise WorkflowProfileError(
                "WORKFLOW_PROFILE_NOT_FOUND", "未找到指定的工作流配置。"
            )
        return configuration

    def update_profile(self, profile_id: str, name: str, note: str = "") -> dict:
        configuration = self._require_platform(profile_id)
        try:
            updated = self.store.update_configuration(
                profile_id,
                name=name,
                note=note,
                access_method=ACCESS_WORKFLOW_PLATFORM,
                service_base_url=configuration.get("serviceBaseUrl", ""),
            )
            return self._profile(updated)
        except ModelConfigurationError as exc:
            self._raise(exc)

    def replace_api_key(self, profile_id: str, api_key: str) -> dict:
        self._require_platform(profile_id)
        try:
            return self._profile(self.store.replace_api_key(profile_id, api_key))
        except ModelConfigurationError as exc:
            self._raise(exc)

    def activate_profile(self, profile_id: str) -> dict:
        self._require_platform(profile_id)
        try:
            self.store.activate_configuration(profile_id)
            task_type = self.store.get_configuration(profile_id)["taskType"]
            return self.list_for_task(task_type)
        except ModelConfigurationError as exc:
            self._raise(exc)

    def delete_profile(self, profile_id: str) -> dict:
        configuration = self._require_platform(profile_id)
        try:
            self.store.delete_configuration(profile_id)
            return self.list_for_task(configuration["taskType"])
        except ModelConfigurationError as exc:
            self._raise(exc)

    def get_active_profile(self, task_type: str, migrate: bool = True) -> Optional[dict]:
        del migrate
        try:
            configuration = self.store.get_active_configuration(task_type)
        except ModelConfigurationError as exc:
            self._raise(exc)
        if not configuration or configuration.get("accessMethod") != ACCESS_WORKFLOW_PLATFORM:
            return None
        return self._profile(configuration)

    def _unused_name(self, task_type: str) -> str:
        _, configurations = self._platform_configurations(task_type)
        names = {str(item.get("name", "")).casefold() for item in configurations}
        root = "当前配置"
        if root.casefold() not in names:
            return root
        index = 2
        while "{0} {1}".format(root, index).casefold() in names:
            index += 1
        return "{0} {1}".format(root, index)

    def save_legacy_task_api_key(
        self, task_type: str, api_key_ref: str, api_key: str
    ) -> dict:
        del api_key_ref
        data = self.list_for_task(task_type)
        active_id = str(data.get("activeProfileId", ""))
        if active_id:
            self.replace_api_key(active_id, api_key)
        else:
            profile = self.create_profile(
                task_type,
                self._unused_name(task_type),
                api_key,
                activate=True,
            )
            active_id = profile["id"]
        return self.list_for_task(task_type)

    def clear_active_api_key(self, task_type: str) -> dict:
        data = self.list_for_task(task_type)
        active_id = str(data.get("activeProfileId", ""))
        if active_id:
            try:
                self.store.clear_api_key(active_id)
            except ModelConfigurationError as exc:
                self._raise(exc)
        return self.list_for_task(task_type)
