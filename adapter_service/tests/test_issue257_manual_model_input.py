import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.direct_services import DirectServiceStore, DirectServiceError


class ManualModelInputStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        key_dir = root / "provider_api_keys"
        self.store = DirectServiceStore(config_path=self.config_path, key_dir=key_dir)

        # Create a test service
        created = self.store.create_service(
            name="Test Service",
            service_base_url="https://api.example.com/v1",
            api_key="sk-test-key-123456",
            default_model="",
        )
        self.service_id = created["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_and_list_custom_models(self) -> None:
        res1 = self.store.add_custom_model(self.service_id, "my-deepseek-v3")
        self.assertIn("my-deepseek-v3", res1.get("customModels", []))

        res2 = self.store.add_custom_model(self.service_id, "  my-custom-qwen  ")
        self.assertEqual(res2.get("customModels"), ["my-deepseek-v3", "my-custom-qwen"])

        # Duplicate should not be re-added
        res3 = self.store.add_custom_model(self.service_id, "my-deepseek-v3")
        self.assertEqual(res3.get("customModels"), ["my-deepseek-v3", "my-custom-qwen"])

        # Empty model name should raise DirectServiceError
        with self.assertRaises(DirectServiceError) as ctx:
            self.store.add_custom_model(self.service_id, "   ")
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_MODEL_REQUIRED")

    def test_delete_custom_model_cascades_smooth_reset(self) -> None:
        self.store.add_custom_model(self.service_id, "custom-m1")
        self.store.add_custom_model(self.service_id, "custom-m2")

        # Set custom-m1 as defaultModel
        self.store.update_service(
            service_id=self.service_id,
            expected_revision=1,
            name="Test Service",
            service_base_url="https://api.example.com/v1",
            default_model="custom-m1",
        )

        # Set custom-m1 as word.smart_write task model
        self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="custom-m1",
            custom_model=True,
        )

        # Set custom-m2 as excel.smart_fill task model
        self.store.update_task_model_selection(
            task_type="excel.smart_fill",
            service_id=self.service_id,
            model_name="custom-m2",
            custom_model=True,
        )

        # Delete custom-m1
        del_res = self.store.delete_custom_model(self.service_id, "custom-m1")
        self.assertEqual(del_res.get("customModels"), ["custom-m2"])

        # Check default_model is smoothly reset to empty string
        svc = self.store.get_service(self.service_id)
        self.assertEqual(svc.get("defaultModel"), "")

        # Check word.smart_write was smoothly reset to inherit default
        selections = self.store.list_task_model_selections().get("selections", {})
        word_sel = selections.get("word.smart_write", {})
        self.assertEqual(word_sel.get("modelName"), "")
        self.assertFalse(word_sel.get("customModel"))
        self.assertFalse(word_sel.get("customModelValidated"))

        # Check excel.smart_fill still keeps custom-m2
        excel_sel = selections.get("excel.smart_fill", {})
        self.assertEqual(excel_sel.get("modelName"), "custom-m2")
        self.assertTrue(excel_sel.get("customModel"))

    def test_custom_model_allowed_when_catalog_is_usable(self) -> None:
        # Mock catalog as usableForSelection
        svc = self.store.get_service(self.service_id)
        payload, _ = self.store._load_with_legacy_direct_migration()
        raw_svc = payload["directServices"][self.service_id]
        raw_svc["modelList"] = ["catalog-model-a", "catalog-model-b"]
        raw_svc["modelListFetchedAt"] = "2026-10-15T12:00:00Z"
        from app.services.direct_services import save_config_payload
        save_config_payload(payload, self.config_path)

        # Now catalog is usableForSelection. Saving custom_model should NOT raise DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED
        record = self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="my-custom-unlisted",
            custom_model=True,
        )
        self.assertEqual(record["modelName"], "my-custom-unlisted")
        self.assertTrue(record["customModel"])

        # It should also automatically add to service's customModels
        updated_svc = self.store.get_service(self.service_id)
        self.assertIn("my-custom-unlisted", updated_svc.get("customModels", []))

    def test_unverified_custom_model_is_available_for_selection(self) -> None:
        record = self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="unverified-custom",
            custom_model=True,
        )
        # Should not raise DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED
        svc = self.store.get_service(self.service_id)
        # _ensure_task_model_ready should pass
        self.store._ensure_task_model_ready(
            task_type="word.smart_write",
            service_id=self.service_id,
            service=svc,
            selection=record,
            effective_model="unverified-custom",
        )

        selections = self.store.list_task_model_selections().get("selections", {})
        word_sel = selections.get("word.smart_write", {})
        self.assertTrue(word_sel.get("modelAvailable"))
        self.assertEqual(word_sel.get("modelAvailability"), "available")
        self.assertFalse(word_sel.get("customModelValidated"))

