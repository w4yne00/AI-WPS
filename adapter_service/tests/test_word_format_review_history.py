import os
import sys
import threading
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
            @classmethod
            def model_validate(cls, d):
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
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryError, TaskHistoryStore
from app.services.word.deterministic_format_review import (
    DeterministicFormatReviewService,
)


class MockFormatReviewer:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.snapshot_calls = 0

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "serviceName": "格式审查模型服务",
            "modelName": "format-review-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-format-1",
            "modelConfigurationName": "格式审查配置",
        }

    def review(self, request, trace_id="", task_auth=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback("inspecting")
        if self.delay > 0:
            time.sleep(self.delay)
        return {
            "summary": {
                "scope": getattr(request, "selection_mode", "document"),
                "templateId": "technical-document-template-rules",
                "provider": "local",
                "semanticStatus": "not_needed",
                "executionStatus": "completed",
                "complianceStatus": "violations_found",
                "coverageStatus": "complete",
            },
            "issues": [
                {
                    "ruleId": "heading_hierarchy",
                    "category": "structure",
                    "severity": "warning",
                    "paragraphIndex": 1,
                    "message": "标题层级跳级",
                    "currentValue": 3,
                    "expectedValue": 2,
                    "status": "open",
                }
            ],
        }


class BlockingFormatReviewer:
    def __init__(self) -> None:
        self.started_event = threading.Event()
        self.release_event = threading.Event()
        self.snapshot_calls = 0

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "serviceName": "格式审查模型服务",
            "modelName": "format-review-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-format-1",
            "modelConfigurationName": "格式审查配置",
        }

    def review(self, request, trace_id="", task_auth=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback("inspecting")
        self.started_event.set()
        self.release_event.wait(timeout=5)
        return {
            "summary": {
                "scope": getattr(request, "selection_mode", "document"),
                "templateId": "technical-document-template-rules",
                "provider": "local",
                "semanticStatus": "not_needed",
                "executionStatus": "completed",
                "complianceStatus": "violations_found",
                "coverageStatus": "complete",
            },
            "issues": [],
        }


class ContinuationFormatReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot_task_auth(self):
        return {
            "serviceName": "格式审查模型服务",
            "modelName": "format-review-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-format-1",
            "modelConfigurationName": "格式审查配置",
        }

    def review(self, request, trace_id="", task_auth=None, progress_callback=None, semantic_state=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "_semanticComplete": False,
                "_semanticState": {"step": 1},
            }
        return {
            "_semanticComplete": True,
            "summary": {
                "scope": getattr(request, "selection_mode", "document"),
                "templateId": "technical-document-template-rules",
                "provider": "local",
                "semanticStatus": "completed",
                "executionStatus": "completed",
                "complianceStatus": "compliant",
                "coverageStatus": "complete",
            },
            "issues": [],
        }


class WordFormatReviewHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"
        self.temp_dir = TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.history_dir = self.temp_path / "history"
        self.staging_dir = self.temp_path / "staging"
        self.history_store = TaskHistoryStore(base_dir=self.history_dir)
        self.history_patch = patch(
            "app.services.word.deterministic_format_review.get_task_history_store",
            return_value=self.history_store,
        )
        self.history_patch.start()
        self.coordinator = LongTaskCoordinator(max_running=4, max_queued=8)
        self.reviewer = MockFormatReviewer()
        self.service = DeterministicFormatReviewService(
            staging_root=self.staging_dir,
            reviewer=self.reviewer,
            coordinator=self.coordinator,
        )

    def tearDown(self) -> None:
        self.history_patch.stop()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _create_and_commit_snapshot(
        self,
        doc_id: str = "test-doc.docx",
        doc_session_id: str = "session-1",
        doc_display_name: str = "测试文档.docx",
    ) -> dict:
        identity = {
            "documentIdSha256": "doc-sha-" + doc_id,
            "hostDocumentId": doc_id,
        }
        session = self.service.create_snapshot(
            {
                "documentId": doc_id,
                "selectionMode": "document",
                "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                "formatFactSchemaVersion": "format_snapshot.v2",
                "documentIdentity": identity,
                "editSequence": "1",
                "documentSessionId": doc_session_id,
                "documentDisplayName": doc_display_name,
                "host": "wps",
            }
        )
        blocks = self.service._normalize_format_blocks(
            [
                {
                    "blockId": "format-p-1",
                    "blockType": "heading",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "headingLevel": 3,
                    "text": "测试标题",
                    "format": {
                        "styleName": "Heading 3",
                        "fontName": "黑体",
                        "fontSize": 16,
                        "alignment": "left",
                        "lineSpacing": 1.0,
                        "firstLineIndent": 0,
                        "dataStatus": "verified",
                    },
                }
            ]
        )
        metrics = self.service._format_metrics(blocks)
        self.service.upload_batch(
            session["snapshotId"],
            0,
            {
                "uploadToken": session["uploadToken"],
                "batchId": "format-batch-0",
                "blocks": blocks,
                "editSequence": "1",
                **{key: metrics[key] for key in (
                    "characterCount", "contentSha256", "structureSha256", "formatSha256"
                )},
            },
        )
        verification = {
            "batchCount": 1,
            "blockCount": 1,
            "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "coverage": metrics["coverage"],
            "documentIdentity": identity,
            "editSequence": "1",
        }
        committed = self.service.commit_snapshot(
            session["snapshotId"],
            {
                "uploadToken": session["uploadToken"],
                **{key: verification[key] for key in (
                    "batchCount", "blockCount", "reviewCharacterCount",
                    "contentSha256", "structureSha256", "formatSha256", "coverage"
                )},
                "verification": verification,
            },
        )
        return committed

    def test_format_review_rejects_duplicate_slot_task(self) -> None:
        self.service.reviewer = MockFormatReviewer(delay=0.5)

        committed1 = self._create_and_commit_snapshot(
            doc_id="doc-1.docx", doc_session_id="session-A"
        )
        job1 = self.service.start_job(
            {
                "snapshotId": committed1["snapshotId"],
                "snapshotToken": committed1["snapshotToken"],
                "clientJobId": "client-job-format-1",
                "documentSessionId": "session-A",
                "documentDisplayName": "文档A.docx",
                "host": "wps",
            },
            "trace-1",
        )
        self.assertEqual(job1["status"], "running")

        committed2 = self._create_and_commit_snapshot(
            doc_id="doc-1.docx", doc_session_id="session-A"
        )
        with self.assertRaises(AdapterError) as cm:
            self.service.start_job(
                {
                    "snapshotId": committed2["snapshotId"],
                    "snapshotToken": committed2["snapshotToken"],
                    "clientJobId": "client-job-format-2",
                    "documentSessionId": "session-A",
                    "documentDisplayName": "文档A.docx",
                    "host": "wps",
                },
                "trace-2",
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_DOCUMENT_TASK_BUSY")

        committed3 = self._create_and_commit_snapshot(
            doc_id="doc-2.docx", doc_session_id="session-B"
        )
        job3 = self.service.start_job(
            {
                "snapshotId": committed3["snapshotId"],
                "snapshotToken": committed3["snapshotToken"],
                "clientJobId": "client-job-format-3",
                "documentSessionId": "session-B",
                "documentDisplayName": "文档B.docx",
                "host": "wps",
            },
            "trace-3",
        )
        self.assertIn(job3["status"], {"queued", "running", "completed"})

    def test_format_review_rejects_cross_session_job_id_reuse(self) -> None:
        self.service.reviewer = MockFormatReviewer(delay=0.5)

        committed1 = self._create_and_commit_snapshot(
            doc_id="doc-1.docx", doc_session_id="session-A"
        )
        self.service.start_job(
            {
                "snapshotId": committed1["snapshotId"],
                "snapshotToken": committed1["snapshotToken"],
                "clientJobId": "client-job-shared-id",
                "documentSessionId": "session-A",
                "documentDisplayName": "文档A.docx",
                "host": "wps",
            },
            "trace-1",
        )

        committed2 = self._create_and_commit_snapshot(
            doc_id="doc-2.docx", doc_session_id="session-B"
        )
        with self.assertRaises(AdapterError) as cm:
            self.service.start_job(
                {
                    "snapshotId": committed2["snapshotId"],
                    "snapshotToken": committed2["snapshotToken"],
                    "clientJobId": "client-job-shared-id",
                    "documentSessionId": "session-B",
                    "documentDisplayName": "文档B.docx",
                    "host": "wps",
                },
                "trace-2",
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_TASK_CONFLICT")

    def test_format_review_slot_released_on_cancel_queued(self) -> None:
        # Occupy running slots with dummy jobs so next format review task is queued
        dummy_events = [threading.Event() for _ in range(self.coordinator.max_running)]
        for i, ev in enumerate(dummy_events):
            self.coordinator.submit(
                job_id=f"dummy-running-job-{i}",
                trace_id=f"trace-dummy-{i}",
                task_type="other",
                runner=lambda snap, prog, e=ev: e.wait(timeout=5),
                snapshot={},
                failure_code="DUMMY_FAILED",
                failure_message="dummy failure",
            )

        committed = self._create_and_commit_snapshot(
            doc_id="doc-cancel-q.docx", doc_session_id="session-cancel-q"
        )
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-cancel-q1",
                "documentSessionId": "session-cancel-q",
                "documentDisplayName": "取消测试.docx",
                "host": "wps",
            },
            "trace-cancel-q",
        )
        self.assertEqual(job["status"], "queued")

        cancel_result = self.service.cancel_job(job["jobId"])
        self.assertIsNotNone(cancel_result)
        self.assertEqual(cancel_result["status"], "cancelled")

        # After queued cancellation, the slot is immediately released
        committed2 = self._create_and_commit_snapshot(
            doc_id="doc-cancel-q.docx", doc_session_id="session-cancel-q"
        )
        job2 = self.service.start_job(
            {
                "snapshotId": committed2["snapshotId"],
                "snapshotToken": committed2["snapshotToken"],
                "clientJobId": "client-job-cancel-q2",
                "documentSessionId": "session-cancel-q",
                "documentDisplayName": "取消测试.docx",
                "host": "wps",
            },
            "trace-cancel-q2",
        )
        self.assertEqual(job2["status"], "queued")
        for ev in dummy_events:
            ev.set()

    def test_format_review_running_cancel_retains_slot_until_runner_exits(self) -> None:
        reviewer = BlockingFormatReviewer()
        self.service.reviewer = reviewer

        committed = self._create_and_commit_snapshot(
            doc_id="doc-cancel-run.docx", doc_session_id="session-cancel-run"
        )
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-cancel-run1",
                "documentSessionId": "session-cancel-run",
                "documentDisplayName": "运行中取消.docx",
                "host": "wps",
            },
            "trace-cancel-run",
        )
        self.assertTrue(reviewer.started_event.wait(timeout=5))

        try:
            # Request cancel while runner is executing
            cancel_result = self.service.cancel_job(job["jobId"])
            self.assertIsNotNone(cancel_result)
            self.assertEqual(cancel_result["status"], "running")

            # Slot MUST still be occupied while runner is running
            committed2 = self._create_and_commit_snapshot(
                doc_id="doc-cancel-run.docx", doc_session_id="session-cancel-run"
            )
            with self.assertRaises(AdapterError) as cm:
                self.service.start_job(
                    {
                        "snapshotId": committed2["snapshotId"],
                        "snapshotToken": committed2["snapshotToken"],
                        "clientJobId": "client-job-cancel-run2",
                        "documentSessionId": "session-cancel-run",
                        "documentDisplayName": "运行中取消2.docx",
                        "host": "wps",
                    },
                    "trace-cancel-run-2",
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_DOCUMENT_TASK_BUSY")
        finally:
            reviewer.release_event.set()

        # Wait for runner to exit
        for _ in range(50):
            cur = self.service.get_job(job["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

        # Now slot must be released, allowing new submission
        committed3 = self._create_and_commit_snapshot(
            doc_id="doc-cancel-run.docx", doc_session_id="session-cancel-run"
        )
        job3 = self.service.start_job(
            {
                "snapshotId": committed3["snapshotId"],
                "snapshotToken": committed3["snapshotToken"],
                "clientJobId": "client-job-cancel-run3",
                "documentSessionId": "session-cancel-run",
                "documentDisplayName": "运行中取消3.docx",
                "host": "wps",
            },
            "trace-cancel-run-3",
        )
        self.assertIn(job3["status"], {"queued", "running", "completed"})
        for _ in range(50):
            cur = self.service.get_job(job3["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

    def test_format_review_snapshot_session_binding_missing_in_request(self) -> None:
        reviewer = BlockingFormatReviewer()
        self.service.reviewer = reviewer

        committed = self._create_and_commit_snapshot(
            doc_id="doc-bound.docx", doc_session_id="session-bound-1"
        )
        # Omit documentSessionId in request payload
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-missing-sess",
                "documentDisplayName": "缺失会话.docx",
            },
            "trace-missing",
        )
        self.assertTrue(reviewer.started_event.wait(timeout=5))

        try:
            # Another task with same session-bound-1 should be blocked by busy slot
            committed2 = self._create_and_commit_snapshot(
                doc_id="doc-bound.docx", doc_session_id="session-bound-1"
            )
            with self.assertRaises(AdapterError) as cm:
                self.service.start_job(
                    {
                        "snapshotId": committed2["snapshotId"],
                        "snapshotToken": committed2["snapshotToken"],
                        "clientJobId": "client-job-dup-sess",
                        "documentSessionId": "session-bound-1",
                    },
                    "trace-dup",
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_DOCUMENT_TASK_BUSY")
        finally:
            reviewer.release_event.set()
        for _ in range(50):
            cur = self.service.get_job(job["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

    def test_format_review_snapshot_session_binding_empty_in_request(self) -> None:
        reviewer = BlockingFormatReviewer()
        self.service.reviewer = reviewer

        committed = self._create_and_commit_snapshot(
            doc_id="doc-empty.docx", doc_session_id="session-empty-bound"
        )
        # Empty string documentSessionId in request payload
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-empty-sess",
                "documentSessionId": "",
                "documentDisplayName": "空会话.docx",
            },
            "trace-empty",
        )
        self.assertTrue(reviewer.started_event.wait(timeout=5))

        try:
            committed2 = self._create_and_commit_snapshot(
                doc_id="doc-empty.docx", doc_session_id="session-empty-bound"
            )
            with self.assertRaises(AdapterError) as cm:
                self.service.start_job(
                    {
                        "snapshotId": committed2["snapshotId"],
                        "snapshotToken": committed2["snapshotToken"],
                        "clientJobId": "client-job-dup-empty",
                        "documentSessionId": "session-empty-bound",
                    },
                    "trace-dup-empty",
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_DOCUMENT_TASK_BUSY")
        finally:
            reviewer.release_event.set()
        for _ in range(50):
            cur = self.service.get_job(job["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

    def test_format_review_snapshot_session_binding_matching_in_request(self) -> None:
        committed = self._create_and_commit_snapshot(
            doc_id="doc-match.docx", doc_session_id="session-match"
        )
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-match",
                "documentSessionId": "session-match",
                "host": "wps",
            },
            "trace-match",
        )
        self.assertIn(job["status"], {"queued", "running", "completed"})

    def test_format_review_snapshot_session_binding_conflict_in_request(self) -> None:
        committed = self._create_and_commit_snapshot(
            doc_id="doc-conflict.docx", doc_session_id="session-original"
        )
        with self.assertRaises(AdapterError) as cm:
            self.service.start_job(
                {
                    "snapshotId": committed["snapshotId"],
                    "snapshotToken": committed["snapshotToken"],
                    "clientJobId": "client-job-conflict",
                    "documentSessionId": "session-tampered",
                },
                "trace-conflict",
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_TASK_CONFLICT")

    def test_format_review_snapshot_host_conflict_in_request(self) -> None:
        committed = self._create_and_commit_snapshot(
            doc_id="doc-host-conflict.docx", doc_session_id="session-host-test"
        )
        with self.assertRaises(AdapterError) as cm:
            self.service.start_job(
                {
                    "snapshotId": committed["snapshotId"],
                    "snapshotToken": committed["snapshotToken"],
                    "clientJobId": "client-job-host-conflict",
                    "host": "word",
                },
                "trace-host-conflict",
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_TASK_CONFLICT")

    def test_format_review_empty_snapshot_session_defaults_to_document_id(self) -> None:
        reviewer = BlockingFormatReviewer()
        self.service.reviewer = reviewer

        # Snapshot created with empty documentSessionId
        committed = self._create_and_commit_snapshot(
            doc_id="doc-fallback.docx", doc_session_id=""
        )

        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-fb-slot",
            },
            "trace-fb",
        )
        self.assertTrue(reviewer.started_event.wait(timeout=5))

        try:
            # Second job submitted with documentId as documentSessionId should hit 409 BUSY
            committed2 = self._create_and_commit_snapshot(
                doc_id="doc-fallback.docx", doc_session_id="doc-fallback.docx"
            )
            with self.assertRaises(AdapterError) as cm:
                self.service.start_job(
                    {
                        "snapshotId": committed2["snapshotId"],
                        "snapshotToken": committed2["snapshotToken"],
                        "clientJobId": "client-job-fb-slot2",
                        "documentSessionId": "doc-fallback.docx",
                    },
                    "trace-fb2",
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.code, "WORD_FORMAT_REVIEW_DOCUMENT_TASK_BUSY")
        finally:
            reviewer.release_event.set()
        for _ in range(50):
            cur = self.service.get_job(job["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

    def test_format_review_continuation_retains_slot_until_terminal_completion(self) -> None:
        reviewer = ContinuationFormatReviewer()
        self.service.reviewer = reviewer

        committed = self._create_and_commit_snapshot(
            doc_id="doc-continuation.docx", doc_session_id="session-cont"
        )
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "client-job-cont-1",
                "documentSessionId": "session-cont",
                "host": "wps",
            },
            "trace-cont",
        )

        # Wait for first slice to return continuation and complete second slice
        for _ in range(50):
            cur = self.service.get_job(job["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)

        self.assertEqual(cur["status"], "completed")
        self.assertEqual(reviewer.calls, 2)

        # After final completion, slot is released so a new task can submit
        committed2 = self._create_and_commit_snapshot(
            doc_id="doc-continuation.docx", doc_session_id="session-cont"
        )
        job2 = self.service.start_job(
            {
                "snapshotId": committed2["snapshotId"],
                "snapshotToken": committed2["snapshotToken"],
                "clientJobId": "client-job-cont-2",
                "documentSessionId": "session-cont",
                "host": "wps",
            },
            "trace-cont-2",
        )
        self.assertIn(job2["status"], {"queued", "running", "completed"})
        for _ in range(50):
            cur = self.service.get_job(job2["jobId"])
            if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)

    def test_format_review_records_minimal_summary_history(self) -> None:
        with patch(
            "app.services.word.deterministic_format_review.get_task_history_store",
            return_value=self.history_store,
        ):
            committed = self._create_and_commit_snapshot(
                doc_id="doc-hist.docx",
                doc_session_id="session-hist",
                doc_display_name="终稿合同.docx",
            )
            job = self.service.start_job(
                {
                    "snapshotId": committed["snapshotId"],
                    "snapshotToken": committed["snapshotToken"],
                    "clientJobId": "client-job-hist-1",
                    "documentSessionId": "session-hist",
                    "documentDisplayName": "终稿合同.docx",
                    "host": "wps",
                },
                "trace-hist",
            )

            for _ in range(50):
                cur = self.service.get_job(job["jobId"])
                if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.02)

            self.assertEqual(cur["status"], "completed")

            history_items = self.history_store.list_history("word.format_review")
            self.assertEqual(len(history_items), 1)

            entry = history_items[0]
            self.assertEqual(entry["taskType"], "word.format_review")
            self.assertEqual(entry["jobId"], job["jobId"])
            self.assertEqual(entry["documentDisplayName"], "终稿合同.docx")
            self.assertEqual(entry["serviceName"], "格式审查模型服务")
            self.assertEqual(entry["modelName"], "format-review-model-v1")

            result = entry["result"]
            self.assertEqual(result["reportType"], "format_review")
            self.assertEqual(result["reportId"], job["jobId"])
            self.assertEqual(result["issueCount"], 1)
            self.assertIn("categoryCounts", result)
            self.assertIn("severityCounts", result)
            self.assertIn("statusCounts", result)
            self.assertIn("reportExpiresAt", result)

            self.assertNotIn("formatBlocks", result)
            self.assertNotIn("formatFacts", result)
            self.assertNotIn("issues", result)
            self.assertNotIn("imageAssets", result)
            self.assertNotIn("plainText", result)
            self.assertNotIn("rawText", result)
            self.assertNotIn("apiKey", str(result))

    def test_format_review_handles_oversize_history(self) -> None:
        with patch.object(
            self.history_store,
            "record_success",
            side_effect=TaskHistoryError("HISTORY_ENTRY_TOO_LARGE", "Entry too large"),
        ), patch(
            "app.services.word.deterministic_format_review.get_task_history_store",
            return_value=self.history_store,
        ):
            committed = self._create_and_commit_snapshot(
                doc_id="doc-oversize.docx",
                doc_session_id="session-oversize",
                doc_display_name="超大格式文档.docx",
            )
            job = self.service.start_job(
                {
                    "snapshotId": committed["snapshotId"],
                    "snapshotToken": committed["snapshotToken"],
                    "clientJobId": "client-job-oversize-1",
                    "documentSessionId": "session-oversize",
                    "documentDisplayName": "超大格式文档.docx",
                    "host": "wps",
                },
                "trace-oversize",
            )

            for _ in range(50):
                cur = self.service.get_job(job["jobId"])
                if cur and cur.get("status") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.02)

            self.assertEqual(cur["status"], "completed")


if __name__ == "__main__":
    unittest.main()
