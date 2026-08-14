#!/usr/bin/env python3
"""Run the final delivery archive with a real Python 3.8 Uvicorn process."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


CHECK_ENDPOINTS = (
    ("health", "/health", None),
    ("provider_status", "/provider/status", None),
    (
        "model_configurations",
        "/provider/model-configurations",
        {"taskType": "word.smart_write"},
    ),
    ("writing_policy_summary", "/writing-policies/summary", None),
)


class GateFailure(RuntimeError):
    pass


def require_python38() -> None:
    if sys.version_info[:2] != (3, 8):
        raise GateFailure(
            "PYTHON38_REQUIRED current={0}.{1}".format(
                sys.version_info[0], sys.version_info[1]
            )
        )
    print("python38_version={0}".format(sys.version.split()[0]))


def reproduce_original_import_failure() -> None:
    original_signature = (
        "class WorkflowProfileCompatibilityStore:\n"
        "    def _platform_configurations(self, task_type: str) "
        "-> tuple[dict, list]:\n"
        "        return {}, []\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", original_signature],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 or "not subscriptable" not in result.stderr:
        raise GateFailure("ORIGINAL_FAILURE_NOT_REPRODUCED")
    print("original_failure_reproduction=passed")


def safe_extract(archive_path: Path, destination: Path) -> Path:
    if not archive_path.is_file():
        raise GateFailure("DELIVERY_ARCHIVE_MISSING {0}".format(archive_path))
    with tarfile.open(str(archive_path), "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise GateFailure("DELIVERY_ARCHIVE_EMPTY")
        destination_root = destination.resolve()
        for member in members:
            if member.issym() or member.islnk():
                raise GateFailure("DELIVERY_ARCHIVE_LINK_REJECTED {0}".format(member.name))
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError:
                raise GateFailure(
                    "DELIVERY_ARCHIVE_PATH_REJECTED {0}".format(member.name)
                )
        archive.extractall(str(destination))

    manifests = list(destination.glob("*/release-manifest.json"))
    if len(manifests) != 1:
        raise GateFailure(
            "DELIVERY_ROOT_INVALID manifest_count={0}".format(len(manifests))
        )
    return manifests[0].parent


def load_manifest(delivery_root: Path, expected_version: str) -> Dict:
    manifest_path = delivery_root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version", ""))
    adapter_version = str(manifest.get("adapter", {}).get("version", ""))
    if version != expected_version or adapter_version != expected_version:
        raise GateFailure(
            "DELIVERY_VERSION_MISMATCH expected={0} release={1} adapter={2}".format(
                expected_version, version, adapter_version
            )
        )
    generation_policy = manifest.get("releaseGenerationPolicy", {})
    expected_generation_components = [
        "adapter_release",
        "word_plugin",
        "excel_plugin",
        "ppt_plugin",
        "publish_manifest",
        "runtime_state_snapshot",
        "current_pointer",
    ]
    if (
        generation_policy.get("switchStrategy")
        != "durable-compensating-rename"
        or generation_policy.get("currentPointer") != "current"
        or generation_policy.get("components")
        != expected_generation_components
    ):
        raise GateFailure("RELEASE_GENERATION_POLICY_INVALID")
    transaction_tool = delivery_root / "installer/release_transaction.py"
    if not transaction_tool.is_file():
        raise GateFailure("RELEASE_TRANSACTION_TOOL_MISSING")
    print("delivery_manifest=passed version={0}".format(expected_version))
    return manifest


def run_compatibility_scan(delivery_root: Path) -> None:
    scanner = Path(__file__).with_name("check_python38_compatibility.py")
    adapter_root = (
        delivery_root / "packages/adapter-start-kit/adapter_service"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(scanner),
            str(adapter_root),
            str(delivery_root / "installer/release_transaction.py"),
            str(delivery_root / "scripts/check_python38_compatibility.py"),
            str(delivery_root / "scripts/python38_delivery_runtime_gate.py"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateFailure(result.stdout.strip() or result.stderr.strip())
    print("production_compatibility_scan=passed")


def adapter_environment(
    adapter_root: Path,
    runtime_root: Path,
    dependency_root: Optional[Path] = None,
) -> Dict[str, str]:
    dependency_root = dependency_root or adapter_root
    environment = dict(os.environ)
    environment.pop("AI_WPS_WRITING_POLICY_DB", None)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                (str(dependency_root), str(adapter_root))
            ),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "AI_WPS_ENABLE_MOCK_PROVIDER": "0",
            "AI_WPS_STATE_DIR": str(runtime_root / "state"),
            "AI_WPS_BACKUP_DIR": str(runtime_root / "backups"),
            "AI_WPS_VAR_DIR": str(runtime_root / "var"),
        }
    )
    return environment


def import_application(adapter_root: Path, environment: Dict[str, str], expected_version: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.main import app; "
                "assert app.version == {0!r}, app.version; "
                "print(app.version)"
            ).format(expected_version),
        ],
        cwd=str(adapter_root),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateFailure("ADAPTER_IMPORT_FAILED {0}".format(result.stderr.strip()))
    print("adapter_import=passed version={0}".format(result.stdout.strip()))


def reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def get_json(port: int, path: str, query: Optional[Dict[str, str]] = None) -> Dict:
    url = "http://127.0.0.1:{0}{1}".format(port, path)
    if query:
        url += "?" + urlencode(query)
    with urlopen(url, timeout=3) as response:
        if response.status != 200:
            raise GateFailure(
                "ENDPOINT_STATUS_INVALID path={0} status={1}".format(
                    path, response.status
                )
            )
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(process: subprocess.Popen, port: int, expected_version: str) -> Dict:
    deadline = time.monotonic() + 20
    last_error = "not_started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise GateFailure(
                "UVICORN_EXITED returncode={0}".format(process.returncode)
            )
        try:
            body = get_json(port, "/health")
            data = body.get("data", {})
            if (
                body.get("success") is True
                and data.get("mode") == "uvicorn"
                and data.get("version") == expected_version
            ):
                return body
            last_error = "unexpected_health_contract"
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(0.2)
    raise GateFailure("UVICORN_START_TIMEOUT last_error={0}".format(last_error))


def check_contracts(port: int, expected_version: str) -> None:
    responses = {}
    for label, path, query in CHECK_ENDPOINTS:
        body = get_json(port, path, query)
        if body.get("success") is not True or not isinstance(body.get("data"), dict):
            raise GateFailure("ENDPOINT_CONTRACT_INVALID path={0}".format(path))
        responses[label] = body

    health = responses["health"]["data"]
    if (
        health.get("service") != "wps-ai-adapter"
        or health.get("version") != expected_version
        or health.get("mode") != "uvicorn"
    ):
        raise GateFailure("HEALTH_CONTRACT_INVALID")
    provider = responses["provider_status"]["data"]
    if "configured" not in provider or "authSource" not in provider:
        raise GateFailure("PROVIDER_STATUS_CONTRACT_INVALID")
    configurations = responses["model_configurations"]["data"]
    if (
        configurations.get("taskType") != "word.smart_write"
        or not isinstance(configurations.get("configurations"), list)
    ):
        raise GateFailure("MODEL_CONFIGURATION_CONTRACT_INVALID")
    policy = responses["writing_policy_summary"]["data"]
    if "totalCount" not in policy or "enabledCount" not in policy:
        raise GateFailure("WRITING_POLICY_CONTRACT_INVALID")
    openapi = get_json(port, "/openapi.json")
    public_format_review_paths = {
        "/word/format-review",
        "/word/format-review/snapshots",
        "/word/format-review/jobs",
    }
    if not public_format_review_paths.issubset(openapi.get("paths", {})):
        raise GateFailure("PUBLIC_FORMAT_REVIEW_API_CONTRACT_INVALID")
    print("public_format_review_api=passed")
    print("key_contracts=passed count={0}".format(len(CHECK_ENDPOINTS)))


def prepare_runtime_layout(runtime_root: Path) -> None:
    for path in (
        runtime_root / "state",
        runtime_root / "backups",
        runtime_root / "var/logs",
        runtime_root / "var/run",
        runtime_root / "var/transactions",
    ):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)


def prepare_python_runtime(delivery_root: Path, runtime_root: Path) -> Path:
    external_root = os.environ.get("AI_WPS_PYTHON38_GATE_SITE_PACKAGES", "").strip()
    if external_root:
        dependency_root = Path(external_root).resolve()
        if not dependency_root.is_dir():
            raise GateFailure(
                "PYTHON38_GATE_DEPENDENCIES_MISSING {0}".format(dependency_root)
            )
        print("python38_gate_dependencies=external")
        return dependency_root

    runtime_deps = delivery_root / "packages/kylin-v10-arm-py38"
    pip_bootstrap = delivery_root / "packages/kylin-v10-arm-py38-pip-bootstrap"
    installer = delivery_root / "installer/install_private_runtime.sh"
    dependency_root = runtime_root / "python-runtime"
    result = subprocess.run(
        [
            "bash",
            str(installer),
            sys.executable,
            str(runtime_deps),
            str(pip_bootstrap),
            str(dependency_root),
        ],
        env=dict(os.environ, PYTHONNOUSERSITE="1", PYTHONPATH=""),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateFailure(
            "PRIVATE_RUNTIME_INSTALL_FAILED {0}".format(
                (result.stdout + result.stderr).strip()[-1000:]
            )
        )
    print("python38_gate_dependencies=package")
    return dependency_root


def check_runtime_path_contract(adapter_root: Path, runtime_root: Path) -> None:
    state_root = runtime_root / "state"
    backup_root = runtime_root / "backups"
    var_root = runtime_root / "var"
    if not (state_root / "writing_policies.db").is_file():
        raise GateFailure("RUNTIME_STATE_WRITING_POLICY_MISSING")
    if not (var_root / "logs/adapter.log").is_file():
        raise GateFailure("RUNTIME_VAR_APPLICATION_LOG_MISSING")
    for path in (
        backup_root,
        var_root / "run",
        var_root / "transactions",
    ):
        if not path.is_dir():
            raise GateFailure("RUNTIME_AREA_MISSING {0}".format(path.name))
    for forbidden_name in ("logs", "run", "transactions"):
        if (state_root / forbidden_name).exists():
            raise GateFailure(
                "RUNTIME_STATE_BOUNDARY_INVALID {0}".format(forbidden_name)
            )

    program_root = adapter_root.parent
    forbidden_program_paths = (
        program_root / "config/adapter.json",
        program_root / "run/provider_api_key",
        program_root / "run/provider_api_keys",
        program_root / "run/writing_policies.db",
        program_root / "run/adapter.pid",
        program_root / "run/transactions",
        program_root / "logs",
        adapter_root / "logs",
    )
    for path in forbidden_program_paths:
        if path.exists():
            raise GateFailure(
                "MUTABLE_PROGRAM_PATH_CREATED {0}".format(
                    path.relative_to(program_root)
                )
            )
    print("runtime_path_contract=passed")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_gate(archive_path: Path, expected_version: str) -> None:
    require_python38()
    reproduce_original_import_failure()
    with tempfile.TemporaryDirectory(prefix="ai-wps-python38-gate-") as temp_dir:
        temp_root = Path(temp_dir)
        delivery_root = safe_extract(archive_path, temp_root / "delivery")
        load_manifest(delivery_root, expected_version)
        run_compatibility_scan(delivery_root)

        adapter_root = delivery_root / "packages/adapter-start-kit/adapter_service"
        runtime_root = temp_root / "runtime"
        runtime_root.mkdir(mode=0o700)
        prepare_runtime_layout(runtime_root)
        dependency_root = prepare_python_runtime(delivery_root, runtime_root)
        environment = adapter_environment(adapter_root, runtime_root, dependency_root)
        import_application(adapter_root, environment, expected_version)

        port = reserve_port()
        log_path = runtime_root / "var/logs/uvicorn.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=str(adapter_root),
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for_health(process, port, expected_version)
                print("uvicorn_start=passed")
                check_contracts(port, expected_version)
                check_runtime_path_contract(adapter_root, runtime_root)
            finally:
                stop_process(process)
        print("python38_delivery_runtime_gate=passed")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)
    try:
        run_gate(args.archive, args.expected_version)
    except (GateFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print("python38_delivery_runtime_gate=failed {0}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
