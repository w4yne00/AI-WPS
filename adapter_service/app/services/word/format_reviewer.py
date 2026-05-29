import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import FormatReviewIssue, Paragraph, WordDocumentRequest
from app.services.document_normalizer import body_paragraphs
from app.services.provider_client import ProviderClient, extract_answer
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

AI_ROLE_BATCH_SIZE = 120
DEFAULT_TEMPLATE_ID = "technical-file-format-requirements"


class WordFormatReviewer:
    def __init__(
        self,
        template_loader: Optional[TemplateLoader] = None,
        provider_client: Optional[ProviderClient] = None,
    ) -> None:
        self.template_loader = template_loader or TemplateLoader()
        self.provider_client = provider_client or ProviderClient()

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
        if ai_diagnostics.get("aiAttempted"):
            provider = "enterprise-dify-chat/{0}".format(self.provider_client.get_auth_source_for_task("word.format_review"))
        issues = self._build_issues(request, template, ai_roles)
        return {
            "issues": [self._dump_issue(issue) for issue in issues],
            "summary": {
                "scope": request.selection_mode,
                "templateId": template["id"],
                "provider": provider,
                "paragraphCount": len(paragraphs),
                "issueCount": len(issues),
                "aiClassifiedParagraphCount": len(ai_roles),
                "localFallbackParagraphCount": max(len(paragraphs) - len(ai_roles), 0),
                "aiBatchCount": ai_batch_count,
                **ai_diagnostics,
            },
        }

    def _dump_issue(self, issue: FormatReviewIssue) -> Dict:
        if hasattr(issue, "model_dump"):
            return issue.model_dump(by_alias=True)
        return issue.dict(by_alias=True)

    def _resolve_template(self, template_id: str) -> Dict:
        try:
            return self.template_loader.get_template(template_id)
        except FileNotFoundError:
            return self.template_loader.get_template(DEFAULT_TEMPLATE_ID)

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

        ai_roles = ai_roles or {}
        for paragraph in body_paragraphs(request):
            role_info = ai_roles.get(paragraph.index, {})
            role = role_info.get("role") or self._infer_role(paragraph, template)
            rule = self._rule_for_role(role, template)
            issues.extend(self._paragraph_issues(paragraph, rule, role))
        return issues

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
        if rule.get("fontSize") is not None and paragraph.font_size is not None:
            if abs(float(paragraph.font_size) - float(rule["fontSize"])) > 0.01:
                issues.append(
                    self._issue(
                        paragraph,
                        role,
                        "font_size",
                        "字号不符合模板要求。",
                        "{0}pt".format(paragraph.font_size),
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
        if rule.get("alignment") and paragraph.alignment and str(paragraph.alignment).lower() != str(rule["alignment"]).lower():
            issues.append(
                self._issue(
                    paragraph,
                    role,
                    "alignment",
                    "对齐方式不符合模板要求。",
                    str(paragraph.alignment),
                    str(rule["alignment"]),
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
                    "格式审查未读取到正文段落，未调用 Dify。",
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
        valid_roles = set((template.get("roleRules") or {}).keys()) | {"body"}
        for start in range(0, len(paragraphs), AI_ROLE_BATCH_SIZE):
            batch = paragraphs[start:start + AI_ROLE_BATCH_SIZE]
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
                if role not in valid_roles:
                    diagnostics["aiInvalidRoleCount"] += 1
                    continue
                confidence = item.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.75
                roles[index] = {"role": role, "confidence": max(0.0, min(1.0, confidence))}
        if diagnostics["aiAttempted"] and not roles:
            if diagnostics["aiParseErrorCount"]:
                diagnostics["aiFallbackReason"] = "dify_response_not_role_json"
            elif diagnostics["aiRequestErrorCount"]:
                diagnostics["aiFallbackReason"] = "provider_request_failed"
            elif diagnostics["aiInvalidRoleCount"] or diagnostics["aiOutOfBatchCount"]:
                diagnostics["aiFallbackReason"] = "dify_response_no_valid_roles"
            else:
                diagnostics["aiFallbackReason"] = "dify_returned_no_roles"
        return roles, batch_count, diagnostics

    def _build_role_prompt(
        self,
        request: WordDocumentRequest,
        template: Dict,
        paragraphs: Optional[List[Paragraph]] = None,
    ) -> str:
        paragraphs = paragraphs if paragraphs is not None else body_paragraphs(request)
        role_names = sorted((template.get("roleRules") or {}).keys())
        payload = {
            "templateId": template.get("id"),
            "scope": request.selection_mode,
            "roles": role_names + ["body"],
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
                '{"paragraphs":[{"paragraphIndex":1,"role":"heading1","confidence":0.95}]}',
                "role 只能从给定 roles 中选择。",
                "",
                "输入：",
                json.dumps(payload, ensure_ascii=False),
            ]
        )

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
        style_name = paragraph.style_name or ""
        style_rule = (template.get("styles") or {}).get(style_name)
        if isinstance(style_rule, dict) and style_rule.get("roleRef"):
            return style_rule["roleRef"]

        text = (paragraph.text or "").strip()
        if not text:
            return "body"
        if re.match(r"^附录[A-ZＡ-Ｚ]?[（(]", text):
            return "appendix_title"
        if re.match(r"^[A-Z]\.\d+\.\d+\.\d+", text):
            return "appendix_heading3"
        if re.match(r"^[A-Z]\.\d+\.\d+", text):
            return "appendix_heading2"
        if re.match(r"^[A-Z]\.\d+", text):
            return "appendix_heading1"
        if re.match(r"^(图|表)\s*\d+", text):
            return "caption"
        if paragraph.index <= 3 and len(text) <= 40 and not re.match(r"^(\d+(\.\d+)*|[A-Z]\.\d+)", text):
            return "document_title"
        if re.match(r"^注\s*\d+[:：.．]", text):
            return "numbered_note"
        if text.startswith("注") and len(text) < 180:
            return "note"
        if re.match(r"^[（(]?[a-zA-Z]\)|^[a-zA-Z][）)]", text):
            return "list1_numbered"
        if re.match(r"^[（(]?\d+[）)]", text):
            return "list2_numbered"

        outline_level = paragraph.outline_level or 0
        if 1 <= outline_level <= 4:
            return "heading{0}".format(outline_level)
        heading_match = re.match(r"^(\d+(?:\.\d+){0,3})(?:\s+|　+)", text)
        if heading_match:
            level = min(4, heading_match.group(1).count(".") + 1)
            return "heading{0}".format(level)
        return "body"

    def _rule_for_role(self, role: str, template: Dict) -> Dict:
        role_rules = template.get("roleRules") or {}
        if role in role_rules:
            return role_rules[role]
        return template.get("body", {})

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
