import importlib.util
import json
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import FormatReviewSummary, WordDocumentRequest
    from app.services.word.format_reviewer import WordFormatReviewer


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


class RecordingFormatReviewProvider:
    def __init__(self, configured: bool = True, fail: bool = False, answer: str = "") -> None:
        self.configured = configured
        self.fail = fail
        self.answer = answer or '{"paragraphs":[{"paragraphIndex":1,"role":"heading1","confidence":0.95}]}'
        self.calls = []
        self.skipped = []

    def is_task_configured(self, task_type: str) -> bool:
        return self.configured and task_type == "word.format_review"

    def get_auth_source_for_task(self, task_type: str) -> str:
        return "task-file"

    def format_review_roles(self, trace_id: str, input_data: dict, prompt: str, task_auth=None) -> dict:
        self.calls.append({"traceId": trace_id, "inputData": input_data, "prompt": prompt, "taskAuth": task_auth})
        if self.fail:
            raise ValueError("invalid provider response")
        return {"answer": self.answer}

    def record_unconfigured_debug(self, task_type: str, trace_id: str, query: str) -> None:
        self.skipped.append({"taskType": task_type, "traceId": trace_id, "query": query})

    def record_skipped_debug(self, task_type: str, trace_id: str, query: str, skip_reason: str, provider: str = "local") -> None:
        self.skipped.append(
            {"taskType": task_type, "traceId": trace_id, "query": query, "skipReason": skip_reason, "provider": provider}
        )


class VersionedFormatSemanticsProvider(RecordingFormatReviewProvider):
    def format_semantics(
        self, operation: str, trace_id: str, input_data: dict, prompt: str,
        task_auth=None, output_token_budget=None,
    ) -> dict:
        self.calls.append({"traceId": trace_id, "inputData": input_data, "prompt": prompt, "taskAuth": task_auth})
        return {
            "answer": (
                '{"schemaVersion":"format_semantics.v1","operation":"classify_role",'
                '"snapshotBinding":{"contentSha256":"content-1","structureSha256":"structure-1",'
                '"formatSha256":"format-1"},"items":[{"blockId":"format-paragraph-1",'
                '"role":"heading","level":1,"confidence":0.95},{"blockId":"format-context-2",'
                '"role":"heading","level":1,"confidence":0.95}]}'
            )
        }


