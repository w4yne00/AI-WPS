#!/usr/bin/env python3
"""Run the complete candidate lifecycle against the final delivery archive."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen


SCENARIOS = ["fresh_install", "upgrade_v022", "upgrade_v0231", "damaged_v0230"]
FAULTS = [
    "python_import_failure",
    "candidate_start_failure",
    "health_version_mismatch",
    "core_state_failure",
    "writing_policy_failure",
    "permission_error",
    "wps_not_exited",
    "install_interruption",
]


class LifecycleFailure(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise LifecycleFailure(code)


def load_runtime_gate():
    import python38_delivery_runtime_gate as runtime_gate

    return runtime_gate


def run_delivery_audit(delivery_root: Path) -> None:
    candidates = (
        Path(__file__).with_name("audit_phase1_delivery.py"),
        Path(__file__).with_name("audit_delivery.py"),
    )
    auditor = next((path for path in candidates if path.is_file()), None)
    if auditor is None:
        raise LifecycleFailure("DELIVERY_AUDITOR_MISSING")
    result = subprocess.run(
        [sys.executable, str(auditor), str(delivery_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    require(result.returncode == 0, result.stdout.strip() or "DELIVERY_AUDIT_FAILED")
    print("lifecycle_delivery_audit=passed")
    final_auditor = delivery_root / "scripts/audit_v0250_delivery.py"
    if final_auditor.is_file():
        final_result = subprocess.run(
            [sys.executable, str(final_auditor), str(delivery_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            final_result.returncode == 0,
            final_result.stdout.strip() or "V0250_DELIVERY_AUDIT_FAILED",
        )
        print("lifecycle_v0250_delivery_audit=passed")


def adapter_modules(delivery_root: Path):
    adapter_service = delivery_root / "packages/adapter-start-kit/adapter_service"
    sys.path.insert(0, str(adapter_service))
    from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS
    from app.services.writing_policy.store import WritingPolicyStore

    return adapter_service, SUPPORTED_WORKFLOW_TASKS, WritingPolicyStore


def write_legacy_state(
    legacy_root: Path,
    task_types,
    writing_policy_store,
    corrupt_core: bool = False,
    corrupt_policy: bool = False,
) -> None:
    config_dir = legacy_root / "config"
    run_dir = legacy_root / "run"
    key_dir = run_dir / "provider_api_keys"
    config_dir.mkdir(parents=True)
    key_dir.mkdir(parents=True)
    if corrupt_core:
        (config_dir / "adapter.json").write_text(
            '{"modelConfigurations":{"broken":', encoding="utf-8"
        )
        return
    configurations = {}
    active = {}
    task_refs = {}
    routes = {}
    for index, task_type in enumerate(task_types):
        configuration_id = "config-{0}".format(index)
        key_ref = "task-key-{0}".format(index)
        configurations[configuration_id] = {
            "id": configuration_id,
            "taskType": task_type,
            "name": "fixture-{0}".format(index),
            "accessMethod": "workflow_platform",
            "serviceBaseUrl": "https://model-{0}.example/v1".format(index),
            "apiKeyRef": key_ref,
        }
        active[task_type] = configuration_id
        task_refs[task_type] = key_ref
        routes[task_type] = {"path": "/chat-messages", "apiKeyRef": key_ref}
        key_path = key_dir / key_ref
        key_path.write_text("fixture-secret-{0}".format(index), encoding="utf-8")
        key_path.chmod(0o600)
    (config_dir / "adapter.json").write_text(
        json.dumps(
            {
                "modelConfigurations": configurations,
                "activeModelConfigurations": active,
                "taskApiKeyRefs": task_refs,
                "taskRoutes": routes,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if corrupt_policy:
        (run_dir / "writing_policies.db").write_bytes(b"not-a-sqlite-database")
    else:
        writing_policy_store(run_dir / "writing_policies.db").create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "system",
                "preferredText": "卫星互联网运营平台",
                "aliases": ["运营平台"],
                "forbiddenVariants": [],
                "definition": "统一名称",
                "contextKeywords": ["平台"],
                "priority": "high",
                "enabled": True,
                "note": "lifecycle-fixture",
            }
        )


def install_environment(root: Path, port: int) -> Dict[str, str]:
    install_root = root / "install"
    jsaddons = root / "jsaddons"
    install_root.mkdir(parents=True, exist_ok=True)
    jsaddons.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.pop("SUDO_USER", None)
    environment.pop("SUDO_UID", None)
    environment.update(
        {
            "AI_WPS_INSTALL_ROOT": str(install_root),
            "WPS_JSADDONS_DIR": str(jsaddons),
            "AI_WPS_SYSTEMD_SERVICE_FILE": str(root / "no-systemd/ai-wps.service"),
            "AI_WPS_CANDIDATE_PORT": str(port + 1),
            "PORT": str(port),
            "PYTHON_BIN": os.environ.get(
                "AI_WPS_LIFECYCLE_PYTHON_BIN", sys.executable
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def stop_installed_adapter(root: Path, environment: Dict[str, str]) -> None:
    stop_script = root / "install/current/scripts/stop_adapter.sh"
    if stop_script.is_file():
        subprocess.run(
            ["bash", str(stop_script), environment["PORT"]],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )


def run_installer(
    delivery_root: Path,
    root: Path,
    port: int,
    expected_returncode: int = 0,
    environment_updates: Optional[Dict[str, str]] = None,
) -> Tuple[subprocess.CompletedProcess, Dict[str, str]]:
    environment = install_environment(root, port)
    if environment_updates:
        environment.update(environment_updates)
    result = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if result.returncode != expected_returncode:
        diagnostics = []
        for log_path in sorted(root.rglob("*.log")):
            try:
                diagnostics.append(log_path.read_text(encoding="utf-8")[-1200:])
            except OSError:
                continue
        raise LifecycleFailure(
            "INSTALL_RESULT_INVALID expected={0} actual={1} output={2}".format(
                expected_returncode,
                result.returncode,
                (result.stdout + result.stderr + "\n" + "\n".join(diagnostics))[-2400:],
            )
        )
    return result, environment


def verify_committed_install(root: Path, expected_version: str) -> None:
    current = root / "install/current"
    release = root / "install/releases" / expected_version
    require(current.is_symlink() and current.samefile(release), "CURRENT_RELEASE_INVALID")
    transactions = list((root / "install/var/transactions").glob("*.json"))
    require(bool(transactions), "TRANSACTION_LOG_MISSING")
    latest = max(transactions, key=lambda path: path.stat().st_mtime_ns)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    require(payload.get("status") == "committed", "TRANSACTION_NOT_COMMITTED")


def run_install_scenarios(
    delivery_root: Path,
    temp_root: Path,
    expected_version: str,
    reserve_port,
) -> None:
    unused_adapter, task_types, writing_policy_store = adapter_modules(delivery_root)

    fresh_root = temp_root / "fresh"
    fresh_result, fresh_environment = run_installer(
        delivery_root, fresh_root, reserve_port()
    )
    try:
        verify_committed_install(fresh_root, expected_version)
        require("phase1_install_done=true" in fresh_result.stdout, "FRESH_INSTALL_NOT_DONE")
    finally:
        stop_installed_adapter(fresh_root, fresh_environment)
    print("lifecycle_scenario=fresh_install passed")

    upgrade_root = temp_root / "upgrade-v022"
    environment = install_environment(upgrade_root, reserve_port())
    legacy = upgrade_root / "install/adapter-start-kit"
    write_legacy_state(legacy, task_types, writing_policy_store)
    upgrade_result = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    try:
        require(upgrade_result.returncode == 0, "V022_UPGRADE_FAILED")
        verify_committed_install(upgrade_root, expected_version)
        migrated = json.loads(
            (upgrade_root / "install/state/adapter.json").read_text(encoding="utf-8")
        )
        require(
            len(migrated.get("activeModelConfigurations", {})) == len(task_types),
            "V022_ACTIVE_CONFIGURATIONS_LOST",
        )
        require(
            len(list((upgrade_root / "install/state/provider_api_keys").iterdir()))
            == len(task_types),
            "V022_KEY_REFERENCES_LOST",
        )
    finally:
        stop_installed_adapter(upgrade_root, environment)
    print("lifecycle_scenario=upgrade_v022 passed")

    damaged_root = temp_root / "damaged-v0230"
    damaged_environment = install_environment(damaged_root, reserve_port())
    damaged_release = damaged_root / "install/releases/0.23.0-alpha"
    write_legacy_state(
        damaged_release,
        task_types,
        writing_policy_store,
        corrupt_core=True,
    )
    (damaged_release / "release-manifest.json").write_text(
        json.dumps({"version": "0.23.0-alpha"}), encoding="utf-8"
    )
    os.symlink(str(damaged_release), str(damaged_root / "install/current"))
    damaged = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=damaged_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    require(damaged.returncode != 0, "DAMAGED_V0230_UNEXPECTEDLY_COMMITTED")
    require(
        "runtime_state_migration_status=recovery" in damaged.stdout,
        "DAMAGED_V0230_RECOVERY_NOT_REPORTED",
    )
    require(
        (damaged_release / "config/adapter.json").read_text(encoding="utf-8")
        == '{"modelConfigurations":{"broken":',
        "DAMAGED_V0230_SOURCE_CHANGED",
    )
    print("lifecycle_scenario=damaged_v0230 passed")
    print("lifecycle_fault=core_state_failure passed")

    degraded_root = temp_root / "degraded-policy"
    degraded_environment = install_environment(degraded_root, reserve_port())
    degraded_legacy = degraded_root / "install/adapter-start-kit"
    write_legacy_state(
        degraded_legacy,
        task_types,
        writing_policy_store,
        corrupt_policy=True,
    )
    degraded = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=degraded_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    try:
        require(
            degraded.returncode == 0,
            "WRITING_POLICY_DEGRADED_INSTALL_FAILED output={0}".format(
                (degraded.stdout + degraded.stderr)[-1200:]
            ),
        )
        require(
            "candidate_preflight=degraded" in degraded.stdout,
            "WRITING_POLICY_DEGRADED_NOT_DISCLOSED",
        )
    finally:
        stop_installed_adapter(degraded_root, degraded_environment)
    print("lifecycle_fault=writing_policy_failure passed")


def run_v0231_upgrade_scenario(
    delivery_root: Path,
    baseline_root: Path,
    temp_root: Path,
    expected_version: str,
    reserve_port,
    baseline_version: str = "0.23.1-alpha",
) -> None:
    root = temp_root / "upgrade-{0}".format(baseline_version.replace(".", "_"))
    port = reserve_port()
    unused_adapter, task_types, writing_policy_store = adapter_modules(delivery_root)
    write_legacy_state(
        root / "install/adapter-start-kit",
        task_types,
        writing_policy_store,
    )
    baseline_result, baseline_environment = run_installer(
        baseline_root, root, port
    )
    try:
        verify_committed_install(root, baseline_version)
        install_root = root / "install"
        jsaddons = root / "jsaddons"
        baseline_release = install_root / "releases" / baseline_version
        components = {
            "adapter_release": baseline_release,
            "word_plugin": jsaddons / "wps-ai-assistant_1.0.0",
            "excel_plugin": jsaddons / "wps-ai-assistant-et_1.0.0",
            "ppt_plugin": jsaddons / "wps-ai-assistant-wpp_1.0.0",
            "publish_manifest": jsaddons / "publish.xml",
            "runtime_state_snapshot": install_root / "state",
            "current_pointer": install_root / "current",
        }
        for name in (
            "adapter_release",
            "word_plugin",
            "excel_plugin",
            "ppt_plugin",
            "runtime_state_snapshot",
        ):
            (components[name] / ".baseline-lifecycle-sentinel").write_text(
                name + "\n", encoding="utf-8"
            )
        with components["publish_manifest"].open("a", encoding="utf-8") as handle:
            handle.write("\n<!-- baseline-lifecycle-sentinel -->\n")
        before = {
            name: component_fingerprint(path) for name, path in components.items()
        }
        interrupted, interrupted_environment = run_installer(
            delivery_root,
            root,
            port,
            expected_returncode=1,
            environment_updates={
                "AI_WPS_TRANSACTION_FAIL_AFTER": "after_switch:excel_plugin"
            },
        )
        require(
            "release_generation_switch_failed" in interrupted.stdout,
            "BASELINE_UPGRADE_INTERRUPTION_NOT_INJECTED",
        )
        after = {
            name: component_fingerprint(path) for name, path in components.items()
        }
        require(before == after, "BASELINE_UPGRADE_ROLLBACK_MISMATCH")
        wait_for_adapter_version(port, baseline_version)
        require(
            not (install_root / "releases" / expected_version).exists(),
            "V0231_UPGRADE_PARTIAL_RELEASE_LEFT",
        )
        preserved_state = {
            "adapter": state_configuration_contract(install_root / "state"),
            "keys": component_fingerprint(install_root / "state/provider_api_keys"),
            "writing_policy": component_fingerprint(
                install_root / "state/writing_policies.db"
            ),
        }
        stop_installed_adapter(root, interrupted_environment)
        successful, successful_environment = run_installer(
            delivery_root, root, port
        )
        try:
            verify_committed_install(root, expected_version)
            require(
                "phase1_install_done=true" in successful.stdout,
                "BASELINE_UPGRADE_SUCCESS_NOT_COMMITTED",
            )
            require(
                state_configuration_contract(install_root / "state")
                == preserved_state["adapter"],
                "BASELINE_UPGRADE_CONFIGURATIONS_NOT_PRESERVED",
            )
            require(
                component_fingerprint(install_root / "state/provider_api_keys")
                == preserved_state["keys"],
                "BASELINE_UPGRADE_KEY_REFERENCES_NOT_PRESERVED",
            )
            require(
                component_fingerprint(install_root / "state/writing_policies.db")
                == preserved_state["writing_policy"],
                "BASELINE_UPGRADE_WRITING_POLICY_NOT_PRESERVED",
            )
        finally:
            stop_installed_adapter(root, successful_environment)
    finally:
        stop_installed_adapter(root, baseline_environment)
    print("lifecycle_scenario=upgrade_baseline version={0} passed".format(baseline_version))


def run_preflight_faults(
    delivery_root: Path, temp_root: Path, reserve_port, expected_version: str
) -> None:
    preflight = delivery_root / "installer/preflight_candidate.sh"

    def run_fault(name: str, mutate) -> str:
        root = temp_root / name
        candidate = root / "candidate"
        shutil.copytree(
            str(delivery_root / "packages/adapter-start-kit"), str(candidate)
        )
        (candidate / "python-runtime").mkdir()
        mutate(candidate, root)
        result = subprocess.run(
            [
                "bash",
                str(preflight),
                sys.executable,
                str(candidate),
                str(candidate / "python-runtime"),
                str(reserve_port()),
                expected_version,
                str(root / "preflight"),
            ],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            check=False,
            capture_output=True,
            text=True,
            timeout=40,
        )
        require(result.returncode != 0, "FAULT_NOT_BLOCKED {0}".format(name))
        print("lifecycle_fault={0} passed".format(name))
        return result.stdout + result.stderr

    def import_failure(candidate: Path, unused_root: Path) -> None:
        main = candidate / "adapter_service/app/main.py"
        main.write_text("raise RuntimeError('injected import failure')\n", encoding="utf-8")

    output = run_fault("python_import_failure", import_failure)
    require("candidate_full_import_failed" in output, "IMPORT_FAILURE_CODE_MISSING")

    def start_failure(candidate: Path, root: Path) -> None:
        main = candidate / "adapter_service/app/main.py"
        original = main.read_text(encoding="utf-8")
        marker = root / "import-marker"
        prefix = (
            "from pathlib import Path as _LifecyclePath\n"
            "_lifecycle_marker = _LifecyclePath({0!r})\n"
            "if _lifecycle_marker.exists():\n"
            "    raise RuntimeError('injected start failure')\n"
            "_lifecycle_marker.write_text('imported')\n"
        ).format(str(marker))
        main.write_text(prefix + original, encoding="utf-8")

    output = run_fault("candidate_start_failure", start_failure)
    require(
        any(
            marker in output
            for marker in (
                "candidate_start_failed",
                "candidate_live_timeout",
                "candidate_business_not_ready",
                "candidate_preflight_failed=",
            )
        ),
        "START_FAILURE_CODE_MISSING",
    )

    def version_mismatch(candidate: Path, unused_root: Path) -> None:
        for relative in (
            "adapter_service/app/main.py",
            "adapter_service/app/services/health.py",
        ):
            path = candidate / relative
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    expected_version, "0.23.0-alpha"
                ),
                encoding="utf-8",
            )

    output = run_fault("health_version_mismatch", version_mismatch)
    require(
        "candidate_version_mismatch" in output
        or "candidate_preflight_failed=" in output,
        "VERSION_FAILURE_CODE_MISSING",
    )


def run_prewrite_guards(delivery_root: Path, temp_root: Path, reserve_port) -> None:
    permission_root = temp_root / "permission"
    environment = install_environment(permission_root, reserve_port())
    wps_dir = Path(environment["WPS_JSADDONS_DIR"])
    wps_dir.chmod(0o500)
    permission = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    wps_dir.chmod(0o700)
    require(permission.returncode != 0, "PERMISSION_ERROR_NOT_BLOCKED")
    require("target_path_not_writable" in permission.stdout, "PERMISSION_CODE_MISSING")
    print("lifecycle_fault=permission_error passed")

    wps_root = temp_root / "wps-running"
    environment = install_environment(wps_root, reserve_port())
    bin_dir = wps_root / "bin"
    bin_dir.mkdir()
    ps_stub = bin_dir / "ps"
    ps_stub.write_text("#!/usr/bin/env bash\nprintf '%s\\n' wps\n", encoding="utf-8")
    ps_stub.chmod(0o755)
    environment["PATH"] = "{0}:{1}".format(bin_dir, environment.get("PATH", ""))
    running = subprocess.run(
        ["bash", str(delivery_root / "installer/install_phase1.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    require(running.returncode != 0, "WPS_RUNNING_NOT_BLOCKED")
    require("wps_process_running" in running.stdout, "WPS_RUNNING_CODE_MISSING")
    print("lifecycle_fault=wps_not_exited passed")


def component_fingerprint(path: Path):
    if path.is_symlink():
        return {"type": "symlink", "target": os.readlink(str(path))}
    if path.is_file():
        return {"type": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    require(path.is_dir(), "INTERRUPTION_COMPONENT_MISSING {0}".format(path))
    return {
        "type": "directory",
        "files": {
            item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in sorted(path.rglob("*"))
            if item.is_file()
        },
    }


def state_configuration_contract(state_root: Path) -> Dict[str, object]:
    payload = json.loads((state_root / "adapter.json").read_text(encoding="utf-8"))
    configurations = payload.get("modelConfigurations", {})
    active = payload.get("activeModelConfigurations", {})
    key_refs = payload.get("taskApiKeyRefs", {})
    routes = payload.get("taskRoutes", {})
    require(
        isinstance(configurations, dict)
        and isinstance(active, dict)
        and isinstance(key_refs, dict)
        and isinstance(routes, dict),
        "STATE_CONFIGURATION_CONTRACT_INVALID",
    )
    return {
        "configuration_count": len(configurations),
        "active_task_types": sorted(active),
        "task_key_refs": sorted(key_refs.items()),
        "route_task_types": sorted(routes),
    }


def wait_for_adapter_version(port: int, expected_version: str) -> None:
    deadline = time.monotonic() + 20
    last_error = "not_started"
    while time.monotonic() < deadline:
        try:
            with urlopen(
                "http://127.0.0.1:{0}/health".format(port), timeout=2
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("data", {}).get("version") == expected_version:
                return
            last_error = "version_mismatch"
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(0.2)
    raise LifecycleFailure(
        "INTERRUPTION_PREVIOUS_ADAPTER_NOT_HEALTHY {0}".format(last_error)
    )


def run_interruption_fault(
    delivery_root: Path,
    temp_root: Path,
    expected_version: str,
    reserve_port,
) -> None:
    root = temp_root / "interruption"
    port = reserve_port()
    unused_result, environment = run_installer(delivery_root, root, port)
    wait_for_adapter_version(port, expected_version)

    install_root = root / "install"
    jsaddons = root / "jsaddons"
    release = install_root / "releases" / expected_version
    components = {
        "adapter_release": release,
        "word_plugin": jsaddons / "wps-ai-assistant_1.0.0",
        "excel_plugin": jsaddons / "wps-ai-assistant-et_1.0.0",
        "ppt_plugin": jsaddons / "wps-ai-assistant-wpp_1.0.0",
        "publish_manifest": jsaddons / "publish.xml",
        "runtime_state_snapshot": install_root / "state",
        "current_pointer": install_root / "current",
    }
    for name in (
        "adapter_release",
        "word_plugin",
        "excel_plugin",
        "ppt_plugin",
        "runtime_state_snapshot",
    ):
        (components[name] / ".lifecycle-sentinel").write_text(
            name + "\n", encoding="utf-8"
        )
    with components["publish_manifest"].open("a", encoding="utf-8") as handle:
        handle.write("\n<!-- lifecycle-sentinel -->\n")
    before = {
        name: component_fingerprint(path) for name, path in components.items()
    }

    interrupted, interrupted_environment = run_installer(
        delivery_root,
        root,
        port,
        expected_returncode=1,
        environment_updates={
            "AI_WPS_TRANSACTION_FAIL_AFTER": "after_switch:excel_plugin"
        },
    )
    try:
        require(
            "release_generation_switch_failed" in interrupted.stdout,
            "INTERRUPTION_NOT_INJECTED",
        )
        after = {
            name: component_fingerprint(path) for name, path in components.items()
        }
        require(before == after, "INTERRUPTION_COMPONENT_ROLLBACK_MISMATCH")
        wait_for_adapter_version(port, expected_version)
        transactions = list((install_root / "var/transactions").glob("*.json"))
        require(len(transactions) >= 2, "INTERRUPTION_TRANSACTION_LOG_MISSING")
        latest = max(transactions, key=lambda path: path.stat().st_mtime_ns)
        transaction = json.loads(latest.read_text(encoding="utf-8"))
        require(
            transaction.get("status") == "rolled_back",
            "INTERRUPTION_NOT_ROLLED_BACK",
        )
        require(
            [item.get("name") for item in transaction.get("components", [])]
            == [
                "adapter_release",
                "word_plugin",
                "excel_plugin",
                "ppt_plugin",
                "publish_manifest",
                "runtime_state_snapshot",
                "current_pointer",
            ],
            "INTERRUPTION_COMPONENT_INVENTORY_INVALID",
        )
    finally:
        stop_installed_adapter(root, interrupted_environment)
    print("lifecycle_fault=install_interruption passed")


def run_gate(
    archive: Path,
    expected_version: str,
    baseline_archive: Optional[Path],
    baseline_version: str = "0.23.1-alpha",
) -> None:
    runtime_gate = load_runtime_gate()
    runtime_gate.require_python38()
    if baseline_archive is None:
        raise LifecycleFailure("BASELINE_ARCHIVE_REQUIRED")
    with tempfile.TemporaryDirectory(prefix="ai-wps-lifecycle-") as temp_dir:
        temp_root = Path(temp_dir)
        delivery_root = runtime_gate.safe_extract(archive, temp_root / "delivery")
        baseline_root = runtime_gate.safe_extract(
            baseline_archive, temp_root / "baseline-delivery"
        )
        run_delivery_audit(delivery_root)
        runtime_gate.run_gate(archive, expected_version)
        run_v0231_upgrade_scenario(
            delivery_root,
            baseline_root,
            temp_root,
            expected_version,
            runtime_gate.reserve_port,
            baseline_version,
        )
        run_install_scenarios(
            delivery_root, temp_root / "install-scenarios", expected_version, runtime_gate.reserve_port
        )
        run_preflight_faults(
            delivery_root,
            temp_root / "preflight-faults",
            runtime_gate.reserve_port,
            expected_version,
        )
        run_prewrite_guards(
            delivery_root, temp_root / "prewrite-faults", runtime_gate.reserve_port
        )
        run_interruption_fault(
            delivery_root,
            temp_root,
            expected_version,
            runtime_gate.reserve_port,
        )
    print("python38_delivery_lifecycle_gate=passed status=candidate")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", nargs="?", type=Path)
    parser.add_argument("--expected-version")
    parser.add_argument("--baseline-archive", type=Path)
    parser.add_argument("--baseline-version", default="0.23.1-alpha")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({"scenarios": SCENARIOS, "faults": FAULTS}))
        return 0
    if args.archive is None or not args.expected_version:
        parser.error("archive and --expected-version are required")
    try:
        run_gate(
            args.archive.resolve(),
            args.expected_version,
            args.baseline_archive.resolve() if args.baseline_archive else None,
            args.baseline_version,
        )
    except (
        LifecycleFailure,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print("python38_delivery_lifecycle_gate=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
