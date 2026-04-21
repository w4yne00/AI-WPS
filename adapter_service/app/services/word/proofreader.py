import re
from collections import Counter
from typing import List

from app.core.models import Issue, WordDocumentRequest
from app.services.document_normalizer import (
    body_paragraphs,
    headings,
    paragraph_font_sizes,
    paragraph_fonts,
)

SPACE_BEFORE_CHINESE_PUNCTUATION = re.compile(r"\s+[，。！？；：]")


class WordProofreader:
    def proofread(self, request: WordDocumentRequest) -> List[Issue]:
        issues: List[Issue] = []
        issues.extend(self._check_heading_hierarchy(request))
        issues.extend(self._check_font_consistency(request))
        issues.extend(self._check_font_size_consistency(request))
        issues.extend(self._check_double_spaces(request))
        issues.extend(self._check_punctuation_spacing(request))
        return issues

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
