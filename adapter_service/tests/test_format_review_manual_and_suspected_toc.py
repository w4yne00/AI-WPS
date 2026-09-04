import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.services.word.deterministic_format_review import (
        AdapterError,
        DeterministicFormatReviewService,
    )


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class ManualAndSuspectedTocValidationTests(unittest.TestCase):
    def test_normalizes_manual_toc_and_suspected_toc_in_coverage(self):
        service = DeterministicFormatReviewService()
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
