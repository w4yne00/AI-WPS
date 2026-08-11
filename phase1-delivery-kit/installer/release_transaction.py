#!/usr/bin/env python3
"""Durable compensating transactions for AI-WPS release generations."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
EXPECTED_COMPONENTS = (
    "adapter_release",
    "word_plugin",
    "excel_plugin",
    "ppt_plugin",
    "publish_manifest",
    "runtime_state_snapshot",
    "current_pointer",
)


class TransactionError(RuntimeError):
    pass


def _utc_now():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _lexists(path):
    return os.path.lexists(str(path))


def _remove_path(path):
    if not _lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(str(path))
    else:
        raise TransactionError("unsupported_path_type path={0}".format(path))


def _fsync_directory(path):
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_json(path, payload):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(".{0}.{1}.tmp".format(path.name, uuid.uuid4().hex))
    descriptor = os.open(
        str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        path.chmod(0o600)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise TransactionError("transaction_log_invalid path={0}".format(path))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise TransactionError("transaction_schema_invalid path={0}".format(path))
    return payload


def _hash_path(path):
    digest = hashlib.sha256()

    def add(value):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")

    if path.is_symlink():
        add("symlink")
        add(os.readlink(str(path)))
        return digest.hexdigest()
    if path.is_file():
        add("file")
        with path.open("rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()
    if not path.is_dir():
        raise TransactionError("component_path_missing path={0}".format(path))
    add("directory")
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_symlink():
            add("symlink:" + relative)
            add(os.readlink(str(child)))
        elif child.is_dir():
            add("directory:" + relative)
        elif child.is_file():
            add("file:" + relative)
            with child.open("rb") as source:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
        else:
            raise TransactionError(
                "unsupported_component_entry path={0}".format(child)
            )
    return digest.hexdigest()


def _absolute_path(value, label):
    path = Path(value)
    if not path.is_absolute():
        raise TransactionError("{0}_must_be_absolute".format(label))
    if path == Path("/"):
        raise TransactionError("{0}_root_rejected".format(label))
    return path


def _load_snapshot(
    backup_dir,
    snapshot_id,
    release_version=None,
    allow_degraded=False,
    allow_recovery=False,
):
    if not SAFE_ID.fullmatch(snapshot_id):
        raise TransactionError("candidate_snapshot_id_invalid")
    snapshot_dir = backup_dir / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        raise TransactionError("candidate_snapshot_manifest_missing")
    if not isinstance(manifest, dict):
        raise TransactionError("candidate_snapshot_manifest_invalid")
    validated = (
        manifest.get("valid") is True
        or (
            allow_degraded
            and manifest.get("coreStatus") == "ready"
            and manifest.get("writingPolicyStatus") == "degraded"
        )
        or (
            allow_recovery
            and manifest.get("copyVerified") is True
            and manifest.get("coreStatus") == "recovery"
        )
    )
    if (
        manifest.get("snapshotId") != snapshot_id
        or not validated
    ):
        raise TransactionError("candidate_snapshot_manifest_invalid")
    if release_version is not None and manifest.get("releaseVersion") != release_version:
        raise TransactionError("candidate_snapshot_release_mismatch")
    declared_files = manifest.get("files")
    if not isinstance(declared_files, list):
        raise TransactionError("candidate_snapshot_inventory_invalid")
    expected = {}
    for item in declared_files:
        if not isinstance(item, dict):
            raise TransactionError("candidate_snapshot_inventory_invalid")
        relative = str(item.get("path", ""))
        if (
            not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or relative in expected
        ):
            raise TransactionError("candidate_snapshot_inventory_invalid")
        expected[relative] = (
            str(item.get("sha256", "")),
            int(item.get("size", -1)),
        )
    actual = {}
    state_dir = snapshot_dir / "state"
    if not state_dir.is_dir():
        raise TransactionError("candidate_snapshot_state_missing")
    for path in sorted(state_dir.rglob("*")):
        if path.is_file():
            actual[path.relative_to(state_dir).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
            )
    if actual != expected:
        raise TransactionError("candidate_snapshot_inventory_mismatch")
    return manifest


def _prepare(arguments):
    transaction_dir = _absolute_path(arguments.transaction_dir, "transaction_dir")
    backup_dir = _absolute_path(arguments.backup_dir, "backup_dir")
    transaction_id = arguments.transaction_id
    release_version = arguments.release_version
    if not SAFE_ID.fullmatch(transaction_id):
        raise TransactionError("transaction_id_invalid")
    if not SAFE_ID.fullmatch(release_version):
        raise TransactionError("release_version_invalid")
    candidate_snapshot = backup_dir / arguments.candidate_snapshot_id
    _load_snapshot(
        backup_dir,
        arguments.candidate_snapshot_id,
        release_version,
        allow_degraded=True,
        allow_recovery=arguments.recovery_activation,
    )

    transaction_path = transaction_dir / (transaction_id + ".json")
    if _lexists(transaction_path):
        raise TransactionError("transaction_log_exists path={0}".format(transaction_path))
    components = []
    names = set()
    for name, candidate_value, target_value in arguments.component:
        if not SAFE_ID.fullmatch(name) or name in names:
            raise TransactionError("component_name_invalid name={0}".format(name))
        names.add(name)
        candidate = _absolute_path(candidate_value, "component_candidate")
        target = _absolute_path(target_value, "component_target")
        if candidate == target or candidate.parent != target.parent:
            raise TransactionError(
                "component_same_parent_required name={0}".format(name)
            )
        if not _lexists(candidate):
            raise TransactionError("component_candidate_missing name={0}".format(name))
        if not target.parent.is_dir():
            raise TransactionError("component_parent_missing name={0}".format(name))
        if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
            raise TransactionError("component_filesystem_mismatch name={0}".format(name))
        backup = target.parent / (
            ".ai-wps-{0}-{1}.previous".format(transaction_id, name)
        )
        displaced = target.parent / (
            ".ai-wps-{0}-{1}.displaced".format(transaction_id, name)
        )
        if _lexists(backup) or _lexists(displaced):
            raise TransactionError("component_recovery_path_exists name={0}".format(name))
        components.append(
            {
                "name": name,
                "candidate": str(candidate),
                "target": str(target),
                "backup": str(backup),
                "displaced": str(displaced),
                "candidateSha256": _hash_path(candidate),
                "hadTarget": _lexists(target),
                "phase": "pending",
                "verified": False,
            }
        )
    if not components:
        raise TransactionError("transaction_components_required")
    if tuple(item["name"] for item in components) != EXPECTED_COMPONENTS:
        raise TransactionError("release_generation_components_invalid")
    state_candidate = next(
        Path(item["candidate"])
        for item in components
        if item["name"] == "runtime_state_snapshot"
    )
    if _hash_path(state_candidate) != _hash_path(candidate_snapshot / "state"):
        raise TransactionError("candidate_snapshot_state_mismatch")
    adapter_target = next(
        Path(item["target"])
        for item in components
        if item["name"] == "adapter_release"
    )
    current_candidate = next(
        Path(item["candidate"])
        for item in components
        if item["name"] == "current_pointer"
    )
    if (
        not current_candidate.is_symlink()
        or os.readlink(str(current_candidate)) != str(adapter_target)
    ):
        raise TransactionError("current_pointer_candidate_invalid")

    transaction = {
        "schemaVersion": SCHEMA_VERSION,
        "transactionId": transaction_id,
        "releaseVersion": release_version,
        "candidateSnapshotId": arguments.candidate_snapshot_id,
        "candidateSnapshotSha256": _hash_path(candidate_snapshot),
        "activationMode": (
            "recovery" if arguments.recovery_activation else "upgrade"
        ),
        "backupDir": str(backup_dir),
        "createdAt": _utc_now(),
        "updatedAt": _utc_now(),
        "status": "prepared",
        "components": components,
    }
    _write_json(transaction_path, transaction)
    return transaction_path, transaction


def _switch(transaction_path, fail_after=None):
    transaction = _read_json(transaction_path)
    if transaction.get("status") != "prepared":
        raise TransactionError(
            "transaction_not_prepared status={0}".format(transaction.get("status"))
        )
    transaction["status"] = "switching"
    transaction["updatedAt"] = _utc_now()
    _write_json(transaction_path, transaction)
    for component in transaction["components"]:
        candidate = Path(component["candidate"])
        target = Path(component["target"])
        backup = Path(component["backup"])
        component["phase"] = "backing_up"
        transaction["updatedAt"] = _utc_now()
        _write_json(transaction_path, transaction)
        if component["hadTarget"]:
            if not _lexists(target):
                raise TransactionError(
                    "component_target_disappeared name={0}".format(component["name"])
                )
            os.replace(str(target), str(backup))
            _fsync_directory(target.parent)
        component["phase"] = "backup_created"
        transaction["updatedAt"] = _utc_now()
        _write_json(transaction_path, transaction)
        if fail_after == "after_backup:{0}".format(component["name"]):
            os._exit(97)
        os.replace(str(candidate), str(target))
        _fsync_directory(target.parent)
        component["phase"] = "switched"
        transaction["updatedAt"] = _utc_now()
        _write_json(transaction_path, transaction)
        if fail_after == "after_switch:{0}".format(component["name"]):
            os._exit(97)
    transaction["status"] = "awaiting_finalization"
    transaction["updatedAt"] = _utc_now()
    _write_json(transaction_path, transaction)
    return transaction


def _rollback_components(transaction_path, transaction, reason):
    transaction["status"] = "rolling_back"
    transaction["rollbackReason"] = reason
    transaction["updatedAt"] = _utc_now()
    _write_json(transaction_path, transaction)
    for component in reversed(transaction["components"]):
        candidate = Path(component["candidate"])
        target = Path(component["target"])
        backup = Path(component["backup"])
        displaced = Path(component["displaced"])
        if component.get("hadTarget"):
            if _lexists(backup):
                if _lexists(target):
                    if _lexists(displaced):
                        _remove_path(displaced)
                    os.replace(str(target), str(displaced))
                os.replace(str(backup), str(target))
            elif not _lexists(target):
                raise TransactionError(
                    "component_previous_generation_missing name={0}".format(
                        component["name"]
                    )
                )
        elif _lexists(target):
            if _lexists(displaced):
                _remove_path(displaced)
            os.replace(str(target), str(displaced))
        if _lexists(displaced):
            _remove_path(displaced)
        if _lexists(candidate):
            _remove_path(candidate)
        component["phase"] = "rolled_back"
        component["verified"] = False
        transaction["updatedAt"] = _utc_now()
        _write_json(transaction_path, transaction)
    candidate_snapshot = (
        Path(transaction["backupDir"]) / transaction["candidateSnapshotId"]
    )
    if _lexists(candidate_snapshot):
        _remove_path(candidate_snapshot)
    transaction["status"] = "rolled_back"
    transaction["updatedAt"] = _utc_now()
    _write_json(transaction_path, transaction)
    return transaction


def _finalize(transaction_path, defer_commit=False, external_commit=False):
    transaction = _read_json(transaction_path)
    expected_status = "ready_to_commit" if external_commit else "awaiting_finalization"
    if transaction.get("status") != expected_status:
        raise TransactionError(
            "transaction_not_switchable status={0}".format(transaction.get("status"))
        )
    try:
        candidate_snapshot = (
            Path(transaction["backupDir"]) / transaction["candidateSnapshotId"]
        )
        _load_snapshot(
            Path(transaction["backupDir"]),
            transaction["candidateSnapshotId"],
            transaction["releaseVersion"],
            allow_degraded=True,
            allow_recovery=transaction.get("activationMode") == "recovery",
        )
        if _hash_path(candidate_snapshot) != transaction.get(
            "candidateSnapshotSha256"
        ):
            raise TransactionError("candidate_snapshot_verification_failed")
        for component in transaction["components"]:
            target = Path(component["target"])
            if not _lexists(target):
                raise TransactionError(
                    "component_target_missing name={0}".format(component["name"])
                )
            if (
                external_commit
                and component["name"] == "runtime_state_snapshot"
            ):
                if component.get("verified") is not True:
                    raise TransactionError(
                        "component_not_preverified name={0}".format(component["name"])
                    )
                continue
            if _hash_path(target) != component["candidateSha256"]:
                raise TransactionError(
                    "component_verification_failed name={0}".format(component["name"])
                )
            component["verified"] = True
    except TransactionError as error:
        transaction["status"] = "verification_failed"
        transaction["verificationError"] = str(error)
        transaction["updatedAt"] = _utc_now()
        _write_json(transaction_path, transaction)
        raise
    if defer_commit:
        transaction["status"] = "ready_to_commit"
        transaction["verifiedAt"] = _utc_now()
        transaction["updatedAt"] = transaction["verifiedAt"]
        _write_json(transaction_path, transaction)
        return transaction
    if transaction.get("activationMode") == "recovery":
        transaction["status"] = "recovery_activated"
        transaction["activatedAt"] = _utc_now()
        transaction["updatedAt"] = transaction["activatedAt"]
    else:
        transaction["status"] = "committed"
        transaction["committedAt"] = _utc_now()
        transaction["updatedAt"] = transaction["committedAt"]
    _write_json(transaction_path, transaction)
    for component in transaction["components"]:
        _remove_path(Path(component["backup"]))
        _remove_path(Path(component["candidate"]))
        _remove_path(Path(component["displaced"]))
    return transaction


def _parser():
    parser = argparse.ArgumentParser(
        description="Switch and compensate complete AI-WPS release generations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--transaction-dir", required=True)
    prepare.add_argument("--transaction-id", required=True)
    prepare.add_argument("--release-version", required=True)
    prepare.add_argument("--backup-dir", required=True)
    prepare.add_argument("--candidate-snapshot-id", required=True)
    prepare.add_argument("--recovery-activation", action="store_true")
    prepare.add_argument(
        "--component", nargs=3, action="append", metavar=("NAME", "CANDIDATE", "TARGET"), required=True
    )
    for command in ("switch", "finalize", "commit", "recover", "rollback"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("transaction_log")
        if command == "switch":
            subparser.add_argument("--fail-after")
        elif command == "finalize":
            subparser.add_argument("--defer-commit", action="store_true")
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            transaction_path, transaction = _prepare(arguments)
        else:
            transaction_path = _absolute_path(
                arguments.transaction_log, "transaction_log"
            )
            if arguments.command == "switch":
                transaction = _switch(transaction_path, arguments.fail_after)
            elif arguments.command == "finalize":
                transaction = _finalize(
                    transaction_path, defer_commit=arguments.defer_commit
                )
            elif arguments.command == "commit":
                transaction = _finalize(
                    transaction_path,
                    defer_commit=False,
                    external_commit=True,
                )
            else:
                current = _read_json(transaction_path)
                if current.get("status") in {
                    "committed",
                    "recovery_activated",
                    "rolled_back",
                }:
                    transaction = current
                else:
                    transaction = _rollback_components(
                        transaction_path, current, arguments.command
                    )
        print(
            json.dumps(
                {
                    "success": True,
                    "status": transaction["status"],
                    "transactionLog": str(transaction_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except TransactionError as error:
        print(
            json.dumps(
                {"success": False, "errorCode": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"success": False, "errorCode": "RELEASE_TRANSACTION_FAILED"},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
