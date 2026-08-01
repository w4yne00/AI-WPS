import importlib.util
import json
import os
import threading
import time
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError, ProviderTimeoutError
    from app.core.models import WordDocumentRequest
    from app.services.writing_policy import (
        WritingPolicyMatchResult,
        WritingPolicyService,
        audit_document_review_writing_policy,
    )
    from app.services.writing_policy import service as writing_policy_service_module
    from app.services.writing_policy.store import WritingPolicyStore
    from app.services.provider_client import get_last_provider_debug, record_provider_debug, reset_provider_debug
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.word import document_reviewer as document_reviewer_module
    from app.services.word.document_review_jobs import DocumentReviewJobStore
    from app.services.word.document_reviewer import WordDocumentReviewer


PROJECT_WRITING_POLICY_DB = Path(__file__).resolve().parents[2] / "run" / "writing_policies.db"
_MISSING_ENV = object()


def database_signature(path):
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size)


@contextmanager
def isolated_default_writing_policy_database(test_case):
    project_signature = database_signature(PROJECT_WRITING_POLICY_DB)
    previous = os.environ.get("AI_WPS_WRITING_POLICY_DB", _MISSING_ENV)
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "writing_policies.db"
        writing_policy_service_module._reset_writing_policy_services()
        os.environ["AI_WPS_WRITING_POLICY_DB"] = str(db_path)
        try:
            yield db_path
        finally:
            writing_policy_service_module._reset_writing_policy_services()
            if previous is _MISSING_ENV:
                os.environ.pop("AI_WPS_WRITING_POLICY_DB", None)
            else:
                os.environ["AI_WPS_WRITING_POLICY_DB"] = previous
            test_case.assertEqual(
                database_signature(PROJECT_WRITING_POLICY_DB),
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
        writing_policy_block: str,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "traceId": trace_id,
                "documentType": document_type,
                "reviewPrompt": review_prompt,
                "writingPolicyBlock": writing_policy_block,
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


class PolicyAwareDocumentReviewProvider(RecordingDocumentReviewProvider):
    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        writing_policy_block: str,
    ) -> dict:
        result = super().document_review(
            text,
            trace_id,
            document_type,
            review_prompt,
            writing_policy_block,
        )
        result["summary"] = "发现 1 项术语问题。"
        result["issues"] = [
            {
                "category": "professional",
                "severity": "medium",
                "location": "第 1 段",
                "originalText": "秘钥",
                "problem": "术语写法不符合当前生效规范。",
                "suggestion": "统一使用“密钥”。",
                "suggestedRewrite": "密钥",
            }
        ]
        return result


class TimeoutDocumentReviewProvider:
    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        writing_policy_block: str,
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
        writing_policy_block: str,
    ) -> dict:
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {
            "summary": "后台任务完成。",
            "issues": [],
            "provider": "enterprise-dify-chat/task-file",
        }


class SnapshotDocumentReviewProvider:
    def __init__(self) -> None:
        self.current_auth = {
            "providerBaseUrl": "https://provider.invalid/v1",
            "providerChatPath": "/chat-messages",
            "workflowProfileId": "profile-a",
            "workflowProfileName": "档案 A",
            "apiKeyRef": "profile-a-key",
            "apiKey": "secret-a",
            "authSource": "task-file",
        }
        self.resolve_count = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def resolve_task_auth(self, task_type):
        self.resolve_count += 1
        return {**self.current_auth, "taskType": task_type}

    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str,
        review_prompt: str,
        writing_policy_block: str,
        task_auth=None,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "traceId": trace_id,
                "taskAuth": dict(task_auth or {}),
            }
        )
        if len(self.calls) == 1:
            self.started.set()
            self.release.wait(timeout=2)
        return {
            "summary": "后台任务完成。",
            "issues": [],
            "provider": "enterprise-dify-chat/task-file",
        }


class FailingAuthSnapshotDocumentReviewProvider(RecordingDocumentReviewProvider):
    def resolve_task_auth(self, task_type):
        raise OSError("cannot read /secret/provider_api_keys/key-file")


