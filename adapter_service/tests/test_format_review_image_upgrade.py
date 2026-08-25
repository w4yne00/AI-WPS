# Issue #92: overlay-upgrade from 0.25.1 dormant image semantics.
# Tests name the user-visible break: switch, migrated modes/bindings, one review.

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationStore,
)
from app.services.word.image_semantics import ImageSemanticConfigStore

from adapter_service.tests.test_format_review_image_defaults import (
    HAS_PYDANTIC,
    FigureCaptionProvider,
    _figure_request,
)

if HAS_PYDANTIC:
    from app.services.word.format_reviewer import WordFormatReviewer


def _write_v0251_runtime(root, with_acceptance=True, format_review_image_mode="disabled"):
    key_dir = root / "provider_api_keys"
    key_dir.mkdir()
    (key_dir / "legacy-key").write_text("secret\n", encoding="utf-8")
    (key_dir / "workflow-key").write_text("wf-secret\n", encoding="utf-8")
    (key_dir / "write-key").write_text("write-secret\n", encoding="utf-8")
    image = {"enabled": False, "configVersion": 1}
    if with_acceptance:
        image["wpsAcceptanceConfirmed"] = True
    format_review = {
        "id": "legacy",
        "taskType": "word.format_review",
        "name": "旧直连",
        "accessMethod": ACCESS_DIRECT_MODEL,
        "serviceBaseUrl": "https://vision.example/v1",
        "modelName": "vision-1",
        "apiKeyRef": "legacy-key",
        "configVersion": 1,
    }
    if format_review_image_mode is not None:
        format_review["imageInputMode"] = format_review_image_mode
    payload = {
        "formatReview": {"imageSemantics": image},
        "modelConfigurations": {
            "legacy": format_review,
            "workflow": {
                "id": "workflow",
                "taskType": "word.format_review",
                "name": "工作流",
                "accessMethod": ACCESS_WORKFLOW_PLATFORM,
                "serviceBaseUrl": "https://dify.example/v1",
                "apiKeyRef": "workflow-key",
                "configVersion": 1,
                "imageInputMode": "disabled",
            },
            "writer": {
                "id": "writer",
                "taskType": "word.smart_write",
                "name": "编写",
                "accessMethod": ACCESS_DIRECT_MODEL,
                "serviceBaseUrl": "https://vision.example/v1",
                "modelName": "writer-1",
                "apiKeyRef": "write-key",
                "configVersion": 1,
                "imageInputMode": "disabled",
            },
        },
    }
    config_path = root / "adapter.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path, key_dir


def _upgrade(config_path, key_dir):
    store = ModelConfigurationStore(config_path, key_dir)
    listed = store.list_for_task("word.format_review")
    writing = store.list_for_task("word.smart_write")
    return store, listed, writing


def _config_by_id(listed, config_id):
    matches = [item for item in listed["configurations"] if item["id"] == config_id]
    return matches[0]


