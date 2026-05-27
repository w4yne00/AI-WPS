import json
import re
from typing import Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import FormatChange, Paragraph, WordDocumentRequest
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


class WordFormatter:
    def __init__(
        self,
        template_loader: Optional[TemplateLoader] = None,
        provider_client: Optional[ProviderClient] = None,
    ) -> None:
        self.template_loader = template_loader or TemplateLoader()
        self.provider_client = provider_client or ProviderClient()

    def preview(self, request: WordDocumentRequest, trace_id: str = "") -> Dict:
        requested_template = request.options.template_id or "general-office"
        template = self._resolve_template(requested_template)
        paragraphs = body_paragraphs(request)
        ai_roles, ai_batch_count = self._classify_roles_with_ai(request, template, trace_id) if trace_id else ({}, 0)
        provider = "local"
        if ai_roles:
            provider = "enterprise-dify-chat/{0}".format(self.provider_client.get_auth_source_for_task("word.smart_format"))
        changes = self._build_change_plan(request, template, ai_roles)
        page_change_count = len([change for change in changes if change.paragraph_index == 0])
        return {
            "changes": [self._dump_change(change) for change in changes],
            "summary": {
                "changeCount": len(changes),
                "templateId": template["id"],
                "provider": provider,
                "pageSetupChangeCount": page_change_count,
                "paragraphCount": len(paragraphs),
                "aiClassifiedParagraphCount": len(ai_roles),
                "localFallbackParagraphCount": max(len(paragraphs) - len(ai_roles), 0),
                "aiBatchCount": ai_batch_count,
            },
        }

    def _dump_change(self, change: FormatChange) -> Dict:
        if hasattr(change, "model_dump"):
            return change.model_dump(by_alias=True)
        return change.dict(by_alias=True)

    def _resolve_template(self, template_id: str) -> Dict:
        try:
            return self.template_loader.get_template(template_id)
        except FileNotFoundError:
            return self.template_loader.get_template("general-office")

    def _build_change_plan(
        self,
        request: WordDocumentRequest,
        template: Dict,
        ai_roles: Optional[Dict[int, Dict]] = None,
    ) -> List[FormatChange]:
        changes: List[FormatChange] = []
        page_change = self._build_page_change(request, template)
        if page_change:
            changes.append(page_change)

        ai_roles = ai_roles or {}
        for paragraph in body_paragraphs(request):
            role_info = ai_roles.get(paragraph.index, {})
            role = role_info.get("role") or self._infer_role(paragraph, template)
            rule = self._rule_for_role(role, template)
            current_style = paragraph.style_name or "Normal"
            target_style = rule.get("styleName", current_style)
            target_properties = self._target_properties(rule)
            reason_parts = self._paragraph_reason_parts(paragraph, rule, role, current_style, target_style)

            if reason_parts or current_style != target_style:
                changes.append(
                    FormatChange(
                        paragraphIndex=paragraph.index,
                        currentStyle=current_style,
                        targetStyle=target_style,
                        reason="; ".join(reason_parts) or "套用{0}模板样式".format(ROLE_TEXT.get(role, role)),
                        targetProperties=target_properties,
                        role=role,
                        confidence=role_info.get("confidence", 0.92 if not role_info else None),
                    )
                )

        return changes

    def _build_page_change(self, request: WordDocumentRequest, template: Dict) -> Optional[FormatChange]:
        page_rule = template.get("page", {})
        if not page_rule:
            return None
        current = request.content.document_structure.get("page_setup", {}) or {}
        target = {
            "type": "pageSetup",
            "paperSize": page_rule.get("paperSize", "A4"),
            "widthTwips": page_rule.get("widthTwips"),
            "heightTwips": page_rule.get("heightTwips"),
            "marginTopTwips": page_rule.get("marginTopTwips"),
            "marginBottomTwips": page_rule.get("marginBottomTwips"),
            "marginLeftTwips": page_rule.get("marginLeftTwips"),
            "marginRightTwips": page_rule.get("marginRightTwips"),
        }
        expected = {
            "marginTop": page_rule.get("marginTopTwips"),
            "marginBottom": page_rule.get("marginBottomTwips"),
            "marginLeft": page_rule.get("marginLeftTwips"),
            "marginRight": page_rule.get("marginRightTwips"),
        }
        if current and all(self._roughly_equal(current.get(key), value) for key, value in expected.items() if value is not None):
            return None
        return FormatChange(
            paragraphIndex=0,
            currentStyle="PageSetup",
            targetStyle="PageSetup",
            reason="按模板设置 A4 页面和页边距",
            targetProperties={key: value for key, value in target.items() if value is not None},
            role="page_setup",
            confidence=1.0,
        )

    def _classify_roles_with_ai(
        self,
        request: WordDocumentRequest,
        template: Dict,
        trace_id: str,
    ) -> Tuple[Dict[int, Dict], int]:
        task_type = "word.smart_format"
        if not self.provider_client.is_task_configured(task_type):
            return {}, 0

        roles: Dict[int, Dict] = {}
        batch_count = 0
        valid_roles = set((template.get("roleRules") or {}).keys()) | {"body"}
        paragraphs = body_paragraphs(request)
        for start in range(0, len(paragraphs), AI_ROLE_BATCH_SIZE):
            batch = paragraphs[start:start + AI_ROLE_BATCH_SIZE]
            batch_indexes = {paragraph.index for paragraph in batch}
            prompt = self._build_role_prompt(request, template, batch)
            batch_count += 1
            try:
                body = self.provider_client.post_task(task_type, trace_id, {}, prompt)
                answer = extract_answer(body)
            except AdapterError:
                continue
            payload = self._extract_json(answer)
            if not isinstance(payload, dict):
                continue
            items = payload.get("paragraphs", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    index = int(item.get("paragraphIndex", item.get("paragraph_index")))
                except (TypeError, ValueError):
                    continue
                if index not in batch_indexes:
                    continue
                role = str(item.get("role", "")).strip()
                if role not in valid_roles:
                    continue
                confidence = item.get("confidence")
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.75
                roles[index] = {"role": role, "confidence": max(0.0, min(1.0, confidence))}
        return roles, batch_count

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
                "你是 Word 技术文件排版结构识别助手。",
                "请只判断每个段落在模板中的角色，不要改写原文，不要输出排版代码。",
                "只返回 JSON 对象，格式为：",
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
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end >= start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None

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

    def _target_properties(self, rule: Dict) -> Dict:
        fields = [
            "fontName",
            "asciiFontName",
            "fontSize",
            "bold",
            "alignment",
            "lineSpacing",
            "lineSpacingTwips",
            "lineRule",
            "firstLineIndentTwips",
            "leftIndentTwips",
            "rightIndentTwips",
            "hangingIndentTwips",
            "spaceBeforeTwips",
            "spaceAfterTwips",
            "outlineLevel",
        ]
        target = {field: rule[field] for field in fields if field in rule}
        target["styleName"] = rule.get("styleName", "")
        return target

    def _paragraph_reason_parts(self, paragraph: Paragraph, rule: Dict, role: str, current_style: str, target_style: str) -> List[str]:
        reason_parts: List[str] = []
        if current_style != target_style:
            reason_parts.append("识别为{0}，套用模板样式".format(ROLE_TEXT.get(role, role)))
        if rule.get("fontName") and paragraph.font_name and not self._font_matches(paragraph.font_name, rule):
            reason_parts.append("字体调整为{0}".format(rule["fontName"]))
        if rule.get("fontSize") is not None and paragraph.font_size is not None:
            if abs(float(paragraph.font_size) - float(rule["fontSize"])) > 0.01:
                reason_parts.append("字号调整为{0}pt".format(rule["fontSize"]))
        if rule.get("lineSpacing") is not None and paragraph.line_spacing is not None:
            normalized = self._normalize_line_spacing(paragraph.line_spacing)
            if normalized is not None and abs(normalized - float(rule["lineSpacing"])) > 0.05:
                reason_parts.append("行距调整为{0}倍".format(rule["lineSpacing"]))
        if rule.get("alignment") and paragraph.alignment and str(paragraph.alignment).lower() != str(rule["alignment"]).lower():
            reason_parts.append("对齐方式调整为{0}".format(rule["alignment"]))
        if rule.get("firstLineIndentTwips") is not None:
            current_indent = paragraph.first_line_indent
            if current_indent is not None and not self._roughly_equal(current_indent, rule["firstLineIndentTwips"]):
                reason_parts.append("首行缩进按模板调整")
        return reason_parts

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
