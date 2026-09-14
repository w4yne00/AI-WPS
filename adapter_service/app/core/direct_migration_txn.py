import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


JOURNAL_NAME = "adapter-direct-migration-journal.json"
RECOVERY_RECORD_NAME = "adapter-direct-migration-recovery.json"
RECOVERY_WRITE_FAILED_NAME = "adapter-direct-migration-recovery.write-failed"
SNAPSHOT_SUFFIX = ".direct-migration-snapshot"
PRE_BACKUP_SUFFIX = ".pre-direct-migration"
STAGE_DIR_PREFIX = ".direct-migration-stage-"

PHASE_STAGING = "staging"
PHASE_COMMITTING = "committing"
PHASE_COMMITTED = "committed"
PHASE_ROLLED_BACK = "rolled_back"

_recovery_record_write_failed = False
_recovery_record_write_error = ""
_recovery_failed_config = ""


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
        os.replace(str(temporary), str(destination))
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
    return sorted(name for name in names if name)


def _write_snapshot_tree(
    target: Path,
    config_bytes: bytes,
    key_dir: Path,
    key_names: List[str],
) -> List[str]:
    if target.exists():
        shutil.rmtree(str(target), ignore_errors=True)
    keys_dir = target / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    adapter = target / "adapter.json"
    adapter.write_bytes(config_bytes)
    with open(str(adapter), "rb") as handle:
        os.fsync(handle.fileno())
    copied = []
    for name in key_names:
        source = key_dir / name
        if source.is_file():
            copy_file_fsync(source, keys_dir / name)
            copied.append(name)
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
    copied = _write_snapshot_tree(root / "committed", config_bytes, key_dir, key_names)
    fsync_directory(root)
    return {
        "configSha256": sha256_bytes(config_bytes),
        "keyNames": copied,
        "keyDir": str(key_dir),
    }


def restore_snapshot_tree(tree: Path, config_path: Path, key_dir: Path) -> Optional[dict]:
    adapter = tree / "adapter.json"
    if not adapter.is_file():
        return None
    key_dir.mkdir(parents=True, exist_ok=True)
    copy_file_fsync(adapter, config_path)
    keys_dir = tree / "keys"
    if keys_dir.is_dir():
        for source in keys_dir.iterdir():
            if source.is_file():
                copy_file_fsync(source, key_dir / source.name)
    return json.loads(config_path.read_text(encoding="utf-8"))


def read_journal(config_path: Path) -> Optional[dict]:
    path = journal_path(config_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_journal(config_path: Path, payload: dict) -> None:
    write_json_atomic(journal_path(config_path), payload)


def infer_key_dir(config_path: Path, journal: Optional[dict] = None) -> Path:
    if journal and journal.get("keyDir"):
        return Path(str(journal["keyDir"]))
    sibling = config_path.parent / "provider_api_keys"
    if sibling.exists() or not (config_path.parent / "run").exists():
        return sibling
    return config_path.parent / "run" / "provider_api_keys"


def cleanup_staging_dirs(key_dir: Path, extra_dirs: Optional[List[str]] = None) -> None:
    parents = {key_dir.parent, key_dir}
    for extra in extra_dirs or []:
        if extra:
            parents.add(Path(extra).parent)
            target = Path(extra)
            if target.exists():
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
        path = key_dir / ref
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def recover_unreadable_config(config_path: Path) -> Optional[dict]:
    journal = read_journal(config_path)
    key_dir = infer_key_dir(config_path, journal)
    root = snapshot_dir(config_path)
    restored = None
    reason = ""
    phase = str((journal or {}).get("phase") or "")
    if phase in {PHASE_STAGING, PHASE_COMMITTING}:
        restored = restore_snapshot_tree(root / "pre", config_path, key_dir)
        reason = "in_flight_rollback"
        _delete_key_refs(key_dir, list((journal or {}).get("newKeyRefs") or []))
        cleanup_staging_dirs(key_dir, [(journal or {}).get("stagingDir") or ""])
    if restored is None:
        restored = restore_snapshot_tree(root / "committed", config_path, key_dir)
        if restored is not None:
            reason = "committed_snapshot"
    if restored is None:
        restored = restore_snapshot_tree(root / "pre", config_path, key_dir)
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


def reconcile_inflight(config_path: Path, key_dir: Path) -> None:
    journal = read_journal(config_path)
    if journal is None:
        cleanup_staging_dirs(key_dir)
        return
    phase = str(journal.get("phase") or "")
    staging_dir = str(journal.get("stagingDir") or "")
    new_refs = list(journal.get("newKeyRefs") or [])
    if phase == PHASE_COMMITTED:
        cleanup_staging_dirs(key_dir, [staging_dir])
        return
    if phase not in {PHASE_STAGING, PHASE_COMMITTING}:
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
        except (OSError, json.JSONDecodeError, UnicodeError, ValueError):
            pass
        journal["phase"] = PHASE_COMMITTED
        try:
            write_journal(config_path, journal)
        except OSError:
            pass
        cleanup_staging_dirs(key_dir, [staging_dir])
        return
    restore_snapshot_tree(snapshot_dir(config_path) / "pre", config_path, key_dir)
    _delete_key_refs(key_dir, new_refs)
    cleanup_staging_dirs(key_dir, [staging_dir])
    journal["phase"] = PHASE_ROLLED_BACK
    try:
        write_journal(config_path, journal)
    except OSError:
        pass
