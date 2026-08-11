import importlib.util
import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.services.recovery import RecoveryOperationError, RecoveryOperations
from app.services.runtime_state import RuntimeStateError


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app.main import app


class _ReadyWritingPolicyStore:
    def summary(self):
        return {"status": "ready"}


class _ReadyWritingPolicyService:
    store = _ReadyWritingPolicyStore()


class RecoveryOperationServiceTests(unittest.TestCase):
    def test_service_keeps_recovery_backup_separate_from_restore_validity_and_redacts_diagnostics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            backup_dir = root / "backups"
            state_dir.mkdir()
            secret = "never-expose-recovery-key"
            (state_dir / "adapter.json").write_text(
                '{"modelConfigurations":{"broken":"' + secret,
                encoding="utf-8",
            )
            operations = RecoveryOperations(
                state_dir=state_dir,
                backup_dir=backup_dir,
                release_version="0.23.1-alpha",
            )

            with self.assertRaises(RecoveryOperationError) as ready_error:
                operations.create_read_only_backup(current_status="ready")
            self.assertEqual(ready_error.exception.code, "RECOVERY_MODE_REQUIRED")

            backup = operations.create_read_only_backup(current_status="recovery")
            diagnostics = operations.build_diagnostics(
                {
                    "service": "wps-ai-adapter",
                    "status": "recovery",
                    "version": "0.23.1-alpha",
                    "mode": "uvicorn",
                    "providerBaseUrl": "https://secret.example/v1",
                    "apiKey": secret,
                    "rawAnswer": "private model response",
                    "subsystems": {
                        "modelConfigurations": {
                            "status": "recovery",
                            "errorCode": "MODEL_CONFIGURATION_DATA_UNAVAILABLE",
                            "stage": "load_model_configurations",
                            "allowedActions": [
                                "retry",
                                "create_backup",
                                "export_diagnostics",
                            ],
                        }
                    },
                    "operationPolicy": {
                        "configurationMutationsAllowed": False,
                        "modelTasksAllowed": False,
                        "writingPolicyMutationsAllowed": False,
                    },
                }
            )

            self.assertEqual(backup["status"], "recovery")
            self.assertTrue(backup["copyVerified"])
            self.assertFalse(backup["valid"])
            self.assertGreaterEqual(diagnostics["backupStatus"]["verifiedCount"], 1)
            serialized = json.dumps(diagnostics, ensure_ascii=False)
            self.assertNotIn(secret, serialized)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("providerBaseUrl", serialized)
            self.assertNotIn("rawAnswer", serialized)

            with patch.object(
                operations.manager,
                "_verify_snapshot_files",
                side_effect=AssertionError("health status must not rehash snapshots"),
            ):
                status = operations.backup_status()
            self.assertGreaterEqual(status["verifiedCount"], 1)

            with patch.object(
                operations.manager,
                "create_snapshot",
                side_effect=RuntimeStateError("SNAPSHOT_COPY_UNSTABLE", "recovery"),
            ):
                with self.assertRaises(RecoveryOperationError) as backup_error:
                    operations.create_read_only_backup(current_status="recovery")
            self.assertEqual(backup_error.exception.code, "RECOVERY_BACKUP_FAILED")

            created = {
                "snapshotId": "snapshot-created-before-status-failure",
                "status": "recovery",
                "copyVerified": True,
                "valid": False,
            }
            with patch.object(
                operations.manager,
                "create_snapshot",
                return_value=created,
            ), patch.object(
                operations,
                "backup_status",
                side_effect=OSError("sensitive backup path"),
            ):
                partial = operations.create_read_only_backup(
                    current_status="recovery"
                )
            self.assertEqual(partial["snapshotId"], created["snapshotId"])
            self.assertTrue(partial["backupStatus"]["statusUnavailable"])
            self.assertEqual(
                partial["backupStatus"]["latestVerified"]["snapshotId"],
                created["snapshotId"],
            )


