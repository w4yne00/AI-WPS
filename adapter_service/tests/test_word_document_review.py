import importlib.util
import os
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import ProviderTimeoutError
    from app.core.models import WordDocumentRequest
    from app.services.enterprise_knowledge import KnowledgeMatchResult
    from app.services.enterprise_knowledge import service as knowledge_service_module
    from app.services.provider_client import get_last_provider_debug, record_provider_debug, reset_provider_debug
    from app.services.word import document_reviewer as document_reviewer_module
    from app.services.word.document_review_jobs import DocumentReviewJobStore
    from app.services.word.document_reviewer import WordDocumentReviewer


PROJECT_KNOWLEDGE_DB = Path(__file__).resolve().parents[2] / "run" / "enterprise_knowledge.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


@contextmanager
def isolated_default_knowledge_database(test_case):
    project_signature = database_signature(PROJECT_KNOWLEDGE_DB)
    previous = os.environ.get("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", _MISSING_ENV)
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "enterprise_knowledge.db"
        knowledge_service_module._reset_enterprise_knowledge_services()
        os.environ["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = str(db_path)
        try:
            yield db_path
        finally:
            knowledge_service_module._reset_enterprise_knowledge_services()
            if previous is _MISSING_ENV:
                os.environ.pop("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", None)
            else:
                os.environ["AI_WPS_ENTERPRISE_KNOWLEDGE_DB"] = previous
            test_case.assertEqual(
                database_signature(PROJECT_KNOWLEDGE_DB),
                project_signature,
            )


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingDocumentReviewProvider:
    def __init__(self) -> None:
        self.calls = []

    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        enterprise_knowledge_block: str,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "traceId": trace_id,
                "documentType": document_type,
                "reviewPrompt": review_prompt,
                "enterpriseKnowledgeBlock": enterprise_knowledge_block,
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
    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        enterprise_knowledge_block: str,
    ) -> dict:
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": "word.document_review",
                "stage": "request",
                "provider": "enterprise-dify-chat",
                "error": {"type": "TimeoutError", "message": "timed out"},
            }
        )
        raise ProviderTimeoutError("模型后台文档审查未按时返回。")


class BlockingDocumentReviewProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        enterprise_knowledge_block: str,
    ) -> dict:
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {
            "summary": "后台任务完成。",
            "issues": [],
            "provider": "enterprise-dify-chat/task-file",
        }


