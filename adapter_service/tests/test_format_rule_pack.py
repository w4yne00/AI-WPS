import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.services.word.authorized_format_algorithm import (
    audit_format_facts,
    classify_table_fact,
    heading_hierarchy_warnings,
)
from app.services.word.format_rule_pack import (
    FormatRulePackError,
    FormatRulePackLoader,
)
from app.services.word.format_reviewer import WordFormatReviewer
from app.core.models import WordDocumentRequest
from tools.compile_format_rule_pack import compile_rule_pack


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DOCX = ROOT / "templates/company/technical-file-format-requirements.docx"
TEMPLATE_JSON = ROOT / "templates/company/technical-file-format-requirements.json"
STRUCTURE_RULES = ROOT / "templates/company/technical-file-structure-rules.json"


class FormatRulePackTests(unittest.TestCase):
    def test_compiler_extracts_authoritative_docx_values_and_manual_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "technical.json"
            pack = compile_rule_pack(
                TEMPLATE_DOCX,
                TEMPLATE_JSON,
                STRUCTURE_RULES,
                output,
            )

            self.assertEqual(pack["schemaVersion"], 1)
            self.assertEqual(pack["template"]["id"], "technical-file-format-requirements")
            self.assertEqual(
                pack["template"]["sourceDocumentSha256"],
                hashlib.sha256(TEMPLATE_DOCX.read_bytes()).hexdigest(),
            )
            self.assertEqual(pack["template"]["page"]["marginLeftTwips"], 1800)
            self.assertEqual(pack["template"]["roleRules"]["heading1"]["fontName"], "黑体")
            self.assertEqual(pack["template"]["roleRules"]["heading1"]["fontSize"], 12.0)
            self.assertTrue(pack["rules"])
            self.assertTrue(all(rule["enabled"] for rule in pack["rules"]))
            self.assertNotIn("defaultTemplateValues", pack["algorithm"])
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["integrity"],
                pack["integrity"],
            )

    def test_loader_rejects_tampered_rule_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "technical.json"
            compile_rule_pack(TEMPLATE_DOCX, TEMPLATE_JSON, STRUCTURE_RULES, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["template"]["roleRules"]["body"]["fontName"] = "第三方默认字体"
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(FormatRulePackError):
                FormatRulePackLoader(root).load("technical-file-format-requirements")

    def test_reviewer_fails_closed_when_compiled_pack_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            request = WordDocumentRequest(
                documentId="missing-pack.docx",
                content={"paragraphs": [{"index": 1, "text": "正文"}]},
                options={"templateId": "technical-file-format-requirements"},
            )
            with self.assertRaises(FormatRulePackError):
                WordFormatReviewer(rule_pack_loader=FormatRulePackLoader(Path(directory))).review(request)

    def test_algorithm_matches_golden_facts_and_rejects_weak_data_table_evidence(self):
        self.assertEqual(
            classify_table_fact(
                {
                    "cells": [
                        {"text": "字段", "row": 0, "column": 0},
                        {"text": "值", "row": 0, "column": 1},
                        {"text": "版本", "row": 1, "column": 0},
                        {"text": "1.0", "row": 1, "column": 1},
                    ]
                }
            )["tableType"],
            "data",
        )
        self.assertEqual(
            classify_table_fact(
                {"cells": [{"text": "看起来像表格"}, {"text": "但没有记录结构"}]}
            )["tableType"],
            "unknown",
        )
        warnings = heading_hierarchy_warnings(
            [{"level": 1, "text": "一"}, {"level": 3, "text": "三"}]
        )
        self.assertEqual(warnings[0]["type"], "heading_level_jump")

    def test_algorithm_never_supplies_template_defaults(self):
        facts = {
            "paragraphs": [
                {"role": "body", "fontName": "第三方默认字体", "fontSize": 10}
            ]
        }
        pack = {
            "template": {
                "roleRules": {
                    "body": {"fontName": "宋体", "fontSize": 12.0}
                }
            },
            "rules": [],
        }
        result = audit_format_facts(facts, pack)
        self.assertEqual(result["issues"][0]["expectedValue"], "宋体")
        self.assertNotEqual(result["issues"][0]["expectedValue"], "第三方默认字体")

    def test_format_reviewer_reports_the_compiled_pack_as_its_authority(self):
        request = WordDocumentRequest(
            documentId="rule-pack-review.docx",
            content={
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "正文",
                        "styleName": "Normal",
                        "fontName": "宋体",
                        "fontSize": 12,
                    }
                ]
            },
            options={"templateId": "technical-file-format-requirements"},
        )
        result = WordFormatReviewer().review(request)
        self.assertEqual(result["summary"]["rulePackVersion"], "2026-05-23.rules.1")
        self.assertEqual(len(result["summary"]["rulePackSha256"]), 64)
        self.assertEqual(result["issues"][0]["ruleVersion"], "2026-05-23.rules.1")
        self.assertEqual(len(result["issues"][0]["templateHash"]), 64)

    def test_runtime_executes_authorized_heading_and_table_rules(self):
        request = WordDocumentRequest(
            documentId="structure-review.docx",
            content={
                "paragraphs": [{"index": 1, "text": "正文", "styleName": "Normal"}],
                "headings": [{"level": 1, "text": "一"}, {"level": 3, "text": "三"}],
                "documentStructure": {
                    "formatFacts": {
                        "tables": [{"cells": [{"text": "只有一行"}, {"text": "没有数据行"}]}]
                    }
                },
            },
            options={"templateId": "technical-file-format-requirements"},
        )
        result = WordFormatReviewer().review(request)
        rule_ids = {issue["ruleId"] for issue in result["issues"]}
        self.assertIn("structure.heading_hierarchy", rule_ids)
        self.assertIn("structure.table_semantics", rule_ids)


if __name__ == "__main__":
    unittest.main()
