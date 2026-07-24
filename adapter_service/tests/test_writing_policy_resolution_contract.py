import unittest

from app.services.writing_policy.audit import audit_writing_policy_result
from app.services.writing_policy.matcher import build_match_result
from app.services.writing_policy.models import MAX_PROMPT_CHARS


def _style(
    item_id,
    name,
    item_type="style",
    layer="preset",
    priority="medium",
    scope="word.smart_write",
):
    return {
        "id": item_id,
        "type": item_type,
        "scope": scope,
        "category": "去模板化" if item_type == "anti_template" else "成文质量",
        "name": name,
        "ruleText": "%s 的完整规则正文。" % name,
        "positiveExample": "",
        "negativeExample": "",
        "contextKeywords": [],
        "alwaysApply": True,
        "priority": priority,
        "enabled": True,
        "layer": layer,
    }


def _term(item_id, preferred_text, layer, aliases=None):
    return {
        "id": item_id,
        "type": "term",
        "preferredText": preferred_text,
        "aliases": list(aliases or []),
        "forbiddenVariants": [],
        "definition": "%s 的术语说明。" % preferred_text,
        "priority": "medium",
        "enabled": True,
        "layer": layer,
        "packId": "preset-pack" if layer == "preset" else "",
    }


class WritingPolicyResolutionContractTests(unittest.TestCase):
    def test_prompt_declares_fixed_precedence_and_orders_layers(self):
        protected = _style(
            "rule.protected",
            "保护数字和责任主体",
            layer="preset",
            priority="low",
        )
        protected["category"] = "保护项"
        organization = _style(
            "rule.organization",
            "组织明确要求",
            layer="organization",
            priority="low",
            scope="global",
        )
        preset = _style(
            "rule.preset",
            "预置文体要求",
            layer="preset",
            priority="high",
        )
        anti_template = _style(
            "rule.anti",
            "删除空泛铺垫",
            item_type="anti_template",
            layer="preset",
            priority="high",
        )

        result = build_match_result(
            [],
            [anti_template, preset, organization, protected],
            "word.smart_write",
            ["原文含数字 2026 和责任主体。"],
        )

        self.assertIn("1. 保护项", result.prompt_block)
        self.assertIn("2. 用户本次明确要求", result.prompt_block)
        self.assertLess(
            result.prompt_block.index("保护数字和责任主体"),
            result.prompt_block.index("组织明确要求"),
        )
        self.assertLess(
            result.prompt_block.index("组织明确要求"),
            result.prompt_block.index("预置文体要求"),
        )
        self.assertLess(
            result.prompt_block.index("预置文体要求"),
            result.prompt_block.index("删除空泛铺垫"),
        )

    def test_organization_terms_replace_conflicting_preset_terms(self):
        organization = _term(
            "term.organization",
            "Zulu organization term",
            "organization",
            aliases=["共同写法"],
        )
        preset = _term(
            "term.preset",
            "Alpha preset term",
            "preset",
            aliases=["共同写法"],
        )

        result = build_match_result(
            [preset, organization],
            [],
            "word.smart_write",
            ["请统一使用共同写法。"],
        )

        self.assertIn("Zulu organization term", result.prompt_block)
        self.assertNotIn("Alpha preset term", result.prompt_block)

    def test_organization_rule_replaces_same_name_task_preset_rule(self):
        organization = _style(
            "rule.organization",
            "统一责任表达",
            layer="organization",
            scope="global",
        )
        organization["ruleText"] = "使用组织确定的责任表达。"
        preset = _style(
            "rule.preset",
            "统一责任表达",
            layer="preset",
            scope="word.smart_write",
        )
        preset["ruleText"] = "使用产品预置的责任表达。"

        result = build_match_result(
            [],
            [preset, organization],
            "word.smart_write",
            ["请明确责任主体。"],
        )

        self.assertIn("使用组织确定的责任表达", result.prompt_block)
        self.assertNotIn("使用产品预置的责任表达", result.prompt_block)

    def test_rule_reservation_never_displaces_higher_precedence_organization_rules(self):
        organization_styles = [
            _style(
                "rule.organization.%02d" % index,
                "组织规则 %02d" % index,
                layer="organization",
            )
            for index in range(8)
        ]
        preset_anti_templates = [
            _style(
                "rule.anti.%02d" % index,
                "通用去模板化 %02d" % index,
                item_type="anti_template",
                layer="preset",
            )
            for index in range(3)
        ]

        result = build_match_result(
            [],
            organization_styles + preset_anti_templates,
            "word.smart_write",
            ["需要按组织规则改写。"],
        )

        self.assertEqual(result.usage["styleRuleCount"], 8)
        self.assertEqual(result.usage["antiTemplateRuleCount"], 0)
        self.assertNotIn("通用去模板化 00：", result.prompt_block)

    def test_prompt_reserves_five_style_and_three_anti_template_slots(self):
        styles = [
            _style("rule.style.%02d" % index, "文体规则 %02d" % index)
            for index in range(10)
        ]
        anti_templates = [
            _style(
                "rule.anti.%02d" % index,
                "去模板化规则 %02d" % index,
                item_type="anti_template",
            )
            for index in range(10)
        ]

        result = build_match_result(
            [],
            styles + anti_templates,
            "word.smart_write",
            ["需要正式改写。"],
        )

        self.assertEqual(result.usage["styleRuleCount"], 5)
        self.assertEqual(result.usage["antiTemplateRuleCount"], 3)
        self.assertEqual(len(result.matched_item_ids), 8)
        self.assertEqual(result.usage["truncatedCount"], 12)
        self.assertLessEqual(len(result.prompt_block), MAX_PROMPT_CHARS)
        self.assertIn("[文体]", result.prompt_block)
        self.assertIn("[去模板化]", result.prompt_block)

    def test_unused_rule_reservation_is_available_to_the_other_rule_type(self):
        styles = [
            _style("rule.style.%02d" % index, "文体规则 %02d" % index)
            for index in range(2)
        ]
        anti_templates = [
            _style(
                "rule.anti.%02d" % index,
                "去模板化规则 %02d" % index,
                item_type="anti_template",
            )
            for index in range(10)
        ]

        result = build_match_result(
            [],
            styles + anti_templates,
            "word.smart_write",
            ["需要正式改写。"],
        )

        self.assertEqual(result.usage["styleRuleCount"], 2)
        self.assertEqual(result.usage["antiTemplateRuleCount"], 6)
        self.assertEqual(len(result.matched_item_ids), 8)

    def test_audit_keeps_bounded_matched_terms_truncated_from_prompt_char_budget(self):
        first = _term("term.first", "标准术语甲", "organization")
        second = _term("term.second", "标准术语乙", "organization")
        first["definition"] = "甲" * 1800
        second["definition"] = "乙" * 1800

        result = build_match_result(
            [first, second],
            [],
            "word.smart_write",
            ["标准术语甲和标准术语乙均需保持。"],
        )
        audit = audit_writing_policy_result(
            "标准术语甲和标准术语乙均需保持。",
            "标准术语甲需保持。",
            result.audit_terms,
        )

        self.assertEqual(result.usage["termMatchCount"], 1)
        self.assertEqual(len(result.audit_terms), 2)
        self.assertIn(
            "standard_term_changed",
            {item["code"] for item in audit["needsReview"]},
        )


if __name__ == "__main__":
    unittest.main()
