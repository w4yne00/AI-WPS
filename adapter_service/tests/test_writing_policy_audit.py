import unittest

from app.services.writing_policy.audit import audit_writing_policy_result


class WritingPolicyAuditTests(unittest.TestCase):
    def test_changed_protected_values_subjects_and_terms_need_review(self):
        terms = [
            {
                "id": "term.cyber.key",
                "type": "term",
                "preferredText": "密钥",
                "aliases": [],
                "forbiddenVariants": ["秘钥"],
            }
        ]
        audit = audit_writing_policy_result(
            "信息化部门负责在 2026年7月25日前完成 3 项整改，并统一使用密钥。",
            "相关部门负责在 2026年8月1日前完成 4 项整改，并统一使用秘钥。",
            terms,
        )

        self.assertFalse(audit["passed"])
        self.assertFalse(audit["degraded"])
        codes = {item["code"] for item in audit["needsReview"]}
        self.assertIn("protected_number_changed", codes)
        self.assertIn("responsibility_subject_changed", codes)
        self.assertIn("nonstandard_term", codes)
        self.assertEqual(audit["expressionSuggestions"], [])
        self.assertEqual(audit["summary"], "写作规范检查发现需要人工核对的内容。")

    def test_explicit_tier_patterns_return_expression_suggestions(self):
        audit = audit_writing_policy_result(
            "请说明实施安排。",
            (
                "值得注意的是，本方案不仅提升能力，更赋能发展。"
                "首先强化基础，其次完善机制，再次优化流程，最后开创崭新局面。"
            ),
            [],
        )

        self.assertFalse(audit["passed"])
        tiers = {item["tier"] for item in audit["expressionSuggestions"]}
        self.assertEqual(tiers, {"T1", "T2", "T3"})
        self.assertEqual(audit["needsReview"], [])
        self.assertEqual(audit["summary"], "写作规范检查提供了表达优化建议。")

    def test_changed_explicit_proper_nouns_and_identifiers_need_review(self):
        audit = audit_writing_policy_result(
            "运维部门负责部署天穹系统，并保持设备型号 NX-2026。",
            "运维部门负责部署苍穹系统，并保持设备型号 NX-2027。",
            [],
        )

        codes = {item["code"] for item in audit["needsReview"]}
        self.assertIn("protected_proper_noun_changed", codes)
        self.assertIn("protected_identifier_changed", codes)

    def test_unchanged_protected_content_returns_one_line_passed_state(self):
        audit = audit_writing_policy_result(
            "信息化部门必须在 2026年7月25日前完成整改。",
            "信息化部门必须在 2026年7月25日前完成整改并提交记录。",
            [],
        )

        self.assertTrue(audit["passed"])
        self.assertFalse(audit["degraded"])
        self.assertEqual(audit["needsReview"], [])
        self.assertEqual(audit["expressionSuggestions"], [])
        self.assertEqual(audit["summary"], "已完成写作规范检查")
        serialized = str(audit)
        self.assertNotIn("AI 生成", serialized)
        self.assertNotIn("作者身份", serialized)

    def test_findings_and_evidence_are_bounded(self):
        source = " ".join("%d 项" % index for index in range(50))
        result = " ".join("%d 项" % (index + 100) for index in range(50))

        audit = audit_writing_policy_result(source, result, [])

        self.assertLessEqual(len(audit["needsReview"]), 12)
        self.assertTrue(
            all(
                len(item.get("evidence", "")) <= 80
                for item in audit["needsReview"]
            )
        )


if __name__ == "__main__":
    unittest.main()
