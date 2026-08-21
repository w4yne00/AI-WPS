import io
import posixpath
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Set
from urllib.parse import unquote
from xml.etree import ElementTree
import zipfile


DOCX_MAX_ENTRIES = 5000
DOCX_MAX_PACKAGE_BYTES = 10 * 1024 * 1024
DOCX_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DOCX_MAX_REQUIRED_PART_BYTES = 20 * 1024 * 1024
DOCX_MAX_XML_PART_BYTES = 20 * 1024 * 1024
DOCX_MAX_COMPRESSION_RATIO = 100
DOCX_COMPRESSION_RATIO_MIN_BYTES = 4096
DOCX_MAX_XML_ELEMENTS = 200000
DOCX_MAX_XML_DEPTH = 64
DOCX_MAX_RELATIONSHIPS = 2000
ZIP_READ_CHUNK_BYTES = 64 * 1024
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")
XML_DECLARATION_RE = re.compile(br"<!\s*(?:doctype|entity)\b", re.IGNORECASE)
EXTERNAL_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

CONTENT_TYPES_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/content-types"
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"


class DocxSecurityError(ValueError):
    """Raised when a DOCX violates the local package or XML safety gate."""


@dataclass(frozen=True)
class ValidatedDocx:
    document_xml: bytes
    styles_xml: Optional[bytes]
    style_names: Dict[str, str]
    style_capability: str


