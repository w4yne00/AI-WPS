import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import FormatReviewIssue, Paragraph, WordDocumentRequest
from app.services.document_normalizer import body_paragraphs
from app.services.provider_client import ProviderClient, extract_answer
from app.services.word.authorized_format_algorithm import (
    audit_format_facts,
    classify_role_fact,
    resolve_role_rule,
)
from app.services.word.format_rule_pack import FormatRulePackError, FormatRulePackLoader
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
DEFAULT_TEMPLATE_ID = "technical-file-format-requirements"


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

    def review(self, request: WordDocumentRequest, trace_id: str = "") -> Dict:
        requested_template = request.options.template_id or DEFAULT_TEMPLATE_ID
        template = self._resolve_template(requested_template)
        paragraphs = body_paragraphs(request)
        ai_diagnostics = self._empty_ai_diagnostics()
        if trace_id:
            ai_roles, ai_batch_count, ai_diagnostics = self._classify_roles_with_ai(request, template, trace_id)
        else:
            ai_roles, ai_batch_count = {}, 0
        provider = "local"
        if ai_roles:
            if hasattr(self.provider_client, "build_provider_source"):
                provider = self.provider_client.build_provider_source("word.format_review")
            else:
                provider = "工作流平台"
        issues = self._build_issues(request, template, ai_roles)
        issues = self._annotate_issues(issues, template)
        summary = {
            "scope": request.selection_mode,
            "templateId": template["id"],
            "rulePackVersion": template.get("_rulePackVersion", "legacy-template"),
            "rulePackSha256": template.get("_rulePackSha256", ""),
            "authorizedAlgorithmVersion": template.get("_algorithmAdapterVersion", ""),
            "provider": provider,
            "paragraphCount": len(paragraphs),
            "issueCount": len(issues),
            "aiClassifiedParagraphCount": len(ai_roles),
            "localFallbackParagraphCount": max(len(paragraphs) - len(ai_roles), 0),
            "aiBatchCount": ai_batch_count,
            **ai_diagnostics,
        }
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
    ) -> List[FormatReviewIssue]:
        issues: List[FormatReviewIssue] = []
        page_issue = self._build_page_issue(request, template)
        if page_issue:
            issues.append(page_issue)

        issues.extend(self._authorized_structure_issues(request, template))

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
                    role_result = {
                        **deterministic_role,
                        "evidence": deterministic_role.get("evidence", []) + ["model_role_unverified"],
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
                cells = []
                for row_index, row in enumerate(block.get("rows", [])):
                    if not isinstance(row, dict):
                        continue
                    for column_index, cell in enumerate(row.get("cells", [])):
                        if isinstance(cell, dict):
                            cells.append({
                                "text": cell.get("text", ""),
                                "row": cell.get("rowIndex", row.get("rowIndex", row_index)),
                                "column": cell.get("columnIndex", column_index),
                                "isHeader": cell.get("isHeader", False),
                            })
                facts["tables"].append({
                    "tableId": block.get("tableId") or block.get("blockId"),
                    "cells": cells,
                })
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
        self, request: WordDocumentRequest, template: Dict
    ) -> List[FormatReviewIssue]:
        facts = self._format_structure_facts(request)
        facts.setdefault("appendixFacts", [])
        facts.setdefault("noteFacts", [])
        pack = {"template": template, "rules": template.get("_rulePackRules", [])}
        audit = audit_format_facts(facts, pack)
        issues: List[FormatReviewIssue] = []
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
    ) -> Tuple[Dict[int, Dict], int, Dict]:
        task_type = "word.format_review"
        diagnostics = self._empty_ai_diagnostics()
        paragraphs = body_paragraphs(request)
        if not paragraphs:
            diagnostics["aiFallbackReason"] = "no_paragraphs"
            if hasattr(self.provider_client, "record_skipped_debug"):
                self.provider_client.record_skipped_debug(
                    task_type,
                    trace_id,
                    "格式审查未读取到正文段落，未调用模型后台。",
                    "no_paragraphs",
                    provider="local",
                )
            return {}, 0, diagnostics

        if not self.provider_client.is_task_configured(task_type):
            diagnostics["aiFallbackReason"] = "provider_not_configured"
            if hasattr(self.provider_client, "record_unconfigured_debug"):
                self.provider_client.record_unconfigured_debug(
                    task_type,
                    trace_id,
                    self._build_role_prompt(request, template, paragraphs[:AI_ROLE_BATCH_SIZE]),
                )
            return {}, 0, diagnostics

        roles: Dict[int, Dict] = {}
        batch_count = 0
        valid_roles = {
            "document_title", "heading", "body", "list_item", "note", "caption",
            "toc_title", "toc_entry", "appendix_title", "appendix_heading", "formula", "table_body", "unknown",
        }
        ai_paragraphs = paragraphs[:AI_ROLE_MAX_PARAGRAPHS]
        if len(paragraphs) > len(ai_paragraphs):
            diagnostics["aiFallbackReason"] = "ai_budget_limited"
        for start in range(0, len(ai_paragraphs), AI_ROLE_BATCH_SIZE):
            batch = ai_paragraphs[start:start + AI_ROLE_BATCH_SIZE]
            batch_indexes = {paragraph.index for paragraph in batch}
            prompt = self._build_role_prompt(request, template, batch)
            if hasattr(self.provider_client, "build_task_input_data"):
                input_data = self.provider_client.build_task_input_data(
                    task_type,
                    trace_id,
                    {"templateId": template.get("id"), "scope": request.selection_mode},
                )
            else:
                input_data = {
                    "scene": "word",
                    "task_id": task_type,
                    "taskType": task_type,
                    "trace_id": trace_id,
                    "templateId": template.get("id"),
                    "scope": request.selection_mode,
                }
            batch_count += 1
            diagnostics["aiAttempted"] = True
            try:
                if hasattr(self.provider_client, "format_review_roles"):
                    body = self.provider_client.format_review_roles(trace_id, input_data, prompt)
                else:
                    body = self.provider_client.post_task(task_type, trace_id, input_data, prompt)
                answer = extract_answer(body)
            except AdapterError:
                diagnostics["aiRequestErrorCount"] += 1
                continue
            except (TypeError, ValueError, json.JSONDecodeError):
                diagnostics["aiRequestErrorCount"] += 1
                continue
            items = self._extract_role_items(answer)
            if not isinstance(items, list):
                diagnostics["aiParseErrorCount"] += 1
                continue
            for item in items:
                if not isinstance(item, dict):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                try:
                    index = int(item.get("paragraphIndex", item.get("paragraph_index")))
                except (TypeError, ValueError):
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                if index not in batch_indexes:
                    diagnostics["aiOutOfBatchCount"] += 1
                    continue
                role = str(item.get("role", "")).strip()
                normalized = self._normalize_model_role(role, item)
                if normalized is None or normalized["role"] not in valid_roles or normalized["role"] == "unknown":
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                confidence = item.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.75
                confidence = max(0.0, min(1.0, confidence))
                roles[index] = {
                    "role": normalized["role"],
                    "attributes": normalized["attributes"],
                    "status": "confirmed" if confidence >= 0.85 else "needs_confirmation",
                    "confidence": confidence,
                    "evidence": ["model_candidate"],
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

    def _build_role_prompt(
        self,
        request: WordDocumentRequest,
        template: Dict,
        paragraphs: Optional[List[Paragraph]] = None,
    ) -> str:
        paragraphs = paragraphs if paragraphs is not None else body_paragraphs(request)
        payload = {
            "templateId": template.get("id"),
            "scope": request.selection_mode,
            "roles": [
                "document_title", "heading", "body", "list_item", "note", "caption",
                "toc_title", "toc_entry", "appendix_title", "appendix_heading", "formula", "table_body",
            ],
            "roleAttributes": {
                "heading": {"level": [1, 2, 3, 4]},
                "list_item": {"level": [1, 2], "ordered": [True, False]},
                "note": {"numbered": [True, False]},
                "appendix_heading": {"level": [1, 2, 3]},
            },
            "paragraphs": [
                {
                    "paragraphIndex": paragraph.index,
                    "text": paragraph.text[:300],
                    "styleName": paragraph.style_name or "",
                    "outlineLevel": paragraph.outline_level or 0,
                }
                for paragraph in paragraphs
            ],
        }
        return "\n".join(
            [
                "你是 Word 技术文件段落角色识别助手。",
                "请只判断每个段落在模板中的角色，不要改写原文，不要判断格式是否合规。",
                "只返回一个 Markdown json 代码块，格式为：",
                '{"paragraphs":[{"paragraphIndex":1,"role":"heading","level":1,"confidence":0.95}]}',
                "role 只能从给定 roles 中选择；level、ordered、numbered 只能使用 roleAttributes 中的值。",
                "模型输出只是候选证据；没有结构事实或第二类独立强证据时，不得视为已确认。",
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
            "aiFallbackReason": "",
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
