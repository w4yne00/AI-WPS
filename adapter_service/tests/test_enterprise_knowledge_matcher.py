import unittest

from app.core.models import DocumentReviewResponseData, RewriteResponseData
from app.services.enterprise_knowledge.models import (
    KNOWLEDGE_SCOPES,
    MAX_CELL_CHARS,
    MAX_DATABASE_BACKUPS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    MAX_PROMPT_CHARS,
    MAX_PUBLIC_MATCHED_ITEMS,
    MAX_STYLE_RULES,
    MAX_TERM_MATCHES,
    MAX_XLSX_EXPANDED_BYTES,
    PREVIEW_TTL_SECONDS,
    PRIORITIES,
    TASK_SCOPES,
    KnowledgeError,
    KnowledgeMatchResult,
    normalize_key,
    public_usage,
)


def dump_by_alias(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    return value.dict(by_alias=True)


class EnterpriseKnowledgeContractTests(unittest.TestCase):
    def test_normalize_key_collapses_case_width_and_whitespace(self):
        self.assertEqual(normalize_key(" ＡI  平台 "), "ai 平台")

    def test_old_rewrite_response_remains_valid_without_usage(self):
        value = dump_by_alias(
            RewriteResponseData(
                originalText="原文",
                rewrittenText="结果",
                rewriteMode="rewrite",
                provider="mock",
            )
        )

        self.assertIsNone(value.get("knowledgeUsage"))

    def test_public_usage_never_exposes_rule_text(self):
        usage = public_usage(
            applied=True,
            terms=1,
            styles=0,
            truncated=0,
            matched_items=[
                {
                    "id": "t1",
                    "type": "term",
                    "name": "标准名",
                    "ruleText": "secret",
                }
            ],
        )

        self.assertEqual(
            usage["matchedItems"],
            [{"id": "t1", "type": "term", "name": "标准名"}],
        )

    def test_public_usage_has_stable_fields_and_caps_matched_items(self):
        usage = public_usage(
            applied=False,
            terms=25,
            styles=9,
            truncated=4,
            matched_items=[
                {"id": f"t{index}", "type": "term", "name": f"术语{index}"}
                for index in range(25)
            ],
            degraded=True,
            degraded_reason="知识库暂时不可用",
        )

        self.assertEqual(usage["termMatchCount"], 25)
        self.assertEqual(usage["styleRuleCount"], 9)
        self.assertEqual(usage["truncatedCount"], 4)
        self.assertTrue(usage["degraded"])
        self.assertEqual(usage["degradedReason"], "知识库暂时不可用")
        self.assertEqual(len(usage["matchedItems"]), MAX_PUBLIC_MATCHED_ITEMS)

    def test_domain_constants_and_error_contract_are_stable(self):
        self.assertEqual(
            KNOWLEDGE_SCOPES,
            (
                "global",
                "word.smart_write",
                "word.smart_imitation",
                "word.document_review",
            ),
        )
        self.assertEqual(TASK_SCOPES, KNOWLEDGE_SCOPES[1:])
        self.assertEqual(PRIORITIES, ("high", "medium", "low"))
        self.assertEqual(MAX_IMPORT_BYTES, 5 * 1024 * 1024)
        self.assertEqual(MAX_IMPORT_ROWS, 5000)
        self.assertEqual(MAX_CELL_CHARS, 2000)
        self.assertEqual(MAX_XLSX_EXPANDED_BYTES, 20 * 1024 * 1024)
        self.assertEqual(MAX_TERM_MATCHES, 30)
        self.assertEqual(MAX_STYLE_RULES, 8)
        self.assertEqual(MAX_PROMPT_CHARS, 3000)
        self.assertEqual(PREVIEW_TTL_SECONDS, 600)
        self.assertEqual(MAX_DATABASE_BACKUPS, 3)

        error = KnowledgeError("invalid_scope", "知识范围无效")
        self.assertEqual(error.code, "invalid_scope")
        self.assertEqual(error.message, "知识范围无效")
        self.assertEqual(str(error), "知识范围无效")

    def test_match_result_detaches_from_mutable_constructor_values(self):
        usage = {
            "applied": True,
            "matchedItems": [{"id": "t1", "type": "term", "name": "标准名"}],
        }
        diagnostic = {"knowledgeItemIds": ["t1"]}
        result = KnowledgeMatchResult(
            prompt_block="企业规范",
            usage=usage,
            matched_item_ids=("t1",),
            diagnostic=diagnostic,
        )

        usage["matchedItems"][0]["name"] = "被篡改"
        usage["matchedItems"].append({"id": "t2", "type": "term", "name": "新增"})
        diagnostic["knowledgeItemIds"].append("t2")

        self.assertEqual(result.usage["matchedItems"][0]["name"], "标准名")
        self.assertEqual(len(result.usage["matchedItems"]), 1)
        self.assertEqual(result.diagnostic["knowledgeItemIds"], ["t1"])

    def test_match_result_returns_defensive_deep_copies(self):
        result = KnowledgeMatchResult(
            prompt_block="企业规范",
            usage={
                "applied": True,
                "matchedItems": [{"id": "t1", "type": "term", "name": "标准名"}],
            },
            matched_item_ids=("t1",),
            diagnostic={"knowledgeItemIds": ["t1"]},
        )

        usage_view = result.usage
        usage_view["matchedItems"][0]["name"] = "被篡改"
        usage_view["matchedItems"].append({"id": "t2", "type": "term", "name": "新增"})
        diagnostic_patch = result.diagnostic_patch()
        diagnostic_patch["knowledgeItemIds"].append("t2")

        self.assertEqual(result.usage["matchedItems"][0]["name"], "标准名")
        self.assertEqual(len(result.usage["matchedItems"]), 1)
        self.assertEqual(result.diagnostic_patch()["knowledgeItemIds"], ["t1"])

    def test_document_review_accepts_aliased_usage_metadata(self):
        value = dump_by_alias(
            DocumentReviewResponseData(
                documentType="technical_solution",
                reviewPrompt="检查专业性",
                summary="未发现问题",
                knowledgeUsage={
                    "applied": True,
                    "termMatchCount": 1,
                    "styleRuleCount": 0,
                    "truncatedCount": 0,
                    "matchedItems": [
                        {"id": "t1", "type": "term", "name": "标准名"}
                    ],
                },
            )
        )

        self.assertEqual(value["knowledgeUsage"]["termMatchCount"], 1)
        self.assertEqual(
            value["knowledgeUsage"]["matchedItems"],
            [{"id": "t1", "type": "term", "name": "标准名"}],
        )


if __name__ == "__main__":
    unittest.main()
