import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.errors import AdapterError
from app.services.word.format_semantics import FormatSemanticContract
from app.services.word.image_semantics import (
    IMAGE_INPUT_MODES,
    ImageSemanticConfigStore,
    ImageSemanticRuntime,
    collect_image_inventory,
    image_pixel_policy,
)


class ImageSemanticSafetyTests(unittest.TestCase):
    def test_missing_runtime_setting_is_closed_and_can_be_enabled_only_after_acceptance(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ImageSemanticConfigStore(config_path)

            self.assertFalse(store.get()["enabled"])
            with self.assertRaises(AdapterError) as raised:
                store.set_enabled(True, wps_acceptance_confirmed=False)
            self.assertEqual(raised.exception.code, "IMAGE_SEMANTICS_WPS_ACCEPTANCE_REQUIRED")

            enabled = store.set_enabled(True, wps_acceptance_confirmed=True)
            self.assertTrue(enabled["enabled"])
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(persisted["formatReview"]["imageSemantics"]["enabled"])

    def test_closed_runtime_never_allocates_exports_or_uploads_pixels(self):
        calls = []
        runtime = ImageSemanticRuntime(
            export_picture=lambda candidate: calls.append("export"),
            upload_picture=lambda asset: calls.append("upload"),
        )

        result = runtime.process_group(
            [{"imageId": "figure-1", "altText": "", "nearbyText": ""}],
            runtime_config={"enabled": False},
            model_configuration={
                "imageInputMode": "openai_image_url",
                "imageExternalAuthorization": {"authorized": True},
                "imageSemanticValidation": {"validated": True},
            },
        )

        self.assertEqual(result["status"], "not_assessable")
        self.assertFalse(result["slotCreated"])
        self.assertFalse(result["pixelExported"])
        self.assertFalse(result["pixelUploaded"])
        self.assertEqual(calls, [])

    def test_pixel_policy_requires_mode_authorization_and_current_validation(self):
        self.assertEqual(set(IMAGE_INPUT_MODES), {"disabled", "openai_image_url", "dify_file"})
        base = {
            "configVersion": 4,
            "serviceBaseUrl": "https://vision.example/v1",
            "accessMethod": "direct_model",
            "modelName": "vision-1",
            "imageInputMode": "openai_image_url",
        }
        self.assertFalse(
            image_pixel_policy(
                {"enabled": True, "wpsAcceptanceConfirmed": True}, base
            )["allowed"]
        )

        authorized = dict(base)
        authorized["imageExternalAuthorization"] = {
            "authorized": True,
            "configVersion": 4,
            "serviceHost": "vision.example",
            "accessMethod": "direct_model",
            "imageInputMode": "openai_image_url",
            "modelName": "vision-1",
        }
        authorized["imageSemanticValidation"] = {
            "validated": True,
            "configVersion": 4,
            "serviceHost": "vision.example",
            "accessMethod": "direct_model",
            "imageInputMode": "openai_image_url",
            "modelName": "vision-1",
        }
        self.assertTrue(
            image_pixel_policy(
                {"enabled": True, "wpsAcceptanceConfirmed": True}, authorized
            )["allowed"]
        )

        changed = dict(authorized, modelName="text-only-1")
        self.assertFalse(
            image_pixel_policy(
                {"enabled": True, "wpsAcceptanceConfirmed": True}, changed
            )["allowed"]
        )

    def test_inventory_preserves_deterministic_picture_facts_when_visuals_are_off(self):
        inventory = collect_image_inventory(
            {
                "formatBlocks": [
                    {
                        "blockType": "image",
                        "imageId": "figure-1",
                        "captionStatus": "missing",
                        "altText": "系统架构图",
                        "nearbyText": "系统总体架构",
                    },
                    {
                        "blockType": "image",
                        "imageId": "figure-2",
                        "captionStatus": "present",
                    },
                ]
            }
        )
        self.assertEqual(inventory["imageCount"], 2)
        self.assertEqual(inventory["missingFigureCaptionCount"], 1)
        self.assertEqual(inventory["textEvidenceOnlyCount"], 1)
        self.assertEqual(inventory["notAssessableCount"], 0)

    def test_pixel_inspected_response_requires_verified_pixel_evidence(self):
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_figure_caption",
            "snapshotBinding": {},
            "items": [
                {
                    "blockId": "figure-1",
                    "status": "pixel_inspected",
                    "suggestion": "系统架构",
                }
            ],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_figure_caption",
                payload,
                {"figure-1": {"pixelEvidenceVerified": False}},
                {},
            )
        self.assertEqual(raised.exception.code, "IMAGE_SEMANTICS_DISABLED")

        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_figure_caption",
                payload,
                {"figure-1": {"pixelEvidenceVerified": False}},
                {},
                allow_pixel_inspection=True,
            )
        self.assertEqual(raised.exception.code, "IMAGE_PIXEL_EVIDENCE_NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
