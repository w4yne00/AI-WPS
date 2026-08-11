import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.services.model_configurations import (
    ModelConfigurationStore,
    normalize_service_base_url,
)
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS
from app.services.writing_policy.store import WritingPolicyStore


SNAPSHOT_SCHEMA_VERSION = 1
MIN_VALID_SNAPSHOTS = 3
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_STATE_FILES = ("adapter.json", "provider_api_key", "writing_policies.db")
_CONSISTENT_COPY_ATTEMPTS = 3
_POLICY_TABLE_COLUMNS = {
    "writing_policy_terms": {
        "id",
        "scope",
        "category",
        "preferred_text",
        "preferred_normalized",
        "aliases",
        "forbidden_variants",
        "definition",
        "context_keywords",
        "priority",
        "enabled",
        "note",
        "created_at",
        "updated_at",
    },
    "style_rules": {
        "id",
        "item_type",
        "scope",
        "task_types",
        "scene_ids",
        "name",
        "name_normalized",
        "rule_text",
        "positive_example",
        "negative_example",
        "context_keywords",
        "always_apply",
        "priority",
        "enabled",
        "note",
        "created_at",
        "updated_at",
    },
    "writing_policy_imports": {
        "id",
        "imported_at",
        "file_name",
        "format",
        "row_count",
        "created_count",
        "updated_count",
        "conflict_count",
        "error_count",
        "result",
    },
    "preset_overrides": {
        "preset_entry_id",
        "pack_id",
        "item_type",
        "operation",
        "payload",
        "created_at",
        "updated_at",
    },
    "preset_rule_overrides": {
        "preset_entry_id",
        "pack_id",
        "item_type",
        "operation",
        "payload",
        "created_at",
        "updated_at",
    },
    "schema_metadata": {"key", "value"},
}
_POLICY_PRIMARY_KEYS = {
    "writing_policy_terms": "id",
    "style_rules": "id",
    "writing_policy_imports": "id",
    "preset_overrides": "preset_entry_id",
    "preset_rule_overrides": "preset_entry_id",
    "schema_metadata": "key",
}
_POLICY_INTEGER_COLUMNS = {
    "writing_policy_terms": {"enabled"},
    "style_rules": {"always_apply", "enabled"},
    "writing_policy_imports": {
        "row_count",
        "created_count",
        "updated_count",
        "conflict_count",
        "error_count",
    },
}
_POLICY_REQUIRED_INDEXES = {
    "writing_policy_terms": {
        "idx_writing_policy_terms_scope": (False, ("scope",)),
        "idx_writing_policy_terms_enabled": (False, ("enabled",)),
        "idx_writing_policy_terms_preferred_normalized": (
            True,
            ("preferred_normalized",),
        ),
    },
    "style_rules": {
        "idx_style_rules_scope": (False, ("scope",)),
        "idx_style_rules_enabled": (False, ("enabled",)),
        "idx_style_rules_scope_name_normalized": (
            True,
            ("scope", "name_normalized"),
        ),
    },
    "preset_overrides": {
        "idx_preset_overrides_item_type": (False, ("item_type",))
    },
    "preset_rule_overrides": {
        "idx_preset_rule_overrides_item_type": (False, ("item_type",))
    },
}
_LEGACY_STYLE_COLUMNS = _POLICY_TABLE_COLUMNS["style_rules"] - {
    "item_type",
    "task_types",
    "scene_ids",
}


