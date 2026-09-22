import base64
import binascii
import io
import re
import secrets
import zipfile
from typing import Dict, List, Optional
from xml.etree import ElementTree

from app.core.errors import AdapterError
from app.services.ppt.docx_security import (
    DOCX_MAX_PACKAGE_BYTES,
    DocxSecurityError,
    validate_docx_bytes,
)


TASK_TYPE = "word.material_composer"
MATERIAL_IMPORT_MAX_READABLE_CHARACTERS = 100000
CHARACTER_COUNT_METHOD = "unicode_codepoints_of_extracted_readable_text"
_PART = "word/document.xml"
_HEADING_NAME = re.compile(r"^(?:Heading|标题)\s*([1-6])$", re.IGNORECASE)


class WordMaterialImportService:
    def __init__(self) -> None:
        self._materials = {}

    def import_material(self, request: dict) -> dict:
        payload = request or {}
        file_name = str(payload.get("fileName") or payload.get("file_name") or "")
        content = _decode_upload(payload.get("contentBase64") or payload.get("content_base64"))
        _reject_wrong_type(file_name, str(payload.get("mimeType") or payload.get("mime_type") or ""))
        try:
            validated = validate_docx_bytes(content)
        except DocxSecurityError as exc:
            raise _security_error(exc) from exc
        reading = _read_document(validated.document_xml, validated.style_names, content)
        if reading["limits"]["readableCharacterCount"] > MATERIAL_IMPORT_MAX_READABLE_CHARACTERS:
            raise AdapterError(
                "MATERIAL_TEXT_OVER_LIMIT",
                "可读取文字超过本阶段实施参数上限，已拒绝导入，未截断内容。",
                status_code=413,
            )
        material_id = "mat_{0}".format(secrets.token_hex(8))
        view = {
            "materialId": material_id,
            "taskType": TASK_TYPE,
            "fileName": file_name,
            "documentSessionId": str(
                payload.get("documentSessionId") or payload.get("document_session_id") or ""
            ),
            "sourceFileUnchanged": True,
            "targetDocumentUnchanged": True,
            "understandsAllContent": False,
            "limits": reading["limits"],
            "disclosure": reading["disclosure"],
            "unreadRegions": reading["unreadRegions"],
            "blocks": reading["blocks"],
            "fragments": reading["fragments"],
        }
        self._materials[material_id] = view
        return view

    def view_material(self, material_id: str) -> dict:
        view = self._materials.get(material_id)
        if view is None:
            raise AdapterError(
                "MATERIAL_NOT_FOUND",
                "资料不存在或已过期，请重新导入。",
                status_code=404,
            )
        return view


def _decode_upload(value) -> bytes:
    encoded = str(value or "").strip()
    if not encoded:
        raise AdapterError("MATERIAL_FILE_TYPE_REJECTED", "未收到 DOCX 文件内容。", status_code=400)
    try:
        return base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise AdapterError(
            "MATERIAL_FILE_REJECTED",
            "文件内容无法读取，请重新选择有效 DOCX。",
            status_code=400,
        ) from exc


def _reject_wrong_type(file_name: str, mime_type: str) -> None:
    lowered_name = file_name.lower()
    lowered_mime = mime_type.lower()
    if lowered_name and not lowered_name.endswith(".docx"):
        raise AdapterError(
            "MATERIAL_FILE_TYPE_REJECTED",
            "只接受 DOCX 资料，当前文件类型不符。",
            status_code=400,
        )
    if lowered_mime and "wordprocessingml" not in lowered_mime and lowered_mime not in {
        "application/octet-stream",
        "application/zip",
    }:
        raise AdapterError(
            "MATERIAL_FILE_TYPE_REJECTED",
            "只接受 DOCX 资料，当前文件类型不符。",
            status_code=400,
        )


def _security_error(exc: DocxSecurityError) -> AdapterError:
    message = str(exc)
    if "too large" in message or "budget" in message or "ratio" in message:
        return AdapterError(
            "MATERIAL_FILE_TOO_LARGE",
            "文件超过现有 DOCX 安全校验上限，已拒绝导入，未截断内容。",
            status_code=413,
        )
    return AdapterError(
        "MATERIAL_FILE_REJECTED",
        "文件未通过现有 DOCX 安全校验，已拒绝导入。",
        status_code=400,
    )


def _read_document(document_xml: bytes, style_names: Dict[str, str], package: bytes) -> dict:
    root = ElementTree.fromstring(document_xml)
    body = _find_child(root, "body")
    blocks = []
    fragments = []
    table_index = 0
    readable_count = 0
    if body is not None:
        for block_index, child in enumerate(list(body)):
            name = _local_name(child.tag)
            if name == "p":
                block, fragment, count = _paragraph_block(
                    child, style_names, block_index, len(fragments) + 1
                )
                if block is None:
                    continue
                blocks.append(block)
                if fragment is not None:
                    fragments.append(fragment)
                readable_count += count
            elif name == "tbl":
                block, table_fragments, count = _table_block(
                    child, block_index, table_index, len(fragments) + 1
                )
                table_index += 1
                if block is None:
                    continue
                blocks.append(block)
                fragments.extend(table_fragments)
                readable_count += count
    unread = _unread_regions(document_xml, package)
    return {
        "blocks": blocks,
        "fragments": fragments,
        "unreadRegions": unread,
        "disclosure": (
            "本次只读取正文、标题、列表和表格文字。"
            "图片文字和嵌入附件未读取，不宣称理解全部内容。"
        ),
        "limits": {
            "parameterStatus": "implementation_parameter",
            "productConfirmed": False,
            "fileByteLimit": DOCX_MAX_PACKAGE_BYTES,
            "fileByteLimitSource": "existing_docx_security_gate",
            "readableCharacterLimit": MATERIAL_IMPORT_MAX_READABLE_CHARACTERS,
            "characterCountMethod": CHARACTER_COUNT_METHOD,
            "readableCharacterCount": readable_count,
        },
    }


