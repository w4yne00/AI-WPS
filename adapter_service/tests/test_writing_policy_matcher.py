import time
import unittest
from unittest import mock

from app.core.models import DocumentReviewResponseData, RewriteResponseData
from app.services.writing_policy import matcher as matcher_module
from app.services.writing_policy.matcher import build_match_result
from app.services.writing_policy.models import (
    WRITING_POLICY_SCOPES,
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
    WritingPolicyError,
    WritingPolicyMatchResult,
    normalize_key,
    public_usage,
)


def term_item(
    item_id,
    preferred_text,
    aliases=None,
    forbidden=None,
    priority="medium",
    **overrides
):
    item = {
        "id": item_id,
        "type": "term",
        "scope": "global",
        "category": "系统",
        "preferredText": preferred_text,
        "aliases": list(aliases or []),
        "forbiddenVariants": list(forbidden or []),
        "definition": "",
        "contextKeywords": [],
        "priority": priority,
        "enabled": True,
        "note": "",
    }
    item.update(overrides)
    return item


def style_item(
    item_id,
    scope,
    name,
    rule_text,
    keywords=None,
    always_apply=False,
    priority="medium",
    **overrides
):
    item = {
        "id": item_id,
        "type": "style",
        "scope": scope,
        "name": name,
        "ruleText": rule_text,
        "positiveExample": "",
        "negativeExample": "",
        "contextKeywords": list(keywords or []),
        "alwaysApply": always_apply,
        "priority": priority,
        "enabled": True,
        "note": "",
    }
    item.update(overrides)
    return item


def base36_code(value):
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, len(alphabet))
        encoded = alphabet[remainder] + encoded
    return (encoded or "0").rjust(4, "0")


