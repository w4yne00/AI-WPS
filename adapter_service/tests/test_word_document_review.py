import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.document_reviewer import WordDocumentReviewer


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingDocumentReviewProvider:
    def __init__(self) -> None:
        self.calls = []

    def document_review(self, text: str, trace_id: str, document_type: str, review_prompt: str) -> dict:
        self.calls.append(
            {
                "text": text,
                "traceId": trace_id,
                "documentType": document_type,
                "reviewPrompt": review_prompt,
            }
        )
        return {
            "summary": "发现 1 项问题。",
            "issues": [
                {
                    "category": "logic",
                    "severity": "medium",
                    "location": "选中文本",
                    "originalText": "相关数据",
                    "problem": "指代不清。",
                    "suggestion": "补充数据范围。",
                    "suggestedRewrite": "业务数据",
                }
            ],
            "provider": "enterprise-dify-chat/task-file",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for document review tests")
class WordDocumentReviewerTests(unittest.TestCase):
    def test_document_review_sends_selected_text_and_returns_scope(self) -> None:
        request = parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "选中的段落内容。",
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "contract_acceptance",
                    "technicalReviewPrompt": "重点检查验收标准。",
                },
            }
        )
        provider = RecordingDocumentReviewProvider()

        result = WordDocumentReviewer(provider_client=provider).review(request, trace_id="trace-review")

        self.assertEqual(provider.calls[0]["text"], "选中的段落内容。")
        self.assertEqual(provider.calls[0]["documentType"], "contract_acceptance")
        self.assertEqual(provider.calls[0]["reviewPrompt"], "重点检查验收标准。")
        self.assertEqual(result["scope"], "selection")
        self.assertEqual(result["documentType"], "contract_acceptance")
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")
        self.assertEqual(result["issues"][0]["category"], "logic")

    def test_document_review_falls_back_to_paragraph_text(self) -> None:
        request = parse_word_request(
            {
                "documentId": "doc-review-paragraphs.docx",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "",
                    "paragraphs": [
                        {"index": 1, "text": "第一段。"},
                        {"index": 2, "text": "第二段。"},
                    ],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "test_outline",
                    "technicalReviewPrompt": "",
                },
            }
        )
        provider = RecordingDocumentReviewProvider()

        result = WordDocumentReviewer(provider_client=provider).review(request, trace_id="trace-review-doc")

        self.assertEqual(provider.calls[0]["text"], "第一段。\n第二段。")
        self.assertIn("测试", provider.calls[0]["reviewPrompt"])
        self.assertEqual(result["scope"], "document")