def _paragraph_block(paragraph, style_names, block_index, fragment_number):
    text = _element_text(paragraph)
    if not text:
        return None, None, 0
    level = _heading_level(paragraph, style_names)
    source = {"part": _PART, "blockIndex": block_index}
    if level is not None:
        kind = "heading"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "level": level,
            "text": text,
            "source": source,
        }
    elif _has_child(paragraph, "numPr"):
        kind = "list_item"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "text": text,
            "source": source,
        }
    else:
        kind = "paragraph"
        block = {
            "blockId": "block-{0}".format(block_index),
            "kind": kind,
            "text": text,
            "source": source,
        }
    fragment = {
        "fragmentId": "frag-{0}".format(fragment_number),
        "blockId": block["blockId"],
        "kind": kind,
        "text": text,
        "source": source,
    }
    return block, fragment, len(text)


def _table_block(table, block_index, table_index, fragment_start):
    rows = []
    fragments = []
    readable_count = 0
    fragment_number = fragment_start
    for row_index, row in enumerate(_children(table, "tr")):
        cells = []
        column_index = 0
        for cell in _children(row, "tc"):
            text = _cell_text(cell)
            span = _grid_span(cell)
            cells.append(text)
            source = {
                "part": _PART,
                "blockIndex": block_index,
                "tableIndex": table_index,
                "row": row_index,
                "column": column_index,
            }
            fragments.append(
                {
                    "fragmentId": "frag-{0}".format(fragment_number),
                    "blockId": "block-{0}".format(block_index),
                    "kind": "table_cell",
                    "text": text,
                    "source": source,
                }
            )
            fragment_number += 1
            readable_count += len(text)
            column_index += span
            if span > 1:
                cells.extend([""] * (span - 1))
        rows.append(cells)
    if not rows:
        return None, [], 0
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return (
        {
            "blockId": "block-{0}".format(block_index),
            "kind": "table",
            "rows": rows,
            "source": {
                "part": _PART,
                "blockIndex": block_index,
                "tableIndex": table_index,
            },
        },
        fragments,
        readable_count,
    )


def _heading_level(paragraph, style_names) -> Optional[int]:
    properties = _find_child(paragraph, "pPr")
    if properties is None:
        return None
    style = _find_child(properties, "pStyle")
    style_value = _attr(style, "val") if style is not None else ""
    style_name = (style_names or {}).get(style_value, "")
    match = _HEADING_NAME.match(re.sub(r"\s+", " ", str(style_name or style_value).strip()))
    if match is not None:
        return int(match.group(1))
    outline = _find_child(properties, "outlineLvl")
    if outline is None:
        return None
    try:
        level = int(_attr(outline, "val"))
    except (TypeError, ValueError):
        return None
    if 0 <= level <= 5:
        return level + 1
    return None


def _unread_regions(document_xml: bytes, package: bytes) -> List[dict]:
    root = ElementTree.fromstring(document_xml)
    image_count = 0
    for element in root.iter():
        if _local_name(element.tag) in {"drawing", "pict"}:
            image_count += 1
    embedded_count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
            for name in archive.namelist():
                lowered = name.lower()
                if "/embeddings/" in lowered or "oleobject" in lowered:
                    embedded_count += 1
    except zipfile.BadZipFile:
        embedded_count = 0
    regions = []
    if image_count:
        regions.append(
            {
                "kind": "image",
                "count": image_count,
                "message": "图片中的文字未读取。",
            }
        )
    if embedded_count:
        regions.append(
            {
                "kind": "embedded_attachment",
                "count": embedded_count,
                "message": "嵌入附件未读取。",
            }
        )
    return regions


def _cell_text(cell) -> str:
    parts = []
    for paragraph in cell.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        text = _element_text(paragraph)
        if text:
            parts.append(text)
    return " ".join(parts)


def _element_text(element) -> str:
    parts = []
    for node in element.iter():
        if _local_name(node.tag) == "t" and node.text:
            parts.append(node.text)
    return "".join(parts).strip()


def _grid_span(cell) -> int:
    for node in cell.iter():
        if _local_name(node.tag) == "gridSpan":
            try:
                return max(1, int(_attr(node, "val")))
            except (TypeError, ValueError):
                return 1
    return 1


def _has_child(element, local_name: str) -> bool:
    return _find_descendant(element, local_name) is not None


def _find_child(element, local_name: str):
    if element is None:
        return None
    for child in list(element):
        if _local_name(child.tag) == local_name:
            return child
    return None


def _find_descendant(element, local_name: str):
    for node in element.iter():
        if _local_name(node.tag) == local_name:
            return node
    return None


def _children(element, local_name: str):
    return [child for child in list(element) if _local_name(child.tag) == local_name]


def _attr(element, local_name: str) -> str:
    if element is None:
        return ""
    for key, value in element.attrib.items():
        if _local_name(key) == local_name:
            return str(value or "")
    return ""


def _local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]
