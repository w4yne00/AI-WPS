import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.word.deterministic_format_review import (
        DeterministicFormatReviewService,
    )
    from app.services.word.format_reviewer import WordFormatReviewer


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


def _paragraph(index, text, **kwargs):
    payload = {
        "index": index,
        "text": text,
        "styleName": kwargs.get("styleName", "Normal"),
        "fontName": kwargs.get("fontName", "宋体"),
        "fontSize": kwargs.get("fontSize", 12),
        "alignment": kwargs.get("alignment", "left"),
        "outlineLevel": kwargs.get("outlineLevel", 0),
        "lineSpacing": kwargs.get("lineSpacing", 1.25),
        "firstLineIndent": kwargs.get("firstLineIndent", 480),
    }
    return payload


def _block(paragraph, block_type="paragraph"):
    return {
        "blockId": "format-paragraph-{0}".format(paragraph["index"]),
        "blockType": block_type,
        "scope": "in_scope",
        "paragraphIndex": paragraph["index"],
        "text": paragraph["text"],
        "headingLevel": paragraph["outlineLevel"] if block_type == "heading" else 0,
        "range": {"paragraphIndex": paragraph["index"], "sectionIndex": 1},
        "format": {
            "styleName": paragraph["styleName"],
            "fontName": paragraph["fontName"],
            "fontSize": paragraph["fontSize"],
            "alignment": paragraph["alignment"],
            "outlineLevel": paragraph["outlineLevel"],
            "lineSpacing": paragraph["lineSpacing"],
            "firstLineIndent": paragraph["firstLineIndent"],
            "dataStatus": "verified",
        },
    }


TOC_REGION = {
    "regionId": "auto-toc-1",
    "source": "tables_of_contents",
    "startParagraphIndex": 2,
    "endParagraphIndex": 4,
    "paragraphIndexes": [2, 3, 4],
    "titleParagraphIndex": 2,
}


