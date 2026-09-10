import sys
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    import pydantic
except ImportError:
    class _PydanticShim:
        class BaseModel:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
            @classmethod
            def parse_obj(cls, d):
                return cls(**d)
            def dict(self, *a, **k):
                return self.__dict__
            def copy(self, deep=True):
                from copy import deepcopy
                return deepcopy(self)
        @staticmethod
        def Field(*a, **k):
            default = k.get("default", None)
            if default is None and "default_factory" in k:
                return k["default_factory"]()
            return default
        StrictBool = bool
        StrictInt = int
        StrictStr = str
        @staticmethod
        def root_validator(*a, **k):
            return lambda fn: fn
        @staticmethod
        def validator(*a, **k):
            return lambda fn: fn

    pyd = types.ModuleType("pydantic")
    for attr in dir(_PydanticShim):
        if not attr.startswith("__"):
            setattr(pyd, attr, getattr(_PydanticShim, attr))
    sys.modules["pydantic"] = pyd

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryStore
from app.services.word.document_review_jobs import DocumentReviewJobStore
from app.services.word.full_document_review import FullDocumentReviewService


class MockDocumentReviewer:
    def __init__(self, oversize: bool = False) -> None:
        self.oversize = oversize

    def snapshot_task_auth(self):
        return {"serviceName": "测试审查服务", "modelName": "review-v1"}

    def review(self, request, trace_id="", task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("parsing")
        if self.oversize:
            return {
                "summary": "超大审查结果",
                "issues": [{"category": "professional", "severity": "high", "problem": "P"}],
                "oversizedData": "X" * (6 * 1024 * 1024),
                "rawAnswer": "...",
                "provider": "mock",
            }
        return {
            "documentType": getattr(getattr(request, "options", None), "technical_document_type", "contract"),
            "summary": "审查发现 2 项问题。",
            "issues": [
                {
                    "category": "professional",
                    "severity": "high",
                    "location": "正文第 1 段",
                    "originalText": "绝密原文内容1",
                    "problem": "术语不规范",
                    "suggestion": "建议修正",
                },
                {
                    "category": "expression",
                    "severity": "low",
                    "location": "正文第 2 段",
                    "originalText": "绝密原文内容2",
                    "problem": "表达欠通顺",
                    "suggestion": "调整语序",
                },
            ],
            "rawAnswer": "完整模型输出",
            "provider": "mock",
            "writingPolicyUsage": {"applied": True, "scene": "yangqi", "packNames": ["base"]},
            "writingPolicyAudit": {"enabled": True, "passed": True, "summary": "合规"},
        }


class WordReviewHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.history_dir = Path(self.tmp_dir.name) / "history"
        self.history_store = TaskHistoryStore(self.history_dir)
        self.history_patch = patch(
            "app.services.word.document_review_jobs.get_task_history_store",
            return_value=self.history_store,
        )
        self.full_history_patch = patch(
            "app.services.word.full_document_review.get_task_history_store",
            return_value=self.history_store,
        )
        self.history_patch.start()
        self.full_history_patch.start()

    def tearDown(self):
        self.history_patch.stop()
        self.full_history_patch.stop()
        self.tmp_dir.cleanup()

    def test_regular_document_review_records_minimal_summary_history(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = DocumentReviewJobStore(reviewer=MockDocumentReviewer(), coordinator=coordinator)
        req = WordDocumentRequest.parse_obj({
            "documentId": "合同初稿.docx",
            "documentDisplayName": "合同初稿.docx",
            "documentSessionId": "doc-session-1",
            "clientJobId": "client-review-job-001",
            "content": {
                "plainText": "绝密文档全文内容" * 10,
                "paragraphs": [{"index": 0, "text": "绝密段落文本"}],
            },
            "options": {"technicalDocumentType": "contract"},
        })

        res = store.run_sync(req, "trace-review-001")
        self.assertIn("summary", res)

        histories = self.history_store.list_history("word.document_review")
        self.assertEqual(len(histories), 1)
        entry = histories[0]
        self.assertEqual(entry["documentDisplayName"], "合同初稿.docx")
        self.assertEqual(entry["serviceName"], "测试审查服务")
        self.assertEqual(entry["modelName"], "review-v1")
        self.assertEqual(entry["jobId"], "client-review-job-001")

        result = entry["result"]
        self.assertEqual(result["reportType"], "document_review")
        self.assertEqual(result["issueCount"], 2)
        self.assertEqual(result["categoryCounts"].get("professional"), 1)
        self.assertEqual(result["categoryCounts"].get("expression"), 1)
        self.assertEqual(result["severityCounts"].get("high"), 1)
        self.assertEqual(result["severityCounts"].get("low"), 1)
        # Privacy: must NOT copy full text or raw content
        self.assertNotIn("plainText", result)
        self.assertNotIn("paragraphs", result)
        self.assertNotIn("rawAnswer", result)

    def test_regular_document_review_handles_oversize_history(self):
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        store = DocumentReviewJobStore(reviewer=MockDocumentReviewer(oversize=True), coordinator=coordinator)
        req = WordDocumentRequest.parse_obj({
            "documentId": "超大合同.docx",
            "documentDisplayName": "超大合同.docx",
            "documentSessionId": "doc-session-over",
            "clientJobId": "client-review-over-001",
            "content": {"plainText": "测试内容"},
        })

        res = store.run_sync(req, "trace-review-over")
        self.assertIn("summary", res)
        histories = self.history_store.list_history("word.document_review")
        self.assertEqual(len(histories), 0)
        self.assertIn("historyNotice", res)

    def test_full_document_review_records_dedicated_report_reference_history(self):
        service = FullDocumentReviewService(staging_root=Path(self.tmp_dir.name) / "staging")
        job_id = "full-review-job-777"
        snapshot = {
            "documentId": "技术白皮书.docx",
            "documentDisplayName": "技术白皮书.docx",
            "documentSessionId": "session-full-1",
            "reviewCharacterCount": 8500,
            "serviceName": "Word 全篇文档审查",
            "modelName": "review-direct-v1",
        }
        report = {
            "summary": "全篇审查发现 3 项问题",
            "issueCount": 3,
            "categoryCounts": {"professional": 2, "standard": 1},
            "severityCounts": {"high": 1, "medium": 2},
            "statusCounts": {"open": 3},
            "coverage": {"status": "complete", "reviewedCharacterCount": 8500},
            "enumerationStatus": "complete",
            "reportExpiresAt": time.time() + 86400,
            "issues": [
                {"issueId": "iss-1", "problem": "结构问题1", "originalText": "绝密分片正文1"},
                {"issueId": "iss-2", "problem": "结构问题2", "originalText": "绝密分片正文2"},
                {"issueId": "iss-3", "problem": "结构问题3", "originalText": "绝密分片正文3"},
            ],
            "chunks": [{"chunkId": "chunk-1", "text": "分片原文1"}],
        }

        service._record_history_on_report_saved(job_id, snapshot, report)

        histories = self.history_store.list_history("word.document_review")
        self.assertEqual(len(histories), 1)
        entry = histories[0]
        self.assertEqual(entry["documentDisplayName"], "技术白皮书.docx")
        self.assertEqual(entry["jobId"], job_id)

        result = entry["result"]
        self.assertEqual(result["reportType"], "full_document_review")
        self.assertEqual(result["reportId"], job_id)
        self.assertEqual(result["issueCount"], 3)
        self.assertEqual(result["categoryCounts"]["professional"], 2)
        # Privacy: must NOT copy full text or chunk inputs
        self.assertNotIn("chunks", result)
        self.assertNotIn("issues", result)

    def test_regular_document_review_rejects_duplicate_slot_task(self):
        coordinator = LongTaskCoordinator(max_running=2, max_queued=2)

        class SlowReviewer(MockDocumentReviewer):
            def review(self, request, trace_id="", task_auth=None, progress_callback=None):
                time.sleep(0.5)
                return super().review(request, trace_id, task_auth, progress_callback)

        store = DocumentReviewJobStore(reviewer=SlowReviewer(), coordinator=coordinator)
        req1 = WordDocumentRequest.parse_obj({
            "documentId": "并发文档.docx",
            "documentSessionId": "doc-session-busy",
            "clientJobId": "client-job-busy-1",
            "content": {"plainText": "测试内容1"},
        })
        req2 = WordDocumentRequest.parse_obj({
            "documentId": "并发文档.docx",
            "documentSessionId": "doc-session-busy",
            "clientJobId": "client-job-busy-2",
            "content": {"plainText": "测试内容2"},
        })

        job1 = store.start(req1, "trace-busy-1")
        self.assertIn(job1.get("status"), {"queued", "running"})

        with self.assertRaises(AdapterError) as ctx:
            store.start(req2, "trace-busy-2")
        self.assertEqual(ctx.exception.code, "WORD_DOCUMENT_REVIEW_TASK_BUSY")


if __name__ == "__main__":
    unittest.main()
