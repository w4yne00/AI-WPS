import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.deterministic_format_review import (
        AdapterError,
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


def _document_payload(toc_regions=None, suspected_toc_regions=None):
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
    ]
    blocks = [
        _block(paragraphs[0], "paragraph"),
        _block(paragraphs[1], "heading"),
        _block(paragraphs[2], "paragraph"),
        _block(paragraphs[3], "paragraph"),
        _block(paragraphs[4], "paragraph"),
    ]
    coverage = {}
    if toc_regions is not None:
        coverage["tocRegions"] = toc_regions
    if suspected_toc_regions is not None:
        coverage["suspectedTocRegions"] = suspected_toc_regions

    return {
        "documentId": "manual-toc.docx",
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
class ManualAndSuspectedTocValidationTests(unittest.TestCase):
    def test_normalizes_manual_toc_and_suspected_toc_in_coverage(self):
        raw_coverage = {
            "tocRegions": [
                {
                    "regionId": "manual-toc-1",
                    "source": "manual_toc",
                    "startParagraphIndex": 2,
                    "endParagraphIndex": 4,
                    "paragraphIndexes": [2, 3, 4],
                    "titleParagraphIndex": 2,
                }
            ],
            "suspectedTocRegions": [
                {
                    "regionId": "suspected-toc-1",
                    "source": "suspected_toc",
                    "startParagraphIndex": 6,
                    "endParagraphIndex": 8,
                    "paragraphIndexes": [6, 7, 8],
                    "reason": "insufficient_evidence:missing_dot_leader_and_title",
                }
            ],
        }
        normalized = DeterministicFormatReviewService._normalize_source_coverage(raw_coverage)
        self.assertEqual(len(normalized.get("tocRegions", [])), 1)
        self.assertEqual(normalized["tocRegions"][0]["source"], "manual_toc")
        self.assertEqual(len(normalized.get("suspectedTocRegions", [])), 1)
        self.assertEqual(normalized["suspectedTocRegions"][0]["source"], "suspected_toc")
        self.assertEqual(normalized["suspectedTocRegions"][0]["regionId"], "suspected-toc-1")
        self.assertEqual(
            normalized["suspectedTocRegions"][0]["reason"],
            "insufficient_evidence:missing_dot_leader_and_title",
        )

    def test_rejects_invalid_suspected_toc_source(self):
        with self.assertRaises(AdapterError) as ctx:
            DeterministicFormatReviewService._normalize_source_coverage({
                "suspectedTocRegions": [{"source": "invalid_source", "paragraphIndexes": [1, 2]}]
            })
        self.assertEqual(ctx.exception.code, "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID")

    def test_rejects_invalid_suspected_toc_paragraph_indexes(self):
        with self.assertRaises(AdapterError) as ctx:
            DeterministicFormatReviewService._normalize_source_coverage({
                "suspectedTocRegions": [{"source": "suspected_toc", "paragraphIndexes": [-1]}]
            })
        self.assertEqual(ctx.exception.code, "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class ManualAndSuspectedTocReviewerTests(unittest.TestCase):
    def test_manual_toc_region_does_not_emit_format_or_unmapped_role_issues(self):
        manual_toc_region = {
            "regionId": "manual-toc-1",
            "source": "manual_toc",
            "startParagraphIndex": 2,
            "endParagraphIndex": 4,
            "paragraphIndexes": [2, 3, 4],
            "titleParagraphIndex": 2,
        }
        payload = _document_payload(toc_regions=[manual_toc_region])
        result = WordFormatReviewer().review(parse_word_request(payload))

        toc_issues = [
            issue for issue in result["issues"]
            if issue.get("paragraphIndex") in {2, 3, 4}
        ]
        self.assertEqual(toc_issues, [])
        self.assertEqual(result["summary"].get("exemptedTocRegionCount"), 1)
        self.assertEqual(result["summary"].get("exemptedTocParagraphCount"), 3)
        self.assertEqual(
            result["summary"].get("tocExemptionSummary"),
            "已识别并略过目录：1 个区域，共 3 段",
        )
        # Non-toc body paragraph 5 still emits issue
        body_issues = [
            issue for issue in result["issues"]
            if issue.get("paragraphIndex") == 5
        ]
        self.assertTrue(body_issues)

    def test_suspected_toc_region_suppresses_body_issues_and_sets_partial_coverage(self):
        suspected_region = {
            "regionId": "suspected-toc-1",
            "source": "suspected_toc",
            "startParagraphIndex": 3,
            "endParagraphIndex": 4,
            "paragraphIndexes": [3, 4],
            "reason": "insufficient_evidence:missing_dot_leader_and_title",
        }
        payload = _document_payload(suspected_toc_regions=[suspected_region])
        result = WordFormatReviewer().review(parse_word_request(payload))

        # Suspected TOC paragraphs must not emit body format issues
        suspected_issues = [
            issue for issue in result["issues"]
            if issue.get("paragraphIndex") in {3, 4}
        ]
        self.assertEqual(suspected_issues, [])

        # Must NOT be counted as exempted
        self.assertFalse(result["summary"].get("exemptedTocRegionCount"))
        self.assertFalse(result["summary"].get("exemptedTocParagraphCount"))

        # Must count as suspected
        self.assertEqual(result["summary"].get("suspectedTocRegionCount"), 1)
        self.assertEqual(result["summary"].get("suspectedTocParagraphCount"), 2)
        self.assertEqual(
            result["summary"].get("suspectedTocSummary"),
            "发现疑似目录：1 个区域，共 2 段（证据不足，未审查未豁免）",
        )
        self.assertEqual(result["summary"].get("coverageStatus"), "partial")
        self.assertTrue(result["summary"].get("coverageReason"))

    def test_model_toc_role_without_coverage_structure_cannot_exempt(self):
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
                {"aiAttempted": True, "aiAcceptedCount": 1, "semanticStatus": "enhanced"},
                1,
            )

        reviewer._classify_roles_with_model = fake_classify
        # Empty coverage: no auto/manual toc and no suspected toc
        payload = _document_payload(toc_regions=None, suspected_toc_regions=None)
        result = reviewer.review(parse_word_request(payload))

        # Paragraph 3 must NOT be exempted by AI alone
        para3_issues = [
            issue for issue in result["issues"]
            if issue.get("paragraphIndex") == 3
        ]
        self.assertTrue(para3_issues)
        self.assertFalse(result["summary"].get("exemptedTocRegionCount"))
