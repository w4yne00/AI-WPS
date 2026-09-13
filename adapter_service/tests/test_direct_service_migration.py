import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.direct_services import DirectServiceStore
from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationError,
    ModelConfigurationStore,
    WorkflowProfileCompatibilityStore,
)
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

        with patch("app.services.direct_services.save_config_payload", side_effect=IOError("disk full")):
            with self.assertRaises(IOError):
                self.store.list_services()

        # Check that original payload was restored and no orphaned direct service keys remain
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_rollback", payload.get("modelConfigurations", {}))
        self.assertEqual(payload["activeModelConfigurations"]["word.smart_write"], "legacy_rollback")
        self.assertTrue((self.key_dir / "key_rollback").exists())

        # No direct_svc_ key files created
        direct_keys = list(self.key_dir.glob("direct_svc_*"))
        self.assertEqual(len(direct_keys), 0)

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


if __name__ == "__main__":
    unittest.main()