class FakeWritingPolicyService:
    def __init__(self, degraded=False):
        self.calls = []
        self.review_audit_calls = []
        self.usage = {
            "applied": not degraded,
            "degraded": degraded,
            "degradedReason": "写作规范服务暂时不可用，已跳过写作规范增强。" if degraded else "",
            "termMatchCount": 0 if degraded else 1,
            "styleRuleCount": 0,
            "truncatedCount": 0,
            "matchedItems": [] if degraded else [{"id": "t1", "type": "term", "name": "标准术语"}],
        }
        self.result = WritingPolicyMatchResult(
            "" if degraded else "写作规范（必须遵守）：\n- 使用标准术语。",
            self.usage,
            () if degraded else ("t1",),
            {
                "writingPolicyApplied": not degraded,
                "writingPolicyDegraded": degraded,
                "writingPolicyErrorCode": "writing_policy_io_error" if degraded else "",
                "writingPolicyTermCount": 0 if degraded else 1,
                "writingPolicyStyleCount": 0,
                "writingPolicyTruncatedCount": 0,
                "writingPolicyElapsedMs": 4,
                "writingPolicyItemIds": [] if degraded else ["t1"],
            },
        )

    def prepare(self, task_scope, source_parts, scene="auto"):
        self.calls.append((task_scope, list(source_parts), scene))
        return self.result

    def audit_document_review(self, _match_result, source_text):
        self.review_audit_calls.append(source_text)
        return {
            "enabled": True,
            "passed": True,
            "degraded": False,
            "degradedReason": "",
            "summary": "已完成文档审查规范检查",
            "needsReview": [],
            "expressionSuggestions": [],
        }


class EmptyWritingPolicyStore:
    def enabled_items(self, _task_scope, _scene_id=None):
        return [], []


class FailingDocumentReviewAuditWritingPolicyService(FakeWritingPolicyService):
    def audit_document_review(self, _match_result, _source_text):
        raise RuntimeError("review audit unavailable")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for document review tests")
