import importlib.util
import unittest


HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import Heading, Paragraph, WordDocumentRequest
    from app.services.word.authorized_format_algorithm import (
        classify_role_fact,
        heading_hierarchy_warnings,
    )
    from app.services.word.deterministic_format_review import DeterministicFormatReviewService
    from app.services.word.format_reviewer import WordFormatReviewer


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for outline-level tests")
class OutlineLevelTests(unittest.TestCase):
    def test_models_use_wps_body_constant_and_reject_unknown_outline_values(self):
        values = [0, 10, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, "not-a-number", -1, 11, 1.5]
        paragraphs = [
            Paragraph.parse_obj({"index": index, "text": str(value), "outlineLevel": value})
            for index, value in enumerate(values, 1)
        ]
        headings = [Heading.parse_obj({"level": value, "text": str(value)}) for value in values]

        self.assertEqual(
            [paragraph.outline_level for paragraph in paragraphs],
            [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, None, None, None, None],
        )
        self.assertEqual(
            [heading.level for heading in headings],
            [None, None, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, None, None, None, None],
        )

    def test_algorithm_does_not_turn_wps_body_level_into_a_heading(self):
        self.assertEqual(
            classify_role_fact({"outlineLevel": 10})["role"],
            "body",
        )
        self.assertEqual(
            classify_role_fact({"blockType": "paragraph", "outlineLevel": 10})["role"],
            "body",
        )
        self.assertEqual(
            classify_role_fact({"blockType": "heading", "headingLevel": 10, "outlineLevel": 10})["role"],
            "body",
        )
        self.assertEqual(
            classify_role_fact({"outlineLevel": -1})["role"],
            "unknown",
        )

    def test_heading_hierarchy_ignores_body_and_invalid_levels(self):
        warnings = heading_hierarchy_warnings([
            {"level": 10, "paragraphIndex": 1, "text": "正文"},
            {"level": 1, "paragraphIndex": 2, "text": "一、标题"},
            {"level": 3, "paragraphIndex": 3, "text": "三级标题"},
        ])

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["paragraphIndex"], 3)
        self.assertEqual(warnings[0]["level"], 3)
        self.assertEqual(warnings[0]["previousLevel"], 1)

    def test_heading_hierarchy_deduplicates_same_violating_paragraph(self):
        warnings = heading_hierarchy_warnings([
            {"level": 1, "paragraphIndex": 1, "text": "一级标题"},
            {"level": 3, "paragraphIndex": 3, "text": "三级标题"},
            {"level": 1, "paragraphIndex": 4, "text": "另一个一级标题"},
            {"level": 3, "paragraphIndex": 3, "text": "三级标题"},
        ])

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["paragraphIndex"], 3)

    def test_heading_hierarchy_keeps_distinct_unindexed_violations(self):
        warnings = heading_hierarchy_warnings([
            {"level": 1, "text": "一级标题"},
            {"level": 3, "text": "第一个三级标题"},
            {"level": 1, "text": "另一个一级标题"},
            {"level": 3, "text": "第二个三级标题"},
        ])

        self.assertEqual(len(warnings), 2)

    def test_format_blocks_defensively_treat_wps_body_level_as_body(self):
        reviewer = WordFormatReviewer()
        request = type("Request", (), {})()
        request.content = type("Content", (), {})()
        request.content.document_structure = {
            "formatBlocks": [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "heading",
                    "paragraphIndex": 1,
                    "headingLevel": 10,
                    "text": "正文",
                    "format": {"outlineLevel": 10},
                },
                {
                    "blockId": "format-paragraph-2",
                    "blockType": "heading",
                    "paragraphIndex": 2,
                    "headingLevel": 1,
                    "text": "一级标题",
                    "format": {"outlineLevel": 1},
                },
            ]
        }
        request.content.headings = []
        request.content.paragraphs = []

        facts = reviewer._format_structure_facts(request)

        self.assertEqual(facts["paragraphs"][0]["blockType"], "paragraph")
        self.assertEqual(facts["paragraphs"][0]["outlineLevel"], 0)
        self.assertEqual(facts["paragraphs"][1]["blockType"], "heading")
        self.assertEqual(facts["paragraphs"][1]["outlineLevel"], 1)

    def test_background_snapshot_normalizes_outline_levels_at_ingress(self):
        blocks = DeterministicFormatReviewService._normalize_format_blocks([
            {
                "blockId": "body-ten-1",
                "blockType": "heading",
                "scope": "in_scope",
                "paragraphIndex": 1,
                "headingLevel": 10,
                "text": "正文",
                "format": {"outlineLevel": 10},
            },
            {
                "blockId": "heading-one",
                "blockType": "heading",
                "scope": "in_scope",
                "paragraphIndex": 2,
                "headingLevel": 1,
                "text": "标题",
                "format": {"outlineLevel": 1},
            },
        ])

        self.assertEqual(
            [(block["blockType"], block["outlineLevel"], block.get("headingLevel")) for block in blocks],
            [("paragraph", 0, None), ("heading", 1, 1)],
        )

    def test_background_format_facts_derive_headings_from_verified_blocks(self):
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
        request = DeterministicFormatReviewService._request_from_blocks(
            {"selectionMode": "document", "templateId": "technical-file-format-requirements"},
            blocks,
            {"contentSha256": "c", "structureSha256": "s", "formatSha256": "f", "coverage": {}},
        )
        parsed = (
            WordDocumentRequest.model_validate(request)
            if hasattr(WordDocumentRequest, "model_validate")
            else WordDocumentRequest.parse_obj(request)
        )
        facts = WordFormatReviewer()._format_structure_facts(parsed)

        self.assertEqual(
            [(item["level"], item["paragraphIndex"]) for item in facts["headings"]],
            [(1, 1), (3, 2)],
        )
        result = WordFormatReviewer().review(parsed, trace_id="")
        hierarchy_issues = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.heading_hierarchy"
        ]
        self.assertEqual(len(hierarchy_issues), 1)
        self.assertEqual(hierarchy_issues[0]["paragraphIndex"], 2)
        self.assertEqual(hierarchy_issues[0]["anchorId"], "format-paragraph-2")


if __name__ == "__main__":
    unittest.main()
