#!/usr/bin/env python3
"""Run the v0.26.0-preview.1 delivery and installation lifecycle gate."""

import argparse
import json
import os
import pwd
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Callable, Dict, Optional, Tuple


VERSION = "0.26.0-preview.1"
BASELINE_VERSION = "0.25.3-alpha"
SCENARIOS = [
    "runtime_gate",
    "fresh_install",
    "legacy_boundary",
    "preview_upgrade",
    "preview_legacy_direct_migration",
]


class LifecycleFailure(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise LifecycleFailure(code)


def archive_manifest(archive_path: Path) -> Dict:
    if not archive_path.is_file():
        raise LifecycleFailure("BASELINE_ARCHIVE_MISSING {0}".format(archive_path))
    try:
        with tarfile.open(str(archive_path), "r:gz") as archive:
            member = next(
                item
                for item in archive.getmembers()
                if Path(item.name).name == "release-manifest.json" and item.isfile()
            )
            extracted = archive.extractfile(member)
            require(extracted is not None, "ARCHIVE_MANIFEST_UNREADABLE")
            value = json.loads(extracted.read().decode("utf-8"))
    except (OSError, tarfile.TarError, StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifecycleFailure("ARCHIVE_MANIFEST_INVALID {0}".format(archive_path.name)) from exc
    require(isinstance(value, dict), "ARCHIVE_MANIFEST_INVALID")
    return value


def audit_delivery(delivery_root: Path) -> None:
    for relative in (
        "scripts/audit_delivery.py",
        "scripts/audit_v0260_preview1_delivery.py",
    ):
        auditor = delivery_root / relative
        require(auditor.is_file(), "DELIVERY_AUDITOR_MISSING {0}".format(relative))
        result = subprocess.run(
            [sys.executable, str(auditor), str(delivery_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            result.returncode == 0,
            result.stdout.strip() or result.stderr.strip() or "DELIVERY_AUDIT_FAILED",
        )
        print("lifecycle_audit=passed script={0}".format(relative))


def stage_external_installer_dependencies(delivery_root: Path) -> bool:
    external_value = os.environ.get(
        "AI_WPS_PYTHON38_GATE_SITE_PACKAGES", ""
    ).strip()
    if not external_value:
        return False
    external_root = Path(external_value).resolve()
    require(
        external_root.is_dir(),
        "PYTHON38_GATE_DEPENDENCIES_MISSING {0}".format(external_root),
    )
    installer = delivery_root / "installer/install_private_runtime.sh"
    require(installer.is_file(), "PRIVATE_RUNTIME_INSTALLER_MISSING")
    installer.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DEPS_DIR="${2:-}"
PRIVATE_RUNTIME_DIR="${4:-}"
EXTERNAL_ROOT="${AI_WPS_PYTHON38_GATE_SITE_PACKAGES:-}"

[ -d "$RUNTIME_DEPS_DIR" ] || exit 1
[ -s "$RUNTIME_DEPS_DIR/requirements-lock.txt" ] || exit 1
[ -d "$EXTERNAL_ROOT" ] || exit 1
[ -n "$PRIVATE_RUNTIME_DIR" ] || exit 1
case "$PRIVATE_RUNTIME_DIR" in
  /*) ;;
  *) exit 1 ;;
esac
[ ! -e "$PRIVATE_RUNTIME_DIR" ] || exit 1
mkdir -p "$PRIVATE_RUNTIME_DIR"
cp -R "$EXTERNAL_ROOT"/. "$PRIVATE_RUNTIME_DIR"/
cp "$RUNTIME_DEPS_DIR/requirements-lock.txt" "$PRIVATE_RUNTIME_DIR/requirements-lock.txt"
printf '%s\n' "private_runtime=ready source=external_gate_fixture path=$PRIVATE_RUNTIME_DIR"
""",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    print("installer_runtime_dependencies=external_fixture")
    return True


def reserve_install_ports(reserve_port: Callable[[], int]) -> Tuple[int, int]:
    port = reserve_port()
    candidate_port = reserve_port()
    while candidate_port == port:
        candidate_port = reserve_port()
    return port, candidate_port


def install_environment(
    root: Path, port: int, candidate_port: int
) -> Dict[str, str]:
    home = root / "home"
    install_root = home / "ai-wps"
    jsaddons = home / "jsaddons"
    target_tools = root / "target-tools"
    home.mkdir(parents=True, exist_ok=True)
    install_root.mkdir(parents=True, exist_ok=True)
    jsaddons.mkdir(parents=True, exist_ok=True)
    target_tools.mkdir(parents=True, exist_ok=True)
    target_home_lookup = target_tools / "getent"
    target_home_lookup.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "passwd" ] && [ "${2:-}" = "${AI_WPS_TARGET_USER:-}" ]; then\n'
        '  printf \'%s:x:%s:%s::%s:/bin/sh\\n\' "$AI_WPS_TARGET_USER" "$(id -u)" "$(id -g)" "$HOME"\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    target_home_lookup.chmod(0o755)
    environment = dict(os.environ)
    for variable in (
        "SUDO_USER",
        "SUDO_UID",
        "AI_WPS_STATE_DIR",
        "AI_WPS_BACKUP_DIR",
        "AI_WPS_VAR_DIR",
        "AI_WPS_TRANSACTION_FAIL_AFTER",
    ):
        environment.pop(variable, None)
    environment.update(
        {
            "HOME": str(home),
            "AI_WPS_TARGET_USER": pwd.getpwuid(os.getuid()).pw_name,
            "AI_WPS_INSTALL_ROOT": str(install_root),
            "WPS_JSADDONS_DIR": str(jsaddons),
            "PATH": os.pathsep.join(
                (str(target_tools), environment.get("PATH", ""))
            ),
            "AI_WPS_SYSTEMD_SERVICE_FILE": str(root / "no-systemd/ai-wps.service"),
            "AI_WPS_CANDIDATE_PORT": str(candidate_port),
            "PORT": str(port),
            "PYTHON_BIN": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def run_installer(
    delivery_root: Path,
    environment: Dict[str, str],
    expected_returncode: int = 0,
    updates: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    child_environment = dict(environment)
    if updates:
        child_environment.update(updates)
    installer_command = [
        "bash",
        str(delivery_root / "installer/install_ai_wps.sh"),
        "--target-user",
        child_environment["AI_WPS_TARGET_USER"],
    ]
    result = subprocess.run(
        installer_command,
        env=child_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != expected_returncode:
        raise LifecycleFailure(
            "INSTALL_RESULT_INVALID expected={0} actual={1} output={2}".format(
                expected_returncode,
                result.returncode,
                (result.stdout + result.stderr)[-2400:],
            )
        )
    return result


def stop_adapter(environment: Dict[str, str]) -> None:
    install_root = Path(environment["AI_WPS_INSTALL_ROOT"])
    stop_script = install_root / "current/scripts/stop_adapter.sh"
    if stop_script.is_file():
        subprocess.run(
            ["bash", str(stop_script), environment["PORT"]],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )


def adapter_process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running_adapter_pid(environment: Dict[str, str]) -> int:
    pid_path = Path(environment["AI_WPS_INSTALL_ROOT"]) / "var/run/adapter.pid"
    require(pid_path.is_file(), "ADAPTER_PID_MISSING")
    value = pid_path.read_text(encoding="utf-8").strip()
    require(value.isdigit(), "ADAPTER_PID_INVALID")
    pid = int(value)
    require(adapter_process_is_running(pid), "ADAPTER_PROCESS_NOT_RUNNING")
    return pid


def seed_upgrade_replacement_sentinels(environment: Dict[str, str]):
    install_root = Path(environment["AI_WPS_INSTALL_ROOT"])
    roots = [install_root / "current"]
    jsaddons = Path(environment["WPS_JSADDONS_DIR"])
    roots.extend(
        jsaddons / plugin_name
        for plugin_name in (
            "wps-ai-assistant_1.0.0",
            "wps-ai-assistant-et_1.0.0",
            "wps-ai-assistant-wpp_1.0.0",
        )
    )
    sentinels = []
    for root in roots:
        require(root.is_dir(), "UPGRADE_REPLACEMENT_ROOT_MISSING {0}".format(root))
        sentinel = root / ".upgrade-replacement-sentinel"
        sentinel.write_text("old-generation\n", encoding="utf-8")
        sentinels.append(sentinel)
    return sentinels


def verify_upgrade_replacement(sentinels) -> None:
    require(
        all(not sentinel.exists() for sentinel in sentinels),
        "UPGRADE_FILES_NOT_REPLACED",
    )


def seed_upgrade_persistent_data(environment: Dict[str, str]):
    install_root = Path(environment["AI_WPS_INSTALL_ROOT"])
    state_root = install_root / "state"
    modern_key = state_root / "provider_api_keys/upgrade-sentinel"
    modern_key.parent.mkdir(parents=True, exist_ok=True)
    modern_key.write_bytes(b"modern-key-preserve\n")
    modern_key.chmod(0o600)
    history = install_root / "var/history/upgrade-sentinel.json"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(b'{"history":"preserve"}\n')
    backup = install_root / "backups/upgrade-sentinel.bin"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(b"backup-preserve\n")
    paths = (
        state_root / "provider_api_key",
        modern_key,
        state_root / "writing_policies.db",
        history,
        backup,
    )
    for path in paths:
        require(path.is_file(), "UPGRADE_PERSISTENT_FILE_MISSING {0}".format(path))
    return {path: path.read_bytes() for path in paths}


def verify_upgrade_persistent_data(expected) -> None:
    require(
        all(path.is_file() and path.read_bytes() == content for path, content in expected.items()),
        "UPGRADE_PERSISTENT_DATA_CHANGED",
    )


def verify_upgrade_rollback_replacement(sentinels) -> None:
    require(
        all(
            sentinel.is_file()
            and sentinel.read_text(encoding="utf-8") == "old-generation\n"
            for sentinel in sentinels
        ),
        "UPGRADE_ROLLBACK_FILES_NOT_RESTORED",
    )


def verify_latest_transaction_rolled_back(environment: Dict[str, str]) -> None:
    transaction_dir = Path(environment["AI_WPS_INSTALL_ROOT"]) / "var/transactions"
    transactions = list(transaction_dir.glob("*.json"))
    require(bool(transactions), "UPGRADE_ROLLBACK_TRANSACTION_MISSING")
    latest = max(transactions, key=lambda path: path.stat().st_mtime_ns)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    require(payload.get("status") == "rolled_back", "UPGRADE_TRANSACTION_NOT_ROLLED_BACK")


def verify_install(environment: Dict[str, str]) -> None:
    install_root = Path(environment["AI_WPS_INSTALL_ROOT"])
    current = install_root / "current"
    release = install_root / "releases" / VERSION
    require(current.is_symlink() and current.samefile(release), "CURRENT_RELEASE_INVALID")
    transactions = list((install_root / "var/transactions").glob("*.json"))
    require(bool(transactions), "TRANSACTION_LOG_MISSING")
    latest = max(transactions, key=lambda path: path.stat().st_mtime_ns)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    require(payload.get("status") == "committed", "TRANSACTION_NOT_COMMITTED")


def legacy_fixture(legacy_root: Path) -> Dict[Path, bytes]:
    (legacy_root / "config").mkdir(parents=True)
    (legacy_root / "run").mkdir()
    fixtures = {
        Path("config/adapter.json"): b'{"providerApiKey":"must-not-be-read"}\n',
        Path("run/provider_api_key"): b"legacy-secret\n",
        Path("run/writing_policies.db"): b"legacy-database",
    }
    for relative, content in fixtures.items():
        path = legacy_root / relative
        path.write_bytes(content)
        path.chmod(0o600)
    return fixtures


def assert_files_unchanged(root: Path, expected: Dict[Path, bytes]) -> None:
    actual = {
        relative: (root / relative).read_bytes()
        for relative in expected
        if (root / relative).is_file()
    }
    require(actual == expected, "LEGACY_DATA_CHANGED")


def run_fresh_install(delivery_root: Path, temp_root: Path, reserve_port) -> None:
    root = temp_root / "fresh"
    environment = install_environment(root, *reserve_install_ports(reserve_port))
    result = run_installer(delivery_root, environment)
    try:
        verify_install(environment)
        require("ai_wps_install_done=true" in result.stdout, "FRESH_INSTALL_NOT_DONE")
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=fresh_install passed")


def run_legacy_boundary(delivery_root: Path, temp_root: Path, reserve_port) -> None:
    root = temp_root / "legacy-boundary"
    environment = install_environment(root, *reserve_install_ports(reserve_port))
    legacy_root = Path(environment["HOME"]) / "ai-wps-phase1"
    fixtures = legacy_fixture(legacy_root)
    result = run_installer(delivery_root, environment)
    try:
        verify_install(environment)
        for marker in (
            "legacy_phase1_install_detected=true",
            "legacy_phase1_action=read_only",
            "manual_reinstall_required=true",
            "manual_reconfigure_required=true",
            "legacy_runtime_data_migrated=false",
            "legacy_install_deleted=false",
        ):
            require(marker in result.stdout, "LEGACY_BOUNDARY_MARKER_MISSING {0}".format(marker))
        assert_files_unchanged(legacy_root, fixtures)
        new_root = Path(environment["AI_WPS_INSTALL_ROOT"])
        require(
            all(
                b"legacy-secret" not in path.read_bytes()
                for path in new_root.rglob("*")
                if path.is_file()
            ),
            "LEGACY_SECRET_IMPORTED",
        )
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=legacy_boundary passed")


def run_preview_upgrade(delivery_root: Path, temp_root: Path, reserve_port) -> None:
    root = temp_root / "preview-upgrade"
    environment = install_environment(root, *reserve_install_ports(reserve_port))
    run_installer(delivery_root, environment)
    old_pid = running_adapter_pid(environment)
    replacement_sentinels = seed_upgrade_replacement_sentinels(environment)
    state_root = Path(environment["AI_WPS_INSTALL_ROOT"]) / "state"
    adapter_path = state_root / "adapter.json"
    adapter_content = b'{"previewSentinel":"preserve-me"}\n'
    adapter_path.write_bytes(adapter_content)
    key_path = state_root / "provider_api_key"
    key_content = b"preview-key-ref\n"
    key_path.write_bytes(key_content)
    key_path.chmod(0o600)
    persistent_data = seed_upgrade_persistent_data(environment)

    result = run_installer(delivery_root, environment)
    try:
        verify_install(environment)
        new_pid = running_adapter_pid(environment)
        require(new_pid != old_pid, "UPGRADE_ADAPTER_PID_NOT_REPLACED")
        require(
            not adapter_process_is_running(old_pid),
            "UPGRADE_OLD_ADAPTER_STILL_RUNNING",
        )
        verify_upgrade_replacement(replacement_sentinels)
        markers = (
            "adapter_state_transition_lock=stopped",
            "release_generation=switched",
            "adapter_start=uvicorn",
        )
        positions = tuple(result.stdout.find(marker) for marker in markers)
        require(
            all(position >= 0 for position in positions)
            and positions == tuple(sorted(positions)),
            "UPGRADE_INSTALL_SEQUENCE_INVALID",
        )
        require("ai_wps_install_done=true" in result.stdout, "PREVIEW_UPGRADE_NOT_DONE")
        preserved_config = json.loads(adapter_path.read_text(encoding="utf-8"))
        expected_config = json.loads(adapter_content.decode("utf-8"))
        require(
            isinstance(preserved_config, dict)
            and isinstance(expected_config, dict)
            and all(
                key in preserved_config and preserved_config[key] == value
                for key, value in expected_config.items()
            ),
            "PREVIEW_CONFIG_NOT_PRESERVED",
        )
        require(key_path.read_bytes() == key_content, "PREVIEW_KEY_NOT_PRESERVED")
        verify_upgrade_persistent_data(persistent_data)

        rollback_sentinels = seed_upgrade_replacement_sentinels(environment)
        stable_pid = new_pid
        run_installer(
            delivery_root,
            environment,
            expected_returncode=1,
            updates={"AI_WPS_TRANSACTION_FAIL_AFTER": "after_switch:word_plugin"},
        )
        rollback_pid = running_adapter_pid(environment)
        require(rollback_pid != stable_pid, "UPGRADE_ROLLBACK_PID_NOT_REPLACED")
        require(
            not adapter_process_is_running(stable_pid),
            "UPGRADE_FAILED_CANDIDATE_STILL_RUNNING",
        )
        verify_upgrade_rollback_replacement(rollback_sentinels)
        verify_upgrade_persistent_data(persistent_data)
        verify_latest_transaction_rolled_back(environment)
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=preview_upgrade passed")


def seed_legacy_direct_state(state_root: Path) -> None:
    keys = state_root / "provider_api_keys"
    keys.mkdir(parents=True, exist_ok=True)
    payload = {
        "modelConfigurations": {
            "legacy_write": {
                "id": "legacy_write",
                "taskType": "word.smart_write",
                "name": "旧直连编写",
                "accessMethod": "direct_model",
                "serviceBaseUrl": "https://api.example.com/v1",
                "apiKeyRef": "key_write",
                "modelName": "glm-5.2",
                "temperature": 0.2,
                "maxOutputTokens": 2048,
                "contextWindowTokens": 32000,
                "imageInputMode": "disabled",
            }
        },
        "activeModelConfigurations": {"word.smart_write": "legacy_write"},
    }
    (state_root / "adapter.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (keys / "key_write").write_text("sk-delivery-live\n", encoding="utf-8")
    (keys / "key_write").chmod(0o600)


def seed_legacy_direct_over_limit_state(state_root: Path) -> None:
    keys = state_root / "provider_api_keys"
    keys.mkdir(parents=True, exist_ok=True)
    tasks = [
        "word.smart_write",
        "word.smart_imitation",
        "word.document_review",
        "excel.analysis",
        "excel.formula_assistant",
        "ppt.slide_assistant",
    ]
    configurations = {}
    active = {}
    for index, task_type in enumerate(tasks):
        config_id = "legacy_limit_{0}".format(index)
        key_ref = "key_limit_{0}".format(index)
        configurations[config_id] = {
            "id": config_id,
            "taskType": task_type,
            "name": "超限档案 {0}".format(index),
            "accessMethod": "direct_model",
            "serviceBaseUrl": "https://svc{0}.example.com/v1".format(index),
            "apiKeyRef": key_ref,
            "modelName": "model-{0}".format(index),
            "temperature": 0.1,
            "maxOutputTokens": 1024,
            "contextWindowTokens": 8000,
            "imageInputMode": "disabled",
        }
        (keys / key_ref).write_text("sk-limit-{0}\n".format(index), encoding="utf-8")
        active[task_type] = config_id
    payload = {
        "modelConfigurations": configurations,
        "activeModelConfigurations": active,
    }
    (state_root / "adapter.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_direct_store(adapter_root: Path):
    adapter = str(adapter_root)
    if adapter not in sys.path:
        sys.path.insert(0, adapter)
    from app.services.direct_services import DirectServiceStore
    from app.services.provider_client import ProviderClient

    return DirectServiceStore, ProviderClient


def verify_legacy_direct_migration(state_root: Path, adapter_root: Path) -> None:
    DirectServiceStore, ProviderClient = _load_direct_store(adapter_root)
    config_path = state_root / "adapter.json"
    key_dir = state_root / "provider_api_keys"
    store = DirectServiceStore(config_path, key_dir)
    result = store.list_services()
    require(
        result.get("legacyDirectMigration", {}).get("status") in {"completed", "pending_manual"},
        "LEGACY_DIRECT_MIGRATION_NOT_COMPLETED",
    )
    client = ProviderClient(direct_service_store=store)
    auth = client.resolve_task_auth("word.smart_write")
    require(auth.get("apiKey") == "sk-delivery-live", "LEGACY_DIRECT_AUTH_MISMATCH")
    require(auth.get("modelName") == "glm-5.2", "LEGACY_DIRECT_MODEL_MISMATCH")
    config_path.write_text("{", encoding="utf-8")
    recovered_store = DirectServiceStore(config_path, key_dir)
    recovered_auth = ProviderClient(direct_service_store=recovered_store).resolve_task_auth(
        "word.smart_write"
    )
    require(
        recovered_auth.get("apiKey") == "sk-delivery-live",
        "LEGACY_DIRECT_RECOVERY_AUTH_MISMATCH",
    )


def verify_legacy_direct_over_limit(state_root: Path, adapter_root: Path) -> None:
    DirectServiceStore, _unused = _load_direct_store(adapter_root)
    store = DirectServiceStore(
        state_root / "adapter.json",
        state_root / "provider_api_keys",
    )
    result = store.list_services()
    require(
        result.get("legacyDirectMigration", {}).get("status") == "restricted",
        "LEGACY_DIRECT_LIMIT_NOT_RESTRICTED",
    )
    payload = json.loads((state_root / "adapter.json").read_text(encoding="utf-8"))
    require(
        len(payload.get("modelConfigurations") or {}) == 6,
        "LEGACY_DIRECT_LIMIT_DATA_LOST",
    )


def run_preview_legacy_direct_migration(
    delivery_root: Path, temp_root: Path, reserve_port
) -> None:
    root = temp_root / "preview-legacy-direct"
    environment = install_environment(root, *reserve_install_ports(reserve_port))
    run_installer(delivery_root, environment)
    try:
        stop_adapter(environment)
        state_root = Path(environment["AI_WPS_INSTALL_ROOT"]) / "state"
        adapter_root = Path(environment["AI_WPS_INSTALL_ROOT"]) / "current" / "adapter_service"
        if not adapter_root.is_dir():
            adapter_root = delivery_root / "adapter_service"
        require(adapter_root.is_dir(), "PACKAGED_ADAPTER_MISSING")
        seed_legacy_direct_over_limit_state(state_root)
        verify_legacy_direct_over_limit(state_root, adapter_root)
        seed_legacy_direct_state(state_root)
        verify_legacy_direct_migration(state_root, adapter_root)
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=preview_legacy_direct_migration passed")


def run_gate(
    archive_path: Path,
    expected_version: str,
    baseline_archive: Path,
    baseline_version: str,
) -> None:
    require(expected_version == VERSION, "PREVIEW_VERSION_REQUIRED")
    require(baseline_version == BASELINE_VERSION, "BASELINE_VERSION_REQUIRED")
    baseline = archive_manifest(baseline_archive)
    require(baseline.get("version") == baseline_version, "BASELINE_VERSION_INVALID")
    require(
        baseline.get("deliveryPolicy", {}).get("status") == "candidate",
        "BASELINE_NOT_CANDIDATE",
    )

    import python38_delivery_runtime_gate as runtime_gate

    runtime_gate.require_python38()
    with tempfile.TemporaryDirectory(prefix="ai-wps-preview1-lifecycle-") as temp_dir:
        temp_root = Path(temp_dir)
        delivery_root = runtime_gate.safe_extract(archive_path, temp_root / "delivery")
        audit_delivery(delivery_root)
        runtime_gate.run_gate(archive_path, expected_version)
        stage_external_installer_dependencies(delivery_root)
        run_fresh_install(delivery_root, temp_root, runtime_gate.reserve_port)
        run_legacy_boundary(delivery_root, temp_root, runtime_gate.reserve_port)
        run_preview_upgrade(delivery_root, temp_root, runtime_gate.reserve_port)
        run_preview_legacy_direct_migration(delivery_root, temp_root, runtime_gate.reserve_port)
    print("python38_delivery_lifecycle_gate=passed status=candidate")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--expected-version")
    parser.add_argument("--baseline-archive", required=False)
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({"scenarios": SCENARIOS}, sort_keys=True))
        return 0
    if not args.archive or not args.expected_version or not args.baseline_archive:
        parser.error("archive, --expected-version, and --baseline-archive are required")
    try:
        run_gate(
            Path(args.archive).resolve(),
            args.expected_version,
            Path(args.baseline_archive).resolve(),
            args.baseline_version,
        )
    except (LifecycleFailure, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print("python38_delivery_lifecycle_gate=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
