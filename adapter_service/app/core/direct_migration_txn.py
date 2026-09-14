import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Dict, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - target runtime is Linux
    fcntl = None


JOURNAL_NAME = "adapter-direct-migration-journal.json"
RECOVERY_RECORD_NAME = "adapter-direct-migration-recovery.json"
RECOVERY_WRITE_FAILED_NAME = "adapter-direct-migration-recovery.write-failed"
SNAPSHOT_SUFFIX = ".direct-migration-snapshot"
PRE_BACKUP_SUFFIX = ".pre-direct-migration"
STAGE_DIR_PREFIX = ".direct-migration-stage-"
SNAPSHOT_MANIFEST_NAME = "manifest.json"
LOCK_NAME = "adapter-direct-migration.lock"
SNAPSHOT_RETENTION_SECONDS = 7 * 24 * 60 * 60

PHASE_STAGING = "staging"
PHASE_COMMITTING = "committing"
PHASE_COMMITTED = "committed"
PHASE_ROLLED_BACK = "rolled_back"

_recovery_record_write_failed = False
_recovery_record_write_error = ""
_recovery_failed_config = ""
_SAFE_KEY_REF = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_lock_state = threading.local()


class MigrationStateError(RuntimeError):
    pass


@contextmanager
def migration_lock(config_path: Path):
    depth = int(getattr(_lock_state, "depth", 0) or 0)
    if depth:
        _lock_state.depth = depth + 1
        try:
            yield
        finally:
            _lock_state.depth -= 1
        return
    path = Path(config_path).with_name(LOCK_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    os.chmod(str(path), 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        _lock_state.depth = 1
        yield
    finally:
        _lock_state.depth = 0
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def serialized(operation):
    @wraps(operation)
    def wrapper(store, *args, **kwargs):
        with migration_lock(Path(store.config_path)):
            return operation(store, *args, **kwargs)

    return wrapper


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def snapshot_dir(config_path: Path) -> Path:
    return Path(str(config_path) + SNAPSHOT_SUFFIX)


def journal_path(config_path: Path) -> Path:
    return config_path.with_name(JOURNAL_NAME)


def recovery_record_path(config_path: Path) -> Path:
    return config_path.with_name(RECOVERY_RECORD_NAME)


def recovery_write_failed_path(config_path: Path) -> Path:
    return config_path.with_name(RECOVERY_WRITE_FAILED_NAME)


def pre_backup_path(config_path: Path) -> Path:
    return Path(str(config_path) + PRE_BACKUP_SUFFIX)


def recovery_record_write_status_for(config_path: Path) -> Dict[str, object]:
    failed_path = recovery_write_failed_path(config_path)
    file_failed = failed_path.is_file()
    message = ""
    if file_failed:
        try:
            message = failed_path.read_text(encoding="utf-8").strip()
        except OSError:
            message = "recovery record write failed"
    elif (
        _recovery_record_write_failed
        and _recovery_failed_config == str(config_path)
    ):
        message = _recovery_record_write_error
        file_failed = True
    return {
        "recordWriteFailed": bool(file_failed),
        "message": message,
    }


def fsync_directory(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def copy_file_fsync(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / ".{0}.{1}.tmp".format(
        destination.name, uuid.uuid4().hex
    )
    try:
        shutil.copyfile(str(source), str(temporary))
        with open(str(temporary), "rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(str(temporary), 0o600)
        os.replace(str(temporary), str(destination))
        os.chmod(str(destination), 0o600)
        fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / ".{0}.{1}.tmp".format(path.name, uuid.uuid4().hex)
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def collect_referenced_key_names(payload: dict, extra_names: Optional[List[str]] = None) -> List[str]:
    names = set(extra_names or [])
    for bucket in (
        payload.get("modelConfigurations"),
        payload.get("legacyDirectPending"),
        payload.get("workflowProfiles"),
    ):
        if not isinstance(bucket, dict):
            continue
        for item in bucket.values():
            if isinstance(item, dict):
                ref = str(item.get("apiKeyRef", "")).strip()
                if ref:
                    names.add(ref)
    services = payload.get("directServices")
    if isinstance(services, dict):
        for service_id in services:
            names.add("direct_service_{0}".format(service_id))
    return sorted(name for name in names if name and _SAFE_KEY_REF.fullmatch(name))


def _write_snapshot_tree(
    target: Path,
    config_bytes: bytes,
    key_dir: Path,
    key_names: List[str],
) -> List[str]:
    if target.exists():
        shutil.rmtree(str(target), ignore_errors=True)
    keys_dir = target / "keys"
    keys_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(str(target), 0o700)
    os.chmod(str(keys_dir), 0o700)
    adapter = target / "adapter.json"
    descriptor = os.open(
        str(adapter), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(config_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(str(adapter), 0o600)
    copied = []
    key_hashes = {}
    for name in key_names:
        if not _SAFE_KEY_REF.fullmatch(str(name)):
            continue
        source = key_dir / name
        if source.is_file():
            copy_file_fsync(source, keys_dir / name)
            copied.append(name)
            key_hashes[name] = sha256_file(keys_dir / name)
    write_json_atomic(
        target / SNAPSHOT_MANIFEST_NAME,
        {
            "schemaVersion": 1,
            "createdAt": _utc_now(),
            "configSha256": sha256_bytes(config_bytes),
            "keys": key_hashes,
        },
    )
    fsync_directory(keys_dir)
    fsync_directory(target)
    return copied


def write_pre_snapshot(
    config_path: Path,
    key_dir: Path,
    config_bytes: bytes,
    extra_key_names: Optional[List[str]] = None,
) -> dict:
    try:
        payload = json.loads(config_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        payload = {}
    key_names = collect_referenced_key_names(payload, extra_key_names)
    root = snapshot_dir(config_path)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(str(root), 0o700)
    copied = _write_snapshot_tree(root / "pre", config_bytes, key_dir, key_names)
    fsync_directory(root)
    if config_path.exists():
        copy_file_fsync(config_path, pre_backup_path(config_path))
    return {
        "configSha256": sha256_bytes(config_bytes),
        "keyNames": copied,
        "keyDir": str(key_dir),
    }


def write_committed_snapshot(config_path: Path, key_dir: Path) -> dict:
    config_bytes = config_path.read_bytes()
    payload = json.loads(config_bytes.decode("utf-8"))
    key_names = collect_referenced_key_names(payload)
    root = snapshot_dir(config_path)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(str(root), 0o700)
    copied = _write_snapshot_tree(root / "committed", config_bytes, key_dir, key_names)
    fsync_directory(root)
    return {
        "configSha256": sha256_bytes(config_bytes),
        "keyNames": copied,
        "keyDir": str(key_dir),
    }


def restore_snapshot_tree(tree: Path, config_path: Path, key_dir: Path) -> Optional[dict]:
    adapter = tree / "adapter.json"
    manifest_path = tree / SNAPSHOT_MANIFEST_NAME
    if not adapter.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        return None
    expected_config_hash = str(manifest.get("configSha256") or "")
    if not _SHA256.fullmatch(expected_config_hash):
        return None
    if sha256_file(adapter) != expected_config_hash:
        return None
    keys = manifest.get("keys")
    if not isinstance(keys, dict):
        return None
    keys_dir = tree / "keys"
    for name, expected_hash in keys.items():
        clean_name = str(name or "")
        clean_hash = str(expected_hash or "")
        source = keys_dir / clean_name
        if (
            not _SAFE_KEY_REF.fullmatch(clean_name)
            or not _SHA256.fullmatch(clean_hash)
            or not source.is_file()
            or sha256_file(source) != clean_hash
        ):
            return None
    try:
        payload = json.loads(adapter.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    key_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(str(key_dir), 0o700)
    for name in sorted(keys):
        copy_file_fsync(keys_dir / name, key_dir / name)
    copy_file_fsync(adapter, config_path)
    return payload


def read_journal(config_path: Path) -> Optional[dict]:
    path = journal_path(config_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise MigrationStateError("direct migration journal is unreadable") from exc
    if not isinstance(payload, dict):
        raise MigrationStateError("direct migration journal must be an object")
    return payload


def write_journal(config_path: Path, payload: dict) -> None:
    write_json_atomic(journal_path(config_path), payload)


def infer_key_dir(config_path: Path, journal: Optional[dict] = None) -> Path:
    del journal
    parent = config_path.parent
    if parent.name == "config":
        # The bundled, non-shared runtime stores adapter.json under config/
        # and direct-service keys under the sibling run/ directory.
        return parent.parent / "run" / "provider_api_keys"
    return parent / "provider_api_keys"


def _safe_stage_dir(key_dir: Path, value: object) -> Optional[Path]:
    raw = str(value or "").strip()
    if not raw:
        return None
    target = Path(raw)
    try:
        parent = target.parent.resolve()
        expected_parent = key_dir.parent.resolve()
    except OSError:
        return None
    if parent != expected_parent or not target.name.startswith(STAGE_DIR_PREFIX):
        return None
    return target


def _validated_journal(config_path: Path, key_dir: Path, journal: dict) -> dict:
    expected_config = config_path.resolve()
    expected_key_dir = key_dir.resolve()
    try:
        recorded_config = Path(str(journal.get("configPath") or "")).resolve()
        recorded_key_dir = Path(str(journal.get("keyDir") or "")).resolve()
    except OSError as exc:
        raise MigrationStateError("direct migration journal paths are invalid") from exc
    if recorded_config != expected_config or recorded_key_dir != expected_key_dir:
        raise MigrationStateError("direct migration journal roots do not match runtime state")
    phase = str(journal.get("phase") or "")
    if phase not in {
        PHASE_STAGING,
        PHASE_COMMITTING,
        PHASE_COMMITTED,
        PHASE_ROLLED_BACK,
    }:
        raise MigrationStateError("direct migration journal phase is invalid")
    stage = _safe_stage_dir(key_dir, journal.get("stagingDir"))
    if stage is None:
        raise MigrationStateError("direct migration staging path is invalid")
    refs = journal.get("newKeyRefs") or []
    if not isinstance(refs, list) or any(
        not _SAFE_KEY_REF.fullmatch(str(ref or ""))
        or not str(ref).startswith("direct_service_direct_svc_")
        for ref in refs
    ):
        raise MigrationStateError("direct migration key references are invalid")
    staged_hash = str(journal.get("stagedConfigSha256") or "")
    if staged_hash and not _SHA256.fullmatch(staged_hash):
        raise MigrationStateError("direct migration config hash is invalid")
    clean = dict(journal)
    clean["stagingDir"] = str(stage)
    clean["newKeyRefs"] = [str(ref) for ref in refs]
    return clean


def cleanup_staging_dirs(key_dir: Path, extra_dirs: Optional[List[str]] = None) -> None:
    parents = {key_dir.parent, key_dir}
    for extra in extra_dirs or []:
        target = _safe_stage_dir(key_dir, extra)
        if target is not None and target.exists():
            shutil.rmtree(str(target), ignore_errors=True)
    for parent in parents:
        if not parent.is_dir():
            continue
        for item in parent.glob(STAGE_DIR_PREFIX + "*"):
            if item.is_dir():
                shutil.rmtree(str(item), ignore_errors=True)


def write_recovery_record(config_path: Path, reason: str) -> None:
    global _recovery_record_write_failed, _recovery_record_write_error, _recovery_failed_config
    record = {
        "restoredAt": _utc_now(),
        "reason": reason,
        "restoredFrom": str(snapshot_dir(config_path)),
    }
    try:
        write_json_atomic(recovery_record_path(config_path), record)
        _recovery_record_write_failed = False
        _recovery_record_write_error = ""
        _recovery_failed_config = ""
        failed_path = recovery_write_failed_path(config_path)
        if failed_path.exists():
            try:
                failed_path.unlink()
            except OSError:
                pass
    except OSError as exc:
        _recovery_record_write_failed = True
        _recovery_record_write_error = str(exc)
        _recovery_failed_config = str(config_path)
        sys.stderr.write(
            "direct-migration recovery record write failed: {0}\n".format(exc)
        )
        try:
            recovery_write_failed_path(config_path).write_text(
                str(exc) + "\n", encoding="utf-8"
            )
        except OSError:
            pass


def _delete_key_refs(key_dir: Path, refs: List[str]) -> None:
    for ref in refs:
        if (
            not _SAFE_KEY_REF.fullmatch(str(ref or ""))
            or not str(ref).startswith("direct_service_direct_svc_")
        ):
            raise MigrationStateError("direct migration key reference is unsafe")
        path = key_dir / ref
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def recover_unreadable_config(
    config_path: Path, key_dir: Optional[Path] = None
) -> Optional[dict]:
    with migration_lock(config_path):
        journal = read_journal(config_path)
        resolved_key_dir = Path(key_dir) if key_dir is not None else infer_key_dir(config_path)
        if journal is not None:
            journal = _validated_journal(config_path, resolved_key_dir, journal)
        root = snapshot_dir(config_path)
        restored = None
        reason = ""
        phase = str((journal or {}).get("phase") or "")
        if phase in {PHASE_STAGING, PHASE_COMMITTING}:
            restored = restore_snapshot_tree(root / "pre", config_path, resolved_key_dir)
            reason = "in_flight_rollback"
            _delete_key_refs(resolved_key_dir, list((journal or {}).get("newKeyRefs") or []))
            cleanup_staging_dirs(resolved_key_dir, [(journal or {}).get("stagingDir") or ""])
        if restored is None:
            restored = restore_snapshot_tree(root / "committed", config_path, resolved_key_dir)
            if restored is not None:
                reason = "committed_snapshot"
        if restored is None:
            restored = restore_snapshot_tree(root / "pre", config_path, resolved_key_dir)
            if restored is not None:
                reason = "pre_migration_snapshot"
        if restored is None:
            backup = pre_backup_path(config_path)
            if backup.is_file():
                copy_file_fsync(backup, config_path)
                try:
                    restored = json.loads(config_path.read_text(encoding="utf-8"))
                    reason = "legacy_pre_direct_migration_file"
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    restored = None
        if restored is not None:
            write_recovery_record(config_path, reason)
        return restored


def finalize_committed(config_path: Path) -> None:
    pre = snapshot_dir(config_path) / "pre"
    backup = pre_backup_path(config_path)
    now = datetime.now(timezone.utc).timestamp()
    for path in (pre, backup):
        try:
            expired = now - path.stat().st_mtime >= SNAPSHOT_RETENTION_SECONDS
        except OSError:
            expired = False
        if not expired:
            continue
        if path.is_dir():
            shutil.rmtree(str(path), ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass


def reconcile_inflight(config_path: Path, key_dir: Path) -> None:
    with migration_lock(config_path):
        journal = read_journal(config_path)
        if journal is None:
            cleanup_staging_dirs(key_dir)
            return
        journal = _validated_journal(config_path, key_dir, journal)
        phase = str(journal.get("phase") or "")
        staging_dir = str(journal.get("stagingDir") or "")
        new_refs = list(journal.get("newKeyRefs") or [])
        if phase == PHASE_COMMITTED:
            finalize_committed(config_path)
            cleanup_staging_dirs(key_dir, [staging_dir])
            return
        if phase == PHASE_ROLLED_BACK:
            cleanup_staging_dirs(key_dir, [staging_dir])
            return
        staged_hash = str(journal.get("stagedConfigSha256") or "")
        current_hash = sha256_file(config_path) if config_path.exists() else None
        readable = False
        if config_path.exists() and current_hash:
            try:
                json.loads(config_path.read_text(encoding="utf-8"))
                readable = True
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                readable = False
        if readable and staged_hash and current_hash == staged_hash:
            try:
                write_committed_snapshot(config_path, key_dir)
                journal["phase"] = PHASE_COMMITTED
                write_journal(config_path, journal)
            except (OSError, json.JSONDecodeError, UnicodeError, ValueError):
                return
            finalize_committed(config_path)
            cleanup_staging_dirs(key_dir, [staging_dir])
            return
        restored = restore_snapshot_tree(
            snapshot_dir(config_path) / "pre", config_path, key_dir
        )
        if restored is None:
            raise MigrationStateError("direct migration pre snapshot is unavailable")
        _delete_key_refs(key_dir, new_refs)
        cleanup_staging_dirs(key_dir, [staging_dir])
        journal["phase"] = PHASE_ROLLED_BACK
        write_journal(config_path, journal)
