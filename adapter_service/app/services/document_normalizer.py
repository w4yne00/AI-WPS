from typing import Iterable, List

from app.core.models import Heading, Paragraph, WordDocumentRequest


def body_paragraphs(request: WordDocumentRequest) -> List[Paragraph]:
    return [paragraph for paragraph in request.content.paragraphs if paragraph.text.strip()]


def headings(request: WordDocumentRequest) -> List[Heading]:
    return list(request.content.headings)


def paragraph_fonts(paragraphs: Iterable[Paragraph]) -> List[str]:
    return [font for font in (paragraph.font_name for paragraph in paragraphs) if font]


def paragraph_font_sizes(paragraphs: Iterable[Paragraph]) -> List[float]:
    return [size for size in (paragraph.font_size for paragraph in paragraphs) if size is not None]
