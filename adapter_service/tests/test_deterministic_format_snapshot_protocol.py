import hashlib
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.errors import AdapterError
from app.core.models import WordDocumentRequest
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import (
    DeterministicFormatReviewService,
)
from app.services.word.format_reviewer import WordFormatReviewer
import app.services.word.deterministic_format_review as format_protocol


class _Reviewer:
    def __init__(self):
        self.requests = []

    def review(self, request, trace_id=""):
        self.requests.append(request)
        return {"issues": [], "summary": {}}


class _IssueReviewer:
    def review(self, request, trace_id=""):
        return {
            "issues": [
                {
                    "ruleId": "font_size",
                    "paragraphIndex": 1,
                    "role": "body",
                    "message": "字号不符合模板要求。",
                    "currentValue": "14pt",
                    "expectedValue": "12pt",
                    "suggestion": "建议调整字号。",
                },
                {
                    "ruleId": "font_size",
                    "paragraphIndex": 2,
                    "role": "body",
                    "message": "字号不符合模板要求。",
                    "currentValue": "14pt",
                    "expectedValue": "12pt",
                    "suggestion": "建议调整字号。",
                },
            ],
            "summary": {
                "provider": "local",
                "templateId": "technical-file-format-requirements",
                "modelConfigurationName": "格式审查主配置",
                "modelConfigurationId": "config-format-1",
                "modelConfigurationVersion": 7,
                "accessMethod": "direct_model",
                "semanticStatus": "degraded",
                "aiCandidateCount": 2,
                "aiAttempted": True,
                "aiCallCount": 1,
                "aiAcceptedCount": 0,
                "aiFallbackReason": "format_semantic_zero_accepted",
            },
        }


