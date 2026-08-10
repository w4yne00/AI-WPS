import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.core.errors import AdapterError


MAX_EXTRACTED_DOCUMENT_CHARACTERS = 200000
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{{{0}}}".format(_WORD_NAMESPACE)


def extract_staged_document_text(staged_document) -> str:
    extension = str(getattr(staged_document, "extension", "") or "").lower()
    path = Path(getattr(staged_document, "path"))
    if extension == "md":
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise AdapterError(
                "PPT_DOCUMENT_EXTRACT_FAILED",
                "Markdown 文档读取失败，请确认文件使用 UTF-8 编码。",
                status_code=400,
            ) from exc
    elif extension == "docx":
        text = _extract_docx(path)
    else:
        raise AdapterError(
            "PPT_DOCUMENT_TYPE_UNSUPPORTED",
            "模型直连仅支持 Markdown 和 Word 文档。",
            status_code=400,
        )
    normalized = _normalize_text(text)
    if not normalized:
        raise AdapterError(
            "PPT_DOCUMENT_EMPTY", "文档中未提取到可用于总结的文字。", status_code=400
        )
    if len(normalized) > MAX_EXTRACTED_DOCUMENT_CHARACTERS:
        raise AdapterError(
            "MODEL_INPUT_OVER_BUDGET",
            "文档抽取内容超过单次模型直连的安全处理上限，请缩小文档范围。",
            status_code=413,
        )
    return normalized


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(str(path)) as archive:
            raw = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise AdapterError(
            "PPT_DOCUMENT_EXTRACT_FAILED",
            "Word 文档正文读取失败，请重新选择有效文件。",
            status_code=400,
        ) from exc
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise AdapterError(
            "PPT_DOCUMENT_EXTRACT_FAILED",
            "Word 文档正文结构无效。",
            status_code=400,
        ) from exc
    body = root.find("{0}body".format(_W))
    if body is None:
        return ""
    blocks = []
    for child in body:
        if child.tag == "{0}p".format(_W):
            paragraph = _paragraph_text(child)
            if paragraph:
                blocks.append(paragraph)
        elif child.tag == "{0}tbl".format(_W):
            table = _table_text(child)
            if table:
                blocks.append(table)
    return "\n\n".join(blocks)


def _paragraph_text(paragraph) -> str:
    text = "".join(node.text or "" for node in paragraph.iter("{0}t".format(_W))).strip()
    if not text:
        return ""
    properties = paragraph.find("{0}pPr".format(_W))
    style_value = ""
    is_numbered = False
    if properties is not None:
        style = properties.find("{0}pStyle".format(_W))
        if style is not None:
            style_value = str(style.attrib.get("{0}val".format(_W), ""))
        is_numbered = properties.find("{0}numPr".format(_W)) is not None
    heading_match = re.search(r"(?:Heading|标题)\s*([1-6])", style_value, re.IGNORECASE)
    if heading_match:
        return "{0} {1}".format("#" * int(heading_match.group(1)), text)
    if is_numbered:
        return "- {0}".format(text)
    return text


def _table_text(table) -> str:
    rows = []
    for row in table.findall("{0}tr".format(_W)):
        cells = []
        for cell in row.findall("{0}tc".format(_W)):
            cell_text = " ".join(
                part.strip()
                for part in (
                    "".join(node.text or "" for node in paragraph.iter("{0}t".format(_W)))
                    for paragraph in cell.findall(".//{0}p".format(_W))
                )
                if part.strip()
            )
            cells.append(cell_text)
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _normalize_text(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
