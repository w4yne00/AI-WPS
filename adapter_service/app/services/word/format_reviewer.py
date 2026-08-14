import json
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import FormatReviewIssue, Paragraph, WordDocumentRequest
from app.services.document_normalizer import body_paragraphs
from app.services.provider_client import ProviderClient, extract_answer
from app.services.word.authorized_format_algorithm import (
    audit_format_facts,
    associate_captions,
    classify_role_fact,
    classify_table_fact,
    resolve_role_rule,
)
from app.services.word.format_rule_pack import FormatRulePackError, FormatRulePackLoader
from app.services.word.format_semantics import (
    FormatSemanticContract,
    FormatSemanticExecutor,
    MAX_FORMAT_SEMANTIC_CALLS,
)
from app.services.template_loader import TemplateLoader


ROLE_TEXT = {
    "document_title": "文档标题",
    "heading1": "一级标题",
    "heading2": "二级标题",
    "heading3": "三级标题",
    "heading4": "四级标题",
    "caption": "图表题",
    "note": "无编号注",
    "numbered_note": "有编号注",
    "list1_numbered": "一级编号列项",
    "list1_plain": "一级无编号列项",
    "list2_numbered": "二级编号列项",
    "list2_plain": "二级无编号列项",
    "appendix_title": "附录标题",
    "appendix_heading1": "附录一级标题",
    "appendix_heading2": "附录二级标题",
    "appendix_heading3": "附录三级标题",
    "table_body": "表正文",
    "body": "正文",
}

AI_ROLE_BATCH_SIZE = 20
AI_ROLE_MAX_PARAGRAPHS = 40
TABLE_CAPTION_SAMPLE_HEAD_ROWS = 3
TABLE_CAPTION_SAMPLE_TAIL_ROWS = 2
DEFAULT_TEMPLATE_ID = "technical-file-format-requirements"
SEMANTIC_ROLE_NAMES = (
    "document_title", "heading", "body", "list_item", "note", "caption",
    "toc_title", "toc_entry", "appendix_title", "appendix_heading", "formula",
    "table_body",
)


