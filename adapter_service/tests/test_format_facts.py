import unittest

from app.services.word.format_facts import (
    normalize_format_facts,
    normalize_line_spacing_fact,
    normalize_page_setup,
    normalize_paper_size_fact,
)


class FormatFactsTests(unittest.TestCase):
    def test_paper_enum_and_point_lengths_are_normalized_without_magnitude_guessing(self):
        paper = normalize_paper_size_fact(7)
        self.assertEqual(paper["normalizedValue"], "A4")
        self.assertEqual(paper["rawUnit"], "enum")

        page, facts = normalize_page_setup(
            {"paperSize": 7},
            {
                "marginTop": {"rawValue": 72, "rawUnit": "pt"},
                "marginBottom": {"rawValue": 90, "rawUnit": "pt"},
            },
        )
        self.assertEqual(page["paperSize"], "A4")
        self.assertEqual(page["marginTop"], 1440)
        self.assertEqual(page["marginBottom"], 1800)
        self.assertEqual(facts["marginTop"]["normalizedUnit"], "twip")

        noisy = normalize_page_setup(
            {"paperSize": 7},
            {"marginTop": {"rawValue": 89.8499998474, "rawUnit": "pt"}},
        )
        self.assertEqual(noisy[0]["marginTop"], 1797)
        half_twip = normalize_page_setup(
            {"paperSize": 7},
            {"marginTop": {"rawValue": 0.025, "rawUnit": "pt"}},
        )
        self.assertEqual(half_twip[0]["marginTop"], 1)

    def test_line_spacing_preserves_mode_and_does_not_turn_points_into_multiple(self):
        fixed = normalize_line_spacing_fact(15, "fixed")
        self.assertEqual(fixed["mode"], "fixed")
        self.assertEqual(fixed["normalizedValue"], 300)
        self.assertEqual(fixed["normalizedUnit"], "twip")

        multiple = normalize_line_spacing_fact(
            {"rawValue": 1.25, "rawUnit": "multiple"}, "multiple"
        )
        self.assertEqual(multiple["normalizedValue"], 1.25)
        self.assertEqual(multiple["normalizedUnit"], "multiple")
        value_alias = normalize_line_spacing_fact(
            {"value": 15, "rawUnit": "pt"}, "fixed"
        )
        self.assertEqual(value_alias["normalizedValue"], 300)

    def test_mixed_unknown_read_failed_and_unsupported_do_not_normalize(self):
        for status in ("mixed", "unknown", "read_failed", "unsupported"):
            fact = normalize_line_spacing_fact(
                {"rawValue": 15, "rawUnit": "pt", "dataStatus": status}, "fixed"
            )
            self.assertEqual(fact["dataStatus"], status)
            self.assertIsNone(fact["normalizedValue"])

    def test_format_facts_provide_legacy_normalized_values_and_stable_diagnostics(self):
        result = normalize_format_facts(
            {
                "fontSize": 12,
                "facts": {
                    "lineSpacing": {"rawValue": 15, "rawUnit": "pt"},
                    "lineSpacingMode": "minimum",
                },
            }
        )
        self.assertEqual(result["lineSpacing"], 300)
        self.assertEqual(result["lineSpacingMode"], "minimum")
        self.assertEqual(result["facts"]["lineSpacing"]["rawValue"], 15)
        self.assertEqual(result["facts"]["fontSize"]["normalizedUnit"], "pt")

        indent = normalize_format_facts({"facts": {"firstLineIndent": 32}})
        self.assertEqual(indent["facts"]["firstLineIndent"]["rawUnit"], "pt")
        self.assertEqual(indent["firstLineIndent"], 640)

    def test_block_status_stays_distinct_and_blocks_legacy_scalar_fallback(self):
        result = normalize_format_facts({
            "lineSpacing": 15,
            "lineSpacingMode": "fixed",
            "dataStatus": "unsupported",
        })
        self.assertEqual(result["dataStatus"], "unsupported")
        self.assertEqual(result["facts"]["lineSpacing"]["dataStatus"], "unsupported")
        self.assertIsNone(result["facts"]["lineSpacing"]["normalizedValue"])
        self.assertIsNone(result["lineSpacing"])


if __name__ == "__main__":
    unittest.main()
