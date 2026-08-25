# Issue #91: new-install format-review direct image semantics defaults.
# These tests name the user-visible break: config save/activate and task reports.

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationStore,
)
from app.services.word.image_semantics import (
    ImageSemanticConfigStore,
    ImageSemanticRuntime,
)

HAS_PYDANTIC = True
try:
    from app.core.models import WordDocumentRequest
    from app.services.word.format_reviewer import WordFormatReviewer
except Exception:  # pragma: no cover - environment without pydantic
    HAS_PYDANTIC = False


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class FigureCaptionProvider(object):
    def __init__(self, suggestion="系统架构"):
        self.suggestion = suggestion
        self.calls = []

    def is_task_configured(self, task_type):
        return task_type == "word.format_review"

    def format_semantics(
        self, operation, trace_id, input_data, prompt, task_auth=None, output_token_budget=None
    ):
        self.calls.append(
            {
                "operation": operation,
                "inputData": input_data,
                "taskAuth": task_auth,
            }
        )
        if operation != "suggest_figure_caption":
            return {
                "answer": json.dumps(
                    {
                        "schemaVersion": "format_semantics.v1",
                        "operation": operation,
                        "snapshotBinding": input_data.get("snapshotBinding", {}),
                        "items": [],
                    },
                    ensure_ascii=False,
                )
            }
        block_id = input_data["candidateBlockIds"][0]
        return {
            "answer": json.dumps(
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": operation,
                    "snapshotBinding": input_data.get("snapshotBinding", {}),
                    "items": [
                        {
                            "blockId": block_id,
                            "status": "suggested",
                            "suggestion": self.suggestion,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }


def _figure_request(image):
    return parse_word_request(
        {
            "documentId": "figure-caption.docx",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "正文",
                "paragraphs": [{"index": 1, "text": "正文"}],
                "headings": [],
                "documentStructure": {
                    "formatBlocks": [
                        {
                            "blockId": "format-image-figure-1",
                            "blockType": "image",
                            "paragraphIndex": 2,
                            "text": "",
                            "images": [image],
                        }
                    ],
                },
            },
            "options": {"templateId": "technical-document-template-rules"},
        }
    )


def _ready_task_auth(validated=True, enabled=True, mode="openai_image_url"):
    binding = {
        "configVersion": 1,
        "serviceHost": "vision.example",
        "accessMethod": ACCESS_DIRECT_MODEL,
        "imageInputMode": mode,
        "modelName": "vision-1",
    }
    authorization = dict(binding)
    authorization["authorized"] = True
    validation = dict(binding)
    validation["validated"] = validated
    return {
        "providerBaseUrl": "https://vision.example/v1",
        "apiKey": "frozen-secret",
        "accessMethod": ACCESS_DIRECT_MODEL,
        "modelName": "vision-1",
        "maxOutputTokens": 4096,
        "contextWindowTokens": 40000,
        "imageSemantics": {"enabled": enabled},
        "modelConfiguration": {
            "configVersion": 1,
            "serviceBaseUrl": "https://vision.example/v1",
            "accessMethod": ACCESS_DIRECT_MODEL,
            "modelName": "vision-1",
            "imageInputMode": mode,
            "imageExternalAuthorization": authorization,
            "imageSemanticValidation": validation,
        },
    }


class NewInstallImageSemanticConfigTests(unittest.TestCase):
    def test_empty_install_enables_image_semantics_without_wps_acceptance(self):
        # Break: missing config treated as closed, or WPS acceptance still a hard gate.
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ImageSemanticConfigStore(config_path)

            settings = store.get()
            self.assertTrue(settings["enabled"])
            self.assertNotIn("wpsAcceptanceConfirmed", settings)

            disabled = store.set_enabled(False)
            self.assertFalse(disabled["enabled"])
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["formatReview"]["imageSemantics"]["enabled"])
            self.assertNotIn(
                "wpsAcceptanceConfirmed",
                persisted["formatReview"]["imageSemantics"],
            )

    def test_example_config_enables_switch_and_omits_wps_acceptance(self):
        # Break: shipped example still ships dormant + acceptance field.
        example = Path(__file__).resolve().parents[2] / "config" / "adapter.example.json"
        payload = json.loads(example.read_text(encoding="utf-8"))
        image = payload["formatReview"]["imageSemantics"]
        self.assertTrue(image["enabled"])
        self.assertNotIn("wpsAcceptanceConfirmed", image)


class FormatReviewDirectConfigDefaultTests(unittest.TestCase):
    def _store(self, root):
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        return ModelConfigurationStore(config_path, root / "provider_api_keys")

    def test_new_format_review_direct_defaults_to_openai_image_url(self):
        # Break: new format-review direct config still defaults to disabled.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            self.assertEqual(configuration["imageInputMode"], "openai_image_url")

    def test_workflow_and_other_tasks_still_default_disabled(self):
        # Break: image mode leaks to workflow or non-format-review tasks.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            workflow = store.create_configuration(
                "word.format_review",
                "工作流格式审查",
                ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://dify.example/v1",
            )
            writing = store.create_configuration(
                "word.smart_write",
                "智能编写直连",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="writer-1",
            )
            self.assertEqual(workflow["imageInputMode"], "disabled")
            self.assertEqual(writing["imageInputMode"], "disabled")

    def test_saving_usable_format_review_direct_writes_egress_binding(self):
        # Break: usable save still requires a separate authorization click.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            created = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            saved = store.replace_api_key(created["id"], "secret")
            authorization = saved["imageExternalAuthorization"]
            self.assertTrue(authorization["authorized"])
            self.assertFalse(authorization.get("stale", False))
            self.assertEqual(authorization["serviceHost"], "vision.example")
            self.assertEqual(authorization["imageInputMode"], "openai_image_url")
            self.assertEqual(authorization["modelName"], "vision-1")
            self.assertTrue(saved["complete"])
            self.assertIsNone(saved["imageSemanticValidation"])

    def test_host_mode_or_model_change_invalidates_binding_until_next_save(self):
        # Break: changed target keeps the old binding, or the changing save rebinds itself.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            created = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            saved = store.replace_api_key(created["id"], "secret")
            changed = store.update_configuration(
                saved["id"],
                name="直连格式审查",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://other-vision.example/v1",
                model_name="vision-1",
                image_input_mode="openai_image_url",
            )
            self.assertTrue(changed["imageExternalAuthorization"]["stale"])

            rebound = store.update_configuration(
                saved["id"],
                name="直连格式审查",
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

    def test_format_review_direct_can_be_set_back_to_disabled(self):
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            created = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            disabled = store.update_configuration(
                created["id"],
                name="直连格式审查",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
                image_input_mode="disabled",
            )
            self.assertEqual(disabled["imageInputMode"], "disabled")
            self.assertIsNone(disabled["imageExternalAuthorization"])

    def test_completeness_and_activation_ignore_probe_result(self):
        # Break: probe failure blocks complete/activate.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            created = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            saved = store.replace_api_key(created["id"], "secret")
            failed = store.record_image_semantic_validation(
                saved["id"], {"validated": False, "errorCode": "IMAGE_PROBE_FAILED"}
            )
            self.assertTrue(failed["complete"])
            self.assertFalse(failed["imageSemanticValidation"]["validated"])
            activated = store.activate_configuration(failed["id"])
            self.assertEqual(activated["activeConfigurationId"], failed["id"])

    def test_copying_usable_format_review_direct_writes_egress_binding(self):
        # Break: copy drops authorization even when the copy is already usable.
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            created = store.create_configuration(
                "word.format_review",
                "直连格式审查",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            store.replace_api_key(created["id"], "secret")
            copied = store.copy_configuration(created["id"], name="直连副本")
            authorization = copied["imageExternalAuthorization"]
            self.assertEqual(copied["imageInputMode"], "openai_image_url")
            self.assertTrue(authorization["authorized"])
            self.assertFalse(authorization.get("stale", False))
            self.assertEqual(authorization["serviceHost"], "vision.example")
            self.assertTrue(copied["complete"])


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class FormatReviewImageReportTests(unittest.TestCase):
    def test_probe_pass_and_missing_caption_report_pixel_inspected(self):
        # Break: ready visual path never marks pixel_inspected or omits host/counts.
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
            trace_id="trace-pixel",
            task_auth=_ready_task_auth(validated=True),
            image_assets=[
                {
                    "imageId": "figure-1",
                    "groupId": "g1",
                    "pixelEvidenceVerified": True,
                }
            ],
        )
        figure_issue = [
            issue
            for issue in result["issues"]
            if issue.get("ruleId") == "structure.missing_figure_caption"
        ]
        self.assertTrue(figure_issue)
        self.assertEqual(figure_issue[0]["suggestion"], "系统架构")
        self.assertEqual(result["summary"]["pixelInspectedCount"], 1)
        self.assertEqual(result["summary"]["pixelUploadCount"], 1)
        self.assertEqual(result["summary"]["figureCaptionCandidateCount"], 1)
        self.assertEqual(result["summary"]["imageTargetHost"], "vision.example")
        self.assertNotIn("图片审查", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("默认识图", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("已看图", json.dumps(result, ensure_ascii=False))

    def test_closed_or_failed_visual_path_completes_without_claiming_pixels(self):
        # Break: closed/failed visual path either fails the review or claims pixels.
        cases = (
            {"enabled": False, "validated": True, "mode": "openai_image_url"},
            {"enabled": True, "validated": False, "mode": "openai_image_url"},
            {"enabled": True, "validated": True, "mode": "disabled"},
        )
        for case in cases:
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
                trace_id="trace-closed",
                task_auth=_ready_task_auth(**case),
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
            statuses = [
                issue.get("dataStatus")
                for issue in result["issues"]
                if issue.get("ruleId") == "structure.missing_figure_caption"
            ]
            self.assertNotIn("verified", statuses)

    def test_existing_caption_pending_association_and_nonvisual_upload_zero(self):
        provider = FigureCaptionProvider()
        request = parse_word_request(
            {
                "documentId": "mixed-figures.docx",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "正文",
                    "paragraphs": [{"index": 1, "text": "正文"}],
                    "headings": [],
                    "documentStructure": {
                        "formatBlocks": [
                            {
                                "blockId": "format-image-1",
                                "blockType": "image",
                                "images": [
                                    {
                                        "imageId": "captioned",
                                        "captionStatus": "present",
                                        "supported": True,
                                    }
                                ],
                            },
                            {
                                "blockId": "format-image-2",
                                "blockType": "image",
                                "images": [
                                    {
                                        "imageId": "pending",
                                        "captionStatus": "missing",
                                        "associationStatus": "ambiguous",
                                        "supported": True,
                                    }
                                ],
                            },
                            {
                                "blockId": "format-chart-1",
                                "blockType": "chart",
                                "images": [
                                    {
                                        "imageId": "chart-1",
                                        "captionStatus": "missing",
                                        "supported": False,
                                    }
                                ],
                            },
                        ]
                    },
                },
                "options": {"templateId": "technical-document-template-rules"},
            }
        )
        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-skip",
            task_auth=_ready_task_auth(validated=True),
            image_assets=[
                {"imageId": "captioned", "pixelEvidenceVerified": True},
                {"imageId": "pending", "pixelEvidenceVerified": True},
                {"imageId": "chart-1", "pixelEvidenceVerified": True},
            ],
        )
        self.assertEqual(result["summary"]["pixelUploadCount"], 0)
        self.assertEqual(result["summary"]["pixelInspectedCount"], 0)
        figure_calls = [
            call for call in provider.calls if call["operation"] == "suggest_figure_caption"
        ]
        self.assertEqual(figure_calls, [])

    def test_master_switch_off_does_not_create_export_slot(self):
        # Break: closed switch still allocates or uploads.
        calls = []
        runtime = ImageSemanticRuntime(
            export_picture=lambda candidate: calls.append("export") or {"ok": True},
            upload_picture=lambda asset: calls.append("upload") or True,
        )
        result = runtime.process_group(
            [{"imageId": "figure-1", "altText": "", "nearbyText": "系统架构"}],
            runtime_config={"enabled": False},
            model_configuration=_ready_task_auth()["modelConfiguration"],
        )
        self.assertFalse(result["slotCreated"])
        self.assertFalse(result["pixelExported"])
        self.assertFalse(result["pixelUploaded"])
        self.assertNotEqual(result["status"], "pixel_inspected")
        self.assertEqual(calls, [])


class ProductCopyGuardTests(unittest.TestCase):
    def test_plugin_has_no_removed_image_review_copy(self):
        # Break: task page or settings still ask to disable enhancement this time,
        # or reuse retired product words.
        root = Path(__file__).resolve().parents[2] / "formal-plugin-kit"
        forbidden = ("图片审查", "默认识图", "已看图", "本次关闭图片增强")
        hits = []
        for path in root.rglob("*"):
            if path.suffix not in {".js", ".html", ".css"}:
                continue
            text = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                if phrase in text:
                    hits.append("{0}: {1}".format(path.name, phrase))
        self.assertEqual(hits, [])
