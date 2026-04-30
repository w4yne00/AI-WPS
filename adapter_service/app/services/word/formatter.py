from typing import Dict, List, Optional

from app.core.models import FormatChange, WordDocumentRequest
from app.services.document_normalizer import body_paragraphs
from app.services.template_loader import TemplateLoader


class WordFormatter:
    def __init__(self, template_loader: Optional[TemplateLoader] = None) -> None:
        self.template_loader = template_loader or TemplateLoader()

    def preview(self, request: WordDocumentRequest) -> Dict:
        requested_template = request.options.template_id or "general-office"
        template = self._resolve_template(requested_template)
        changes = self._build_change_plan(request, template)
        return {
            "changes": [change.dict(by_alias=True) for change in changes],
            "summary": {
                "changeCount": len(changes),
                "templateId": template["id"],
            },
        }

    def _resolve_template(self, template_id: str) -> Dict:
        try:
            return self.template_loader.get_template(template_id)
        except FileNotFoundError:
            return self.template_loader.get_template("general-office")

    def _build_change_plan(
        self, request: WordDocumentRequest, template: Dict
    ) -> List[FormatChange]:
        changes: List[FormatChange] = []

        for paragraph in body_paragraphs(request):
            current_style = paragraph.style_name or "Body"
            rule = self._style_rule(paragraph, template)
            target_style = rule.get("styleName", current_style)
            reason_parts: List[str] = []

            if rule.get("fontName") and paragraph.font_name and not self._font_matches(paragraph.font_name, rule):
                reason_parts.append("align font with template")
            if rule.get("fontSize") is not None and paragraph.font_size is not None:
                if abs(float(paragraph.font_size) - float(rule["fontSize"])) > 0.01:
                    reason_parts.append("align font size with template")
            if rule.get("lineSpacing") is not None and paragraph.line_spacing is not None:
                normalized = self._normalize_line_spacing(paragraph.line_spacing)
                if normalized is not None and abs(normalized - float(rule["lineSpacing"])) > 0.05:
                    reason_parts.append("align line spacing with template")
            if (paragraph.outline_level or 0) == 0 and rule.get("firstLineIndentChars") and not paragraph.text.startswith("  "):
                reason_parts.append("apply body first-line indent")

            if reason_parts or current_style != target_style:
                changes.append(
                    FormatChange(
                        paragraphIndex=paragraph.index,
                        currentStyle=current_style,
                        targetStyle=target_style,
                        reason="; ".join(reason_parts) or "normalize paragraph style",
                    )
                )

        return changes

    def _style_rule(self, paragraph, template: Dict) -> Dict:
        style_name = paragraph.style_name or ""
        if style_name in template.get("styles", {}):
            return template["styles"][style_name]
        outline_level = paragraph.outline_level or 0
        if outline_level > 0:
            return template.get("headings", {}).get("level{0}".format(outline_level), {})
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
