import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.services.word.authorized_format_algorithm import (
    audit_format_facts,
    associate_captions,
    classify_appendix_fact,
    classify_list_fact,
    classify_note_fact,
    classify_role_fact,
    classify_table_fact,
    heading_hierarchy_warnings,
    resolve_role_rule,
)
from app.services.word.format_rule_pack import (
    FormatRulePackError,
    FormatRulePackLoader,
)
from app.services.word.format_reviewer import WordFormatReviewer
from app.core.models import WordDocumentRequest
from tools.compile_format_rule_pack import compile_rule_pack


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DOCX = ROOT / "adapter_service/vendor/wx_doc_format_algorithm/assets/wx_template.docx"
MANUALLY_CONFIRMED_TEMPLATE_DOCX = ROOT / "templates/history/inactive/technical-file-format-requirements.docx"
TEMPLATE_JSON = ROOT / "packaging/format-rule-sources/technical-document-template-rules.v1.0.0.json"
STRUCTURE_RULES = ROOT / "packaging/format-rule-sources/technical-document-template-rules.v1.0.0.structure.json"
ACTIVE_TEMPLATE_ID = "technical-document-template-rules"


class FormatRulePackTests(unittest.TestCase):
    def test_active_rule_pack_has_canonical_identity_and_source_classifications(self):
        pack = FormatRulePackLoader().load(ACTIVE_TEMPLATE_ID)

        self.assertEqual(pack["rulePack"]["id"], ACTIVE_TEMPLATE_ID)
        self.assertEqual(pack["rulePack"]["displayName"], "技术文档模板规则")
        self.assertEqual(pack["rulePack"]["version"], "1.0.0")
        self.assertEqual(pack["rulePack"]["sourceVersion"], "wx-doc-format 0.12.15")
        self.assertEqual(pack["algorithm"]["sourceVersion"], "0.12.15")
        self.assertEqual(pack["template"]["id"], ACTIVE_TEMPLATE_ID)
        self.assertEqual(pack["template"]["name"], "技术文档模板规则")
        self.assertTrue(pack["algorithm"]["sourceClassificationSha256"])
        self.assertTrue(all(
            rule["classification"] in {"normative-format", "normative-structure"}
            for rule in pack["rules"]
        ))
        self.assertNotIn("converter-only", {
            rule["classification"] for rule in pack["rules"]
        })

    def test_legacy_template_identifier_does_not_fallback_to_active_pack(self):
        with self.assertRaises(FormatRulePackError):
            FormatRulePackLoader().load("technical-file-format-requirements")

    def test_loader_does_not_scan_an_inactive_json_as_a_runtime_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active_path = root / "technical-document-template-rules.v1.0.0.json"
            active_path.write_text(
                (ROOT / "adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            (root / "general-office.json").write_text(
                json.dumps({"status": "inactive", "id": "general-office"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(FormatRulePackError, "FORMAT_RULE_PACK_INACTIVE"):
                FormatRulePackLoader(root).list_metadata()

    def test_page_and_margin_variations_remain_diagnostic_only(self):
        request = WordDocumentRequest(
            documentId="page-diagnostic-only.docx",
            content={
                "paragraphs": [{
                    "index": 1,
                    "text": "正文",
                    "styleName": "Normal",
                    "fontName": "宋体",
                    "fontSize": 12,
                }],
                "documentStructure": {
                    "page_setup": {
                        "paperSize": 7,
                        "marginTopTwips": 1,
                        "marginBottomTwips": 2,
                        "marginLeftTwips": 3,
                        "marginRightTwips": 4,
                    }
                },
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )

        result = WordFormatReviewer().review(request)

        self.assertNotIn("page_setup", {issue["ruleId"] for issue in result["issues"]})
        self.assertNotIn("rulePackName", result["summary"])
        self.assertEqual(result["summary"]["rulePackSourceVersion"], "wx-doc-format 0.12.15")

    def test_semantic_roles_require_structural_evidence_and_use_explicit_mapping(self):
        style_only = classify_role_fact({"styleName": "heading 1"})
        self.assertEqual(style_only["role"], "unknown")
        self.assertEqual(style_only["status"], "needs_confirmation")

        heading = classify_role_fact(
            {
                "blockType": "heading",
                "headingLevel": 2,
                "text": "2 范围",
                "styleName": "Normal",
            }
        )
        self.assertEqual(heading["role"], "heading")
        self.assertEqual(heading["attributes"]["level"], 2)
        self.assertEqual(heading["status"], "confirmed")

        pack = {
            "template": {
                "roleRules": {"heading2": {"styleName": "heading 2"}},
                "roleMappings": {"heading": {"2": "heading2"}},
            }
        }
        mapped = resolve_role_rule(heading, pack)
        self.assertEqual(mapped["status"], "mapped")
        self.assertEqual(mapped["ruleKey"], "heading2")

        unmapped = resolve_role_rule(
            {"role": "formula", "status": "confirmed", "attributes": {}}, pack
        )
        self.assertEqual(unmapped["status"], "unconfigured")
        self.assertEqual(unmapped["ruleKey"], "formula")

        same_named_rule_is_not_an_implicit_mapping = resolve_role_rule(
            {"role": "body", "status": "confirmed", "attributes": {}},
            {"template": {"roleRules": {"body": {"fontName": "宋体"}}}},
        )
        self.assertEqual(same_named_rule_is_not_an_implicit_mapping["status"], "unconfigured")

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
            self.assertEqual(pack["template"]["id"], ACTIVE_TEMPLATE_ID)
            self.assertEqual(
                pack["template"]["sourceDocumentSha256"],
                hashlib.sha256(TEMPLATE_DOCX.read_bytes()).hexdigest(),
            )
            self.assertEqual(pack["template"]["page"]["marginLeftTwips"], 1800)
            self.assertEqual(pack["template"]["roleRules"]["heading1"]["fontName"], "黑体")
            self.assertEqual(pack["template"]["roleRules"]["heading1"]["fontSize"], 12.0)
            self.assertTrue(pack["rules"])
            self.assertTrue(all(rule["enabled"] for rule in pack["rules"]))
            self.assertEqual(pack["template"]["roleMappings"]["heading"]["2"], "heading2")
            self.assertNotIn("defaultTemplateValues", pack["algorithm"])
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["integrity"],
                pack["integrity"],
            )

    def test_fixed_wx_template_matches_manually_confirmed_template_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source_pack = compile_rule_pack(
                TEMPLATE_DOCX,
                TEMPLATE_JSON,
                STRUCTURE_RULES,
                Path(directory) / "source.json",
            )
            manual_pack = compile_rule_pack(
                MANUALLY_CONFIRMED_TEMPLATE_DOCX,
                TEMPLATE_JSON,
                STRUCTURE_RULES,
                Path(directory) / "manual.json",
            )

            self.assertEqual(source_pack["template"]["page"], manual_pack["template"]["page"])
            self.assertEqual(source_pack["template"]["body"], manual_pack["template"]["body"])
            self.assertEqual(source_pack["template"]["roleRules"], manual_pack["template"]["roleRules"])
            self.assertEqual(
                source_pack["template"]["sourceDocumentSha256"],
                "889b3f1ba873d0db5373a96c76464885c50d465f9ca6c6b6b43f1ca0efa5a2fe",
            )

    def test_compiler_is_reproducible_and_explicit_template_values_win(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template_json = json.loads(TEMPLATE_JSON.read_text(encoding="utf-8"))
            template_json["body"]["fontSize"] = 13
            custom_template = root / "template.json"
            custom_template.write_text(
                json.dumps(template_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            first_path = root / "first.json"
            second_path = root / "second.json"
            relative_source_classification = Path(
                "adapter_service/vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json"
            )
            first = compile_rule_pack(
                TEMPLATE_DOCX,
                custom_template,
                STRUCTURE_RULES,
                first_path,
                source_classification_path=relative_source_classification,
            )
            second = compile_rule_pack(
                TEMPLATE_DOCX,
                custom_template,
                STRUCTURE_RULES,
                second_path,
                source_classification_path=relative_source_classification,
            )

            self.assertEqual(first, second)
            self.assertEqual(first["template"]["body"]["fontSize"], 13)
            self.assertEqual(
                first["algorithm"]["sourceClassification"],
                "vendor/wx_doc_format_algorithm/RULE_CLASSIFICATION.json",
            )
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_compiler_rejects_converter_only_source_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structure_rules = json.loads(STRUCTURE_RULES.read_text(encoding="utf-8"))
            structure_rules["rules"].append({
                "id": "converter.write_back",
                "algorithm": "write_back",
                "source": "wx-doc-format",
                "appliesTo": ["document"],
                "unit": "document",
                "tolerance": {},
                "severity": "error",
                "enabled": True,
            })
            structure_path = root / "structure.json"
            structure_path.write_text(
                json.dumps(structure_rules, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "STRUCTURE_RULE_CONVERTER_ONLY"):
                compile_rule_pack(TEMPLATE_DOCX, TEMPLATE_JSON, structure_path)

    def test_loader_rejects_tampered_rule_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "technical-document-template-rules.v1.0.0.json"
            compile_rule_pack(TEMPLATE_DOCX, TEMPLATE_JSON, STRUCTURE_RULES, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["template"]["roleRules"]["body"]["fontName"] = "第三方默认字体"
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(FormatRulePackError):
                FormatRulePackLoader(root).load(ACTIVE_TEMPLATE_ID)

    def test_loader_rejects_reclassified_source_rules_even_with_recomputed_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "technical-document-template-rules.v1.0.0.json"
            compile_rule_pack(TEMPLATE_DOCX, TEMPLATE_JSON, STRUCTURE_RULES, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["sourceRules"][0]["category"] = "converter-only"
            canonical = copy.deepcopy(payload)
            canonical.pop("integrity", None)
            payload["integrity"]["contentSha256"] = hashlib.sha256(
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(
                FormatRulePackError,
                "FORMAT_RULE_PACK_SOURCE_CLASSIFICATION_MISMATCH",
            ):
                FormatRulePackLoader(root).load(ACTIVE_TEMPLATE_ID)

    def test_reviewer_fails_closed_when_compiled_pack_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            request = WordDocumentRequest(
                documentId="missing-pack.docx",
                content={"paragraphs": [{"index": 1, "text": "正文"}]},
                options={"templateId": ACTIVE_TEMPLATE_ID},
            )
            with self.assertRaises(FormatRulePackError):
                WordFormatReviewer(rule_pack_loader=FormatRulePackLoader(Path(directory))).review(request)

    def test_algorithm_matches_golden_facts_and_rejects_weak_data_table_evidence(self):
        self.assertEqual(
            classify_table_fact(
                {
                    "cells": [
                        {"text": "字段", "row": 0, "column": 0, "isHeader": True},
                        {"text": "值", "row": 0, "column": 1, "isHeader": True},
                        {"text": "版本", "row": 1, "column": 0},
                        {"text": "1.0", "row": 1, "column": 1},
                    ]
                }
            )["tableType"],
            "data",
        )
        self.assertEqual(
            classify_table_fact(
                {
                    "cells": [
                        {"text": "甲", "row": 0, "column": 0},
                        {"text": "乙", "row": 0, "column": 1},
                        {"text": "丙", "row": 1, "column": 0},
                        {"text": "丁", "row": 1, "column": 1},
                    ]
                }
            )["tableType"],
            "unknown",
        )
        self.assertEqual(
            classify_table_fact(
                {"cells": [{"text": "看起来像表格"}, {"text": "但没有记录结构"}]}
            )["tableType"],
            "unknown",
        )
        self.assertEqual(
            classify_table_fact(
                {
                    "cells": [
                        {"text": "甲", "row": 0, "column": 0},
                        {"text": "乙", "row": 0, "column": 1},
                        {"text": "丙", "row": 1, "column": 0},
                        {"text": "丁", "row": 1, "column": 1},
                        {"text": "戊", "row": 2, "column": 0},
                        {"text": "己", "row": 2, "column": 1},
                    ]
                }
            )["tableType"],
            "data",
        )
        self.assertEqual(
            classify_list_fact({"numFmt": "decimal", "level": 2})["role"],
            "list_item",
        )
        self.assertEqual(
            classify_appendix_fact("附录标题", "普通正文")["role"],
            "unknown",
        )
        self.assertEqual(
            classify_note_fact("", {"numFmt": "decimal", "lvlText": "注%:"}, "")["status"],
            "needs_confirmation",
        )
        self.assertEqual(
            classify_note_fact("注-有编号注", {"numFmt": "decimal", "lvlText": "注%:"}, "注：冲突")["status"],
            "conflict",
        )
        warnings = heading_hierarchy_warnings(
            [{"level": 1, "text": "一"}, {"level": 3, "text": "三"}]
        )
        self.assertEqual(warnings[0]["type"], "heading_level_jump")

    def test_caption_association_is_bounded_and_reports_position_separately(self):
        results = associate_captions(
            [
                {"type": "heading", "sectionId": "s1", "storyId": "main"},
                {"type": "table", "objectId": "t1", "sectionId": "s1", "storyId": "main", "captionEligible": True},
                {"type": "paragraph", "sectionId": "s1", "storyId": "main"},
                {"type": "caption", "text": "表 1：测试", "sectionId": "s1", "storyId": "main"},
                {"type": "sectionBreak", "sectionId": "s2", "storyId": "main"},
                {"type": "table", "objectId": "t2", "sectionId": "s2", "storyId": "main", "captionEligible": True},
                {"type": "caption", "text": "表 2：跨节不可关联", "sectionId": "s1", "storyId": "main"},
            ]
        )
        same_section = results[0]
        self.assertEqual(same_section["status"], "associated")
        self.assertEqual(same_section["placementStatus"], "non_adjacent")
        cross_section = results[1]
        self.assertEqual(cross_section["status"], "orphaned")
        self.assertEqual(cross_section["associationStatus"], "orphaned")

    def test_caption_scope_is_required_and_figure_missing_caption_is_reported_once(self):
        unscoped = associate_captions(
            [{"type": "figure", "objectId": "f1"}, {"type": "caption", "text": "图 1：无范围"}]
        )
        self.assertEqual(unscoped[0]["status"], "orphaned")

        missing_figure = associate_captions(
            [{"type": "figure", "objectId": "f2", "sectionId": "s1", "storyId": "main"}]
        )
        self.assertEqual(missing_figure[0]["status"], "missing")

        ambiguous = associate_captions(
            [
                {"type": "table", "objectId": "t1", "captionEligible": True, "sectionId": "s1", "storyId": "main"},
                {"type": "table", "objectId": "t2", "captionEligible": True, "sectionId": "s1", "storyId": "main"},
                {"type": "caption", "text": "表 1：歧义", "sectionId": "s1", "storyId": "main"},
            ]
        )
        self.assertEqual([item["status"] for item in ambiguous], ["ambiguous"])

        missing_story_scope = associate_captions(
            [
                {"type": "figure", "objectId": "f3", "sectionId": "s1"},
                {"type": "caption", "text": "图 3：缺正文故事范围", "sectionId": "s1"},
            ]
        )
        self.assertEqual(missing_story_scope[0]["status"], "orphaned")

        duplicate_caption = associate_captions(
            [
                {"type": "figure", "objectId": "f3", "sectionId": "s1", "storyId": "main"},
                {"type": "caption", "text": "图 3：第一题注", "sectionId": "s1", "storyId": "main"},
                {"type": "caption", "text": "图 3：第二题注", "sectionId": "s1", "storyId": "main"},
            ]
        )
        self.assertEqual(len(duplicate_caption), 1)
        self.assertEqual(duplicate_caption[0]["status"], "ambiguous")
        self.assertEqual(duplicate_caption[0]["ambiguityReason"], "multiple_captions_for_object")

        incomplete_scope = associate_captions(
            [
                {"type": "figure", "objectId": "f4", "sectionId": "s1"},
                {"type": "caption", "text": "图 4：缺少正文故事范围", "sectionId": "s1"},
            ]
        )
        self.assertEqual(incomplete_scope[0]["status"], "orphaned")

        unknown_table = associate_captions(
            [
                {"type": "table", "objectId": "t3", "captionEligible": False, "sectionId": "s1", "storyId": "main"},
                {"type": "caption", "text": "表 3：未知表语义", "sectionId": "s1", "storyId": "main"},
            ]
        )
        self.assertEqual(unknown_table[0]["status"], "orphaned")

    def test_algorithm_never_supplies_template_defaults(self):
        facts = {
            "paragraphs": [
                {
                    "role": "body",
                    "roleSource": "structural",
                    "fontName": "第三方默认字体",
                    "fontSize": 10,
                }
            ]
        }
        pack = {
            "template": {
                "roleRules": {
                    "body": {"fontName": "宋体", "fontSize": 12.0}
                },
                "roleMappings": {"body": "body"},
            },
            "rules": [],
        }
        result = audit_format_facts(facts, pack)
        self.assertEqual(result["issues"][0]["expectedValue"], "宋体")
        self.assertNotEqual(result["issues"][0]["expectedValue"], "第三方默认字体")

    def test_audit_does_not_apply_same_named_rule_without_mapping(self):
        result = audit_format_facts(
            {
                "paragraphs": [
                    {
                        "blockType": "paragraph",
                        "fontName": "第三方默认字体",
                    }
                ]
            },
            {"template": {"roleRules": {"body": {"fontName": "宋体"}}}, "rules": []},
        )
        self.assertEqual(result["issues"], [])

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
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )
        result = WordFormatReviewer().review(request)
        self.assertEqual(result["summary"]["rulePackVersion"], "1.0.0")
        self.assertNotIn("templateName", result["summary"])
        self.assertEqual(result["summary"]["rulePackSourceVersion"], "wx-doc-format 0.12.15")
        self.assertEqual(len(result["summary"]["rulePackSha256"]), 64)
        self.assertEqual(result["issues"][0]["ruleVersion"], "1.0.0")
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
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )
        result = WordFormatReviewer().review(request)
        rule_ids = {issue["ruleId"] for issue in result["issues"]}
        self.assertIn("structure.heading_hierarchy", rule_ids)
        self.assertIn("structure.table_semantics", rule_ids)

    def test_confirmed_role_without_mapping_does_not_fall_back_to_body_rule(self):
        import copy

        source = FormatRulePackLoader().load(ACTIVE_TEMPLATE_ID)
        source = copy.deepcopy(source)
        source["template"]["roleMappings"] = {"body": "body", "formula": "formula"}

        class FixedLoader:
            def load(self, template_id):
                return source

        request = WordDocumentRequest(
            documentId="unconfigured-role.docx",
            content={
                "paragraphs": [{"index": 1, "text": "x", "styleName": "Normal"}],
                "documentStructure": {
                    "formatFacts": {
                        "paragraphs": [{"paragraphIndex": 1, "blockType": "formula", "text": "x"}]
                    }
                },
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )
        result = WordFormatReviewer(rule_pack_loader=FixedLoader()).review(request)
        rule_ids = {issue["ruleId"] for issue in result["issues"]}
        self.assertIn("structure.role_mapping", rule_ids)
        self.assertNotIn("style_name", rule_ids)

    def test_missing_structure_facts_require_role_confirmation(self):
        request = WordDocumentRequest(
            documentId="missing-structure-facts.docx",
            content={
                "paragraphs": [{"index": 1, "text": "正文", "styleName": "heading 1"}]
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )
        result = WordFormatReviewer().review(request)
        rule_ids = {issue["ruleId"] for issue in result["issues"]}
        self.assertIn("structure.role_confirmation", rule_ids)
        self.assertNotIn("style_name", rule_ids)

    def test_caption_association_and_placement_produce_distinct_non_duplicate_issues(self):
        request = WordDocumentRequest(
            documentId="caption-review.docx",
            content={
                "paragraphs": [{"index": 1, "text": "正文", "styleName": "Normal"}],
                "documentStructure": {
                    "formatFacts": {
                        "tables": [
                            {
                                "tableId": "t1",
                                "cells": [
                                    {"text": "字段", "row": 0, "column": 0, "isHeader": True},
                                    {"text": "值", "row": 0, "column": 1, "isHeader": True},
                                    {"text": "版本", "row": 1, "column": 0},
                                    {"text": "1", "row": 1, "column": 1},
                                ],
                            }
                        ],
                        "blocks": [
                            {"type": "table", "tableId": "t1", "sectionId": "s1", "storyId": "main"},
                            {"type": "caption", "text": "表 1：测试", "sectionId": "s1", "storyId": "main"},
                        ],
                    }
                },
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )
        result = WordFormatReviewer().review(request)
        placement_issues = [issue for issue in result["issues"] if issue["ruleId"] == "structure.caption_placement"]
        association_issues = [issue for issue in result["issues"] if issue["ruleId"] == "structure.caption_association"]
        self.assertEqual(len(placement_issues), 1)
        self.assertEqual(association_issues, [])

    def test_production_format_blocks_distinguish_caption_association_outcomes(self):
        # Break: production snapshots without handwritten sectionId/storyId
        # mark every caption orphaned and every table missing.
        result = WordFormatReviewer().review(self._production_caption_request())
        association = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.caption_association"
        ]
        placement = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.caption_placement"
        ]
        statuses = sorted(str(issue["currentValue"]) for issue in association)
        self.assertEqual(statuses, ["ambiguous", "missing", "orphaned"])
        self.assertEqual(len(placement), 1)
        self.assertEqual(placement[0]["currentValue"], "after")
        self.assertEqual(placement[0]["expectedValue"], "before")
        for issue in association + placement:
            self.assertNotIn("{", str(issue["currentValue"]))
            self.assertNotIn("孤立", str(issue["issueId"]))
            self.assertNotIn("缺失", str(issue["issueId"]))
            self.assertNotIn("歧义", str(issue["issueId"]))

    def test_caption_issue_anchors_to_caption_block_not_array_index(self):
        # Break: captionIndex (blocks subscript) is copied into paragraphIndex,
        # so "整改建议" is labelled as a figure caption.
        result = WordFormatReviewer().review(self._production_caption_request())
        caption_issues = [
            issue for issue in result["issues"]
            if issue["ruleId"] in {
                "structure.caption_association",
                "structure.caption_placement",
            }
            and issue.get("paragraphIndex") is not None
        ]
        self.assertTrue(caption_issues)
        for issue in caption_issues:
            self.assertNotEqual(issue["paragraphIndex"], 5)
            self.assertNotEqual(issue["paragraphIndex"], 4)
        placement = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.caption_placement"
        ]
        self.assertEqual(len(placement), 1)
        self.assertEqual(placement[0]["paragraphIndex"], 20)
        self.assertEqual(placement[0]["role"], "caption")

    def test_figure_image_block_associates_in_same_section_story(self):
        # Break: production image blocks are ignored because the algorithm
        # only accepts type=figure from handwritten fixtures.
        result = WordFormatReviewer().review(self._production_figure_request())
        association = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.caption_association"
        ]
        placement = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.caption_placement"
        ]
        self.assertEqual(association, [])
        self.assertEqual(placement, [])

    @staticmethod
    def _data_table_rows():
        return [
            {
                "rowIndex": 0,
                "cells": [
                    {
                        "cellId": "c00",
                        "text": "字段",
                        "rowIndex": 0,
                        "columnIndex": 0,
                        "rowSpan": 1,
                        "columnSpan": 1,
                        "isHeader": True,
                    },
                    {
                        "cellId": "c01",
                        "text": "值",
                        "rowIndex": 0,
                        "columnIndex": 1,
                        "rowSpan": 1,
                        "columnSpan": 1,
                        "isHeader": True,
                    },
                ],
            },
            {
                "rowIndex": 1,
                "cells": [
                    {
                        "cellId": "c10",
                        "text": "版本",
                        "rowIndex": 1,
                        "columnIndex": 0,
                        "rowSpan": 1,
                        "columnSpan": 1,
                    },
                    {
                        "cellId": "c11",
                        "text": "1",
                        "rowIndex": 1,
                        "columnIndex": 1,
                        "rowSpan": 1,
                        "columnSpan": 1,
                    },
                ],
            },
        ]

    def _production_table_block(self, table_id, paragraph_index, section_index):
        return {
            "blockId": "format-table-" + table_id,
            "blockType": "table",
            "tableId": table_id,
            "tableIndex": paragraph_index,
            "paragraphIndex": paragraph_index,
            "text": "字段\n值\n版本\n1",
            "rows": self._data_table_rows(),
            "nestedTables": [],
            "format": {"dataStatus": "verified"},
            "range": {"sectionIndex": section_index},
        }

    def _production_caption_request(self):
        fillers = [
            {
                "blockId": "format-paragraph-{0}".format(index),
                "blockType": "heading" if index == 5 else "paragraph",
                "paragraphIndex": index,
                "text": "整改建议" if index == 5 else "正文{0}".format(index),
                "format": {"styleName": "Normal", "dataStatus": "verified"},
                "range": {"sectionIndex": 1},
            }
            for index in range(1, 6)
        ]
        blocks = fillers + [
            self._production_table_block("t-associated", 6, 1),
            {
                "blockId": "format-paragraph-20",
                "blockType": "caption",
                "paragraphIndex": 20,
                "text": "表 1：系统架构",
                "format": {"styleName": "Caption", "dataStatus": "verified"},
                "range": {"sectionIndex": 1},
            },
        ]
        for index in range(22, 26):
            blocks.append({
                "blockId": "format-paragraph-{0}".format(index),
                "blockType": "paragraph",
                "paragraphIndex": index,
                "text": "间隔正文{0}".format(index),
                "format": {"styleName": "Normal", "dataStatus": "verified"},
                "range": {"sectionIndex": 1},
            })
        blocks.extend([
            self._production_table_block("t-missing", 26, 1),
            self._production_table_block("t-a", 30, 2),
            self._production_table_block("t-b", 31, 2),
            {
                "blockId": "format-paragraph-32",
                "blockType": "caption",
                "paragraphIndex": 32,
                "text": "表 2：歧义候选",
                "format": {"styleName": "Caption", "dataStatus": "verified"},
                "range": {"sectionIndex": 2},
            },
            {
                "blockId": "format-paragraph-40",
                "blockType": "caption",
                "paragraphIndex": 40,
                "text": "表 9：跨节孤立",
                "format": {"styleName": "Caption", "dataStatus": "verified"},
                "range": {"sectionIndex": 3},
            },
        ])
        paragraphs = [
            {
                "index": block["paragraphIndex"],
                "text": block["text"],
                "styleName": "Caption" if block["blockType"] == "caption" else "Normal",
            }
            for block in blocks
            if block["blockType"] != "table"
        ]
        return WordDocumentRequest(
            documentId="production-caption.docx",
            content={
                "paragraphs": paragraphs,
                "documentStructure": {
                    "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                    "formatBlocks": blocks,
                },
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )

    def _production_figure_request(self):
        blocks = [
            {
                "blockId": "format-image-f1",
                "blockType": "image",
                "paragraphIndex": 8,
                "text": "",
                "format": {"dataStatus": "verified"},
                "range": {"sectionIndex": 1},
                "images": [{
                    "imageId": "f1",
                    "groupId": "f1",
                    "fingerprint": "fp-f1",
                    "captionStatus": "present",
                    "associationStatus": "missing",
                    "supported": True,
                    "altText": "",
                    "nearbyText": "图 1：系统架构",
                }],
            },
            {
                "blockId": "format-paragraph-9",
                "blockType": "caption",
                "paragraphIndex": 9,
                "text": "图 1：系统架构",
                "format": {"styleName": "Caption", "dataStatus": "verified"},
                "range": {"sectionIndex": 1},
            },
        ]
        return WordDocumentRequest(
            documentId="production-figure.docx",
            content={
                "paragraphs": [{
                    "index": 9,
                    "text": "图 1：系统架构",
                    "styleName": "Caption",
                }],
                "documentStructure": {
                    "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
                    "formatBlocks": blocks,
                },
            },
            options={"templateId": ACTIVE_TEMPLATE_ID},
        )


if __name__ == "__main__":
    unittest.main()