def validate_docx_bytes(
    content: bytes,
    max_package_bytes: Optional[int] = None,
    max_entries: Optional[int] = None,
    max_uncompressed_bytes: Optional[int] = None,
    max_required_part_bytes: Optional[int] = None,
    max_xml_part_bytes: Optional[int] = None,
    max_compression_ratio: Optional[int] = None,
    compression_ratio_min_bytes: Optional[int] = None,
    max_xml_elements: Optional[int] = None,
    max_xml_depth: Optional[int] = None,
    max_relationships: Optional[int] = None,
) -> ValidatedDocx:
    max_package_bytes = (
        DOCX_MAX_PACKAGE_BYTES if max_package_bytes is None else max_package_bytes
    )
    if not isinstance(content, bytes) or len(content) > max_package_bytes:
        raise DocxSecurityError("DOCX package is too large")
    max_entries = DOCX_MAX_ENTRIES if max_entries is None else max_entries
    max_uncompressed_bytes = (
        DOCX_MAX_UNCOMPRESSED_BYTES
        if max_uncompressed_bytes is None
        else max_uncompressed_bytes
    )
    max_required_part_bytes = (
        DOCX_MAX_REQUIRED_PART_BYTES
        if max_required_part_bytes is None
        else max_required_part_bytes
    )
    max_xml_part_bytes = (
        DOCX_MAX_XML_PART_BYTES if max_xml_part_bytes is None else max_xml_part_bytes
    )
    max_compression_ratio = (
        DOCX_MAX_COMPRESSION_RATIO
        if max_compression_ratio is None
        else max_compression_ratio
    )
    compression_ratio_min_bytes = (
        DOCX_COMPRESSION_RATIO_MIN_BYTES
        if compression_ratio_min_bytes is None
        else compression_ratio_min_bytes
    )
    max_xml_elements = (
        DOCX_MAX_XML_ELEMENTS if max_xml_elements is None else max_xml_elements
    )
    max_xml_depth = DOCX_MAX_XML_DEPTH if max_xml_depth is None else max_xml_depth
    max_relationships = (
        DOCX_MAX_RELATIONSHIPS if max_relationships is None else max_relationships
    )

    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            entries = archive.infolist()
            names = _validate_zip_entries(
                entries,
                max_entries=max_entries,
                max_uncompressed_bytes=max_uncompressed_bytes,
                max_compression_ratio=max_compression_ratio,
                compression_ratio_min_bytes=compression_ratio_min_bytes,
            )
            required_names = ("[Content_Types].xml", "word/document.xml")
            if any(name not in names for name in required_names):
                raise DocxSecurityError("missing required DOCX parts")

            critical_names = set(required_names)
            if "word/styles.xml" in names:
                critical_names.add("word/styles.xml")
            for name in critical_names:
                info = _entry_by_name(entries, name)
                if info.file_size > max_required_part_bytes:
                    raise DocxSecurityError("critical DOCX part is too large")

            if archive.testzip() is not None:
                raise DocxSecurityError("DOCX contains a corrupt ZIP entry")

            parsed_roots = {}
            xml_parts = {}
            xml_element_count = 0
            for entry in entries:
                if not _is_xml_part(entry.filename):
                    continue
                raw = _read_member(archive, entry, max_bytes=max_xml_part_bytes)
                root, element_count = _parse_xml_bytes(
                    raw,
                    max_elements=max_xml_elements,
                    max_depth=max_xml_depth,
                )
                xml_element_count += element_count
                if xml_element_count > max_xml_elements:
                    raise DocxSecurityError("DOCX XML exceeds its package budget")
                if (
                    entry.filename.lower().endswith(".rels")
                    or entry.filename in critical_names
                ):
                    parsed_roots[entry.filename] = root
                if entry.filename in critical_names:
                    xml_parts[entry.filename] = raw

            content_types_root = parsed_roots.get("[Content_Types].xml")
            document_root = parsed_roots.get("word/document.xml")
            _require_root(
                content_types_root,
                CONTENT_TYPES_NAMESPACE,
                "Types",
                "invalid content types part",
            )
            _require_root(
                document_root,
                WORD_NAMESPACE,
                "document",
                "invalid document part",
            )

            styles_root = parsed_roots.get("word/styles.xml")
            style_names = {}
            if styles_root is not None:
                _require_root(
                    styles_root,
                    WORD_NAMESPACE,
                    "styles",
                    "invalid styles part",
                )
                style_names = _build_style_name_map(styles_root)

            _validate_relationships(
                parsed_roots,
                names,
                max_relationships=max_relationships,
            )
            return ValidatedDocx(
                document_xml=xml_parts["word/document.xml"],
                styles_xml=xml_parts.get("word/styles.xml"),
                style_names=style_names,
                style_capability=(
                    "styles_xml" if styles_root is not None else "outline_fallback"
                ),
            )
    except DocxSecurityError:
        raise
    except (
        KeyError,
        MemoryError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        raise DocxSecurityError("DOCX package is invalid") from exc


def _validate_zip_entries(
    entries: Sequence[zipfile.ZipInfo],
    max_entries: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: int,
    compression_ratio_min_bytes: int,
) -> Set[str]:
    if len(entries) > max_entries:
        raise DocxSecurityError("too many DOCX entries")

    names = set()
    normalized_names = set()
    expanded_bytes = 0
    for entry in entries:
        name = str(entry.filename or "")
        is_directory = name.endswith("/")
        path_name = name[:-1] if is_directory else name
        normalized_name = unicodedata.normalize("NFKC", name)
        path_parts = path_name.split("/")
        normalized_path = posixpath.normpath(path_name)
        normalized_key = normalized_name.casefold()
        if (
            not name
            or not path_name
            or "\\" in name
            or name.startswith("/")
            or WINDOWS_ABSOLUTE_RE.match(name)
            or any(part in ("", ".", "..") for part in path_parts)
            or normalized_path != path_name
            or normalized_name != name
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in name)
            or name in names
            or normalized_key in normalized_names
            or entry.flag_bits & 0x1
            or entry.file_size < 0
            or entry.compress_size < 0
        ):
            raise DocxSecurityError("DOCX contains an unsafe ZIP member")

        names.add(name)
        normalized_names.add(normalized_key)
        expanded_bytes += entry.file_size
        if expanded_bytes > max_uncompressed_bytes:
            raise DocxSecurityError("DOCX uncompressed content is too large")
        if entry.file_size >= compression_ratio_min_bytes:
            if entry.compress_size == 0 or entry.file_size > entry.compress_size * max_compression_ratio:
                raise DocxSecurityError("DOCX compression ratio is unsafe")
    return names


def _entry_by_name(entries: Sequence[zipfile.ZipInfo], name: str) -> zipfile.ZipInfo:
    for entry in entries:
        if entry.filename == name:
            return entry
    raise DocxSecurityError("required DOCX part is missing")