def _document_payload(include_auto_toc=True):
    paragraphs = [
        _paragraph(1, "总体技术方案", styleName="Title", fontName="黑体", fontSize=22),
        _paragraph(2, "目录", styleName="Heading 1", fontName="黑体", fontSize=16, outlineLevel=1),
        _paragraph(
            3,
            "一、概述.........1",
            styleName="TOC 1",
            fontName="楷体",
            fontSize=14,
            lineSpacing=1.0,
            firstLineIndent=0,
        ),
        _paragraph(
            4,
            "二、建设目标.........3",
            styleName="TOC 1",
            fontName="楷体",
            fontSize=14,
            lineSpacing=1.0,
            firstLineIndent=0,
        ),
        _paragraph(
            5,
            "本文件规定系统总体要求。",
            styleName="Normal",
            fontName="楷体",
            fontSize=14,
            outlineLevel=0,
            lineSpacing=1.0,
            firstLineIndent=0,
        ),
        _paragraph(6, "注：本条用于说明适用范围。", styleName="Normal", fontName="楷体", fontSize=10.5),
        _paragraph(7, "图 1：总体架构", styleName="Caption", fontName="黑体", fontSize=10.5),
        _paragraph(8, "附录 A 术语", styleName="Normal", fontName="黑体", fontSize=16, outlineLevel=0),
    ]
    blocks = [
        _block(paragraphs[0], "paragraph"),
        _block(paragraphs[1], "heading"),
        _block(paragraphs[2], "paragraph"),
        _block(paragraphs[3], "paragraph"),
        _block(paragraphs[4], "paragraph"),
        _block(paragraphs[5], "paragraph"),
        _block(paragraphs[6], "caption"),
        _block(paragraphs[7], "paragraph"),
    ]
    coverage = {"tocRegions": [dict(TOC_REGION)]} if include_auto_toc else {}
    return {
        "documentId": "auto-toc.docx",
        "scene": "word",
        "selectionMode": "document",
        "content": {
            "plainText": "\n".join(item["text"] for item in paragraphs),
            "paragraphs": paragraphs,
            "headings": [
                {"level": 1, "text": "目录", "paragraphIndex": 2},
            ],
            "documentStructure": {
                "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                "formatBlocks": blocks,
                "coverage": coverage,
            },
        },
        "options": {"templateId": "technical-document-template-rules"},
    }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class AutoTocExemptionTests(unittest.TestCase):
    def test_auto_toc_region_does_not_emit_format_or_unmapped_role_issues(self):
        result = WordFormatReviewer().review(parse_word_request(_document_payload(True)))

        toc_issues = [
            issue
            for issue in result["issues"]
            if issue.get("paragraphIndex") in {2, 3, 4}
        ]
        self.assertEqual(toc_issues, [])
        self.assertEqual(result["summary"].get("exemptedTocRegionCount"), 1)
        self.assertEqual(result["summary"].get("exemptedTocParagraphCount"), 3)
        self.assertEqual(
            result["summary"].get("tocExemptionSummary"),
            "已识别并略过目录：1 个区域，共 3 段",
        )
        self.assertNotIn(
            "toc_title",
            [issue.get("role") for issue in result["issues"] if issue.get("ruleId") == "structure.role_mapping"],
        )

    def test_auto_toc_exemption_does_not_swallow_body_note_caption_or_appendix(self):
        result = WordFormatReviewer().review(parse_word_request(_document_payload(True)))
        body_issues = [
            issue for issue in result["issues"] if issue.get("paragraphIndex") == 5
        ]
        self.assertTrue(body_issues)
        self.assertTrue(
            any(issue.get("ruleId") in {"font_name", "font_size", "style_name"} for issue in body_issues)
        )
        non_toc_indexes = {
            issue.get("paragraphIndex")
            for issue in result["issues"]
            if issue.get("paragraphIndex") not in {2, 3, 4, None}
        }
        self.assertTrue(5 in non_toc_indexes)
        self.assertTrue(non_toc_indexes - {5})

    def test_bare_catalog_word_without_auto_toc_structure_is_not_exempted(self):
        result = WordFormatReviewer().review(parse_word_request(_document_payload(False)))

        self.assertFalse(result["summary"].get("exemptedTocRegionCount"))
        toc_title_issues = [
            issue for issue in result["issues"] if issue.get("paragraphIndex") == 2
        ]
        toc_entry_issues = [
            issue for issue in result["issues"] if issue.get("paragraphIndex") in {3, 4}
        ]
        self.assertTrue(toc_title_issues or toc_entry_issues)

    def test_model_toc_role_without_auto_toc_structure_cannot_exempt(self):
        reviewer = WordFormatReviewer()

        def fake_classify(*args, **kwargs):
            return (
                {
                    3: {
                        "role": "toc_entry",
                        "attributes": {},
                        "status": "confirmed",
                        "confidence": 0.99,
                    }
                },
                1,
                {
                    "semanticComplete": True,
                    "semanticStatus": "completed",
                    "aiAcceptedCount": 1,
                    "aiCallCount": 1,
                    "aiAttempted": True,
                },
            )

        reviewer._classify_roles_with_ai = fake_classify
        result = reviewer.review(parse_word_request(_document_payload(False)), trace_id="toc-model")
        self.assertFalse(result["summary"].get("exemptedTocRegionCount"))
        self.assertTrue(any(issue.get("paragraphIndex") == 3 for issue in result["issues"]))

    def test_structured_report_records_exemption_and_excludes_toc_from_issue_count(self):
        reviewer = WordFormatReviewer()
        request = parse_word_request(_document_payload(True))
        result = reviewer.review(request)
        previous = os.environ.get("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW")
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                service = DeterministicFormatReviewService(
                    staging_root=Path(temp_dir),
                    coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
                    reviewer=reviewer,
                )
                report = service._build_report(
                    result,
                    {
                        "snapshotId": "snap-auto-toc",
                        "request": request,
                        "sourceCoverage": {"tocRegions": [dict(TOC_REGION)]},
                        "contentSha256": "c",
                        "structureSha256": "s",
                        "formatSha256": "f",
                    },
                )
                self.assertEqual(report["summary"]["exemptedTocRegionCount"], 1)
                self.assertEqual(report["summary"]["exemptedTocParagraphCount"], 3)
                self.assertEqual(
                    report["coverage"].get("exemptedTocParagraphCount")
                    or report["summary"]["exemptedTocParagraphCount"],
                    3,
                )
                self.assertFalse(
                    any(issue.get("paragraphIndex") in {2, 3, 4} for issue in report["issues"])
                )
                self.assertEqual(report["issueCount"], len(report["issues"]))
                service._save_report("auto-toc-report", report)
                markdown = service.export_report("auto-toc-report", "markdown")
                self.assertIn("已识别并略过目录：1 个区域，共 3 段", markdown)
        finally:
            if previous is None:
                os.environ.pop("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None)
            else:
                os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = previous

    def test_snapshot_coverage_keeps_auto_toc_regions(self):
        previous = os.environ.get("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW")
        os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = "1"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                service = DeterministicFormatReviewService(
                    staging_root=Path(temp_dir),
                    coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
                )
                session = service.create_snapshot(
                    {
                        "documentId": "auto-toc.docx",
                        "selectionMode": "document",
                        "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                        "formatFactSchemaVersion": "format_snapshot.v2",
                        "documentIdentity": {
                            "documentIdSha256": "document-fingerprint",
                            "hostDocumentId": "host-document-1",
                        },
                        "editSequence": "1",
                        "coverage": {"tocRegions": [dict(TOC_REGION)]},
                    }
                )
                record = service._load_snapshot(session["snapshotId"])
        finally:
            if previous is None:
                os.environ.pop("AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW", None)
            else:
                os.environ["AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW"] = previous

        regions = record.get("sourceCoverage", {}).get("tocRegions") or []
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["paragraphIndexes"], [2, 3, 4])
        self.assertEqual(regions[0]["source"], "tables_of_contents")


if HAS_PYDANTIC:
    class _ChineseRoleDisplay(unittest.TestCase):
        def test_report_role_text_includes_toc_roles(self):
            from app.services.word import deterministic_format_review as protocol

            self.assertEqual(protocol._report_issue_role({"role": "toc_title"}), "目录标题")
            self.assertEqual(protocol._report_issue_role({"role": "toc_entry"}), "目录项")
