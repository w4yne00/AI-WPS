import json
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON38_BIN = os.environ.get("AI_WPS_PYTHON38_BIN", "")


class PackagingScriptTests(unittest.TestCase):
    def _delivery_source_pairs(self):
        policy = json.loads(
            (ROOT / "packaging/delivery-sources-v0231.json").read_text(
                encoding="utf-8"
            )
        )
        return {
            (entry["source"], entry["target"])
            for entry in policy["entries"]
        }

    def _delivery_target_files(self):
        policy = json.loads(
            (ROOT / "packaging/delivery-sources-v0231.json").read_text(
                encoding="utf-8"
            )
        )
        targets = set()
        for entry in policy["entries"]:
            target = entry["target"].rstrip("/")
            if entry["type"] == "file":
                targets.add(target)
            else:
                targets.update(
                    target + "/" + relative
                    for relative in entry["include"]
                )
        return targets

    def _copy_phase1_installer(self, destination: Path) -> Path:
        installer_dir = destination / "delivery" / "installer"
        installer_dir.mkdir(parents=True)
        installer = installer_dir / "install_phase1.sh"
        shutil.copy2(
            ROOT / "phase1-delivery-kit/installer/install_phase1.sh",
            installer,
        )
        return installer

    def test_phase1_installer_rejects_sudo_context_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = self._copy_phase1_installer(root)
            install_root = root / "install"
            jsaddons = root / "jsaddons"
            install_root.mkdir()
            jsaddons.mkdir()
            sentinel = install_root / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_INSTALL_ROOT": str(install_root),
                    "WPS_JSADDONS_DIR": str(jsaddons),
                    "PYTHON_BIN": "/usr/bin/false",
                    "SUDO_USER": "operator",
                    "SUDO_UID": str(os.getuid()),
                }
            )

            result = subprocess.run(
                ["bash", str(installer)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("target_user_required_for_admin_install", result.stdout)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(sorted(path.name for path in install_root.iterdir()), ["keep.txt"])
            self.assertEqual(list(jsaddons.iterdir()), [])

    def test_phase1_admin_install_requires_explicit_target_identity_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = self._copy_phase1_installer(root)
            install_root = root / "install"
            jsaddons = root / "jsaddons"
            install_root.mkdir()
            jsaddons.mkdir()
            sentinel = install_root / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            current_user = subprocess.check_output(
                ["id", "-un"], text=True
            ).strip()
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_INSTALL_ROOT": str(install_root),
                    "WPS_JSADDONS_DIR": str(jsaddons),
                    "PYTHON_BIN": "/usr/bin/false",
                    "SUDO_USER": current_user,
                    "SUDO_UID": str(os.getuid()),
                }
            )

            result = subprocess.run(
                ["bash", str(installer), "--target-user", current_user],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("admin_target_identity_required", result.stdout)
            self.assertIn("--target-uid", result.stdout)
            self.assertIn("--target-home", result.stdout)
            self.assertIn("--wps-jsaddons-dir", result.stdout)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(sorted(path.name for path in install_root.iterdir()), ["keep.txt"])
            self.assertEqual(list(jsaddons.iterdir()), [])

    def test_phase1_installer_rejects_running_wps_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = self._copy_phase1_installer(root)
            install_root = root / "install"
            jsaddons = root / "jsaddons"
            bin_dir = root / "bin"
            install_root.mkdir()
            jsaddons.mkdir()
            bin_dir.mkdir()
            sentinel = install_root / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            ps_stub = bin_dir / "ps"
            ps_stub.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' wps\n",
                encoding="utf-8",
            )
            ps_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.pop("SUDO_USER", None)
            environment.pop("SUDO_UID", None)
            environment.update(
                {
                    "AI_WPS_INSTALL_ROOT": str(install_root),
                    "WPS_JSADDONS_DIR": str(jsaddons),
                    "PATH": "{0}:{1}".format(bin_dir, environment.get("PATH", "")),
                    "PYTHON_BIN": "/usr/bin/false",
                }
            )

            result = subprocess.run(
                ["bash", str(installer)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("wps_process_running", result.stdout)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(sorted(path.name for path in install_root.iterdir()), ["keep.txt"])
            self.assertEqual(list(jsaddons.iterdir()), [])

    def test_phase1_installer_fails_closed_when_process_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = self._copy_phase1_installer(root)
            install_root = root / "install"
            jsaddons = root / "jsaddons"
            bin_dir = root / "bin"
            install_root.mkdir()
            jsaddons.mkdir()
            bin_dir.mkdir()
            sentinel = install_root / "keep.txt"
            sentinel.write_text("unchanged", encoding="utf-8")
            ps_stub = bin_dir / "ps"
            ps_stub.write_text("#!/usr/bin/env bash\nexit 2\n", encoding="utf-8")
            ps_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.pop("SUDO_USER", None)
            environment.pop("SUDO_UID", None)
            environment.update(
                {
                    "AI_WPS_INSTALL_ROOT": str(install_root),
                    "WPS_JSADDONS_DIR": str(jsaddons),
                    "PATH": "{0}:{1}".format(bin_dir, environment.get("PATH", "")),
                    "PYTHON_BIN": "/usr/bin/false",
                }
            )

            result = subprocess.run(
                ["bash", str(installer)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("wps_process_check_failed", result.stdout)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(sorted(path.name for path in install_root.iterdir()), ["keep.txt"])
            self.assertEqual(list(jsaddons.iterdir()), [])

    def test_private_runtime_installs_hashed_lock_to_release_target(self) -> None:
        script = ROOT / "phase1-delivery-kit/installer/install_private_runtime.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            bootstrap = root / "bootstrap"
            target = root / "release" / "python-runtime"
            runtime_wheels = runtime / "wheels"
            bootstrap_wheels = bootstrap / "wheels"
            runtime_wheels.mkdir(parents=True)
            bootstrap_wheels.mkdir(parents=True)
            runtime_wheel = runtime_wheels / "demo-1.0-py3-none-any.whl"
            bootstrap_wheel = bootstrap_wheels / "pip-24.0-py3-none-any.whl"
            runtime_wheel.write_bytes(b"runtime-wheel")
            bootstrap_wheel.write_bytes(b"bootstrap-wheel")
            runtime_hash = hashlib.sha256(runtime_wheel.read_bytes()).hexdigest()
            bootstrap_hash = hashlib.sha256(bootstrap_wheel.read_bytes()).hexdigest()
            (runtime / "requirements-lock.txt").write_text(
                "demo==1.0 --hash=sha256:{0}\n".format(runtime_hash),
                encoding="utf-8",
            )
            (runtime / "SHA256SUMS").write_text(
                "{0}  wheels/{1}\n".format(runtime_hash, runtime_wheel.name)
                + "{0}  requirements-lock.txt\n".format(
                    hashlib.sha256(
                        (runtime / "requirements-lock.txt").read_bytes()
                    ).hexdigest()
                ),
                encoding="utf-8",
            )
            (bootstrap / "SHA256SUMS").write_text(
                "{0}  wheels/{1}\n".format(bootstrap_hash, bootstrap_wheel.name),
                encoding="utf-8",
            )
            python_log = root / "python.log"
            python_stub = root / "python"
            python_stub.write_text(
                """#!/usr/bin/env bash
printf 'PYTHONNOUSERSITE=%s PYTHONPATH=%s ARGS=%s\\n' "${PYTHONNOUSERSITE:-}" "${PYTHONPATH:-}" "$*" >> "$PYTHON_STUB_LOG"
if [[ " $* " == *" --target "* ]]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--target" ]; then
      mkdir -p "$2"
      printf '%s\\n' installed > "$2/demo-installed.txt"
      break
    fi
    shift
  done
fi
exit 0
""",
                encoding="utf-8",
            )
            python_stub.chmod(0o755)
            environment = dict(os.environ)
            environment["PYTHON_STUB_LOG"] = str(python_log)

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    str(python_stub),
                    str(runtime),
                    str(bootstrap),
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            invocations = python_log.read_text(encoding="utf-8")
            self.assertIn("PYTHONNOUSERSITE=1", invocations)
            self.assertIn("--require-hashes", invocations)
            self.assertIn("--target {0}".format(target), invocations)
            self.assertNotIn(" --user ", invocations)
            self.assertTrue((target / "demo-installed.txt").is_file())
            self.assertEqual(
                (target / "requirements-lock.txt").read_text(encoding="utf-8"),
                (runtime / "requirements-lock.txt").read_text(encoding="utf-8"),
            )

    def test_private_runtime_rejects_corrupt_wheel_before_target_write(self) -> None:
        script = ROOT / "phase1-delivery-kit/installer/install_private_runtime.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            bootstrap = root / "bootstrap"
            target = root / "release" / "python-runtime"
            (runtime / "wheels").mkdir(parents=True)
            (bootstrap / "wheels").mkdir(parents=True)
            wheel = runtime / "wheels" / "demo-1.0-py3-none-any.whl"
            wheel.write_bytes(b"corrupt")
            (runtime / "requirements-lock.txt").write_text(
                "demo==1.0 --hash=sha256:{0}\n".format("0" * 64),
                encoding="utf-8",
            )
            (runtime / "SHA256SUMS").write_text(
                "{0}  wheels/{1}\n".format("0" * 64, wheel.name),
                encoding="utf-8",
            )
            (bootstrap / "SHA256SUMS").write_text("", encoding="utf-8")

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    sys.executable,
                    str(runtime),
                    str(bootstrap),
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("offline_hash_verification_failed", result.stdout)
            self.assertFalse(target.exists())

    def test_uvicorn_start_uses_release_private_runtime_and_disables_user_site(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kit = root / "adapter-start-kit"
            shutil.copytree(ROOT / "adapter-start-kit", kit)
            (kit / "adapter_service").mkdir()
            private_runtime = kit / "python-runtime"
            private_runtime.mkdir()
            state = root / "state"
            backup = root / "backups"
            var = root / "var"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            python_log = root / "python.log"
            started = root / "started"
            python_stub = bin_dir / "python"
            python_stub.write_text(
                """#!/usr/bin/env bash
printf 'PYTHONNOUSERSITE=%s PYTHONPATH=%s ARGS=%s\\n' "${PYTHONNOUSERSITE:-}" "${PYTHONPATH:-}" "$*" >> "$PYTHON_STUB_LOG"
if [[ " $* " == *" -m uvicorn "* ]]; then
  printf '%s\\n' started > "$PYTHON_STUB_STARTED"
  sleep 10
fi
exit 0
""",
                encoding="utf-8",
            )
            python_stub.chmod(0o755)
            curl_stub = bin_dir / "curl"
            curl_stub.write_text(
                """#!/usr/bin/env bash
if [ -f "$PYTHON_STUB_STARTED" ]; then
  printf '%s' '{"success":true,"data":{"status":"ready","version":"0.23.1-alpha","mode":"uvicorn"}}'
  exit 0
fi
exit 1
""",
                encoding="utf-8",
            )
            curl_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_STATE_DIR": str(state),
                    "AI_WPS_BACKUP_DIR": str(backup),
                    "AI_WPS_VAR_DIR": str(var),
                    "PATH": "{0}:{1}".format(bin_dir, environment.get("PATH", "")),
                    "PYTHON_BIN": str(python_stub),
                    "PYTHON_STUB_LOG": str(python_log),
                    "PYTHON_STUB_STARTED": str(started),
                }
            )

            result = subprocess.run(
                ["bash", str(kit / "scripts/start_uvicorn_adapter.sh"), "28100"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            pid_file = var / "run" / "adapter.pid"
            if pid_file.is_file():
                try:
                    os.kill(int(pid_file.read_text(encoding="utf-8").strip()), 15)
                except (OSError, ValueError):
                    pass

            self.assertEqual(result.returncode, 0, result.stderr)
            invocations = python_log.read_text(encoding="utf-8")
            self.assertIn("PYTHONNOUSERSITE=1", invocations)
            self.assertIn("PYTHONPATH={0}".format(private_runtime), invocations)
            self.assertIn("ARGS=-s -m uvicorn", invocations)

    def test_installed_release_does_not_fallback_when_private_runtime_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kit = root / "adapter-start-kit"
            shutil.copytree(ROOT / "adapter-start-kit", kit)
            (kit / ".release-private-runtime-required").touch()
            state = root / "state"
            backup = root / "backups"
            var = root / "var"
            python_log = root / "python.log"
            python_stub = root / "python"
            python_stub.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' invoked >> \"$PYTHON_STUB_LOG\"\n",
                encoding="utf-8",
            )
            python_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_STATE_DIR": str(state),
                    "AI_WPS_BACKUP_DIR": str(backup),
                    "AI_WPS_VAR_DIR": str(var),
                    "PYTHON_BIN": str(python_stub),
                    "PYTHON_STUB_LOG": str(python_log),
                }
            )

            result = subprocess.run(
                ["bash", str(kit / "scripts/start_uvicorn_adapter.sh"), "28100"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("private_runtime_missing", result.stdout)
            self.assertFalse(python_log.exists())

    def test_candidate_preflight_checks_import_start_version_and_readiness(self) -> None:
        script = ROOT / "phase1-delivery-kit/installer/preflight_candidate.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "candidate"
            adapter_service = candidate / "adapter_service"
            private_runtime = candidate / "python-runtime"
            preflight_var = root / "preflight-var"
            bin_dir = root / "bin"
            adapter_service.mkdir(parents=True)
            private_runtime.mkdir()
            bin_dir.mkdir()
            python_log = root / "python.log"
            started = root / "started"
            python_stub = bin_dir / "python"
            python_stub.write_text(
                """#!/usr/bin/env bash
printf 'PYTHONNOUSERSITE=%s PYTHONPATH=%s ARGS=%s\\n' "${PYTHONNOUSERSITE:-}" "${PYTHONPATH:-}" "$*" >> "$PYTHON_STUB_LOG"
if [[ " $* " == *" -m uvicorn "* ]]; then
  printf '%s\\n' "$$" > "$PYTHON_STUB_STARTED"
  sleep 10
fi
exit 0
""",
                encoding="utf-8",
            )
            python_stub.chmod(0o755)
            curl_stub = bin_dir / "curl"
            curl_stub.write_text(
                """#!/usr/bin/env bash
if [ ! -f "$PYTHON_STUB_STARTED" ]; then
  exit 1
fi
url="${@: -1}"
case "$url" in
  */health/live)
    printf '%s' '{"success":true,"data":{"status":"live","version":"0.23.1-alpha"}}'
    ;;
  */health/ready)
    printf '%s' '{"success":true,"data":{"status":"ready","version":"0.23.1-alpha"}}'
    ;;
  */health)
    printf '%s' '{"success":true,"data":{"status":"ready","version":"0.23.1-alpha","mode":"uvicorn"}}'
    ;;
esac
""",
                encoding="utf-8",
            )
            curl_stub.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "PATH": "{0}:{1}".format(bin_dir, environment.get("PATH", "")),
                    "PYTHON_STUB_LOG": str(python_log),
                    "PYTHON_STUB_STARTED": str(started),
                }
            )

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    str(python_stub),
                    str(candidate),
                    str(private_runtime),
                    "28101",
                    "0.23.1-alpha",
                    str(preflight_var),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("candidate_preflight=ready", result.stdout)
            invocations = python_log.read_text(encoding="utf-8")
            self.assertIn("PYTHONNOUSERSITE=1", invocations)
            self.assertIn("PYTHONPATH={0}".format(private_runtime), invocations)
            self.assertIn("ARGS=-s -c", invocations)
            self.assertIn("ARGS=-s -m uvicorn", invocations)
            candidate_pid = int(started.read_text(encoding="utf-8").strip())
            with self.assertRaises(OSError):
                os.kill(candidate_pid, 0)

    def test_standalone_adapter_exposes_split_health_and_recovery_guard(self) -> None:
        script = (ROOT / "adapter_service/standalone_adapter.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('path == "/health/live"', script)
        self.assertIn('path == "/health/ready"', script)
        self.assertIn('path == "/recovery/backups"', script)
        self.assertIn('path == "/recovery/diagnostics"', script)
        self.assertNotIn('path == "/recovery/restore"', script)
        self.assertIn("get_health_snapshot", script)
        self.assertIn("get_operation_block", script)
        self.assertIn("ADAPTER_RECOVERY_MODE", script)

    def test_release_manifest_declares_runtime_path_contract(self) -> None:
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )

        policy = manifest["runtimeStatePolicy"]
        self.assertEqual(policy["sharedStateEnv"], "AI_WPS_STATE_DIR")
        self.assertEqual(policy["backupEnv"], "AI_WPS_BACKUP_DIR")
        self.assertEqual(policy["runtimeVarEnv"], "AI_WPS_VAR_DIR")
        self.assertTrue(policy["legacyLayoutFallback"])
        self.assertEqual(policy["snapshotRoot"], "state/")
        self.assertEqual(
            policy["snapshotExcluded"],
            ["backups/", "var/logs/", "var/run/", "var/transactions/"],
        )
        self.assertEqual(policy["copyVerificationField"], "copyVerified")
        self.assertFalse(policy["recoveryActivation"]["automaticSwitch"])
        self.assertEqual(
            policy["recoveryActivation"]["explicitFlag"], "--activate-recovery"
        )
        self.assertEqual(
            policy["recoveryActivation"]["terminalStatus"],
            "recovery_activated",
        )
        self.assertIsNone(policy["recoveryApi"]["restoreEndpoint"])

    def test_release_manifest_declares_complete_generation_contract(self) -> None:
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )

        policy = manifest["releaseGenerationPolicy"]
        self.assertEqual(policy["releaseRoot"], "releases/<version>/")
        self.assertEqual(policy["currentPointer"], "current")
        self.assertEqual(policy["transactionLogRoot"], "var/transactions/")
        self.assertEqual(policy["switchStrategy"], "durable-compensating-rename")
        self.assertEqual(
            policy["components"],
            [
                "adapter_release",
                "word_plugin",
                "excel_plugin",
                "ppt_plugin",
                "publish_manifest",
                "runtime_state_snapshot",
                "current_pointer",
            ],
        )

    def test_delivery_declares_release_private_runtime_contract(self) -> None:
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        delivery_sources = self._delivery_source_pairs()
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        smoke_test = (ROOT / "phase1-delivery-kit/scripts/phase1_smoke_test.sh").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            manifest["adapter"]["privateRuntime"],
            {
                "path": "python-runtime/",
                "lock": "packages/kylin-v10-arm-py38/requirements-lock.txt",
                "hashManifest": "packages/kylin-v10-arm-py38/SHA256SUMS",
                "disableUserSite": True,
            },
        )
        self.assertIn(
            (
                "offline-deps/kylin-v10-arm-py38/requirements-lock.txt",
                "packages/kylin-v10-arm-py38/requirements-lock.txt",
            ),
            delivery_sources,
        )
        self.assertIn(
            (
                "offline-deps/kylin-v10-arm-py38/SHA256SUMS",
                "packages/kylin-v10-arm-py38/SHA256SUMS",
            ),
            delivery_sources,
        )
        self.assertNotIn(" --user ", installer)
        self.assertIn("install_private_runtime.sh", installer)
        self.assertIn("preflight_candidate.sh", installer)
        self.assertIn("python-runtime", smoke_test)
        self.assertIn("PYTHONNOUSERSITE=1", smoke_test)

    def test_uvicorn_start_script_replaces_stale_running_adapter(self) -> None:
        script = (ROOT / "adapter-start-kit/scripts/start_uvicorn_adapter.sh").read_text(encoding="utf-8")

        self.assertIn("EXPECTED_VERSION", script)
        self.assertIn("CURRENT_VERSION", script)
        self.assertIn('EXPECTED_VERSION="${EXPECTED_VERSION:-0.23.1-alpha}"', script)
        self.assertIn("replace_existing_adapter", script)
        self.assertIn("adapter_stale_running", script)

    def test_adapter_operations_scripts_manage_uvicorn_and_provider_diagnostics(self) -> None:
        scripts = {
            name: (ROOT / "adapter-start-kit/scripts" / name).read_text(encoding="utf-8")
            for name in [
                "start_adapter.sh",
                "restart_adapter.sh",
                "status_adapter.sh",
                "check_health.sh",
                "show_logs.sh",
                "stop_adapter.sh",
            ]
        }

        self.assertIn("start_uvicorn_adapter.sh", scripts["start_adapter.sh"])
        self.assertIn("start_uvicorn_adapter.sh", scripts["restart_adapter.sh"])
        self.assertIn("/provider/status", scripts["status_adapter.sh"])
        self.assertIn("/health/live", scripts["status_adapter.sh"])
        self.assertIn("/health/live", scripts["check_health.sh"])
        self.assertIn("/health/ready", scripts["check_health.sh"])
        self.assertIn("adapter_business_status", scripts["check_health.sh"])
        self.assertIn("/provider/route-diagnostics", scripts["check_health.sh"])
        self.assertIn("/provider/debug-last", scripts["check_health.sh"])
        self.assertIn("provider=mock", scripts["show_logs.sh"])
        self.assertIn("stop_port_listener", scripts["stop_adapter.sh"])

    def test_health_script_rejects_recovery_from_ready_http_status(self) -> None:
        script = ROOT / "adapter-start-kit/scripts/check_health.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            curl_stub = bin_dir / "curl"
            curl_stub.write_text(
                """#!/usr/bin/env bash
url="${@: -1}"
case "$url" in
  */health/live)
    printf '%s' '{"success":true,"data":{"status":"live"}}'
    ;;
  */health/ready)
    printf '%s' '503'
    ;;
  */health)
    printf '%s' '{"success":true,"data":{"service":"wps-ai-adapter","status":"recovery","version":"0.23.1-alpha","mode":"uvicorn","providerConfigured":false,"providerAuthSource":"none","subsystems":{"modelConfigurations":{"status":"recovery"},"writingPolicies":{"status":"ready"}}}}'
    ;;
  *)
    printf '%s' '{}'
    ;;
esac
""",
                encoding="utf-8",
            )
            curl_stub.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = "{0}:{1}".format(
                bin_dir, environment.get("PATH", "")
            )

            result = subprocess.run(
                ["bash", str(script), "18100"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("adapter_business_status=recovery", result.stdout)
        self.assertIn("ready_http_status=503", result.stdout)
        self.assertNotIn("provider_status=reachable", result.stdout)

    def test_standalone_adapter_exposes_model_configuration_management(self) -> None:
        script = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")

        self.assertIn('path == "/provider/model-configurations"', script)
        self.assertIn('action == "copy"', script)
        self.assertIn('action == "validate"', script)
        self.assertIn('path == "/provider/workflow-profiles"', script)
        self.assertIn("def do_PATCH", script)
        self.assertIn('path.endswith("/activate")', script)
        self.assertIn('path.endswith("/api-key")', script)
        self.assertIn("ModelConfigurationStore", script)
        self.assertIn("WorkflowProfileCompatibilityStore", script)

    def test_delivery_audits_eight_versioned_system_prompts(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")
        auditor = (ROOT / "packaging/audit_phase1_delivery.py").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (ROOT / "phase1-delivery-kit/release-manifest.json").read_text(encoding="utf-8")
        )

        self.assertIn("SystemPromptStore", script)
        self.assertIn("PROMPT_REFERENCE_MISSING", auditor)
        self.assertIn("PROMPT_HASH_MISMATCH", auditor)
        self.assertIn(
            (
                "adapter_service/system_prompts",
                "packages/adapter-start-kit/adapter_service/system_prompts",
            ),
            self._delivery_source_pairs(),
        )
        self.assertIn(
            "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json",
            self._delivery_target_files(),
        )
        self.assertEqual(manifest["adapter"]["systemPromptCount"], 8)
        self.assertEqual(
            manifest["adapter"]["accessMethods"],
            ["workflow_platform", "direct_model"],
        )
        self.assertEqual(
            manifest["adapter"]["systemPromptManifest"],
            "packages/adapter-start-kit/adapter_service/system_prompts/manifest.json",
        )
        self.assertTrue((ROOT / "adapter_service/system_prompts/manifest.json").is_file())

    def test_standalone_adapter_exposes_ppt_background_routes(self) -> None:
        script = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")

        self.assertIn("def parse_ppt_request", script)
        self.assertIn("def ppt_slide_assistant_job_payload", script)
        self.assertIn('path == "/ppt/slide-assistant/jobs"', script)
        self.assertIn('path.startswith("/ppt/slide-assistant/jobs/")', script)
        self.assertIn('ppt_slide_assistant_prefix = "/ppt/slide-assistant/jobs/"', script)
        self.assertIn("PPT_SLIDE_ASSISTANT_JOB_STORE.cancel", script)
        self.assertIn("close_ppt_resources", script)
        self.assertIn("PPT_SLIDE_JOB_NOT_FOUND", script)
        self.assertIn("def parse_ppt_structure_request", script)
        self.assertIn("def ppt_structure_review_job_payload", script)
        self.assertIn('path == "/ppt/structure-review/jobs"', script)
        self.assertIn('path.startswith("/ppt/structure-review/jobs/")', script)
        self.assertIn('ppt_structure_review_prefix = "/ppt/structure-review/jobs/"', script)
        self.assertIn("PPT_STRUCTURE_REVIEW_JOB_STORE.cancel", script)
        self.assertIn("PPT_STRUCTURE_JOB_NOT_FOUND", script)
        self.assertIn(
            '"ppt.structure_review" if path.startswith("/ppt/structure-review")',
            script,
        )

    def test_adapter_autostart_scripts_install_systemd_service(self) -> None:
        install_script = (ROOT / "adapter-start-kit/scripts/install_autostart.sh").read_text(
            encoding="utf-8"
        )
        unit_script = (ROOT / "adapter-start-kit/scripts/systemd_unit.sh").read_text(
            encoding="utf-8"
        )
        uninstall_script = (ROOT / "adapter-start-kit/scripts/uninstall_autostart.sh").read_text(
            encoding="utf-8"
        )
        guide = (ROOT / "adapter-start-kit/docs/autostart-guide.md").read_text(encoding="utf-8")

        self.assertIn("ai-wps-adapter.service", install_script)
        self.assertIn("systemctl enable --now", install_script)
        self.assertIn("render_adapter_systemd_unit", install_script)
        self.assertIn("ExecStart=", unit_script)
        self.assertIn("scripts/start_adapter.sh", unit_script)
        self.assertIn("Restart=on-failure", unit_script)
        self.assertIn("User=", unit_script)
        self.assertIn("systemctl disable --now", uninstall_script)
        self.assertIn("daemon-reload", uninstall_script)
        self.assertIn("开机自启动", guide)
        self.assertIn("bash scripts/install_autostart.sh", guide)

    def test_phase1_upgrade_rebinds_existing_systemd_service_to_current(self) -> None:
        installer = (
            ROOT / "phase1-delivery-kit/installer/install_phase1.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("install_current_systemd_service", installer)
        self.assertIn('"$CURRENT_LINK" \\', installer)
        self.assertIn('systemctl start "$SYSTEMD_SERVICE_NAME"', installer)
        self.assertIn("AI_WPS_SYSTEMD_MANAGED_BY_PARENT", installer)
        self.assertIn("--defer-commit", installer)
        self.assertIn('"$TRANSACTION_TOOL" commit', installer)
        self.assertIn("compensate_systemd_release", installer)
        self.assertIn("recover_systemd_handoff", installer)
        self.assertNotIn("exec runuser", installer)

    def test_phase1_delivery_includes_smart_write_dify_manual(self) -> None:
        self.assertIn(
            ("docs/operations", "docs/operations"),
            self._delivery_source_pairs(),
        )
        for name in [
            "dify-smart-write-workflow.md",
            "dify-smart-imitation-workflow.md",
            "dify-document-review-workflow.md",
            "dify-format-review-workflow.md",
            "dify-excel-analysis-workflow.md",
            "dify-excel-formula-assistant-workflow.md",
            "dify-ppt-structure-review-workflow.md",
        ]:
            self.assertIn("docs/operations/" + name, self._delivery_target_files())
            self.assertTrue((ROOT / "docs/operations" / name).is_file())

    def test_formula_assistant_release_guide_defines_kylin_fallback_and_read_only_evidence(self) -> None:
        guide = (ROOT / "docs/operations/dify-excel-formula-assistant-workflow.md").read_text(
            encoding="utf-8"
        )
        checklist = (ROOT / "phase1-delivery-kit/docs/phase1-acceptance-checklist.md").read_text(
            encoding="utf-8"
        )
        record = (ROOT / "phase1-delivery-kit/docs/phase1-acceptance-record.md").read_text(
            encoding="utf-8"
        )

        for token in [
            "HasFormula",
            "FormulaLocal",
            "FormulaR1C1",
            "Formula → FormulaLocal → FormulaR1C1",
            "30×20",
            "计算模式",
            "待目标机执行",
        ]:
            self.assertIn(token, guide + checklist + record)

    def test_v0231_acceptance_record_tracks_release_issue_and_external_validation(self) -> None:
        def assert_release_acceptance_state(record_text: str) -> None:
            self.assertIn("Issue #33", record_text)
            self.assertIn("Python 3.8 最终包生命周期门禁", record_text)
            self.assertIn("白名单组装与静态审计通过", record_text)
            self.assertIn("尚未标记候选构建", record_text)
            self.assertIn("不得宣称目标机已经恢复", record_text)
            self.assertIn("父票后续动作", record_text)

        record = (ROOT / "phase1-delivery-kit/docs/phase1-acceptance-record.md").read_text(
            encoding="utf-8"
        )
        assert_release_acceptance_state(record)

    def test_delivery_includes_excel_and_ppt_prompt_templates(self) -> None:
        self.assertIn(
            ("docs/prompt-templates", "docs/prompt-templates"),
            self._delivery_source_pairs(),
        )
        template_names = [
            "excel-smart-analysis-prompt-template.md",
            "excel-formula-assistant-prompt-template.md",
            "ppt-smart-summary-prompt-template.md",
            "ppt-structure-review-prompt-template.md",
        ]
        for name in template_names:
            self.assertIn("docs/prompt-templates/" + name, self._delivery_target_files())
            template_path = ROOT / "docs/prompt-templates" / name
            self.assertTrue(template_path.is_file(), f"missing prompt template: {name}")
            text = template_path.read_text(encoding="utf-8")
            for required_text in [
                "适用任务",
                "输入",
                "System Prompt",
                "变量",
                "输出契约",
                "<think>",
                "max token",
                "错误",
                "禁止事项",
            ]:
                self.assertIn(required_text, text)
            self.assertNotIn("Bearer sk-", text)
            self.assertNotIn("provider_api_key", text)

    def test_phase1_packaging_includes_word_and_excel_addins(self) -> None:
        sources = self._delivery_source_pairs()
        self.assertIn(
            (
                "formal-plugin-kit/wps-ai-assistant_1.0.0",
                "packages/wps-ai-assistant_1.0.0",
            ),
            sources,
        )
        targets = self._delivery_target_files()
        self.assertIn(
            "packages/wps-ai-assistant_1.0.0/manifest.json",
            targets,
        )
        self.assertIn(
            "packages/wps-ai-assistant-et_1.0.0/manifest.json",
            targets,
        )
        self.assertIn(
            (
                "formal-plugin-kit/wps-ai-assistant-et_1.0.0",
                "packages/wps-ai-assistant-et_1.0.0",
            ),
            sources,
        )

    def test_phase1_packaging_includes_all_three_host_addins_and_ppt_guide(self) -> None:
        self.assertIn(
            (
                "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0",
                "packages/wps-ai-assistant-wpp_1.0.0",
            ),
            self._delivery_source_pairs(),
        )
        self.assertIn(
            "packages/wps-ai-assistant-wpp_1.0.0/manifest.json",
            self._delivery_target_files(),
        )
        self.assertIn(
            "docs/operations/dify-ppt-slide-assistant-workflow.md",
            self._delivery_target_files(),
        )
        self.assertTrue(
            (ROOT / "docs/operations/dify-ppt-slide-assistant-workflow.md").is_file()
        )

    def test_phase1_installer_installs_word_and_excel_addins(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('WORD_PLUGIN_NAME="wps-ai-assistant_1.0.0"', script)
        self.assertIn('EXCEL_PLUGIN_NAME="wps-ai-assistant-et_1.0.0"', script)
        self.assertIn('name="wps-ai-assistant"', script)
        self.assertIn('type="wps"', script)
        self.assertIn('name="wps-ai-assistant-et"', script)
        self.assertIn('type="et"', script)
        self.assertIn('grep -v \'name="wps-ai-assistant"\'', script)
        self.assertIn('grep -v \'name="wps-ai-assistant-et"\'', script)
        self.assertIn("prepare_runtime_state", script)

    def test_phase1_installer_installs_ppt_addin_in_same_package(self) -> None:
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        publish_xml = (ROOT / "phase1-delivery-kit/wps-jsaddons/publish.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn('PPT_PLUGIN_NAME="wps-ai-assistant-wpp_1.0.0"', installer)
        self.assertIn('name="wps-ai-assistant-wpp"', installer)
        self.assertIn('type="wpp"', installer)
        self.assertIn('grep -v \'name="wps-ai-assistant-wpp"\'', installer)
        self.assertIn('name="wps-ai-assistant-wpp"', publish_xml)
        self.assertIn('type="wpp"', publish_xml)
        self.assertIn("prepare_runtime_state", installer)
        self.assertIn("config/adapter.json", installer)
        self.assertIn("provider_api_key", installer)
        self.assertIn("provider_api_keys", installer)

    def test_smart_imitation_icon_and_config_are_packaged(self) -> None:
        self.assertTrue(
            (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png").exists()
        )
        self.assertTrue((ROOT / "docs/operations/dify-smart-imitation-workflow.md").exists())
        config = (ROOT / "config/adapter.example.json").read_text(encoding="utf-8")
        self.assertIn('"word.smart_imitation": "word_smart_imitation"', config)

    def test_phase1_installer_migrates_adapter_runtime_configuration(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(encoding="utf-8")

        self.assertIn("prepare_runtime_state", script)
        self.assertIn("legacy_runtime_state_exists", script)
        self.assertIn("runtime_state_migration_status", script)
        self.assertIn("config/adapter.json", script)
        self.assertIn("run/provider_api_key", script)
        self.assertIn("run/provider_api_keys", script)
        self.assertNotIn('copy_dir "$ADAPTER_SOURCE" "$ADAPTER_TARGET"', script)

    def test_phase1_installer_preserves_writing_policy_database(self) -> None:
        script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("run/writing_policies.db", script)
        self.assertIn("prepare_runtime_state", script)
        self.assertIn("runtime_state_snapshot_reason=pre_install", script)

    def test_recovery_candidate_restart_preserves_legacy_runtime_layout(self) -> None:
        script = (
            ROOT / "phase1-delivery-kit/installer/install_phase1.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("restart_previous_adapter()", script)
        self.assertIn(
            'if [ "$PREVIOUS_RELEASE_VERSION" = "legacy" ] && ! runtime_state_exists; then',
            script,
        )
        self.assertIn(
            'env -u AI_WPS_STATE_DIR -u AI_WPS_BACKUP_DIR -u AI_WPS_VAR_DIR',
            script,
        )
        self.assertGreaterEqual(script.count("restart_previous_adapter"), 3)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            adapter = root / "legacy-adapter"
            (adapter / "scripts").mkdir(parents=True)
            marker = root / "legacy-restarted"
            start_script = adapter / "scripts/start_uvicorn_adapter.sh"
            start_script.write_text(
                "#!/usr/bin/env bash\n"
                "[ -z \"${AI_WPS_STATE_DIR+x}\" ] || exit 21\n"
                "[ -z \"${AI_WPS_BACKUP_DIR+x}\" ] || exit 22\n"
                "[ -z \"${AI_WPS_VAR_DIR+x}\" ] || exit 23\n"
                "printf '%s\\n' restarted > \"$LEGACY_RESTART_MARKER\"\n",
                encoding="utf-8",
            )
            start_script.chmod(0o755)
            harness = root / "restart-legacy.sh"
            function_definitions = script.split('\nparse_arguments "$@"\n', 1)[0]
            harness.write_text(
                function_definitions
                + "\nADAPTER_TARGET=\"$TEST_LEGACY_ADAPTER\"\n"
                + "PREVIOUS_RELEASE_VERSION=legacy\n"
                + "STATE_DIR=\"$TEST_MISSING_STATE\"\n"
                + "BACKUP_DIR=\"$TEST_BACKUP_DIR\"\n"
                + "VAR_DIR=\"$TEST_VAR_DIR\"\n"
                + "PORT=28123\n"
                + "export AI_WPS_STATE_DIR=\"$STATE_DIR\"\n"
                + "export AI_WPS_BACKUP_DIR=\"$BACKUP_DIR\"\n"
                + "export AI_WPS_VAR_DIR=\"$VAR_DIR\"\n"
                + "restart_previous_adapter\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "TEST_LEGACY_ADAPTER": str(adapter),
                    "TEST_MISSING_STATE": str(root / "missing-state"),
                    "TEST_BACKUP_DIR": str(root / "backups"),
                    "TEST_VAR_DIR": str(root / "var"),
                    "LEGACY_RESTART_MARKER": str(marker),
                }
            )

            result = subprocess.run(
                ["bash", str(harness)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8"), "restarted\n")

    def test_phase1_installer_prepares_state_before_switching_release_generation(self) -> None:
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        install_flow = installer.rsplit('log "phase1_install_start=true"', 1)[1]

        self.assertLess(
            install_flow.index("prepare_runtime_state"),
            install_flow.index("switch_release_generation"),
        )
        self.assertLess(
            install_flow.index("create_candidate_state_snapshot"),
            install_flow.index("switch_release_generation"),
        )
        self.assertIn("prepare_release_transaction", install_flow)
        self.assertIn("finalize_release_generation", install_flow)
        self.assertNotIn('rm -rf "$ADAPTER_TARGET"', installer)
        self.assertNotIn("preserve_adapter_runtime_config", installer)
        self.assertNotIn("restore_adapter_runtime_config", installer)

    def test_phase1_delivery_generates_writing_policy_templates_and_includes_guide(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )
        guide = ROOT / "docs/operations/writing-policy-library.md"

        self.assertIn("docs/import-templates", script)
        self.assertIn("generate_csv_template", script)
        self.assertIn("generate_xlsx_template", script)
        self.assertIn("writing-policies-import-template.csv", script)
        self.assertIn("writing-policies-import-template.xlsx", script)
        sources = self._delivery_source_pairs()
        self.assertIn(("docs/operations", "docs/operations"), sources)
        self.assertIn(
            ("docs/writing-policy-sources.md", "docs/writing-policy-sources.md"),
            sources,
        )
        targets = self._delivery_target_files()
        self.assertIn("docs/operations/writing-policy-library.md", targets)
        self.assertIn("docs/writing-policy-sources.md", targets)
        self.assertIn(
            "packages/adapter-start-kit/adapter_service/app/main.py",
            targets,
        )
        self.assertIn(
            "packages/adapter-start-kit/adapter_service/writing_policy_packs/yangqi-tech-writing-base.json",
            targets,
        )
        self.assertIn(
            (
                "adapter_service/writing_policy_packs",
                "packages/adapter-start-kit/adapter_service/writing_policy_packs",
            ),
            sources,
        )
        self.assertIn(
            ("adapter_service/app", "packages/adapter-start-kit/adapter_service/app"),
            sources,
        )
        self.assertNotIn('cp -R "$ROOT_DIR/adapter_service"', script)
        self.assertTrue(guide.is_file(), "missing writing policy operations guide")
        self.assertTrue(
            (ROOT / "adapter_service/writing_policy_packs/yangqi-tech-writing-base.json").is_file()
        )
        self.assertTrue(
            (ROOT / "adapter_service/writing_policy_packs/THIRD_PARTY_NOTICES.md").is_file()
        )

        text = guide.read_text(encoding="utf-8")
        for required_text in [
            "全局术语",
            "智能编写",
            "智能仿写",
            "文档审查",
            "5 MB",
            "|",
            "保留库内标准",
            "CSV 导出",
            "完整备份",
            "降级",
            "diagnostics",
            "损坏",
        ]:
            self.assertIn(required_text, text)

    def test_phase1_delivery_uses_v0231_release_name(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('KIT_NAME="ai-wps-phase1-delivery-${DATE_TAG}-v0231"', script)

    def test_delivery_build_revalidates_approved_pack_reviews(self) -> None:
        script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "load_pack_snapshot(pack_root)",
            script,
        )

    def test_phase1_installer_initializes_database_only_on_first_install(self) -> None:
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        function_prefix = installer.split("enable_exec_permissions() {", 1)[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter_target = Path(temp_dir) / "adapter-start-kit"
            shutil.copytree(
                ROOT / "adapter_service",
                adapter_target / "adapter_service",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "logs", "run"),
            )
            harness = Path(temp_dir) / "initialize-test.sh"
            harness.write_text(
                function_prefix
                + "\nADAPTER_TARGET=\"$1\"\n"
                + "PYTHON_BIN=\"$2\"\n"
                + "initialize_writing_policy_database\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment.pop("AI_WPS_WRITING_POLICY_DB", None)
            result = subprocess.run(
                ["bash", str(harness), str(adapter_target), sys.executable],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            database = adapter_target / "run/writing_policies.db"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(database.is_file())
            self.assertGreater(database.stat().st_size, 0)
            self.assertEqual(database.stat().st_mode & 0o777, 0o600)

            original = database.read_bytes()
            second_result = subprocess.run(
                ["bash", str(harness), str(adapter_target), sys.executable],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(database.read_bytes(), original)
            self.assertIn("writing_policy_database=reused", second_result.stdout)

    @unittest.skipUnless(
        PYTHON38_BIN,
        "AI_WPS_PYTHON38_BIN is required for the final delivery build gate",
    )
    def test_built_v0231_delivery_has_complete_safe_release_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = dict(os.environ)
            environment["DATE_TAG"] = "20260811"
            environment["PYTHON_BIN"] = sys.executable
            environment["PYTHON38_BIN"] = PYTHON38_BIN
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "packaging/build_phase1_delivery_kit.sh"),
                    temp_dir,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            archive = (
                Path(temp_dir)
                / "ai-wps-phase1-delivery-20260811-v0231.tar.gz"
            )
            self.assertTrue(archive.is_file())
            checksum = archive.with_name(archive.name + ".sha256")
            self.assertTrue(checksum.is_file())
            self.assertEqual(
                checksum.read_text(encoding="utf-8"),
                "{0}  {1}\n".format(
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    archive.name,
                ),
            )
            with tarfile.open(archive, "r:gz") as package:
                names = package.getnames()
                root = "ai-wps-phase1-delivery-20260811-v0231"
                manifest_member = package.extractfile(
                    root + "/release-manifest.json"
                )
                self.assertIsNotNone(manifest_member)
                release_manifest = json.load(manifest_member)

                self.assertEqual(release_manifest["version"], "0.23.1-alpha")
                self.assertEqual(
                    release_manifest["versionRule"],
                    "AI-WPS-P1-WORD-EXCEL-PPT-0.23.1-20260811",
                )
                self.assertEqual(
                    release_manifest["adapter"]["pythonRuntimeGate"],
                    "scripts/python38_delivery_runtime_gate.py",
                )
                self.assertEqual(release_manifest["adapter"]["minimumPython"], "3.8")
                self.assertEqual(
                    release_manifest["excelFormulaAssistantAssets"],
                    {
                        "operationsGuide": "docs/operations/dify-excel-formula-assistant-workflow.md",
                        "promptTemplate": "docs/prompt-templates/excel-formula-assistant-prompt-template.md",
                    },
                )
                self.assertEqual(
                    release_manifest["pptStructureReviewAssets"],
                    {
                        "operationsGuide": "docs/operations/dify-ppt-structure-review-workflow.md",
                        "promptTemplate": "docs/prompt-templates/ppt-structure-review-prompt-template.md",
                    },
                )
                self.assertIn(
                    root + "/docs/operations/dify-ppt-structure-review-workflow.md",
                    names,
                )
                self.assertIn(
                    root + "/docs/prompt-templates/ppt-structure-review-prompt-template.md",
                    names,
                )
                self.assertEqual(
                    set(release_manifest["writingPolicyPacks"]),
                    {
                        "yangqi-tech-writing-base",
                        "technical-document-style",
                        "official-document-style",
                        "cybersecurity-terminology",
                    },
                )
                for pack_id in release_manifest["writingPolicyPacks"]:
                    self.assertIn(
                        root
                        + "/packages/adapter-start-kit/adapter_service/"
                        + "writing_policy_packs/"
                        + pack_id
                        + ".json",
                        names,
                    )
                    self.assertIn(
                        root
                        + "/packages/adapter-start-kit/adapter_service/"
                        + "writing_policy_packs/"
                        + pack_id
                        + ".review.json",
                        names,
                    )

                required_files = [
                    "/scripts/check_python38_compatibility.py",
                    "/scripts/python38_delivery_runtime_gate.py",
                    "/docs/operations/dify-excel-formula-assistant-workflow.md",
                    "/docs/prompt-templates/excel-formula-assistant-prompt-template.md",
                    "/docs/writing-policy-sources.md",
                    "/docs/import-templates/writing-policies-import-template.csv",
                    "/docs/import-templates/writing-policies-import-template.xlsx",
                    "/packages/adapter-start-kit/adapter_service/"
                    "writing_policy_packs/THIRD_PARTY_NOTICES.md",
                    "/docs/phase1-acceptance-checklist.md",
                    "/docs/phase1-acceptance-record.md",
                ]
                for suffix in required_files:
                    self.assertIn(root + suffix, names)

                forbidden_fragments = [
                    "/run/writing_policies.db",
                    "writing_policies.db.backup-",
                    "/provider_api_key",
                    "/provider_api_keys/",
                    "/logs/",
                ]
                for name in names:
                    self.assertFalse(name.endswith(".log"), name)
                    self.assertFalse(
                        any(fragment in name for fragment in forbidden_fragments),
                        name,
                    )
                    if name.endswith((".csv", ".xlsx")):
                        self.assertIn("/docs/import-templates/", name)

    def test_taskpane_document_review_has_three_document_types_and_prompt_map(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertNotIn('value="general_technical"', html)
        self.assertIn('value="technical_solution"', html)
        self.assertIn('value="contract_acceptance"', html)
        self.assertIn('value="test_outline"', html)
        self.assertIn("DOCUMENT_REVIEW_PROMPTS", js)
        self.assertIn("applyDocumentReviewPrompt", js)

    def test_taskpane_merges_fallback_templates(self) -> None:
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("mergeTemplates", js)
        self.assertIn("technical-file-format-requirements", js)

    def test_taskpane_settings_hides_unified_key_but_keeps_compatibility(self) -> None:
        host_dirs = [
            "wps-ai-assistant_1.0.0",
            "wps-ai-assistant-et_1.0.0",
            "wps-ai-assistant-wpp_1.0.0",
        ]
        host_files = [
            (
                ROOT / "formal-plugin-kit" / host_dir / "taskpane.html",
                ROOT / "formal-plugin-kit" / host_dir / "taskpane.js",
            )
            for host_dir in host_dirs
        ]
        html = host_files[0][0].read_text(encoding="utf-8")
        js = host_files[0][1].read_text(encoding="utf-8")
        standalone = (ROOT / "adapter_service/standalone_adapter.py").read_text(encoding="utf-8")
        installer = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("renderTaskRoutes", js)
        self.assertIn("workflow-profile-manager", html)
        self.assertIn("workflow-profile-select", html)
        self.assertIn("/provider/model-configurations", js)
        self.assertIn("word.smart_write", js)
        self.assertIn("word.smart_imitation", js)
        self.assertIn("word.document_review", js)
        self.assertIn("word.format_review", js)
        self.assertNotIn("word.smart_format", js)
        for host_html_path, host_js_path in host_files:
            host_html = host_html_path.read_text(encoding="utf-8")
            host_js = host_js_path.read_text(encoding="utf-8")
            self.assertNotIn('id="provider-api-key"', host_html)
            self.assertNotIn('id="btn-save-api-key"', host_html)
            self.assertNotIn('id="btn-clear-api-key"', host_html)
            self.assertNotIn('request("/provider/api-key"', host_js)
        self.assertIn('path == "/provider/api-key"', standalone)
        self.assertIn("run/provider_api_key", installer)
        self.assertIn("run/provider_api_keys", installer)
        self.assertNotIn('id="btn-probe"', html)
        self.assertNotIn("runProbe", js)

    def test_smart_write_taskpane_uses_compact_prompt_controls(self) -> None:
        html = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html").read_text(
            encoding="utf-8"
        )
        js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js").read_text(encoding="utf-8")

        self.assertIn("智能编写", html)
        self.assertIn('id="write-action"', html)
        self.assertIn('value="standard"', html)
        self.assertIn("技术方案正式", html)
        self.assertIn('id="rewrite-summary-card"', html)
        self.assertIn("rewrite-style-detail", html)
        self.assertIn("rewrite-focus-detail", html)
        self.assertIn("rewrite-length-detail", html)
        self.assertIn("rewrite-output-detail", html)
        self.assertIn("prompt-fragment-card", html)
        self.assertIn('id="prompt-fragment-card" class="prompt-fragment-card" hidden', html)
        self.assertIn("rewrite-prompt-label", html)
        self.assertIn("补充要求：请突出风险和下一步计划，压缩到200字以内。", html)
        self.assertIn("updateRewritePromptPreview", js)
        self.assertIn("showPromptFragments: false", js)
        self.assertIn('rewriteStyle: "standard"', js)
        self.assertIn('focusPoint: "complete"', js)
        self.assertIn('lengthMode: "same"', js)
        self.assertIn("prompt-fragment-card\").hidden = !shouldShowPromptFragments", js)
        self.assertIn("REWRITE_STYLE_PROMPTS", js)
        self.assertIn("不要原样返回待处理内容", js)
        self.assertIn("/word/smart-write", js)
        self.assertNotIn("/word/rewrite", js)

    def test_ribbon_uses_current_entries_and_current_icons(self) -> None:
        ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml").read_text(
            encoding="utf-8"
        )
        ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js").read_text(
            encoding="utf-8"
        )

        for label in ["智能编写", "智能仿写", "文档审查", "格式审查", "设置"]:
            self.assertIn('label="{0}"'.format(label), ribbon)
        for old_label in ["格式校对", "智能排版", "技术文档审查"]:
            self.assertNotIn('label="{0}"'.format(old_label), ribbon)
        self.assertNotIn("智能改写", ribbon)
        self.assertNotIn("智能续写", ribbon)
        self.assertIn("btnAiSmartWrite", ribbon)
        self.assertIn("btnAiSmartImitation", ribbon)
        self.assertNotIn("btnAiRewrite", ribbon)
        self.assertNotIn("btnAiContinue", ribbon)
        self.assertIn("icon-smart-write.png", ribbon_js)
        self.assertIn("icon-smart-imitation.png", ribbon_js)
        self.assertIn("icon-review.png", ribbon_js)

    def test_phase1_publish_xml_contains_word_and_excel_addins(self) -> None:
        publish_xml = (ROOT / "phase1-delivery-kit/wps-jsaddons/publish.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn('name="wps-ai-assistant"', publish_xml)
        self.assertIn('type="wps"', publish_xml)
        self.assertIn('name="wps-ai-assistant-et"', publish_xml)
        self.assertIn('type="et"', publish_xml)

    def test_excel_addin_contains_only_excel_ribbon_entries(self) -> None:
        ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml").read_text(
            encoding="utf-8"
        )
        ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('label="智能分析"', ribbon)
        self.assertIn('label="设置"', ribbon)
        self.assertNotIn('label="智能编写"', ribbon)
        self.assertNotIn('label="智能仿写"', ribbon)
        self.assertNotIn('label="文档审查"', ribbon)
        self.assertNotIn('label="格式审查"', ribbon)
        self.assertIn("btnAiExcelAnalysis", ribbon_js)
        self.assertIn("icon-excel-analysis.png", ribbon_js)
