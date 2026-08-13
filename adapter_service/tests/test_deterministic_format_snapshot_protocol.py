import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import (
    DeterministicFormatReviewService,
)
import app.services.word.deterministic_format_review as format_protocol


class _Reviewer:
    def __init__(self):
        self.requests = []

    def review(self, request, trace_id=""):
        self.requests.append(request)
        return {"issues": [], "summary": {}}


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