class RecoveryOperationStandaloneTests(unittest.TestCase):
    def test_standalone_exposes_only_backup_and_diagnostics_recovery_routes(
        self,
    ) -> None:
        import standalone_adapter

        class FakeOperations:
            def create_read_only_backup(self, current_status):
                return {
                    "snapshotId": "snapshot-standalone",
                    "status": current_status,
                    "copyVerified": True,
                    "valid": False,
                }

            def build_diagnostics(self, health_snapshot):
                return {
                    "status": health_snapshot["status"],
                    "backupStatus": {"verifiedCount": 1, "validCount": 0},
                }

        def call(method, path):
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            handler.headers = {"Content-Length": "2"}
            handler.rfile = BytesIO(b"{}")
            handler._write = lambda status, body: captured.update(
                status=status, body=body
            )
            getattr(handler, method)()
            return captured

        with patch.object(
            standalone_adapter,
            "get_health_snapshot",
            return_value={"status": "recovery"},
        ), patch.object(
            standalone_adapter,
            "get_recovery_operations",
            return_value=FakeOperations(),
        ):
            backup = call("do_POST", "/recovery/backups")
            diagnostics = call("do_GET", "/recovery/diagnostics")
            restore = call("do_POST", "/recovery/restore")

        self.assertEqual(backup["status"], 200)
        self.assertTrue(backup["body"]["data"]["copyVerified"])
        self.assertEqual(diagnostics["status"], 200)
        self.assertEqual(
            diagnostics["body"]["data"]["backupStatus"]["verifiedCount"], 1
        )
        self.assertEqual(restore["status"], 404)

        class FailingOperations(FakeOperations):
            def create_read_only_backup(self, current_status):
                raise RecoveryOperationError("RECOVERY_BACKUP_FAILED", "recovery")

        with patch.object(
            standalone_adapter,
            "get_health_snapshot",
            return_value={"status": "recovery"},
        ), patch.object(
            standalone_adapter,
            "get_recovery_operations",
            return_value=FailingOperations(),
        ):
            failed_backup = call("do_POST", "/recovery/backups")

        self.assertEqual(failed_backup["status"], 503)
        self.assertEqual(
            failed_backup["body"]["errors"][0]["code"],
            "RECOVERY_BACKUP_FAILED",
        )


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class RecoveryOperationApiTests(unittest.TestCase):
    def test_recovery_mode_creates_verified_backup_and_exports_only_redacted_diagnostics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            backup_dir = root / "backups"
            var_dir = root / "var"
            state_dir.mkdir()
            secret = "never-expose-recovery-key"
            config_path = state_dir / "adapter.json"
            config_path.write_text(
                '{"modelConfigurations":{"broken":"' + secret,
                encoding="utf-8",
            )
            environment = {
                "AI_WPS_STATE_DIR": str(state_dir),
                "AI_WPS_BACKUP_DIR": str(backup_dir),
                "AI_WPS_VAR_DIR": str(var_dir),
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "app.services.health.get_writing_policy_service",
                return_value=_ReadyWritingPolicyService(),
            ):
                client = TestClient(app)
                health_before = client.get("/health")
                backup_response = client.post("/recovery/backups", json={})
                diagnostics_response = client.get("/recovery/diagnostics")
                restore_response = client.post(
                    "/recovery/restore", json={"snapshotId": "implicit"}
                )

            self.assertEqual(health_before.status_code, 200)
            self.assertEqual(health_before.json()["data"]["status"], "recovery")
            self.assertEqual(
                health_before.json()["data"]["backupStatus"]["verifiedCount"],
                0,
            )
            self.assertEqual(
                backup_response.status_code,
                200,
                backup_response.text,
            )
            backup = backup_response.json()["data"]
            self.assertEqual(backup["status"], "recovery")
            self.assertTrue(backup["copyVerified"])
            self.assertFalse(backup["valid"])
            self.assertTrue(backup["snapshotId"].startswith("snapshot-"))

            self.assertEqual(diagnostics_response.status_code, 200)
            diagnostics = diagnostics_response.json()["data"]
            self.assertEqual(diagnostics["status"], "recovery")
            self.assertEqual(
                diagnostics["subsystems"]["modelConfigurations"]["stage"],
                "load_model_configurations",
            )
            self.assertGreaterEqual(diagnostics["backupStatus"]["verifiedCount"], 1)
            serialized = json.dumps(diagnostics, ensure_ascii=False)
            self.assertNotIn(secret, serialized)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("apiKey", serialized)
            self.assertNotIn("providerBaseUrl", serialized)
            self.assertNotIn("rawAnswer", serialized)

            self.assertEqual(restore_response.status_code, 404)
            audit = (backup_dir / "runtime-state-audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(secret, audit)
            self.assertNotIn(str(root), audit)


if __name__ == "__main__":
    unittest.main()