def dump_by_alias(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    return value.dict(by_alias=True)


class WritingPolicyContractTests(unittest.TestCase):
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

        self.assertIsNone(value.get("writingPolicyUsage"))

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
            degraded_reason="规范库暂时不可用",
        )

        self.assertEqual(usage["termMatchCount"], 25)
        self.assertEqual(usage["styleRuleCount"], 9)
        self.assertEqual(usage["truncatedCount"], 4)
        self.assertTrue(usage["degraded"])
        self.assertEqual(usage["degradedReason"], "规范库暂时不可用")
        self.assertEqual(len(usage["matchedItems"]), MAX_PUBLIC_MATCHED_ITEMS)

    def test_domain_constants_and_error_contract_are_stable(self):
        self.assertEqual(
            WRITING_POLICY_SCOPES,
            (
                "global",
                "word.smart_write",
                "word.smart_imitation",
                "word.document_review",
            ),
        )
        self.assertEqual(TASK_SCOPES, WRITING_POLICY_SCOPES[1:])
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

        error = WritingPolicyError("invalid_scope", "写作规范范围无效")
        self.assertEqual(error.code, "invalid_scope")
        self.assertEqual(error.message, "写作规范范围无效")
        self.assertEqual(str(error), "写作规范范围无效")

    def test_match_result_detaches_from_mutable_constructor_values(self):
        usage = {
            "applied": True,
            "matchedItems": [{"id": "t1", "type": "term", "name": "标准名"}],
        }
        diagnostic = {"writingPolicyItemIds": ["t1"]}
        result = WritingPolicyMatchResult(
            prompt_block="企业规范",
            usage=usage,
            matched_item_ids=("t1",),
            diagnostic=diagnostic,
        )

        usage["matchedItems"][0]["name"] = "被篡改"
        usage["matchedItems"].append({"id": "t2", "type": "term", "name": "新增"})
        diagnostic["writingPolicyItemIds"].append("t2")

        self.assertEqual(result.usage["matchedItems"][0]["name"], "标准名")
        self.assertEqual(len(result.usage["matchedItems"]), 1)
        self.assertEqual(result.diagnostic["writingPolicyItemIds"], ["t1"])

    def test_match_result_returns_defensive_deep_copies(self):
        result = WritingPolicyMatchResult(
            prompt_block="企业规范",
            usage={
                "applied": True,
                "matchedItems": [{"id": "t1", "type": "term", "name": "标准名"}],
            },
            matched_item_ids=("t1",),
            diagnostic={"writingPolicyItemIds": ["t1"]},
        )

        usage_view = result.usage
        usage_view["matchedItems"][0]["name"] = "被篡改"
        usage_view["matchedItems"].append({"id": "t2", "type": "term", "name": "新增"})
        diagnostic_patch = result.diagnostic_patch()
        diagnostic_patch["writingPolicyItemIds"].append("t2")

        self.assertEqual(result.usage["matchedItems"][0]["name"], "标准名")
        self.assertEqual(len(result.usage["matchedItems"]), 1)
        self.assertEqual(result.diagnostic_patch()["writingPolicyItemIds"], ["t1"])

    def test_document_review_accepts_aliased_usage_metadata(self):
        value = dump_by_alias(
            DocumentReviewResponseData(
                documentType="technical_solution",
                reviewPrompt="检查专业性",
                summary="未发现问题",
                writingPolicyUsage={
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

        self.assertEqual(value["writingPolicyUsage"]["termMatchCount"], 1)
        self.assertEqual(
            value["writingPolicyUsage"]["matchedItems"],
            [{"id": "t1", "type": "term", "name": "标准名"}],
        )


class WritingPolicyMatcherTests(unittest.TestCase):
    def test_near_import_limit_matching_scans_large_source_within_budget(self):
        near_match_prefix = "甲" * 24
        terms = []
        for term_index in range(5000):
            preferred = "%s丙%04d" % (near_match_prefix, term_index)
            if term_index == 0:
                preferred = "命中术语"
            terms.append(
                term_item(
                    "perf-%04d" % term_index,
                    preferred,
                    aliases=[
                        "%s乙%04d%02d" % (
                            near_match_prefix,
                            term_index,
                            alias_index,
                        )
                        for alias_index in range(20)
                    ],
                )
            )
        source = ("甲" * 100000) + " 命中术语"

        started = time.perf_counter()
        result = build_match_result(terms, [], "word.smart_write", [source])
        elapsed = time.perf_counter() - started

        self.assertEqual(result.matched_item_ids, ("perf-0000",))
        self.assertLess(
            elapsed,
            8.0,
            "near-limit matching took %.3fs; expected one-pass literal scanning"
            % elapsed,
        )

    def test_near_import_limit_style_keywords_match_within_budget(self):
        near_match_prefix = "甲" * 24
        styles = []
        for style_index in range(5000):
            keywords = [
                "%s乙%04d%02d" % (
                    near_match_prefix,
                    style_index,
                    keyword_index,
                )
                for keyword_index in range(20)
            ]
            if style_index == 0:
                keywords[0] = "命中关键词"
            styles.append(
                style_item(
                    "style-perf-%04d" % style_index,
                    "global",
                    "性能规则-%04d" % style_index,
                    "规则正文-%04d" % style_index,
                    keywords=keywords,
                )
            )
        source = ("甲" * 100000) + " 命中关键词"

        started = time.perf_counter()
        result = build_match_result([], styles, "word.smart_write", [source])
        elapsed = time.perf_counter() - started

        self.assertEqual(result.matched_item_ids, ("style-perf-0000",))
        self.assertLess(
            elapsed,
            8.0,
            "near-limit style matching took %.3fs; expected batched literal scanning"
            % elapsed,
        )

    def test_distributed_term_candidates_are_filtered_before_index_build(self):
        terms = []
        for term_index in range(5000):
            aliases = [
                "%s-term-token" % base36_code((term_index * 20) + alias_index)
                for alias_index in range(20)
            ]
            if term_index == 0:
                aliases[0] = "唯一术语命中"
            terms.append(
                term_item(
                    "filtered-term-%04d" % term_index,
                    "p-%s-preferred" % base36_code(term_index),
                    aliases=aliases,
                )
            )
        source = ("正文" * 50000) + " 唯一术语命中"
        token_counts = []
        state_counts = []
        original_index = matcher_module._LiteralIndex

        class RecordingIndex(original_index):
            def __init__(self, token_targets):
                super().__init__(token_targets)
                token_counts.append(len(token_targets))
                state_counts.append(self.state_count)

        started = time.perf_counter()
        with mock.patch.object(matcher_module, "_LiteralIndex", RecordingIndex):
            matched_terms, _matched_styles = matcher_module.match_writing_policy(
                terms, [], "word.smart_write", [source]
            )
        elapsed = time.perf_counter() - started

        self.assertEqual(
            token_counts,
            [1],
            "term prefilter passed %d tokens to indexes in %.3fs"
            % (sum(token_counts), elapsed),
        )
        self.assertEqual(state_counts, [7])
        self.assertEqual(
            [item["id"] for item in matched_terms], ["filtered-term-0000"]
        )
        self.assertLess(elapsed, 8.0)

    def test_distributed_style_candidates_are_filtered_before_index_build(self):
        styles = []
        for style_index in range(5000):
            keywords = [
                "%s-style-token" % base36_code((style_index * 20) + keyword_index)
                for keyword_index in range(20)
            ]
            if style_index == 0:
                keywords[0] = "唯一风格命中"
            styles.append(
                style_item(
                    "filtered-style-%04d" % style_index,
                    "global",
                    "过滤规则-%04d" % style_index,
                    "过滤规则正文-%04d" % style_index,
                    keywords=keywords,
                )
            )
        source = ("正文" * 50000) + " 唯一风格命中"
        token_counts = []
        state_counts = []
        original_index = matcher_module._LiteralIndex

        class RecordingIndex(original_index):
            def __init__(self, token_targets):
                super().__init__(token_targets)
                token_counts.append(len(token_targets))
                state_counts.append(self.state_count)

        started = time.perf_counter()
        with mock.patch.object(matcher_module, "_LiteralIndex", RecordingIndex):
            matched_terms, matched_styles = matcher_module.match_writing_policy(
                [], styles, "word.smart_write", [source]
            )
        elapsed = time.perf_counter() - started

        self.assertEqual(matched_terms, [])
        self.assertEqual(
            token_counts,
            [1],
            "style prefilter passed %d tokens to indexes in %.3fs"
            % (sum(token_counts), elapsed),
        )
        self.assertEqual(state_counts, [7])
        self.assertEqual(
            [item["id"] for item in matched_styles], ["filtered-style-0000"]
        )
        self.assertLess(elapsed, 8.0)

    def test_prefix_filter_preserves_short_nfkc_and_cross_space_matches(self):
        terms = [
            term_item("short-1", "甲"),
            term_item("short-2", "未命中二", aliases=["乙乙"]),
            term_item("short-3", "未命中三", forbidden=["丙丙丙"]),
            term_item("nfkc-space", "AI 平台", aliases=["ＡＩ   平台"]),
        ]
        styles = [
            style_item("style-1", "global", "单字", "单字规则", keywords=["丁"]),
            style_item("style-2", "global", "双字", "双字规则", keywords=["戊戊"]),
            style_item(
                "style-3", "global", "三字", "三字规则", keywords=["己己己"]
            ),
            style_item(
                "style-4", "global", "四字", "四字规则", keywords=["ＡＢＣＤ"]
            ),
        ]

        matched_terms, matched_styles = matcher_module.match_writing_policy(
            terms,
            styles,
            "word.smart_write",
            ["甲 乙乙 丙丙丙", "", "AI", "平台 丁 戊戊 己己己 abcd"],
        )

        self.assertEqual(
            {item["id"] for item in matched_terms},
            {"short-1", "short-2", "short-3", "nfkc-space"},
        )
        self.assertEqual(
            {item["id"] for item in matched_styles},
            {"style-1", "style-2", "style-3", "style-4"},
        )

    def test_short_prefix_filter_uses_source_characters_and_skips_empty_source(self):
        terms = [
            term_item("short-hit", "甲"),
            term_item("short-miss-1", "乙"),
            term_item("short-miss-2", "未命中", aliases=["丙丙"]),
            term_item("short-miss-3", "未命中", forbidden=["丁丁丁"]),
        ]
        recorded_tokens = []
        original_index = matcher_module._LiteralIndex

        class RecordingIndex(original_index):
            def __init__(self, token_targets):
                recorded_tokens.append(sorted(token_targets))
                super().__init__(token_targets)

        with mock.patch.object(matcher_module, "_LiteralIndex", RecordingIndex):
            matched_terms, _matched_styles = matcher_module.match_writing_policy(
                terms, [], "word.smart_write", ["甲"]
            )

        self.assertEqual(recorded_tokens, [["甲"]])
        self.assertEqual([item["id"] for item in matched_terms], ["short-hit"])

        styles = [
            style_item(
                "empty-style", "global", "空正文", "不得命中", keywords=["戊"]
            )
        ]
        with mock.patch.object(
            matcher_module,
            "_LiteralIndex",
            side_effect=AssertionError("empty source must not build an index"),
        ):
            empty_terms, empty_styles = matcher_module.match_writing_policy(
                terms, styles, "word.smart_write", ["", ""]
            )

        self.assertEqual(empty_terms, [])
        self.assertEqual(empty_styles, [])

    def test_distributed_tokens_use_bounded_indexes_and_match_batch_boundaries(self):
        terms = [
            term_item(
                "batch-%04d" % index,
                "分散-%04d-%s" % (index, "甲" * 50),
            )
            for index in range(2200)
        ]
        source = "%s %s %s" % (
            " ".join(item["preferredText"][:8] for item in terms),
            terms[1700]["preferredText"],
            terms[1800]["preferredText"],
        )
        state_counts = []
        original_index = matcher_module._LiteralIndex

        class RecordingIndex(original_index):
            def __init__(self, token_targets):
                super().__init__(token_targets)
                state_counts.append(self.state_count)

        with mock.patch.object(matcher_module, "_LiteralIndex", RecordingIndex):
            matched_terms, _matched_styles = matcher_module.match_writing_policy(
                terms, [], "word.smart_write", [source]
            )

        self.assertGreater(len(state_counts), 1)
        self.assertLessEqual(max(state_counts), 100001)
        self.assertEqual(
            [item["id"] for item in matched_terms],
            ["batch-1700", "batch-1800"],
        )

    def test_style_index_preserves_always_keyword_and_task_override_semantics(self):
        styles = [
            style_item(
                "global-overridden",
                "global",
                "结论先行",
                "不应回退的全局规则",
                always_apply=True,
            ),
            style_item(
                "task-miss",
                "word.smart_write",
                "结论先行",
                "关键词未命中的任务规则",
                keywords=["未命中关键词"],
            ),
            style_item(
                "always",
                "global",
                "简洁表达",
                "始终应用规则",
                always_apply=True,
            ),
            style_item(
                "keyword-hit",
                "global",
                "项目表达",
                "关键词命中规则",
                keywords=["项目汇报"],
            ),
            style_item(
                "keyword-miss",
                "global",
                "合同表达",
                "不应出现规则",
                keywords=["合同验收"],
            ),
        ]

        result = build_match_result(
            [], styles, "word.smart_write", ["项目汇报正文"]
        )

        self.assertEqual(set(result.matched_item_ids), {"always", "keyword-hit"})
        self.assertIn("始终应用规则", result.prompt_block)
        self.assertIn("关键词命中规则", result.prompt_block)
        self.assertNotIn("不应回退的全局规则", result.prompt_block)
        self.assertNotIn("关键词未命中的任务规则", result.prompt_block)
        self.assertNotIn("不应出现规则", result.prompt_block)

    def test_prefix_and_duplicate_tokens_use_compact_terminal_storage(self):
        token_count = 800
        token_targets = {
            ("前" * length) + "终": {(length, 1)}
            for length in range(1, token_count + 1)
        }

        index = matcher_module._LiteralIndex(token_targets)

        self.assertLessEqual(index.state_count, (2 * token_count) + 1)
        self.assertEqual(index.token_count, token_count)
        self.assertEqual(index.terminal_payload_count, token_count)

    def test_prefix_and_duplicate_tokens_match_each_item_once(self):
        prefix_count = 800
        terms = [
            term_item(
                "prefix-%04d" % length,
                "未命中-%04d" % length,
                aliases=[("前" * length) + "终", ("前" * length) + "终"],
            )
            for length in range(1, prefix_count + 1)
        ]
        terms.extend(
            term_item(
                "shared-%04d" % index,
                "共享标准-%04d" % index,
                aliases=["共享词", "共享词"],
            )
            for index in range(50)
        )

        matched_terms, _matched_styles = matcher_module.match_writing_policy(
            terms,
            [],
            "word.smart_write",
            [("前" * prefix_count) + "终 共享词"],
        )

        self.assertEqual(len(matched_terms), prefix_count + 50)
        self.assertEqual(
            len({item["id"] for item in matched_terms}), prefix_count + 50
        )

    def test_duplicate_term_id_uses_full_payload_tie_break(self):
        definition_a = term_item(
            "dirty-term", "标准名称", definition="definition-a"
        )
        definition_b = term_item(
            "dirty-term", "标准名称", definition="definition-b"
        )

        first = build_match_result(
            [definition_b, definition_a], [], "word.smart_write", ["标准名称"]
        )
        second = build_match_result(
            [definition_a, definition_b], [], "word.smart_write", ["标准名称"]
        )

        self.assertEqual(first.prompt_block, second.prompt_block)
        self.assertEqual(first.usage, second.usage)
        self.assertIn("definition-a", first.prompt_block)
        self.assertNotIn("definition-b", first.prompt_block)

    def test_duplicate_style_key_uses_full_payload_tie_break(self):
        rule_a = style_item(
            "dirty-style",
            "global",
            "结论先行",
            "rule-a",
            always_apply=True,
        )
        rule_b = style_item(
            "dirty-style",
            "global",
            "结论先行",
            "rule-b",
            always_apply=True,
        )

        first = build_match_result(
            [], [rule_b, rule_a], "word.smart_write", ["普通正文"]
        )
        second = build_match_result(
            [], [rule_a, rule_b], "word.smart_write", ["普通正文"]
        )

        self.assertEqual(first.prompt_block, second.prompt_block)
        self.assertEqual(first.usage, second.usage)
        self.assertIn("rule-a", first.prompt_block)
        self.assertNotIn("rule-b", first.prompt_block)

    def test_alias_and_forbidden_variant_match_once(self):
        terms = [
            term_item(
                "t1",
                "标准名称",
                aliases=["旧名称"],
                forbidden=["错误名称"],
                priority="high",
            )
        ]

        result = build_match_result(
            terms, [], "word.smart_write", ["旧名称与错误名称均出现"]
        )

        self.assertEqual(result.usage["termMatchCount"], 1)
        self.assertEqual(result.matched_item_ids, ("t1",))
        self.assertIn("标准名称", result.prompt_block)

    def test_term_order_uses_match_class_priority_normalized_name_and_id(self):
        terms = [
            term_item("t-forbidden", "戊", forbidden=["禁用命中"], priority="high"),
            term_item("t-alias", "丁", aliases=["别名命中"], priority="high"),
            term_item("t-low", "甲", priority="low"),
            term_item("t-z", "乙", priority="high"),
            term_item("t-b", "丙", priority="high"),
            term_item("t-a", "丙", priority="high"),
        ]
        source = "甲乙丙 别名命中 禁用命中"

        result = build_match_result(terms, [], "word.smart_write", [source])

        self.assertEqual(
            result.matched_item_ids,
            ("t-a", "t-b", "t-z", "t-low", "t-alias", "t-forbidden"),
        )

    def test_input_order_does_not_change_result(self):
        terms = [
            term_item("t2", "乙", aliases=["旧乙"], priority="low"),
            term_item("t1", "甲", aliases=["旧甲"], priority="high"),
        ]
        styles = [
            style_item("s2", "global", "规则乙", "规则正文乙", always_apply=True),
            style_item(
                "s1",
                "word.smart_write",
                "规则甲",
                "规则正文甲",
                always_apply=True,
            ),
        ]

        first = build_match_result(
            terms, styles, "word.smart_write", ["旧甲和旧乙"]
        )
        second = build_match_result(
            list(reversed(terms)),
            list(reversed(styles)),
            "word.smart_write",
            ["旧甲和旧乙"],
        )

        self.assertEqual(first.prompt_block, second.prompt_block)
        self.assertEqual(first.usage, second.usage)
        self.assertEqual(first.matched_item_ids, second.matched_item_ids)

    def test_nfkc_normalization_applies_to_terms_and_keywords(self):
        terms = [term_item("t1", "AI 平台", aliases=["ＡＩ　平台"])]
        styles = [
            style_item(
                "s1",
                "global",
                "英文规范",
                "统一英文大小写。",
                keywords=["ＰＲＯＪＥＣＴ　Ａ"],
            )
        ]

        result = build_match_result(
            terms, styles, "word.smart_write", ["ai 平台用于 project a"]
        )

        self.assertEqual(result.usage["termMatchCount"], 1)
        self.assertEqual(result.usage["styleRuleCount"], 1)

    def test_task_style_replaces_same_normalized_global_style(self):
        styles = [
            style_item(
                "s1", "global", "ＡＩ 规范", "全局规则", always_apply=True
            ),
            style_item(
                "s2",
                "word.smart_write",
                "ai 规范",
                "任务规则",
                always_apply=True,
            ),
        ]

        result = build_match_result([], styles, "word.smart_write", ["项目汇报"])

        self.assertEqual(result.matched_item_ids, ("s2",))
        self.assertIn("任务规则", result.prompt_block)
        self.assertNotIn("全局规则", result.prompt_block)

    def test_task_style_override_happens_before_keyword_qualification(self):
        styles = [
            style_item(
                "s1", "global", "结论先行", "全局规则", always_apply=True
            ),
            style_item(
                "s2",
                "word.smart_write",
                "结论先行",
                "任务规则",
                keywords=["项目汇报"],
            ),
        ]

        result = build_match_result([], styles, "word.smart_write", ["普通正文"])

        self.assertEqual(result.usage["styleRuleCount"], 0)
        self.assertNotIn("全局规则", result.prompt_block)

    def test_task_styles_rank_before_global_styles(self):
        styles = [
            style_item(
                "global-high",
                "global",
                "全局高优先级",
                "全局规则",
                always_apply=True,
                priority="high",
            ),
            style_item(
                "task-low",
                "word.smart_write",
                "任务低优先级",
                "任务规则",
                always_apply=True,
                priority="low",
            ),
        ]

        result = build_match_result([], styles, "word.smart_write", ["正文"])

        self.assertEqual(result.matched_item_ids, ("task-low", "global-high"))

    def test_always_apply_and_keyword_qualification_are_both_supported(self):
        styles = [
            style_item("always", "global", "始终应用", "始终规则", always_apply=True),
            style_item(
                "keyword-hit",
                "global",
                "关键词命中",
                "命中规则",
                keywords=["项目汇报"],
            ),
            style_item(
                "keyword-miss",
                "global",
                "关键词未命中",
                "不应出现",
                keywords=["合同验收"],
            ),
        ]

        result = build_match_result(
            [], styles, "word.smart_write", ["", "项目汇报材料"]
        )

        self.assertEqual(result.usage["styleRuleCount"], 2)
        self.assertIn("始终规则", result.prompt_block)
        self.assertIn("命中规则", result.prompt_block)
        self.assertNotIn("不应出现", result.prompt_block)

    def test_term_style_and_public_item_limits_count_every_truncation(self):
        terms = [
            term_item("t%d" % index, "名称%d" % index, aliases=["命中%d" % index])
            for index in range(35)
        ]
        styles = [
            style_item(
                "s%d" % index,
                "global",
                "规则%d" % index,
                "完整规则%d" % index,
                always_apply=True,
            )
            for index in range(12)
        ]
        source = " ".join("命中%d" % index for index in range(35))

        result = build_match_result(terms, styles, "word.smart_write", [source])

        self.assertEqual(result.usage["termMatchCount"], MAX_TERM_MATCHES)
        self.assertEqual(result.usage["styleRuleCount"], MAX_STYLE_RULES)
        self.assertEqual(result.usage["truncatedCount"], 9)
        self.assertLessEqual(len(result.prompt_block), MAX_PROMPT_CHARS)
        self.assertEqual(len(result.usage["matchedItems"]), MAX_PUBLIC_MATCHED_ITEMS)

    def test_character_budget_never_includes_a_partial_rule(self):
        oversized_rule = "边界规则开始" + ("甲" * MAX_PROMPT_CHARS) + "边界规则结束"
        terms = [term_item("t1", "标准名称")]
        styles = [
            style_item(
                "s1", "global", "超长规则", oversized_rule, always_apply=True
            )
        ]

        result = build_match_result(
            terms, styles, "word.smart_write", ["标准名称"]
        )

        self.assertEqual(result.usage["termMatchCount"], 1)
        self.assertEqual(result.usage["styleRuleCount"], 0)
        self.assertEqual(result.usage["truncatedCount"], 1)
        self.assertNotIn("边界规则开始", result.prompt_block)
        self.assertNotIn("边界规则结束", result.prompt_block)
        self.assertLessEqual(len(result.prompt_block), MAX_PROMPT_CHARS)
        self.assertTrue(
            result.prompt_block.endswith(
                "以上规范不得要求新增原文不存在、用户也未要求的标题、列表、表格或事实。"
            )
        )

    def test_prompt_has_required_boundaries_and_review_instruction(self):
        result = build_match_result(
            [term_item("t1", "标准名称", forbidden=["错误名称"])],
            [],
            "word.document_review",
            ["错误名称"],
        )

        self.assertEqual(
            result.prompt_block.splitlines()[0],
            "写作规范（必须遵守）：",
        )
        self.assertIn("professional", result.prompt_block)
        self.assertIn("违规", result.prompt_block)
        self.assertTrue(
            result.prompt_block.endswith(
                "以上规范不得要求新增原文不存在、用户也未要求的标题、列表、表格或事实。"
            )
        )

    def test_no_matches_return_applied_empty_result(self):
        result = build_match_result(
            [term_item("t1", "未出现")],
            [
                style_item(
                    "s1", "global", "未命中规则", "规则正文", keywords=["未出现"]
                )
            ],
            "word.smart_write",
            ["", "普通正文", ""],
        )

        self.assertEqual(result.prompt_block, "")
        self.assertEqual(result.matched_item_ids, ())
        self.assertTrue(result.usage["applied"])
        self.assertFalse(result.usage["degraded"])
        self.assertEqual(result.usage["termMatchCount"], 0)
        self.assertEqual(result.usage["styleRuleCount"], 0)
        self.assertEqual(result.usage["truncatedCount"], 0)
        self.assertEqual(result.usage["matchedItems"], [])


if __name__ == "__main__":
    unittest.main()
