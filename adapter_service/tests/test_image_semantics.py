import json
import struct
import zlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.errors import AdapterError
from app.services.word.format_semantics import FormatSemanticContract
from app.services.word.image_semantics import (
    IMAGE_INPUT_MODES,
    ImageAssetStore,
    ImageSemanticConfigStore,
    ImageSemanticRuntime,
    collect_image_inventory,
    image_pixel_policy,
    select_image_export_groups,
)


class ImageSemanticSafetyTests(unittest.TestCase):
    @staticmethod
    def _png(width=32, height=16, payload=b"pixels"):
        def chunk(kind, data):
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
            )

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", payload)
            + chunk(b"IEND", b"")
        )

    def test_missing_runtime_setting_defaults_on_and_can_be_disabled(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ImageSemanticConfigStore(config_path)

            self.assertTrue(store.get()["enabled"])
            self.assertNotIn("wpsAcceptanceConfirmed", store.get())

            disabled = store.set_enabled(False)
            self.assertFalse(disabled["enabled"])
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["formatReview"]["imageSemantics"]["enabled"])
            self.assertNotIn(
                "wpsAcceptanceConfirmed",
                persisted["formatReview"]["imageSemantics"],
            )

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
                {"enabled": True}, base
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
                {"enabled": True}, authorized
            )["allowed"]
        )

        changed = dict(authorized, modelName="text-only-1")
        self.assertFalse(
            image_pixel_policy(
                {"enabled": True}, changed
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

    def test_figure_caption_suggestion_requires_text_or_verified_pixel_evidence(self):
        candidate = {
            "figureCaptionStatus": "missing",
            "evidence": {"evidenceStatus": "insufficient", "altText": ""},
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_figure_caption",
            "snapshotBinding": {},
            "items": [{"blockId": "figure-1", "status": "suggested", "suggestion": "系统架构"}],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_figure_caption", payload, {"figure-1": candidate}, {}, allow_pixel_inspection=True
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_EVIDENCE_INSUFFICIENT")

        candidate["pixelEvidenceVerified"] = True
        payload["items"][0]["status"] = "pixel_inspected"
        normalized = FormatSemanticContract.validate_response(
            "suggest_figure_caption", payload, {"figure-1": candidate}, {}, allow_pixel_inspection=True
        )
        self.assertEqual(normalized["items"][0]["status"], "pixel_inspected")

    def test_image_export_groups_only_include_confirmed_missing_captions_and_preserve_order(self):
        groups = select_image_export_groups(
            [
                {"imageId": "figure-1", "captionStatus": "missing", "supported": True},
                {"imageId": "figure-2", "captionStatus": "present", "supported": True},
                {"imageId": "figure-3", "captionStatus": "missing", "supported": False},
                {"imageId": "figure-4", "captionStatus": "missing", "supported": True, "groupId": "g2"},
                {"imageId": "figure-5", "captionStatus": "missing", "supported": True, "groupId": "g2"},
            ],
            remaining_calls=2,
        )
        self.assertEqual([[item["imageId"] for item in group] for group in groups], [["figure-1"], ["figure-4", "figure-5"]])

    def test_image_asset_store_rejects_path_escape_and_fake_png(self):
        with TemporaryDirectory() as tmp:
            store = ImageAssetStore(Path(tmp) / "assets")
            group = store.allocate_group(
                "format-snapshot-12345678",
                [{"imageId": "figure-1", "groupId": "g1"}],
                {"documentId": "doc-a", "editSequence": "7"},
            )
            slot = Path(group["assets"][0]["slotPath"])
            slot.write_bytes(self._png())
            committed = store.commit_group(group["groupId"], {"documentId": "doc-a", "editSequence": "7"})
            self.assertEqual(committed["status"], "committed")
            self.assertEqual(committed["assets"][0]["width"], 32)
            self.assertEqual(committed["assets"][0]["height"], 16)
            store.delete_group(group["groupId"])
            self.assertFalse(slot.exists())

            escaped = store.allocate_group(
                "format-snapshot-12345678",
                [{"imageId": "figure-2", "groupId": "g2"}],
                {"documentId": "doc-a", "editSequence": "7"},
            )
            escaped_slot = Path(escaped["assets"][0]["slotPath"])
            escaped_slot.symlink_to(Path(tmp) / "outside.png")
            with self.assertRaises(AdapterError) as raised:
                store.commit_group(escaped["groupId"], {"documentId": "doc-a", "editSequence": "7"})
            self.assertEqual(raised.exception.code, "IMAGE_ASSET_PATH_INVALID")

    def test_image_asset_store_group_is_atomic_and_enforces_resource_limits(self):
        with TemporaryDirectory() as tmp:
            store = ImageAssetStore(Path(tmp) / "assets")
            group = store.allocate_group(
                "format-snapshot-12345678",
                [
                    {"imageId": "figure-1", "groupId": "g1"},
                    {"imageId": "figure-2", "groupId": "g1"},
                ],
                {"documentId": "doc-a", "editSequence": "7"},
            )
            Path(group["assets"][0]["slotPath"]).write_bytes(self._png())
            Path(group["assets"][1]["slotPath"]).write_bytes(b"not-a-png")
            with self.assertRaises(AdapterError) as raised:
                store.commit_group(group["groupId"], {"documentId": "doc-a", "editSequence": "7"})
            self.assertEqual(raised.exception.code, "IMAGE_ASSET_PNG_INVALID")
            self.assertFalse(Path(group["assets"][0]["slotPath"]).exists())
            self.assertFalse(Path(group["assets"][1]["slotPath"]).exists())

            oversized = store.allocate_group(
                "format-snapshot-12345678",
                [{"imageId": "figure-3", "groupId": "g2"}],
                {"documentId": "doc-a", "editSequence": "7"},
            )
            Path(oversized["assets"][0]["slotPath"]).write_bytes(self._png(width=9000, height=1))
            with self.assertRaises(AdapterError) as raised:
                store.commit_group(oversized["groupId"], {"documentId": "doc-a", "editSequence": "7"})
            self.assertEqual(raised.exception.code, "IMAGE_ASSET_DIMENSION_LIMIT")


if __name__ == "__main__":
    unittest.main()
