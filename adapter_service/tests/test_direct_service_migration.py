import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.config import load_config_payload
from app.core.errors import AdapterError
from app.core import direct_migration_txn as migration_txn
from app.services.direct_services import DirectServiceError, DirectServiceStore
from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationError,
    ModelConfigurationStore,
    WorkflowProfileCompatibilityStore,
)
from app.services.provider_client import ProviderClient
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


class DirectServiceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "adapter.json"
        self.key_dir = self.root / "provider_api_keys"
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.store = DirectServiceStore(self.config_path, self.key_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _seed_legacy_config(
        self,
        config_id: str,
        task_type: str,
        key_ref: str,
        api_key_content: str,
        name: str = "旧直连配置",
        service_base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-4o",
        temperature: float = 0.7,
        max_output_tokens: int = 2048,
        context_window_tokens: int = 32000,
        image_input_mode: str = "disabled",
        active: bool = False,
    ) -> None:
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        configurations = payload.setdefault("modelConfigurations", {})
        configurations[config_id] = {
            "id": config_id,
            "taskType": task_type,
            "name": name,
            "accessMethod": ACCESS_DIRECT_MODEL,
            "serviceBaseUrl": service_base_url,
            "apiKeyRef": key_ref,
            "modelName": model_name,
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "contextWindowTokens": context_window_tokens,
            "imageInputMode": image_input_mode,
        }
        if api_key_content:
            (self.key_dir / key_ref).write_text(api_key_content, encoding="utf-8")
        if active:
            active_map = payload.setdefault("activeModelConfigurations", {})
            active_map[task_type] = config_id
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _production_direct_service_keys(self):
        return sorted(self.key_dir.glob("direct_service_direct_svc_*"))

    def test_migration_not_needed_when_no_legacy_direct_configurations(self):
        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "not_needed")
        self.assertEqual(result["legacyDirectMigration"]["migratedConfigurationCount"], 0)
        self.assertEqual(result["directServiceCount"], 0)

    def test_merge_identical_url_and_key_across_multiple_tasks(self):
        # 3 tasks across Word, Excel, PPT with identical URL and Key
        self._seed_legacy_config(
            "legacy_word_write",
            "word.smart_write",
            "key_ref_word",
            "sk-shared-key-12345",
            name="公司大模型编写",
            service_base_url="https://llm.company.com/v1/",
            model_name="glm-5.2",
            temperature=0.2,
            active=True,
        )
        self._seed_legacy_config(
            "legacy_excel_analysis",
            "excel.analysis",
            "key_ref_excel",
            "sk-shared-key-12345",  # identical key
            name="公司大模型分析",
            service_base_url="https://llm.company.com/v1",  # same normalized URL
            model_name="glm-5.2",
            temperature=0.0,
            active=True,
        )
        self._seed_legacy_config(
            "legacy_ppt_summary",
            "ppt.slide_assistant",
            "key_ref_ppt",
            "sk-shared-key-12345",  # identical key
            name="公司大模型总结",
            service_base_url="https://llm.company.com/v1",  # same normalized URL
            model_name="glm-5.2",
            temperature=0.5,
            active=False,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        self.assertEqual(result["legacyDirectMigration"]["migratedConfigurationCount"], 3)
        self.assertEqual(result["directServiceCount"], 1)

        service = result["directServices"][0]
        self.assertEqual(service["serviceBaseUrl"], "https://llm.company.com/v1")
        self.assertEqual(service["defaultModel"], "glm-5.2")

        # Check task model selections
        word_sel = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(word_sel["serviceId"], service["id"])
        self.assertEqual(word_sel["temperature"], 0.2)
        self.assertEqual(word_sel["modelName"], "glm-5.2")

        excel_sel = self.store.get_task_model_selection("excel.analysis")
        self.assertEqual(excel_sel["serviceId"], service["id"])
        self.assertEqual(excel_sel["temperature"], 0.0)

        ppt_sel = self.store.get_task_model_selection("ppt.slide_assistant")
        self.assertEqual(ppt_sel["serviceId"], service["id"])
        self.assertEqual(ppt_sel["temperature"], 0.5)

        # Check activation
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        active = payload.get("activeModelConfigurations", {})
        self.assertEqual(active.get("word.smart_write"), service["id"])
        self.assertEqual(active.get("excel.analysis"), service["id"])
        # PPT was not active, so should not be in activeModelConfigurations
        self.assertNotIn("ppt.slide_assistant", active)

        # Legacy configs removed
        self.assertEqual(len(payload.get("modelConfigurations", {})), 0)

        # Duplicate legacy keys cleaned up, new service key exists
        self.assertFalse((self.key_dir / "key_ref_word").exists())
        self.assertFalse((self.key_dir / "key_ref_excel").exists())
        self.assertFalse((self.key_dir / "key_ref_ppt").exists())
        self.assertEqual(self.store._read_key(service["id"]), "sk-shared-key-12345")

    def test_separate_services_when_urls_or_keys_differ(self):
        # Different URL, same Key
        self._seed_legacy_config(
            "legacy_1",
            "word.smart_write",
            "key_1",
            "sk-secret",
            service_base_url="https://url-a.example.com/v1",
        )
        self._seed_legacy_config(
            "legacy_2",
            "word.smart_imitation",
            "key_2",
            "sk-secret",
            service_base_url="https://url-b.example.com/v1",
        )
        # Same URL, different Key
        self._seed_legacy_config(
            "legacy_3",
            "excel.formula_assistant",
            "key_3",
            "sk-other-secret",
            service_base_url="https://url-a.example.com/v1",
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        self.assertEqual(result["legacyDirectMigration"]["migratedConfigurationCount"], 3)
        # 3 distinct groups: (url-a, sk-secret), (url-b, sk-secret), (url-a, sk-other-secret)
        self.assertEqual(result["directServiceCount"], 3)

    def test_differing_models_in_same_group_leaves_default_model_empty(self):
        self._seed_legacy_config(
            "legacy_write",
            "word.smart_write",
            "key_shared",
            "sk-same-key",
            model_name="deepseek-v4-flash",
            service_base_url="https://model.example.com/v1",
            active=True,
        )
        self._seed_legacy_config(
            "legacy_imitation",
            "word.smart_imitation",
            "key_shared",
            "sk-same-key",
            model_name="glm-5.2",
            service_base_url="https://model.example.com/v1",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        self.assertEqual(result["directServiceCount"], 1)

        service = result["directServices"][0]
        # Merged model inconsistent -> defaultModel empty, for admin selection
        self.assertEqual(service["defaultModel"], "")

        # But each task preserves its specific model
        write_sel = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(write_sel["modelName"], "deepseek-v4-flash")

        imitation_sel = self.store.get_task_model_selection("word.smart_imitation")
        self.assertEqual(imitation_sel["modelName"], "glm-5.2")

    def test_incomplete_configuration_migrated_as_draft_without_activation(self):
        # Missing modelName
        self._seed_legacy_config(
            "legacy_incomplete",
            "word.document_review",
            "key_incomplete",
            "sk-key",
            model_name="",
            active=True,
        )
        # Invalid budget: maxOutputTokens >= contextWindowTokens
        self._seed_legacy_config(
            "legacy_bad_budget",
            "excel.smart_fill",
            "key_bad_budget",
            "sk-key",
            model_name="valid-model",
            max_output_tokens=4000,
            context_window_tokens=4000,
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        active = payload.get("activeModelConfigurations", {})
        self.assertNotIn("word.document_review", active)
        self.assertNotIn("excel.smart_fill", active)

        # Selections still preserved as draft
        doc_sel = self.store.get_task_model_selection("word.document_review")
        self.assertEqual(doc_sel["modelName"], "")
        fill_sel = self.store.get_task_model_selection("excel.smart_fill")
        self.assertEqual(fill_sel["maxOutputTokens"], 4000)

    def test_exceeding_five_services_triggers_restricted_mode_without_data_loss(self):
        # 6 different URLs
        for index in range(6):
            self._seed_legacy_config(
                f"legacy_{index}",
                SUPPORTED_WORKFLOW_TASKS[index % len(SUPPORTED_WORKFLOW_TASKS)],
                f"key_{index}",
                f"sk-secret-{index}",
                service_base_url=f"https://service-{index}.example.com/v1",
                active=True,
            )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "restricted")
        self.assertEqual(result["legacyDirectMigration"]["code"], "DIRECT_SERVICE_MIGRATION_LIMIT")
        self.assertEqual(result["legacyDirectMigration"]["requiredServiceCount"], 6)
        self.assertEqual(result["directServiceCount"], 0)

        # Original data untouched
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload.get("modelConfigurations", {})), 6)
        for index in range(6):
            self.assertTrue((self.key_dir / f"key_{index}").exists())

    def test_atomic_rollback_on_save_failure_cleans_up_new_keys(self):
        self._seed_legacy_config(
            "legacy_rollback",
            "word.smart_write",
            "key_rollback",
            "sk-rollback-test",
            active=True,
        )

        real_write = migration_txn.write_json_atomic

        def fail_config_write(path, payload):
            if Path(path) == self.config_path:
                raise IOError("disk full")
            return real_write(path, payload)

        with patch(
            "app.services.direct_services.migration_txn.write_json_atomic",
            side_effect=fail_config_write,
        ):
            with self.assertRaises(IOError):
                self.store.list_services()

        # Check that original payload was restored and no orphaned direct service keys remain
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_rollback", payload.get("modelConfigurations", {}))
        self.assertEqual(payload["activeModelConfigurations"]["word.smart_write"], "legacy_rollback")
        self.assertTrue((self.key_dir / "key_rollback").exists())

        self.assertEqual(self._production_direct_service_keys(), [])

    def test_migrated_active_task_can_resolve_auth_without_catalog(self):
        self._seed_legacy_config(
            "legacy_active_write",
            "word.smart_write",
            "key_active_write",
            "sk-live-key",
            model_name="glm-5.2",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        selection = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(selection["modelName"], "glm-5.2")
        self.assertEqual(selection["modelAvailability"], "available")
        self.assertTrue(selection["modelAvailable"])

        client = ProviderClient(direct_service_store=self.store)
        auth = client.resolve_task_auth("word.smart_write")
        self.assertEqual(auth["modelName"], "glm-5.2")
        self.assertEqual(auth["apiKey"], "sk-live-key")
        self.assertEqual(auth["accessMethod"], ACCESS_DIRECT_MODEL)

    def test_incomplete_url_without_key_kept_as_inactive_draft(self):
        self._seed_legacy_config(
            "legacy_url_only",
            "word.smart_write",
            "key_url_only",
            "",
            service_base_url="https://draft.example.com/v1",
            model_name="glm-5.2",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        service = result["directServices"][0]
        self.assertEqual(service["serviceBaseUrl"], "https://draft.example.com/v1")
        self.assertFalse(service["keyConfigured"])
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("word.smart_write", payload.get("activeModelConfigurations", {}))

    def test_incomplete_key_without_url_kept_as_inactive_draft(self):
        self._seed_legacy_config(
            "legacy_key_only",
            "excel.analysis",
            "key_only",
            "sk-draft-key",
            service_base_url="",
            model_name="glm-5.2",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        service = result["directServices"][0]
        self.assertEqual(service["serviceBaseUrl"], "")
        self.assertTrue(service["keyConfigured"])
        self.assertEqual(self.store._read_key(service["id"]), "sk-draft-key")
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("excel.analysis", payload.get("activeModelConfigurations", {}))

    def test_unconsumed_profiles_for_same_task_are_held_for_manual_processing(self):
        self._seed_legacy_config(
            "legacy_write_a",
            "word.smart_write",
            "key_write_a",
            "sk-profile-a",
            name="档案 A",
            model_name="glm-5.2",
            temperature=0.1,
            active=False,
        )
        self._seed_legacy_config(
            "legacy_write_b",
            "word.smart_write",
            "key_write_b",
            "sk-profile-b",
            name="档案 B",
            service_base_url="https://other.example.com/v1",
            model_name="deepseek-v4-flash",
            temperature=0.9,
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "pending_manual")
        self.assertEqual(
            result["legacyDirectMigration"]["code"],
            "DIRECT_SERVICE_MIGRATION_PENDING_PROFILES",
        )
        selection = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(selection["modelName"], "deepseek-v4-flash")
        self.assertEqual(selection["temperature"], 0.9)

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        pending = payload.get("legacyDirectPending", {})
        self.assertIn("legacy_write_a", pending)
        self.assertNotIn("legacy_write_a", payload.get("modelConfigurations", {}))
        self.assertNotIn("legacy_write_b", payload.get("modelConfigurations", {}))
        self.assertTrue((self.key_dir / "key_write_a").exists())
        self.assertFalse((self.key_dir / "key_write_b").exists())

        again = self.store.list_services()
        self.assertEqual(again["legacyDirectMigration"]["status"], "pending_manual")
        self.assertIn("legacy_write_a", json.loads(self.config_path.read_text(encoding="utf-8")).get("legacyDirectPending", {}))

    def test_reused_existing_service_clears_default_model_on_conflict(self):
        existing = self.store.create_service(
            name="已有共享服务",
            service_base_url="https://shared.example.com/v1",
            default_model="alpha-model",
            api_key="sk-shared",
        )
        self._seed_legacy_config(
            "legacy_beta",
            "word.smart_write",
            "key_beta",
            "sk-shared",
            service_base_url="https://shared.example.com/v1",
            model_name="beta-model",
            active=True,
        )
        self._seed_legacy_config(
            "legacy_gamma",
            "excel.analysis",
            "key_gamma",
            "sk-shared",
            service_base_url="https://shared.example.com/v1",
            model_name="gamma-model",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        self.assertEqual(result["directServiceCount"], 1)
        service = result["directServices"][0]
        self.assertEqual(service["id"], existing["id"])
        self.assertEqual(service["defaultModel"], "")

    def test_hostname_case_and_default_port_do_not_split_services(self):
        self._seed_legacy_config(
            "legacy_upper",
            "word.smart_write",
            "key_upper",
            "sk-same",
            service_base_url="https://API.Example.com:443/v1",
            active=True,
        )
        self._seed_legacy_config(
            "legacy_lower",
            "excel.analysis",
            "key_lower",
            "sk-same",
            service_base_url="https://api.example.com/v1",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        self.assertEqual(result["directServiceCount"], 1)
        self.assertEqual(result["directServices"][0]["serviceBaseUrl"], "https://api.example.com/v1")

    def test_atomic_rollback_after_config_write_restores_original(self):
        self._seed_legacy_config(
            "legacy_after_write",
            "word.smart_write",
            "key_after_write",
            "sk-after-write",
            active=True,
        )
        original = self.config_path.read_text(encoding="utf-8")
        real_save = migration_txn.write_json_atomic

        def save_then_fail(path, payload):
            real_save(path, payload)
            if Path(path) == self.config_path:
                raise DirectServiceError("DIRECT_SERVICE_MIGRATION_FAILED", "injected verify failure")

        with patch(
            "app.services.direct_services.migration_txn.write_json_atomic",
            side_effect=save_then_fail,
        ):
            with self.assertRaises(DirectServiceError):
                self.store.list_services()

        self.assertEqual(
            json.loads(self.config_path.read_text(encoding="utf-8")),
            json.loads(original),
        )
        self.assertTrue((self.key_dir / "key_after_write").exists())
        self.assertEqual(self._production_direct_service_keys(), [])

    def test_systemexit_during_commit_leaves_original_config_and_keys(self):
        self._seed_legacy_config(
            "legacy_sysexit",
            "word.smart_write",
            "key_sysexit",
            "sk-sysexit",
            active=True,
        )
        original = self.config_path.read_text(encoding="utf-8")

        real_write = migration_txn.write_json_atomic

        def exit_on_config(path, payload):
            if Path(path) == self.config_path:
                raise SystemExit(1)
            return real_write(path, payload)

        with patch(
            "app.services.direct_services.migration_txn.write_json_atomic",
            side_effect=exit_on_config,
        ):
            with self.assertRaises(SystemExit):
                self.store.list_services()

        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original)
        self.assertTrue((self.key_dir / "key_sysexit").exists())
        self.assertEqual(self._production_direct_service_keys(), [])

    def test_truncated_config_is_restored_from_pre_migration_backup(self):
        self._seed_legacy_config(
            "legacy_recover",
            "word.smart_write",
            "key_recover",
            "sk-recover",
            active=True,
        )
        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        backup = Path(str(self.config_path) + ".pre-direct-migration")
        self.assertTrue(backup.is_file())
        self.config_path.write_text("{", encoding="utf-8")

        recovered = self.store.list_services()
        self.assertIn(recovered["legacyDirectMigration"]["status"], ("completed", "not_needed"))
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertTrue(payload.get("directServices") or payload.get("modelConfigurations"))
        recovery_record = self.config_path.with_name("adapter-direct-migration-recovery.json")
        self.assertTrue(recovery_record.is_file())

    def test_legacy_direct_write_contract_is_retired(self):
        model_store = ModelConfigurationStore(self.config_path, self.key_dir)

        # Attempting to create direct_model via ModelConfigurationStore must raise retired error
        with self.assertRaises(ModelConfigurationError) as cm:
            model_store.create_configuration(
                "word.smart_write",
                "尝试旧直连创建",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://legacy.example.com/v1",
                model_name="legacy-model",
            )
        self.assertEqual(cm.exception.code, "MODEL_CONFIG_DIRECT_WRITE_RETIRED")

        # Workflow platform creation still works normally
        wf = model_store.create_configuration(
            "word.smart_write",
            "工作流编写配置",
            ACCESS_WORKFLOW_PLATFORM,
            service_base_url="https://workflow.example.com/v1",
        )
        self.assertEqual(wf["accessMethod"], ACCESS_WORKFLOW_PLATFORM)

        # Attempting to update workflow profile to direct_model must also be rejected
        with self.assertRaises(ModelConfigurationError) as cm:
            model_store.update_configuration(
                wf["id"],
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://legacy.example.com/v1",
                model_name="legacy-model",
            )
        self.assertEqual(cm.exception.code, "MODEL_CONFIG_DIRECT_WRITE_RETIRED")

    def test_workflow_profile_compatibility_facade_strictly_exposes_workflow_platform(self):
        model_store = ModelConfigurationStore(self.config_path, self.key_dir)
        wf = model_store.create_configuration(
            "excel.analysis",
            "表格工作流",
            ACCESS_WORKFLOW_PLATFORM,
            service_base_url="https://dify.example.com/v1",
        )

        facade = WorkflowProfileCompatibilityStore(self.config_path, self.key_dir)
        data = facade.list_for_task("excel.analysis")
        self.assertEqual(data["profileCount"], 1)
        self.assertEqual(data["profiles"][0]["id"], wf["id"])

    def test_truncated_config_restores_self_contained_auth_state(self):
        self._seed_legacy_config(
            "legacy_recover",
            "word.smart_write",
            "key_recover",
            "sk-recover-live",
            model_name="glm-5.2",
            active=True,
        )
        migrated = self.store.list_services()
        self.assertEqual(migrated["legacyDirectMigration"]["status"], "completed")
        service_id = migrated["directServices"][0]["id"]
        fingerprint_before = DirectServiceStore.api_key_fingerprint("sk-recover-live")
        self.assertEqual(
            DirectServiceStore.api_key_fingerprint(self.store._read_key(service_id)),
            fingerprint_before,
        )
        self.config_path.write_text("{", encoding="utf-8")

        from app.core.config import load_config_payload

        payload = load_config_payload(self.config_path)
        self.assertIn(service_id, payload.get("directServices", {}))
        self.assertEqual(
            payload.get("activeModelConfigurations", {}).get("word.smart_write"),
            service_id,
        )

        client = ProviderClient(direct_service_store=self.store)
        auth = client.resolve_task_auth("word.smart_write")
        self.assertEqual(auth["apiKey"], "sk-recover-live")
        self.assertEqual(auth["modelName"], "glm-5.2")
        self.assertEqual(
            DirectServiceStore.api_key_fingerprint(auth["apiKey"]),
            fingerprint_before,
        )

    def test_load_settings_recovers_truncated_migrated_config_before_startup(self):
        self._seed_legacy_config(
            "legacy_startup",
            "word.smart_write",
            "key_startup",
            "sk-startup",
            model_name="glm-5.2",
            active=True,
        )
        migrated = self.store.list_services()
        service_id = migrated["directServices"][0]["id"]
        self.config_path.write_text("{", encoding="utf-8")

        from app.core.config import load_settings

        settings = load_settings(self.config_path)
        self.assertEqual(settings.service_port, 18100)
        restored = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn(service_id, restored.get("directServices", {}))

    def test_health_read_recovers_truncated_migrated_config(self):
        self._seed_legacy_config(
            "legacy_health",
            "word.smart_write",
            "key_health",
            "sk-health",
            model_name="glm-5.2",
            active=True,
        )
        migrated = self.store.list_services()
        service_id = migrated["directServices"][0]["id"]
        self.config_path.write_text("{", encoding="utf-8")

        from app.services.health import _read_config_payload

        with patch(
            "app.services.health.default_config_path", return_value=self.config_path
        ):
            restored = _read_config_payload()

        self.assertIn(service_id, restored.get("directServices", {}))

    def test_default_config_layout_recovers_keys_from_sibling_run_directory(self):
        runtime_root = self.root / "runtime"
        config_path = runtime_root / "config" / "adapter.json"
        key_dir = runtime_root / "run" / "provider_api_keys"
        config_path.parent.mkdir(parents=True)
        key_dir.mkdir(parents=True)
        config_path.write_text('{"directServices": {}}\n', encoding="utf-8")
        (key_dir / "direct_service_direct_svc_runtime").write_text(
            "sk-runtime", encoding="utf-8"
        )
        migration_txn.write_pre_snapshot(
            config_path,
            key_dir,
            config_path.read_bytes(),
            extra_key_names=["direct_service_direct_svc_runtime"],
        )
        config_path.write_text("{", encoding="utf-8")

        restored = migration_txn.recover_unreadable_config(config_path)

        self.assertEqual(restored, {"directServices": {}})
        self.assertEqual(
            (key_dir / "direct_service_direct_svc_runtime").read_text(
                encoding="utf-8"
            ),
            "sk-runtime",
        )

    def test_provider_client_startup_recovers_shared_state_before_auth_resolution(self):
        state_dir = self.root / "shared-state"
        config_path = state_dir / "adapter.json"
        key_dir = state_dir / "provider_api_keys"
        key_dir.mkdir(parents=True)
        config_path.write_text("{}\n", encoding="utf-8")
        self._seed_legacy_config(
            "legacy_provider_startup",
            "word.smart_write",
            "key_provider_startup",
            "sk-provider-startup",
            model_name="glm-5.2",
            active=True,
        )
        # The helper above seeds the test fixture's default paths; copy its
        # resulting payload/key into the shared runtime layout used by startup.
        config_path.write_bytes(self.config_path.read_bytes())
        (key_dir / "key_provider_startup").write_text(
            "sk-provider-startup", encoding="utf-8"
        )
        store = DirectServiceStore(config_path, key_dir)
        migrated = store.list_services()
        self.assertEqual(migrated["legacyDirectMigration"]["status"], "completed")
        config_path.write_text("{", encoding="utf-8")

        from app.services.provider_client import ProviderClient

        with patch.dict(os.environ, {"AI_WPS_STATE_DIR": str(state_dir)}):
            auth = ProviderClient().resolve_task_auth("word.smart_write")

        self.assertEqual(auth["apiKey"], "sk-provider-startup")
        self.assertEqual(auth["modelName"], "glm-5.2")

    def test_untrusted_journal_paths_never_delete_external_targets(self):
        victim_file = self.root / "victim.txt"
        victim_dir = self.root / "victim-dir"
        victim_file.write_text("keep", encoding="utf-8")
        victim_dir.mkdir()
        (victim_dir / "keep.txt").write_text("keep", encoding="utf-8")
        migration_txn.write_json_atomic(
            migration_txn.journal_path(self.config_path),
            {
                "phase": migration_txn.PHASE_COMMITTING,
                "configPath": str(self.config_path),
                "keyDir": str(self.key_dir),
                "stagingDir": str(victim_dir),
                "newKeyRefs": [str(victim_file)],
                "stagedConfigSha256": "0" * 64,
            },
        )
        self.config_path.write_text("{", encoding="utf-8")

        from app.core.config import load_config_payload

        with self.assertRaises(Exception):
            load_config_payload(self.config_path)
        self.assertEqual(victim_file.read_text(encoding="utf-8"), "keep")
        self.assertTrue((victim_dir / "keep.txt").is_file())

    def test_corrupt_journal_fails_closed_even_when_config_is_readable(self):
        migration_txn.journal_path(self.config_path).write_text(
            "{", encoding="utf-8"
        )

        with self.assertRaises(DirectServiceError) as caught:
            self.store.list_services()

        self.assertEqual(
            caught.exception.code, "DIRECT_SERVICE_MIGRATION_STATE_INVALID"
        )

    @unittest.skipIf(migration_txn.fcntl is None, "fcntl is required")
    def test_migration_lock_blocks_other_processes(self):
        adapter_root = Path(__file__).resolve().parents[1]
        script = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[2])\n"
            "from app.core.direct_migration_txn import migration_lock\n"
            "with migration_lock(Path(sys.argv[1])):\n"
            "    print('locked', flush=True)\n"
            "    time.sleep(0.4)\n"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(self.config_path),
                str(adapter_root),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            started = time.monotonic()
            with migration_txn.migration_lock(self.config_path):
                elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.2)
            self.assertEqual(process.wait(timeout=2), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)

    def test_reconcile_does_not_mark_committed_when_snapshot_write_fails(self):
        payload = {"directServices": {"direct_svc_kept": {"id": "direct_svc_kept"}}}
        migration_txn.write_json_atomic(self.config_path, payload)
        stage_dir = self.key_dir.parent / ".direct-migration-stage-safe"
        stage_dir.mkdir()
        migration_txn.write_json_atomic(
            migration_txn.journal_path(self.config_path),
            {
                "phase": migration_txn.PHASE_COMMITTING,
                "configPath": str(self.config_path),
                "keyDir": str(self.key_dir),
                "stagingDir": str(stage_dir),
                "newKeyRefs": [],
                "stagedConfigSha256": migration_txn.sha256_file(self.config_path),
            },
        )

        with patch(
            "app.core.direct_migration_txn.write_committed_snapshot",
            side_effect=OSError("disk full"),
        ):
            migration_txn.reconcile_inflight(self.config_path, self.key_dir)

        journal = json.loads(
            migration_txn.journal_path(self.config_path).read_text(encoding="utf-8")
        )
        self.assertEqual(journal["phase"], migration_txn.PHASE_COMMITTING)
        self.assertTrue(stage_dir.is_dir())

    def test_snapshots_are_private_and_reject_tampering(self):
        original_umask = os.umask(0)
        try:
            metadata = migration_txn.write_pre_snapshot(
                self.config_path,
                self.key_dir,
                self.config_path.read_bytes(),
            )
        finally:
            os.umask(original_umask)
        tree = migration_txn.snapshot_dir(self.config_path) / "pre"
        self.assertEqual(tree.stat().st_mode & 0o777, 0o700)
        self.assertEqual((tree / "adapter.json").stat().st_mode & 0o777, 0o600)
        self.assertTrue((tree / "manifest.json").is_file())
        self.assertEqual(metadata["configSha256"], migration_txn.sha256_file(tree / "adapter.json"))

        (tree / "adapter.json").write_text('{"tampered": true}', encoding="utf-8")
        self.assertIsNone(
            migration_txn.restore_snapshot_tree(tree, self.config_path, self.key_dir)
        )

    def test_committed_snapshot_retention_removes_expired_recovery_copies(self):
        migration_txn.write_pre_snapshot(
            self.config_path,
            self.key_dir,
            self.config_path.read_bytes(),
        )
        migration_txn.write_committed_snapshot(
            self.config_path,
            self.key_dir,
        )
        expired_at = time.time() - migration_txn.SNAPSHOT_RETENTION_SECONDS - 1
        snapshot_root = migration_txn.snapshot_dir(self.config_path)
        retained_paths = (
            snapshot_root / "pre",
            migration_txn.pre_backup_path(self.config_path),
        )
        for target in retained_paths:
            os.utime(target, (expired_at, expired_at))

        migration_txn.finalize_committed(self.config_path)

        for target in retained_paths:
            self.assertFalse(target.exists())

    def test_reused_existing_service_seeds_legacy_compatibility_for_auth(self):
        existing = self.store.create_service(
            name="已有共享服务",
            service_base_url="https://shared.example.com/v1",
            default_model="alpha-model",
            api_key="sk-shared",
        )
        self.assertEqual(existing["modelListSource"], "none")
        self._seed_legacy_config(
            "legacy_beta",
            "word.smart_write",
            "key_beta",
            "sk-shared",
            service_base_url="https://shared.example.com/v1",
            model_name="beta-model",
            active=True,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        selection = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(selection["modelName"], "beta-model")
        self.assertEqual(selection["modelAvailability"], "available")
        self.assertTrue(selection["modelAvailable"])

        client = ProviderClient(direct_service_store=self.store)
        auth = client.resolve_task_auth("word.smart_write")
        self.assertEqual(auth["modelName"], "beta-model")
        self.assertEqual(auth["apiKey"], "sk-shared")

    def test_auth_failure_revokes_legacy_compatible(self):
        self._seed_legacy_config(
            "legacy_auth",
            "word.smart_write",
            "key_auth",
            "sk-bad",
            model_name="glm-5.2",
            active=True,
        )
        self.store.list_services()
        selection = self.store.get_task_model_selection("word.smart_write")
        self.assertEqual(selection["modelAvailability"], "available")
        service_id = selection["serviceId"]
        self.store._record_model_catalog_failure(
            service_id,
            DirectServiceError("DIRECT_SERVICE_AUTH_FAILED", "API Key 认证失败。"),
        )
        after = self.store.get_task_model_selection("word.smart_write")
        self.assertNotEqual(after.get("modelUnavailableReason"), "legacy_compatible")
        self.assertNotEqual(after.get("modelAvailability"), "available")
        self.assertFalse(after.get("modelAvailable"))
        client = ProviderClient(direct_service_store=self.store)
        with self.assertRaises(AdapterError) as cm:
            client.resolve_task_auth("word.smart_write")
        self.assertEqual(cm.exception.code, "DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE")

    def test_legacy_compatibility_requires_valid_expiring_proof(self):
        self._seed_legacy_config(
            "legacy_proof",
            "word.smart_write",
            "key_proof",
            "sk-proof",
            model_name="glm-5.2",
            active=True,
        )
        migrated = self.store.list_services()
        service_id = migrated["directServices"][0]["id"]
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        service = payload["directServices"][service_id]
        service.pop("legacyCompatibility", None)
        migration_txn.write_json_atomic(self.config_path, payload)
        self.assertFalse(self.store._legacy_model_compatible(service, "glm-5.2"))

        service["legacyCompatibility"] = {
            "models": ["glm-5.2"],
            "serviceBaseUrl": service["serviceBaseUrl"],
            "revision": service["revision"],
            "apiKeyFingerprint": DirectServiceStore.api_key_fingerprint("sk-proof"),
            "expiresAt": "not-a-timestamp",
            "revoked": False,
        }
        self.assertFalse(self.store._legacy_model_compatible(service, "glm-5.2"))

    def test_hard_exit_after_production_keys_reconciles_on_restart(self):
        self._seed_legacy_config(
            "legacy_hard",
            "word.smart_write",
            "key_hard",
            "sk-hard-exit",
            model_name="glm-5.2",
            active=True,
        )
        adapter_root = Path(__file__).resolve().parents[1]
        script = self.root / "crash_after_keys.py"
        script.write_text(
            "\n".join(
                [
                    "import os, sys",
                    "sys.path.insert(0, {0!r})".format(str(adapter_root)),
                    "from app.services.direct_services import DirectServiceStore",
                    "store = DirectServiceStore({0!r}, {1!r})".format(
                        str(self.config_path), str(self.key_dir)
                    ),
                    "original = store._write_key",
                    "def crash_after(service_id, api_key):",
                    "    original(service_id, api_key)",
                    "    os._exit(17)",
                    "store._write_key = crash_after",
                    "store.list_services()",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        crashed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(adapter_root),
            env=dict(os.environ, PYTHONPATH=str(adapter_root)),
            check=False,
        )
        self.assertEqual(crashed.returncode, 17)
        restarted = DirectServiceStore(self.config_path, self.key_dir)
        restarted.list_services()
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertTrue(
            "legacy_hard" in payload.get("modelConfigurations", {})
            or payload.get("directServices")
        )
        staging = list(self.key_dir.parent.glob(".direct-migration-stage-*"))
        self.assertEqual(staging, [])
        referenced = {
            "direct_service_{0}".format(service_id)
            for service_id in payload.get("directServices", {})
        }
        orphan = [
            path
            for path in self._production_direct_service_keys()
            if path.name not in referenced
        ]
        self.assertEqual(orphan, [])
        client = ProviderClient(direct_service_store=restarted)
        auth = client.resolve_task_auth("word.smart_write")
        self.assertEqual(auth["apiKey"], "sk-hard-exit")
        self.assertEqual(auth["modelName"], "glm-5.2")

    def test_pending_profiles_can_be_listed_migrated_and_abandoned(self):
        self._seed_legacy_config(
            "legacy_write_a",
            "word.smart_write",
            "key_write_a",
            "sk-profile-a",
            name="档案 A",
            model_name="glm-5.2",
            active=False,
        )
        self._seed_legacy_config(
            "legacy_write_b",
            "word.smart_write",
            "key_write_b",
            "sk-profile-b",
            name="档案 B",
            service_base_url="https://other.example.com/v1",
            model_name="deepseek-v4-flash",
            active=True,
        )
        listed = self.store.list_services()
        pending = listed.get("legacyDirectPending") or self.store.list_legacy_pending()
        if isinstance(pending, dict) and "items" in pending:
            items = pending["items"]
        else:
            items = pending
        ids = {item["id"] for item in items}
        self.assertIn("legacy_write_a", ids)
        item = next(entry for entry in items if entry["id"] == "legacy_write_a")
        self.assertTrue(item["keyConfigured"])
        self.assertNotIn("apiKey", item)
        self.assertNotEqual(item.get("apiKey"), "sk-profile-a")

        migrated = self.store.migrate_legacy_pending(
            "legacy_write_a", expected_revision=item["revision"]
        )
        self.assertIn(migrated["id"], {svc["id"] for svc in self.store.list_services()["directServices"]})
        again = self.store.list_legacy_pending()
        again_items = again["items"] if isinstance(again, dict) and "items" in again else again
        self.assertEqual(again_items, [])

        self._seed_legacy_config(
            "legacy_write_c",
            "excel.analysis",
            "key_write_c",
            "sk-profile-c",
            name="档案 C",
            service_base_url="https://third.example.com/v1",
            model_name="other-model",
            active=False,
        )
        self._seed_legacy_config(
            "legacy_write_d",
            "excel.analysis",
            "key_write_d",
            "sk-profile-d",
            name="档案 D",
            service_base_url="https://fourth.example.com/v1",
            model_name="other-model-2",
            active=True,
        )
        self.store.list_services()
        pending_before_abandon = self.store.list_legacy_pending()["items"]
        abandon_item = next(
            entry for entry in pending_before_abandon if entry["id"] == "legacy_write_c"
        )
        abandoned = self.store.abandon_legacy_pending(
            "legacy_write_c", expected_revision=abandon_item["revision"]
        )
        self.assertEqual(abandoned["id"], "legacy_write_c")
        self.assertFalse((self.key_dir / "key_write_c").exists())
        leftover = self.store.list_legacy_pending()
        leftover_items = leftover["items"] if isinstance(leftover, dict) and "items" in leftover else leftover
        leftover_ids = {item["id"] for item in leftover_items}
        self.assertNotIn("legacy_write_c", leftover_ids)

    def test_pending_migrate_limit_failure_preserves_pending_profile(self):
        payload = {"directServices": {}, "legacyDirectPending": {}}
        now = "2026-09-14T00:00:00Z"
        for index in range(5):
            service_id = "direct_svc_existing_{0}".format(index)
            payload["directServices"][service_id] = {
                "id": service_id,
                "name": "已有服务 {0}".format(index),
                "serviceBaseUrl": "https://existing-{0}.example/v1".format(index),
                "defaultModel": "model",
                "modelList": ["model"],
                "revision": 1,
                "createdAt": now,
                "updatedAt": now,
            }
        payload["legacyDirectPending"]["legacy_limit"] = {
            "id": "legacy_limit",
            "taskType": "word.smart_write",
            "name": "待迁移",
            "accessMethod": ACCESS_DIRECT_MODEL,
            "serviceBaseUrl": "https://sixth.example/v1",
            "apiKeyRef": "legacy_limit_key",
            "modelName": "glm-5.2",
        }
        migration_txn.write_json_atomic(self.config_path, payload)
        (self.key_dir / "legacy_limit_key").write_text("sk-limit", encoding="utf-8")

        with self.assertRaises(DirectServiceError):
            self.store.migrate_legacy_pending(
                "legacy_limit", expected_revision=1
            )

        after = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_limit", after.get("legacyDirectPending", {}))
        self.assertNotIn("legacy_limit", after.get("modelConfigurations", {}))

    def test_pending_rebuild_never_exceeds_service_limit_when_credentials_match(self):
        first = None
        for index in range(5):
            created = self.store.create_service(
                name="已有服务 {0}".format(index),
                service_base_url="https://existing-{0}.example/v1".format(index),
                default_model="model",
                api_key="sk-existing-{0}".format(index),
            )
            if first is None:
                first = created
        payload = load_config_payload(self.config_path)
        payload["legacyDirectPending"] = {
            "legacy_rebuild_limit": {
                "id": "legacy_rebuild_limit",
                "taskType": "word.smart_write",
                "name": "待重建",
                "accessMethod": ACCESS_DIRECT_MODEL,
                "serviceBaseUrl": first["serviceBaseUrl"],
                "apiKeyRef": "legacy_rebuild_limit_key",
                "modelName": "model",
                "revision": 1,
            }
        }
        migration_txn.write_json_atomic(self.config_path, payload)
        (self.key_dir / "legacy_rebuild_limit_key").write_text(
            "sk-existing-0", encoding="utf-8"
        )

        with self.assertRaises(DirectServiceError) as caught:
            self.store.rebuild_legacy_pending(
                "legacy_rebuild_limit", expected_revision=1
            )

        self.assertEqual(caught.exception.code, "DIRECT_SERVICE_LIMIT")
        after = load_config_payload(self.config_path)
        self.assertEqual(len(after.get("directServices", {})), 5)
        self.assertIn(
            "legacy_rebuild_limit", after.get("legacyDirectPending", {})
        )

    def test_pending_mutation_rejects_stale_revision_without_changes(self):
        payload = {
            "legacyDirectPending": {
                "legacy_stale": {
                    "id": "legacy_stale",
                    "taskType": "word.smart_write",
                    "name": "待处理",
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "serviceBaseUrl": "https://stale.example/v1",
                    "apiKeyRef": "legacy_stale_key",
                    "modelName": "glm-5.2",
                    "revision": 3,
                }
            }
        }
        migration_txn.write_json_atomic(self.config_path, payload)
        before = self.config_path.read_bytes()

        with self.assertRaises(DirectServiceError) as caught:
            self.store.migrate_legacy_pending(
                "legacy_stale", expected_revision=2
            )

        self.assertEqual(caught.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_pending_mutation_requires_revision(self):
        payload = {
            "legacyDirectPending": {
                "legacy_revision_required": {
                    "id": "legacy_revision_required",
                    "taskType": "word.smart_write",
                    "name": "待处理",
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "serviceBaseUrl": "https://revision.example/v1",
                    "revision": 1,
                }
            }
        }
        migration_txn.write_json_atomic(self.config_path, payload)

        with self.assertRaises(DirectServiceError) as caught:
            self.store.abandon_legacy_pending("legacy_revision_required")

        self.assertEqual(caught.exception.code, "DIRECT_SERVICE_REVISION_REQUIRED")
        self.assertIn(
            "legacy_revision_required",
            load_config_payload(self.config_path).get("legacyDirectPending", {}),
        )

    def test_pending_rebuild_save_failure_rolls_back_key_and_pending(self):
        payload = {
            "legacyDirectPending": {
                "legacy_rebuild": {
                    "id": "legacy_rebuild",
                    "taskType": "word.smart_write",
                    "name": "待重建",
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "serviceBaseUrl": "https://rebuild.example/v1",
                    "apiKeyRef": "legacy_rebuild_key",
                    "modelName": "glm-5.2",
                }
            }
        }
        migration_txn.write_json_atomic(self.config_path, payload)
        (self.key_dir / "legacy_rebuild_key").write_text("sk-rebuild", encoding="utf-8")

        with patch(
            "app.core.direct_migration_txn.write_committed_snapshot",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaises(OSError):
                self.store.rebuild_legacy_pending(
                    "legacy_rebuild", expected_revision=1
                )

        after = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_rebuild", after.get("legacyDirectPending", {}))
        self.assertEqual(self._production_direct_service_keys(), [])

    def test_recovery_record_write_failure_is_visible(self):
        self._seed_legacy_config(
            "legacy_record",
            "word.smart_write",
            "key_record",
            "sk-record",
            active=True,
        )
        self.store.list_services()
        self.config_path.write_text("{", encoding="utf-8")
        original_write = migration_txn.write_json_atomic

        def fail_record(path, payload):
            if Path(path).name == "adapter-direct-migration-recovery.json":
                raise OSError("disk full")
            return original_write(path, payload)

        with patch(
            "app.core.direct_migration_txn.write_json_atomic", fail_record
        ):
            recovered = DirectServiceStore(self.config_path, self.key_dir).list_services()
        status = recovered.get("legacyDirectMigrationRecovery") or recovered.get(
            "legacyDirectMigration"
        )
        self.assertTrue(
            recovered.get("recoveryRecordWriteFailed")
            or (isinstance(status, dict) and status.get("recordWriteFailed"))
            or recovered.get("health", {}).get("degraded")
        )


if __name__ == "__main__":
    unittest.main()
