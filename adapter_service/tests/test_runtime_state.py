import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.services.runtime_state as runtime_state_module
from app.services.runtime_state import RuntimeStateError, RuntimeStateManager
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS
from app.services.writing_policy.store import WritingPolicyStore


def _write_legacy_state(root: Path, secret_prefix: str = "secret") -> dict:
    config_dir = root / "config"
    run_dir = root / "run"
    key_dir = run_dir / "provider_api_keys"
    config_dir.mkdir(parents=True)
    key_dir.mkdir(parents=True)
    configurations = {}
    active = {}
    secrets = {}
    for index, task_type in enumerate(SUPPORTED_WORKFLOW_TASKS):
        configuration_id = "config-{0}".format(index)
        key_ref = "task-key-{0}".format(index)
        secret = "{0}-{1}".format(secret_prefix, index)
        configurations[configuration_id] = {
            "id": configuration_id,
            "taskType": task_type,
            "name": "配置 {0}".format(index),
            "accessMethod": "workflow_platform",
            "serviceBaseUrl": "https://model-{0}.example/v1".format(index),
            "apiKeyRef": key_ref,
        }
        active[task_type] = configuration_id
        (key_dir / key_ref).write_text(secret, encoding="utf-8")
        secrets[key_ref] = secret
    payload = {
        "modelConfigurations": configurations,
        "activeModelConfigurations": active,
        "taskApiKeyRefs": {
            task_type: "task-key-{0}".format(index)
            for index, task_type in enumerate(SUPPORTED_WORKFLOW_TASKS)
        },
        "taskRoutes": {
            task_type: {
                "path": "/chat-messages",
                "apiKeyRef": "task-key-{0}".format(index),
            }
            for index, task_type in enumerate(SUPPORTED_WORKFLOW_TASKS)
        },
    }
    (config_dir / "adapter.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    policy_store = WritingPolicyStore(run_dir / "writing_policies.db")
    policy_store.create_item(
        {
            "type": "term",
            "scope": "global",
            "category": "系统",
            "preferredText": "卫星互联网运营平台",
            "aliases": ["运营平台"],
            "forbiddenVariants": [],
            "definition": "统一名称",
            "contextKeywords": ["平台"],
            "priority": "high",
            "enabled": True,
            "note": "迁移测试",
        }
    )
    return secrets


class RuntimeStateManagerTests(unittest.TestCase):
    def test_snapshot_retries_when_source_changes_during_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            original_copy = manager._copy_state_once
            copy_count = 0

            def copy_with_one_concurrent_change(source, target, legacy_layout):
                nonlocal copy_count
                copy_count += 1
                original_copy(source, target, legacy_layout)
                if copy_count == 1:
                    config_path = legacy_root / "config/adapter.json"
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                    payload["modelConfigurations"]["config-0"][
                        "serviceBaseUrl"
                    ] = "https://changed.example/v1"
                    config_path.write_text(json.dumps(payload), encoding="utf-8")

            with mock.patch.object(
                manager, "_copy_state_once", side_effect=copy_with_one_concurrent_change
            ):
                result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "ready")
            self.assertGreaterEqual(copy_count, 2)
            migrated = json.loads((state_dir / "adapter.json").read_text())
            self.assertEqual(
                migrated["modelConfigurations"]["config-0"]["serviceBaseUrl"],
                "https://changed.example/v1",
            )

    def test_snapshot_signature_tracks_sqlite_wal_and_shared_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            manager.migrate_legacy_state(legacy_root)
            database = state_dir / "writing_policies.db"

            with sqlite3.connect(str(database)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "UPDATE schema_metadata SET value = '01' "
                    "WHERE key = 'schema_version'"
                )
                connection.commit()
                signature = manager._state_signature(state_dir, legacy_layout=False)

            names = {item[0] for item in signature}
            self.assertIn("writing_policies.db-wal", names)
            self.assertIn("writing_policies.db-shm", names)

    def test_policy_only_legacy_state_does_not_import_example_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            policy_path = legacy_root / "run/writing_policies.db"
            WritingPolicyStore(policy_path)
            state_dir = root / "state"
            manager = RuntimeStateManager(
                state_dir, root / "backups", "0.23.1-alpha"
            )

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "ready")
            payload = json.loads(
                (state_dir / "adapter.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["modelConfigurations"], {})
            self.assertNotIn("taskApiKeyRefs", payload)

    def test_snapshot_ignores_deleted_legacy_workflow_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            state_dir.mkdir()
            (state_dir / "adapter.json").write_text(
                json.dumps(
                    {
                        "providerBaseUrl": "https://workflow.example/v1",
                        "workflowProfiles": {
                            "legacy-deleted-workflow": {
                                "id": "legacy-deleted-workflow",
                                "taskType": "word.smart_write",
                                "apiKeyRef": "deleted-workflow-key",
                            }
                        },
                        "activeWorkflowProfiles": {
                            "word.smart_write": "legacy-deleted-workflow"
                        },
                        "modelConfigurations": {},
                        "activeModelConfigurations": {},
                        "migrationState": {
                            "workflowProfilesImported": True,
                            "workflowProfilesVersion": 1,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            WritingPolicyStore(state_dir / "writing_policies.db")
            manager = RuntimeStateManager(
                state_dir, root / "backups", "0.25.1-alpha"
            )

            result = manager.create_snapshot("pre_install")

            self.assertEqual(result["status"], "ready")
            manifest = json.loads(
                (
                    root / "backups" / result["snapshotId"] / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["inventory"]["modelConfigurations"]["totalCount"], 0
            )
            self.assertEqual(manifest["inventory"]["activeRelationships"], [])

    def test_delivery_contract_installs_shared_state_operator_workflow(self) -> None:
        root = Path(__file__).resolve().parents[2]
        installer = (root / "phase1-delivery-kit/installer/install_phase1.sh").read_text(
            encoding="utf-8"
        )
        build_script = (root / "packaging/build_phase1_delivery_kit.sh").read_text(
            encoding="utf-8"
        )
        manifest = json.loads(
            (root / "phase1-delivery-kit/release-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        operator_script = (
            root / "adapter-start-kit/scripts/runtime_state.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('STATE_DIR="${AI_WPS_STATE_DIR:-$INSTALL_ROOT/state}"', installer)
        self.assertIn('BACKUP_DIR="${AI_WPS_BACKUP_DIR:-$INSTALL_ROOT/backups}"', installer)
        self.assertTrue(
            '$RUNTIME_STATE_TOOL" migrate' in installer
            or '$candidate_state_tool" migrate' in installer
        )
        self.assertTrue(
            '$RUNTIME_STATE_TOOL" snapshot' in installer
            or '$candidate_state_tool" snapshot' in installer
        )
        self.assertIn("runtime_state_snapshot_reason=pre_install", installer)
        self.assertIn("runtime_state_migration_status=degraded", installer)
        self.assertIn('export AI_WPS_STATE_DIR="$STATE_DIR"', installer)
        self.assertIn(
            'database_root="${2:-${STATE_DIR:-$ADAPTER_TARGET/run}}"',
            installer,
        )
        self.assertIn(
            '--component runtime_state_snapshot "$CANDIDATE_STATE" "$STATE_DIR"',
            installer,
        )
        source_policy = json.loads(
            (root / "packaging/delivery-sources-v0231.json").read_text(
                encoding="utf-8"
            )
        )
        delivered_files = {
            entry["target"].rstrip("/") + "/" + relative
            for entry in source_policy["entries"]
            if entry["type"] in {"tree", "archive"}
            for relative in entry["include"]
        }
        self.assertIn(
            "docs/operations/runtime-state-recovery.md",
            delivered_files,
        )
        self.assertIn("assemble_phase1_delivery.py", build_script)
        self.assertIn("RESTORE_WHOLE_STATE", operator_script)
        policy = manifest["runtimeStatePolicy"]
        self.assertEqual(policy["snapshotManifestSchemaVersion"], 1)
        self.assertEqual(policy["minimumValidSnapshots"], 3)
        self.assertTrue(policy["wholeStateRestoreOnly"])

    def test_cli_creates_pre_install_snapshot_without_exposing_state_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            backup_dir = root / "backups"
            legacy_root = root / "legacy"
            secrets = _write_legacy_state(legacy_root)
            RuntimeStateManager(
                state_dir, backup_dir, "0.23.1-alpha"
            ).migrate_legacy_state(legacy_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "tools/runtime_state.py"),
                    "snapshot",
                    "--state-dir",
                    str(state_dir),
                    "--backup-dir",
                    str(backup_dir),
                    "--release-version",
                    "0.23.1-alpha",
                    "--reason",
                    "pre_install",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ready")
            for secret in secrets.values():
                self.assertNotIn(secret, result.stdout + result.stderr)

    def test_migrate_legacy_state_verifies_all_tasks_and_redacts_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            secrets = _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(
                state_dir=state_dir,
                backup_dir=backup_dir,
                release_version="0.23.1-alpha",
            )

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["taskCount"], len(SUPPORTED_WORKFLOW_TASKS))
            migrated = json.loads(
                (state_dir / "adapter.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(migrated["activeModelConfigurations"]),
                set(SUPPORTED_WORKFLOW_TASKS),
            )
            for ref, secret in secrets.items():
                key_path = state_dir / "provider_api_keys" / ref
                self.assertEqual(key_path.read_text(encoding="utf-8"), secret)
                self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)

            snapshot_dir = backup_dir / result["snapshotId"]
            manifest_text = (snapshot_dir / "manifest.json").read_text(
                encoding="utf-8"
            )
            manifest = json.loads(manifest_text)
            self.assertTrue(manifest["valid"])
            self.assertEqual(
                manifest["inventory"]["modelConfigurations"]["taskCount"],
                len(SUPPORTED_WORKFLOW_TASKS),
            )
            self.assertEqual(
                manifest["inventory"]["writingPolicies"]["totalCount"], 1
            )
            self.assertEqual(
                manifest["inventory"]["writingPolicies"]["enabledCount"], 1
            )
            self.assertEqual(stat.S_IMODE(backup_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(snapshot_dir.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((snapshot_dir / "manifest.json").stat().st_mode),
                0o600,
            )
            for secret in secrets.values():
                self.assertNotIn(secret, manifest_text)
            fingerprints = {
                item["ref"]: item["sha256"]
                for item in manifest["inventory"]["apiKeys"]
            }
            self.assertEqual(
                fingerprints["task-key-0"],
                hashlib.sha256(secrets["task-key-0"].encode("utf-8")).hexdigest(),
            )

    def test_core_migration_failure_preserves_existing_state_and_reports_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            config_path = legacy_root / "config/adapter.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["activeModelConfigurations"]["word.smart_write"] = "missing"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            state_dir.mkdir()
            (state_dir / "sentinel").write_text("unchanged", encoding="utf-8")
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")

            with self.assertRaises(RuntimeStateError) as raised:
                manager.migrate_legacy_state(legacy_root)

            self.assertEqual(raised.exception.status, "recovery")
            self.assertEqual(raised.exception.code, "CORE_STATE_INVALID")
            self.assertEqual(
                (state_dir / "sentinel").read_text(encoding="utf-8"),
                "unchanged",
            )
            manifests = list(backup_dir.glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text())
            self.assertTrue(manifest["copyVerified"])
            self.assertFalse(manifest["valid"])
            with self.assertRaises(RuntimeStateError) as restore_error:
                manager.restore_snapshot(manifest["snapshotId"], confirmed=True)
            self.assertEqual(restore_error.exception.code, "SNAPSHOT_NOT_VALID")

    def test_writing_policy_failure_preserves_database_and_reports_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            corrupt = b"not-a-sqlite-database\x00policy-data"
            (legacy_root / "run/writing_policies.db").write_bytes(corrupt)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["errorCode"], "WRITING_POLICY_STATE_INVALID")
            self.assertEqual((state_dir / "writing_policies.db").read_bytes(), corrupt)
            self.assertTrue((state_dir / "adapter.json").is_file())
            self.assertEqual(
                (legacy_root / "run/writing_policies.db").read_bytes(), corrupt
            )

    def test_writing_policy_schema_mismatch_reports_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            database = legacy_root / "run/writing_policies.db"
            with sqlite3.connect(str(database)) as connection:
                connection.executescript(
                    """
                    ALTER TABLE writing_policy_terms RENAME TO old_terms;
                    CREATE TABLE writing_policy_terms (
                        id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL
                    );
                    DROP TABLE old_terms;
                    """
                )
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["errorCode"], "WRITING_POLICY_STATE_INVALID")

    def test_writing_policy_missing_auxiliary_table_reports_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            database = legacy_root / "run/writing_policies.db"
            with sqlite3.connect(str(database)) as connection:
                connection.execute("DROP TABLE writing_policy_imports")
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["errorCode"], "WRITING_POLICY_STATE_INVALID")

    def test_writing_policy_wrong_index_columns_report_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            database = legacy_root / "run/writing_policies.db"
            with sqlite3.connect(str(database)) as connection:
                connection.executescript(
                    """
                    DROP INDEX idx_writing_policy_terms_preferred_normalized;
                    CREATE UNIQUE INDEX idx_writing_policy_terms_preferred_normalized
                        ON writing_policy_terms(category);
                    """
                )
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")

            result = manager.migrate_legacy_state(legacy_root)

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["errorCode"], "WRITING_POLICY_STATE_INVALID")

    def test_snapshot_retention_keeps_three_valid_and_last_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            backup_dir = root / "backups"
            legacy_root = root / "legacy"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            manager.migrate_legacy_state(legacy_root)
            protected_id = manager.create_snapshot(
                "accepted_release", protect_last_accepted=True
            )["snapshotId"]
            for index in range(5):
                manager.create_snapshot("install-{0}".format(index))

            snapshot_ids = {
                path.name
                for path in backup_dir.iterdir()
                if path.is_dir() and (path / "manifest.json").is_file()
            }
            self.assertIn(protected_id, snapshot_ids)
            unprotected = []
            for snapshot_id in snapshot_ids:
                manifest = json.loads(
                    (backup_dir / snapshot_id / "manifest.json").read_text()
                )
                if not manifest["retention"]["lastAcceptedVersion"]:
                    unprotected.append(snapshot_id)
            self.assertEqual(len(unprotected), 3)
            audit_entries = [
                json.loads(line)
                for line in (backup_dir / "runtime-state-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertTrue(
                any(entry["action"] == "prune" for entry in audit_entries)
            )

    def test_snapshot_prune_is_skipped_when_intent_audit_cannot_be_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            backup_dir = root / "backups"
            legacy_root = root / "legacy"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            manager.migrate_legacy_state(legacy_root)
            manager.create_snapshot("stable-one")
            manager.create_snapshot("stable-two")

            with mock.patch.object(manager, "_append_audit", return_value=False):
                manager.create_snapshot("must-not-prune")

            snapshots = [
                path
                for path in backup_dir.iterdir()
                if path.is_dir() and (path / "manifest.json").is_file()
            ]
            self.assertEqual(len(snapshots), 4)

    def test_restore_requires_confirmation_and_switches_the_whole_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root, secret_prefix="old-secret")
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            migration = manager.migrate_legacy_state(legacy_root)
            snapshot_id = migration["snapshotId"]
            (state_dir / "provider_api_keys/task-key-0").write_text(
                "new-secret", encoding="utf-8"
            )
            (state_dir / "extra-file").write_text("must-disappear", encoding="utf-8")
            manager.create_snapshot("newer-state-one")
            manager.create_snapshot("newer-state-two")

            with self.assertRaises(RuntimeStateError) as raised:
                manager.restore_snapshot(snapshot_id, confirmed=False)
            self.assertEqual(raised.exception.code, "RESTORE_CONFIRMATION_REQUIRED")
            audit_entries = [
                json.loads(line)
                for line in (backup_dir / "runtime-state-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(audit_entries[-1]["action"], "restore")
            self.assertEqual(audit_entries[-1]["status"], "blocked")

            result = manager.restore_snapshot(snapshot_id, confirmed=True)

            self.assertEqual(result["status"], "ready")
            self.assertEqual(
                (state_dir / "provider_api_keys/task-key-0").read_text(encoding="utf-8"),
                "old-secret-0",
            )
            self.assertFalse((state_dir / "extra-file").exists())
            self.assertTrue(result["preRestoreSnapshotId"])
            audit_entries = [
                json.loads(line)
                for line in (backup_dir / "runtime-state-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [item["status"] for item in audit_entries[-2:]],
                ["pending", "ready"],
            )

    def test_restore_aborts_before_switch_when_audit_intent_cannot_be_persisted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            snapshot_id = manager.migrate_legacy_state(legacy_root)["snapshotId"]
            sentinel = state_dir / "sentinel"
            sentinel.write_text("original", encoding="utf-8")

            with mock.patch.object(manager, "_append_audit", return_value=False):
                with self.assertRaises(RuntimeStateError) as raised:
                    manager.restore_snapshot(snapshot_id, confirmed=True)

            self.assertEqual(raised.exception.code, "RESTORE_AUDIT_FAILED")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")

    def test_restore_switch_failure_keeps_original_state_and_audits_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            snapshot_id = manager.migrate_legacy_state(legacy_root)["snapshotId"]
            sentinel = state_dir / "sentinel"
            sentinel.write_text("original", encoding="utf-8")

            with mock.patch.object(
                runtime_state_module,
                "_exchange_directories",
                side_effect=OSError("exchange unavailable"),
            ):
                with self.assertRaises(RuntimeStateError) as raised:
                    manager.restore_snapshot(snapshot_id, confirmed=True)

            self.assertEqual(raised.exception.status, "recovery")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")
            audit_entries = [
                json.loads(line)
                for line in (backup_dir / "runtime-state-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(audit_entries[-1]["action"], "restore")
            self.assertEqual(audit_entries[-1]["status"], "recovery")

    def test_restore_stage_creation_failure_is_sanitized_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy"
            state_dir = root / "state"
            backup_dir = root / "backups"
            _write_legacy_state(legacy_root)
            manager = RuntimeStateManager(state_dir, backup_dir, "0.23.1-alpha")
            snapshot_id = manager.migrate_legacy_state(legacy_root)["snapshotId"]

            with mock.patch.object(
                manager,
                "_new_stage",
                side_effect=OSError("sensitive local path"),
            ):
                with self.assertRaises(RuntimeStateError) as raised:
                    manager.restore_snapshot(snapshot_id, confirmed=True)

            self.assertEqual(raised.exception.code, "RESTORE_FAILED")
            audit_entries = [
                json.loads(line)
                for line in (backup_dir / "runtime-state-audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(audit_entries[-1]["action"], "restore")
            self.assertEqual(audit_entries[-1]["status"], "recovery")
            self.assertNotIn("sensitive local path", json.dumps(audit_entries))


if __name__ == "__main__":
    unittest.main()