class TableCaptionFormatSemanticsProvider(RecordingFormatReviewProvider):
    def __init__(self, suggestion="项目月度完成情况") -> None:
        super().__init__()
        self.suggestion = suggestion

    def format_semantics(
        self, operation: str, trace_id: str, input_data: dict, prompt: str,
        task_auth=None, output_token_budget=None,
    ) -> dict:
        self.calls.append({"operation": operation, "inputData": input_data, "prompt": prompt})
        block_id = input_data["candidateBlockIds"][0]
        return {
            "answer": json.dumps({
                "schemaVersion": "format_semantics.v1",
                "operation": operation,
                "snapshotBinding": input_data.get("snapshotBinding", {}),
                "items": [{
                    "blockId": block_id,
                    "status": "suggested",
                    "suggestion": self.suggestion,
                }],
            }, ensure_ascii=False),
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class WordFormatReviewerTests(unittest.TestCase):
    def test_format_review_summary_preserves_table_caption_diagnostics(self) -> None:
        summary = FormatReviewSummary(
            templateId="technical-file-format-requirements",
            tableCaptionCandidateCount=2,
            tableCaptionSuggestedCount=1,
            tableCaptionRestrictedCount=1,
        )

        payload = (
            summary.model_dump(by_alias=True)
            if hasattr(summary, "model_dump")
            else summary.dict(by_alias=True)
        )
        self.assertEqual(payload["tableCaptionCandidateCount"], 2)
        self.assertEqual(payload["tableCaptionSuggestedCount"], 1)
        self.assertEqual(payload["tableCaptionRestrictedCount"], 1)

    def _request(self, selection_mode: str = "selection", first_outline_level=0):
        return parse_word_request(
            {
                "documentId": "format-review.docx",
                "scene": "word",
                "selectionMode": selection_mode,
                "content": {
                    "plainText": "1 总则\n正文内容",
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "1 总则",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 12,
                            "alignment": "left",
                            "outlineLevel": first_outline_level,
                        },
                        {
                            "index": 2,
                            "text": "正文内容",
                            "styleName": "Normal",
                            "fontName": "楷体",
                            "fontSize": 14,
                            "alignment": "left",
                            "outlineLevel": 0,
                            "lineSpacing": 1.0,
                            "firstLineIndent": 0,
                        },
                    ],
                    "headings": [],
                    "documentStructure": {"page_setup": {"marginTop": 72}},
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True,
                },
            }
        )

    @staticmethod
    def _hierarchy_request(levels=(1, 3), include_paragraph_indexes=True):
        paragraphs = []
        headings = []
        blocks = []
        for position, level in enumerate(levels, 1):
            paragraph_index = position if include_paragraph_indexes else None
            text = "{0}级标题".format(level)
            paragraphs.append({
                "index": paragraph_index,
                "text": text,
                "styleName": "Heading {0}".format(level),
                "outlineLevel": level,
            })
            headings.append({
                "level": level,
                "text": text,
                "paragraphIndex": paragraph_index,
            })
            blocks.append({
                "blockId": "format-paragraph-{0}".format(position),
                "blockType": "heading",
                "scope": "in_scope",
                "paragraphIndex": paragraph_index,
                "headingLevel": level,
                "text": text,
                "range": {"paragraphIndex": paragraph_index},
                "format": {"outlineLevel": level},
            })
        return parse_word_request({
            "documentId": "heading-hierarchy.docx",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "\n".join(item["text"] for item in paragraphs),
                "paragraphs": paragraphs,
                "headings": headings,
                "documentStructure": {"formatBlocks": blocks},
            },
            "options": {"templateId": "technical-file-format-requirements"},
        })

    def test_heading_jump_is_one_localized_anchored_issue(self) -> None:
        result = WordFormatReviewer().review(self._hierarchy_request(), trace_id="")

        issues = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.heading_hierarchy"
        ]
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue["paragraphIndex"], 2)
        self.assertEqual(issue["role"], "heading")
        self.assertEqual(issue["currentLevel"], 3)
        self.assertEqual(issue["previousLevel"], 1)
        self.assertEqual(issue["anchorId"], "format-paragraph-2")
        self.assertEqual(issue["sourceAnchor"]["paragraphIndex"], 2)
        self.assertEqual(issue["anchorVerification"], "verified")
        self.assertIn("前一有效标题为 1 级", issue["message"])
        self.assertIn("补齐 2 级标题", issue["suggestion"])

    def test_normal_heading_sequence_does_not_create_hierarchy_issue(self) -> None:
        result = WordFormatReviewer().review(self._hierarchy_request((1, 2)), trace_id="")

        self.assertEqual(
            [issue for issue in result["issues"] if issue["ruleId"] == "structure.heading_hierarchy"],
            [],
        )

    def test_unverified_heading_position_does_not_fabricate_anchor(self) -> None:
        result = WordFormatReviewer().review(
            self._hierarchy_request(include_paragraph_indexes=False), trace_id=""
        )

        issue = next(
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.heading_hierarchy"
        )
        self.assertIsNone(issue["paragraphIndex"])
        self.assertEqual(issue["anchorId"], "")
        self.assertEqual(issue["sourceAnchor"], {})
        self.assertEqual(issue["anchorVerification"], "unverified")

    def test_format_review_returns_issues_not_apply_changes(self) -> None:
        provider = RecordingFormatReviewProvider()

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection", first_outline_level=None),
            trace_id="trace-format-review",
        )

        self.assertEqual(result["summary"]["scope"], "selection")
        self.assertEqual(result["summary"]["templateId"], "technical-file-format-requirements")
        self.assertEqual(result["summary"]["provider"], "工作流平台")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)
        self.assertIn("issues", result)
        self.assertNotIn("changes", result)
        self.assertFalse(any("targetProperties" in issue for issue in result["issues"]))
        self.assertEqual(provider.calls[0]["inputData"]["taskType"], "word.format_review")

    def test_format_review_uses_local_fallback_without_task_key(self) -> None:
        provider = RecordingFormatReviewProvider(configured=False)

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("document", first_outline_level=None),
            trace_id="trace-format-local",
        )

        self.assertEqual(result["summary"]["scope"], "document")
        self.assertEqual(result["summary"]["provider"], "local")
        self.assertEqual(result["summary"]["aiFallbackReason"], "provider_not_configured")
        self.assertEqual(provider.calls, [])
        self.assertEqual(provider.skipped[0]["taskType"], "word.format_review")

    def test_format_review_reports_no_candidates_as_a_normal_no_call(self) -> None:
        provider = RecordingFormatReviewProvider()
        request = self._request("document")
        request.content.document_structure = {
            "formatBlocks": [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "paragraph",
                    "paragraphIndex": 1,
                    "text": "正文内容一",
                },
                {
                    "blockId": "format-paragraph-2",
                    "blockType": "paragraph",
                    "paragraphIndex": 2,
                    "text": "正文内容",
                },
            ]
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-no-candidates",
            task_auth={
                "providerBaseUrl": "https://model.example/v1",
                "apiKey": "frozen-secret",
                "accessMethod": "direct_model",
                "modelName": "review-model",
                "maxOutputTokens": 4096,
                "contextWindowTokens": 40000,
            },
        )

        summary = result["summary"]
        self.assertEqual(summary["aiCandidateCount"], 0)
        self.assertFalse(summary["aiAttempted"])
        self.assertEqual(summary["aiCallCount"], 0)
        self.assertEqual(summary["aiAcceptedCount"], 0)
        self.assertEqual(summary["semanticStatus"], "not_needed")
        self.assertEqual(summary["aiFallbackReason"], "no_candidates")
        self.assertEqual(provider.calls, [])

    def test_format_review_falls_back_when_ai_role_provider_fails(self) -> None:
        provider = RecordingFormatReviewProvider(fail=True)

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection", first_outline_level=None),
            trace_id="trace-format-provider-failed",
        )

        self.assertEqual(result["summary"]["scope"], "selection")
        self.assertEqual(result["summary"]["provider"], "local")
        self.assertEqual(result["summary"]["aiAttempted"], True)
        self.assertEqual(result["summary"]["aiCallCount"], 1)
        self.assertEqual(result["summary"]["aiAcceptedCount"], 0)
        self.assertEqual(result["summary"]["aiRequestErrorCount"], 1)
        self.assertEqual(result["summary"]["aiFallbackReason"], "provider_request_failed")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)

    def test_format_review_ignores_think_tag_before_role_json(self) -> None:
        provider = RecordingFormatReviewProvider(
            answer='<think>{"draft": true, "reason": "内部分析"}</think>\n{"paragraphs":[{"paragraphIndex":1,"role":"heading1","confidence":0.95}]}'
        )
        request = self._request("selection")
        request.content.document_structure["formatFacts"] = {
            "paragraphs": [
                {"paragraphIndex": 1, "styleName": "Normal", "text": "1 总则"}
            ]
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-think",
        )

        self.assertEqual(result["summary"]["aiFallbackReason"], "")
        self.assertEqual(result["summary"]["aiClassifiedParagraphCount"], 1)
        self.assertEqual(result["summary"]["provider"], "工作流平台")
        self.assertEqual(result["summary"]["aiAttempted"], True)
        self.assertEqual(result["summary"]["aiCallCount"], 1)
        self.assertEqual(result["summary"]["aiAcceptedCount"], 1)

    def test_format_review_distinguishes_parse_failure_from_zero_accepted(self) -> None:
        request = self._request("document")
        request.content.paragraphs = [request.content.paragraphs[1]]
        request.content.plain_text = "待确认内容"
        request.content.document_structure = {
            "formatBlocks": [
                {
                    "blockId": "format-context-2",
                    "blockType": "unknown",
                    "scope": "in_scope",
                    "paragraphIndex": 2,
                    "text": "待确认内容",
                    "format": {"styleName": "Normal"},
                },
            ],
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "workflow_platform",
            "formatSemanticReadiness": {"code": "ready"},
        }

        parse_provider = RecordingFormatReviewProvider(answer="not-json")
        parse_result = WordFormatReviewer(provider_client=parse_provider).review(
            request, trace_id="trace-format-parse-failed", task_auth=task_auth
        )
        self.assertEqual(parse_result["summary"]["aiCallCount"], 1)
        self.assertEqual(parse_result["summary"]["aiParseErrorCount"], 1)
        self.assertEqual(
            parse_result["summary"]["aiFallbackReason"],
            "format_semantic_response_invalid",
        )

        empty_provider = RecordingFormatReviewProvider(answer='{"paragraphs":[]}')
        empty_result = WordFormatReviewer(provider_client=empty_provider).review(
            request, trace_id="trace-format-zero-accepted", task_auth=task_auth
        )
        self.assertEqual(empty_result["summary"]["aiCallCount"], 1)
        self.assertEqual(empty_result["summary"]["aiAcceptedCount"], 0)
        self.assertEqual(
            empty_result["summary"]["aiFallbackReason"],
            "format_semantic_zero_accepted",
        )

    def test_format_review_reports_model_configuration_identity(self) -> None:
        provider = RecordingFormatReviewProvider()
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "review-model",
            "maxOutputTokens": 4096,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-identity",
            "modelConfigurationName": "格式审查主配置",
            "modelConfiguration": {
                "id": "config-format-identity",
                "name": "格式审查主配置",
                "configVersion": 9,
                "taskType": "word.format_review",
            },
        }

        result = WordFormatReviewer(provider_client=provider).review(
            self._request("selection"),
            trace_id="trace-format-identity",
            task_auth=task_auth,
        )

        summary = result["summary"]
        self.assertEqual(summary["modelConfigurationName"], "格式审查主配置")
        self.assertEqual(summary["modelConfigurationId"], "config-format-identity")
        self.assertEqual(summary["modelConfigurationVersion"], 9)
        self.assertEqual(summary["accessMethod"], "direct_model")
        self.assertNotIn("apiKey", summary)

    def test_format_review_rejects_unbounded_model_role_attributes(self) -> None:
        reviewer = WordFormatReviewer()
        self.assertIsNone(reviewer._normalize_model_role("heading", {"role": "heading"}))
        self.assertIsNone(reviewer._normalize_model_role("heading10", {"role": "heading10"}))
        self.assertIsNone(reviewer._normalize_model_role("list_item", {"role": "list_item", "level": 1}))
        self.assertEqual(
            reviewer._normalize_model_role(
                "heading", {"role": "heading", "level": 2}
            ),
            {"role": "heading", "attributes": {"level": 2}},
        )

    def test_format_review_sends_only_ambiguous_candidates_with_snapshot_binding(self) -> None:
        provider = RecordingFormatReviewProvider(
            answer=(
                '{"snapshot":{"contentSha256":"content-1","structureSha256":"structure-1",'
                '"formatSha256":"format-1"},"candidates":[{"blockId":"format-context-2",'
                '"role":"heading","level":1,"confidence":0.95}]}'
            )
        )
        request = self._request("document")
        request.content.paragraphs[1] = request.content.paragraphs[1].copy(
            update={"text": "待确认内容"}
        )
        request.content.document_structure = {
            "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
            "formatFingerprint": "format-1",
            "structureFingerprint": "structure-1",
            "contentFingerprint": "content-1",
            "formatBlocks": [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "paragraph",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "text": "普通正文",
                    "format": {"styleName": "Normal"},
                },
                {
                    "blockId": "format-context-2",
                    "blockType": "context",
                    "scope": "in_scope",
                    "paragraphIndex": 2,
                    "text": "待确认内容",
                    "format": {"styleName": "Normal"},
                },
            ],
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "review-model",
            "maxOutputTokens": 4096,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-1",
            "modelConfiguration": {"configVersion": 7, "taskType": "word.format_review"},
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-candidates",
            task_auth=task_auth,
        )

        self.assertEqual(len(provider.calls), 1)
        prompt = provider.calls[0]["prompt"]
        self.assertIn("format-context-2", prompt)
        self.assertNotIn("format-paragraph-1", prompt)
        self.assertIn("content-1", prompt)
        self.assertEqual(provider.calls[0]["taskAuth"], task_auth)
        self.assertEqual(result["summary"]["aiCandidateCount"], 1)
        self.assertEqual(result["summary"]["semanticStatus"], "completed")
        self.assertTrue(any(issue["paragraphIndex"] == 2 for issue in result["issues"]))

    def test_format_review_keeps_deterministic_review_when_direct_capability_is_unknown(self) -> None:
        provider = RecordingFormatReviewProvider()
        request = self._request("document")
        request.content.document_structure["formatFacts"] = {
            "paragraphs": [{"paragraphIndex": 1, "styleName": "Normal", "text": "待确认"}]
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "unknown-model",
            "maxOutputTokens": None,
            "contextWindowTokens": 40000,
            "modelConfigurationId": "config-format-unknown",
            "modelConfiguration": {"configVersion": 3, "taskType": "word.format_review"},
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-format-capability-unknown",
            task_auth=task_auth,
        )

        self.assertEqual(provider.calls, [])
        self.assertEqual(result["summary"]["semanticStatus"], "degraded")
        self.assertEqual(result["summary"]["aiFallbackReason"], "model_capability_unknown")
        self.assertGreaterEqual(result["summary"]["issueCount"], 1)

    def test_format_review_uses_versioned_semantic_contract_when_available(self) -> None:
        provider = VersionedFormatSemanticsProvider()
        request = self._request("document")
        request.content.document_structure = {
            "formatSnapshotSchemaVersion": "word.format_review.snapshot.v2",
            "formatFingerprint": "format-1",
            "structureFingerprint": "structure-1",
            "contentFingerprint": "content-1",
            "formatBlocks": [
                {
                    "blockId": "format-paragraph-1",
                    "blockType": "unknown",
                    "scope": "in_scope",
                    "paragraphIndex": 1,
                    "text": "1 总则",
                    "format": {"styleName": "Normal"},
                },
                {
                    "blockId": "format-context-2",
                    "blockType": "context",
                    "scope": "in_scope",
                    "paragraphIndex": 2,
                    "text": "正文内容",
                    "format": {"styleName": "Normal"},
                },
            ],
        }
        task_auth = {
            "providerBaseUrl": "https://model.example/v1",
            "apiKey": "frozen-secret",
            "accessMethod": "direct_model",
            "modelName": "review-model",
            "maxOutputTokens": 4096,
            "contextWindowTokens": 40000,
        }

        result = WordFormatReviewer(provider_client=provider).review(
            request, trace_id="trace-format-versioned", task_auth=task_auth
        )

        self.assertEqual(result["summary"]["aiCallCount"], 1)
        self.assertEqual(result["summary"]["aiCorrectionCount"], 0)
        self.assertEqual(result["summary"]["semanticStatus"], "degraded")
        self.assertEqual(provider.calls[0]["inputData"]["operation"], "classify_role")

    def test_format_review_normalizes_wps_font_size_and_alignment_values(self) -> None:
        request = parse_word_request(
            {
                "documentId": "format-review-normalized.docx",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "正文内容",
                    "paragraphs": [
                        {
                            "index": 4,
                            "text": "正文内容",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 0,
                            "alignment": "3",
                            "outlineLevel": 0,
                            "lineSpacing": 1.25,
                            "firstLineIndent": 640,
                        }
                    ],
                    "headings": [],
                    "documentStructure": {
                        "page_setup": {
                            "marginTop": 1440,
                            "marginBottom": 1440,
                            "marginLeft": 1800,
                            "marginRight": 1800,
                        }
                    },
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True,
                },
            }
        )

        result = WordFormatReviewer().review(request)

        self.assertFalse(
            any(issue["ruleId"] in {"font_size", "alignment"} for issue in result["issues"]),
            result["issues"],
        )

    def test_missing_data_table_caption_uses_complete_evidence_and_returns_read_only_body(self) -> None:
        provider = TableCaptionFormatSemanticsProvider()
        request = parse_word_request({
            "documentId": "table-caption.docx",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "项目进展",
                "paragraphs": [],
                "headings": [],
                "documentStructure": {
                    "contentFingerprint": "content-1",
                    "structureFingerprint": "structure-1",
                    "formatFingerprint": "format-1",
                    "formatBlocks": [
                        {
                            "blockId": "heading-1",
                            "blockType": "heading",
                            "paragraphIndex": 1,
                            "text": "项目进展",
                        },
                        {
                            "blockId": "format-table-table-1",
                            "blockType": "table",
                            "tableId": "table-1",
                            "paragraphIndex": 2,
                            "headerRows": 2,
                            "rows": [
                                {"rowIndex": 0, "cells": [
                                    {"columnIndex": 0, "text": "月份", "isHeader": True, "columnSpan": 2},
                                ]},
                                {"rowIndex": 1, "cells": [
                                    {"columnIndex": 0, "text": "月份", "isHeader": True},
                                    {"columnIndex": 1, "text": "完成率", "isHeader": True},
                                ]},
                                {"rowIndex": 2, "cells": [
                                    {"columnIndex": 0, "text": "1月"},
                                    {"columnIndex": 1, "text": "80%"},
                                ]},
                                {"rowIndex": 3, "cells": [
                                    {"columnIndex": 0, "text": "2月"},
                                    {"columnIndex": 1, "text": "90%"},
                                ]},
                            ],
                            "source": "项目台账",
                            "footnotes": ["完成率按月统计"],
                        },
                    ],
                },
            },
            "options": {"templateId": "technical-file-format-requirements"},
        })
        result = WordFormatReviewer(provider_client=provider).review(
            request,
            trace_id="trace-table-caption",
            task_auth={
                "providerBaseUrl": "https://model.example/v1",
                "apiKey": "frozen-secret",
                "accessMethod": "direct_model",
                "modelName": "review-model",
                "maxOutputTokens": 4096,
                "contextWindowTokens": 40000,
            },
        )

        caption_issues = [
            issue for issue in result["issues"]
            if issue["ruleId"] == "structure.missing_table_caption"
        ]
        self.assertEqual(len(caption_issues), 1)
        self.assertEqual(caption_issues[0]["suggestion"], "项目月度完成情况")
        self.assertEqual(caption_issues[0]["dataStatus"], "verified")
        evidence = caption_issues[0]["evidence"][0]
        self.assertEqual(evidence["evidenceStatus"], "complete")
        self.assertEqual(evidence["headerRows"], 2)
        self.assertEqual(evidence["heading"], "项目进展")
        self.assertEqual(evidence["source"], "项目台账")
        self.assertEqual(result["summary"]["tableCaptionSuggestedCount"], 1)
        self.assertEqual(provider.calls[0]["operation"], "suggest_table_caption")

    def test_missing_figure_caption_uses_text_evidence_without_pixel_export(self) -> None:
        provider = TableCaptionFormatSemanticsProvider(suggestion="系统架构")
        request = parse_word_request({
            "documentId": "figure-caption.docx",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "正文",
                "paragraphs": [{"index": 1, "text": "正文"}],
                "headings": [],
                "documentStructure": {
                    "formatBlocks": [{
                        "blockId": "format-image-figure-1",
                        "blockType": "image",
                        "paragraphIndex": 2,
                        "text": "",
                        "images": [{
                            "imageId": "figure-1",
                            "captionStatus": "missing",
                            "nearbyText": "系统架构",
                            "supported": True,
                        }],
                    }],
                },
            },
            "options": {"templateId": "technical-file-format-requirements"},
        })

        reviewer = WordFormatReviewer(provider_client=provider)
        suggestions, diagnostics = reviewer._suggest_missing_figure_captions(
            request, "trace-figure-caption"
        )

        self.assertEqual(suggestions["figure-1"]["status"], "text_evidence_only")
        self.assertEqual(suggestions["figure-1"]["suggestion"], "系统架构")
        self.assertEqual(diagnostics["figureCaptionTextEvidenceOnlyCount"], 1)
        self.assertEqual(diagnostics["imageSemanticStatus"], "disabled")
        call = provider.calls[0]
        self.assertEqual(call["operation"], "suggest_figure_caption")
        self.assertNotIn("image_files", call["inputData"])

    def test_large_data_table_uses_explicit_first_three_last_two_evidence(self) -> None:
        rows = [
            {"rowIndex": 0, "cells": [
                {"columnIndex": 0, "text": "指标", "isHeader": True},
                {"columnIndex": 1, "text": "说明", "isHeader": True},
            ]}
        ]
        for index in range(1, 31):
            rows.append({"rowIndex": index, "cells": [
                {"columnIndex": 0, "text": "指标{0}".format(index)},
                {"columnIndex": 1, "text": "数据" * 500},
            ]})
        request = parse_word_request({
            "documentId": "large-table-caption.docx",
            "scene": "word",
            "content": {"documentStructure": {"formatBlocks": [{
                "blockId": "format-table-large-table",
                "blockType": "table",
                "tableId": "large-table",
                "paragraphIndex": 1,
                "headerRows": 1,
                "rows": rows,
            }]}},
        })

        candidate = WordFormatReviewer()._table_caption_candidates(request)[0]
        evidence = candidate["evidence"]
        self.assertEqual(evidence["evidenceStatus"], "restricted")
        self.assertEqual(evidence["sampling"], "first_three_and_last_two_rows")
        self.assertEqual(
            [row["rowIndex"] for row in evidence["rows"]],
            [0, 1, 2, 29, 30],
        )

    def test_only_unambiguous_missing_data_tables_enter_caption_suggestion_candidates(self) -> None:
        blocks = [
            {
                "blockId": "format-table-data",
                "blockType": "table",
                "tableId": "data-table",
                "paragraphIndex": 1,
                "rows": [
                    {"rowIndex": 0, "cells": [
                        {"columnIndex": 0, "text": "项目", "isHeader": True},
                        {"columnIndex": 1, "text": "数量", "isHeader": True},
                    ]},
                    {"rowIndex": 1, "cells": [
                        {"columnIndex": 0, "text": "甲"}, {"columnIndex": 1, "text": "1"},
                    ]},
                    {"rowIndex": 2, "cells": [
                        {"columnIndex": 0, "text": "乙"}, {"columnIndex": 1, "text": "2"},
                    ]},
                ],
            },
            {
                "blockId": "format-table-layout",
                "blockType": "table",
                "tableId": "layout-table",
                "paragraphIndex": 2,
                "nestedTable": True,
                "rows": [{"rowIndex": 0, "cells": [{"columnIndex": 0, "text": "布局"}]}],
            },
            {
                "blockId": "caption-1", "blockType": "caption", "paragraphIndex": 3,
                "text": "表1 旧题注", "sectionId": "s", "storyId": "body",
            },
            {
                "blockId": "caption-2", "blockType": "caption", "paragraphIndex": 4,
                "text": "表2 另一题注", "sectionId": "s", "storyId": "body",
            },
            {
                "blockId": "format-table-ambiguous",
                "blockType": "table",
                "tableId": "ambiguous-table",
                "paragraphIndex": 5,
                "rows": [
                    {"rowIndex": 0, "cells": [
                        {"columnIndex": 0, "text": "项目", "isHeader": True},
                        {"columnIndex": 1, "text": "数量", "isHeader": True},
                    ]},
                    {"rowIndex": 1, "cells": [
                        {"columnIndex": 0, "text": "甲"}, {"columnIndex": 1, "text": "1"},
                    ]},
                    {"rowIndex": 2, "cells": [
                        {"columnIndex": 0, "text": "乙"}, {"columnIndex": 1, "text": "2"},
                    ]},
                ],
                "sectionId": "s", "storyId": "body",
            },
        ]
        request = parse_word_request({
            "documentId": "candidate-boundary.docx",
            "scene": "word",
            "content": {"documentStructure": {"formatBlocks": blocks}},
        })

        candidates = WordFormatReviewer()._table_caption_candidates(request)
        self.assertEqual([item["tableId"] for item in candidates], ["data-table"])
