import importlib.util
import threading
import time
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import ProviderTimeoutError
    from app.core.models import WordDocumentRequest
    from app.services.word.document_review_jobs import DocumentReviewJobStore
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


class TimeoutDocumentReviewProvider:
    def document_review(self, text: str, trace_id: str, document_type: str, review_prompt: str) -> dict:
        raise ProviderTimeoutError("模型后台文档审查未按时返回。")


class BlockingDocumentReviewProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def document_review(self, text: str, trace_id: str, document_type: str, review_prompt: str) -> dict:
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {
            "summary": "后台任务完成。",
            "issues": [],
            "provider": "enterprise-dify-chat/task-file",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for document review tests")
class WordDocumentReviewerTests(unittest.TestCase):
    def _request(self, plain_text: str = "选中的段落内容。"):
        return parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": plain_text,
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "contract_acceptance",
                    "technicalReviewPrompt": "重点检查验收标准。",
                },
            }
        )

    def test_document_review_job_store_returns_running_then_completed(self) -> None:
        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(reviewer=WordDocumentReviewer(provider_client=provider))

        started = store.start(self._request(), trace_id="trace-review-job")

        self.assertEqual(started["jobId"], "trace-review-job")
        self.assertEqual(started["status"], "running")
        self.assertTrue(provider.started.wait(timeout=1))
        self.assertEqual(store.get("trace-review-job")["status"], "running")

        provider.release.set()
        completed = None
        for _ in range(50):
            completed = store.get("trace-review-job")
            if completed and completed["status"] == "completed":
                break
            time.sleep(0.02)

        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["summary"], "后台任务完成。")

    def test_document_review_job_store_uses_client_job_id_idempotently_and_reports_running_diagnostics(self) -> None:
        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(reviewer=WordDocumentReviewer(provider_client=provider))
        request = parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "clientJobId": "client-review-180s-recovery",
                "content": {
                    "plainText": "需要长时间审查的选中文本。",
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "technical_solution",
                    "technicalReviewPrompt": "",
                },
            }
        )

        started = store.start(request, trace_id="trace-server-first")
        duplicate = store.start(request, trace_id="trace-server-second")

        self.assertEqual(started["jobId"], "client-review-180s-recovery")
        self.assertEqual(started["traceId"], "trace-server-first")
        self.assertEqual(duplicate["jobId"], "client-review-180s-recovery")
        self.assertEqual(duplicate["traceId"], "trace-server-first")
        self.assertEqual(duplicate["status"], "running")
        self.assertIn("elapsedSeconds", duplicate)
        self.assertIn("heartbeatAgeSeconds", duplicate)
        self.assertEqual(duplicate["providerTimeoutSeconds"], 1800)
        self.assertIn("模型后台", duplicate["runningMessage"])
        self.assertTrue(provider.started.wait(timeout=1))
        self.assertEqual(provider.call_count, 1)

        provider.release.set()

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

    def test_document_review_returns_readable_fallback_when_provider_times_out(self) -> None:
        request = parse_word_request(
            {
                "documentId": "doc-review-timeout.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "需要审查的选中文本。",
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "technical_solution",
                    "technicalReviewPrompt": "",
                },
            }
        )

        result = WordDocumentReviewer(provider_client=TimeoutDocumentReviewProvider()).review(
            request,
            trace_id="trace-review-timeout",
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["parseFallbackReason"], "provider_timeout")
        self.assertIn("模型后台文档审查未按时返回", result["summary"])
        self.assertNotIn("Dify", result["summary"])
        self.assertIn("缩小审查范围", result["rawAnswer"])
        self.assertEqual(result["provider"], "enterprise-dify-chat/timeout")
