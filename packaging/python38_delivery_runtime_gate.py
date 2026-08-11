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


def adapter_environment(adapter_root: Path, runtime_root: Path) -> Dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": str(adapter_root),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "AI_WPS_ENABLE_MOCK_PROVIDER": "0",
            "AI_WPS_WRITING_POLICY_DB": str(runtime_root / "writing_policies.db"),
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
    print("key_contracts=passed count={0}".format(len(CHECK_ENDPOINTS)))


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
        environment = adapter_environment(adapter_root, runtime_root)
        import_application(adapter_root, environment, expected_version)

        port = reserve_port()
        log_path = runtime_root / "uvicorn.log"
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
