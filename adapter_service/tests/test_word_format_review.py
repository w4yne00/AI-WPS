import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.format_reviewer import WordFormatReviewer


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingFormatReviewProvider:
    def __init__(self, configured: bool = True, fail: bool = False, answer: str = "") -> None:
        self.configured = configured
        self.fail = fail
        self.answer = answer or '{"paragraphs":[{"paragraphIndex":1,"role":"heading1","confidence":0.95}]}'
        self.calls = []
        self.skipped = []

    def is_task_configured(self, task_type: str) -> bool:
        return self.configured and task_type == "word.format_review"

    def get_auth_source_for_task(self, task_type: str) -> str:
        return "task-file"

    def format_review_roles(self, trace_id: str, input_data: dict, prompt: str, task_auth=None) -> dict:
        self.calls.append({"traceId": trace_id, "inputData": input_data, "prompt": prompt, "taskAuth": task_auth})
        if self.fail:
            raise ValueError("invalid provider response")
        return {"answer": self.answer}

    def record_unconfigured_debug(self, task_type: str, trace_id: str, query: str) -> None:
        self.skipped.append({"taskType": task_type, "traceId": trace_id, "query": query})

    def record_skipped_debug(self, task_type: str, trace_id: str, query: str, skip_reason: str, provider: str = "local") -> None:
        self.skipped.append(
            {"taskType": task_type, "traceId": trace_id, "query": query, "skipReason": skip_reason, "provider": provider}
        )


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class WordFormatReviewerTests(unittest.TestCase):
    def _request(self, selection_mode: str = "selection"):
        return parse_word_request(
            {
                "documentId": "format-review.docx",
                "scene": "word",
                "selectionMode": selection_mode,
                "content": {
                    "plainText": "1 总则\n正文内容",
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "1 总则",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 12,
                            "alignment": "left",
                            "outlineLevel": 0,
                        },
                        {
                            "index": 2,
                            "text": "正文内容",
                            "styleName": "Normal",
                            "fontName": "楷体",
                            "fontSize": 14,
                            "alignment": "left",
                            "outlineLevel": 0,
                            "lineSpacing": 1.0,
                            "firstLineIndent": 0,
                        },
                    ],
                    "headings": [],
                    "documentStructure": {"page_setup": {"marginTop": 72}},
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True,
                },
            }
        )

    def test_format_review_returns_issues_not_apply_changes(self) -> None:
        provider = RecordingFormatReviewProvider()

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection"),
            trace_id="trace-format-review",
        )

        self.assertEqual(result["summary"]["scope"], "selection")
        self.assertEqual(result["summary"]["templateId"], "technical-file-format-requirements")
        self.assertEqual(result["summary"]["provider"], "工作流平台")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)
        self.assertIn("issues", result)
        self.assertNotIn("changes", result)
        self.assertFalse(any("targetProperties" in issue for issue in result["issues"]))
        self.assertEqual(provider.calls[0]["inputData"]["taskType"], "word.format_review")

    def test_format_review_uses_local_fallback_without_task_key(self) -> None:
        provider = RecordingFormatReviewProvider(configured=False)

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("document"),
            trace_id="trace-format-local",
        )

        self.assertEqual(result["summary"]["scope"], "document")
        self.assertEqual(result["summary"]["provider"], "local")
        self.assertEqual(result["summary"]["aiFallbackReason"], "provider_not_configured")
        self.assertEqual(provider.calls, [])
        self.assertEqual(provider.skipped[0]["taskType"], "word.format_review")

    def test_format_review_falls_back_when_ai_role_provider_fails(self) -> None:
        provider = RecordingFormatReviewProvider(fail=True)

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection"),
            trace_id="trace-format-provider-failed",
        )

        self.assertEqual(result["summary"]["scope"], "selection")
        self.assertEqual(result["summary"]["provider"], "local")
        self.assertEqual(result["summary"]["aiAttempted"], True)
        self.assertEqual(result["summary"]["aiRequestErrorCount"], 1)
        self.assertEqual(result["summary"]["aiFallbackReason"], "provider_request_failed")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)

    def test_format_review_ignores_think_tag_before_role_json(self) -> None:
        provider = RecordingFormatReviewProvider(
            answer='<think>{"draft": true, "reason": "内部分析"}</think>\n{"paragraphs":[{"paragraphIndex":1,"role":"heading1","confidence":0.95}]}'
        )
        request = self._request("selection")
        request.content.document_structure["formatFacts"] = {
            "paragraphs": [
                {"paragraphIndex": 1, "styleName": "Normal", "text": "1 总则"}
            ]
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-think",
        )

        self.assertEqual(result["summary"]["aiFallbackReason"], "")
        self.assertEqual(result["summary"]["aiClassifiedParagraphCount"], 1)
        self.assertEqual(result["summary"]["provider"], "工作流平台")

    def test_format_review_rejects_unbounded_model_role_attributes(self) -> None:
        reviewer = WordFormatReviewer()
        self.assertIsNone(reviewer._normalize_model_role("heading", {"role": "heading"}))
        self.assertIsNone(reviewer._normalize_model_role("heading10", {"role": "heading10"}))
        self.assertIsNone(reviewer._normalize_model_role("list_item", {"role": "list_item", "level": 1}))
        self.assertEqual(
            reviewer._normalize_model_role(
                "heading", {"role": "heading", "level": 2}
            ),
            {"role": "heading", "attributes": {"level": 2}},
        )

    def test_format_review_sends_only_ambiguous_candidates_with_snapshot_binding(self) -> None:
        provider = RecordingFormatReviewProvider(
            answer=(
                '{"snapshot":{"contentSha256":"content-1","structureSha256":"structure-1",'
                '"formatSha256":"format-1"},"candidates":[{"blockId":"format-context-2",'
                '"role":"heading","level":1,"confidence":0.95}]}'
            )
        )
        request = self._request("document")
        request.content.paragraphs[1] = request.content.paragraphs[1].copy(
            update={"text": "待确认内容"}
        )
        request.content.document_structure = {
            "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
            "formatFingerprint": "format-1",
            "structureFingerprint": "structure-1",
            "contentFingerprint": "content-1",
            "formatBlocks": [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "paragraph",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "text": "普通正文",
                    "format": {"styleName": "Normal"},
                },
                {
                    "blockId": "format-context-2",
                    "blockType": "context",
                    "scope": "in_scope",
                    "paragraphIndex": 2,
                    "text": "待确认内容",
                    "format": {"styleName": "Normal"},
                },
            ],
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "review-model",
            "maxOutputTokens": 4096,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-1",
            "modelConfiguration": {"configVersion": 7, "taskType": "word.format_review"},
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-candidates",
            task_auth=task_auth,
        )

        self.assertEqual(len(provider.calls), 1)
        prompt = provider.calls[0]["prompt"]
        self.assertIn("format-context-2", prompt)
        self.assertNotIn("format-paragraph-1", prompt)
        self.assertIn("content-1", prompt)
        self.assertEqual(provider.calls[0]["taskAuth"], task_auth)
        self.assertEqual(result["summary"]["aiCandidateCount"], 1)
        self.assertEqual(result["summary"]["semanticStatus"], "completed")
        self.assertTrue(any(issue["paragraphIndex"] == 2 for issue in result["issues"]))

    def test_format_review_keeps_deterministic_review_when_direct_capability_is_unknown(self) -> None:
        provider = RecordingFormatReviewProvider()
        request = self._request("document")
        request.content.document_structure["formatFacts"] = {
            "paragraphs": [{"paragraphIndex": 1, "styleName": "Normal", "text": "待确认"}]
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "unknown-model",
            "maxOutputTokens": None,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-unknown",
            "modelConfiguration": {"configVersion": 3, "taskType": "word.format_review"},
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-capability-unknown",
            task_auth=task_auth,
        )

        self.assertEqual(provider.calls, [])
        self.assertEqual(result["summary"]["semanticStatus"], "degraded")
        self.assertEqual(result["summary"]["aiFallbackReason"], "model_capability_unknown")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)

    def test_format_review_normalizes_wps_font_size_and_alignment_values(self) -> None:
        request = parse_word_request(
            {
                "documentId": "format-review-normalized.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "正文内容",
                    "paragraphs": [
                        {
                            "index": 4,
                            "text": "正文内容",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 0,
                            "alignment": "3",
                            "outlineLevel": 0,
                            "lineSpacing": 1.25,
                            "firstLineIndent": 640,
                        }
                    ],
                    "headings": [],
                    "documentStructure": {
                        "page_setup": {
                            "marginTop": 1440,
                            "marginBottom": 1440,
                            "marginLeft": 1800,
                            "marginRight": 1800,
                        }
                    },
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True,
                },
            }
        )

        result = WordFormatReviewer().review(request)

        self.assertFalse(
            any(issue["ruleId"] in {"font_size", "alignment"} for issue in result["issues"]),
            result["issues"],
        )
