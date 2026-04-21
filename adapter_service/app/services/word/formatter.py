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
        body = template.get("body", {})
        body_font = body.get("fontName")
        body_size = body.get("fontSize")

        for paragraph in body_paragraphs(request):
            current_style = paragraph.style_name or "Body"
            target_style = current_style
            reason_parts: List[str] = []

            if (paragraph.outline_level or 0) > 0:
                level_key = "level{0}".format(paragraph.outline_level)
                target_style = "Heading {0}".format(paragraph.outline_level)
                heading = template.get("headings", {}).get(level_key, {})
                if paragraph.font_name != heading.get("fontName"):
                    reason_parts.append("align heading font with template")
                if paragraph.font_size != heading.get("fontSize"):
                    reason_parts.append("align heading size with template")
            else:
                target_style = "Body"
                if paragraph.font_name != body_font:
                    reason_parts.append("align body font with template")
                if paragraph.font_size != body_size:
                    reason_parts.append("align body size with template")
                if not paragraph.text.startswith("  "):
                    reason_parts.append("apply body indent and spacing defaults")

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
