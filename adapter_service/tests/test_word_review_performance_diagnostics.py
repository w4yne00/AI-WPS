import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.core.errors import AdapterError, ProviderTimeoutError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.provider_client import ProviderClient
from app.services.word.document_review_jobs import DocumentReviewJobStore
from app.services.word.document_reviewer import WordDocumentReviewer
from app.services.word.full_document_review import FullDocumentReviewService
from app.services.word.deterministic_format_review import DeterministicFormatReviewService
from app.services.word.format_reviewer import WordFormatReviewer


class WordReviewPerformanceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = LongTaskCoordinator()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_full_review = os.environ.get("AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW")
        os.environ["AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW"] = "1"
        self._old_history_dir = os.environ.get("AI_WPS_TASK_HISTORY_DIR")
        os.environ["AI_WPS_TASK_HISTORY_DIR"] = os.path.join(self.temp_dir.name, "history")

    def tearDown(self):
        self.temp_dir.cleanup()
        if self._old_history_dir is None:
            os.environ.pop("AI_WPS_TASK_HISTORY_DIR", None)
        else:
            os.environ["AI_WPS_TASK_HISTORY_DIR"] = self._old_history_dir
        if self._old_full_review is None:
            os.environ.pop("AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW", None)
        else:
            os.environ["AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW"] = self._old_full_review

    def test_limited_document_review_success_records_provider_metrics_and_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_document_review(text, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 120,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 450,
                    "parseMs": 15,
                })
            return {
                "summary": "审查通过",
                "issues": [],
                "provider": "direct-model",
            }

        fake_provider_client.document_review.side_effect = fake_document_review

        reviewer = WordDocumentReviewer(provider_client=fake_provider_client)
        store = DocumentReviewJobStore(reviewer=reviewer, coordinator=self.coordinator)

        req = WordDocumentRequest.parse_obj({
            "content": {"plain_text": "这是一个测试文档的正文内容。"},
            "selection_mode": "document",
            "options": {"technical_document_type": "technical_solution"},
            "clientJobId": "doc-review-perf-1",
        })

        res = store.start(req, trace_id="trace-doc-review-perf-1")
        self.assertEqual(res["jobId"], "doc-review-perf-1")

        completed = self.coordinator.wait("doc-review-perf-1")
        self.assertEqual(completed["status"], "completed")

        # 毫秒级总耗时与阶段耗时
        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseElapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)
        # 秒级兼容字段保留
        self.assertIn("elapsedSeconds", completed)
        self.assertIn("phaseElapsedSeconds", completed)
        self.assertIn("phaseDurations", completed)

        # 真实阶段记录（preparing, provider_processing, aggregating）
        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("aggregating", phase_durations_ms)

        # 阻塞调用不可伪造流式首包
        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 120)
        self.assertEqual(metrics.get("providerCompleteMs"), 450)
        self.assertEqual(metrics.get("parseMs"), 15)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")

        # 终态诊断
        diagnostics = self.coordinator.diagnostics()
        recent = diagnostics["recentTerminalJobs"][0]
        self.assertEqual(recent["jobId"], "doc-review-perf-1")
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "success")
        self.assertEqual(recent["errorCode"], "")

    def test_limited_document_review_timeout_records_real_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_timeout_review(text, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 200,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": None,
                    "parseMs": None,
                })
            raise ProviderTimeoutError("模型处理超过等待时限。")

        fake_provider_client.document_review.side_effect = fake_timeout_review

        reviewer = WordDocumentReviewer(provider_client=fake_provider_client)
        store = DocumentReviewJobStore(reviewer=reviewer, coordinator=self.coordinator)

        req = WordDocumentRequest.parse_obj({
            "content": {"plain_text": "这是一个超时的测试文档。"},
            "selection_mode": "document",
            "options": {"technical_document_type": "technical_solution"},
            "clientJobId": "doc-review-timeout-1",
        })

        store.start(req, trace_id="trace-timeout-1")
        completed = self.coordinator.wait("doc-review-timeout-1")
        self.assertEqual(completed["status"], "completed")

        # 普通限量文档审查 Provider 超时记录真实 outcome 与 errorCode
        self.assertEqual(completed["metrics"].get("providerOutcome"), "provider_timeout")
        self.assertIsNone(completed["metrics"].get("providerFirstVisibleMs"))

        diagnostics = self.coordinator.diagnostics()
        recent = diagnostics["recentTerminalJobs"][0]
        self.assertEqual(recent["jobId"], "doc-review-timeout-1")
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "provider_timeout")
        self.assertEqual(recent["errorCode"], "PROVIDER_TIMEOUT")

    def test_limited_document_review_adapter_error_records_real_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_error_review(text, trace_id, **kwargs):
            raise AdapterError("PROVIDER_UNREACHABLE", "无法访问模型后台。")

        fake_provider_client.document_review.side_effect = fake_error_review

        reviewer = WordDocumentReviewer(provider_client=fake_provider_client)
        store = DocumentReviewJobStore(reviewer=reviewer, coordinator=self.coordinator)

        req = WordDocumentRequest.parse_obj({
            "content": {"plain_text": "这是一个错误的测试文档。"},
            "selection_mode": "document",
            "options": {"technical_document_type": "technical_solution"},
            "clientJobId": "doc-review-error-1",
        })

        store.start(req, trace_id="trace-error-1")
        completed = self.coordinator.wait("doc-review-error-1")
        self.assertEqual(completed["status"], "completed")

        self.assertEqual(completed["metrics"].get("providerOutcome"), "provider_error")
        diagnostics = self.coordinator.diagnostics()
        recent = diagnostics["recentTerminalJobs"][0]
        self.assertEqual(recent["errorCode"], "PROVIDER_UNREACHABLE")
        self.assertEqual(recent.get("providerOutcome"), "provider_error")

    def test_workflow_format_semantics_publishes_blocking_provider_metrics(self):
        class ProgressRecorder:
            def __init__(self):
                self.attempts = []

            def record_provider_attempt(self, metrics):
                self.attempts.append(metrics)

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({
                    "data": {
                        "outputs": {
                            "result_json": {"schemaVersion": "format_semantics.v1"},
                        }
                    }
                }).encode("utf-8")

        recorder = ProgressRecorder()
        client = ProviderClient()
        task_auth = {
            "providerBaseUrl": "https://workflow.example.com/v1",
            "providerChatPath": "/chat-messages",
            "providerMode": "blocking",
            "apiKey": "test-key",
        }

        with patch(
            "app.services.provider_client.urllib_request.urlopen",
            return_value=FakeResponse(),
        ):
            client._post_workflow_format_semantics(
                "classify_role",
                "trace-workflow-format-perf",
                {"candidate_json": "{}"},
                task_auth,
                timeout_seconds=60,
                progress_callback=recorder,
            )

        self.assertEqual(len(recorder.attempts), 1)
        metrics = recorder.attempts[0]
        self.assertIsInstance(metrics.get("providerHeadersMs"), int)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertIsInstance(metrics.get("providerCompleteMs"), int)
        self.assertIsInstance(metrics.get("parseMs"), int)

    def test_workflow_format_semantics_timeout_publishes_partial_metrics(self):
        class ProgressRecorder:
            def __init__(self):
                self.attempts = []

            def record_provider_attempt(self, metrics):
                self.attempts.append(metrics)

        recorder = ProgressRecorder()
        client = ProviderClient()
        task_auth = {
            "providerBaseUrl": "https://workflow.example.com/v1",
            "providerChatPath": "/chat-messages",
            "providerMode": "blocking",
            "apiKey": "test-key",
        }

        with patch(
            "app.services.provider_client.urllib_request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with self.assertRaises(ProviderTimeoutError):
                client._post_workflow_format_semantics(
                    "classify_role",
                    "trace-workflow-format-timeout",
                    {"candidate_json": "{}"},
                    task_auth,
                    timeout_seconds=60,
                    progress_callback=recorder,
                )

        self.assertEqual(len(recorder.attempts), 1)
        metrics = recorder.attempts[0]
        self.assertIsNone(metrics.get("providerHeadersMs"))
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertIsNone(metrics.get("providerCompleteMs"))
        self.assertIsNone(metrics.get("parseMs"))

    def test_full_document_review_accumulates_chunk_and_aggregate_provider_metrics(self):
        service = FullDocumentReviewService(
            staging_root=Path(self.temp_dir.name) / "full-review",
            coordinator=self.coordinator,
        )
        service.enabled = True

        fake_provider_client = MagicMock()
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "maxOutputTokens": 4096,
            "maxOutputTokensExplicit": True,
            "contextWindowTokens": 32000,
            "contextWindowTokensExplicit": True,
        }

        def fake_chunk_call(*args, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 80,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 300,
                    "parseMs": 10,
                })
            import json
            return json.dumps(
                {
                    "schemaVersion": "word.document_review.full.chunk.v1",
                    "chunkId": "chunk-1",
                    "summary": "审查完成。",
                    "enumerationStatus": "complete",
                    "issues": [],
                },
                ensure_ascii=False,
            )

        fake_provider_client.full_document_review_chunk.side_effect = fake_chunk_call
        service.provider_client = fake_provider_client

        text = "测试正文"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        created = service.create_session({
            "documentId": "doc-perf-1",
            "documentType": "technical_solution",
            "reviewPrompt": "检查",
            "writingPolicyScene": "auto",
            "coverage": {"includedRegions": ["body"], "excludedRegions": []},
            "host": "wps",
            "documentSessionId": "sess-perf-1",
            "documentDisplayName": "测试文档.docx",
        })
        uploaded = service.upload_batch(
            created["sessionId"],
            0,
            {
                "uploadToken": created["uploadToken"],
                "blocks": [{
                    "blockId": "paragraph-1",
                    "blockType": "paragraph",
                    "paragraphIndex": 1,
                    "text": text,
                }],
                "characterCount": len(text),
                "contentSha256": digest,
                "batchId": "batch-1",
                "range": {"start": "paragraph-1", "end": "paragraph-1"},
                "editSequence": 1,
            },
        )
        commit_res = service.commit_snapshot(
            created["sessionId"],
            {
                "uploadToken": created["uploadToken"],
                "batchCount": 1,
                "reviewCharacterCount": len(text),
                "contentSha256": digest,
                "verificationSha256": digest,
                "structureSha256": uploaded["structureSha256"],
            },
        )

        job_res = service.start_job({
            "snapshotId": commit_res["snapshotId"],
            "snapshotToken": commit_res["snapshotToken"],
            "host": "wps",
            "documentSessionId": "sess-perf-1",
        }, trace_id="trace-full-perf-1")
        job_id = job_res["jobId"]

        completed = self.coordinator.wait(job_id, task_type="word.document_review.full")
        self.assertEqual(completed["status"], "completed")

        # 验证包含 chunking, provider_processing, parsing, aggregating 等阶段
        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("chunking", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)
        self.assertIn("aggregating", phase_durations_ms)

        # 验证 Provider metrics 累积且不伪造首包
        metrics = completed["metrics"]
        self.assertGreaterEqual(metrics.get("providerAttempts", 0), 1)
        self.assertEqual(metrics.get("providerHeadersMs"), 80)
        self.assertEqual(metrics.get("providerCompleteMs"), 300)
        self.assertEqual(metrics.get("parseMs"), 10)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")

    def test_format_review_records_phases_and_semantic_provider_metrics(self):
        fake_reviewer = MagicMock()
        fake_reviewer.snapshot_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_review(request, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback:
                progress_callback("extracting")
                progress_callback("provider_processing")
                if hasattr(progress_callback, "record_provider_attempt"):
                    progress_callback.record_provider_attempt({
                        "providerHeadersMs": 95,
                        "providerFirstVisibleMs": None,
                        "providerCompleteMs": 250,
                        "parseMs": 12,
                    })
                progress_callback("parsing")
            return {
                "summary": {
                    "totalIssues": 0,
                    "paragraphIssues": 0,
                    "tableIssues": 0,
                    "figureIssues": 0,
                    "pageSetupIssues": 0,
                    "aiAttempted": True,
                    "aiRequestErrorCount": 1,
                    "semanticStatus": "degraded",
                    "aiFallbackReason": "provider_request_failed",
                },
                "issues": [],
                "coverage": {},
                "duplicateGroupCount": 0,
            }

        fake_reviewer.review.side_effect = fake_review

        service = DeterministicFormatReviewService(
            staging_root=Path(self.temp_dir.name) / "format-review",
            coordinator=self.coordinator,
            reviewer=fake_reviewer,
        )
        service.enabled = True

        identity = {
            "documentIdSha256": "document-fingerprint",
            "hostDocumentId": "host-document-1",
        }
        session = service.create_snapshot(
            {
                "documentId": "format-review-contract.docx",
                "selectionMode": "document",
                "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                "formatFactSchemaVersion": "format_snapshot.v2",
                "documentIdentity": identity,
                "editSequence": "1",
            }
        )
        blocks = service._normalize_format_blocks(
            [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "paragraph",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "text": "正文内容",
                    "format": {
                        "styleName": "Normal",
                        "fontName": "楷体",
                        "fontSize": 14,
                        "alignment": "left",
                        "lineSpacing": 1.0,
                        "firstLineIndent": 0,
                        "dataStatus": "verified",
                    },
                }
            ]
        )
        metrics = service._format_metrics(blocks)
        service.upload_batch(
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
        committed = service.commit_snapshot(
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
        job_res = service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "fmt-job-perf-1",
            },
            trace_id="trace-fmt-1",
        )

        completed = self.coordinator.wait(job_res["jobId"], task_type="word.format_review.deterministic")
        self.assertEqual(completed["status"], "completed")

        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("extracting", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)
        self.assertIn("aggregating", phase_durations_ms)

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 95)
        self.assertEqual(metrics.get("providerCompleteMs"), 250)
        self.assertEqual(metrics.get("parseMs"), 12)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "provider_error")


if __name__ == "__main__":
    unittest.main()