def _read_member(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    max_bytes: int,
) -> bytes:
    if entry.file_size > max_bytes:
        raise DocxSecurityError("DOCX member is too large")
    chunks = []
    total = 0
    with archive.open(entry, "r") as source:
        while True:
            chunk = source.read(ZIP_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise DocxSecurityError("DOCX member expands beyond its budget")
            chunks.append(chunk)
    if total != entry.file_size:
        raise DocxSecurityError("DOCX member size does not match its declaration")
    return b"".join(chunks)


def _is_xml_part(name: str) -> bool:
    lower_name = name.lower()
    return lower_name.endswith(".xml") or lower_name.endswith(".rels")


def _parse_xml_bytes(raw: bytes, max_elements: int, max_depth: int):
    if XML_DECLARATION_RE.search(raw):
        raise DocxSecurityError("DOCX XML contains a DTD or entity declaration")
    depth = 0
    element_count = 0
    try:
        for event, element in ElementTree.iterparse(
            io.BytesIO(raw), events=("start", "end")
        ):
            if event == "start":
                depth += 1
                element_count += 1
                if element_count > max_elements or depth > max_depth:
                    raise DocxSecurityError("DOCX XML exceeds its structural budget")
            else:
                depth -= 1
                element.clear()
        return ElementTree.fromstring(raw), element_count
    except DocxSecurityError:
        raise
    except ElementTree.ParseError as exc:
        raise DocxSecurityError("DOCX XML is malformed") from exc


def _require_root(root, namespace: str, local_name: str, message: str) -> None:
    if root is None or root.tag != "{{{0}}}{1}".format(namespace, local_name):
        raise DocxSecurityError(message)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attribute(element, local_name: str) -> str:
    for key, value in element.attrib.items():
        if _local_name(key) == local_name:
            return str(value or "")
    return ""


def _build_style_name_map(styles_root) -> Dict[str, str]:
    records = {}
    seen_style_ids = set()
    for style in styles_root:
        if _local_name(style.tag) != "style":
            continue
        style_id = _attribute(style, "styleId").strip()
        if not style_id or style_id in seen_style_ids:
            raise DocxSecurityError("DOCX styles contain duplicate or missing style IDs")
        seen_style_ids.add(style_id)
        style_type = _attribute(style, "type").strip().lower()
        if style_type and style_type != "paragraph":
            continue
        name = ""
        based_on = ""
        for child in style:
            child_name = _local_name(child.tag)
            if child_name == "name":
                name = _attribute(child, "val").strip()
            elif child_name == "basedOn":
                based_on = _attribute(child, "val").strip()
        records[style_id] = {"name": name, "based_on": based_on}

    def resolve(style_id: str, trail: Sequence[str]) -> str:
        if style_id in trail:
            raise DocxSecurityError("DOCX styles contain an inheritance cycle")
        record = records.get(style_id)
        if record is None:
            return ""
        if record["name"]:
            return record["name"]
        parent = record["based_on"]
        if not parent:
            return ""
        return resolve(parent, tuple(trail) + (style_id,))

    return {style_id: resolve(style_id, ()) for style_id in records}


def _validate_relationships(
    parsed_roots: Dict[str, object],
    names: Set[str],
    max_relationships: int,
) -> None:
    relationship_count = 0
    for relationship_part, root in parsed_roots.items():
        if not relationship_part.lower().endswith(".rels"):
            continue
        _require_root(
            root,
            RELATIONSHIPS_NAMESPACE,
            "Relationships",
            "invalid DOCX relationship part",
        )
        if relationship_part == "_rels/.rels":
            source_directory = ""
        else:
            source_directory = relationship_part.split("/_rels/", 1)[0]
        for relationship in root.iter():
            if _local_name(relationship.tag) != "Relationship":
                continue
            relationship_count += 1
            if relationship_count > max_relationships:
                raise DocxSecurityError("DOCX contains too many relationships")
            target = _attribute(relationship, "Target").strip()
            target_mode = _attribute(relationship, "TargetMode").strip().lower()
            if (
                not target
                or target_mode == "external"
                or target.startswith("/")
                or "\\" in target
                or EXTERNAL_TARGET_RE.match(target)
            ):
                raise DocxSecurityError("DOCX contains an external or unsafe relationship")
            target = unquote(target.split("#", 1)[0])
            resolved_target = posixpath.normpath(
                posixpath.join(source_directory, target)
            )
            if (
                resolved_target in ("", ".", "..")
                or resolved_target.startswith("../")
                or resolved_target not in names
            ):
                raise DocxSecurityError("DOCX relationship target is outside the package")