class OverlayUpgradeImageSemanticTests(unittest.TestCase):
    def test_overlay_upgrade_turns_on_switch_and_drops_acceptance(self):
        # Break: 0.25.1 enabled=false stays off, or acceptance remains in user settings.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp), with_acceptance=True)
            _upgrade(config_path, key_dir)
            settings = ImageSemanticConfigStore(config_path).get()
            self.assertTrue(settings["enabled"])
            self.assertNotIn("wpsAcceptanceConfirmed", settings)

    def test_overlay_upgrade_without_acceptance_field_still_enables_switch(self):
        # Break: only configs that still carry the retired field are migrated.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp), with_acceptance=False)
            _upgrade(config_path, key_dir)
            settings = ImageSemanticConfigStore(config_path).get()
            self.assertTrue(settings["enabled"])
            self.assertNotIn("wpsAcceptanceConfirmed", settings)

    def test_overlay_upgrade_migrates_format_review_direct_and_writes_binding(self):
        # Break: old direct format-review stays disabled, or upgrade skips the binding.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            store, listed, _writing = _upgrade(config_path, key_dir)
            legacy = _config_by_id(listed, "legacy")
            authorization = legacy["imageExternalAuthorization"]
            self.assertEqual(legacy["imageInputMode"], "openai_image_url")
            self.assertTrue(authorization["authorized"])
            self.assertFalse(authorization.get("stale", False))
            self.assertEqual(authorization["serviceHost"], "vision.example")
            self.assertEqual(authorization["imageInputMode"], "openai_image_url")
            self.assertEqual(authorization["modelName"], "vision-1")
            self.assertIsNone(legacy["imageSemanticValidation"])

            saved = store.create_configuration(
                "word.format_review",
                "对照保存",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            saved = store.replace_api_key(saved["id"], "other-secret")
            saved_auth = saved["imageExternalAuthorization"]
            self.assertEqual(authorization["serviceHost"], saved_auth["serviceHost"])
            self.assertEqual(authorization["imageInputMode"], saved_auth["imageInputMode"])
            self.assertEqual(authorization["modelName"], saved_auth["modelName"])
            self.assertEqual(authorization["authorized"], saved_auth["authorized"])

    def test_overlay_upgrade_migrates_missing_image_input_mode_field(self):
        # Break: 0.25.1 records without imageInputMode keep the dormant fill-in.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(
                Path(tmp), format_review_image_mode=None
            )
            _store, listed, _writing = _upgrade(config_path, key_dir)
            legacy = _config_by_id(listed, "legacy")
            self.assertEqual(legacy["imageInputMode"], "openai_image_url")
            self.assertTrue(legacy["imageExternalAuthorization"]["authorized"])

    def test_overlay_upgrade_does_not_rewrite_workflow_or_other_task_modes(self):
        # Break: upgrade leaks openai_image_url onto workflow or writing configs.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            _store, listed, writing = _upgrade(config_path, key_dir)
            workflow = _config_by_id(listed, "workflow")
            writer = _config_by_id(writing, "writer")
            self.assertEqual(workflow["imageInputMode"], "disabled")
            self.assertIsNone(workflow["imageExternalAuthorization"])
            self.assertEqual(writer["imageInputMode"], "disabled")
            self.assertIsNone(writer["imageExternalAuthorization"])

    def test_overlay_upgrade_later_host_change_stales_until_next_save(self):
        # Break: post-upgrade target change keeps the migrated binding.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            store, _listed, _writing = _upgrade(config_path, key_dir)
            changed = store.update_configuration(
                "legacy",
                name="旧直连",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://other-vision.example/v1",
                model_name="vision-1",
                image_input_mode="openai_image_url",
            )
            self.assertTrue(changed["imageExternalAuthorization"]["stale"])
            rebound = store.update_configuration(
                "legacy",
                name="旧直连",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://other-vision.example/v1",
                model_name="vision-1",
                image_input_mode="openai_image_url",
            )
            self.assertFalse(rebound["imageExternalAuthorization"]["stale"])
            self.assertEqual(
                rebound["imageExternalAuthorization"]["serviceHost"],
                "other-vision.example",
            )

    def test_overlay_upgrade_is_one_shot_and_stop_switch_stays_off(self):
        # Break: later adapter loads re-open a switch the operator closed.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            _upgrade(config_path, key_dir)
            ImageSemanticConfigStore(config_path).set_enabled(False)
            _store, listed, _writing = _upgrade(config_path, key_dir)
            settings = ImageSemanticConfigStore(config_path).get()
            self.assertFalse(settings["enabled"])
            self.assertEqual(_config_by_id(listed, "legacy")["imageInputMode"], "openai_image_url")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class OverlayUpgradeFormatReviewResultTests(unittest.TestCase):
    def test_upgraded_review_completes_without_pixels_when_probe_absent(self):
        # Break: missing probe blocks the review, or the report claims pixel_inspected.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            _store, listed, _writing = _upgrade(config_path, key_dir)
            legacy = _config_by_id(listed, "legacy")
            settings = ImageSemanticConfigStore(config_path).get()
            self.assertTrue(settings["enabled"])
            self.assertEqual(legacy["imageInputMode"], "openai_image_url")
            self.assertTrue(legacy["imageExternalAuthorization"]["authorized"])
            self.assertIsNone(legacy["imageSemanticValidation"])
            provider = FigureCaptionProvider()
            result = WordFormatReviewer(provider_client=provider).review(
                _figure_request(
                    {
                        "imageId": "figure-1",
                        "captionStatus": "missing",
                        "nearbyText": "系统架构",
                        "supported": True,
                    }
                ),
                trace_id="trace-upgrade",
                task_auth={
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "modelName": "vision-1",
                    "imageSemantics": settings,
                    "modelConfiguration": {
                        "serviceBaseUrl": "https://vision.example/v1",
                        "accessMethod": ACCESS_DIRECT_MODEL,
                        "modelName": "vision-1",
                        "imageInputMode": legacy["imageInputMode"],
                        "imageExternalAuthorization": legacy["imageExternalAuthorization"],
                        "imageSemanticValidation": legacy["imageSemanticValidation"],
                    },
                },
                image_assets=[
                    {
                        "imageId": "figure-1",
                        "groupId": "g1",
                        "pixelEvidenceVerified": True,
                    }
                ],
            )
            self.assertGreaterEqual(result["summary"]["issueCount"], 1)
            self.assertEqual(result["summary"].get("pixelInspectedCount"), 0)
            self.assertEqual(result["summary"]["pixelUploadCount"], 0)
            self.assertNotEqual(result["summary"].get("imageEvidenceStatus"), "pixel_inspected")
            dumped = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("pixel_inspected", dumped)
            self.assertNotIn("已看图", dumped)

    def test_in_flight_frozen_auth_ignores_live_upgrade(self):
        # Break: a task started before upgrade re-reads the live switch and claims pixels.
        with TemporaryDirectory() as tmp:
            config_path, key_dir = _write_v0251_runtime(Path(tmp))
            frozen = {
                "accessMethod": ACCESS_DIRECT_MODEL,
                "modelName": "vision-1",
                "imageSemantics": {"enabled": False},
                "modelConfiguration": {
                    "serviceBaseUrl": "https://vision.example/v1",
                    "accessMethod": ACCESS_DIRECT_MODEL,
                    "modelName": "vision-1",
                    "imageInputMode": "disabled",
                    "imageExternalAuthorization": None,
                    "imageSemanticValidation": None,
                },
            }
            _store, listed, _writing = _upgrade(config_path, key_dir)
            legacy = _config_by_id(listed, "legacy")
            self.assertEqual(legacy["imageInputMode"], "openai_image_url")

            class LiveUpgradeProvider(FigureCaptionProvider):
                def image_semantic_settings(self):
                    return ImageSemanticConfigStore(config_path).get()

            provider = LiveUpgradeProvider()
            result = WordFormatReviewer(provider_client=provider).review(
                _figure_request(
                    {
                        "imageId": "figure-1",
                        "captionStatus": "missing",
                        "nearbyText": "系统架构",
                        "supported": True,
                    }
                ),
                trace_id="trace-inflight",
                task_auth=frozen,
                image_assets=[
                    {
                        "imageId": "figure-1",
                        "groupId": "g1",
                        "pixelEvidenceVerified": True,
                    }
                ],
            )
            self.assertGreaterEqual(result["summary"]["issueCount"], 1)
            self.assertEqual(result["summary"].get("pixelInspectedCount"), 0)
            self.assertEqual(result["summary"]["pixelUploadCount"], 0)