class RuntimeStateError(RuntimeError):
    def __init__(self, code: str, status: str = "recovery") -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json_secure(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(".{0}.{1}.tmp".format(path.name, uuid.uuid4().hex))
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _exchange_directories(left: Path, right: Path) -> None:
    """Atomically exchange two directories without an absent-state window."""
    library = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(str(left))
    right_bytes = os.fsencode(str(right))
    if sys.platform == "darwin":
        exchange = getattr(library, "renamex_np", None)
        if exchange is None:
            raise OSError("atomic directory exchange is unavailable")
        exchange.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        exchange.restype = ctypes.c_int
        result = exchange(left_bytes, right_bytes, 0x00000002)
    elif sys.platform.startswith("linux"):
        exchange = getattr(library, "renameat2", None)
        if exchange is None:
            raise OSError("atomic directory exchange is unavailable")
        exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        exchange.restype = ctypes.c_int
        result = exchange(-100, left_bytes, -100, right_bytes, 0x00000002)
    else:
        raise OSError("atomic directory exchange is unsupported")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


class RuntimeStateManager:
    def __init__(
        self,
        state_dir: Path,
        backup_dir: Path,
        release_version: str,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.backup_dir = Path(backup_dir)
        self.release_version = str(release_version or "unknown")[:80]

    def create_snapshot(
        self,
        reason: str,
        protect_last_accepted: bool = False,
    ) -> dict:
        return self._create_snapshot_from_source(
            self.state_dir,
            reason,
            legacy_layout=False,
            protect_last_accepted=protect_last_accepted,
        )

    def migrate_legacy_state(self, legacy_root: Path) -> dict:
        legacy_root = Path(legacy_root)
        snapshot = self._create_snapshot_from_source(
            legacy_root,
            "pre_migration",
            legacy_layout=True,
            protect_last_accepted=False,
        )
        if snapshot["coreStatus"] != "ready":
            raise RuntimeStateError("CORE_STATE_INVALID", "recovery")

        stage = self._new_stage("migration")
        try:
            frozen_source = self.backup_dir / snapshot["snapshotId"] / "state"
            self._copy_state(frozen_source, stage, legacy_layout=False)
            source_core, source_comparison = self._inspect_core(stage)
            if source_core["status"] != "ready":
                raise RuntimeStateError("CORE_STATE_INVALID", "recovery")

            self._migrate_model_configurations(stage)
            target_core, target_comparison = self._inspect_core(stage)
            if target_core["status"] != "ready":
                raise RuntimeStateError("CORE_STATE_INVALID", "recovery")
            if source_comparison != target_comparison:
                raise RuntimeStateError("CORE_STATE_MISMATCH", "recovery")

            policy = self._migrate_writing_policy(stage)
            self._secure_state_tree(stage)
            self._switch_state(stage)
            stage = None
            result = {
                "status": "ready" if policy["status"] == "ready" else "degraded",
                "snapshotId": snapshot["snapshotId"],
                "taskCount": target_core["modelConfigurations"]["taskCount"],
            }
            if policy["status"] != "ready":
                result["errorCode"] = "WRITING_POLICY_STATE_INVALID"
            self._append_audit("migrate", result["status"], snapshot["snapshotId"])
            return result
        except RuntimeStateError:
            self._append_audit("migrate", "recovery", snapshot["snapshotId"])
            raise
        except Exception:
            self._append_audit("migrate", "recovery", snapshot["snapshotId"])
            raise RuntimeStateError("CORE_STATE_MIGRATION_FAILED", "recovery")
        finally:
            if stage is not None and stage.exists():
                shutil.rmtree(str(stage))

    def restore_snapshot(self, snapshot_id: str, confirmed: bool = False) -> dict:
        if not confirmed:
            raise RuntimeStateError("RESTORE_CONFIRMATION_REQUIRED", "blocked")
        clean_id = str(snapshot_id or "").strip()
        if not _SAFE_REF.fullmatch(clean_id):
            raise RuntimeStateError("SNAPSHOT_ID_INVALID", "blocked")
        snapshot_dir = self.backup_dir / clean_id
        manifest_path = snapshot_dir / "manifest.json"
        state_source = snapshot_dir / "state"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            raise RuntimeStateError("SNAPSHOT_NOT_FOUND", "blocked")
        if not isinstance(manifest, dict) or not manifest.get("valid"):
            raise RuntimeStateError("SNAPSHOT_NOT_VALID", "blocked")
        self._verify_snapshot_files(state_source, manifest)

        stage = self._new_stage("restore")
        try:
            self._copy_state(state_source, stage, legacy_layout=False)
            core, unused_comparison = self._inspect_core(stage)
            policy = self._inspect_policy(stage / "writing_policies.db", migrate=False)
            if core["status"] != "ready" or policy["status"] != "ready":
                raise RuntimeStateError("SNAPSHOT_NOT_VALID", "blocked")
            pre_restore = self.create_snapshot("pre_restore")
            self._secure_state_tree(stage)
            self._switch_state(stage)
            stage = None
            self._append_audit("restore", "ready", clean_id)
            return {
                "status": "ready",
                "snapshotId": clean_id,
                "preRestoreSnapshotId": pre_restore["snapshotId"],
            }
        except RuntimeStateError as error:
            self._append_audit("restore", error.status, clean_id)
            raise
        except Exception:
            self._append_audit("restore", "recovery", clean_id)
            raise RuntimeStateError("RESTORE_FAILED", "recovery")
        finally:
            if stage is not None and stage.exists():
                shutil.rmtree(str(stage))

    def _create_snapshot_from_source(
        self,
        source: Path,
        reason: str,
        legacy_layout: bool,
        protect_last_accepted: bool,
    ) -> dict:
        clean_reason = str(reason or "").strip()
        if not _SAFE_REASON.fullmatch(clean_reason):
            raise RuntimeStateError("SNAPSHOT_REASON_INVALID", "blocked")
        self.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.backup_dir.chmod(0o700)
        snapshot_id = "snapshot-{0}-{1}".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            uuid.uuid4().hex[:12],
        )
        pending = self.backup_dir / ".{0}.pending".format(snapshot_id)
        final = self.backup_dir / snapshot_id
        pending.mkdir(mode=0o700)
        state_copy = pending / "state"
        try:
            self._copy_state(Path(source), state_copy, legacy_layout=legacy_layout)
            core, unused_comparison = self._inspect_core(state_copy)
            policy = self._inspect_policy(
                state_copy / "writing_policies.db", migrate=False
            )
            files = self._file_manifest(state_copy)
            valid = core["status"] == "ready" and policy["status"] == "ready"
            manifest = {
                "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
                "snapshotId": snapshot_id,
                "createdAt": _utc_now(),
                "reason": clean_reason,
                "releaseVersion": self.release_version,
                "sourceLayout": "legacy" if legacy_layout else "shared",
                "valid": valid,
                "coreStatus": core["status"],
                "writingPolicyStatus": policy["status"],
                "inventory": {
                    "modelConfigurations": core["modelConfigurations"],
                    "activeRelationships": core["activeRelationships"],
                    "taskKeyReferenceCount": core["taskKeyReferenceCount"],
                    "apiKeys": core["apiKeys"],
                    "writingPolicies": policy,
                },
                "files": files,
                "retention": {
                    "lastAcceptedVersion": bool(protect_last_accepted),
                },
            }
            _write_json_secure(pending / "manifest.json", manifest)
            self._secure_state_tree(state_copy)
            pending.chmod(0o700)
            os.replace(str(pending), str(final))
            if valid:
                self._prune_valid_snapshots()
            result = {
                "status": "ready" if valid else (
                    "recovery" if core["status"] != "ready" else "degraded"
                ),
                "snapshotId": snapshot_id,
                "valid": valid,
                "coreStatus": core["status"],
                "writingPolicyStatus": policy["status"],
            }
            self._append_audit("snapshot", result["status"], snapshot_id)
            return result
        except Exception as error:
            if pending.exists():
                shutil.rmtree(str(pending))
            if isinstance(error, RuntimeStateError):
                raise
            raise

    def _copy_state(self, source: Path, target: Path, legacy_layout: bool) -> None:
        for unused_attempt in range(_CONSISTENT_COPY_ATTEMPTS):
            try:
                before = self._state_signature(source, legacy_layout)
                self._reset_copy_target(target)
                self._copy_state_once(source, target, legacy_layout)
                after = self._state_signature(source, legacy_layout)
                if before == after:
                    return
            except OSError:
                pass
        self._reset_copy_target(target)
        raise RuntimeStateError("SNAPSHOT_SOURCE_UNSTABLE", "recovery")

    @staticmethod
    def _reset_copy_target(target: Path) -> None:
        if target.exists():
            shutil.rmtree(str(target))

    def _state_signature(self, source: Path, legacy_layout: bool) -> tuple:
        if source.is_symlink():
            raise RuntimeStateError("STATE_SYMLINK_REJECTED", "recovery")
        if legacy_layout:
            candidates = [
                ("adapter.json", source / "config/adapter.json"),
                ("provider_api_key", source / "run/provider_api_key"),
                ("writing_policies.db", source / "run/writing_policies.db"),
            ]
            key_source = source / "run/provider_api_keys"
            policy_parent = source / "run"
        else:
            candidates = [(name, source / name) for name in _STATE_FILES]
            key_source = source / "provider_api_keys"
            policy_parent = source
        database_path = (
            source / "run/writing_policies.db"
            if legacy_layout
            else source / "writing_policies.db"
        )
        candidates.extend(
            ("writing_policies.db{0}".format(suffix), Path(str(database_path) + suffix))
            for suffix in ("-wal", "-shm")
        )
        if key_source.is_symlink():
            raise RuntimeStateError("STATE_SYMLINK_REJECTED", "recovery")
        if key_source.is_dir():
            candidates.extend(
                ("provider_api_keys/{0}".format(path.name), path)
                for path in sorted(key_source.iterdir())
            )
        candidates.extend(
            (path.name, path)
            for path in sorted(policy_parent.glob("writing_policies.db.backup-*"))
        )
        signatures = []
        for relative, path in candidates:
            if not path.exists():
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeStateError("STATE_FILE_INVALID", "recovery")
            before = path.stat()
            digest = _sha256_file(path)
            after = path.stat()
            identity_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            identity_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if identity_before != identity_after:
                raise OSError("runtime state changed while hashing")
            signatures.append((relative, identity_after, digest))
        return tuple(signatures)

    def _copy_state_once(self, source: Path, target: Path, legacy_layout: bool) -> None:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.chmod(0o700)
        if legacy_layout:
            sources = {
                "adapter.json": source / "config/adapter.json",
                "provider_api_key": source / "run/provider_api_key",
                "writing_policies.db": source / "run/writing_policies.db",
            }
            key_source = source / "run/provider_api_keys"
            policy_parent = source / "run"
        else:
            sources = {name: source / name for name in _STATE_FILES}
            key_source = source / "provider_api_keys"
            policy_parent = source

        for name, source_path in sources.items():
            if source_path.is_symlink():
                raise RuntimeStateError("STATE_SYMLINK_REJECTED", "recovery")
            if source_path.is_file():
                target_path = target / name
                if name == "writing_policies.db":
                    self._copy_sqlite_database(source_path, target_path)
                else:
                    shutil.copyfile(str(source_path), str(target_path))
                (target / name).chmod(0o600)

        if key_source.is_symlink():
            raise RuntimeStateError("STATE_SYMLINK_REJECTED", "recovery")
        if key_source.is_dir():
            target_keys = target / "provider_api_keys"
            target_keys.mkdir(mode=0o700)
            for key_path in sorted(key_source.iterdir()):
                if key_path.is_symlink() or not key_path.is_file():
                    raise RuntimeStateError("KEY_FILE_INVALID", "recovery")
                if not _SAFE_REF.fullmatch(key_path.name):
                    raise RuntimeStateError("KEY_REFERENCE_INVALID", "recovery")
                shutil.copyfile(str(key_path), str(target_keys / key_path.name))
                (target_keys / key_path.name).chmod(0o600)

        for backup in sorted(policy_parent.glob("writing_policies.db.backup-*")):
            if backup.is_symlink() or not backup.is_file():
                continue
            target_path = target / backup.name
            shutil.copyfile(str(backup), str(target_path))
            target_path.chmod(0o600)

    @staticmethod
    def _copy_sqlite_database(source: Path, target: Path) -> None:
        try:
            source_uri = source.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(source_uri, uri=True, timeout=30.0) as source_db:
                with sqlite3.connect(str(target), timeout=30.0) as target_db:
                    source_db.backup(target_db)
            target.chmod(0o600)
        except (OSError, sqlite3.Error):
            if target.exists():
                target.unlink()
            shutil.copyfile(str(source), str(target))
            target.chmod(0o600)

    def _inspect_core(self, state: Path) -> Tuple[dict, dict]:
        config_path = state / "adapter.json"
        if not config_path.exists():
            payload = {}
        else:
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                return self._invalid_core(), {}
        if not isinstance(payload, dict):
            return self._invalid_core(), {}

        try:
            configurations = self._logical_configurations(payload)
            active = self._logical_active_relationships(payload, configurations)
            task_refs = self._task_key_references(payload)
            referenced_keys = {
                str(item["apiKeyRef"])
                for item in configurations.values()
                if item.get("apiKeyRef")
            }
            referenced_keys.update(task_refs.values())
            routes = payload.get("taskRoutes", {})
            if routes is None:
                routes = {}
            if not isinstance(routes, dict):
                raise ValueError("invalid routes")
            route_comparison = {}
            for task_type, route in routes.items():
                task = str(task_type).strip()
                if task not in SUPPORTED_WORKFLOW_TASKS or not isinstance(route, dict):
                    raise ValueError("invalid route")
                ref = str(route.get("apiKeyRef", "")).strip()
                if ref:
                    self._validate_ref(ref)
                    referenced_keys.add(ref)
                route_comparison[task] = {
                    "path": str(route.get("path", "")),
                    "apiKeyRef": ref,
                }

            key_inventory = []
            key_comparison = {}
            for ref in sorted(referenced_keys):
                key_path = self._key_path(state, ref)
                if key_path is None or not key_path.is_file():
                    raise ValueError("missing key")
                fingerprint = _sha256_file(key_path)
                key_inventory.append(
                    {"ref": ref, "sha256": fingerprint, "present": True}
                )
                key_comparison[ref] = fingerprint

            counts = {task: 0 for task in SUPPORTED_WORKFLOW_TASKS}
            public_configurations = []
            comparison_configurations = {}
            for configuration_id, item in configurations.items():
                task = item["taskType"]
                counts[task] += 1
                public_configurations.append(
                    {
                        "taskType": task,
                        "configurationId": configuration_id,
                        "apiKeyRef": item.get("apiKeyRef", ""),
                        "serviceBaseUrlSha256": _sha256_text(
                            str(item.get("serviceBaseUrl", ""))
                        ),
                    }
                )
                comparison_configurations[configuration_id] = dict(item)

            configured_tasks = [task for task, count in counts.items() if count]
            public = {
                "status": "ready",
                "modelConfigurations": {
                    "totalCount": len(configurations),
                    "taskCount": len(configured_tasks),
                    "countsByTask": counts,
                    "items": sorted(
                        public_configurations,
                        key=lambda item: (item["taskType"], item["configurationId"]),
                    ),
                },
                "activeRelationships": [
                    {"taskType": task, "configurationId": active[task]}
                    for task in sorted(active)
                ],
                "taskKeyReferenceCount": len(task_refs),
                "apiKeys": key_inventory,
            }
            comparison = {
                "configurations": comparison_configurations,
                "active": active,
                "taskKeyRefs": task_refs,
                "routes": route_comparison,
                "keys": key_comparison,
            }
            return public, comparison
        except Exception:
            return self._invalid_core(), {}

    @staticmethod
    def _invalid_core() -> dict:
        return {
            "status": "recovery",
            "modelConfigurations": {
                "totalCount": 0,
                "taskCount": 0,
                "countsByTask": {
                    task: 0 for task in SUPPORTED_WORKFLOW_TASKS
                },
                "items": [],
            },
            "activeRelationships": [],
            "taskKeyReferenceCount": 0,
            "apiKeys": [],
        }

    def _logical_configurations(self, payload: dict) -> Dict[str, dict]:
        raw = payload.get("modelConfigurations", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("invalid model configurations")
        result = {}
        for key, value in raw.items():
            item = self._configuration_record(key, value)
            if item["id"] in result:
                raise ValueError("duplicate configuration identity")
            result[item["id"]] = item

        legacy = payload.get("workflowProfiles", {})
        if legacy is None:
            legacy = {}
        if not isinstance(legacy, dict):
            raise ValueError("invalid workflow profiles")
        provider_url = str(payload.get("providerBaseUrl", ""))
        for key, value in legacy.items():
            if not isinstance(value, dict):
                raise ValueError("invalid workflow profile")
            item_id = str(value.get("id", key)).strip()
            if item_id in result:
                continue
            result[item_id] = self._configuration_record(
                key,
                {
                    "id": item_id,
                    "taskType": value.get("taskType"),
                    "apiKeyRef": value.get("apiKeyRef"),
                    "serviceBaseUrl": provider_url,
                },
            )
        return result

    def _configuration_record(self, key: object, value: object) -> dict:
        if not isinstance(value, dict):
            raise ValueError("invalid configuration")
        item_id = str(value.get("id", key)).strip()
        task = str(value.get("taskType", "")).strip()
        ref = str(value.get("apiKeyRef", "")).strip()
        if not item_id or task not in SUPPORTED_WORKFLOW_TASKS:
            raise ValueError("invalid configuration identity")
        if ref:
            self._validate_ref(ref)
        service_url = str(value.get("serviceBaseUrl", "")).strip()
        if service_url:
            service_url = normalize_service_base_url(service_url)
        return {
            "id": item_id,
            "taskType": task,
            "apiKeyRef": ref,
            "serviceBaseUrl": service_url,
        }

    @staticmethod
    def _logical_active_relationships(
        payload: dict, configurations: Dict[str, dict]
    ) -> Dict[str, str]:
        current = payload.get("activeModelConfigurations", {})
        legacy = payload.get("activeWorkflowProfiles", {})
        if current is None:
            current = {}
        if legacy is None:
            legacy = {}
        if not isinstance(current, dict) or not isinstance(legacy, dict):
            raise ValueError("invalid active relationships")
        result = {str(task): str(item_id) for task, item_id in current.items()}
        for task, item_id in legacy.items():
            result.setdefault(str(task), str(item_id))
        for task, item_id in result.items():
            if task not in SUPPORTED_WORKFLOW_TASKS:
                raise ValueError("invalid active task")
            if item_id not in configurations or configurations[item_id]["taskType"] != task:
                raise ValueError("invalid active target")
        return result

    def _task_key_references(self, payload: dict) -> Dict[str, str]:
        raw = payload.get("taskApiKeyRefs", {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("invalid task key references")
        result = {}
        for task, ref in raw.items():
            clean_task = str(task).strip()
            clean_ref = str(ref).strip()
            if clean_task not in SUPPORTED_WORKFLOW_TASKS:
                raise ValueError("invalid task key task")
            self._validate_ref(clean_ref)
            result[clean_task] = clean_ref
        return result

    @staticmethod
    def _validate_ref(ref: str) -> None:
        if not _SAFE_REF.fullmatch(str(ref or "")):
            raise ValueError("invalid reference")

    @staticmethod
    def _key_path(state: Path, ref: str) -> Optional[Path]:
        candidate = state / "provider_api_keys" / ref
        if candidate.is_file():
            return candidate
        if ref == "default" and (state / "provider_api_key").is_file():
            return state / "provider_api_key"
        return None

    @staticmethod
    def _policy_schema_is_valid(
        connection: sqlite3.Connection, schema_version: int
    ) -> bool:
        required = (
            dict(_POLICY_TABLE_COLUMNS)
            if schema_version >= 1
            else {
                "writing_policy_terms": _POLICY_TABLE_COLUMNS[
                    "writing_policy_terms"
                ],
                "style_rules": _LEGACY_STYLE_COLUMNS,
            }
        )
        for table, required_columns in required.items():
            columns = {
                str(row[1]): (str(row[2]).upper(), bool(row[3]), int(row[5]))
                for row in connection.execute("PRAGMA table_info({0})".format(table))
            }
            if not required_columns.issubset(columns):
                return False
            primary_key = _POLICY_PRIMARY_KEYS[table]
            integer_columns = _POLICY_INTEGER_COLUMNS.get(table, set())
            for column in required_columns:
                expected_type = "INTEGER" if column in integer_columns else "TEXT"
                if columns[column][0] != expected_type:
                    return False
                if column != primary_key and not columns[column][1]:
                    return False
            if columns.get(primary_key, ("", False, 0))[2] != 1:
                return False
        if schema_version >= 1:
            for table, expected in _POLICY_REQUIRED_INDEXES.items():
                actual = {
                    str(row[1]): bool(row[2])
                    for row in connection.execute(
                        "PRAGMA index_list({0})".format(table)
                    )
                }
                for name, (unique, expected_columns) in expected.items():
                    if actual.get(name) is not unique:
                        return False
                    actual_columns = tuple(
                        str(row[2])
                        for row in connection.execute(
                            "PRAGMA index_info({0})".format(name)
                        )
                    )
                    if actual_columns != expected_columns:
                        return False
        term_sql = RuntimeStateManager._table_sql(
            connection, "writing_policy_terms"
        )
        style_sql = RuntimeStateManager._table_sql(connection, "style_rules")
        required_checks = [
            (term_sql, r"check\s*\(\s*scope\s*=\s*'global'\s*\)"),
            (term_sql, r"check\s*\(\s*enabled\s+in\s*\(\s*0\s*,\s*1\s*\)\s*\)"),
            (style_sql, r"check\s*\(\s*always_apply\s+in\s*\(\s*0\s*,\s*1\s*\)\s*\)"),
            (style_sql, r"check\s*\(\s*enabled\s+in\s*\(\s*0\s*,\s*1\s*\)\s*\)"),
        ]
        if schema_version >= 1:
            preset_sql = RuntimeStateManager._table_sql(
                connection, "preset_overrides"
            )
            preset_rule_sql = RuntimeStateManager._table_sql(
                connection, "preset_rule_overrides"
            )
            required_checks.extend(
                [
                    (preset_sql, r"check\s*\(\s*item_type\s*=\s*'term'\s*\)"),
                    (
                        preset_sql,
                        r"check\s*\(\s*operation\s+in\s*\(\s*'override'\s*,\s*'disabled'\s*\)\s*\)",
                    ),
                    (
                        preset_rule_sql,
                        r"check\s*\(\s*item_type\s+in\s*\(\s*'style'\s*,\s*'anti_template'\s*\)\s*\)",
                    ),
                    (
                        preset_rule_sql,
                        r"check\s*\(\s*operation\s+in\s*\(\s*'override'\s*,\s*'disabled'\s*\)\s*\)",
                    ),
                ]
            )
        return all(re.search(pattern, sql, re.IGNORECASE) for sql, pattern in required_checks)

    @staticmethod
    def _table_sql(connection: sqlite3.Connection, table: str) -> str:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return str(row[0] or "") if row is not None else ""

    @staticmethod
    def _inspect_policy(path: Path, migrate: bool) -> dict:
        if not path.exists():
            return {
                "status": "ready",
                "present": False,
                "schemaVersion": 0,
                "totalCount": 0,
                "enabledCount": 0,
                "integrity": "not_present",
            }
        try:
            if migrate:
                WritingPolicyStore(path)
            with sqlite3.connect(str(path), timeout=30.0) as connection:
                check = connection.execute("PRAGMA quick_check").fetchone()
                if check is None or check[0] != "ok":
                    raise sqlite3.DatabaseError("integrity")
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"writing_policy_terms", "style_rules"}.issubset(tables):
                    raise sqlite3.DatabaseError("schema")
                metadata_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'schema_metadata'"
                ).fetchone()
                schema_version = 0
                if metadata_exists:
                    row = connection.execute(
                        "SELECT value FROM schema_metadata "
                        "WHERE key = 'schema_version'"
                    ).fetchone()
                    schema_version = int(row[0]) if row is not None else 0
                if schema_version > 1 or not RuntimeStateManager._policy_schema_is_valid(
                    connection, schema_version
                ):
                    raise sqlite3.DatabaseError("schema")
                term = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(enabled), 0) "
                    "FROM writing_policy_terms"
                ).fetchone()
                style = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(enabled), 0) FROM style_rules"
                ).fetchone()
            return {
                "status": "ready",
                "present": True,
                "schemaVersion": schema_version,
                "totalCount": int(term[0]) + int(style[0]),
                "enabledCount": int(term[1]) + int(style[1]),
                "integrity": "ok",
            }
        except Exception:
            return {
                "status": "degraded",
                "present": True,
                "schemaVersion": 0,
                "totalCount": 0,
                "enabledCount": 0,
                "integrity": "invalid",
            }

    def _migrate_writing_policy(self, state: Path) -> dict:
        database = state / "writing_policies.db"
        source = self._inspect_policy(database, migrate=False)
        if source["status"] != "ready" or not source["present"]:
            return source
        original = state / ".writing_policies.db.pre-migration"
        shutil.copyfile(str(database), str(original))
        original.chmod(0o600)
        try:
            target = self._inspect_policy(database, migrate=True)
            if (
                target["status"] != "ready"
                or target["totalCount"] != source["totalCount"]
                or target["enabledCount"] != source["enabledCount"]
            ):
                shutil.copyfile(str(original), str(database))
                database.chmod(0o600)
                return dict(source, status="degraded", integrity="migration_mismatch")
            return target
        finally:
            if original.exists():
                original.unlink()

    @staticmethod
    def _migrate_model_configurations(state: Path) -> None:
        config_path = state / "adapter.json"
        if not config_path.exists():
            _write_json_secure(config_path, {})
        store = ModelConfigurationStore(
            config_path=config_path,
            key_dir=state / "provider_api_keys",
        )
        for task_type in SUPPORTED_WORKFLOW_TASKS:
            store.list_for_task(task_type)

    @staticmethod
    def _file_manifest(state: Path) -> List[dict]:
        result = []
        if not state.exists():
            return result
        for path in sorted(state.rglob("*")):
            if not path.is_file():
                continue
            result.append(
                {
                    "path": path.relative_to(state).as_posix(),
                    "sha256": _sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
        return result

    def _verify_snapshot_files(self, state: Path, manifest: dict) -> None:
        declared = manifest.get("files")
        if not isinstance(declared, list):
            raise RuntimeStateError("SNAPSHOT_MANIFEST_INVALID", "blocked")
        actual = {
            item["path"]: (item["sha256"], item["size"])
            for item in self._file_manifest(state)
        }
        expected = {}
        for item in declared:
            if not isinstance(item, dict):
                raise RuntimeStateError("SNAPSHOT_MANIFEST_INVALID", "blocked")
            path = str(item.get("path", ""))
            if path.startswith("/") or ".." in Path(path).parts:
                raise RuntimeStateError("SNAPSHOT_MANIFEST_INVALID", "blocked")
            expected[path] = (str(item.get("sha256", "")), int(item.get("size", -1)))
        if actual != expected:
            raise RuntimeStateError("SNAPSHOT_CHECKSUM_MISMATCH", "blocked")

    def _new_stage(self, label: str) -> Path:
        parent = self.state_dir.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=".{0}.".format(label), dir=str(parent)))

    def _switch_state(self, stage: Path) -> None:
        existing = self.state_dir.exists()
        try:
            if existing:
                _exchange_directories(self.state_dir, stage)
            else:
                os.replace(str(stage), str(self.state_dir))
        except Exception:
            raise RuntimeStateError("STATE_SWITCH_FAILED", "recovery")
        if existing and stage.exists():
            try:
                shutil.rmtree(str(stage))
            except OSError:
                pass

    @staticmethod
    def _secure_state_tree(state: Path) -> None:
        if not state.exists():
            return
        for path in state.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file():
                path.chmod(0o600)
        state.chmod(0o700)

    def _prune_valid_snapshots(self) -> None:
        unprotected = []
        for path in self.backup_dir.iterdir():
            if not path.is_dir() or path.name.startswith("."):
                continue
            try:
                manifest = json.loads(
                    (path / "manifest.json").read_text(encoding="utf-8")
                )
            except Exception:
                continue
            if not manifest.get("valid"):
                continue
            retention = manifest.get("retention", {})
            if isinstance(retention, dict) and retention.get("lastAcceptedVersion"):
                continue
            unprotected.append((str(manifest.get("createdAt", "")), path.name, path))
        unprotected.sort(reverse=True)
        for unused_created, unused_name, path in unprotected[MIN_VALID_SNAPSHOTS:]:
            if not self._append_audit("prune", "pending", path.name):
                continue
            tombstone = self.backup_dir / ".{0}.prune-pending".format(path.name)
            try:
                os.replace(str(path), str(tombstone))
            except OSError:
                self._append_audit("prune", "recovery", path.name)
                continue
            if not self._append_audit("prune", "ready", path.name):
                try:
                    os.replace(str(tombstone), str(path))
                except OSError:
                    pass
                continue
            try:
                shutil.rmtree(str(tombstone))
            except OSError:
                pass

    def _append_audit(self, action: str, status: str, snapshot_id: str) -> bool:
        try:
            self.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.backup_dir.chmod(0o700)
            audit_path = self.backup_dir / "runtime-state-audit.jsonl"
            descriptor = os.open(
                str(audit_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "timestamp": _utc_now(),
                            "action": action,
                            "status": status,
                            "snapshotId": snapshot_id,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            audit_path.chmod(0o600)
            return True
        except Exception:
            return False
