import hashlib
import json
import os
import re
import socket
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError

from app.core.config import default_config_path, load_config_payload, save_config_payload
from app.core.runtime_paths import resolve_runtime_paths
from app.services.model_configurations import (
    MAX_CONFIGURATION_NAME_LENGTH,
    ModelConfigurationError,
    _STORE_LOCK,
    host_for_task,
    normalize_service_base_url,
)
from app.services.word.image_semantics import IMAGE_INPUT_MODES
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS

MAX_DIRECT_SERVICES = 5
MAX_DIRECT_SERVICE_NAME_LENGTH = MAX_CONFIGURATION_NAME_LENGTH
DIRECT_SERVICE_SCHEMA_VERSION = "provider.direct_service.v1"
TASK_MODEL_SELECTION_SCHEMA_VERSION = "provider.task_model_selection.v1"
MODEL_LIST_CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_MODEL_CATALOG_MODELS = 1000
MAX_MODEL_CATALOG_RESPONSE_BYTES = 1024 * 1024
_SAFE_KEY_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


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


def _parse_utc_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        cleaned = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
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

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            return normalize_service_base_url(url)
        except ModelConfigurationError as exc:
            raise DirectServiceError(
                "DIRECT_SERVICE_URL_INVALID", exc.message
            ) from exc

    def list_services(self) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = [
                self._sanitize_service(item)
                for item in self._service_map(payload).values()
            ]
            services.sort(key=lambda s: (s.get("createdAt", ""), s["id"]))
            return {
                "schemaVersion": DIRECT_SERVICE_SCHEMA_VERSION,
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
        api_key: Optional[str] = None,
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
            clean_url = self._normalize_url(service_base_url)
            clean_model = self._validate_model_name(default_model)

            service_id = f"direct_svc_{uuid.uuid4().hex[:12]}"
            if api_key is not None and str(api_key).strip():
                self._write_key(service_id, str(api_key).strip())

            now = _utc_now()
            record = {
                "id": service_id,
                "name": clean_name,
                "serviceBaseUrl": clean_url,
                "defaultModel": clean_model,
                "modelList": [],
                "modelListFetchedAt": None,
                "modelListLastAttemptAt": None,
                "modelListFetchStatus": "not_attempted",
                "modelListLastError": None,
                "modelListInvalidated": False,
                "modelListTrusted": True,
                "modelListSource": "none",
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
            clean_url = self._normalize_url(service_base_url)
            clean_model = self._validate_model_name(default_model)

            if clean_url != str(service.get("serviceBaseUrl", "")):
                self._invalidate_model_catalog(service)

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
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

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
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            self._check_revision(service, expected_revision)

            clean_key = str(api_key or "").strip()
            if not clean_key or _CONTROL_CHAR_RE.search(clean_key):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_INVALID", "API Key 格式无效。"
                )

            prior_key = self._read_key(service_id)
            had_prior_key = self._key_exists(service_id)

            self._invalidate_model_catalog(service)
            self._write_key(service_id, clean_key)
            try:
                service["revision"] = int(service.get("revision", 1)) + 1
                service["updatedAt"] = _utc_now()
                services[service_id] = service
                payload["directServices"] = services
                save_config_payload(payload, self.config_path)
            except Exception:
                if had_prior_key:
                    try:
                        self._write_key(service_id, prior_key)
                    except Exception:
                        pass
                else:
                    self._delete_key(service_id)
                raise
            return self._sanitize_service(service)

    def clear_api_key(
        self,
        service_id: str,
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            self._check_revision(service, expected_revision)

            prior_key = self._read_key(service_id)
            had_prior_key = self._key_exists(service_id)

            self._invalidate_model_catalog(service)
            self._delete_key(service_id)
            try:
                service["revision"] = int(service.get("revision", 1)) + 1
                service["updatedAt"] = _utc_now()
                services[service_id] = service
                payload["directServices"] = services
                save_config_payload(payload, self.config_path)
            except Exception:
                if had_prior_key:
                    try:
                        self._write_key(service_id, prior_key)
                    except Exception:
                        pass
                raise
            return self._sanitize_service(service)

    def update_model_list(
        self,
        service_id: str,
        model_list: List[str],
        expected_revision: Optional[int] = None,
        fetched_at: Optional[str] = None,
        trusted: bool = True,
        source: Optional[str] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            if expected_revision is not None:
                self._check_revision(service, expected_revision)

            clean_models = self._extract_model_list(model_list)
            if not trusted:
                service["modelList"] = clean_models
                service["modelListFetchedAt"] = None
                service["modelListLastAttemptAt"] = _utc_now()
                service["modelListFetchStatus"] = "untrusted"
                service["modelListLastError"] = {
                    "code": "DIRECT_SERVICE_MODELS_UNTRUSTED",
                    "message": "客户端提交的模型列表不作为服务目录依据。",
                }
                service["modelListInvalidated"] = False
                service["modelListTrusted"] = False
                service["modelListSource"] = str(source or "client")
                service["revision"] = int(service.get("revision", 1)) + 1
                service["updatedAt"] = _utc_now()
                services[service_id] = service
                payload["directServices"] = services
                save_config_payload(payload, self.config_path)
                return self._sanitize_service(service)

            clean_fetched_at = self._normalize_fetched_at(fetched_at)
            service["modelList"] = clean_models
            service["modelListFetchedAt"] = clean_fetched_at
            service["modelListLastAttemptAt"] = clean_fetched_at
            service["modelListFetchStatus"] = "success"
            service["modelListLastError"] = None
            service["modelListInvalidated"] = False
            service["modelListTrusted"] = True
            service["modelListSource"] = str(source or "discovery")
            service["revision"] = int(service.get("revision", 1)) + 1
            service["updatedAt"] = _utc_now()
            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)
            return self._sanitize_service(service)

    def is_model_list_expired(self, service: dict) -> bool:
        fetched_at = _parse_utc_timestamp(service.get("modelListFetchedAt"))
        if fetched_at is None:
            return True
        return (
            datetime.now(timezone.utc) - fetched_at
        ).total_seconds() >= MODEL_LIST_CACHE_TTL_SECONDS

    def get_model_catalog_status(self, service_id: str) -> dict:
        return self.get_service(service_id).get("modelCatalog", {})

    def _model_catalog_state(self, service: dict) -> dict:
        raw_models = service.get("modelList")
        models = list(raw_models) if isinstance(raw_models, list) else []
        fetched_at = service.get("modelListFetchedAt")
        parsed_fetched_at = _parse_utc_timestamp(fetched_at)
        has_fetched_at = bool(fetched_at and parsed_fetched_at is not None)
        expired = self.is_model_list_expired(service)
        invalidated = bool(service.get("modelListInvalidated", False))

        if invalidated:
            status = "unavailable"
            cache_status = "invalidated"
        elif has_fetched_at and not expired:
            status = "available" if models else "empty"
            cache_status = "valid"
        elif has_fetched_at:
            status = "expired"
            cache_status = "expired"
        else:
            status = "unavailable"
            cache_status = "empty"

        fetch_status = str(service.get("modelListFetchStatus", "")).strip()
        if fetch_status not in {"not_attempted", "success", "error"}:
            fetch_status = "success" if has_fetched_at else "not_attempted"

        last_error = service.get("modelListLastError")
        if isinstance(last_error, dict):
            clean_error = {
                "code": str(last_error.get("code", "")).strip(),
                "message": str(last_error.get("message", "")).strip(),
            }
            if not clean_error["code"] and not clean_error["message"]:
                clean_error = None
        else:
            clean_error = None

        trusted = service.get("modelListTrusted") is not False
        if not trusted:
            if clean_error is None:
                clean_error = {
                    "code": "DIRECT_SERVICE_MODELS_UNTRUSTED",
                    "message": "客户端提交的模型列表不作为服务目录依据。",
                }
            return {
                "status": "unavailable",
                "cacheStatus": "untrusted",
                "fetchStatus": "untrusted",
                "models": [],
                "fetchedAt": None,
                "expiresAt": None,
                "lastAttemptAt": service.get("modelListLastAttemptAt"),
                "lastError": clean_error,
                "manualModelAllowed": True,
                "usableForSelection": False,
                "trusted": False,
                "submittedModelsCount": len(models),
            }

        expires_at = None
        if parsed_fetched_at is not None:
            expires_at = _format_utc_timestamp(
                parsed_fetched_at + timedelta(seconds=MODEL_LIST_CACHE_TTL_SECONDS)
            )

        manual_allowed = cache_status != "valid" or status == "empty"
        return {
            "status": status,
            "cacheStatus": cache_status,
            "fetchStatus": fetch_status,
            "models": models,
            "fetchedAt": fetched_at if has_fetched_at else None,
            "expiresAt": expires_at,
            "lastAttemptAt": service.get("modelListLastAttemptAt"),
            "lastError": clean_error,
            "manualModelAllowed": manual_allowed,
            "usableForSelection": status == "available" and bool(models),
            "trusted": True,
            "submittedModelsCount": len(models),
        }

    def _record_model_catalog_failure(
        self,
        service_id: str,
        error: DirectServiceError,
        expected_revision: Optional[int] = None,
    ) -> None:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)
            if expected_revision is not None:
                try:
                    if int(service.get("revision", 1)) != int(expected_revision):
                        return
                except (TypeError, ValueError):
                    return
            service["modelListLastAttemptAt"] = _utc_now()
            service["modelListFetchStatus"] = "error"
            service["modelListLastError"] = {
                "code": error.code,
                "message": error.message,
            }
            services[service_id] = service
            payload["directServices"] = services
            save_config_payload(payload, self.config_path)

    def _catalog_failure(
        self,
        service_id: str,
        code: str,
        message: str,
        expected_revision: Optional[int] = None,
    ) -> DirectServiceError:
        error = DirectServiceError(code, message)
        try:
            self._record_model_catalog_failure(
                service_id, error, expected_revision=expected_revision
            )
        except DirectServiceError:
            pass
        return error

    @staticmethod
    def _normalize_fetched_at(fetched_at: Optional[str]) -> str:
        if fetched_at is None or not str(fetched_at).strip():
            return _utc_now()
        parsed = _parse_utc_timestamp(fetched_at)
        if parsed is None:
            raise DirectServiceError(
                "DIRECT_SERVICE_TIMESTAMP_INVALID",
                "模型目录获取时间格式无效。",
            )
        return _format_utc_timestamp(parsed)

    @staticmethod
    def _extract_model_list(data) -> List[str]:
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            if isinstance(data.get("data"), list):
                raw_list = data["data"]
            elif isinstance(data.get("models"), list):
                raw_list = data["models"]
            else:
                raise DirectServiceError(
                    "DIRECT_SERVICE_MODELS_PARSE_FAILED", "模型目录返回格式无效。"
                )
        else:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODELS_PARSE_FAILED", "模型目录返回格式无效。"
            )

        if len(raw_list) > MAX_MODEL_CATALOG_MODELS:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODELS_LIMIT",
                f"模型目录最多只能包含 {MAX_MODEL_CATALOG_MODELS} 个模型。",
            )

        extracted = []
        for item in raw_list:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
                if not isinstance(model_id, str):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_MODELS_PARSE_FAILED", "模型目录返回格式无效。"
                    )
                model_name = model_id.strip()
            elif isinstance(item, str):
                model_name = item.strip()
            else:
                raise DirectServiceError(
                    "DIRECT_SERVICE_MODELS_PARSE_FAILED", "模型目录返回格式无效。"
                )
            if (
                not model_name
                or len(model_name) > 160
                or _CONTROL_CHAR_RE.search(model_name)
            ):
                raise DirectServiceError(
                    "DIRECT_SERVICE_MODELS_PARSE_FAILED", "模型目录返回格式无效。"
                )
            if model_name not in extracted:
                extracted.append(model_name)
        return extracted

    def refresh_models(
        self, service_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)
            if expected_revision is not None:
                self._check_revision(service, expected_revision)
            snapshot_revision = int(service.get("revision", 1))

            api_key = self._read_key(service_id)
            if not api_key:
                raise self._catalog_failure(
                    service_id,
                    "DIRECT_SERVICE_KEY_REQUIRED",
                    "未配置 API Key，无法获取模型目录。",
                    expected_revision=snapshot_revision,
                )
            base_url = str(service.get("serviceBaseUrl", "")).strip().rstrip("/")
            if not base_url:
                raise self._catalog_failure(
                    service_id,
                    "DIRECT_SERVICE_URL_REQUIRED",
                    "未配置服务地址，无法获取模型目录。",
                    expected_revision=snapshot_revision,
                )

        models_url = f"{base_url}/models"
        req = urllib.request.Request(
            models_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "AI-WPS-Adapter",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_bytes = resp.read(MAX_MODEL_CATALOG_RESPONSE_BYTES + 1)
                if len(raw_bytes) > MAX_MODEL_CATALOG_RESPONSE_BYTES:
                    raise self._catalog_failure(
                        service_id,
                        "DIRECT_SERVICE_MODELS_RESPONSE_TOO_LARGE",
                        "模型目录响应超过允许大小。",
                        expected_revision=snapshot_revision,
                    )
                raw = raw_bytes.decode("utf-8")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise self._catalog_failure(
                    service_id,
                    "DIRECT_SERVICE_AUTH_FAILED",
                    "API Key 认证失败，请检查密钥是否正确。",
                    expected_revision=snapshot_revision,
                ) from exc
            if exc.code in (404, 405):
                raise self._catalog_failure(
                    service_id,
                    "DIRECT_SERVICE_MODELS_UNAVAILABLE",
                    "服务未提供模型目录接口，可使用高级手动输入。",
                    expected_revision=snapshot_revision,
                ) from exc
            raise self._catalog_failure(
                service_id,
                "DIRECT_SERVICE_UNREACHABLE",
                f"请求模型目录失败（HTTP {exc.code}）。",
                expected_revision=snapshot_revision,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise self._catalog_failure(
                service_id,
                "DIRECT_SERVICE_TIMEOUT",
                "读取模型目录超时，请稍后重试。",
                expected_revision=snapshot_revision,
            ) from exc
        except (URLError, OSError) as exc:
            raise self._catalog_failure(
                service_id,
                "DIRECT_SERVICE_UNREACHABLE",
                "直连服务地址无法连接，请检查服务地址。",
                expected_revision=snapshot_revision,
            ) from exc
        except UnicodeDecodeError as exc:
            raise self._catalog_failure(
                service_id,
                "DIRECT_SERVICE_MODELS_PARSE_FAILED",
                "模型目录返回格式无效。",
                expected_revision=snapshot_revision,
            ) from exc

        try:
            data = json.loads(raw)
        except Exception as exc:
            raise self._catalog_failure(
                service_id,
                "DIRECT_SERVICE_MODELS_PARSE_FAILED",
                "模型目录返回格式无效。",
                expected_revision=snapshot_revision,
            ) from exc

        try:
            extracted = self._extract_model_list(data)
        except DirectServiceError as exc:
            self._record_model_catalog_failure(
                service_id, exc, expected_revision=snapshot_revision
            )
            raise

        return self.update_model_list(
            service_id,
            extracted,
            expected_revision=snapshot_revision,
            trusted=True,
            source="discovery",
        )

    def validate_service(
        self, service_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        try:
            service = self.refresh_models(
                service_id, expected_revision=expected_revision
            )
            return {
                "success": True,
                "validationScope": "service",
                "serviceId": service["id"],
                "serviceName": service.get("name", ""),
                "reachable": True,
                "authenticated": True,
                "modelCatalogAvailable": bool(
                    service.get("modelCatalog", {}).get("usableForSelection")
                ),
                "modelCatalogEndpointAvailable": True,
                "manualModelAllowed": bool(
                    service.get("modelCatalog", {}).get("manualModelAllowed")
                ),
                "taskCallPerformed": False,
                "taskContractValidated": False,
                "mayIncurModelCost": False,
                "directService": service,
            }
        except DirectServiceError as exc:
            if exc.code not in {
                "DIRECT_SERVICE_MODELS_UNAVAILABLE",
                "DIRECT_SERVICE_MODELS_PARSE_FAILED",
                "DIRECT_SERVICE_MODELS_LIMIT",
                "DIRECT_SERVICE_MODELS_RESPONSE_TOO_LARGE",
            }:
                raise
            service = self.get_service(service_id)
            catalog = service.get("modelCatalog", {})
            return {
                "success": True,
                "validationScope": "service",
                "serviceId": service["id"],
                "serviceName": service.get("name", ""),
                "reachable": True,
                "authenticated": True,
                "modelCatalogAvailable": bool(catalog.get("usableForSelection")),
                "modelCatalogEndpointAvailable": False,
                "modelCatalogFetchError": {
                    "code": exc.code,
                    "message": exc.message,
                },
                "modelCatalogCacheStatus": catalog.get("cacheStatus", "empty"),
                "manualModelAllowed": bool(catalog.get("manualModelAllowed")),
                "taskCallPerformed": False,
                "taskContractValidated": False,
                "mayIncurModelCost": False,
                "directService": service,
            }

    def refresh_models_best_effort(
        self, service_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        service = self.get_service(service_id)
        if not service.get("keyConfigured"):
            return {
                "directService": service,
                "modelCatalogRefresh": {
                    "attempted": False,
                    "success": False,
                    "status": "skipped",
                },
            }
        try:
            refreshed = self.refresh_models(
                service_id, expected_revision=expected_revision
            )
            return {
                "directService": refreshed,
                "modelCatalogRefresh": {
                    "attempted": True,
                    "success": True,
                    "status": "refreshed",
                },
            }
        except DirectServiceError as exc:
            try:
                current = self.get_service(service_id)
            except DirectServiceError:
                current = service
            return {
                "directService": current,
                "modelCatalogRefresh": {
                    "attempted": True,
                    "success": False,
                    "status": "error",
                    "error": {"code": exc.code, "message": exc.message},
                },
            }

    def activate_direct_service(self, service_id: str, task_type: str) -> dict:
        clean_task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)
            if not service.get("serviceBaseUrl"):
                raise DirectServiceError(
                    "DIRECT_SERVICE_URL_REQUIRED", "直连服务缺少服务地址，无法设为当前。"
                )
            if not self._key_exists(service_id):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_REQUIRED", "直连服务未配置 API Key，无法设为当前。"
                )

            selections = self._selection_map(payload)
            task_sel = selections.get(clean_task, {})
            effective_model = str(
                task_sel.get("modelName") or service.get("defaultModel") or ""
            ).strip()
            if not effective_model:
                raise DirectServiceError(
                    "DIRECT_SERVICE_MODEL_REQUIRED",
                    "直连服务未配置有效模型（未设置服务默认模型且任务未指定模型），无法设为当前。",
                )

            self._ensure_task_model_ready(
                clean_task,
                service_id,
                service,
                task_sel,
                effective_model,
            )

            task_sel["serviceId"] = service_id
            task_sel["updatedAt"] = _utc_now()
            selections[clean_task] = task_sel
            payload["taskModelSelections"] = selections

            active = payload.get("activeModelConfigurations")
            if not isinstance(active, dict):
                active = {}
            active[clean_task] = service_id
            payload["activeModelConfigurations"] = active

            save_config_payload(payload, self.config_path)

            return {
                "taskType": clean_task,
                "activeConfigurationId": service_id,
                "taskModelSelection": self.get_task_model_selection(clean_task),
            }

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

                custom_model = bool(raw.get("customModel", False))
                custom_model_validated = bool(
                    service
                    and self._is_custom_model_validated(
                        payload,
                        task,
                        service,
                        model_name or effective_model,
                    )
                )
                model_availability, model_available, unavailable_reason = (
                    self._model_availability(
                        service_id,
                        service,
                        model_name or effective_model,
                        custom_model,
                        custom_model_validated,
                    )
                )
                catalog = self._model_catalog_state(service) if service else {}

                results.append(
                    {
                        "schemaVersion": TASK_MODEL_SELECTION_SCHEMA_VERSION,
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
                        "customModel": custom_model,
                        "customModelValidated": custom_model_validated,
                        "modelAvailability": model_availability,
                        "modelAvailable": model_available,
                        "modelUnavailableReason": unavailable_reason,
                        "modelCatalogStatus": catalog.get("status", "unavailable"),
                        "modelCatalogCacheStatus": catalog.get(
                            "cacheStatus", "empty"
                        ),
                        "manualModelAllowed": bool(
                            catalog.get("manualModelAllowed", False)
                        ),
                        "updatedAt": str(raw.get("updatedAt", "")),
                    }
                )

            return {
                "schemaVersion": TASK_MODEL_SELECTION_SCHEMA_VERSION,
                "taskModelSelections": results,
                "selections": {r["taskType"]: r for r in results},
            }

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

            is_custom = bool(custom_model)
            service = services.get(clean_service_id, {}) if clean_service_id else {}
            if is_custom:
                if not clean_model:
                    raise DirectServiceError(
                        "DIRECT_SERVICE_MODEL_REQUIRED", "自定义模型名称不能为空。"
                    )
                catalog = self._model_catalog_state(service) if service else {}
                if catalog.get("usableForSelection"):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED",
                        "模型目录当前可用时不能使用高级手填模型。",
                    )

            effective_validated = bool(
                is_custom
                and service
                and self._is_custom_model_validated(
                    payload,
                    clean_task,
                    service,
                    clean_model,
                )
            )

            record = {
                "serviceId": clean_service_id,
                "modelName": clean_model,
                "temperature": clean_temp,
                "maxOutputTokens": clean_max_output,
                "contextWindowTokens": clean_context,
                "imageInputMode": clean_image_mode,
                "customModel": is_custom,
                "customModelValidated": effective_validated,
                "updatedAt": _utc_now(),
            }
            selections[clean_task] = record
            payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)

            return self.get_task_model_selection(clean_task)

    def mark_custom_model_validated(
        self,
        task_type: str,
        service_id: str,
        model_name: str,
        expected_service_base_url: Optional[str] = None,
        expected_api_key_fingerprint: Optional[str] = None,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        clean_model = self._validate_model_name(model_name)
        if not clean_model:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_REQUIRED", "自定义模型名称不能为空。"
            )
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            services = self._service_map(payload)
            service = self._require_service(services, service_id)
            if not self._key_exists(service["id"]):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_REQUIRED", "直连服务未配置 API Key，无法记录模型验证结果。"
                )
            if (
                expected_service_base_url is not None
                and str(service.get("serviceBaseUrl", "")).strip()
                != str(expected_service_base_url).strip()
            ):
                raise DirectServiceError(
                    "DIRECT_SERVICE_CONFIG_CHANGED",
                    "服务地址在验证期间发生变化，请重新验证模型。",
                )
            if (
                expected_api_key_fingerprint is not None
                and self._api_key_fingerprint(self._read_key(service["id"]))
                != str(expected_api_key_fingerprint)
            ):
                raise DirectServiceError(
                    "DIRECT_SERVICE_CONFIG_CHANGED",
                    "API Key 在验证期间发生变化，请重新验证模型。",
                )
            catalog = self._model_catalog_state(service)
            if catalog.get("usableForSelection"):
                raise DirectServiceError(
                    "DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED",
                    "模型目录当前可用时不能使用高级手填模型。",
                )

            validations = self._validation_map(payload)
            validations[clean_task] = {
                "serviceId": service["id"],
                "modelName": clean_model,
                "serviceBaseUrl": str(service.get("serviceBaseUrl", "")),
                "apiKeyFingerprint": self._api_key_fingerprint(
                    self._read_key(service["id"])
                ),
                "validatedAt": _utc_now(),
            }
            payload["customModelValidations"] = validations
            save_config_payload(payload, self.config_path)
            return dict(validations[clean_task])

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

    @staticmethod
    def _validation_map(payload: dict) -> Dict[str, dict]:
        validations = payload.get("customModelValidations")
        if isinstance(validations, dict):
            return validations
        return {}

    @staticmethod
    def api_key_fingerprint(api_key: str) -> str:
        return hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _api_key_fingerprint(api_key: str) -> str:
        return DirectServiceStore.api_key_fingerprint(api_key)

    def _is_custom_model_validated(
        self,
        payload: dict,
        task_type: str,
        service: dict,
        model_name: str,
    ) -> bool:
        if not service or not model_name:
            return False
        marker = self._validation_map(payload).get(task_type)
        if not isinstance(marker, dict):
            return False
        service_url_matches = (
            str(marker.get("serviceBaseUrl", "")).strip()
            == str(service.get("serviceBaseUrl", "")).strip()
        )
        return bool(
            service_url_matches
            and str(marker.get("serviceId", "")) == str(service.get("id", ""))
            and str(marker.get("modelName", "")).strip() == str(model_name).strip()
            and str(marker.get("apiKeyFingerprint", ""))
            == self._api_key_fingerprint(self._read_key(str(service.get("id", ""))))
        )

    def is_custom_model_validated(
        self, task_type: str, service_id: str, model_name: str
    ) -> bool:
        clean_task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload = load_config_payload(self.config_path)
            service = self._require_service(
                self._service_map(payload), service_id
            )
            return self._is_custom_model_validated(
                payload, clean_task, service, model_name
            )

    def _model_availability(
        self,
        service_id: str,
        service: dict,
        model_name: str,
        custom_model: bool,
        custom_model_validated: bool,
    ):
        if not service_id or not service or not model_name:
            return "unconfigured", False, "missing_model"
        if custom_model:
            catalog = self._model_catalog_state(service)
            if catalog.get("usableForSelection"):
                return "unavailable", False, "catalog_usable"
            if custom_model_validated:
                return "available", True, ""
            return "unverified", False, "validation_required"

        catalog = self._model_catalog_state(service)
        models = catalog.get("models", [])
        if catalog.get("usableForSelection"):
            if model_name in models:
                return "available", True, ""
            return "unavailable", False, "disappeared"
        if catalog.get("status") == "expired":
            return "expired", False, "cache_expired"
        if catalog.get("status") == "unavailable" or service.get("modelListInvalidated") or (
            catalog.get("fetchStatus") == "error"
            and catalog.get("cacheStatus") != "valid"
        ):
            return "unavailable", False, "catalog_unavailable"
        if catalog.get("status") == "empty":
            return "unavailable", False, "catalog_empty"
        return "unavailable", False, "catalog_unavailable"

    def _ensure_task_model_ready(
        self,
        task_type: str,
        service_id: str,
        service: dict,
        selection: dict,
        effective_model: str,
    ) -> None:
        custom_model = bool(selection.get("customModel", False))
        custom_validated = self._is_custom_model_validated(
            load_config_payload(self.config_path),
            task_type,
            service,
            effective_model,
        )
        availability, _, reason = self._model_availability(
            service_id,
            service,
            effective_model,
            custom_model,
            custom_validated,
        )
        if custom_model and not custom_validated:
            raise DirectServiceError(
                "DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED",
                "高级手填模型尚未通过真实任务调用验证，不能设为当前。",
            )
        if custom_model and availability == "unavailable" and reason == "catalog_usable":
            raise DirectServiceError(
                "DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED",
                "模型目录当前可用时不能使用高级手填模型。",
            )
        if availability == "unavailable" and reason == "disappeared":
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_DISAPPEARED",
                f"所选模型 {effective_model} 已从服务目录中移除，请重新选择模型。",
            )
        if availability == "expired":
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_CATALOG_EXPIRED",
                "模型目录缓存已过期，请先刷新目录后再提交任务。",
            )
        if availability == "unavailable" and reason in {
            "catalog_unavailable",
            "catalog_empty",
        }:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE",
                "模型目录当前不可用，请刷新目录或先验证高级手填模型。",
            )

    @staticmethod
    def _invalidate_model_catalog(service: dict) -> None:
        had_cache = bool(
            service.get("modelList") or service.get("modelListFetchedAt")
        )
        # Keep the last successful response for diagnostics and recovery, but
        # mark it unusable until the new URL/key has completed a fresh fetch.
        service["modelListLastAttemptAt"] = None
        service["modelListFetchStatus"] = "not_attempted"
        service["modelListLastError"] = None
        service["modelListInvalidated"] = bool(
            service.get("modelListInvalidated") or had_cache
        )

    def _require_service(self, services: Dict[str, dict], service_id: str) -> dict:
        service = services.get(str(service_id or "").strip())
        if not isinstance(service, dict):
            raise DirectServiceError(
                "DIRECT_SERVICE_NOT_FOUND", "未找到指定的直连服务。"
            )
        return service

    @staticmethod
    def _check_revision(service: dict, expected_revision) -> None:
        if expected_revision is None:
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_REQUIRED",
                "缺少 expectedRevision 参数，无法进行并发校验。",
            )
        try:
            exp = int(expected_revision)
        except (ValueError, TypeError):
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_INVALID",
                "expectedRevision 必须是有效整数。",
            )
        current = int(service.get("revision", 1))
        if exp != current:
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
        catalog = self._model_catalog_state(service)
        return {
            "schemaVersion": DIRECT_SERVICE_SCHEMA_VERSION,
            "id": service_id,
            "name": str(service.get("name", "")),
            "serviceBaseUrl": str(service.get("serviceBaseUrl", "")),
            "keyConfigured": self._key_exists(service_id),
            "defaultModel": str(service.get("defaultModel", "")),
            "modelList": list(service.get("modelList", []))
            if isinstance(service.get("modelList"), list)
            else [],
            "modelListFetchedAt": service.get("modelListFetchedAt"),
            "modelListExpiresAt": catalog.get("expiresAt"),
            "modelListStatus": catalog.get("status"),
            "modelListCacheStatus": catalog.get("cacheStatus"),
            "modelListFetchStatus": catalog.get("fetchStatus"),
            "modelListLastAttemptAt": catalog.get("lastAttemptAt"),
            "modelListError": catalog.get("lastError"),
            "modelListInvalidated": bool(service.get("modelListInvalidated", False)),
            "modelListTrusted": bool(catalog.get("trusted", True)),
            "modelListSource": str(service.get("modelListSource", "discovery")),
            "modelCatalog": catalog,
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

    def has_api_key(self, service_id: str) -> bool:
        return self._key_exists(service_id)

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
        try:
            os.makedirs(str(path.parent), mode=0o700, exist_ok=True)
            os.chmod(str(path.parent), 0o700)
        except OSError as exc:
            raise DirectServiceError(
                "DIRECT_SERVICE_KEY_PERSIST_FAILED", f"无法创建或保护密钥目录: {exc}"
            ) from exc

        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            fd = os.open(
                str(temporary),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with open(fd, "w", encoding="utf-8") as f:
                f.write(api_key.strip() + "\n")
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
        except OSError as exc:
            raise DirectServiceError(
                "DIRECT_SERVICE_KEY_PERSIST_FAILED", f"无法写入或保护密钥文件: {exc}"
            ) from exc
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _delete_key(self, service_id: str) -> None:
        path = self._key_path(service_id)
        if path.exists():
            path.unlink()