class WordFormatReviewer:
    def __init__(
        self,
        template_loader: Optional[TemplateLoader] = None,
        provider_client: Optional[ProviderClient] = None,
        rule_pack_loader: Optional[FormatRulePackLoader] = None,
    ) -> None:
        self.template_loader = template_loader or TemplateLoader()
        self.provider_client = provider_client or ProviderClient()
        self.rule_pack_loader = rule_pack_loader or FormatRulePackLoader()

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver("word.format_review"))
        except Exception as exc:
            return {"authSnapshotStatus": "unavailable", "authSnapshotError": type(exc).__name__}

    def review(
        self,
        request: WordDocumentRequest,
        trace_id: str = "",
        task_auth: Optional[Dict] = None,
        semantic_state: Optional[Dict] = None,
        max_semantic_batches: Optional[int] = None,
    ) -> Dict:
        requested_template = request.options.template_id or DEFAULT_TEMPLATE_ID
        template = self._resolve_template(requested_template)
        paragraphs = body_paragraphs(request)
        ai_diagnostics = self._empty_ai_diagnostics()
        table_caption_suggestions: Dict[str, Dict] = {}
        if trace_id:
            ai_roles, ai_batch_count, ai_diagnostics = self._classify_roles_with_ai(
                request,
                template,
                trace_id,
                task_auth=task_auth,
                semantic_state=semantic_state,
                max_semantic_batches=max_semantic_batches,
            )
        else:
            ai_roles, ai_batch_count = {}, 0
        if (
            semantic_state is not None
            and max_semantic_batches is not None
            and not ai_diagnostics.get("semanticComplete", True)
        ):
            return {
                "_semanticComplete": False,
                "_semanticState": ai_diagnostics.pop("_semanticState", semantic_state),
            }
        if trace_id:
            table_caption_suggestions, table_caption_diagnostics = self._suggest_missing_table_captions(
                request,
                trace_id,
                task_auth=task_auth,
                used_calls=int(ai_diagnostics.get("aiCallCount", 0) or 0),
            )
            ai_diagnostics.update(table_caption_diagnostics)
        provider = "local"
        if ai_roles or any(
            isinstance(item, dict) and item.get("status") == "suggested"
            for item in table_caption_suggestions.values()
        ):
            if hasattr(self.provider_client, "build_provider_source"):
                provider = self.provider_client.build_provider_source(
                    "word.format_review", task_auth=task_auth
                )
            else:
                provider = "工作流平台"
        issues = self._build_issues(request, template, ai_roles, table_caption_suggestions)
        issues = self._annotate_issues(issues, template)
        summary = {
            "scope": request.selection_mode,
            "templateId": template["id"],
            "rulePackVersion": template.get("_rulePackVersion", "legacy-template"),
            "rulePackSha256": template.get("_rulePackSha256", ""),
            "authorizedAlgorithmVersion": template.get("_algorithmAdapterVersion", ""),
            "provider": provider if (ai_roles or table_caption_suggestions) else "local",
            "paragraphCount": len(paragraphs),
            "issueCount": len(issues),
            "aiClassifiedParagraphCount": len(ai_roles),
            "localFallbackParagraphCount": max(len(paragraphs) - len(ai_roles), 0),
            "aiBatchCount": ai_batch_count,
            **ai_diagnostics,
        }
        binding = self._snapshot_binding(request)
        if any(binding.values()):
            summary["snapshotBinding"] = binding
        if isinstance(task_auth, dict):
            summary["modelConfigurationId"] = str(task_auth.get("modelConfigurationId", ""))
            configuration = task_auth.get("modelConfiguration")
            if isinstance(configuration, dict):
                summary["modelConfigurationVersion"] = int(configuration.get("configVersion") or 1)
        return {
            "issues": [self._dump_issue(issue) for issue in issues],
            "summary": summary,
        }

    def _dump_issue(self, issue: FormatReviewIssue) -> Dict:
        if hasattr(issue, "model_dump"):
            return issue.model_dump(by_alias=True)
        return issue.dict(by_alias=True)

    def _resolve_template(self, template_id: str) -> Dict:
        try:
            rule_pack = self.rule_pack_loader.load(template_id)
            template = deepcopy(rule_pack["template"])
            template["_rulePackVersion"] = rule_pack["version"]
            template["_rulePackSha256"] = rule_pack["integrity"]["contentSha256"]
            template["_templateHash"] = template["sourceDocumentSha256"]
            template["_algorithmAdapterVersion"] = rule_pack["algorithm"]["adapterVersion"]
            template["_rulePackRules"] = deepcopy(rule_pack["rules"])
            return template
        except FileNotFoundError:
            raise FormatRulePackError("FORMAT_RULE_PACK_REQUIRED {0}".format(template_id))

    def _build_issues(
        self,
        request: WordDocumentRequest,
        template: Dict,
        ai_roles: Optional[Dict[int, Dict]] = None,
        table_caption_suggestions: Optional[Dict[str, Dict]] = None,
    ) -> List[FormatReviewIssue]:
        issues: List[FormatReviewIssue] = []
        page_issue = self._build_page_issue(request, template)
        if page_issue:
            issues.append(page_issue)

        issues.extend(
            self._authorized_structure_issues(
                request, template, table_caption_suggestions or {}
            )
        )

        ai_roles = ai_roles or {}
        structure_facts = self._format_structure_facts(request)
        role_facts = {}
        for item in structure_facts.get("paragraphs", []):
            if not isinstance(item, dict):
                continue
            try:
                paragraph_index = int(item.get("paragraphIndex", 0) or 0)
            except (TypeError, ValueError):
                continue
            if paragraph_index > 0:
                role_facts[paragraph_index] = item
        pack = {"template": template, "rules": template.get("_rulePackRules", [])}
        for paragraph in body_paragraphs(request):
            fact = role_facts.get(paragraph.index, {"paragraphIndex": paragraph.index})
            deterministic_role = classify_role_fact(fact)
            role_result = deterministic_role
            ai_role = ai_roles.get(paragraph.index)
            if isinstance(ai_role, dict) and ai_role.get("status") == "confirmed":
                if deterministic_role.get("status") != "confirmed":
                    if deterministic_role.get("status") != "conflict":
                        role_result = {
                            "role": ai_role.get("role", "unknown"),
                            "attributes": deepcopy(ai_role.get("attributes", {})),
                            "status": "confirmed",
                            "confidence": ai_role.get("confidence"),
                            "evidence": deterministic_role.get("evidence", []) + ["model_role_confirmed"],
                        }
                elif not self._same_role(deterministic_role, ai_role):
                    role_result = {
                        "role": "unknown",
                        "attributes": {},
                        "status": "conflict",
                        "evidence": deterministic_role.get("evidence", []) + ["model_role_conflict"],
                    }
                else:
                    role_result = {
                        **deterministic_role,
                        "evidence": deterministic_role.get("evidence", []) + ["model_role_confirmed"],
                    }
            if role_result.get("status") != "confirmed":
                issues.append(self._role_confirmation_issue(paragraph, role_result))
                continue
            mapping = resolve_role_rule(role_result, pack)
            if mapping.get("status") != "mapped":
                issues.append(
                    FormatReviewIssue(
                        ruleId="structure.role_mapping",
                        paragraphIndex=paragraph.index,
                        role=role_result.get("role", "unknown"),
                        message="已确认的格式语义角色未配置模板规则映射。",
                        currentValue=role_result.get("role", "unknown"),
                        expectedValue="已配置的模板规则键",
                        suggestion="请为该语义角色配置模板规则映射后再审查格式。",
                    )
                )
                continue
            rule = template.get("roleRules", {}).get(mapping["ruleKey"], {})
            issues.extend(self._paragraph_issues(paragraph, rule, role_result.get("role", "unknown")))
        return issues

    def _same_role(self, left: Dict, right: Dict) -> bool:
        return left.get("role") == right.get("role") and left.get("attributes", {}) == right.get("attributes", {})

    def _role_confirmation_issue(self, paragraph: Paragraph, role_result: Dict) -> FormatReviewIssue:
        status = role_result.get("status", "needs_confirmation")
        message = "段落格式语义角色无法确认。"
        if status == "conflict":
            message = "段落格式语义证据存在冲突，需要核对。"
        return FormatReviewIssue(
            ruleId="structure.role_confirmation",
            paragraphIndex=paragraph.index,
            role="unknown",
            message=message,
            currentValue=json.dumps(role_result.get("evidence", []), ensure_ascii=False),
            expectedValue="明确结构事实或两类独立强证据",
            suggestion="请核对段落的结构、编号、题注或标题事实。",
        )

    def _table_caption_candidates(self, request: WordDocumentRequest) -> List[Dict]:
        facts = self._format_structure_facts(request)
        blocks = [deepcopy(block) for block in facts.get("blocks", []) if isinstance(block, dict)]
        table_facts = [table for table in facts.get("tables", []) if isinstance(table, dict)]
        if not blocks:
            blocks = [deepcopy(paragraph) for paragraph in facts.get("paragraphs", []) if isinstance(paragraph, dict)]
            blocks.extend(deepcopy(table) for table in table_facts)
        table_results_by_id = {}
        table_facts_by_id = {}
        for table in table_facts:
            table_id = str(table.get("tableId") or table.get("objectId") or table.get("blockId") or "")
            if not table_id:
                continue
            table_facts_by_id[table_id] = table
            table_results_by_id[table_id] = classify_table_fact(table)
        for block in blocks:
            if str(block.get("blockType") or block.get("type") or "") != "table":
                continue
            table_id = str(block.get("tableId") or block.get("objectId") or block.get("blockId") or "")
            result = table_results_by_id.get(table_id)
            if result:
                block["captionEligible"] = result.get("captionEligible", False)
        association_results = associate_captions(blocks)
        blocks_by_id = {
            str(block.get("tableId") or block.get("objectId") or block.get("blockId") or ""): block
            for block in blocks
            if isinstance(block, dict)
        }
        candidates = []
        for association in association_results:
            if association.get("status") != "missing" or association.get("captionType") != "table":
                continue
            table_id = str(association.get("objectId") or "")
            table = table_facts_by_id.get(table_id) or blocks_by_id.get(table_id)
            if not isinstance(table, dict):
                continue
            table_result = table_results_by_id.get(table_id) or classify_table_fact(table)
            if table_result.get("tableType") != "data" or not table_result.get("captionEligible"):
                continue
            evidence = self._build_table_caption_evidence(table, table_result, blocks, request)
            candidates.append({
                "blockId": table_id,
                "tableId": table_id,
                "tableType": "data",
                "captionStatus": "missing",
                "associationStatus": "missing",
                "association": deepcopy(association),
                "evidence": evidence,
            })
        return candidates

    @staticmethod
    def _table_rows(table: Dict) -> List[Dict]:
        rows = []
        for row_index, row in enumerate(table.get("rows", []) if isinstance(table.get("rows"), list) else []):
            if not isinstance(row, dict):
                continue
            cells = []
            for column_index, cell in enumerate(row.get("cells", []) if isinstance(row.get("cells"), list) else []):
                if not isinstance(cell, dict):
                    continue
                cells.append({
                    "columnIndex": cell.get("columnIndex", cell.get("column", column_index)),
                    "text": str(cell.get("text", "") or ""),
                    "isHeader": bool(cell.get("isHeader", cell.get("header", False))),
                    "rowSpan": int(cell.get("rowSpan", cell.get("rowspan", 1)) or 1),
                    "columnSpan": int(cell.get("columnSpan", cell.get("colSpan", 1)) or 1),
                    "mergeId": str(cell.get("mergeId", "") or ""),
                })
            if cells:
                rows.append({
                    "rowIndex": row.get("rowIndex", row_index),
                    "cells": cells,
                })
        return rows

    def _build_table_caption_evidence(
        self,
        table: Dict,
        table_result: Dict,
        blocks: List[Dict],
        request: WordDocumentRequest,
    ) -> Dict:
        rows = self._table_rows(table)
        row_indexes = [int(row.get("rowIndex", index) or index) for index, row in enumerate(rows)]
        header_rows = int(table.get("headerRows", table_result.get("headerRows", 0)) or 0)
        if not header_rows:
            header_indexes = {
                int(row.get("rowIndex", index) or index)
                for index, row in enumerate(rows)
                if any(cell.get("isHeader") for cell in row.get("cells", []))
            }
            header_rows = len([index for index in row_indexes if index in header_indexes])
        column_count = 0
        merged_relations = []
        for row in rows:
            for cell in row.get("cells", []):
                column = int(cell.get("columnIndex", 0) or 0)
                span = max(1, int(cell.get("columnSpan", 1) or 1))
                column_count = max(column_count, column + span)
                if int(cell.get("rowSpan", 1) or 1) > 1 or span > 1 or cell.get("mergeId"):
                    merged_relations.append({
                        "rowIndex": row.get("rowIndex"),
                        "columnIndex": column,
                        "rowSpan": max(1, int(cell.get("rowSpan", 1) or 1)),
                        "columnSpan": span,
                        "mergeId": cell.get("mergeId", ""),
                    })
        row_count = int(table.get("rowCount", 0) or 0) or len(row_indexes)
        column_count = int(table.get("columnCount", 0) or 0) or column_count
        heading_candidates = []
        table_position = int(table.get("paragraphIndex", 0) or 0)
        for block in blocks:
            block_type = str(block.get("blockType") or block.get("type") or "")
            block_position = int(block.get("paragraphIndex", 0) or 0)
            if block_type in {"heading", "paragraph"} and block_position <= table_position and str(block.get("text", "")).strip():
                heading_candidates.append((block_position, str(block.get("text", "")).strip()))
        for heading in request.content.headings:
            if heading.paragraph_index is not None and heading.paragraph_index <= table_position:
                heading_candidates.append((heading.paragraph_index, heading.text.strip()))
        heading_candidates.sort(key=lambda item: item[0])
        nearby_context = []
        table_block_index = next(
            (index for index, block in enumerate(blocks) if str(block.get("tableId") or block.get("blockId") or "") == str(table.get("tableId") or table.get("blockId") or "")),
            None,
        )
        if table_block_index is not None:
            for block in blocks[max(0, table_block_index - 2):table_block_index + 3]:
                if block is table or str(block.get("blockType") or "") in {"table", "caption"}:
                    continue
                text = str(block.get("text", "") or "").strip()
                if text:
                    nearby_context.append({
                        "blockType": block.get("blockType", ""),
                        "paragraphIndex": block.get("paragraphIndex"),
                        "text": text,
                    })
        headers = [
            row for row in rows
            if int(row.get("rowIndex", 0) or 0) < header_rows
            or any(cell.get("isHeader") for cell in row.get("cells", []))
        ]
        evidence = {
            "evidenceStatus": "complete",
            "sampling": "full_table",
            "tableId": table.get("tableId") or table.get("blockId"),
            "rowCount": row_count,
            "columnCount": column_count,
            "headerRows": header_rows,
            "headers": headers,
            "mergedRelations": merged_relations,
            "rows": rows,
            "units": deepcopy(table.get("units", table.get("unit", []))),
            "source": deepcopy(table.get("source", table.get("dataSource", table.get("sourceText", "")))),
            "footnotes": deepcopy(table.get("footnotes", table.get("footnotesText", table.get("notes", [])))),
            "heading": heading_candidates[-1][1] if heading_candidates else "",
            "nearbyContext": nearby_context,
            "tableEvidence": deepcopy(table_result.get("evidence", [])),
        }
        candidate_for_budget = {"blockId": evidence["tableId"], "evidence": evidence}
        budget_overhead = "\n" + ("表题建议约束。" * 80)
        try:
            FormatSemanticContract.require_input_budget(
                json.dumps(candidate_for_budget, ensure_ascii=False, separators=(",", ":")) + budget_overhead
            )
            return evidence
        except AdapterError:
            ordered_rows = rows
            sampled_rows = ordered_rows[:TABLE_CAPTION_SAMPLE_HEAD_ROWS]
            for row in ordered_rows[-TABLE_CAPTION_SAMPLE_TAIL_ROWS:]:
                if row not in sampled_rows:
                    sampled_rows.append(row)
            evidence["evidenceStatus"] = "restricted"
            evidence["sampling"] = "first_three_and_last_two_rows"
            evidence["omittedRowCount"] = max(len(ordered_rows) - len(sampled_rows), 0)
            evidence["rows"] = sampled_rows
            try:
                FormatSemanticContract.require_input_budget(
                    json.dumps({"blockId": evidence["tableId"], "evidence": evidence}, ensure_ascii=False, separators=(",", ":")) + budget_overhead
                )
                return evidence
            except AdapterError:
                evidence["evidenceStatus"] = "insufficient"
                evidence["sampling"] = "unavailable"
                evidence["rows"] = []
                evidence["insufficientReason"] = "bounded_table_evidence_over_budget"
                return evidence

    def _suggest_missing_table_captions(
        self,
        request: WordDocumentRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        used_calls: int = 0,
    ) -> Tuple[Dict[str, Dict], Dict]:
        candidates = self._table_caption_candidates(request)
        diagnostics = {
            "tableCaptionCandidateCount": len(candidates),
            "tableCaptionSuggestedCount": 0,
            "tableCaptionRestrictedCount": sum(
                1 for item in candidates if item.get("evidence", {}).get("evidenceStatus") == "restricted"
            ),
            "tableCaptionNotAssessableCount": 0,
            "tableCaptionCallCount": 0,
            "tableCaptionSemanticStatus": "not_needed" if not candidates else "not_run",
        }
        if not candidates:
            return {}, diagnostics
        suggestions = {
            item["tableId"]: {"status": "not_assessable", "evidence": deepcopy(item["evidence"])}
            for item in candidates
            if item.get("evidence", {}).get("evidenceStatus") == "insufficient"
        }
        candidates = [
            item for item in candidates
            if item.get("evidence", {}).get("evidenceStatus") in {"complete", "restricted"}
        ]
        diagnostics["tableCaptionNotAssessableCount"] = len(suggestions)
        if not candidates:
            diagnostics["tableCaptionSemanticStatus"] = "degraded"
            return suggestions, diagnostics
        configured = self._task_auth_configured(task_auth) if task_auth is not None else self.provider_client.is_task_configured("word.format_review")
        if not configured or not self._semantic_protocol_ready(task_auth) or self._direct_capability_unknown(task_auth):
            diagnostics["tableCaptionSemanticStatus"] = "degraded"
            diagnostics["tableCaptionNotAssessableCount"] += len(candidates)
            suggestions.update({
                item["tableId"]: {"status": "not_assessable", "evidence": deepcopy(item["evidence"])}
                for item in candidates
            })
            return suggestions, diagnostics
        current_calls = max(0, int(used_calls or 0))
        for candidate in candidates:
            if current_calls >= MAX_FORMAT_SEMANTIC_CALLS or not hasattr(self.provider_client, "format_semantics"):
                diagnostics["tableCaptionNotAssessableCount"] += 1
                suggestions[candidate["tableId"]] = {"status": "not_assessable", "evidence": deepcopy(candidate["evidence"])}
                continue
            candidate_payload = {candidate["blockId"]: candidate}
            prompt = self._build_table_caption_prompt(request, candidate)
            input_data = {
                "scene": "word",
                "task_id": "word.format_review",
                "taskType": "word.format_review",
                "trace_id": trace_id,
                "templateId": request.options.template_id or DEFAULT_TEMPLATE_ID,
                "scope": request.selection_mode,
                "operation": "suggest_table_caption",
                "candidateBlockIds": [candidate["blockId"]],
                "snapshotBinding": self._snapshot_binding(request),
                "candidate_json": json.dumps(candidate_payload, ensure_ascii=False, sort_keys=True),
            }
            if hasattr(self.provider_client, "build_task_input_data"):
                input_data = self.provider_client.build_task_input_data(
                    "word.format_review", trace_id, input_data
                )

            def semantic_call(query, output_budget):
                return self.provider_client.format_semantics(
                    "suggest_table_caption",
                    trace_id,
                    input_data,
                    query,
                    task_auth=task_auth,
                    output_token_budget=output_budget,
                )

            executor = FormatSemanticExecutor(
                semantic_call,
                used_calls=current_calls,
                task_auth=task_auth or {"accessMethod": "workflow_platform"},
            )
            outcome = executor.execute(
                "suggest_table_caption",
                prompt,
                candidate_payload,
                self._snapshot_binding(request),
            )
            current_calls = outcome["usedCalls"]
            diagnostics["tableCaptionCallCount"] += outcome["usedCalls"] - diagnostics.get("aiCallCount", used_calls)
            diagnostics["aiCallCount"] = current_calls
            diagnostics["aiRetryCount"] = diagnostics.get("aiRetryCount", 0) + outcome["retryCount"]
            diagnostics["aiCorrectionCount"] = diagnostics.get("aiCorrectionCount", 0) + outcome["correctionCount"]
            if outcome.get("error") is not None or not outcome.get("items"):
                diagnostics["tableCaptionNotAssessableCount"] += 1
                suggestions[candidate["tableId"]] = {"status": "not_assessable", "evidence": deepcopy(candidate["evidence"])}
                continue
            item = outcome["items"][0]
            suggestions[candidate["tableId"]] = {
                "status": item.get("status", "suggested"),
                "suggestion": item.get("suggestion", ""),
                "evidence": deepcopy(candidate["evidence"]),
            }
            if item.get("status") == "suggested" and item.get("suggestion"):
                diagnostics["tableCaptionSuggestedCount"] += 1
            else:
                diagnostics["tableCaptionNotAssessableCount"] += 1
        diagnostics["tableCaptionSemanticStatus"] = (
            "completed" if diagnostics["tableCaptionNotAssessableCount"] == 0 else "degraded"
        )
        return suggestions, diagnostics

    def _build_table_caption_prompt(self, request: WordDocumentRequest, candidate: Dict) -> str:
        payload = {
            "schemaVersion": "format_semantics.v1",
            "operation": "suggest_table_caption",
            "snapshotBinding": self._snapshot_binding(request),
            "candidates": {candidate["blockId"]: candidate},
        }
        return "\n".join([
            "你是技术文件表题建议助手。",
            "只处理已确定为数据表、已确认缺少表题且不存在歧义关联的候选。",
            "只能根据 evidence 视图生成只读表题正文；不得补造证据外的机构、时间、地域、数值或统计口径。",
            "evidenceStatus=restricted 时，只能使用首三行和末两行样例，不得将样例描述为整表。",
            "证据不足时返回 status=not_assessable 且 suggestion 为空。",
            "suggestion 最长 80 个 Unicode 字符，不含表前缀、编号、Markdown、换行或解释。",
            "只返回 JSON，不要 Markdown、推理过程或思考标签。",
            json.dumps(payload, ensure_ascii=False),
        ])

    def _format_structure_facts(self, request: WordDocumentRequest) -> Dict:
        structure = request.content.document_structure or {}
        supplied = structure.get("formatFacts") if isinstance(structure.get("formatFacts"), dict) else {}
        facts = deepcopy(supplied)
        format_blocks = structure.get("formatBlocks")
        if isinstance(format_blocks, list) and format_blocks:
            facts["blocks"] = deepcopy(format_blocks)
            facts["paragraphs"] = [
                {
                    **deepcopy(block),
                    "paragraphIndex": block.get("paragraphIndex"),
                    "blockType": block.get("blockType"),
                    "styleName": (block.get("format") or {}).get("styleName", "") if isinstance(block.get("format"), dict) else "",
                }
                for block in format_blocks
                if isinstance(block, dict) and block.get("blockType") in {"paragraph", "heading", "listItem", "caption", "formula", "tableCell"}
            ]
            facts["tables"] = []
            for block in format_blocks:
                if not isinstance(block, dict) or block.get("blockType") != "table":
                    continue
                table_fact = deepcopy(block)
                cells = []
                for row_index, row in enumerate(block.get("rows", [])):
                    if not isinstance(row, dict):
                        continue
                    for column_index, cell in enumerate(row.get("cells", [])):
                        if isinstance(cell, dict):
                            cells.append({
                                **deepcopy(cell),
                                "text": cell.get("text", ""),
                                "row": cell.get("rowIndex", row.get("rowIndex", row_index)),
                                "column": cell.get("columnIndex", column_index),
                                "isHeader": cell.get("isHeader", False),
                            })
                table_fact["tableId"] = block.get("tableId") or block.get("blockId")
                table_fact["cells"] = cells
                facts["tables"].append(table_fact)
        if "paragraphs" not in facts:
            facts["paragraphs"] = []
        if not facts["paragraphs"]:
            heading_by_index = {
                heading.paragraph_index: heading
                for heading in request.content.headings
                if heading.paragraph_index is not None
            }
            facts["paragraphs"] = [
                {
                    "paragraphIndex": paragraph.index,
                    "blockType": "heading" if paragraph.index in heading_by_index or paragraph.outline_level else "",
                    "text": paragraph.text,
                    "styleName": paragraph.style_name or "",
                    "outlineLevel": paragraph.outline_level or 0,
                    "headingLevel": (
                        heading_by_index[paragraph.index].level
                        if paragraph.index in heading_by_index
                        else paragraph.outline_level or 0
                    ),
                }
                for paragraph in body_paragraphs(request)
            ]
        facts["headings"] = [
            {"level": heading.level, "text": heading.text}
            for heading in request.content.headings
        ]
        return facts

    def _authorized_structure_issues(
        self,
        request: WordDocumentRequest,
        template: Dict,
        table_caption_suggestions: Optional[Dict[str, Dict]] = None,
    ) -> List[FormatReviewIssue]:
        facts = self._format_structure_facts(request)
        facts.setdefault("appendixFacts", [])
        facts.setdefault("noteFacts", [])
        pack = {"template": template, "rules": template.get("_rulePackRules", [])}
        audit = audit_format_facts(facts, pack)
        issues: List[FormatReviewIssue] = []
        table_caption_suggestions = table_caption_suggestions or {}
        for warning in audit["issues"]:
            if warning.get("ruleId") != "structure.heading_hierarchy":
                continue
            issues.append(
                FormatReviewIssue(
                    ruleId="structure.heading_hierarchy",
                    paragraphIndex=None,
                    role="heading",
                    message="标题层级出现跳级。",
                    currentValue=str(warning.get("level", "")),
                    expectedValue="不超过一级跳级",
                    suggestion="请补齐缺失的标题层级。",
                )
            )
        for index, result in enumerate(audit.get("tables", []), start=1):
            if result.get("tableType") == "unknown":
                issues.append(
                    FormatReviewIssue(
                        ruleId="structure.table_semantics",
                        paragraphIndex=None,
                        role="table",
                        message="表格缺少可确认的数据表结构证据。",
                        currentValue=str(result.get("evidence", [])),
                        expectedValue="表头及重复数据行",
                        suggestion="请补充表头和至少一行结构一致的数据记录。",
                    )
                )
        for result in audit.get("captions", []):
            status = result.get("status")
            if status == "missing" and result.get("captionType") == "table":
                table_id = str(result.get("objectId") or "")
                suggestion = table_caption_suggestions.get(table_id, {})
                evidence = suggestion.get("evidence") if isinstance(suggestion, dict) else None
                suggestion_status = suggestion.get("status") if isinstance(suggestion, dict) else None
                if suggestion_status == "suggested":
                    issues.append(
                        FormatReviewIssue(
                            ruleId="structure.missing_table_caption",
                            paragraphIndex=None,
                            role="table",
                            message="数据表缺少表题，已生成只读题注建议。",
                            currentValue=table_id,
                            expectedValue="表题正文",
                            suggestion=str(suggestion.get("suggestion", "")),
                            evidence=[deepcopy(evidence)] if isinstance(evidence, dict) else [],
                            dataStatus="verified" if (evidence or {}).get("evidenceStatus") == "complete" else "insufficient",
                        )
                    )
                    continue
                if suggestion_status in {"not_assessable", "text_evidence_only"}:
                    issues.append(
                        FormatReviewIssue(
                            ruleId="structure.missing_table_caption",
                            paragraphIndex=None,
                            role="table",
                            message="数据表缺少表题，但当前证据不足以可靠生成建议。",
                            currentValue=table_id,
                            expectedValue="表题正文",
                            suggestion="无法可靠建议",
                            evidence=[deepcopy(evidence)] if isinstance(evidence, dict) else [],
                            dataStatus="not_assessable",
                        )
                    )
                    continue
            if status in {"orphaned", "missing", "ambiguous"}:
                issues.append(
                    FormatReviewIssue(
                        ruleId="structure.caption_association",
                        paragraphIndex=result.get("captionIndex"),
                        role="caption" if result.get("captionIndex") is not None else result.get("captionType", "table"),
                        message="题注未能与唯一兼容对象建立可追溯关联。",
                        currentValue=json.dumps(result, ensure_ascii=False),
                        expectedValue="唯一且同节同正文故事的兼容对象",
                        suggestion="请核对题注类型、所在节和相邻对象关系。",
                    )
                )
            elif status == "associated" and result.get("placementStatus") in {"violation", "non_adjacent"}:
                issues.append(
                    FormatReviewIssue(
                        ruleId="structure.caption_placement",
                        paragraphIndex=result.get("captionIndex"),
                        role="caption",
                        message="题注已关联，但位置不符合模板要求。",
                        currentValue=result.get("placement", "unknown"),
                        expectedValue=result.get("expectedPlacement", "相邻位置"),
                        suggestion="请调整题注与图表对象的相对位置。",
                    )
                )
        return issues

    def _annotate_issues(
        self, issues: List[FormatReviewIssue], template: Dict
    ) -> List[FormatReviewIssue]:
        rule_sources = {
            rule.get("id"): rule.get("source", "")
            for rule in template.get("_rulePackRules", [])
            if isinstance(rule, dict)
        }
        metadata = {
            "source": "compiled-template",
            "template_hash": template.get("_templateHash", ""),
            "rule_version": template.get("_rulePackVersion", ""),
            "rule_pack_sha256": template.get("_rulePackSha256", ""),
        }
        annotated = []
        for issue in issues:
            update = dict(metadata)
            update["source"] = rule_sources.get(issue.rule_id, metadata["source"])
            if hasattr(issue, "model_copy"):
                annotated.append(issue.model_copy(update=update))
            else:
                annotated.append(issue.copy(update=update))
        return annotated

    def _build_page_issue(self, request: WordDocumentRequest, template: Dict) -> Optional[FormatReviewIssue]:
        page_rule = template.get("page", {})
        if not page_rule:
            return None
        current = request.content.document_structure.get("page_setup", {}) or {}
        expected = {
            "marginTop": page_rule.get("marginTopTwips"),
            "marginBottom": page_rule.get("marginBottomTwips"),
            "marginLeft": page_rule.get("marginLeftTwips"),
            "marginRight": page_rule.get("marginRightTwips"),
        }
        if current and all(self._roughly_equal(current.get(key), value) for key, value in expected.items() if value is not None):
            return None
        return FormatReviewIssue(
            ruleId="page_setup",
            paragraphIndex=0,
            role="page_setup",
            message="页面设置不符合模板要求。",
            currentValue=json.dumps(current, ensure_ascii=False) if current else "未读取",
            expectedValue="A4 页面及模板页边距",
            suggestion="建议按模板设置 A4 页面和页边距。",
        )

    def _paragraph_issues(self, paragraph: Paragraph, rule: Dict, role: str) -> List[FormatReviewIssue]:
        issues: List[FormatReviewIssue] = []
        current_style = paragraph.style_name or "Normal"
        target_style = rule.get("styleName", current_style)
        if current_style != target_style:
            issues.append(
                self._issue(
                    paragraph,
                    role,
                    "style_name",
                    "段落样式不符合模板要求。",
                    current_style,
                    target_style,
                    "建议按{0}套用模板样式。".format(ROLE_TEXT.get(role, role)),
                )
            )
        if rule.get("fontName") and paragraph.font_name and not self._font_matches(paragraph.font_name, rule):
            issues.append(
                self._issue(
                    paragraph,
                    role,
                    "font_name",
                    "字体不符合模板要求。",
                    paragraph.font_name,
                    rule["fontName"],
                    "建议字体调整为{0}。".format(rule["fontName"]),
                )
            )
        current_font_size = self._normalize_font_size(paragraph.font_size)
        if rule.get("fontSize") is not None and current_font_size is not None:
            if abs(current_font_size - float(rule["fontSize"])) > 0.01:
                issues.append(
                    self._issue(
                        paragraph,
                        role,
                        "font_size",
                        "字号不符合模板要求。",
                        "{0}pt".format(current_font_size),
                        "{0}pt".format(rule["fontSize"]),
                        "建议字号调整为{0}pt。".format(rule["fontSize"]),
                    )
                )
        if rule.get("lineSpacing") is not None and paragraph.line_spacing is not None:
            normalized = self._normalize_line_spacing(paragraph.line_spacing)
            if normalized is not None and abs(normalized - float(rule["lineSpacing"])) > 0.05:
                issues.append(
                    self._issue(
                        paragraph,
                        role,
                        "line_spacing",
                        "行距不符合模板要求。",
                        "{0}倍".format(normalized),
                        "{0}倍".format(rule["lineSpacing"]),
                        "建议行距调整为{0}倍。".format(rule["lineSpacing"]),
                    )
                )
        current_alignment = self._normalize_alignment(paragraph.alignment)
        expected_alignment = self._normalize_alignment(rule.get("alignment"))
        if expected_alignment and current_alignment and current_alignment != expected_alignment:
            issues.append(
                self._issue(
                    paragraph,
                    role,
                    "alignment",
                    "对齐方式不符合模板要求。",
                    current_alignment,
                    expected_alignment,
                    "建议对齐方式调整为{0}。".format(rule["alignment"]),
                )
            )
        if rule.get("firstLineIndentTwips") is not None:
            current_indent = paragraph.first_line_indent
            if current_indent is not None and not self._roughly_equal(current_indent, rule["firstLineIndentTwips"]):
                issues.append(
                    self._issue(
                        paragraph,
                        role,
                        "first_line_indent",
                        "首行缩进不符合模板要求。",
                        str(current_indent),
                        str(rule["firstLineIndentTwips"]),
                        "建议按模板设置首行缩进。",
                    )
                )
        return issues

    def _issue(
        self,
        paragraph: Paragraph,
        role: str,
        rule_id: str,
        message: str,
        current_value: str,
        expected_value: str,
        suggestion: str,
    ) -> FormatReviewIssue:
        return FormatReviewIssue(
            ruleId=rule_id,
            paragraphIndex=paragraph.index,
            role=role,
            message=message,
            currentValue=current_value,
            expectedValue=expected_value,
            suggestion=suggestion,
        )

    def _classify_roles_with_ai(
        self,
        request: WordDocumentRequest,
        template: Dict,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        semantic_state: Optional[Dict] = None,
        max_semantic_batches: Optional[int] = None,
    ) -> Tuple[Dict[int, Dict], int, Dict]:
        task_type = "word.format_review"
        diagnostics = self._empty_ai_diagnostics()
        candidates = self._role_candidates(request)
        diagnostics["aiCandidateCount"] = len(candidates)
        if not candidates:
            diagnostics["semanticStatus"] = "not_needed"
            diagnostics["aiFallbackReason"] = "no_candidates"
            if hasattr(self.provider_client, "record_skipped_debug"):
                self.provider_client.record_skipped_debug(
                    task_type,
                    trace_id,
                    self._build_role_prompt(request, template, []),
                    "no_candidates",
                    provider="local",
                )
            return {}, 0, diagnostics

        configured = self._task_auth_configured(task_auth) if task_auth is not None else self.provider_client.is_task_configured(task_type)
        if not configured:
            diagnostics["semanticStatus"] = "degraded"
            diagnostics["aiFallbackReason"] = "provider_not_configured"
            if hasattr(self.provider_client, "record_unconfigured_debug"):
                self.provider_client.record_unconfigured_debug(
                    task_type,
                    trace_id,
                    self._build_role_prompt(request, template, candidates[:AI_ROLE_BATCH_SIZE]),
                )
            return {}, 0, diagnostics

        if not self._semantic_protocol_ready(task_auth):
            diagnostics["semanticStatus"] = "degraded"
            diagnostics["aiFallbackReason"] = "format_semantic_protocol_not_ready"
            if hasattr(self.provider_client, "record_skipped_debug"):
                self.provider_client.record_skipped_debug(
                    task_type,
                    trace_id,
                    self._build_role_prompt(request, template, candidates[:AI_ROLE_BATCH_SIZE]),
                    "format_semantic_protocol_not_ready",
                    provider="local",
                )
            return {}, 0, diagnostics

        if self._direct_capability_unknown(task_auth):
            diagnostics["semanticStatus"] = "degraded"
            diagnostics["aiFallbackReason"] = "model_capability_unknown"
            if hasattr(self.provider_client, "record_skipped_debug"):
                self.provider_client.record_skipped_debug(
                    task_type,
                    trace_id,
                    self._build_role_prompt(request, template, candidates[:AI_ROLE_BATCH_SIZE]),
                    "model_capability_unknown",
                    provider="local",
                )
            return {}, 0, diagnostics

        roles: Dict[int, Dict] = {}
        batch_count = 0
        ai_candidates = candidates[:AI_ROLE_MAX_PARAGRAPHS]
        if len(candidates) > len(ai_candidates):
            diagnostics["aiFallbackReason"] = "ai_budget_limited"
        strict_binding = bool(all(self._snapshot_binding(request).values()))
        semantic_batches, oversized = self._semantic_batches(request, template, ai_candidates)
        diagnostics["aiSkippedCount"] += len(oversized)
        diagnostics["aiSkippedReasons"] = (
            ["input_over_budget"] * len(oversized)
        )
        state = semantic_state if isinstance(semantic_state, dict) else {}
        state_candidate_ids = state.get("candidateBlockIds")
        current_candidate_ids = [item["blockId"] for item in ai_candidates]
        if state_candidate_ids not in (None, current_candidate_ids):
            state = {}
        stored_roles = state.get("roles", {})
        if isinstance(stored_roles, dict):
            for key, value in stored_roles.items():
                try:
                    roles[int(key)] = deepcopy(value)
                except (TypeError, ValueError):
                    continue
        diagnostics.update(state.get("diagnostics", {}) if isinstance(state.get("diagnostics"), dict) else {})
        diagnostics["aiCandidateCount"] = len(candidates)
        diagnostics["aiSkippedCount"] = len(oversized)
        diagnostics["aiSkippedReasons"] = ["input_over_budget"] * len(oversized)
        start_batch = int(state.get("nextBatch", 0) or 0)
        phase_started_at = float(state.get("phaseStartedAt", time.monotonic()))
        if time.monotonic() - phase_started_at >= 10 * 60:
            diagnostics["semanticStatus"] = "degraded"
            diagnostics["semanticComplete"] = True
            diagnostics["aiFallbackReason"] = "semantic_phase_timeout"
            return roles, batch_count, diagnostics
        batches_run = 0
        for batch_index, batch in enumerate(semantic_batches[start_batch:], start=start_batch):
            if max_semantic_batches is not None and batches_run >= max_semantic_batches:
                break
            if diagnostics.get("aiCallCount", 0) >= MAX_FORMAT_SEMANTIC_CALLS:
                break
            batches_run += 1
            batch_by_block = {item["blockId"]: item for item in batch}
            batch_by_index = {item["paragraphIndex"]: item for item in batch}
            candidate_json = json.dumps(
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": "classify_role",
                    "snapshotBinding": self._snapshot_binding(request),
                    "candidates": batch_by_block,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            state["nextBatch"] = batch_index + 1
            prompt = self._build_role_prompt(request, template, batch)
            if hasattr(self.provider_client, "build_task_input_data"):
                input_data = self.provider_client.build_task_input_data(
                    task_type,
                    trace_id,
                    {
                        "templateId": template.get("id"),
                        "scope": request.selection_mode,
                        "operation": "classify_role",
                        "candidateBlockIds": list(batch_by_block),
                        "snapshotBinding": self._snapshot_binding(request),
                        "candidate_json": candidate_json,
                    },
                )
            else:
                input_data = {
                    "scene": "word",
                    "task_id": task_type,
                    "taskType": task_type,
                        "trace_id": trace_id,
                        "templateId": template.get("id"),
                        "scope": request.selection_mode,
                        "operation": "classify_role",
                        "candidateBlockIds": list(batch_by_block),
                        "snapshotBinding": self._snapshot_binding(request),
                        "candidate_json": candidate_json,
                    }
            batch_count += 1
            diagnostics["aiAttempted"] = True
            try:
                if hasattr(self.provider_client, "format_semantics"):
                    def semantic_call(query, output_budget):
                        return self.provider_client.format_semantics(
                            "classify_role",
                            trace_id,
                            input_data,
                            query,
                            task_auth=task_auth,
                            output_token_budget=output_budget,
                        )

                    executor = FormatSemanticExecutor(
                        semantic_call,
                        used_calls=diagnostics["aiCallCount"],
                        task_auth=task_auth or {"accessMethod": "workflow_platform"},
                        phase_started_at=phase_started_at,
                    )
                    outcome = executor.execute(
                        "classify_role",
                        prompt,
                        batch_by_block,
                        self._snapshot_binding(request),
                    )
                    diagnostics["aiCallCount"] = outcome["usedCalls"]
                    diagnostics["aiRetryCount"] += outcome["retryCount"]
                    diagnostics["aiCorrectionCount"] += outcome["correctionCount"]
                    if outcome.get("error") is not None:
                        if outcome["error"].code == "FORMAT_SEMANTIC_PROVIDER_ERROR":
                            diagnostics["aiRequestErrorCount"] += 1
                        else:
                            diagnostics["aiParseErrorCount"] += 1
                        continue
                    items = outcome["items"]
                    response_payload = outcome["payload"]
                elif hasattr(self.provider_client, "format_review_roles"):
                    if task_auth is None:
                        body = self.provider_client.format_review_roles(trace_id, input_data, prompt)
                    else:
                        body = self.provider_client.format_review_roles(
                            trace_id, input_data, prompt, task_auth=task_auth
                        )
                    answer = extract_answer(body)
                    response_payload = self._extract_semantic_payload(answer)
                    items = response_payload.get("items")
                else:
                    kwargs = {"task_auth": task_auth} if task_auth is not None else {}
                    body = self.provider_client.post_task(task_type, trace_id, input_data, prompt, **kwargs)
                    answer = extract_answer(body)
                    response_payload = self._extract_semantic_payload(answer)
                    items = response_payload.get("items")
            except AdapterError:
                diagnostics["aiRequestErrorCount"] += 1
                continue
            except (TypeError, ValueError, json.JSONDecodeError):
                diagnostics["aiRequestErrorCount"] += 1
                continue
            if strict_binding and response_payload.get("snapshotBinding") != self._snapshot_binding(request):
                diagnostics["aiInvalidBindingCount"] += 1
                continue
            if not isinstance(items, list):
                diagnostics["aiParseErrorCount"] += 1
                continue
            for item in items:
                if not isinstance(item, dict):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                block_id = str(item.get("blockId", "")).strip()
                candidate = batch_by_block.get(block_id) if strict_binding else None
                if strict_binding and candidate is None:
                    diagnostics["aiOutOfBatchCount"] += 1
                    continue
                raw_index = item.get("paragraphIndex", item.get("paragraph_index"))
                if raw_index is None and block_id in batch_by_block:
                    raw_index = batch_by_block[block_id].get("paragraphIndex")
                if raw_index is None and candidate is not None:
                    raw_index = candidate.get("paragraphIndex")
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                if candidate is None:
                    candidate = batch_by_index.get(index)
                if candidate is None:
                    diagnostics["aiOutOfBatchCount"] += 1
                    continue
                role = str(item.get("role", "")).strip()
                normalized = self._normalize_model_role(role, item)
                if normalized is None or normalized["role"] == "unknown":
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                if not self._model_target_allowed(normalized, candidate.get("allowedTargets", [])):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                confidence = item.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                confidence = max(0.0, min(1.0, confidence))
                if confidence < 0.85:
                    diagnostics["aiLowConfidenceCount"] += 1
                    continue
                if candidate.get("deterministicStatus") == "conflict":
                    diagnostics["aiConflictCount"] += 1
                    continue
                roles[index] = {
                    "role": normalized["role"],
                    "attributes": normalized["attributes"],
                    "status": "confirmed" if confidence >= 0.85 else "needs_confirmation",
                    "confidence": confidence,
                    "blockId": candidate["blockId"],
                    "evidence": ["model_candidate"],
                }
        semantic_complete = (
            start_batch + batches_run >= len(semantic_batches)
            or diagnostics.get("aiCallCount", 0) >= MAX_FORMAT_SEMANTIC_CALLS
        )
        if roles and len(roles) == len(ai_candidates) and not oversized:
            diagnostics["semanticStatus"] = "completed"
        else:
            diagnostics["semanticStatus"] = "degraded"
        diagnostics["semanticComplete"] = semantic_complete
        if not semantic_complete and semantic_state is not None:
            diagnostics["_semanticState"] = {
                "candidateBlockIds": current_candidate_ids,
                "nextBatch": int(state.get("nextBatch", start_batch) or start_batch),
                "roles": {str(key): deepcopy(value) for key, value in roles.items()},
                "phaseStartedAt": phase_started_at,
                "diagnostics": {
                    key: deepcopy(value)
                    for key, value in diagnostics.items()
                    if not key.startswith("_")
                },
            }
        if diagnostics["aiAttempted"] and not roles:
            if diagnostics["aiParseErrorCount"]:
                diagnostics["aiFallbackReason"] = "dify_response_not_role_json"
            elif diagnostics["aiRequestErrorCount"]:
                diagnostics["aiFallbackReason"] = "provider_request_failed"
            elif diagnostics["aiInvalidRoleCount"] or diagnostics["aiOutOfBatchCount"]:
                diagnostics["aiFallbackReason"] = "dify_response_no_valid_roles"
            elif not diagnostics["aiFallbackReason"]:
                diagnostics["aiFallbackReason"] = "dify_returned_no_roles"
        return roles, batch_count, diagnostics

    @staticmethod
    def _semantic_protocol_ready(task_auth: Optional[Dict]) -> bool:
        if not isinstance(task_auth, dict):
            return True
        if str(task_auth.get("accessMethod", "")) != "workflow_platform":
            return True
        readiness = task_auth.get("formatSemanticReadiness")
        if not isinstance(readiness, dict):
            return False
        return str(readiness.get("code", "")) == "ready"

    def _semantic_batches(
        self,
        request: WordDocumentRequest,
        template: Dict,
        candidates: List[Dict],
    ) -> Tuple[List[List[Dict]], List[Dict]]:
        batches: List[List[Dict]] = []
        oversized: List[Dict] = []
        current: List[Dict] = []
        for candidate in candidates:
            trial = current + [candidate]
            try:
                FormatSemanticContract.require_input_budget(
                    self._build_role_prompt(request, template, trial)
                )
            except AdapterError:
                if current:
                    batches.append(current)
                    current = []
                    try:
                        FormatSemanticContract.require_input_budget(
                            self._build_role_prompt(request, template, [candidate])
                        )
                    except AdapterError:
                        oversized.append(candidate)
                    else:
                        current = [candidate]
                else:
                    oversized.append(candidate)
                continue
            current = trial
            if len(current) >= AI_ROLE_BATCH_SIZE:
                batches.append(current)
                current = []
        if current:
            batches.append(current)
        return batches, oversized

    @staticmethod
    def _model_target_allowed(normalized: Dict, allowed_targets: List[Dict]) -> bool:
        for target in allowed_targets:
            if not isinstance(target, dict) or target.get("role") != normalized.get("role"):
                continue
            expected = target.get("attributes") or {}
            actual = normalized.get("attributes") or {}
            if all(actual.get(key) == value for key, value in expected.items()):
                return True
        return False

    def _role_candidates(self, request: WordDocumentRequest) -> List[Dict]:
        facts = self._format_structure_facts(request)
        role_facts = {
            int(item.get("paragraphIndex")): item
            for item in facts.get("paragraphs", [])
            if isinstance(item, dict) and str(item.get("paragraphIndex", "")).isdigit()
        }
        blocks = {
            int(item.get("paragraphIndex")): item
            for item in (request.content.document_structure or {}).get("formatBlocks", [])
            if isinstance(item, dict) and item.get("paragraphIndex") is not None
        }
        candidates = []
        for paragraph in body_paragraphs(request):
            fact = role_facts.get(paragraph.index, {"paragraphIndex": paragraph.index, "text": paragraph.text})
            deterministic = classify_role_fact(fact)
            if deterministic.get("status") == "confirmed":
                continue
            block = blocks.get(paragraph.index, {})
            if block and block.get("scope", "in_scope") != "in_scope":
                continue
            block_id = str(block.get("blockId") or "format-paragraph-{0}".format(paragraph.index))
            allowed = []
            for item in deterministic.get("candidates", []):
                if isinstance(item, dict) and item.get("role") in SEMANTIC_ROLE_NAMES:
                    allowed.append({"role": item["role"], "attributes": deepcopy(item.get("attributes", {}))})
            if not allowed:
                allowed = [{"role": role, "attributes": {}} for role in SEMANTIC_ROLE_NAMES]
            candidates.append({
                "blockId": block_id,
                "paragraphIndex": paragraph.index,
                "text": paragraph.text,
                "evidence": deepcopy(deterministic.get("evidence", [])),
                "deterministicStatus": deterministic.get("status", "needs_confirmation"),
                "allowedTargets": allowed,
                "format": deepcopy(block.get("format", {})) if isinstance(block.get("format"), dict) else {
                    "styleName": paragraph.style_name or "",
                    "outlineLevel": paragraph.outline_level or 0,
                },
            })
        return candidates

    @staticmethod
    def _task_auth_configured(task_auth: Optional[Dict]) -> bool:
        if not isinstance(task_auth, dict) or task_auth.get("authSnapshotStatus") == "unavailable":
            return False
        return bool(
            str(task_auth.get("providerBaseUrl", "")).strip()
            and str(task_auth.get("apiKey", "")).strip()
        )

    @staticmethod
    def _direct_capability_unknown(task_auth: Optional[Dict]) -> bool:
        if not isinstance(task_auth, dict) or task_auth.get("accessMethod") != "direct_model":
            return False
        return not str(task_auth.get("modelName", "")).strip() or task_auth.get("maxOutputTokens") is None

    @staticmethod
    def _snapshot_binding(request: WordDocumentRequest) -> Dict[str, str]:
        structure = request.content.document_structure or {}
        return {
            "contentSha256": str(structure.get("contentFingerprint") or structure.get("contentSha256") or ""),
            "structureSha256": str(structure.get("structureFingerprint") or structure.get("structureSha256") or ""),
            "formatSha256": str(structure.get("formatFingerprint") or structure.get("formatSha256") or ""),
        }

    def _build_role_prompt(
        self,
        request: WordDocumentRequest,
        template: Dict,
        candidates: Optional[List[Dict]] = None,
    ) -> str:
        candidates = candidates if candidates is not None else self._role_candidates(request)
        payload = {
            "templateId": template.get("id"),
            "scope": request.selection_mode,
            "operation": "classify_role",
            "snapshotBinding": self._snapshot_binding(request),
            "candidates": candidates,
        }
        return "\n".join(
            [
                "你是 Word 技术文件段落角色识别助手。",
                "只处理 candidates 中列出的模糊候选；不得返回未列出的 blockId，不得处理确定性规则已确认的对象。",
                "role 和属性只能从每个候选的 allowedTargets 中选择；confidence 必须是 0 到 1 的数字。",
                "遵守 format_semantics.v1；本次输入估算不得超过 8192 Token，输出不得超过运行时提供的任务预算。",
                "只返回 JSON，不要 Markdown 代码围栏、推理过程、思考标签或格式合规结论。",
                '{"schemaVersion":"format_semantics.v1","operation":"classify_role","snapshotBinding":{"contentSha256":"...","structureSha256":"...","formatSha256":"..."},"items":[{"blockId":"...","role":"heading","level":1,"confidence":0.95}]}',
                "",
                "输入：",
                json.dumps(payload, ensure_ascii=False),
            ]
        )

    def _normalize_model_role(self, role: str, item: Dict) -> Optional[Dict]:
        attributes: Dict[str, Any] = {}
        if role.startswith("heading") and role[7:].isdigit():
            attributes["level"] = int(role[7:])
            role = "heading"
        elif role.startswith("list") and "_" in role:
            prefix, kind = role.split("_", 1)
            if prefix[4:].isdigit() and kind in {"numbered", "plain"}:
                attributes.update({"level": int(prefix[4:]), "ordered": kind == "numbered"})
                role = "list_item"
        elif role.startswith("appendix_heading") and role[16:].isdigit():
            attributes["level"] = int(role[16:])
            role = "appendix_heading"
        elif role == "numbered_note":
            role = "note"
            attributes["numbered"] = True
        elif role == "note":
            if not isinstance(item.get("numbered"), bool):
                return None
            attributes["numbered"] = item["numbered"]
        if role == "heading":
            if "level" not in item and "headingLevel" not in item and "level" not in attributes:
                return None
            try:
                level = int(item.get("level", attributes.get("level", item.get("headingLevel", 1))))
            except (TypeError, ValueError):
                return None
            if not 1 <= level <= 4:
                return None
            attributes["level"] = level
        if role in {"list_item", "appendix_heading"}:
            if "level" not in item and "level" not in attributes:
                return None
            try:
                level = int(item.get("level", attributes.get("level", 1)))
            except (TypeError, ValueError):
                return None
            limit = 2 if role == "list_item" else 3
            if not 1 <= level <= limit:
                return None
            attributes["level"] = level
        if role == "list_item" and "ordered" not in attributes:
            if not isinstance(item.get("ordered"), bool):
                return None
            attributes["ordered"] = item["ordered"]
        return {"role": role, "attributes": attributes}

    def _extract_json(self, answer: str):
        raw = (answer or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
        if fence:
            try:
                return json.loads(fence.group(1).strip())
            except json.JSONDecodeError:
                pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end >= start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end >= start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None

    def _extract_role_items(self, answer: str):
        payload = self._extract_json(answer)
        return self._role_items_from_payload(payload)

    def _extract_semantic_payload(self, answer: str) -> Dict:
        payload = self._extract_json(answer)
        if not isinstance(payload, dict):
            return {"items": None, "snapshotBinding": None}
        if isinstance(payload.get("candidates"), list):
            return {
                "items": payload.get("candidates"),
                "snapshotBinding": payload.get("snapshotBinding") or payload.get("snapshot"),
            }
        return {"items": self._role_items_from_payload(payload), "snapshotBinding": None}

    def _role_items_from_payload(self, payload: Any, depth: int = 0):
        if depth > 4 or payload is None:
            return None
        if isinstance(payload, list):
            return payload
        if isinstance(payload, str):
            nested = self._extract_json(payload)
            if nested is None:
                return None
            return self._role_items_from_payload(nested, depth + 1)
        if not isinstance(payload, dict):
            return None

        paragraphs = payload.get("paragraphs")
        if isinstance(paragraphs, list):
            return paragraphs
        if isinstance(paragraphs, str):
            return self._role_items_from_payload(paragraphs, depth + 1)

        for key in ("result", "data", "outputs", "output", "answer", "text", "message", "content"):
            if key not in payload:
                continue
            items = self._role_items_from_payload(payload[key], depth + 1)
            if items is not None:
                return items
        return None

    def _empty_ai_diagnostics(self) -> Dict:
        return {
            "aiAttempted": False,
            "aiParseErrorCount": 0,
            "aiRequestErrorCount": 0,
            "aiInvalidRoleCount": 0,
            "aiOutOfBatchCount": 0,
            "aiInvalidBindingCount": 0,
            "aiLowConfidenceCount": 0,
            "aiConflictCount": 0,
            "aiCandidateCount": 0,
            "aiCallCount": 0,
            "aiRetryCount": 0,
            "aiCorrectionCount": 0,
            "aiSkippedCount": 0,
            "aiSkippedReasons": [],
            "aiFallbackReason": "",
            "semanticStatus": "not_needed",
            "semanticComplete": True,
        }

    def _infer_role(self, paragraph: Paragraph, template: Dict) -> str:
        result = classify_role_fact(
            {
                "paragraphIndex": paragraph.index,
                "text": paragraph.text,
                "styleName": paragraph.style_name or "",
                "outlineLevel": paragraph.outline_level or 0,
            }
        )
        return result.get("role", "unknown") if result.get("status") == "confirmed" else "unknown"

    def _rule_for_role(self, role: str, template: Dict) -> Dict:
        mapping = resolve_role_rule(role, {"template": template})
        if mapping.get("status") != "mapped":
            return {}
        return (template.get("roleRules") or {}).get(mapping.get("ruleKey"), {})

    def _normalize_font_size(self, value) -> Optional[float]:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if numeric > 0 else None

    def _normalize_alignment(self, value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        lowered = text.lower()
        mapping = {
            "0": "left",
            "1": "center",
            "2": "right",
            "3": "justify",
            "4": "distribute",
            "left": "left",
            "center": "center",
            "centered": "center",
            "centre": "center",
            "right": "right",
            "justify": "justify",
            "justified": "justify",
            "distributed": "distribute",
            "distribute": "distribute",
            "左对齐": "left",
            "居中": "center",
            "居中对齐": "center",
            "右对齐": "right",
            "两端对齐": "justify",
            "分散对齐": "distribute",
            "wdalignparagraphleft": "left",
            "wdalignparagraphcenter": "center",
            "wdalignparagraphright": "right",
            "wdalignparagraphjustify": "justify",
            "wdalignparagraphdistribute": "distribute",
        }
        return mapping.get(lowered, mapping.get(text, lowered))

    def _font_matches(self, font_name: str, rule: Dict) -> bool:
        expected = [rule.get("fontName", "")]
        expected.extend(rule.get("fontAliases", []))
        normalized = {item.lower() for item in expected if item}
        return font_name.lower() in normalized

    def _normalize_line_spacing(self, value) -> Optional[float]:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric > 10:
            return numeric / 240.0
        return numeric

    def _roughly_equal(self, current, expected) -> bool:
        try:
            return abs(float(current) - float(expected)) < 2.0
        except (TypeError, ValueError):
            return False