class FakeKnowledgeService:
    def __init__(self, degraded=False):
        self.calls = []
        self.usage = {
            "applied": not degraded,
            "degraded": degraded,
            "degradedReason": "企业知识服务暂时不可用，已跳过企业知识增强。" if degraded else "",
            "termMatchCount": 0 if degraded else 1,
            "styleRuleCount": 0,
            "truncatedCount": 0,
            "matchedItems": [] if degraded else [{"id": "t1", "type": "term", "name": "标准术语"}],
        }
        self.result = KnowledgeMatchResult(
            "" if degraded else "企业术语与写作规范（必须遵守）：\n- 使用标准术语。",
            self.usage,
            () if degraded else ("t1",),
            {
                "knowledgeApplied": not degraded,
                "knowledgeDegraded": degraded,
                "knowledgeErrorCode": "knowledge_io_error" if degraded else "",
                "knowledgeTermCount": 0 if degraded else 1,
                "knowledgeStyleCount": 0,
                "knowledgeTruncatedCount": 0,
                "knowledgeElapsedMs": 4,
                "knowledgeItemIds": [] if degraded else ["t1"],
            },
        )

    def prepare(self, task_scope, source_parts):
        self.calls.append((task_scope, list(source_parts)))
        return self.result


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

    def test_document_review_job_resolves_default_knowledge_inside_worker(self) -> None:
        provider = RecordingDocumentReviewProvider()
        knowledge = FakeKnowledgeService()
        caller_threads = []
        submitting_thread = threading.get_ident()

        def resolve_knowledge_service():
            caller_threads.append(threading.get_ident())
            return knowledge

        with patch.object(
            document_reviewer_module,
            "get_enterprise_knowledge_service",
            side_effect=resolve_knowledge_service,
        ) as getter:
            reviewer = WordDocumentReviewer(provider)
            store = DocumentReviewJobStore(reviewer=reviewer)
            getter.assert_not_called()

            started = store.start(
                self._request(),
                trace_id="trace-review-lazy-knowledge",
            )
            completed = started
            for _ in range(50):
                completed = store.get(started["jobId"])
                if completed and completed["status"] == "completed":
                    break
                time.sleep(0.02)

            getter.assert_called_once_with()

        self.assertEqual(len(caller_threads), 1)
        self.assertNotEqual(caller_threads[0], submitting_thread)
        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            provider.calls[0]["enterpriseKnowledgeBlock"],
            knowledge.result.prompt_block,
        )
        self.assertEqual(completed["result"]["knowledgeUsage"], knowledge.result.usage)

    def test_document_review_job_store_returns_running_then_completed(self) -> None:
        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                knowledge_service=FakeKnowledgeService(),
            )
        )

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
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                knowledge_service=FakeKnowledgeService(),
            )
        )
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
        knowledge = FakeKnowledgeService()

        result = WordDocumentReviewer(provider_client=provider, knowledge_service=knowledge).review(
            request,
            trace_id="trace-review",
        )

        self.assertEqual(
            knowledge.calls,
            [
                (
                    "word.document_review",
                    ["选中的段落内容。", "contract_acceptance", "重点检查验收标准。"],
                )
            ],
        )
        self.assertEqual(provider.calls[0]["text"], "选中的段落内容。")
        self.assertEqual(provider.calls[0]["documentType"], "contract_acceptance")
        self.assertEqual(provider.calls[0]["reviewPrompt"], "重点检查验收标准。")
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], knowledge.result.prompt_block)
        self.assertEqual(result["scope"], "selection")
        self.assertEqual(result["documentType"], "contract_acceptance")
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")
        self.assertEqual(result["issues"][0]["category"], "logic")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)

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
        knowledge = FakeKnowledgeService()

        result = WordDocumentReviewer(provider_client=provider, knowledge_service=knowledge).review(
            request,
            trace_id="trace-review-doc",
        )

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

        reset_provider_debug()
        knowledge = FakeKnowledgeService()
        result = WordDocumentReviewer(
            provider_client=TimeoutDocumentReviewProvider(),
            knowledge_service=knowledge,
        ).review(
            request,
            trace_id="trace-review-timeout",
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["parseFallbackReason"], "provider_timeout")
        self.assertIn("模型后台文档审查未按时返回", result["summary"])
        self.assertNotIn("Dify", result["summary"])
        self.assertIn("缩小审查范围", result["rawAnswer"])
        self.assertEqual(result["provider"], "enterprise-dify-chat/timeout")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "request")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["error"]["type"], "TimeoutError")
        self.assertTrue(debug["knowledgeApplied"])

    def test_document_review_degraded_knowledge_still_calls_provider(self) -> None:
        provider = RecordingDocumentReviewProvider()
        knowledge = FakeKnowledgeService(degraded=True)

        result = WordDocumentReviewer(provider, knowledge_service=knowledge).review(
            self._request(),
            trace_id="trace-review-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertEqual(result["knowledgeUsage"], knowledge.result.usage)
        self.assertTrue(result["knowledgeUsage"]["degraded"])

    def test_document_review_defaults_to_empty_enterprise_knowledge_service(self) -> None:
        provider = RecordingDocumentReviewProvider()
        with isolated_default_knowledge_database(self) as db_path:
            reviewer = WordDocumentReviewer(provider)
            self.assertFalse(db_path.exists())

            result = reviewer.review(
                self._request(),
                trace_id="trace-review-default",
            )

            self.assertTrue(db_path.exists())
        self.assertEqual(provider.calls[0]["enterpriseKnowledgeBlock"], "")
        self.assertTrue(result["knowledgeUsage"]["applied"])
        self.assertFalse(result["knowledgeUsage"]["degraded"])
        self.assertEqual(result["knowledgeUsage"]["termMatchCount"], 0)
        self.assertEqual(result["knowledgeUsage"]["matchedItems"], [])
