import unittest

from app.core.errors import AdapterError
from app.services.word.format_semantics import (
    FORMAT_SEMANTIC_OPERATIONS,
    MAX_FORMAT_SEMANTIC_CALLS,
    MAX_FORMAT_SEMANTIC_INPUT_TOKENS,
    FormatSemanticContract,
    FormatSemanticExecutor,
)


class FormatSemanticContractTests(unittest.TestCase):
    def test_only_four_operations_are_allowed(self):
        self.assertEqual(
            FORMAT_SEMANTIC_OPERATIONS,
            (
                "classify_role",
                "associate_caption",
                "suggest_figure_caption",
                "suggest_table_caption",
            ),
        )
        self.assertTrue(FormatSemanticContract.is_allowed_operation("classify_role"))
        self.assertFalse(FormatSemanticContract.is_allowed_operation("rewrite_format"))

    def test_input_budget_is_conservative_and_rejects_oversized_prompt(self):
        self.assertLessEqual(
            FormatSemanticContract.estimate_input_tokens("a" * 7900),
            MAX_FORMAT_SEMANTIC_INPUT_TOKENS,
        )
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.require_input_budget("a" * 9000)
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_INPUT_OVER_BUDGET")

    def test_output_budget_is_bounded_by_access_method_and_task_limit(self):
        self.assertEqual(
            FormatSemanticContract.output_budget(
                {"accessMethod": "workflow_platform", "maxOutputTokens": 9999}
            ),
            2048,
        )
        self.assertEqual(
            FormatSemanticContract.output_budget(
                {"accessMethod": "direct_model", "maxOutputTokens": 8192}
            ),
            4096,
        )
        self.assertEqual(
            FormatSemanticContract.output_budget(
                {"accessMethod": "direct_model", "maxOutputTokens": 1200}
            ),
            1200,
        )

    def test_response_must_match_operation_snapshot_and_candidate_range(self):
        candidates = {
            "block-1": {"allowedTargets": [{"role": "heading", "attributes": {"level": 1}}]},
        }
        binding = {"contentSha256": "c", "structureSha256": "s", "formatSha256": "f"}
        valid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": binding,
            "items": [
                {
                    "blockId": "block-1",
                    "role": "heading",
                    "level": 1,
                    "confidence": 0.9,
                }
            ],
        }
        normalized = FormatSemanticContract.validate_response(
            "classify_role", valid, candidates, binding
        )
        self.assertEqual(normalized["items"][0]["blockId"], "block-1")

        invalid = dict(valid)
        invalid["items"] = [{"blockId": "outside", "role": "heading", "level": 1, "confidence": 0.9}]
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "classify_role", invalid, candidates, binding
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE")

    def test_response_schema_is_operation_specific_and_references_are_bounded(self):
        binding = {}
        candidates = {
            "caption-1": {"allowedTargetBlockIds": ["figure-1"]},
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "associate_caption",
            "snapshotBinding": binding,
            "items": [{
                "blockId": "caption-1",
                "status": "ambiguous",
                "targetBlockId": "outside",
            }],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "associate_caption", payload, candidates, binding
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE")

        role_candidates = {
            "block-1": {"allowedTargets": [{"role": "heading", "attributes": {"level": 1}}]},
        }
        role_payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": binding,
            "items": [{
                "blockId": "block-1",
                "role": "heading",
                "level": "not-an-int",
                "confidence": 0.9,
                "suggestion": "不应出现在角色响应中",
            }],
        }
        with self.assertRaises(AdapterError):
            FormatSemanticContract.validate_response(
                "classify_role", role_payload, role_candidates, binding
            )

    def test_validation_can_require_a_complete_result_for_every_synthetic_candidate(self):
        candidates = {
            "block-1": {"allowedTargets": [{"role": "heading", "attributes": {"level": 1}}]},
            "block-2": {"allowedTargets": [{"role": "body", "attributes": {}}]},
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": {},
            "items": [
                {"blockId": "block-1", "role": "heading", "level": 1, "confidence": 0.9}
            ],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "classify_role", payload, candidates, {}, require_complete=True
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_RESPONSE_INCOMPLETE")

    def test_suggestion_is_body_only_and_bounded(self):
        candidates = {"figure-1": {"allowedTargets": []}}
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_figure_caption",
            "snapshotBinding": {},
            "items": [{"blockId": "figure-1", "suggestion": "系统总体架构"}],
        }
        self.assertEqual(
            FormatSemanticContract.validate_response(
                "suggest_figure_caption", payload, candidates, {}
            )["items"][0]["suggestion"],
            "系统总体架构",
        )
        payload["items"][0]["suggestion"] = "图1 系统总体架构\n"
        with self.assertRaises(AdapterError):
            FormatSemanticContract.validate_response(
                "suggest_figure_caption", payload, candidates, {}
            )

    def test_table_caption_suggestion_is_bound_to_data_table_and_evidence(self):
        candidates = {
            "table-1": {
                "tableType": "data",
                "captionStatus": "missing",
                "associationStatus": "missing",
                "evidence": {
                    "evidenceStatus": "complete",
                    "heading": "项目进展",
                    "headers": [["月份", "完成率"]],
                    "rows": [["1月", "80%"]],
                    "source": "项目台账",
                },
            }
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_table_caption",
            "snapshotBinding": {},
            "items": [{
                "blockId": "table-1",
                "status": "suggested",
                "suggestion": "项目进展完成率",
            }],
        }
        self.assertEqual(
            FormatSemanticContract.validate_response(
                "suggest_table_caption", payload, candidates, {}
            )["items"][0]["suggestion"],
            "项目进展完成率",
        )
        payload["items"][0]["suggestion"] = "2025年全国公司完成率"
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_table_caption", payload, candidates, {}
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_EVIDENCE_VIOLATION")

    def test_table_caption_suggestion_rejects_table_number_prefix(self):
        candidates = {
            "table-1": {
                "tableType": "data",
                "captionStatus": "missing",
                "associationStatus": "missing",
                "evidence": {"evidenceStatus": "complete", "rows": [["项目进展"]]},
            }
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_table_caption",
            "snapshotBinding": {},
            "items": [{
                "blockId": "table-1",
                "status": "suggested",
                "suggestion": "表1 项目进展情况",
            }],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_table_caption", payload, candidates, {}, require_complete=True
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_RESPONSE_INVALID")

    def test_table_caption_suggestion_rejects_non_missing_or_insufficient_candidates(self):
        candidates = {
            "table-1": {
                "tableType": "layout",
                "captionStatus": "missing",
                "associationStatus": "missing",
                "evidence": {"evidenceStatus": "complete"},
            }
        }
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_table_caption",
            "snapshotBinding": {},
            "items": [{"blockId": "table-1", "status": "suggested", "suggestion": "布局"}],
        }
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.validate_response(
                "suggest_table_caption", payload, candidates, {}
            )
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE")

        candidates["table-1"]["tableType"] = "data"
        candidates["table-1"]["evidence"] = {"evidenceStatus": "insufficient"}
        payload["items"][0] = {
            "blockId": "table-1",
            "status": "not_assessable",
            "suggestion": "",
        }
        normalized = FormatSemanticContract.validate_response(
            "suggest_table_caption", payload, candidates, {}
        )
        self.assertEqual(normalized["items"][0]["status"], "not_assessable")

    def test_call_budget_is_hard_and_counts_retries_and_corrections(self):
        self.assertEqual(MAX_FORMAT_SEMANTIC_CALLS, 16)
        self.assertEqual(
            FormatSemanticContract.remaining_calls(MAX_FORMAT_SEMANTIC_CALLS - 1),
            1,
        )
        with self.assertRaises(AdapterError) as raised:
            FormatSemanticContract.require_call_budget(MAX_FORMAT_SEMANTIC_CALLS)
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_CALL_LIMIT_EXCEEDED")

    def test_executor_retries_transient_errors_and_corrects_invalid_json_once(self):
        responses = [
            AdapterError("PROVIDER_TIMEOUT", "timeout"),
            {"answer": '{"schemaVersion":"wrong"}'},
            {
                "answer": (
                    '{"schemaVersion":"format_semantics.v1",'
                    '"operation":"suggest_figure_caption","snapshotBinding":{},'
                    '"items":[{"blockId":"figure-1","suggestion":"系统架构"}]}'
                )
            },
        ]

        def call(_query, _output_budget):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        executor = FormatSemanticExecutor(call, task_auth={"accessMethod": "workflow_platform"})
        result = executor.execute(
            "suggest_figure_caption",
            "candidate payload",
            {"figure-1": {"allowedTargets": []}},
            {},
        )
        self.assertEqual(result["items"][0]["suggestion"], "系统架构")
        self.assertEqual(result["usedCalls"], 3)
        self.assertEqual(result["retryCount"], 1)
        self.assertEqual(result["correctionCount"], 1)


if __name__ == "__main__":
    unittest.main()