class DeterministicFormatSnapshotProtocolTests(unittest.TestCase):
    def setUp(self):
        self.previous_flag = os.environ.get(
            "AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"
        )
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.reviewer = _Reviewer()
        self.service = DeterministicFormatReviewService(
            staging_root=Path(self.temp_dir.name),
            reviewer=self.reviewer,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )

    def tearDown(self):
        if self.previous_flag is None:
            os.environ.pop("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None)
        else:
            os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = self.previous_flag
        self.temp_dir.cleanup()

    @staticmethod
    def _blocks(text="选区内正文"):
        return [
            {
                "blockId": "format-paragraph-1",
                "blockType": "paragraph",
                "scope": "in_scope",
                "paragraphIndex": 1,
                "text": text,
                "format": {
                    "styleName": "Normal",
                    "fontName": "宋体",
                    "fontSize": 12,
                    "dataStatus": "verified",
                },
            },
            {
                "blockId": "format-context-2",
                "blockType": "context",
                "scope": "context",
                "paragraphIndex": 2,
                "text": "范围外上下文",
                "format": {"dataStatus": "context_only"},
            },
        ]

    def _session(self):
        return self.service.create_snapshot(
            {
                "documentId": "protocol.docx",
                "selectionMode": "selection",
                "documentIdentity": {
                    "documentIdSha256": "document-fingerprint",
                    "hostDocumentId": "host-document-1",
                },
                "editSequence": "5",
                "scope": {
                    "mode": "selection",
                    "expandedToSemanticUnits": True,
                    "contextOnly": ["format-context-2"],
                },
                "pageSetup": {
                    "paperSize": "A4",
                    "marginTop": 72,
                    "marginBottom": 72,
                    "marginLeft": 90,
                    "marginRight": 90,
                },
            }
        )

    def _upload(self, session, blocks=None, edit_sequence="5"):
        normalized = self.service._normalize_format_blocks(blocks or self._blocks())
        metrics = self.service._format_metrics(normalized)
        payload = {
            "uploadToken": session["uploadToken"],
            "batchId": "format-batch-0",
            "blocks": normalized,
            "editSequence": edit_sequence,
        }
        payload.update({key: metrics[key] for key in (
            "characterCount", "contentSha256", "structureSha256", "formatSha256"
        )})
        return self.service.upload_batch(session["snapshotId"], 0, payload), metrics

    def _commit(self, session, metrics, verification=None):
        expected_verification = verification or {
            "batchCount": 1,
            "blockCount": 2,
            "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "coverage": metrics["coverage"],
            "documentIdentity": {
                "documentIdSha256": "document-fingerprint",
                "hostDocumentId": "host-document-1",
            },
            "editSequence": "5",
        }
        return self.service.commit_snapshot(
            session["snapshotId"],
            {
                "uploadToken": session["uploadToken"],
                "batchCount": 1,
                "blockCount": 2,
                "reviewCharacterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": metrics["structureSha256"],
                "formatSha256": metrics["formatSha256"],
                "coverage": metrics["coverage"],
                "verification": expected_verification,
            },
        )

    def test_selection_context_is_stored_but_not_reviewed(self):
        session = self._session()
        uploaded, metrics = self._upload(session)
        self.assertEqual(uploaded["coverage"]["inScopeBlockCount"], 1)
        self.assertEqual(uploaded["coverage"]["contextBlockCount"], 1)
        committed = self._commit(session, metrics)
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "format-protocol-job-1",
            },
            "format-trace-1",
        )
        for _ in range(50):
            current = self.service.get_job(job["jobId"])
            if current["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        self.assertEqual(current["status"], "completed")
        self.assertEqual(len(self.reviewer.requests), 1)
        self.assertEqual(
            [paragraph.text for paragraph in self.reviewer.requests[0].content.paragraphs],
            ["选区内正文"],
        )
        self.assertEqual(
            self.reviewer.requests[0].content.document_structure["page_setup"]["paperSize"],
            "A4",
        )
        self.assertFalse(self.service.snapshot_path(session["snapshotId"]).exists())

    def test_completed_report_has_stable_instances_pagination_groups_and_exports(self):
        self.service.reviewer = _IssueReviewer()
        session = self._session()
        blocks = self._blocks()
        blocks[0]["text"] = "第一段正文"
        blocks[1]["text"] = "第二段正文"
        _, metrics = self._upload(session, blocks=blocks)
        committed = self._commit(session, metrics)
        job = self.service.start_job(
            {
                "snapshotId": committed["snapshotId"],
                "snapshotToken": committed["snapshotToken"],
                "clientJobId": "format-report-contract-job",
            },
            "format-report-trace",
        )
        for _ in range(50):
            current = self.service.get_job(job["jobId"])
            if current["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        self.assertEqual(current["status"], "completed")

        report = self.service.get_report(job["jobId"])
        self.assertEqual(report["summary"]["executionStatus"], "completed")
        self.assertEqual(report["summary"]["complianceStatus"], "violations_found")
        self.assertEqual(report["issueCount"], 2)
        self.assertNotIn("issues", report)
        page = self.service.list_issues(job["jobId"], page_size=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["page"], 1)
        self.assertTrue(page["nextCursor"])
        issue = page["items"][0]
        self.assertTrue(issue["issueId"])
        self.assertTrue(issue["anchorId"])
        self.assertEqual(issue["propertyPath"], "format.fontSize")
        self.assertEqual(issue["duplicateGroupSize"], 2)
        self.assertEqual(len(page["duplicateGroups"]), 1)
        filtered = self.service.list_issues(job["jobId"], rule_id="font_size")
        self.assertEqual(filtered["total"], 2)
        markdown = self.service.export_report(job["jobId"], "markdown")
        self.assertIn("# 格式审查报告", markdown)
        self.assertIn(issue["issueId"], markdown)
        self.assertIn("模型配置：格式审查主配置", markdown)
        self.assertIn("模型调用事实：已尝试，候选 2、调用 1、接受 0", markdown)
        self.assertIn("语义增强降级原因：模型已调用但没有接受任何结果", markdown)

    def test_heading_hierarchy_report_deduplicates_and_exports_verified_location(self):
        blocks = [
            {
                "blockId": "format-paragraph-1",
                "blockType": "heading",
                "scope": "in_scope",
                "paragraphIndex": 1,
                "headingLevel": 1,
                "text": "一级标题",
                "format": {"outlineLevel": 1},
            },
            {
                "blockId": "format-paragraph-2",
                "blockType": "heading",
                "scope": "in_scope",
                "paragraphIndex": 2,
                "headingLevel": 3,
                "text": "三级标题",
                "format": {"outlineLevel": 3},
            },
        ]
        metrics = self.service._format_metrics(blocks)
        request_data = self.service._request_from_blocks(
            {"selectionMode": "document", "templateId": "technical-file-format-requirements"},
            blocks,
            metrics,
        )
        request = (
            WordDocumentRequest.model_validate(request_data)
            if hasattr(WordDocumentRequest, "model_validate")
            else WordDocumentRequest.parse_obj(request_data)
        )
        snapshot = {
            "request": request,
            "contentSha256": "content-hierarchy",
            "structureSha256": "structure-hierarchy",
            "formatSha256": "format-hierarchy",
        }
        sync_result = WordFormatReviewer().review(request, trace_id="")
        issue = next(
            item for item in sync_result["issues"]
            if item["ruleId"] == "structure.heading_hierarchy"
        )

        report = self.service._build_report({"issues": [issue, dict(issue)], "summary": {}}, snapshot)

        self.assertEqual(report["issueCount"], 1)
        exported_issue = report["issues"][0]
        self.assertEqual(exported_issue["paragraphIndex"], 2)
        self.assertEqual(exported_issue["role"], "heading")
        self.assertEqual(exported_issue["anchorId"], "format-paragraph-2")
        self.assertEqual(exported_issue["anchorVerification"], "verified")
        self.assertEqual(exported_issue["currentLevel"], 3)
        self.assertEqual(exported_issue["previousLevel"], 1)
        markdown = self.service._build_report({"issues": [issue], "summary": {}}, snapshot)
        self.service._save_report("heading-export-job", markdown)
        exported_markdown = self.service.export_report("heading-export-job", "markdown")
        self.assertIn("位置：P2", exported_markdown)
        self.assertIn("角色：标题", exported_markdown)
        self.assertIn("前一有效标题级别：1", exported_markdown)
        self.assertNotIn("P0", exported_markdown)
        self.assertNotIn("未识别角色", exported_markdown)

    def test_report_expiry_and_anchor_verification_are_public_lifecycle(self):
        now = [1000.0]
        service = DeterministicFormatReviewService(
            staging_root=Path(self.temp_dir.name),
            reviewer=_IssueReviewer(),
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
            wall_clock=lambda: now[0],
        )
        session = service.create_snapshot({
            "documentId": "lifecycle.docx", "selectionMode": "document",
            "documentIdentity": {"documentIdSha256": hashlib.sha256(b"lifecycle.docx").hexdigest()},
        })
        blocks = service._normalize_format_blocks([{
            "blockId": "format-paragraph-1", "blockType": "paragraph",
            "scope": "in_scope", "paragraphIndex": 1, "text": "正文",
            "format": {"styleName": "Normal", "dataStatus": "verified"},
        }])
        metrics = service._format_metrics(blocks)
        upload = service.upload_batch(session["snapshotId"], 0, {
            "uploadToken": session["uploadToken"], "batchId": "format-life-batch",
            "blocks": blocks, "editSequence": None,
            **{key: metrics[key] for key in ("characterCount", "contentSha256", "structureSha256", "formatSha256")},
        })
        self.assertEqual(upload["status"], "uploaded")
        committed = service.commit_snapshot(session["snapshotId"], {
            "uploadToken": session["uploadToken"], "batchCount": 1,
            "blockCount": 1, "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"], "coverage": metrics["coverage"],
            "verification": {
                "batchCount": 1, "blockCount": 1,
                "reviewCharacterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": metrics["structureSha256"],
                "formatSha256": metrics["formatSha256"], "coverage": metrics["coverage"],
                "documentIdentity": {"documentIdSha256": hashlib.sha256(b"lifecycle.docx").hexdigest()},
                "editSequence": None,
            },
        })
        # The identity is omitted by this minimal document fixture; the report is the public seam.
        job = service.start_job({
            "snapshotId": committed["snapshotId"],
            "snapshotToken": committed["snapshotToken"],
            "clientJobId": "format-life-job",
        }, "format-life-trace")
        for _ in range(50):
            if service.get_job(job["jobId"])["status"] == "completed":
                break
            time.sleep(0.01)
        issue_id = service.list_issues(job["jobId"])["items"][0]["issueId"]
        updated = service.update_issue(job["jobId"], issue_id, anchor_verification="unverified")
        self.assertEqual(updated["anchorVerification"], "unverified")
        now[0] += 24 * 60 * 60 + 1
        with self.assertRaises(AdapterError) as context:
            service.get_report(job["jobId"])
        self.assertEqual(context.exception.code, "DETERMINISTIC_FORMAT_REVIEW_REPORT_NOT_FOUND")

    def test_same_batch_is_idempotent_and_conflict_is_rejected(self):
        session = self._session()
        first, _ = self._upload(session)
        normalized = self.service._normalize_format_blocks(self._blocks())
        metrics = self.service._format_metrics(normalized)
        retry_payload = {
            "uploadToken": session["uploadToken"],
            "batchId": "format-batch-0",
            "blocks": normalized,
            "editSequence": "5",
        }
        retry_payload.update({key: metrics[key] for key in (
            "characterCount", "contentSha256", "structureSha256", "formatSha256"
        )})
        retry = self.service.upload_batch(session["snapshotId"], 0, retry_payload)
        self.assertTrue(retry["idempotent"])
        retry_payload["contentSha256"] = "0" * 64
        with self.assertRaises(AdapterError) as context:
            self.service.upload_batch(session["snapshotId"], 0, retry_payload)
        self.assertEqual(
            context.exception.code,
            "DETERMINISTIC_FORMAT_REVIEW_BATCH_IDEMPOTENCY_CONFLICT",
        )
        self.assertFalse(first["idempotent"])

    def test_second_pass_mismatch_removes_snapshot(self):
        session = self._session()
        _, metrics = self._upload(session)
        verification = {
            "batchCount": 1,
            "blockCount": 2,
            "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": "f" * 64,
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "coverage": metrics["coverage"],
            "documentIdentity": {
                "documentIdSha256": "document-fingerprint",
                "hostDocumentId": "host-document-1",
            },
            "editSequence": "5",
        }
        with self.assertRaises(AdapterError) as context:
            self._commit(session, metrics, verification=verification)
        self.assertEqual(
            context.exception.code,
            "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_MISMATCH",
        )
        self.assertFalse(self.service.snapshot_path(session["snapshotId"]).exists())

    def test_edit_sequence_change_aborts_and_removes_snapshot(self):
        session = self._session()
        with self.assertRaises(AdapterError) as context:
            self._upload(session, edit_sequence="6")
        self.assertEqual(
            context.exception.code,
            "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_CHANGED",
        )
        self.assertFalse(self.service.snapshot_path(session["snapshotId"]).exists())

    def test_table_metrics_are_single_counted_and_storage_is_private(self):
        session = self._session()
        blocks = [{
            "blockId": "format-table-1",
            "blockType": "table",
            "scope": "in_scope",
            "tableId": "table-1",
            "text": "表头\n单元格",
            "rows": [{"rowIndex": 1, "cells": [{"text": "表头"}]},
                     {"rowIndex": 2, "cells": [{"text": "单元格"}]}],
            "format": {"dataStatus": "verified"},
        }]
        uploaded, metrics = self._upload(session, blocks=blocks)
        self.assertEqual(uploaded["reviewCharacterCount"], len("表头\n单元格"))
        self.assertEqual(metrics["coverage"]["tableCount"], 1)
        snapshot_dir = self.service.snapshot_path(session["snapshotId"])
        self.assertEqual(stat.S_IMODE(snapshot_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((snapshot_dir / "snapshot.json").stat().st_mode), 0o600)
        with self.assertRaises(AdapterError) as context:
            self.service.upload_batch(
                session["snapshotId"], 1,
                {"uploadToken": "wrong", "batchId": "format-batch-1", "blocks": blocks,
                 "characterCount": 0, "contentSha256": "", "structureSha256": "", "formatSha256": ""},
            )
        self.assertEqual(context.exception.code, "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID")

    def test_duplicate_block_across_batches_cleans_snapshot(self):
        session = self._session()
        self._upload(session)
        normalized = self.service._normalize_format_blocks(self._blocks())
        metrics = self.service._format_metrics(normalized)
        payload = {
            "uploadToken": session["uploadToken"],
            "batchId": "format-batch-1",
            "blocks": normalized,
            "editSequence": "5",
        }
        payload.update({key: metrics[key] for key in (
            "characterCount", "contentSha256", "structureSha256", "formatSha256"
        )})
        with self.assertRaises(AdapterError) as context:
            self.service.upload_batch(session["snapshotId"], 1, payload)
        self.assertEqual(context.exception.code, "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID")
        self.assertFalse(self.service.snapshot_path(session["snapshotId"]).exists())

    def test_snapshot_byte_limit_cleans_session(self):
        session = self._session()
        with patch.object(format_protocol, "MAX_FORMAT_SNAPSHOT_BYTES", 1):
            with self.assertRaises(AdapterError) as context:
                self._upload(session)
        self.assertEqual(context.exception.code, "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX")
        self.assertFalse(self.service.snapshot_path(session["snapshotId"]).exists())

    def test_legacy_invalid_body_uses_adapter_error_envelope(self):
        with self.assertRaises(AdapterError) as context:
            self.service.create_snapshot({"content": []})
        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(
            context.exception.code,
            "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
        )

    def test_table_cell_format_and_structure_are_fingerprinted(self):
        blocks = self.service._normalize_format_blocks([{
            "blockId": "format-table-2",
            "blockType": "table",
            "scope": "in_scope",
            "tableId": "table-2",
            "text": "单元格",
            "rows": [{"rowIndex": 1, "cells": [{
                "cellId": "cell-1",
                "text": "单元格",
                "rowSpan": 1,
                "format": {"fontName": "宋体"},
            }]}],
            "format": {},
        }])
        baseline = self.service._format_metrics(blocks)
        blocks[0]["rows"][0]["cells"][0]["format"]["fontName"] = "黑体"
        format_changed = self.service._format_metrics(blocks)
        self.assertNotEqual(baseline["formatSha256"], format_changed["formatSha256"])
        blocks[0]["rows"][0]["cells"][0]["rowSpan"] = 2
        structure_changed = self.service._format_metrics(blocks)
        self.assertNotEqual(format_changed["structureSha256"], structure_changed["structureSha256"])

    def test_format_metrics_count_segments_cells_and_unsupported_objects(self):
        blocks = self.service._normalize_format_blocks([{
            "blockId": "format-paragraph-mixed",
            "blockType": "paragraph",
            "scope": "in_scope",
            "text": "混合格式",
            "format": {
                "segments": [
                    {"start": 0, "end": 2, "format": {"fontName": "宋体"}},
                    {"start": 2, "end": 4, "format": {"fontName": "黑体"}},
                ],
                "dataStatus": "verified",
            },
        }, {
            "blockId": "format-table-mixed",
            "blockType": "table",
            "scope": "in_scope",
            "text": "表格",
            "rows": [{"rowIndex": 1, "cells": [
                {"cellId": "cell-1", "text": "一", "format": {
                    "segments": [{"start": 0, "end": 1, "format": {"bold": True}}]
                }},
                {"cellId": "cell-2", "text": "二", "format": {}}
            ]}],
            "format": {},
        }])
        metrics = self.service._format_metrics(blocks, {
            "headerFooter": {
                "header": {"status": "unavailable", "failureCount": 1},
                "footer": {"status": "read", "characterCount": 8},
            },
            "unsupportedObjects": [
                {"type": "textBox", "count": 2, "status": "not_supported"},
                {"type": "comment", "count": 1, "status": "not_supported"},
            ],
        })
        self.assertEqual(metrics["coverage"]["formatSegmentCount"], 3)
        self.assertEqual(metrics["coverage"]["tableCellCount"], 2)
        self.assertEqual(metrics["coverage"]["unsupportedObjectCount"], 3)
        self.assertEqual(metrics["coverage"]["headerFooter"]["header"]["status"], "unavailable")
        self.assertEqual(metrics["capacityTier"], "standard")

    def test_capacity_tiers_are_explicit_and_over_limit_is_rejected(self):
        self.assertEqual(self.service.classify_capacity(60000)["tier"], "standard")
        self.assertEqual(self.service.classify_capacity(60001)["tier"], "large")
        self.assertEqual(self.service.classify_capacity(120000)["tier"], "large")
        with self.assertRaises(AdapterError) as context:
            self.service.classify_capacity(120001, raise_error=True)
        self.assertEqual(context.exception.code, "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE")

    def test_format_fragmentation_insufficient_status_is_preserved(self):
        blocks = self.service._normalize_format_blocks([{
            "blockId": "format-paragraph-insufficient",
            "blockType": "paragraph",
            "scope": "in_scope",
            "text": "无法完整读取",
            "format": {
                "segments": [],
                "dataStatus": "insufficient",
                "insufficientReason": "format_fragmentation_limit",
            },
        }])
        metrics = self.service._format_metrics(blocks)
        self.assertEqual(metrics["coverage"]["formatDataStatus"], "insufficient")
        self.assertEqual(metrics["coverage"]["formatDataInsufficientBlockCount"], 1)

    def test_character_format_attributes_are_preserved_in_segments(self):
        blocks = self.service._normalize_format_blocks([{
            "blockId": "format-paragraph-attributes",
            "blockType": "paragraph",
            "scope": "in_scope",
            "text": "属性",
            "format": {
                "segments": [{
                    "start": 0,
                    "end": 2,
                    "format": {
                        "strikeThrough": True,
                        "superscript": True,
                        "color": "red",
                        "characterScale": 90,
                    },
                }],
            },
        }])
        segment_format = blocks[0]["format"]["segments"][0]["format"]
        self.assertTrue(segment_format["strikeThrough"])
        self.assertTrue(segment_format["superscript"])
        self.assertEqual(segment_format["color"], "red")
        self.assertEqual(segment_format["characterScale"], 90)


if __name__ == "__main__":
    unittest.main()