class WordDocumentReviewerTests(unittest.TestCase):
    def _request(
        self,
        plain_text: str = "选中的段落内容。",
        writing_policy_scene: str = "auto",
    ):
        return parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "writingPolicyScene": writing_policy_scene,
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

    def test_document_review_job_resolves_default_writing_policy_inside_worker(self) -> None:
        provider = RecordingDocumentReviewProvider()
        writing_policy = FakeWritingPolicyService()
        caller_threads = []
        submitting_thread = threading.get_ident()

        def resolve_writing_policy_service():
            caller_threads.append(threading.get_ident())
            return writing_policy

        with patch.object(
            document_reviewer_module,
            "get_writing_policy_service",
            side_effect=resolve_writing_policy_service,
        ) as getter:
            reviewer = WordDocumentReviewer(provider)
            store = DocumentReviewJobStore(reviewer=reviewer)
            getter.assert_not_called()

            started = store.start(
                self._request(),
                trace_id="trace-review-lazy-writing_policy",
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
            provider.calls[0]["writingPolicyBlock"],
            writing_policy.result.prompt_block,
        )
        self.assertEqual(completed["result"]["writingPolicyUsage"], writing_policy.result.usage)

    def test_document_review_job_store_returns_running_then_completed(self) -> None:
        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                writing_policy_service=FakeWritingPolicyService(),
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
                writing_policy_service=FakeWritingPolicyService(),
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

    def test_document_review_job_freezes_input_and_auth_while_queued(self) -> None:
        provider = SnapshotDocumentReviewProvider()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                writing_policy_service=FakeWritingPolicyService(),
            ),
            coordinator=coordinator,
        )
        first_request = self._request("先运行的内容。")
        second_request = parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "clientJobId": "client-review-snapshot",
                "content": {
                    "plainText": "排队时的原始内容。",
                    "paragraphs": [],
                    "headings": [],
                },
                "options": {
                    "technicalDocumentType": "technical_solution",
                    "technicalReviewPrompt": "",
                },
            }
        )

        store.start(first_request, trace_id="trace-running-snapshot")
        self.assertTrue(provider.started.wait(timeout=1))
        provider.current_auth.update(
            workflowProfileId="profile-b",
            workflowProfileName="档案 B",
            apiKeyRef="profile-b-key",
            apiKey="secret-b",
        )
        queued = store.start(second_request, trace_id="trace-queued-snapshot")
        second_request.content.plain_text = "提交后修改的内容。"
        provider.current_auth.update(
            workflowProfileId="profile-c",
            workflowProfileName="档案 C",
            apiKeyRef="profile-c-key",
            apiKey="secret-c",
        )
        duplicate = store.start(second_request, trace_id="trace-duplicate-snapshot")

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["phase"], "queued")
        self.assertEqual(queued["queuePosition"], 1)
        self.assertTrue(queued["canCancel"])
        self.assertEqual(duplicate["traceId"], "trace-queued-snapshot")
        self.assertEqual(provider.resolve_count, 2)
        self.assertNotIn("secret-b", str(queued))

        provider.release.set()
        completed = None
        for _ in range(100):
            completed = store.get("client-review-snapshot")
            if completed and completed["status"] == "completed":
                break
            time.sleep(0.02)

        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(provider.calls[1]["text"], "排队时的原始内容。")
        self.assertEqual(provider.calls[1]["taskAuth"]["workflowProfileId"], "profile-b")
        self.assertEqual(provider.calls[1]["taskAuth"]["apiKey"], "secret-b")
        self.assertNotIn("secret-b", str(completed))

    def test_document_review_job_store_cancels_only_queued_jobs(self) -> None:
        provider = BlockingDocumentReviewProvider()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=1)
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                writing_policy_service=FakeWritingPolicyService(),
            ),
            coordinator=coordinator,
        )
        running = store.start(self._request("运行中。"), trace_id="trace-review-running")
        self.assertTrue(provider.started.wait(timeout=1))
        queued = store.start(self._request("排队中。"), trace_id="trace-review-queued")

        cancelled = store.cancel(queued["jobId"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(cancelled["canCancel"])
        with self.assertRaises(AdapterError) as raised:
            store.cancel(running["jobId"])
        self.assertEqual(raised.exception.code, "LONG_TASK_NOT_CANCELLABLE")
        provider.release.set()

    def test_document_review_auth_snapshot_failure_returns_sanitized_error(self) -> None:
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=FailingAuthSnapshotDocumentReviewProvider(),
                writing_policy_service=FakeWritingPolicyService(),
            ),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )

        with self.assertRaises(AdapterError) as raised:
            store.start(self._request(), trace_id="trace-auth-snapshot-failure")

        self.assertEqual(
            raised.exception.code, "DOCUMENT_REVIEW_AUTH_SNAPSHOT_FAILED"
        )
        self.assertNotIn("/secret", raised.exception.message)

    def test_document_review_sends_selected_text_and_returns_scope(self) -> None:
        request = parse_word_request(
            {
                "documentId": "doc-review.docx",
                "scene": "word",
                "selectionMode": "selection",
                "writingPolicyScene": "cybersecurity",
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
        writing_policy = FakeWritingPolicyService()

        result = WordDocumentReviewer(provider_client=provider, writing_policy_service=writing_policy).review(
            request,
            trace_id="trace-review",
        )

        self.assertEqual(
            writing_policy.calls,
            [
                (
                    "word.document_review",
                    ["选中的段落内容。", "contract_acceptance", "重点检查验收标准。"],
                    "cybersecurity",
                )
            ],
        )
        self.assertEqual(provider.calls[0]["text"], "选中的段落内容。")
        self.assertEqual(provider.calls[0]["documentType"], "contract_acceptance")
        self.assertEqual(provider.calls[0]["reviewPrompt"], "重点检查验收标准。")
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], writing_policy.result.prompt_block)
        self.assertEqual(result["scope"], "selection")
        self.assertEqual(result["documentType"], "contract_acceptance")
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")
        self.assertEqual(result["issues"][0]["category"], "logic")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)

    def test_document_review_merges_policy_findings_into_existing_issue_shape(self) -> None:
        provider = RecordingDocumentReviewProvider()
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordDocumentReviewer(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).review(
            self._request(
                "值得注意的是，等保测评发现秘钥配置不符合访问控制要求。",
                writing_policy_scene="cybersecurity",
            ),
            trace_id="trace-review-policy-findings",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertIn("[文体]", provider.calls[0]["writingPolicyBlock"])
        self.assertIn("通用去模板化规则", provider.calls[0]["writingPolicyBlock"])
        self.assertEqual(
            result["writingPolicyUsage"]["packNames"],
            ["G企技术写作基础", "技术文件文体", "网络安全术语"],
        )
        self.assertEqual(len(result["issues"]), 4)
        terminology_issue = next(
            issue
            for issue in result["issues"]
            if issue["category"] == "professional"
            and issue["originalText"] == "秘钥"
        )
        self.assertEqual(terminology_issue["location"], "写作规范检查")
        self.assertIn("标准写法", terminology_issue["problem"])
        self.assertIn("密钥", terminology_issue["suggestion"])
        template_issue = next(
            issue
            for issue in result["issues"]
            if issue["category"] == "expression"
            and issue["originalText"] == "值得注意的是"
        )
        self.assertEqual(template_issue["severity"], "low")
        self.assertTrue(template_issue["problem"])
        self.assertTrue(template_issue["suggestion"])
        self.assertIn("另发现 3 项写作规范问题", result["summary"])
        self.assertEqual(len(result["writingPolicyAudit"]["needsReview"]), 2)
        self.assertEqual(
            len(result["writingPolicyAudit"]["expressionSuggestions"]),
            1,
        )

    def test_document_review_policy_check_failure_preserves_model_result(self) -> None:
        provider = RecordingDocumentReviewProvider()
        writing_policy = FailingDocumentReviewAuditWritingPolicyService()

        result = WordDocumentReviewer(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).review(
            self._request(),
            trace_id="trace-review-policy-check-failure",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["category"], "logic")
        self.assertEqual(result["summary"], "发现 1 项问题。")
        self.assertTrue(result["writingPolicyAudit"]["degraded"])
        self.assertIn("规范检查暂时不可用", result["writingPolicyAudit"]["summary"])
        self.assertNotIn("模型后台连接失败", result["writingPolicyAudit"]["summary"])

    def test_document_review_does_not_flag_alias_inside_standard_term(self) -> None:
        provider = RecordingDocumentReviewProvider()
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordDocumentReviewer(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).review(
            self._request(
                "网络安全等级保护应核对访问控制配置。",
                writing_policy_scene="cybersecurity",
            ),
            trace_id="trace-review-standard-term",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["writingPolicyAudit"]["needsReview"], [])
        self.assertEqual(len(result["issues"]), 1)

    def test_document_review_duplicate_alias_keeps_first_finding_details(self) -> None:
        audit = audit_document_review_writing_policy(
            "等保要求需要核对。",
            [
                {
                    "preferredText": "网络安全等级保护",
                    "aliases": ["等保"],
                },
                {
                    "preferredText": "信息系统等级保护",
                    "aliases": ["等保"],
                },
            ],
        )

        self.assertEqual(len(audit["needsReview"]), 1)
        self.assertIn("网络安全等级保护", audit["needsReview"][0]["suggestion"])
        self.assertNotIn("信息系统等级保护", audit["needsReview"][0]["suggestion"])

    def test_document_review_deduplicates_model_and_local_policy_findings(self) -> None:
        provider = PolicyAwareDocumentReviewProvider()
        writing_policy = WritingPolicyService(store=EmptyWritingPolicyStore())

        result = WordDocumentReviewer(
            provider_client=provider,
            writing_policy_service=writing_policy,
        ).review(
            self._request(
                "访问控制使用秘钥。",
                writing_policy_scene="cybersecurity",
            ),
            trace_id="trace-review-policy-deduplication",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(result["writingPolicyAudit"]["needsReview"]), 1)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["location"], "第 1 段")
        self.assertEqual(result["summary"], "发现 1 项术语问题。")

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
        writing_policy = FakeWritingPolicyService()

        result = WordDocumentReviewer(provider_client=provider, writing_policy_service=writing_policy).review(
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
        writing_policy = FakeWritingPolicyService()
        result = WordDocumentReviewer(
            provider_client=TimeoutDocumentReviewProvider(),
            writing_policy_service=writing_policy,
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
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        debug = get_last_provider_debug()
        self.assertEqual(debug["stage"], "request")
        self.assertEqual(debug["provider"], "enterprise-dify-chat")
        self.assertEqual(debug["error"]["type"], "TimeoutError")
        self.assertTrue(debug["writingPolicyApplied"])

    def test_document_review_degraded_writing_policy_still_calls_provider(self) -> None:
        provider = RecordingDocumentReviewProvider()
        writing_policy = FakeWritingPolicyService(degraded=True)

        result = WordDocumentReviewer(provider, writing_policy_service=writing_policy).review(
            self._request(),
            trace_id="trace-review-degraded",
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["writingPolicyBlock"], "")
        self.assertEqual(result["writingPolicyUsage"], writing_policy.result.usage)
        self.assertTrue(result["writingPolicyUsage"]["degraded"])

    def test_document_review_defaults_to_bundled_base_writing_policy(self) -> None:
        provider = RecordingDocumentReviewProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            reviewer = WordDocumentReviewer(provider)
            self.assertFalse(db_path.exists())

            result = reviewer.review(
                self._request(),
                trace_id="trace-review-default",
            )

            self.assertTrue(db_path.exists())
        self.assertIn("[文体]", provider.calls[0]["writingPolicyBlock"])
        self.assertTrue(result["writingPolicyUsage"]["applied"])
        self.assertFalse(result["writingPolicyUsage"]["degraded"])
        self.assertEqual(result["writingPolicyUsage"]["termMatchCount"], 0)
        self.assertGreater(result["writingPolicyUsage"]["styleRuleCount"], 0)
        self.assertEqual(
            result["writingPolicyUsage"]["packNames"],
            ["G企技术写作基础", "技术文件文体"],
        )

    def test_document_review_applies_scoped_organization_rule_once(self) -> None:
        provider = RecordingDocumentReviewProvider()
        with isolated_default_writing_policy_database(self) as db_path:
            store = WritingPolicyStore(db_path)
            store.create_item(
                {
                    "type": "style",
                    "name": "审查验收证据",
                    "ruleText": "文档审查应核对验收结论是否给出证据依据。",
                    "positiveExample": "经测试记录核验，指标满足要求。",
                    "negativeExample": "项目整体情况良好。",
                    "contextKeywords": [],
                    "alwaysApply": True,
                    "priority": "high",
                    "taskTypes": ["word.document_review"],
                    "sceneIds": ["yangqi"],
                    "enabled": True,
                    "note": "组织规则端到端测试",
                }
            )
            for name, rule_text, task_types, scene_ids in (
                (
                    "编写专用排除规则",
                    "此规则只允许进入智能编写。",
                    ["word.smart_write"],
                    ["yangqi"],
                ),
                (
                    "党政审查场景排除规则",
                    "此规则只允许进入党政公文审查。",
                    ["word.document_review"],
                    ["official"],
                ),
            ):
                store.create_item(
                    {
                        "type": "anti_template",
                        "name": name,
                        "ruleText": rule_text,
                        "contextKeywords": [],
                        "alwaysApply": True,
                        "priority": "high",
                        "taskTypes": task_types,
                        "sceneIds": scene_ids,
                        "enabled": True,
                    }
                )

            result = WordDocumentReviewer(provider).review(
                self._request(writing_policy_scene="yangqi"),
                trace_id="trace-review-scoped-rule",
            )

        self.assertEqual(len(provider.calls), 1)
        self.assertIn(
            "文档审查应核对验收结论是否给出证据依据",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertNotIn(
            "此规则只允许进入智能编写",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertNotIn(
            "此规则只允许进入党政公文审查",
            provider.calls[0]["writingPolicyBlock"],
        )
        self.assertGreaterEqual(result["writingPolicyUsage"]["styleRuleCount"], 1)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for route contract tests")
    def test_fastapi_job_routes_cancel_queued_and_report_restart_interruption(self) -> None:
        from app.api import word as word_api
        from app.main import app
        from fastapi.testclient import TestClient

        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                writing_policy_service=FakeWritingPolicyService(),
            ),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )
        original_store = word_api.document_review_jobs
        word_api.document_review_jobs = store
        running_request = parse_word_request(
            {
                "clientJobId": "client-fastapi-running",
                "content": {"plainText": "运行中。"},
            }
        )
        queued_request = parse_word_request(
            {
                "clientJobId": "client-fastapi-queued",
                "content": {"plainText": "排队中。"},
            }
        )
        try:
            running = word_api.start_document_review_job(running_request)
            self.assertTrue(provider.started.wait(timeout=1))
            queued = word_api.start_document_review_job(queued_request)
            cancelled = word_api.cancel_document_review_job("client-fastapi-queued")
            interrupted_response = word_api.get_document_review_job(
                "client-from-before-adapter-restart", resume=True
            )
            missing_response = word_api.get_document_review_job("client-never-existed")
        finally:
            provider.release.set()
            word_api.document_review_jobs = original_store

        interrupted = json.loads(interrupted_response.body.decode("utf-8"))
        missing = json.loads(missing_response.body.decode("utf-8"))
        invalid_response = TestClient(app).post(
            "/word/document-review/jobs",
            json={"content": "invalid-content-shape"},
        )
        malformed_response = TestClient(app).post(
            "/word/document-review/jobs",
            content=b"{bad-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(running["data"]["status"], "running")
        self.assertEqual(queued["data"]["status"], "queued")
        self.assertEqual(queued["data"]["queuePosition"], 1)
        self.assertTrue(queued["data"]["canCancel"])
        self.assertEqual(cancelled["message"], "cancelled")
        self.assertEqual(cancelled["data"]["status"], "cancelled")
        self.assertEqual(interrupted_response.status_code, 404)
        self.assertEqual(
            interrupted["errors"][0]["code"],
            "DOCUMENT_REVIEW_JOB_INTERRUPTED",
        )
        self.assertEqual(interrupted["data"]["status"], "failed")
        self.assertIn("adapter 重启", interrupted["message"])
        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(
            missing["errors"][0]["code"], "DOCUMENT_REVIEW_JOB_NOT_FOUND"
        )
        self.assertEqual(missing["data"]["status"], "not_found")
        self.assertEqual(invalid_response.status_code, 422)
        self.assertEqual(
            invalid_response.json()["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )
        self.assertEqual(
            invalid_response.json()["taskType"], "word.document_review"
        )
        self.assertEqual(malformed_response.status_code, 422)
        self.assertEqual(
            malformed_response.json()["taskType"], "word.document_review"
        )
        self.assertEqual(
            malformed_response.json()["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )

    def test_standalone_job_routes_match_fastapi_cancel_and_error_contract(self) -> None:
        import standalone_adapter

        provider = BlockingDocumentReviewProvider()
        store = DocumentReviewJobStore(
            reviewer=WordDocumentReviewer(
                provider_client=provider,
                writing_policy_service=FakeWritingPolicyService(),
            ),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )
        original_store = standalone_adapter.DOCUMENT_REVIEW_JOB_STORE
        standalone_adapter.DOCUMENT_REVIEW_JOB_STORE = store

        def invoke_raw(method, path, raw):
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: captured.update(status=status, body=body)
            getattr(handler, method)()
            return captured

        def invoke(method, path, payload=None):
            raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            return invoke_raw(method, path, raw)

        try:
            running = invoke(
                "do_POST",
                "/word/document-review/jobs",
                {
                    "clientJobId": "client-standalone-running",
                    "content": {"plainText": "运行中。"},
                },
            )
            self.assertTrue(provider.started.wait(timeout=1))
            queued = invoke(
                "do_POST",
                "/word/document-review/jobs",
                {
                    "clientJobId": "client-standalone-queued",
                    "content": {"plainText": "排队中。"},
                },
            )
            cancelled = invoke(
                "do_DELETE",
                "/word/document-review/jobs/client-standalone-queued",
            )
            running_cancel = invoke(
                "do_DELETE",
                "/word/document-review/jobs/client-standalone-running",
            )
            interrupted = invoke(
                "do_GET",
                "/word/document-review/jobs/client-from-before-adapter-restart?resume=1",
            )
            missing = invoke(
                "do_GET",
                "/word/document-review/jobs/client-never-existed",
            )
            invalid = invoke(
                "do_POST",
                "/word/document-review/jobs",
                {"content": "invalid-content-shape"},
            )
            malformed = invoke_raw(
                "do_POST",
                "/word/document-review/jobs",
                b"{bad-json",
            )
        finally:
            provider.release.set()
            standalone_adapter.DOCUMENT_REVIEW_JOB_STORE = original_store

        self.assertEqual(running["status"], 200)
        self.assertEqual(running["body"]["data"]["status"], "running")
        self.assertEqual(queued["body"]["data"]["status"], "queued")
        self.assertEqual(cancelled["status"], 200)
        self.assertEqual(cancelled["body"]["message"], "cancelled")
        self.assertEqual(cancelled["body"]["data"]["status"], "cancelled")
        self.assertEqual(running_cancel["status"], 409)
        self.assertEqual(
            running_cancel["body"]["errors"][0]["code"],
            "LONG_TASK_NOT_CANCELLABLE",
        )
        self.assertEqual(interrupted["status"], 404)
        self.assertEqual(
            interrupted["body"]["errors"][0]["code"],
            "DOCUMENT_REVIEW_JOB_INTERRUPTED",
        )
        self.assertEqual(interrupted["body"]["data"]["status"], "failed")
        self.assertEqual(missing["status"], 404)
        self.assertEqual(
            missing["body"]["errors"][0]["code"],
            "DOCUMENT_REVIEW_JOB_NOT_FOUND",
        )
        self.assertEqual(invalid["status"], 422)
        self.assertEqual(invalid["body"]["taskType"], "word.document_review")
        self.assertEqual(
            invalid["body"]["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )
        self.assertEqual(malformed["status"], 422)
        self.assertEqual(malformed["body"]["taskType"], "word.document_review")
        self.assertEqual(
            malformed["body"]["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )
