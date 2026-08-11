import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import load_settings, save_config_payload
from app.core.runtime_paths import resolve_runtime_paths
from app.services.provider_client import (
    get_local_api_key_path,
    get_route_api_key_path,
    save_local_api_key,
    save_route_api_key,
)
from app.services.model_configurations import ModelConfigurationStore
from app.services.workflow_profiles import WorkflowProfileStore
from app.services.writing_policy.service import default_database_path
from app.services.writing_policy.store import WritingPolicyStore


ROOT = Path(__file__).resolve().parents[2]


class RuntimePathContractTests(unittest.TestCase):
    def test_runtime_state_contract_is_observable_from_external_python_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            program_root = temp_root / "adapter-start-kit"
            service_root = program_root / "adapter_service"
            shutil.copytree(ROOT / "adapter_service/app", service_root / "app")
            probe = (
                "import json, stat\n"
                "from app.core.config import load_settings, save_config_payload\n"
                "from app.core.runtime_paths import resolve_runtime_paths\n"
                "from app.services.provider_client import save_local_api_key, save_route_api_key\n"
                "from app.services.writing_policy.service import default_database_path\n"
                "from app.services.writing_policy.store import WritingPolicyStore\n"
                "save_config_payload({'servicePort': 19127})\n"
                "save_local_api_key('local-secret')\n"
                "save_route_api_key('word_smart_write', 'route-secret')\n"
                "WritingPolicyStore(default_database_path())\n"
                "paths = resolve_runtime_paths()\n"
                "print(json.dumps({\n"
                "  'port': load_settings().service_port,\n"
                "  'config': str(paths.config_path),\n"
                "  'local_key': str(paths.local_api_key_path),\n"
                "  'route_key': str(paths.api_key_dir / 'word_smart_write'),\n"
                "  'policy': str(paths.writing_policy_db_path),\n"
                "  'local_mode': stat.S_IMODE(paths.local_api_key_path.stat().st_mode),\n"
                "  'route_mode': stat.S_IMODE((paths.api_key_dir / 'word_smart_write').stat().st_mode),\n"
                "}))\n"
            )

            for shared_state_enabled in (False, True):
                with self.subTest(shared_state_enabled=shared_state_enabled):
                    state_dir = temp_root / "shared-state"
                    environment = dict(os.environ)
                    environment["PYTHONPATH"] = str(service_root)
                    for name in (
                        "AI_WPS_STATE_DIR",
                        "AI_WPS_BACKUP_DIR",
                        "AI_WPS_VAR_DIR",
                        "AI_WPS_WRITING_POLICY_DB",
                    ):
                        environment.pop(name, None)
                    if shared_state_enabled:
                        environment["AI_WPS_STATE_DIR"] = str(state_dir)

                    result = subprocess.run(
                        [os.sys.executable, "-c", probe],
                        cwd=str(service_root),
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout.splitlines()[-1])
                    expected_root = (
                        state_dir if shared_state_enabled else program_root.resolve()
                    )
                    expected_config = (
                        expected_root / "adapter.json"
                        if shared_state_enabled
                        else expected_root / "config/adapter.json"
                    )
                    expected_local_key = (
                        expected_root / "provider_api_key"
                        if shared_state_enabled
                        else expected_root / "run/provider_api_key"
                    )
                    expected_route_key = (
                        expected_root / "provider_api_keys/word_smart_write"
                        if shared_state_enabled
                        else expected_root / "run/provider_api_keys/word_smart_write"
                    )
                    expected_policy = (
                        expected_root / "writing_policies.db"
                        if shared_state_enabled
                        else expected_root / "run/writing_policies.db"
                    )
                    self.assertEqual(payload["port"], 19127)
                    self.assertEqual(Path(payload["config"]), expected_config)
                    self.assertEqual(Path(payload["local_key"]), expected_local_key)
                    self.assertEqual(Path(payload["route_key"]), expected_route_key)
                    self.assertEqual(Path(payload["policy"]), expected_policy)
                    self.assertEqual(payload["local_mode"], 0o600)
                    self.assertEqual(payload["route_mode"], 0o600)

    def test_shared_state_persists_configuration_model_key_and_policy_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                save_config_payload({"servicePort": 19127})
                store = ModelConfigurationStore()
                configuration = store.create_configuration(
                    "word.smart_write",
                    "共享状态模型",
                    "workflow_platform",
                    service_base_url="https://model.example/v1",
                )
                store.replace_api_key(configuration["id"], "model-secret")
                WritingPolicyStore(default_database_path())

            self.assertEqual(
                load_settings(state_dir / "adapter.json").service_port,
                19127,
            )
            key_path = state_dir / "provider_api_keys" / configuration["apiKeyRef"]
            self.assertEqual(key_path.read_text(encoding="utf-8").strip(), "model-secret")
            self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE((state_dir / "provider_api_keys").stat().st_mode),
                0o700,
            )
            policy_path = state_dir / "writing_policies.db"
            self.assertTrue(policy_path.is_file())
            self.assertEqual(stat.S_IMODE(policy_path.stat().st_mode), 0o600)

    @staticmethod
    def _write_fake_start_dependencies(bin_dir: Path, capture_path: Path) -> Path:
        bin_dir.mkdir(parents=True)
        python_path = bin_dir / "python3"
        python_path.write_text(
            "#!/usr/bin/env bash\n"
            "if [ \"${1:-}\" = \"-c\" ]; then exit 0; fi\n"
            "if [ \"${1:-}\" = \"-s\" ] && [ \"${2:-}\" = \"-c\" ]; then exit 0; fi\n"
            "printf '%s|%s|%s\\n' \"${AI_WPS_STATE_DIR:-}\" "
            "\"${AI_WPS_BACKUP_DIR:-}\" \"${AI_WPS_VAR_DIR:-}\" > \"$FAKE_CAPTURE\"\n"
            "trap 'exit 0' TERM INT\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        python_path.chmod(0o755)
        curl_path = bin_dir / "curl"
        curl_path.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' "
            "'{\"success\":true,\"data\":{\"mode\":\"uvicorn\","
            "\"version\":\"0.23.1-alpha\"}}'\n",
            encoding="utf-8",
        )
        curl_path.chmod(0o755)
        return python_path

    def test_start_script_keeps_mutable_files_outside_program_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "installation"
            program_root = install_root / "releases" / "0.23.1-alpha"
            shutil.copytree(ROOT / "adapter-start-kit", program_root)
            (program_root / "adapter_service").mkdir()
            capture_path = Path(temp_dir) / "captured-environment.txt"
            fake_bin = Path(temp_dir) / "bin"
            python_path = self._write_fake_start_dependencies(fake_bin, capture_path)
            state_dir = install_root / "state"
            environment = dict(os.environ)
            environment.update(
                {
                    "AI_WPS_STATE_DIR": str(state_dir),
                    "FAKE_CAPTURE": str(capture_path),
                    "PATH": str(fake_bin) + ":/usr/bin:/bin",
                    "PYTHON_BIN": str(python_path),
                }
            )
            environment.pop("AI_WPS_BACKUP_DIR", None)
            environment.pop("AI_WPS_VAR_DIR", None)

            try:
                result = subprocess.run(
                    [
                        "bash",
                        str(program_root / "scripts/start_uvicorn_adapter.sh"),
                        "65529",
                    ],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertTrue((install_root / "backups").is_dir())
                self.assertTrue((install_root / "var" / "logs" / "adapter.log").is_file())
                self.assertTrue((install_root / "var" / "run" / "adapter.pid").is_file())
                self.assertTrue((install_root / "var" / "transactions").is_dir())
                self.assertEqual(
                    capture_path.read_text(encoding="utf-8").strip(),
                    "|".join(
                        [
                            str(state_dir),
                            str(install_root / "backups"),
                            str(install_root / "var"),
                        ]
                    ),
                )
                program_logs = program_root / "logs"
                program_run = program_root / "run"
                self.assertFalse(
                    program_logs.exists() and any(program_logs.iterdir())
                )
                self.assertFalse(program_run.exists() and any(program_run.iterdir()))
            finally:
                subprocess.run(
                    ["bash", str(program_root / "scripts/stop_adapter.sh"), "65529"],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

    def test_start_script_preserves_legacy_runtime_directories_without_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            program_root = Path(temp_dir) / "adapter-start-kit"
            shutil.copytree(ROOT / "adapter-start-kit", program_root)
            (program_root / "adapter_service").mkdir()
            capture_path = Path(temp_dir) / "captured-environment.txt"
            fake_bin = Path(temp_dir) / "bin"
            python_path = self._write_fake_start_dependencies(fake_bin, capture_path)
            environment = {
                "FAKE_CAPTURE": str(capture_path),
                "PATH": str(fake_bin) + ":/usr/bin:/bin",
                "PYTHON_BIN": str(python_path),
            }

            try:
                result = subprocess.run(
                    [
                        "bash",
                        str(program_root / "scripts/start_uvicorn_adapter.sh"),
                        "65528",
                    ],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertTrue((program_root / "logs" / "adapter.log").is_file())
                self.assertTrue((program_root / "run" / "adapter.pid").is_file())
                self.assertTrue((program_root / "run" / "transactions").is_dir())
                self.assertEqual(
                    capture_path.read_text(encoding="utf-8").strip(),
                    "||",
                )
            finally:
                subprocess.run(
                    ["bash", str(program_root / "scripts/stop_adapter.sh"), "65528"],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

    def test_status_script_derives_pid_directory_from_explicit_shared_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "installation"
            program_root = install_root / "releases" / "0.23.1-alpha"
            shutil.copytree(ROOT / "adapter-start-kit", program_root)
            pid_path = install_root / "var" / "run" / "adapter.pid"
            pid_path.parent.mkdir(parents=True)
            pid_path.write_text("99999999\n", encoding="utf-8")
            environment = dict(os.environ)
            environment["AI_WPS_STATE_DIR"] = str(install_root / "state")
            environment.pop("AI_WPS_VAR_DIR", None)

            result = subprocess.run(
                ["bash", str(program_root / "scripts/status_adapter.sh"), "65530"],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("adapter_status=stale pid=99999999", result.stdout)

    def test_shared_state_layout_routes_application_log_to_var_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "installation"
            state_dir = install_root / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "adapter.json").write_text(
                '{"logPath": "./logs/adapter.log"}',
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                settings = load_settings()

            self.assertEqual(
                settings.log_path,
                str(install_root / "var" / "logs" / "adapter.log"),
            )

    def test_shared_state_key_files_keep_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                save_local_api_key("local-secret")
                save_route_api_key("word_smart_write", "task-secret")

            key_paths = (
                state_dir / "provider_api_key",
                state_dir / "provider_api_keys" / "word_smart_write",
            )
            for key_path in key_paths:
                self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)

    def test_key_file_is_private_even_when_final_permission_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "state" / "provider_api_key"
            real_chmod = os.chmod

            def fail_target_chmod(path, mode):
                if Path(path) == target:
                    raise OSError("simulated final chmod failure")
                real_chmod(path, mode)

            previous_umask = os.umask(0o022)
            try:
                with patch("app.services.provider_client.os.chmod", side_effect=fail_target_chmod):
                    with self.assertRaisesRegex(OSError, "simulated final chmod failure"):
                        save_local_api_key("local-secret", target)
            finally:
                os.umask(previous_umask)

            self.assertTrue(target.is_file())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_model_stores_follow_explicit_shared_state_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                model_store = ModelConfigurationStore()
                workflow_store = WorkflowProfileStore()

            for store in (model_store, workflow_store):
                self.assertEqual(store.config_path, state_dir / "adapter.json")
                self.assertEqual(store.key_dir, state_dir / "provider_api_keys")

    def test_key_and_writing_policy_defaults_follow_explicit_shared_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                local_key_path = get_local_api_key_path()
                task_key_path = get_route_api_key_path("word_smart_write")
                database_path = default_database_path()

            self.assertEqual(local_key_path, state_dir / "provider_api_key")
            self.assertEqual(
                task_key_path,
                state_dir / "provider_api_keys" / "word_smart_write",
            )
            self.assertEqual(database_path, state_dir / "writing_policies.db")

    def test_settings_are_loaded_from_explicit_shared_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            state_dir.mkdir()
            (state_dir / "adapter.json").write_text(
                '{"servicePort": 19127, "providerName": "共享状态配置"}',
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                settings = load_settings()

            self.assertEqual(settings.service_port, 19127)
            self.assertEqual(settings.provider_name, "共享状态配置")

    def test_explicit_state_directory_separates_state_backups_and_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "installation"
            program_root = install_root / "releases" / "0.23.1-alpha"
            state_dir = install_root / "state"

            with patch.dict(
                os.environ,
                {"AI_WPS_STATE_DIR": str(state_dir)},
                clear=True,
            ):
                paths = resolve_runtime_paths(program_root)

            self.assertEqual(paths.config_path, state_dir / "adapter.json")
            self.assertEqual(paths.local_api_key_path, state_dir / "provider_api_key")
            self.assertEqual(paths.api_key_dir, state_dir / "provider_api_keys")
            self.assertEqual(paths.writing_policy_db_path, state_dir / "writing_policies.db")
            self.assertEqual(paths.backup_dir, install_root / "backups")
            self.assertEqual(paths.log_dir, install_root / "var" / "logs")
            self.assertEqual(paths.pid_path, install_root / "var" / "run" / "adapter.pid")
            self.assertEqual(paths.transaction_dir, install_root / "var" / "transactions")
            self.assertTrue(paths.shared_state_enabled)

    def test_missing_path_configuration_preserves_legacy_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            program_root = Path(temp_dir) / "adapter-start-kit"

            with patch.dict(os.environ, {}, clear=True):
                paths = resolve_runtime_paths(program_root)

            self.assertEqual(paths.config_path, program_root / "config" / "adapter.json")
            self.assertEqual(paths.local_api_key_path, program_root / "run" / "provider_api_key")
            self.assertEqual(paths.api_key_dir, program_root / "run" / "provider_api_keys")
            self.assertEqual(paths.writing_policy_db_path, program_root / "run" / "writing_policies.db")
            self.assertEqual(paths.log_dir, program_root / "logs")
            self.assertEqual(paths.pid_path, program_root / "run" / "adapter.pid")
            self.assertEqual(paths.transaction_dir, program_root / "run" / "transactions")
            self.assertFalse(paths.shared_state_enabled)

    def test_runtime_path_environment_requires_absolute_paths(self) -> None:
        with patch.dict(
            os.environ,
            {"AI_WPS_STATE_DIR": "relative/state"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "AI_WPS_STATE_DIR.*absolute"):
                resolve_runtime_paths()

    def test_python_and_shell_reject_unicode_control_characters(self) -> None:
        invalid_path = "/tmp/ai-wps\u0085state"
        with patch.dict(
            os.environ,
            {"AI_WPS_STATE_DIR": invalid_path},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "control characters"):
                resolve_runtime_paths()

        environment = dict(os.environ)
        environment["AI_WPS_STATE_DIR"] = invalid_path
        result = subprocess.run(
            ["bash", str(ROOT / "adapter-start-kit/scripts/status_adapter.sh")],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("control_character_rejected", result.stderr)

    def test_shell_runtime_path_contract_rejects_relative_paths(self) -> None:
        environment = dict(os.environ)
        environment["AI_WPS_STATE_DIR"] = "relative/state"
        result = subprocess.run(
            ["bash", str(ROOT / "adapter-start-kit/scripts/status_adapter.sh")],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AI_WPS_STATE_DIR", result.stderr)
        self.assertIn("absolute_path_required", result.stderr)

    def test_systemd_unit_quotes_explicit_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "install with space%blue"
            unit_path = Path(temp_dir) / "ai-wps-adapter.service"
            environment = dict(os.environ)
            environment.update(
                {
                    "UNIT_HELPER": str(
                        ROOT / "adapter-start-kit/scripts/systemd_unit.sh"
                    ),
                    "UNIT_PATH": str(unit_path),
                    "KIT_ROOT": str(root / "current"),
                    "PYTHON_BIN": str(root / "python env/bin/python3"),
                    "PID_PATH": str(root / "var/run/adapter.pid"),
                    "AI_WPS_STATE_DIR": str(root / "state"),
                    "AI_WPS_BACKUP_DIR": str(root / "backups"),
                    "AI_WPS_VAR_DIR": str(root / "var"),
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$UNIT_HELPER"; '
                    'render_adapter_systemd_unit "$UNIT_PATH" "wps-user" '
                    '"$KIT_ROOT" "$PYTHON_BIN" "18100" "$PID_PATH" '
                    '"$AI_WPS_STATE_DIR" "$AI_WPS_BACKUP_DIR" "$AI_WPS_VAR_DIR"',
                ],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            unit = unit_path.read_text(encoding="utf-8")
            escaped_root = str(root).replace("%", "%%")
            self.assertIn(
                'Environment="AI_WPS_STATE_DIR={0}/state"'.format(escaped_root),
                unit,
            )
            self.assertIn(
                'WorkingDirectory="{0}/current"'.format(escaped_root),
                unit,
            )
            self.assertIn(
                'ExecStart=/bin/bash "{0}/current/scripts/start_adapter.sh" "18100"'.format(
                    escaped_root
                ),
                unit,
            )
            self.assertNotIn("Environment=AI_WPS_STATE_DIR=", unit)


if __name__ == "__main__":
    unittest.main()
