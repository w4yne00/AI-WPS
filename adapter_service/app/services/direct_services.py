import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import default_config_path, load_config_payload, save_config_payload
from app.core.runtime_paths import resolve_runtime_paths
from app.services.model_configurations import (
    MAX_CONFIGURATION_NAME_LENGTH,
    host_for_task,
    normalize_service_base_url,
)
from app.services.word.image_semantics import IMAGE_INPUT_MODES
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS

MAX_DIRECT_SERVICES = 5
MAX_DIRECT_SERVICE_NAME_LENGTH = MAX_CONFIGURATION_NAME_LENGTH
_SAFE_KEY_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_STORE_LOCK = threading.RLock()


class DirectServiceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        referenced_tasks: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.referenced_tasks = referenced_tasks or []


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class DirectServiceStore:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        key_dir: Optional[Path] = None,
        api_key_dir: Optional[Path] = None,
    ) -> None:
        self.config_path = (
            Path(config_path) if config_path is not None else default_config_path()
        )
        resolved_key = key_dir if key_dir is not None else api_key_dir
        self.key_dir = (
            Path(resolved_key)
            if resolved_key is not None
            else resolve_runtime_paths().api_key_dir
        )

    # ------------------------------------------------------------------
    # Shared Direct Model Services
    # ------------------------------------------------------------------

    def list_services(self) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = [
                self._sanitize_service(item)
                for item in self._service_map(payload).values()
            ]
            services.sort(key=lambda s: (s.get("createdAt", ""), s["id"]))
            return {
                "directServiceCount": len(services),
                "directServices": services,
            }

    def get_service(self, service_id: str, include_secret: bool = False) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            service = self._require_service(self._service_map(payload), service_id)
            result = self._sanitize_service(service)
            if include_secret:
                result["apiKey"] = self._read_key(service["id"])
            return result

    def create_service(
        self,
        name: str,
        service_base_url: str = "",
        default_model: str = "",
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            if len(services) >= MAX_DIRECT_SERVICES:
                raise DirectServiceError(
                    "DIRECT_SERVICE_LIMIT",
                    f"最多只能保存 {MAX_DIRECT_SERVICES} 份共享直连服务。",
                )

            clean_name = self._validate_service_name(name, services)
            clean_url = normalize_service_base_url(service_base_url)
            clean_model = self._validate_model_name(default_model)

            service_id = f"direct_svc_{uuid.uuid4().hex[:12]}"
            now = _utc_now()
            record = {
                "id": service_id,
                "name": clean_name,
                "serviceBaseUrl": clean_url,
                "defaultModel": clean_model,
                "modelList": [],
                "modelListFetchedAt": None,
                "revision": 1,
                "createdAt": now,
                "updatedAt": now,
            }
            services[service_id] = record
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(record)

    def update_service(
        self,
        service_id: str,
        name: str,
        expected_revision: int,
        service_base_url: str = "",
        default_model: str = "",
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            self._check_revision(service, expected_revision)

            clean_name = self._validate_service_name(
                name, services, exclude_id=service_id
            )
            clean_url = normalize_service_base_url(service_base_url)
            clean_model = self._validate_model_name(default_model)

            service["name"] = clean_name
            service["serviceBaseUrl"] = clean_url
            service["defaultModel"] = clean_model
            service["revision"] = int(service.get("revision", 1)) + 1
            service["updatedAt"] = _utc_now()

            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(service)

    def delete_service(
        self,
        service_id: str,
        expected_revision: Optional[int] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            if expected_revision is not None:
                self._check_revision(service, expected_revision)

            # Check references from taskModelSelections
            selections = self._selection_map(payload)
            referenced = [
                task_type
                for task_type, sel in selections.items()
                if isinstance(sel, dict) and sel.get("serviceId") == service_id
            ]
            if referenced:
                raise DirectServiceError(
                    "DIRECT_SERVICE_IN_USE",
                    "该服务已被任务引用，无法删除。",
                    referenced_tasks=referenced,
                )

            services.pop(service_id, None)
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            self._delete_key(service_id)
            return self.list_services()

    def replace_api_key(
        self,
        service_id: str,
        api_key: str,
        expected_revision: Optional[int] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            if expected_revision is not None:
                self._check_revision(service, expected_revision)

            clean_key = str(api_key or "").strip()
            if not clean_key or _CONTROL_CHAR_RE.search(clean_key):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_INVALID", "API Key 格式无效。"
                )

            self._write_key(service_id, clean_key)
            service["revision"] = int(service.get("revision", 1)) + 1
            service["updatedAt"] = _utc_now()
            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(service)

    def clear_api_key(
        self,
        service_id: str,
        expected_revision: Optional[int] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            if expected_revision is not None:
                self._check_revision(service, expected_revision)

            self._delete_key(service_id)
            service["revision"] = int(service.get("revision", 1)) + 1
            service["updatedAt"] = _utc_now()
            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(service)

    def update_model_list(
        self,
        service_id: str,
        model_list: List[str],
        fetched_at: Optional[str] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            clean_models = [str(m).strip() for m in model_list if str(m).strip()]
            service["modelList"] = clean_models
            service["modelListFetchedAt"] = fetched_at or _utc_now()
            service["updatedAt"] = _utc_now()
            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(service)

    # ------------------------------------------------------------------
    # Task Model Selections
    # ------------------------------------------------------------------

    def list_task_model_selections(
        self,
        host: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            selections = self._selection_map(payload)

            tasks = list(SUPPORTED_WORKFLOW_TASKS)
            if task_type:
                clean_task = self._validate_task_type(task_type)
                tasks = [clean_task]
            elif host:
                clean_host = str(host).strip().lower()
                tasks = [t for t in tasks if host_for_task(t) == clean_host]

            results = []
            for task in tasks:
                raw = selections.get(task, {})
                service_id = str(raw.get("serviceId", "")).strip()
                service = services.get(service_id, {})
                model_name = str(raw.get("modelName", "")).strip()

                effective_model = ""
                if model_name:
                    effective_model = model_name
                elif service:
                    effective_model = str(service.get("defaultModel", "")).strip()

                results.append(
                    {
                        "taskType": task,
                        "host": host_for_task(task),
                        "serviceId": service_id,
                        "serviceName": str(service.get("name", "")),
                        "modelName": model_name,
                        "effectiveModel": effective_model,
                        "temperature": raw.get("temperature"),
                        "maxOutputTokens": raw.get("maxOutputTokens"),
                        "contextWindowTokens": raw.get("contextWindowTokens"),
                        "imageInputMode": str(raw.get("imageInputMode", "disabled")),
                        "customModel": bool(raw.get("customModel", False)),
                        "customModelValidated": bool(
                            raw.get("customModelValidated", False)
                        ),
                        "updatedAt": str(raw.get("updatedAt", "")),
                    }
                )

            return {"taskModelSelections": results}

    def get_task_model_selection(self, task_type: str) -> dict:
        result = self.list_task_model_selections(task_type=task_type)
        items = result.get("taskModelSelections", [])
        if not items:
            raise DirectServiceError(
                "DIRECT_SERVICE_TASK_UNSUPPORTED", f"不支持的任务类型: {task_type}"
            )
        return items[0]

    def update_task_model_selection(
        self,
        task_type: str,
        service_id: str = "",
        model_name: str = "",
        temperature=None,
        max_output_tokens=None,
        context_window_tokens=None,
        image_input_mode=None,
        custom_model: bool = False,
        custom_model_validated: bool = False,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            selections = self._selection_map(payload)

            clean_service_id = str(service_id or "").strip()
            if clean_service_id:
                if clean_service_id not in services:
                    raise DirectServiceError(
                        "DIRECT_SERVICE_NOT_FOUND", "引用的直连服务不存在。"
                    )

            clean_model = self._validate_model_name(model_name)
            clean_temp = self._validate_temperature(temperature)
            clean_max_output = self._validate_positive_int(
                max_output_tokens, "最大输出 Token"
            )
            clean_context = self._validate_positive_int(
                context_window_tokens, "上下文容量"
            )
            clean_image_mode = self._validate_image_input_mode(
                clean_task, image_input_mode
            )

            record = {
                "serviceId": clean_service_id,
                "modelName": clean_model,
                "temperature": clean_temp,
                "maxOutputTokens": clean_max_output,
                "contextWindowTokens": clean_context,
                "imageInputMode": clean_image_mode,
                "customModel": bool(custom_model),
                "customModelValidated": bool(custom_model_validated),
                "updatedAt": _utc_now(),
            }
            selections[clean_task] = record
            payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)

            return self.get_task_model_selection(clean_task)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _service_map(payload: dict) -> Dict[str, dict]:
        services = payload.get("directServices")
        if isinstance(services, dict):
            return services
        return {}

    @staticmethod
    def _selection_map(payload: dict) -> Dict[str, dict]:
        selections = payload.get("taskModelSelections")
        if isinstance(selections, dict):
            return selections
        return {}

    def _require_service(self, services: Dict[str, dict], service_id: str) -> dict:
        service = services.get(str(service_id or "").strip())
        if not isinstance(service, dict):
            raise DirectServiceError(
                "DIRECT_SERVICE_NOT_FOUND", "未找到指定的直连服务。"
            )
        return service

    @staticmethod
    def _check_revision(service: dict, expected_revision: int) -> None:
        current = int(service.get("revision", 1))
        if int(expected_revision) != current:
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_CONFLICT",
                "直连服务已被修改，请刷新后重试。",
            )

    @staticmethod
    def _validate_service_name(
        name: str, services: Dict[str, dict], exclude_id: str = ""
    ) -> str:
        clean = str(name or "").strip()
        if not clean:
            raise DirectServiceError(
                "DIRECT_SERVICE_NAME_INVALID", "请输入服务名称。"
            )
        if len(clean) > MAX_DIRECT_SERVICE_NAME_LENGTH or _CONTROL_CHAR_RE.search(clean):
            raise DirectServiceError(
                "DIRECT_SERVICE_NAME_INVALID",
                f"服务名称不能超过 {MAX_DIRECT_SERVICE_NAME_LENGTH} 个字符且不能包含控制字符。",
            )
        for s_id, s in services.items():
            if s_id != exclude_id and s.get("name") == clean:
                raise DirectServiceError(
                    "DIRECT_SERVICE_NAME_DUPLICATE", "已存在同名直连服务。"
                )
        return clean

    @staticmethod
    def _validate_model_name(model_name: str) -> str:
        clean = str(model_name or "").strip()
        if not clean:
            return ""
        if _CONTROL_CHAR_RE.search(clean) or len(clean) > 160:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_INVALID", "模型标识格式无效。"
            )
        return clean

    @staticmethod
    def _validate_task_type(task_type: str) -> str:
        clean = str(task_type or "").strip()
        if clean not in SUPPORTED_WORKFLOW_TASKS:
            raise DirectServiceError(
                "DIRECT_SERVICE_TASK_UNSUPPORTED", f"不支持的任务类型: {task_type}"
            )
        return clean

    @staticmethod
    def _validate_temperature(temperature) -> Optional[float]:
        if temperature in (None, ""):
            return None
        try:
            val = float(temperature)
            if 0.0 <= val <= 2.0:
                return val
        except (TypeError, ValueError):
            pass
        raise DirectServiceError(
            "DIRECT_SERVICE_PARAM_INVALID", "温度参数必须在 0.0 到 2.0 之间。"
        )

    @staticmethod
    def _validate_positive_int(value, label: str) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            val = int(value)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
        raise DirectServiceError(
            "DIRECT_SERVICE_PARAM_INVALID", f"{label}必须是正整数。"
        )

    @staticmethod
    def _validate_image_input_mode(task_type: str, mode) -> str:
        clean = str(mode or "disabled").strip()
        if clean not in IMAGE_INPUT_MODES:
            raise DirectServiceError(
                "DIRECT_SERVICE_PARAM_INVALID", f"无效的图片输入模式: {mode}"
            )
        if task_type != "word.format_review" and clean != "disabled":
            return "disabled"
        return clean

    def _sanitize_service(self, service: dict) -> dict:
        service_id = str(service.get("id", ""))
        return {
            "id": service_id,
            "name": str(service.get("name", "")),
            "serviceBaseUrl": str(service.get("serviceBaseUrl", "")),
            "keyConfigured": self._key_exists(service_id),
            "defaultModel": str(service.get("defaultModel", "")),
            "modelList": list(service.get("modelList", [])),
            "modelListFetchedAt": service.get("modelListFetchedAt"),
            "revision": int(service.get("revision", 1)),
            "createdAt": str(service.get("createdAt", "")),
            "updatedAt": str(service.get("updatedAt", "")),
        }

    def _key_path(self, service_id: str) -> Path:
        ref = f"direct_service_{service_id}"
        if not _SAFE_KEY_REF.fullmatch(ref):
            raise DirectServiceError(
                "DIRECT_SERVICE_KEY_REF_INVALID", "API Key 引用格式无效。"
            )
        return self.key_dir / ref

    def _key_exists(self, service_id: str) -> bool:
        path = self._key_path(service_id)
        if not path.exists():
            return False
        try:
            return bool(path.read_text(encoding="utf-8").strip())
        except OSError:
            return False

    def _read_key(self, service_id: str) -> str:
        path = self._key_path(service_id)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _write_key(self, service_id: str, api_key: str) -> None:
        path = self._key_path(service_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(path.parent), 0o700)
        except OSError:
            pass
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(api_key.strip() + "\n", encoding="utf-8")
            try:
                os.chmod(str(temporary), 0o600)
            except OSError:
                pass
            os.replace(str(temporary), str(path))
            try:
                os.chmod(str(path), 0o600)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()

    def _delete_key(self, service_id: str) -> None:
        path = self._key_path(service_id)
        if path.exists():
            path.unlink()
