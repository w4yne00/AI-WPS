"""Issue 263: direct format review auto image mode, no separate authorization."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.core.errors import AdapterError
from app.services.direct_services import DirectServiceError, DirectServiceStore
from app.services.provider_client import ProviderClient


TASK = "word.format_review"


class FormatReviewImageAutoTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config.json"
        self.store = DirectServiceStore(self.config, Path(self.tmp.name) / "keys")
        service = self.store.create_service(
            name="vision", service_base_url="https://example.com/v1", default_model="vision"
        )
        self.store.replace_api_key(service["id"], "key-one", expected_revision=1)
        self.store.update_model_list(service["id"], ["vision", "catalog-model"], expected_revision=2)
        self.service = self.store.get_service(service["id"])

    def _activate(self, mode="disabled", model="vision", custom=False):
        return self.store.activate_direct_service(
            self.service["id"],
            TASK,
            {
                "serviceId": self.service["id"],
                "modelName": model,
                "customModel": custom,
                "imageInputMode": mode,
            },
        )

    def test_old_disabled_mode_is_auto_without_forged_auth_or_probe_pass(self):
        self._activate("disabled")

        public = self.store.get_task_model_selection(TASK)
        stored = json.loads(self.config.read_text(encoding="utf-8"))
        raw = stored["taskModelSelections"][TASK]

        self.assertEqual(public["imageInputMode"], "openai_image_url")
        self.assertEqual(public["imageSemanticReadiness"]["code"], "validation_required")
        self.assertIsNone(public["imageExternalAuthorization"])
        self.assertIsNone(public["imageSemanticValidation"])
        self.assertEqual(raw.get("imageInputMode"), "disabled")
        self.assertNotEqual((raw.get("imageExternalAuthorization") or {}).get("authorized"), True)
        self.assertFalse((raw.get("imageSemanticValidation") or {}).get("validated"))
        service, selection, binding, _auth = self.store.image_validation_snapshot(TASK)
        self.assertEqual(service["id"], self.service["id"])
        self.assertEqual(selection["modelName"], "vision")
        self.assertEqual(binding["imageInputMode"], "openai_image_url")

    def test_probe_uses_synthetic_image_and_failure_keeps_selection(self):
        self._activate("openai_image_url", model="catalog-model")
        client = ProviderClient(direct_service_store=self.store)

        def fail_post(*_args, **kwargs):
            path = kwargs["image_files"][0]["path"]
            self.assertIn("ai-wps-image-probe-", path)
            self.assertNotIn("document", path)
            raise AdapterError("IMAGE_CAPABILITY_VALIDATION_FAILED", "模型未能识别合成测试图片。", status_code=502)

        with patch.object(ProviderClient, "_post_direct_task", side_effect=fail_post):
            with self.assertRaises(AdapterError) as raised:
                client.validate_task_image_selection(TASK, "trace-1")

        saved = self.store.get_task_model_selection(TASK)
        self.assertEqual(raised.exception.code, "IMAGE_CAPABILITY_VALIDATION_FAILED")
        self.assertEqual(saved["modelName"], "catalog-model")
        self.assertEqual(saved["serviceId"], self.service["id"])
        self.assertFalse(saved["imageSemanticValidation"]["validated"])
        self.assertIn("合成测试图片", saved["imageSemanticValidation"]["message"])

    def test_draft_probe_does_not_mark_saved_selection_and_repeat_skips_call(self):
        self._activate("openai_image_url", model="catalog-model")
        other = self.store.create_service(
            name="other", service_base_url="https://other.example/v1", default_model="other-model"
        )
        self.store.replace_api_key(other["id"], "key-two", expected_revision=1)
        client = ProviderClient(direct_service_store=self.store)
        calls = []

        def answer(*_args, **_kwargs):
            calls.append("probe")
            return {"answer": "red green red green red green red green"}

        with patch("secrets.choice", side_effect=lambda choices: choices[0]), \
                patch.object(ProviderClient, "_post_direct_task", side_effect=answer):
            client.validate_task_image_selection(
                TASK, "trace-draft",
                {"serviceId": other["id"], "modelName": "other-model", "imageInputMode": "openai_image_url"},
            )
            saved = self.store.get_task_model_selection(TASK)
            self.assertIsNone(saved["imageSemanticValidation"])
            self.assertEqual(saved["modelName"], "catalog-model")

            client.validate_task_image_selection(TASK, "trace-saved")
            client.validate_task_image_selection(TASK, "trace-repeat")

        self.assertEqual(len(calls), 2)
        ready = self.store.get_task_model_selection(TASK)
        self.assertTrue(ready["imageSemanticValidation"]["validated"])
        self.assertEqual(ready["imageSemanticReadiness"]["code"], "ready")

    def test_repeat_format_semantic_validation_skips_the_model(self):
        self._activate("openai_image_url", model="catalog-model")
        client = ProviderClient(direct_service_store=self.store)
        calls = []

        def ok(*_args, **_kwargs):
            calls.append("semantic")
            return {"success": True, "operations": {"classify_role": True}}

        draft = {
            "serviceId": self.service["id"],
            "modelName": "catalog-model",
            "imageInputMode": "openai_image_url",
        }
        with patch.object(ProviderClient, "_validate_format_semantic_direct", side_effect=ok):
            client.validate_task_model_selection(TASK, draft, "trace-1")
            client.validate_task_model_selection(TASK, draft, "trace-2")
        self.assertEqual(calls, ["semantic"])
