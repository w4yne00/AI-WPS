#!/usr/bin/env python3
"""Run the v0.26.0-preview.1 delivery and installation lifecycle gate."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Dict, Optional


VERSION = "0.26.0-preview.1"
BASELINE_VERSION = "0.25.3-alpha"
SCENARIOS = [
    "runtime_gate",
    "fresh_install",
    "legacy_boundary",
    "preview_upgrade",
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


def install_environment(root: Path, port: int, legacy_root: Path) -> Dict[str, str]:
    home = root / "home"
    install_root = root / "ai-wps"
    jsaddons = root / "jsaddons"
    home.mkdir(parents=True, exist_ok=True)
    install_root.mkdir(parents=True, exist_ok=True)
    jsaddons.mkdir(parents=True, exist_ok=True)
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
            "AI_WPS_INSTALL_ROOT": str(install_root),
            "AI_WPS_LEGACY_INSTALL_ROOT": str(legacy_root),
            "WPS_JSADDONS_DIR": str(jsaddons),
            "AI_WPS_SYSTEMD_SERVICE_FILE": str(root / "no-systemd/ai-wps.service"),
            "AI_WPS_CANDIDATE_PORT": str(port + 1),
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
    result = subprocess.run(
        ["bash", str(delivery_root / "installer/install_ai_wps.sh")],
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
    environment = install_environment(root, reserve_port(), root / "legacy/ai-wps-phase1")
    result = run_installer(delivery_root, environment)
    try:
        verify_install(environment)
        require("ai_wps_install_done=true" in result.stdout, "FRESH_INSTALL_NOT_DONE")
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=fresh_install passed")


def run_legacy_boundary(delivery_root: Path, temp_root: Path, reserve_port) -> None:
    root = temp_root / "legacy-boundary"
    legacy_root = root / "legacy/ai-wps-phase1"
    fixtures = legacy_fixture(legacy_root)
    environment = install_environment(root, reserve_port(), legacy_root)
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
    environment = install_environment(root, reserve_port(), root / "legacy/ai-wps-phase1")
    run_installer(delivery_root, environment)
    stop_adapter(environment)
    state_root = Path(environment["AI_WPS_INSTALL_ROOT"]) / "state"
    adapter_path = state_root / "adapter.json"
    adapter_content = b'{"previewSentinel":"preserve-me"}\n'
    adapter_path.write_bytes(adapter_content)
    key_path = state_root / "provider_api_key"
    key_content = b"preview-key-ref\n"
    key_path.write_bytes(key_content)
    key_path.chmod(0o600)

    result = run_installer(delivery_root, environment)
    try:
        verify_install(environment)
        require("ai_wps_install_done=true" in result.stdout, "PREVIEW_UPGRADE_NOT_DONE")
        require(adapter_path.read_bytes() == adapter_content, "PREVIEW_CONFIG_NOT_PRESERVED")
        require(key_path.read_bytes() == key_content, "PREVIEW_KEY_NOT_PRESERVED")
    finally:
        stop_adapter(environment)
    print("lifecycle_scenario=preview_upgrade passed")


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
        run_fresh_install(delivery_root, temp_root, runtime_gate.reserve_port)
        run_legacy_boundary(delivery_root, temp_root, runtime_gate.reserve_port)
        run_preview_upgrade(delivery_root, temp_root, runtime_gate.reserve_port)
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
