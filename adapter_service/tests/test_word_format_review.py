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

    def format_review_roles(self, trace_id: str, input_data: dict, prompt: str) -> dict:
        self.calls.append({"traceId": trace_id, "inputData": input_data, "prompt": prompt})
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
        self.assertEqual(result["summary"]["provider"], "enterprise-dify-chat/task-file")
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

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection"),
            trace_id="trace-format-think",
        )

        self.assertEqual(result["summary"]["aiFallbackReason"], "")
        self.assertEqual(result["summary"]["aiClassifiedParagraphCount"], 1)
        self.assertEqual(result["summary"]["provider"], "enterprise-dify-chat/task-file")

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
