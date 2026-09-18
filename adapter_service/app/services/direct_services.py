import copy
import hashlib
import json
import os
import re
import shutil
import socket
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from app.core.config import default_config_path, load_config_payload, save_config_payload
from app.core.runtime_paths import resolve_runtime_paths
from app.core import direct_migration_txn as migration_txn
from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    MAX_TASK_CONTEXT_WINDOW_TOKENS,
    MAX_TASK_MAX_OUTPUT_TOKENS,
    MAX_CONFIGURATION_NAME_LENGTH,
    MIN_TASK_CONTEXT_WINDOW_TOKENS,
    MIN_TASK_MAX_OUTPUT_TOKENS,
    ModelConfigurationError,
    _STORE_LOCK,
    direct_model_input_budget,
    host_for_task,
    normalize_service_base_url,
)
from app.services.word.image_semantics import IMAGE_INPUT_MODES
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


def _service_host(service_base_url: str) -> str:
    try:
        return (urlsplit(str(service_base_url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _binding_matches(record: Any, binding: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    return all(record.get(k) == v for k, v in binding.items())


def _format_review_image_binding(service: dict, selection: dict) -> Dict[str, Any]:
    effective_model = str(
        selection.get("modelName") or service.get("defaultModel") or ""
    ).strip()
    return {
        "configVersion": 1,
        "serviceHost": _service_host(str(service.get("serviceBaseUrl", ""))),
        "accessMethod": ACCESS_DIRECT_MODEL,
        "imageInputMode": str(selection.get("imageInputMode", "disabled")),
        "modelName": effective_model,
    }


def _format_review_format_semantic_binding(service: dict, selection: dict) -> Dict[str, Any]:
    return {
        "serviceId": str(service.get("id", "")),
        "serviceBaseUrl": str(service.get("serviceBaseUrl", "")).rstrip("/"),
        "serviceHost": _service_host(str(service.get("serviceBaseUrl", ""))),
        "modelName": str(selection.get("modelName") or service.get("defaultModel") or "").strip(),
        "temperature": selection.get("temperature"),
        "maxOutputTokens": selection.get("maxOutputTokens"),
        "contextWindowTokens": selection.get("contextWindowTokens"),
        "imageInputMode": selection.get("imageInputMode") or "openai_image_url",
    }


MAX_DIRECT_SERVICES = 5
MAX_DIRECT_SERVICE_NAME_LENGTH = MAX_CONFIGURATION_NAME_LENGTH
DIRECT_SERVICE_SCHEMA_VERSION = "provider.direct_service.v1"
TASK_MODEL_SELECTION_SCHEMA_VERSION = "provider.task_model_selection.v1"
MODEL_LIST_CACHE_TTL_SECONDS = 24 * 60 * 60
LEGACY_COMPAT_TTL_SECONDS = 7 * 24 * 60 * 60
LEGACY_COMPAT_AUTH_REVOKE_CODES = {"DIRECT_SERVICE_AUTH_FAILED"}
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


def _serialized_store_transaction(operation):
    @wraps(operation)
    def wrapper(store, *args, **kwargs):
        with _STORE_LOCK:
            with migration_txn.migration_lock(store.config_path):
                return operation(store, *args, **kwargs)

    return wrapper


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
    _KEY_ROTATION_LISTENERS: List[Callable[[str, str, int], None]] = []

    @classmethod
    def register_key_rotation_listener(
        cls, listener: Callable[[str, str, int], None]
    ) -> None:
        if listener not in cls._KEY_ROTATION_LISTENERS:
            cls._KEY_ROTATION_LISTENERS.append(listener)

    @classmethod
    def unregister_key_rotation_listener(
        cls, listener: Callable[[str, str, int], None]
    ) -> None:
        if listener in cls._KEY_ROTATION_LISTENERS:
            cls._KEY_ROTATION_LISTENERS.remove(listener)

    def _notify_key_rotation(
        self,
        service_id: str,
        old_key_fingerprint: str,
        service_revision: int,
    ) -> None:
        for listener in list(self._KEY_ROTATION_LISTENERS):
            try:
                listener(service_id, old_key_fingerprint, service_revision)
            except Exception:
                pass
        try:
            from app.services.long_task_coordinator import get_long_task_coordinator
            coord = get_long_task_coordinator()
            if coord is not None and hasattr(coord, "invalidate_by_auth"):
                coord.invalidate_by_auth(
                    service_id,
                    old_key_fingerprint,
                    service_revision=service_revision,
                )
        except Exception:
            pass

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
            payload, migration = self._load_with_legacy_direct_migration()
            services = [
                self._sanitize_service(item, payload=payload)
                for item in self._service_map(payload).values()
            ]
            services.sort(key=lambda s: (s.get("createdAt", ""), s["id"]))
            result = {
                "schemaVersion": DIRECT_SERVICE_SCHEMA_VERSION,
                "directServiceCount": len(services),
                "directServices": services,
                "legacyDirectMigration": migration,
                "legacyDirectPending": self._pending_public_payload(payload),
            }
            recovery = migration_txn.recovery_record_write_status_for(self.config_path)
            if recovery.get("recordWriteFailed"):
                result["legacyDirectMigrationRecovery"] = recovery
                result["recoveryRecordWriteFailed"] = True
            return result

    def get_service(self, service_id: str, include_secret: bool = False) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            service = self._require_service(self._service_map(payload), service_id)
            result = self._sanitize_service(service, payload=payload)
            if include_secret:
                result["apiKey"] = self._read_key(service["id"])
            return result

    def resolve_active_task_selection(
        self, task_type: str, include_secret: bool = False
    ) -> Optional[dict]:
        clean_task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            active = payload.get("activeModelConfigurations")
            active_id = str(active.get(clean_task, "")).strip() if isinstance(active, dict) else ""
            if not active_id or active_id not in services:
                return None

            raw_selection = self._selection_map(payload).get(clean_task, {})
            selected_service_id = str(raw_selection.get("serviceId", "")).strip()
            if selected_service_id != active_id:
                raise DirectServiceError(
                    "DIRECT_SERVICE_SELECTION_MISMATCH",
                    "当前直连服务与任务模型选择不一致，请刷新配置后重试。",
                )

            service = self.get_service(active_id, include_secret=include_secret)
            selection = self.get_task_model_selection(clean_task)
            if str(selection.get("serviceId", "")).strip() != active_id:
                raise DirectServiceError(
                    "DIRECT_SERVICE_SELECTION_MISMATCH",
                    "当前直连服务与任务模型选择不一致，请刷新配置后重试。",
                )
            return {
                "activeServiceId": active_id,
                "directService": service,
                "taskModelSelection": selection,
            }

    @migration_txn.serialized
    def _load_with_legacy_direct_migration(self):
        try:
            migration_txn.reconcile_inflight(self.config_path, self.key_dir)
        except migration_txn.MigrationStateError as exc:
            raise DirectServiceError(
                "DIRECT_SERVICE_MIGRATION_STATE_INVALID",
                "旧直连迁移事务状态不可用，请由管理员检查恢复记录。",
            ) from exc
        payload = self._load_payload_recovering()
        configurations = payload.get("modelConfigurations")
        existing_pending = payload.get("legacyDirectPending")
        existing_pending = (
            dict(existing_pending) if isinstance(existing_pending, dict) else {}
        )
        if not isinstance(configurations, dict):
            if existing_pending:
                return payload, self._pending_manual_status(existing_pending, 0)
            return payload, {"status": "not_needed", "migratedConfigurationCount": 0}

        legacy = {
            str(configuration_id): dict(configuration)
            for configuration_id, configuration in configurations.items()
            if isinstance(configuration, dict)
            and str(configuration.get("taskType", "")) in SUPPORTED_WORKFLOW_TASKS
            and str(configuration.get("accessMethod", "")) == ACCESS_DIRECT_MODEL
        }
        if not legacy:
            if existing_pending:
                return payload, self._pending_manual_status(existing_pending, 0)
            return payload, {"status": "not_needed", "migratedConfigurationCount": 0}

        original_payload = copy.deepcopy(payload)
        services = dict(self._service_map(payload))
        identity_to_service = {}
        for service_id, service in services.items():
            service_key = self._read_key(service_id)
            service_url = str(service.get("serviceBaseUrl", "")).strip()
            if service_url and service_key:
                try:
                    norm_url = self._normalize_url(service_url)
                except DirectServiceError:
                    norm_url = service_url
                identity_to_service[
                    (norm_url, self._api_key_fingerprint(service_key))
                ] = service_id

        active_source = payload.get("activeModelConfigurations")
        active = dict(active_source) if isinstance(active_source, dict) else {}
        consumed_ids = set()
        for task_type in SUPPORTED_WORKFLOW_TASKS:
            active_legacy_id = str(active.get(task_type, ""))
            if active_legacy_id in legacy:
                consumed_ids.add(active_legacy_id)
            else:
                task_ids = [
                    configuration_id
                    for configuration_id, configuration in legacy.items()
                    if configuration.get("taskType") == task_type
                ]
                if task_ids:
                    consumed_ids.add(task_ids[-1])

        pending_legacy = {
            configuration_id: copy.deepcopy(configuration)
            for configuration_id, configuration in legacy.items()
            if configuration_id not in consumed_ids
        }
        consumed_legacy = {
            configuration_id: configuration
            for configuration_id, configuration in legacy.items()
            if configuration_id in consumed_ids
        }

        groups = {}
        legacy_keys = {}
        for configuration_id, configuration in consumed_legacy.items():
            api_key_ref = str(configuration.get("apiKeyRef", "")).strip()
            api_key = self._read_legacy_key(api_key_ref)
            legacy_keys[configuration_id] = (api_key_ref, api_key)
            raw_url = str(configuration.get("serviceBaseUrl", "")).strip()
            try:
                normalized_url = self._normalize_url(raw_url) if raw_url else ""
            except DirectServiceError:
                normalized_url = ""
            identity = (
                ("complete", normalized_url, self._api_key_fingerprint(api_key))
                if normalized_url and api_key
                else ("draft", configuration_id)
            )
            groups.setdefault(identity, []).append(configuration_id)

        new_group_count = sum(
            1
            for identity in groups
            if identity[0] == "draft" or identity[1:] not in identity_to_service
        )
        if len(services) + new_group_count > MAX_DIRECT_SERVICES:
            return payload, {
                "status": "restricted",
                "code": "DIRECT_SERVICE_MIGRATION_LIMIT",
                "migratedConfigurationCount": 0,
                "requiredServiceCount": len(services) + new_group_count,
            }

        existing_names = {
            str(service.get("name", "")).strip().casefold()
            for service in services.values()
        }
        configuration_service_ids = {}
        pending_service_keys = []
        created_service_count = 0
        now = _utc_now()

        def unique_name(source):
            base = str(source or "共享直连服务").strip() or "共享直连服务"
            base = base[:MAX_DIRECT_SERVICE_NAME_LENGTH]
            candidate = base
            suffix_number = 2
            while candidate.casefold() in existing_names:
                suffix = " {0}".format(suffix_number)
                candidate = base[: MAX_DIRECT_SERVICE_NAME_LENGTH - len(suffix)] + suffix
                suffix_number += 1
            existing_names.add(candidate.casefold())
            return candidate

        for identity, configuration_ids in groups.items():
            service_id = ""
            if identity[0] == "complete":
                service_id = identity_to_service.get(identity[1:], "")
            group_configurations = [
                consumed_legacy[item_id] for item_id in configuration_ids
            ]
            models = {
                str(item.get("modelName", "")).strip()
                for item in group_configurations
                if str(item.get("modelName", "")).strip()
            }
            if service_id:
                existing = services[service_id]
                union = set(models)
                existing_default = str(existing.get("defaultModel", "")).strip()
                if existing_default:
                    union.add(existing_default)
                if len(union) > 1:
                    existing["defaultModel"] = ""
                    existing["updatedAt"] = now
                source_key = legacy_keys[configuration_ids[0]][1]
                if not source_key:
                    source_key = self._read_key(service_id)
                self._attach_legacy_compatibility(
                    existing,
                    models,
                    str(existing.get("serviceBaseUrl", "")),
                    source_key,
                )
                services[service_id] = existing
            else:
                service_id = "direct_svc_{0}".format(uuid.uuid4().hex[:12])
                first = group_configurations[0]
                if identity[0] == "complete":
                    service_url = identity[1]
                else:
                    raw_url = str(first.get("serviceBaseUrl", "")).strip()
                    try:
                        service_url = self._normalize_url(raw_url) if raw_url else ""
                    except DirectServiceError:
                        service_url = ""
                seeded_models = sorted(models)
                services[service_id] = {
                    "id": service_id,
                    "name": unique_name(first.get("name")),
                    "serviceBaseUrl": service_url,
                    "defaultModel": next(iter(models)) if len(models) == 1 else "",
                    "modelList": seeded_models,
                    "modelListFetchedAt": None,
                    "modelListLastAttemptAt": None,
                    "modelListFetchStatus": "not_attempted",
                    "modelListLastError": None,
                    "modelListInvalidated": False,
                    "modelListTrusted": True,
                    "modelListSource": "legacy_migration" if seeded_models else "none",
                    "revision": 1,
                    "createdAt": now,
                    "updatedAt": now,
                }
                source_key = legacy_keys[configuration_ids[0]][1]
                if source_key:
                    pending_service_keys.append((service_id, source_key))
                created_service_count += 1
                self._attach_legacy_compatibility(
                    services[service_id],
                    models,
                    service_url,
                    source_key,
                )
            for configuration_id in configuration_ids:
                configuration_service_ids[configuration_id] = service_id

        selections = dict(self._selection_map(payload))

        for task_type in SUPPORTED_WORKFLOW_TASKS:
            active_legacy_id = str(active.get(task_type, ""))
            if active_legacy_id in consumed_legacy:
                active_configuration = consumed_legacy[active_legacy_id]
                service_id = configuration_service_ids[active_legacy_id]
                api_key = legacy_keys[active_legacy_id][1]
                service_url = str(services[service_id].get("serviceBaseUrl", ""))
                model_name = str(active_configuration.get("modelName", "")).strip()
                max_output_tokens = active_configuration.get("maxOutputTokens")
                context_window_tokens = active_configuration.get("contextWindowTokens")
                selections[task_type] = {
                    "serviceId": service_id,
                    "modelName": model_name,
                    "temperature": active_configuration.get("temperature"),
                    "maxOutputTokens": max_output_tokens,
                    "contextWindowTokens": context_window_tokens,
                    "imageInputMode": active_configuration.get(
                        "imageInputMode", "disabled"
                    ),
                    "customModel": False,
                    "customModelValidated": False,
                    "updatedAt": now,
                }
                token_limits_valid = self._legacy_token_limits_valid(
                    max_output_tokens, context_window_tokens
                )
                if service_url and api_key and model_name and token_limits_valid:
                    active[task_type] = service_id
                else:
                    active.pop(task_type, None)
            else:
                task_legacies = [
                    (configuration_id, configuration)
                    for configuration_id, configuration in consumed_legacy.items()
                    if configuration.get("taskType") == task_type
                ]
                if task_legacies and task_type not in selections:
                    last_cid, last_cfg = task_legacies[-1]
                    service_id = configuration_service_ids[last_cid]
                    selections[task_type] = {
                        "serviceId": service_id,
                        "modelName": str(last_cfg.get("modelName", "")).strip(),
                        "temperature": last_cfg.get("temperature"),
                        "maxOutputTokens": last_cfg.get("maxOutputTokens"),
                        "contextWindowTokens": last_cfg.get("contextWindowTokens"),
                        "imageInputMode": last_cfg.get("imageInputMode", "disabled"),
                        "customModel": False,
                        "customModelValidated": False,
                        "updatedAt": now,
                    }

        remaining_configurations = {
            configuration_id: configuration
            for configuration_id, configuration in configurations.items()
            if configuration_id not in legacy
        }
        merged_pending = dict(existing_pending)
        merged_pending.update(pending_legacy)
        for pending_id, pending_item in list(merged_pending.items()):
            if isinstance(pending_item, dict):
                normalized_pending = dict(pending_item)
                normalized_pending["revision"] = int(
                    normalized_pending.get("revision", 1) or 1
                )
                merged_pending[pending_id] = normalized_pending
        payload["directServices"] = services
        payload["taskModelSelections"] = selections
        payload["activeModelConfigurations"] = active
        payload["modelConfigurations"] = remaining_configurations
        if merged_pending:
            payload["legacyDirectPending"] = merged_pending
        else:
            payload.pop("legacyDirectPending", None)

        self._commit_legacy_migration(
            original_payload,
            payload,
            pending_service_keys,
            configuration_service_ids,
            legacy_keys,
            active,
        )

        remaining_refs = {
            str(item.get("apiKeyRef", "")).strip()
            for item in remaining_configurations.values()
            if isinstance(item, dict)
        }
        remaining_refs.update(
            str(item.get("apiKeyRef", "")).strip()
            for item in merged_pending.values()
            if isinstance(item, dict)
        )
        workflow_profiles = payload.get("workflowProfiles")
        if isinstance(workflow_profiles, dict):
            remaining_refs.update(
                str(item.get("apiKeyRef", "")).strip()
                for item in workflow_profiles.values()
                if isinstance(item, dict)
            )
        remaining_refs.update(
            "direct_service_{0}".format(service_id) for service_id in services
        )
        for api_key_ref, _ in legacy_keys.values():
            if api_key_ref and api_key_ref not in remaining_refs:
                self._delete_legacy_key(api_key_ref)

        migrated_payload = load_config_payload(self.config_path, self.key_dir)
        if merged_pending:
            return migrated_payload, self._pending_manual_status(
                merged_pending, len(consumed_legacy), created_service_count
            )
        return migrated_payload, {
            "status": "completed",
            "migratedConfigurationCount": len(consumed_legacy),
            "createdServiceCount": created_service_count,
        }

    _load_with_legacy_document_review_migration = _load_with_legacy_direct_migration

    def _legacy_key_path(self, api_key_ref: str) -> Optional[Path]:
        ref = str(api_key_ref or "").strip()
        if not ref or not _SAFE_KEY_REF.fullmatch(ref):
            return None
        return self.key_dir / ref

    def _read_legacy_key(self, api_key_ref: str) -> str:
        path = self._legacy_key_path(api_key_ref)
        if path is None or not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _delete_legacy_key(self, api_key_ref: str) -> None:
        path = self._legacy_key_path(api_key_ref)
        if path is not None and path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def _pre_migration_backup_path(self) -> Path:
        return Path(str(self.config_path) + ".pre-direct-migration")

    def _migration_recovery_record_path(self) -> Path:
        return self.config_path.with_name("adapter-direct-migration-recovery.json")

    @staticmethod
    def _pending_manual_status(
        pending, migrated_count, created_service_count=0
    ) -> dict:
        status = {
            "status": "pending_manual",
            "code": "DIRECT_SERVICE_MIGRATION_PENDING_PROFILES",
            "migratedConfigurationCount": migrated_count,
            "pendingConfigurationCount": len(pending),
        }
        if created_service_count:
            status["createdServiceCount"] = created_service_count
        return status

    def _sanitize_pending_item(self, config_id: str, configuration: dict) -> dict:
        ref = str(configuration.get("apiKeyRef", "")).strip()
        key = self._read_legacy_key(ref)
        return {
            "id": str(config_id),
            "name": str(configuration.get("name", "")),
            "taskType": str(configuration.get("taskType", "")),
            "serviceBaseUrl": str(configuration.get("serviceBaseUrl", "")),
            "modelName": str(configuration.get("modelName", "")),
            "temperature": configuration.get("temperature"),
            "maxOutputTokens": configuration.get("maxOutputTokens"),
            "contextWindowTokens": configuration.get("contextWindowTokens"),
            "imageInputMode": configuration.get("imageInputMode", "disabled"),
            "keyConfigured": bool(key),
            "apiKeyFingerprint": self._api_key_fingerprint(key) if key else "",
            "revision": int(configuration.get("revision", 1) or 1),
        }

    def _pending_map(self, payload: dict) -> dict:
        pending = payload.get("legacyDirectPending")
        return dict(pending) if isinstance(pending, dict) else {}

    def _pending_public_payload(self, payload: dict) -> dict:
        items = [
            self._sanitize_pending_item(config_id, configuration)
            for config_id, configuration in self._pending_map(payload).items()
            if isinstance(configuration, dict)
        ]
        return {"items": items, "pendingConfigurationCount": len(items)}

    def list_legacy_pending(self) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            return self._pending_public_payload(payload)

    def _require_pending(self, payload: dict, config_id: str) -> dict:
        pending = self._pending_map(payload)
        configuration = pending.get(config_id)
        if not isinstance(configuration, dict):
            raise DirectServiceError(
                "DIRECT_SERVICE_PENDING_NOT_FOUND",
                "未找到待处理的旧直连档案。",
            )
        return configuration

    def _referenced_key_names(self, payload: dict) -> set:
        names = set()
        for bucket_name in ("modelConfigurations", "legacyDirectPending", "workflowProfiles"):
            bucket = payload.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            for item in bucket.values():
                if isinstance(item, dict):
                    ref = str(item.get("apiKeyRef", "")).strip()
                    if ref:
                        names.add(ref)
        for service_id in self._service_map(payload):
            names.add("direct_service_{0}".format(service_id))
        return names

    @_serialized_store_transaction
    def migrate_legacy_pending(
        self,
        config_id: str,
        rebuild: bool = False,
        expected_revision: Optional[int] = None,
    ) -> dict:
        clean_id = str(config_id or "").strip()
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            original_payload = copy.deepcopy(payload)
            configuration = dict(self._require_pending(payload, clean_id))
            self._check_pending_revision(configuration, expected_revision)
            services_before = self._service_map(payload)
            service_ids_before = set(services_before)
            api_key_ref = str(configuration.get("apiKeyRef", "")).strip()
            api_key = self._read_legacy_key(api_key_ref)
            raw_url = str(configuration.get("serviceBaseUrl", "")).strip()
            try:
                normalized = self._normalize_url(raw_url) if raw_url else ""
            except DirectServiceError:
                normalized = ""
            fingerprint = self._api_key_fingerprint(api_key) if api_key else ""
            matching_service_id = ""
            if normalized and fingerprint:
                for service_id, service in services_before.items():
                    if str(service.get("serviceBaseUrl", "")) != normalized:
                        continue
                    existing_key = self._read_key(service_id)
                    if self._api_key_fingerprint(existing_key) == fingerprint:
                        matching_service_id = service_id
                        break
            if len(services_before) >= MAX_DIRECT_SERVICES and (
                rebuild or not matching_service_id
            ):
                raise DirectServiceError(
                    "DIRECT_SERVICE_LIMIT",
                    "最多只能保存 {0} 份共享直连服务。".format(MAX_DIRECT_SERVICES),
                )

            if rebuild:
                pending = self._pending_map(payload)
                pending.pop(clean_id, None)
                if pending:
                    payload["legacyDirectPending"] = pending
                else:
                    payload.pop("legacyDirectPending", None)
                now = _utc_now()
                service_id = "direct_svc_{0}".format(uuid.uuid4().hex[:12])
                model_name = str(configuration.get("modelName", "")).strip()
                existing_names = {
                    str(item.get("name", "")).strip().casefold()
                    for item in services_before.values()
                }
                base_name = str(configuration.get("name") or "共享直连服务").strip()
                base_name = (base_name or "共享直连服务")[:MAX_DIRECT_SERVICE_NAME_LENGTH]
                service_name = base_name
                suffix_number = 2
                while service_name.casefold() in existing_names:
                    suffix = " {0}".format(suffix_number)
                    service_name = (
                        base_name[: MAX_DIRECT_SERVICE_NAME_LENGTH - len(suffix)] + suffix
                    )
                    suffix_number += 1
                services = dict(services_before)
                services[service_id] = {
                    "id": service_id,
                    "name": service_name,
                    "serviceBaseUrl": normalized,
                    "defaultModel": model_name,
                    "modelList": [model_name] if model_name else [],
                    "modelListFetchedAt": None,
                    "modelListLastAttemptAt": None,
                    "modelListFetchStatus": "not_attempted",
                    "modelListLastError": None,
                    "modelListInvalidated": False,
                    "modelListTrusted": True,
                    "modelListSource": "legacy_migration" if model_name else "none",
                    "revision": 1,
                    "createdAt": now,
                    "updatedAt": now,
                }
                self._attach_legacy_compatibility(
                    services[service_id],
                    {model_name} if model_name else set(),
                    normalized,
                    api_key,
                )
                payload["directServices"] = services
                self._commit_legacy_migration(
                    original_payload,
                    payload,
                    [(service_id, api_key)] if api_key else [],
                    {clean_id: service_id},
                    {clean_id: (api_key_ref, api_key)},
                    {},
                )
                if api_key_ref and api_key_ref not in self._referenced_key_names(payload):
                    self._delete_legacy_key(api_key_ref)
                return self._sanitize_service(services[service_id], payload=payload)

            pending = self._pending_map(payload)
            pending.pop(clean_id, None)
            if pending:
                payload["legacyDirectPending"] = pending
            else:
                payload.pop("legacyDirectPending", None)
            configurations = dict(payload.get("modelConfigurations") or {})
            if not isinstance(payload.get("modelConfigurations"), dict):
                configurations = {}
            configurations[clean_id] = configuration
            payload["modelConfigurations"] = configurations
            save_config_payload(payload, self.config_path)
            try:
                result = self.list_services()
            except BaseException:
                migration_txn.write_json_atomic(self.config_path, original_payload)
                raise
        if result["legacyDirectMigration"].get("status") == "restricted":
            migration_txn.write_json_atomic(self.config_path, original_payload)
            raise DirectServiceError(
                "DIRECT_SERVICE_MIGRATION_LIMIT",
                "迁移将超过共享直连服务上限。",
            )
        pending_after = result.get("legacyDirectPending") or {}
        pending_items = (
            pending_after.get("items")
            if isinstance(pending_after, dict)
            else pending_after
        )
        pending_ids = {item.get("id") for item in pending_items or []}
        if clean_id in pending_ids:
            raise DirectServiceError(
                "DIRECT_SERVICE_MIGRATION_FAILED",
                "待处理档案未能迁移。",
            )
        services = result.get("directServices") or []
        if not services:
            raise DirectServiceError(
                "DIRECT_SERVICE_MIGRATION_FAILED",
                "待处理档案未能迁移。",
            )
        raw_after = load_config_payload(self.config_path, self.key_dir)
        raw_services_after = self._service_map(raw_after)
        candidates = [
            service
            for service in services
            if str(service.get("id") or "") not in service_ids_before
        ]
        if not candidates:
            candidates = services
        for service in candidates:
            service_id = str(service.get("id") or "")
            raw_service = raw_services_after.get(service_id, {})
            service_url = str(raw_service.get("serviceBaseUrl") or "")
            service_fingerprint = self._api_key_fingerprint(
                self._read_key(service_id)
            )
            if normalized and service_url != normalized:
                continue
            if fingerprint and service_fingerprint != fingerprint:
                continue
            if not normalized and not fingerprint and len(candidates) != 1:
                continue
            if normalized and not fingerprint and service_id in service_ids_before:
                continue
            if fingerprint and not normalized and service_id in service_ids_before:
                continue
            return service
        raise DirectServiceError(
            "DIRECT_SERVICE_MIGRATION_FAILED",
            "无法确认待处理档案对应的共享直连服务。",
        )

    def rebuild_legacy_pending(
        self, config_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        return self.migrate_legacy_pending(
            config_id, rebuild=True, expected_revision=expected_revision
        )

    @_serialized_store_transaction
    def abandon_legacy_pending(
        self, config_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        clean_id = str(config_id or "").strip()
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            configuration = dict(self._require_pending(payload, clean_id))
            self._check_pending_revision(configuration, expected_revision)
            pending = self._pending_map(payload)
            pending.pop(clean_id, None)
            if pending:
                payload["legacyDirectPending"] = pending
            else:
                payload.pop("legacyDirectPending", None)
            save_config_payload(payload, self.config_path)
            ref = str(configuration.get("apiKeyRef", "")).strip()
            remaining = self._referenced_key_names(payload)
            if ref and ref not in remaining:
                self._delete_legacy_key(ref)
            return {"id": clean_id}

    @staticmethod
    def _check_pending_revision(configuration: dict, expected_revision) -> None:
        if expected_revision is None:
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_REQUIRED",
                "必须提供 expectedRevision。",
            )
        try:
            current = int(configuration.get("revision", 1) or 1)
            expected = int(expected_revision)
        except (TypeError, ValueError) as exc:
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_CONFLICT",
                "待处理档案版本无效，请刷新后重试。",
            ) from exc
        if current != expected:
            raise DirectServiceError(
                "DIRECT_SERVICE_REVISION_CONFLICT",
                "待处理档案已变化，请刷新后重试。",
            )

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / ".{0}.{1}.tmp".format(
            destination.name, uuid.uuid4().hex
        )
        try:
            shutil.copyfile(str(source), str(temporary))
            os.replace(str(temporary), str(destination))
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        migration_txn.write_json_atomic(path, payload)

    def _write_migration_recovery_record(self, reason: str) -> None:
        migration_txn.write_recovery_record(self.config_path, reason)

    def _load_payload_recovering(self) -> dict:
        return load_config_payload(self.config_path, self.key_dir)

    def _restore_pre_migration_backup(self) -> None:
        restored = migration_txn.restore_snapshot_tree(
            migration_txn.snapshot_dir(self.config_path) / "pre",
            self.config_path,
            self.key_dir,
        )
        if restored is not None:
            return
        backup = self._pre_migration_backup_path()
        if backup.is_file():
            self._copy_file(backup, self.config_path)

    def _verify_migrated_payload(
        self,
        verified: dict,
        read_key,
        configuration_service_ids: dict,
        legacy_keys: dict,
        active: dict,
    ) -> None:
        verified_services = self._service_map(verified)
        for configuration_id, service_id in configuration_service_ids.items():
            if service_id not in verified_services:
                raise DirectServiceError(
                    "DIRECT_SERVICE_MIGRATION_FAILED", "迁移后的直连服务校验失败。"
                )
            source_key = legacy_keys[configuration_id][1]
            if source_key and self._api_key_fingerprint(
                read_key(service_id)
            ) != self._api_key_fingerprint(source_key):
                raise DirectServiceError(
                    "DIRECT_SERVICE_MIGRATION_FAILED", "迁移后的 API Key 校验失败。"
                )
        for task_type in SUPPORTED_WORKFLOW_TASKS:
            if task_type in active and str(active[task_type]).startswith("direct_svc_"):
                expected_service = active[task_type]
                selected_id = str(
                    self._selection_map(verified)
                    .get(task_type, {})
                    .get("serviceId", "")
                )
                if selected_id != expected_service:
                    raise DirectServiceError(
                        "DIRECT_SERVICE_MIGRATION_FAILED",
                        "迁移后的任务 {0} 绑定校验失败。".format(task_type),
                    )

    def _commit_legacy_migration(
        self,
        original_payload: dict,
        payload: dict,
        pending_service_keys,
        configuration_service_ids: dict,
        legacy_keys: dict,
        active: dict,
    ) -> None:
        original_bytes = (
            self.config_path.read_bytes()
            if self.config_path.exists()
            else b"{}\n"
        )
        extra_key_names = [
            api_key_ref
            for api_key_ref, _ in legacy_keys.values()
            if api_key_ref
        ]
        pre_meta = migration_txn.write_pre_snapshot(
            self.config_path,
            self.key_dir,
            original_bytes,
            extra_key_names,
        )
        stage_root = self.key_dir.parent / ".direct-migration-stage-{0}".format(
            uuid.uuid4().hex
        )
        stage_keys = stage_root / "keys"
        stage_config = stage_root / "adapter.json"
        newly_written_service_ids = []
        new_key_refs = [
            "direct_service_{0}".format(service_id)
            for service_id, _ in pending_service_keys
        ]
        journal = {
            "phase": migration_txn.PHASE_STAGING,
            "keyDir": str(self.key_dir),
            "configPath": str(self.config_path),
            "stagingDir": str(stage_root),
            "preConfigSha256": pre_meta["configSha256"],
            "newKeyRefs": new_key_refs,
        }
        migration_txn.write_journal(self.config_path, journal)
        try:
            stage_root.mkdir(parents=True, mode=0o700, exist_ok=True)
            os.chmod(str(stage_root), 0o700)
            stage_store = DirectServiceStore(stage_config, stage_keys)
            self._write_json_atomic(stage_config, payload)
            for service_id, source_key in pending_service_keys:
                stage_store._write_key(service_id, source_key)

            def read_staged_or_live(service_id):
                staged_key = stage_store._read_key(service_id)
                if staged_key:
                    return staged_key
                return self._read_key(service_id)

            staged_payload = json.loads(stage_config.read_text(encoding="utf-8"))
            self._verify_migrated_payload(
                staged_payload,
                read_staged_or_live,
                configuration_service_ids,
                legacy_keys,
                active,
            )
            journal["phase"] = migration_txn.PHASE_COMMITTING
            journal["stagedConfigSha256"] = migration_txn.sha256_file(stage_config)
            migration_txn.write_journal(self.config_path, journal)
            for service_id, source_key in pending_service_keys:
                newly_written_service_ids.append(service_id)
                self._write_key(service_id, source_key)
            migration_txn.write_json_atomic(self.config_path, payload)
            verified = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._verify_migrated_payload(
                verified,
                self._read_key,
                configuration_service_ids,
                legacy_keys,
                active,
            )
            migration_txn.write_committed_snapshot(self.config_path, self.key_dir)
            journal["phase"] = migration_txn.PHASE_COMMITTED
            migration_txn.write_journal(self.config_path, journal)
            migration_txn.finalize_committed(self.config_path)
        except BaseException:
            self._restore_pre_migration_backup()
            if not (migration_txn.snapshot_dir(self.config_path) / "pre" / "adapter.json").is_file():
                if not self._pre_migration_backup_path().is_file():
                    try:
                        save_config_payload(original_payload, self.config_path)
                    except Exception:
                        pass
            for service_id in newly_written_service_ids:
                try:
                    self._delete_key(service_id)
                except Exception:
                    pass
            raise
        finally:
            shutil.rmtree(str(stage_root), ignore_errors=True)

    @staticmethod
    def _legacy_token_limits_valid(max_output_tokens, context_window_tokens) -> bool:
        try:
            max_output = (
                None if max_output_tokens in (None, "") else int(max_output_tokens)
            )
            context_window = (
                None
                if context_window_tokens in (None, "")
                else int(context_window_tokens)
            )
        except (TypeError, ValueError):
            return False
        if max_output is not None and max_output < 0:
            return False
        if context_window is not None and context_window < 0:
            return False
        max_output = None if max_output == 0 else max_output
        context_window = None if context_window == 0 else context_window
        return not (
            max_output is not None
            and context_window is not None
            and direct_model_input_budget(context_window, max_output)[0] <= 0
        )

    @_serialized_store_transaction
    def create_service(
        self,
        name: str,
        service_base_url: str = "",
        default_model: str = "",
        api_key: Optional[str] = None,
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
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

    @_serialized_store_transaction
    def update_service(
        self,
        service_id: str,
        name: str,
        expected_revision: int,
        service_base_url: str = "",
        default_model: str = "",
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
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

    @_serialized_store_transaction
    def delete_service(
        self,
        service_id: str,
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            self._check_revision(service, expected_revision)

            referenced = self._get_referenced_tasks(payload, service_id)
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

    @_serialized_store_transaction
    def replace_api_key(
        self,
        service_id: str,
        api_key: str,
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
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
            old_fp = (
                self._api_key_fingerprint(prior_key)
                if had_prior_key and prior_key
                else ""
            )
            old_revision = int(service.get("revision", 1))

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
            if old_fp:
                self._notify_key_rotation(service_id, old_fp, old_revision)
            return self._sanitize_service(service, payload=payload)

    @_serialized_store_transaction
    def clear_api_key(
        self,
        service_id: str,
        expected_revision: int,
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

            self._check_revision(service, expected_revision)

            prior_key = self._read_key(service_id)
            had_prior_key = self._key_exists(service_id)
            old_fp = (
                self._api_key_fingerprint(prior_key)
                if had_prior_key and prior_key
                else ""
            )
            old_revision = int(service.get("revision", 1))

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
            if old_fp:
                self._notify_key_rotation(service_id, old_fp, old_revision)
            return self._sanitize_service(service, payload=payload)

    @_serialized_store_transaction
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
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            service = self._require_service(services, service_id)

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

    @_serialized_store_transaction
    def _record_model_catalog_failure(
        self,
        service_id: str,
        error: DirectServiceError,
        expected_revision: Optional[int] = None,
    ) -> None:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
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
            if error.code in LEGACY_COMPAT_AUTH_REVOKE_CODES:
                proof = service.get("legacyCompatibility")
                if isinstance(proof, dict):
                    proof["revoked"] = True
                    proof["revokeReason"] = error.code
                    service["legacyCompatibility"] = proof
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

    @_serialized_store_transaction
    def refresh_models(
        self, service_id: str, expected_revision: Optional[int] = None
    ) -> dict:
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            service = self._require_service(services, service_id)
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
                "authenticationVerified": True,
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
            authentication_verified = exc.code != "DIRECT_SERVICE_MODELS_UNAVAILABLE"
            return {
                "success": True,
                "validationScope": "service",
                "serviceId": service["id"],
                "serviceName": service.get("name", ""),
                "reachable": True,
                "authenticated": True if authentication_verified else None,
                "authenticationVerified": authentication_verified,
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

    @_serialized_store_transaction
    def activate_direct_service(
        self,
        service_id: str,
        task_type: str,
        task_model_selection: Optional[dict] = None,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
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
            if task_model_selection is not None:
                if not isinstance(task_model_selection, dict):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_PARAM_INVALID",
                        "任务模型选择必须是对象。",
                    )
                requested_service_id = str(
                    task_model_selection.get("serviceId", "")
                ).strip()
                if requested_service_id and requested_service_id != service_id:
                    raise DirectServiceError(
                        "DIRECT_SERVICE_SELECTION_MISMATCH",
                        "任务模型选择引用的直连服务与待激活服务不一致。",
                    )
                task_sel = self._build_task_model_selection_record(
                    payload,
                    services,
                    clean_task,
                    service_id=service_id,
                    model_name=task_model_selection.get("modelName", ""),
                    temperature=task_model_selection.get("temperature"),
                    max_output_tokens=task_model_selection.get("maxOutputTokens"),
                    context_window_tokens=task_model_selection.get(
                        "contextWindowTokens"
                    ),
                    image_input_mode=task_model_selection.get("imageInputMode"),
                    custom_model=bool(task_model_selection.get("customModel", False)),
                )
            else:
                task_sel = dict(selections.get(clean_task, {}))
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
                payload,
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
            payload, _ = self._load_with_legacy_direct_migration()
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

                image_mode = str(
                    raw.get("imageInputMode")
                    or ("openai_image_url" if task == "word.format_review" else "disabled")
                )
                image_authorization = None
                image_validation = None
                image_readiness = None
                format_semantic_validation = None
                format_semantic_readiness = None

                if task == "word.format_review":
                    img_binding = self.image_validation_binding(service, raw)
                    raw_auth = raw.get("imageExternalAuthorization")
                    if image_mode == "disabled" or not isinstance(raw_auth, dict):
                        image_authorization = None
                    else:
                        is_stale = (
                            not _binding_matches(raw_auth, img_binding)
                            or not service
                            or not self._key_exists(service_id)
                        )
                        image_authorization = {**raw_auth, "stale": is_stale}

                    raw_val = raw.get("imageSemanticValidation")
                    if not isinstance(raw_val, dict):
                        image_validation = None
                    else:
                        is_stale = (
                            not _binding_matches(raw_val, img_binding)
                            or not service
                            or not self._key_exists(service_id)
                        )
                        image_validation = {**raw_val, "stale": is_stale}

                    if image_mode not in IMAGE_INPUT_MODES or image_mode == "disabled":
                        image_readiness = {
                            "code": "disabled",
                            "ready": False,
                            "label": "图片输入已禁用。",
                        }
                    elif (
                        not image_authorization
                        or not image_authorization.get("authorized")
                        or image_authorization.get("stale")
                    ):
                        image_readiness = {
                            "code": "authorization_required",
                            "ready": False,
                            "label": "请授权当前任务向所选模型服务发送图片。",
                        }
                    elif (
                        not image_validation
                        or not image_validation.get("validated")
                        or image_validation.get("stale")
                    ):
                        image_readiness = {
                            "code": "validation_required",
                            "ready": False,
                            "label": "请使用无敏感测试图片完成视觉能力验证。",
                        }
                    else:
                        image_readiness = {
                            "code": "ready",
                            "ready": True,
                            "label": "图片外发授权和视觉能力验证均有效。",
                        }

                    fmt_binding = self.format_validation_binding(service, raw)
                    raw_fmt_val = raw.get("formatSemanticValidation")
                    draft_validation = payload.get("formatSemanticDraftValidations", {}).get(task)
                    if _binding_matches(draft_validation, fmt_binding):
                        raw_fmt_val = draft_validation
                    if not isinstance(raw_fmt_val, dict):
                        format_semantic_validation = None
                    else:
                        is_stale = (
                            not _binding_matches(raw_fmt_val, fmt_binding)
                            or not service
                            or not self._key_exists(service_id)
                        )
                        format_semantic_validation = {**raw_fmt_val, "stale": is_stale}

                    if (
                        format_semantic_validation
                        and bool(format_semantic_validation.get("success"))
                        and not format_semantic_validation.get("stale")
                    ):
                        format_semantic_readiness = {
                            "code": "ready",
                            "label": "格式语义协议已验证，格式审查可调用模型直连。",
                        }
                    else:
                        format_semantic_readiness = {
                            "code": "validation_required",
                            "label": "格式语义协议尚未验证，格式审查仅运行确定性规则。",
                        }

                limited_review_ready = None
                full_document_review_ready = None
                full_document_review_readiness = None

                if task == "word.document_review":
                    has_service = bool(service)
                    has_url = bool(service and service.get("serviceBaseUrl"))
                    has_key = bool(self._key_exists(service_id)) if service else False
                    has_model = bool(effective_model)
                    config_complete = bool(has_service and has_url and has_key and has_model)
                    limited_review_ready = bool(config_complete and model_available)

                    if not config_complete:
                        full_document_review_readiness = {
                            "code": "configuration_incomplete",
                            "label": "模型配置不完整。",
                        }
                    elif not model_available:
                        full_document_review_readiness = {
                            "code": "model_unavailable",
                            "label": unavailable_reason or "所选模型当前不可用。",
                        }
                    elif raw.get("maxOutputTokens") is None:
                        full_document_review_readiness = {
                            "code": "explicit_output_tokens_required",
                            "label": "仅限量审查可用：请显式设置最大输出 Token。",
                        }
                    elif raw.get("contextWindowTokens") is None:
                        full_document_review_readiness = {
                            "code": "explicit_context_tokens_required",
                            "label": "仅限量审查可用：请显式设置上下文容量。",
                        }
                    elif int(raw.get("maxOutputTokens") or 0) < 2048:
                        full_document_review_readiness = {
                            "code": "output_tokens_too_small",
                            "label": "仅限量审查可用：全篇审查至少需要 2048 输出 Token。",
                        }
                    elif direct_model_input_budget(
                        int(raw.get("contextWindowTokens")),
                        int(raw.get("maxOutputTokens")),
                    )[0] <= 0:
                        full_document_review_readiness = {
                            "code": "token_budget_invalid",
                            "label": "仅限量审查可用：上下文容量不足以容纳输出 Token 与安全余量。",
                        }
                    else:
                        full_document_review_readiness = {
                            "code": "ready",
                            "label": "限量审查与全篇审查均可用。",
                        }
                    full_document_review_ready = bool(
                        full_document_review_readiness["code"] == "ready"
                    )

                entry = {
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
                    "contextWindowTokensExplicit": raw.get("contextWindowTokens") is not None,
                    "imageInputMode": image_mode,
                    "imageExternalAuthorization": image_authorization,
                    "imageSemanticValidation": image_validation,
                    "imageSemanticReadiness": image_readiness,
                    "formatSemanticValidation": format_semantic_validation,
                    "formatSemanticReadiness": format_semantic_readiness,
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
                    "streamingCapability": self._evaluate_streaming_capability(
                        payload, service, effective_model
                    ),
                    "updatedAt": str(raw.get("updatedAt", "")),
                }
                if task == "word.document_review":
                    entry["limitedReviewReady"] = limited_review_ready
                    entry["fullDocumentReviewReady"] = full_document_review_ready
                    entry["fullDocumentReviewReadiness"] = full_document_review_readiness
                results.append(entry)

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

    @_serialized_store_transaction
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
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            selections = self._selection_map(payload)
            record = self._build_task_model_selection_record(
                payload,
                services,
                clean_task,
                service_id=service_id,
                model_name=model_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                context_window_tokens=context_window_tokens,
                image_input_mode=image_input_mode,
                custom_model=custom_model,
            )
            selections[clean_task] = record
            payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)

            return self.get_task_model_selection(clean_task)

    def _build_task_model_selection_record(
        self,
        payload: dict,
        services: dict,
        task_type: str,
        service_id: str = "",
        model_name: str = "",
        temperature=None,
        max_output_tokens=None,
        context_window_tokens=None,
        image_input_mode=None,
        custom_model: bool = False,
    ) -> dict:
        clean_service_id = str(service_id or "").strip()
        if clean_service_id and clean_service_id not in services:
            raise DirectServiceError(
                "DIRECT_SERVICE_NOT_FOUND", "引用的直连服务不存在。"
            )

        clean_model = self._validate_model_name(model_name)
        clean_temp = self._validate_temperature(temperature)
        clean_max_output = self._validate_optional_token_limit(
            max_output_tokens, "最大输出 Token"
        )
        clean_context = self._validate_optional_token_limit(
            context_window_tokens, "上下文容量"
        )
        if (
            clean_max_output is not None
            and clean_context is not None
            and direct_model_input_budget(clean_context, clean_max_output)[0] <= 0
        ):
            raise DirectServiceError(
                "DIRECT_SERVICE_TOKEN_BUDGET_INVALID",
                "上下文容量必须大于最大输出 Token 与安全余量之和。",
            )
        clean_image_mode = self._validate_image_input_mode(
            task_type, image_input_mode
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
                task_type,
                service,
                clean_model,
            )
        )
        existing_selections = payload.get("taskModelSelections", {})
        existing = (
            existing_selections.get(task_type, {})
            if isinstance(existing_selections, dict)
            else {}
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
        if task_type == "word.format_review":
            record["imageExternalAuthorization"] = (
                existing.get("imageExternalAuthorization") if clean_image_mode != "disabled" else None
            )
            record["imageSemanticValidation"] = existing.get("imageSemanticValidation")
            record["formatSemanticValidation"] = existing.get("formatSemanticValidation")
            draft_validation = payload.get("formatSemanticDraftValidations", {}).get(task_type)
            if _binding_matches(draft_validation, self.format_validation_binding(service, record)):
                record["formatSemanticValidation"] = draft_validation

        return record

    @_serialized_store_transaction
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
            payload, _ = self._load_with_legacy_direct_migration()
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

    def _evaluate_streaming_capability(
        self, payload: dict, service: Optional[dict], model_name: str
    ) -> dict:
        clean_model = str(model_name or "").strip()
        if not service or not clean_model:
            return {
                "status": "not_checked",
                "serviceId": service["id"] if service else "",
                "serviceRevision": int(service.get("revision", 1)) if service else None,
                "serviceBaseUrl": normalize_service_base_url(service.get("serviceBaseUrl", "")) if service else "",
                "apiKeyFingerprint": (
                    self._api_key_fingerprint(self._read_key(service["id"]))
                    if (service and self._key_exists(service.get("id")))
                    else ""
                ),
                "modelName": clean_model,
                "testedAt": None,
            }
        key = f"{service['id']}::{clean_model}"
        capabilities = payload.get("streamingCapabilities")
        record = capabilities.get(key) if isinstance(capabilities, dict) else None
        current_revision = int(service.get("revision", 1))
        current_url = normalize_service_base_url(service.get("serviceBaseUrl", ""))
        current_fingerprint = (
            self._api_key_fingerprint(self._read_key(service["id"]))
            if self._key_exists(service.get("id"))
            else ""
        )
        if not record or not isinstance(record, dict):
            return {
                "status": "not_checked",
                "serviceId": service["id"],
                "serviceRevision": current_revision,
                "serviceBaseUrl": current_url,
                "apiKeyFingerprint": current_fingerprint,
                "modelName": clean_model,
                "testedAt": None,
            }
        is_match = (
            int(record.get("serviceRevision", 0)) == current_revision
            and str(record.get("serviceBaseUrl", "")).strip() == current_url.strip()
            and str(record.get("apiKeyFingerprint", "")) == current_fingerprint
            and str(record.get("modelName", "")).strip() == clean_model
        )
        status = str(record.get("status", "not_checked")) if is_match else "stale"
        return {
            "status": status,
            "serviceId": service["id"],
            "serviceRevision": current_revision,
            "serviceBaseUrl": current_url,
            "apiKeyFingerprint": current_fingerprint,
            "modelName": clean_model,
            "testedAt": record.get("testedAt"),
        }

    @_serialized_store_transaction
    def record_streaming_capability(
        self,
        service_id: str,
        model_name: str,
        status: str,
        expected_binding: Optional[dict] = None,
    ) -> dict:
        clean_service_id = str(service_id or "").strip()
        clean_model = self._validate_model_name(model_name)
        if not clean_model:
            raise DirectServiceError(
                "DIRECT_SERVICE_MODEL_REQUIRED", "模型名称不能为空。"
            )
        if status not in {"validated", "unsupported"}:
            raise DirectServiceError(
                "DIRECT_SERVICE_PARAM_INVALID",
                "流式能力状态必须为 validated 或 unsupported。",
            )
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            service = self._require_service(services, clean_service_id)
            if not self._key_exists(service["id"]):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_REQUIRED",
                    "直连服务未配置 API Key，无法记录流式能力。",
                )
            current_revision = int(service.get("revision", 1))
            current_url = normalize_service_base_url(service.get("serviceBaseUrl", ""))
            current_fingerprint = self._api_key_fingerprint(
                self._read_key(service["id"])
            )
            if expected_binding is not None:
                if (
                    expected_binding.get("serviceRevision") is not None
                    and int(expected_binding.get("serviceRevision"))
                    != current_revision
                ):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_CONFIG_CHANGED",
                        "服务版本在验证期间发生变化，请重新验证。",
                    )
                if (
                    expected_binding.get("serviceBaseUrl") is not None
                    and str(expected_binding.get("serviceBaseUrl")).strip()
                    != current_url.strip()
                ):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_CONFIG_CHANGED",
                        "服务地址在验证期间发生变化，请重新验证。",
                    )
                if (
                    expected_binding.get("apiKeyFingerprint") is not None
                    and str(expected_binding.get("apiKeyFingerprint"))
                    != current_fingerprint
                ):
                    raise DirectServiceError(
                        "DIRECT_SERVICE_CONFIG_CHANGED",
                        "API Key 在验证期间发生变化，请重新验证。",
                    )
            capabilities = payload.setdefault("streamingCapabilities", {})
            if (
                len(capabilities) >= 50
                and f"{clean_service_id}::{clean_model}" not in capabilities
            ):
                oldest_key = min(
                    capabilities.keys(),
                    key=lambda k: str(capabilities[k].get("testedAt", "")),
                )
                capabilities.pop(oldest_key, None)
            record = {
                "serviceId": service["id"],
                "serviceRevision": current_revision,
                "serviceBaseUrl": current_url,
                "apiKeyFingerprint": current_fingerprint,
                "modelName": clean_model,
                "status": status,
                "testedAt": _utc_now(),
            }
            capabilities[f"{clean_service_id}::{clean_model}"] = record
            save_config_payload(payload, self.config_path)
            return dict(record)

    @_serialized_store_transaction
    def set_image_external_authorization(
        self, task_type: str, authorized: bool, expected_selection: Optional[dict] = None,
        expected_service_revision: Optional[int] = None,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        if clean_task != "word.format_review":
            raise DirectServiceError(
                "DIRECT_SERVICE_TASK_UNSUPPORTED",
                f"任务类型 {task_type} 不支持图片外发授权。",
            )
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            selections = self._selection_map(payload)
            raw = selections.get(clean_task, {})
            service_id = str(raw.get("serviceId", "")).strip()
            service = self._require_service(services, service_id)
            if expected_service_revision is not None:
                self._check_revision(service, expected_service_revision)
            if expected_selection is not None:
                expected_service = services.get(str(expected_selection.get("serviceId", "")), {})
                if self.image_validation_binding(service, raw) != self.image_validation_binding(expected_service, expected_selection):
                    raise DirectServiceError("DIRECT_SERVICE_CONFIG_CHANGED", "任务选择已变化，请刷新后重新确认图片授权。")
            mode = str(raw.get("imageInputMode", "disabled"))
            if authorized and mode == "disabled":
                raise DirectServiceError(
                    "IMAGE_INPUT_MODE_REQUIRED",
                    "启用图片外发授权前必须选择图片输入模式。",
                )
            if not self._key_exists(service_id):
                raise DirectServiceError(
                    "DIRECT_SERVICE_KEY_REQUIRED",
                    "直连服务未配置 API Key，无法授权图片外发。",
                )
            binding = self.image_validation_binding(service, raw)
            raw["imageExternalAuthorization"] = {
                "authorized": bool(authorized),
                **binding,
            }
            raw["updatedAt"] = _utc_now()
            selections[clean_task] = raw
            payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)
            return self.get_task_model_selection(clean_task)

    @_serialized_store_transaction
    def record_image_semantic_validation(
        self, task_type: str, summary: dict, expected_binding: Optional[dict] = None,
        expected_authorization: Optional[dict] = None,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        if clean_task != "word.format_review":
            raise DirectServiceError(
                "DIRECT_SERVICE_TASK_UNSUPPORTED",
                f"任务类型 {task_type} 不支持视觉能力验证。",
            )
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            selections = self._selection_map(payload)
            raw = selections.get(clean_task, {})
            service_id = str(raw.get("serviceId", "")).strip()
            service = self._require_service(services, service_id)
            binding = self.image_validation_binding(service, raw)
            if expected_binding is not None and (
                binding != expected_binding or raw.get("imageExternalAuthorization") != expected_authorization
            ):
                raise DirectServiceError("DIRECT_SERVICE_CONFIG_CHANGED", "图片授权或模型配置在验证期间发生变化，请重新验证。")
            raw["imageSemanticValidation"] = {
                "validated": bool(
                    summary.get("validated", summary.get("success", False))
                ),
                "completedAt": str(summary.get("completedAt") or _utc_now()),
                "errorCode": str(summary.get("errorCode") or "")[:80],
                **binding,
            }
            raw["updatedAt"] = _utc_now()
            selections[clean_task] = raw
            payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)
            return self.get_task_model_selection(clean_task)

    def image_validation_binding(self, service: dict, selection: dict) -> dict:
        return {**_format_review_image_binding(service, selection), **self.format_validation_binding(service, selection)}

    def image_validation_snapshot(self, task_type: str):
        if task_type != "word.format_review":
            raise DirectServiceError("DIRECT_SERVICE_TASK_UNSUPPORTED", "任务不支持视觉能力验证。")
        with _STORE_LOCK:
            selection = self.get_task_model_selection(task_type)
            service = self.get_service(selection.get("serviceId", ""), include_secret=True)
            authorization = selection.get("imageExternalAuthorization") or {}
            if (selection.get("imageInputMode") != "openai_image_url" or
                    not authorization.get("authorized") or authorization.get("stale")):
                raise DirectServiceError("IMAGE_AUTHORIZATION_REQUIRED", "请先保存图片模式并授权当前任务图片外发。")
            binding = self.image_validation_binding(service, selection)
            authorization = {k: v for k, v in authorization.items() if k != "stale"}
            return service, selection, binding, authorization

    def format_validation_binding(self, service: dict, selection: dict) -> dict:
        binding = _format_review_format_semantic_binding(service, selection)
        # Reuse the existing credential fingerprint; never persist the API Key.
        key = service.get("apiKey")
        if key is None:
            key = self._read_key(str(service.get("id", ""))) if service.get("id") else ""
        binding["apiKeyFingerprint"] = self._api_key_fingerprint(key)
        return binding

    @_serialized_store_transaction
    def record_format_semantic_validation(
        self, task_type: str, summary: dict, selection: Optional[dict] = None,
        expected_binding: Optional[dict] = None,
    ) -> dict:
        clean_task = self._validate_task_type(task_type)
        if clean_task != "word.format_review":
            raise DirectServiceError("DIRECT_SERVICE_TASK_UNSUPPORTED", "任务不支持格式语义验证。")
        with _STORE_LOCK:
            payload, _ = self._load_with_legacy_direct_migration()
            services = self._service_map(payload)
            selections = self._selection_map(payload)
            raw = selections.get(clean_task, {})
            validated_selection = dict(raw if selection is None else selection)
            service = self._require_service(services, str(validated_selection.get("serviceId", "")))
            binding = self.format_validation_binding(service, validated_selection)
            if expected_binding is not None and binding != expected_binding:
                raise DirectServiceError("DIRECT_SERVICE_CONFIG_CHANGED", "服务配置在验证期间发生变化，请重新验证。")
            record = {
                "success": bool(summary.get("success", False)),
                "protocolVersion": str(summary.get("protocolVersion") or "format_semantics.v1"),
                "operations": summary.get("operations") or {"classify_role": True},
                "durationMs": int(summary.get("durationMs") or 0),
                "errorCode": str(summary.get("errorCode") or "")[:80],
                "message": str(summary.get("message") or "")[:200],
                "completedAt": str(summary.get("completedAt") or _utc_now()),
                **binding,
            }
            # One pending draft per task, bound by identity when read or saved.
            drafts = payload.setdefault("formatSemanticDraftValidations", {})
            drafts[clean_task] = record
            current_service = services.get(str(raw.get("serviceId", "")), {})
            if binding == self.format_validation_binding(current_service, raw):
                raw["formatSemanticValidation"] = record
                raw["updatedAt"] = _utc_now()
                selections[clean_task] = raw
                payload["taskModelSelections"] = selections
            save_config_payload(payload, self.config_path)
            return self.get_task_model_selection(clean_task) if selection is None else dict(record)

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
            payload, _ = self._load_with_legacy_direct_migration()
            service = self._require_service(
                self._service_map(payload), service_id
            )
            return self._is_custom_model_validated(
                payload, clean_task, service, model_name
            )

    def _attach_legacy_compatibility(self, service: dict, models, service_url: str, api_key: str) -> None:
        clean_models = sorted(
            {
                str(item).strip()
                for item in models
                if str(item or "").strip()
            }
        )
        if not clean_models:
            return
        catalog = self._model_catalog_state(service)
        if catalog.get("usableForSelection") or bool(service.get("modelListInvalidated")):
            return
        expires_at = _format_utc_timestamp(
            datetime.now(timezone.utc) + timedelta(seconds=LEGACY_COMPAT_TTL_SECONDS)
        )
        proof = {
            "models": clean_models,
            "serviceBaseUrl": str(service_url or service.get("serviceBaseUrl") or ""),
            "apiKeyFingerprint": self._api_key_fingerprint(api_key) if api_key else "",
            "revision": int(service.get("revision", 1) or 1),
            "createdAt": _utc_now(),
            "expiresAt": expires_at,
            "revoked": False,
            "revokeReason": None,
        }
        existing = service.get("legacyCompatibility")
        if isinstance(existing, dict) and not existing.get("revoked"):
            merged = set(existing.get("models") or [])
            merged.update(clean_models)
            proof["models"] = sorted(item for item in merged if item)
            proof["createdAt"] = existing.get("createdAt") or proof["createdAt"]
        service["legacyCompatibility"] = proof
        current_list = (
            list(service.get("modelList"))
            if isinstance(service.get("modelList"), list)
            else []
        )
        union = []
        for name in current_list + proof["models"]:
            clean = str(name or "").strip()
            if clean and clean not in union:
                union.append(clean)
        if union:
            service["modelList"] = union
            source = str(service.get("modelListSource") or "none")
            if source in {"", "none"}:
                service["modelListSource"] = "legacy_migration"
        service["updatedAt"] = _utc_now()

    def _legacy_model_compatible(self, service: dict, model_name: str) -> bool:
        if not model_name:
            return False
        last_error = service.get("modelListLastError")
        last_code = (
            str(last_error.get("code", "")).strip()
            if isinstance(last_error, dict)
            else ""
        )
        if last_code in LEGACY_COMPAT_AUTH_REVOKE_CODES:
            return False
        proof = service.get("legacyCompatibility")
        if isinstance(proof, dict):
            if proof.get("revoked"):
                return False
            models = proof.get("models")
            if not isinstance(models, list) or model_name not in models:
                return False
            if str(proof.get("serviceBaseUrl", "")).strip() != str(
                service.get("serviceBaseUrl", "")
            ).strip():
                return False
            try:
                if int(proof.get("revision", 0) or 0) != int(service.get("revision", 1) or 1):
                    return False
            except (TypeError, ValueError):
                return False
            expires = _parse_utc_timestamp(proof.get("expiresAt"))
            if expires is None or datetime.now(timezone.utc) >= expires:
                return False
            expected_fp = str(proof.get("apiKeyFingerprint") or "")
            if not expected_fp:
                return False
            actual_fp = self._api_key_fingerprint(
                self._read_key(str(service.get("id", "")))
            )
            if actual_fp != expected_fp:
                return False
            return True
        return False

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
        if self._legacy_model_compatible(service, model_name):
            return "available", True, "legacy_compatible"
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
        payload: Optional[dict] = None,
    ) -> None:
        custom_model = bool(selection.get("customModel", False))
        custom_validated = self._is_custom_model_validated(
            payload
            if isinstance(payload, dict)
            else load_config_payload(self.config_path, self.key_dir),
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
    def _validate_int_range(
        value, label: str, minimum: int, maximum: int
    ) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            val = int(value)
            if minimum <= val <= maximum:
                return val
        except (TypeError, ValueError):
            pass
        raise DirectServiceError(
            "DIRECT_SERVICE_PARAM_INVALID",
            f"{label}必须在 {minimum} 到 {maximum} 之间。",
        )

    @staticmethod
    def _validate_optional_token_limit(value, label: str) -> Optional[int]:
        if value in (None, "", 0, "0"):
            return None
        try:
            val = int(value)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
        raise DirectServiceError(
            "DIRECT_SERVICE_PARAM_INVALID",
            f"{label}必须是非负整数，0 或空表示不限。",
        )

    @staticmethod
    def _validate_image_input_mode(task_type: str, mode) -> str:
        if mode is None and task_type == "word.format_review":
            return "openai_image_url"
        clean = str(mode or "disabled").strip()
        if clean not in IMAGE_INPUT_MODES:
            raise DirectServiceError(
                "DIRECT_SERVICE_PARAM_INVALID", f"无效的图片输入模式: {mode}"
            )
        if task_type != "word.format_review" and clean != "disabled":
            return "disabled"
        return clean

    def _get_referenced_tasks(self, payload: Optional[dict], service_id: str) -> List[str]:
        if not payload or not service_id:
            return []
        referenced = set()
        selections = payload.get("taskModelSelections")
        if isinstance(selections, dict):
            for task, sel in selections.items():
                if isinstance(sel, dict) and sel.get("serviceId") == service_id:
                    referenced.add(task)
        active = payload.get("activeModelConfigurations")
        if isinstance(active, dict):
            for task, act_id in active.items():
                if act_id == service_id:
                    referenced.add(task)
                elif isinstance(act_id, dict) and act_id.get("serviceId") == service_id:
                    referenced.add(task)
        return sorted(list(referenced))

    def _sanitize_service(self, service: dict, payload: Optional[dict] = None) -> dict:
        service_id = str(service.get("id", ""))
        catalog = self._model_catalog_state(service)
        if payload is None:
            try:
                payload = load_config_payload(self.config_path, self.key_dir)
            except Exception:
                payload = {}
        referenced_tasks = self._get_referenced_tasks(payload, service_id)
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
            "referencedTasks": referenced_tasks,
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
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(api_key.strip() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
            migration_txn.fsync_directory(path.parent)
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
