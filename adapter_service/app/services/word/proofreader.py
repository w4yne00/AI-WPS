import re
from collections import Counter
from typing import Dict, List, Optional

from app.core.models import Issue, WordDocumentRequest
from app.services.document_normalizer import (
    body_paragraphs,
    headings,
    paragraph_font_sizes,
    paragraph_fonts,
)
from app.services.provider_client import ProviderClient
from app.services.template_loader import TemplateLoader

SPACE_BEFORE_CHINESE_PUNCTUATION = re.compile(r"\s+[，。！？；：]")


class WordProofreader:
    def __init__(
        self,
        template_loader: Optional[TemplateLoader] = None,
        provider_client: Optional[ProviderClient] = None,
    ) -> None:
        self.template_loader = template_loader or TemplateLoader()
        self.provider_client = provider_client or ProviderClient()

    def proofread(self, request: WordDocumentRequest, trace_id: str = "word-proofread") -> List[Issue]:
        issues: List[Issue] = []
        template = self._resolve_template(request.options.template_id or "general-office")
        issues.extend(self._check_template_styles(request, template))
        issues.extend(self._check_heading_hierarchy(request))
        issues.extend(self._check_font_consistency(request))
        issues.extend(self._check_font_size_consistency(request))
        issues.extend(self._check_double_spaces(request))
        issues.extend(self._check_punctuation_spacing(request))
        issues.extend(self._check_ai_typos(request, template, trace_id))
        return issues

    def _resolve_template(self, template_id: str) -> Dict:
        try:
            return self.template_loader.get_template(template_id)
        except FileNotFoundError:
            return self.template_loader.get_template("general-office")

    def _check_heading_hierarchy(self, request: WordDocumentRequest) -> List[Issue]:
        detected: List[Issue] = []
        current_level = 0
        for heading in headings(request):
            if heading.level > current_level + 1:
                detected.append(
                    Issue(
                        ruleId="heading_hierarchy",
                        severity="warning",
                        message=(
                            "Heading levels skip an intermediate level; "
                            "normalize the outline structure."
                        ),
                        suggestion="Insert the missing heading level or lower this heading level.",
                        autoFixable=False,
                    )
                )
            current_level = heading.level
        return detected

    def _check_font_consistency(self, request: WordDocumentRequest) -> List[Issue]:
        paragraphs = body_paragraphs(request)
        fonts = paragraph_fonts(paragraphs)
        if not fonts:
            return []

        dominant_font, _ = Counter(fonts).most_common(1)[0]
        detected: List[Issue] = []
        for paragraph in paragraphs:
            if paragraph.font_name and paragraph.font_name != dominant_font:
                detected.append(
                    Issue(
                        ruleId="font_consistency",
                        severity="warning",
                        message="Body text uses a mixed font family.",
                        paragraphIndex=paragraph.index,
                        suggestion="Align the paragraph font with the dominant body font.",
                        autoFixable=True,
                    )
                )
        return detected

    def _check_font_size_consistency(self, request: WordDocumentRequest) -> List[Issue]:
        paragraphs = body_paragraphs(request)
        sizes = paragraph_font_sizes(paragraphs)
        if not sizes:
            return []

        dominant_size, _ = Counter(sizes).most_common(1)[0]
        detected: List[Issue] = []
        for paragraph in paragraphs:
            if paragraph.font_size is not None and paragraph.font_size != dominant_size:
                detected.append(
                    Issue(
                        ruleId="font_size_consistency",
                        severity="warning",
                        message="Body text uses a mixed font size.",
                        paragraphIndex=paragraph.index,
                        suggestion="Align the paragraph size with the dominant body size.",
                        autoFixable=True,
                    )
                )
        return detected

    def _check_template_styles(self, request: WordDocumentRequest, template: Dict) -> List[Issue]:
        detected: List[Issue] = []
        for paragraph in body_paragraphs(request):
            rule = self._style_rule(paragraph, template)
            if not rule:
                continue

            expected_font = rule.get("fontName")
            if expected_font and paragraph.font_name and not self._font_matches(paragraph.font_name, rule):
                detected.append(
                    Issue(
                        ruleId="template_font",
                        severity="warning",
                        message="Paragraph font does not match the selected Word template.",
                        paragraphIndex=paragraph.index,
                        suggestion="Use {0} for this paragraph style.".format(expected_font),
                        autoFixable=True,
                    )
                )

            expected_size = rule.get("fontSize")
            if expected_size is not None and paragraph.font_size is not None:
                if abs(float(paragraph.font_size) - float(expected_size)) > 0.01:
                    detected.append(
                        Issue(
                            ruleId="template_font_size",
                            severity="warning",
                            message="Paragraph font size does not match the selected Word template.",
                            paragraphIndex=paragraph.index,
                            suggestion="Use {0} pt for this paragraph style.".format(expected_size),
                            autoFixable=True,
                        )
                    )

            expected_line_spacing = rule.get("lineSpacing")
            if expected_line_spacing is not None and paragraph.line_spacing is not None:
                normalized = self._normalize_line_spacing(paragraph.line_spacing)
                if normalized is not None and abs(normalized - float(expected_line_spacing)) > 0.05:
                    detected.append(
                        Issue(
                            ruleId="template_line_spacing",
                            severity="warning",
                            message="Paragraph line spacing does not match the selected Word template.",
                            paragraphIndex=paragraph.index,
                            suggestion="Use {0} line spacing.".format(expected_line_spacing),
                            autoFixable=True,
                        )
                    )
        return detected

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

    def _check_ai_typos(
        self,
        request: WordDocumentRequest,
        template: Dict,
        trace_id: str,
    ) -> List[Issue]:
        ai_config = template.get("aiProofread", {})
        if not ai_config.get("enabled"):
            return []
        text = request.content.plain_text.strip()
        if not text:
            text = "\n".join(paragraph.text for paragraph in body_paragraphs(request)).strip()
        if not text:
            return []

        try:
            typo_items = self.provider_client.proofread_typos(text, trace_id)
        except Exception:
            return []

        detected: List[Issue] = []
        for item in typo_items:
            original = item.get("original", "")
            suggestion = item.get("suggestion", "")
            reason = item.get("reason", "")
            detected.append(
                Issue(
                    ruleId=ai_config.get("ruleId", "ai_typo"),
                    severity="warning",
                    message="AI detected a possible typo or wording issue: {0}".format(original),
                    suggestion="{0}{1}".format(
                        suggestion,
                        "（{0}）".format(reason) if reason else "",
                    ),
                    autoFixable=False,
                )
            )
        return detected

    def _check_double_spaces(self, request: WordDocumentRequest) -> List[Issue]:
        detected: List[Issue] = []
        for paragraph in body_paragraphs(request):
            if "  " in paragraph.text:
                detected.append(
                    Issue(
                        ruleId="double_space",
                        severity="info",
                        message="Repeated whitespace found in the paragraph.",
                        paragraphIndex=paragraph.index,
                        suggestion="Collapse consecutive spaces to a single space.",
                        autoFixable=True,
                    )
                )
        return detected

    def _check_punctuation_spacing(self, request: WordDocumentRequest) -> List[Issue]:
        detected: List[Issue] = []
        for paragraph in body_paragraphs(request):
            if SPACE_BEFORE_CHINESE_PUNCTUATION.search(paragraph.text):
                detected.append(
                    Issue(
                        ruleId="punctuation_spacing",
                        severity="info",
                        message="Space detected before Chinese punctuation.",
                        paragraphIndex=paragraph.index,
                        suggestion="Remove the space before punctuation.",
                        autoFixable=True,
                    )
                )
        return detected
