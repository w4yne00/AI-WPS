import csv
import copy
import io
import posixpath
import re
import secrets
import threading
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from app.services.enterprise_knowledge.models import (
    MAX_CELL_CHARS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    MAX_XLSX_EXPANDED_BYTES,
    PREVIEW_TTL_SECONDS,
    KnowledgeError,
    normalize_key,
)


IMPORT_COLUMNS = (
    "类型",
    "适用范围",
    "名称",
    "标准写法/规则",
    "别名/禁用写法",
    "推荐示例",
    "不推荐示例",
    "关键词",
    "优先级",
    "始终应用",
    "启用",
    "备注",
)
LIST_SEPARATOR = "|"
CSV_MIME = "text/csv"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_EXPORT_MARKER = "#AI-WPS-ENTERPRISE-KNOWLEDGE-EXPORT:1"

_GENERIC_IMPORT_MIMES = {"", "application/octet-stream"}
_CSV_MIMES = _GENERIC_IMPORT_MIMES.union({CSV_MIME, "text/plain"})
_XLSX_MIMES = _GENERIC_IMPORT_MIMES.union({XLSX_MIME})

_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_MAX_XLSX_ENTRIES = 256
_MAX_COMPRESSION_RATIO = 100
_COMPRESSION_RATIO_MIN_BYTES = 4096
MAX_XLSX_WORKSHEET_ELEMENTS = 200000
MAX_XLSX_WORKSHEET_DEPTH = 32
MAX_XLSX_SHARED_STRING_ITEMS = (MAX_IMPORT_ROWS + 1) * len(IMPORT_COLUMNS)
MAX_XLSX_SHARED_STRING_ELEMENTS = MAX_XLSX_SHARED_STRING_ITEMS * 8 + 1
MAX_XLSX_SHARED_STRING_DEPTH = 16
MAX_XLSX_CELL_REFERENCE_CHARS = 7
MAX_XLSX_COLUMN_LETTERS = 3
MAX_XLSX_ROW_DIGITS = 4
MAX_XLSX_ROW_NUMBER = MAX_IMPORT_ROWS + 1
MAX_XLSX_SHARED_STRING_INDEX_DIGITS = 7
_ZIP_READ_CHUNK_BYTES = 64 * 1024
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CELL_REFERENCE_RE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$")
_NON_NEGATIVE_INTEGER_RE = re.compile(r"^[0-9]+$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")

_TYPE_MAP = {
    "术语": "term",
    "term": "term",
    "风格": "style",
    "style": "style",
}
_SCOPE_MAP = {
    "全局": "global",
    "global": "global",
    "智能编写": "word.smart_write",
    "word.smart_write": "word.smart_write",
    "智能仿写": "word.smart_imitation",
    "word.smart_imitation": "word.smart_imitation",
    "文档审查": "word.document_review",
    "word.document_review": "word.document_review",
}
_PRIORITY_MAP = {
    "高": "high",
    "high": "high",
    "中": "medium",
    "medium": "medium",
    "低": "low",
    "low": "low",
}
_BOOLEAN_MAP = {"是": True, "否": False}

_EXAMPLE_ROW = (
    "术语",
    "全局",
    "系统",
    "卫星互联网运营管理平台",
    "别名:卫星网管平台|禁用:卫星网管系统",
    "",
    "",
    "运营|网管",
    "高",
    "否",
    "是",
    "列表字段使用 | 分隔；字面 | 写作 \\|，反斜杠写作 \\\\。",
)


class _ImportRow(dict):
    def __init__(self, values: Dict[str, str], row_number: int):
        super().__init__(values)
        self.row_number = row_number
        self._sourceRow = row_number


class _RowValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ImportPreviewStore:
    def __init__(
        self,
        clock: Optional[Callable[[], float]] = None,
        ttl_seconds: int = PREVIEW_TTL_SECONDS,
        max_entries: int = 20,
    ):
        self._clock = clock or time.monotonic
        self._ttl_seconds = int(ttl_seconds)
        self._max_entries = int(max_entries)
        if self._ttl_seconds <= 0 or self._max_entries <= 0:
            raise ValueError("preview limits must be positive")
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, object]] = {}
        self._sequence = 0

    def create(
        self,
        file_name: str,
        items: Sequence[Dict[str, object]],
        conflicts: Sequence[Dict[str, object]],
        errors: Optional[Sequence[Dict[str, object]]] = None,
        stats: Optional[Dict[str, object]] = None,
        file_meta: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        now = float(self._clock())
        safe_meta = self._safe_file_meta(file_name, file_meta or {})
        payload = {
            "fileMeta": safe_meta,
            "items": self._safe_copy(items),
            "conflicts": self._safe_copy(conflicts),
            "errors": self._safe_copy(errors or []),
            "stats": self._safe_copy(stats or {}),
        }
        with self._lock:
            self._purge_expired(now)
            while len(self._entries) >= self._max_entries:
                oldest_token = min(
                    self._entries,
                    key=lambda token: int(self._entries[token]["sequence"]),
                )
                del self._entries[oldest_token]
            token = secrets.token_urlsafe(24)
            while token in self._entries:
                token = secrets.token_urlsafe(24)
            self._sequence += 1
            self._entries[token] = {
                "expiresAt": now + self._ttl_seconds,
                "sequence": self._sequence,
                "payload": payload,
            }
        return {
            "previewToken": token,
            "expiresInSeconds": self._ttl_seconds,
        }

    def get(self, token: str) -> Dict[str, object]:
        return self._take(token, consume=False)

    def consume(self, token: str) -> Dict[str, object]:
        return self._take(token, consume=True)

    def live_count(self) -> int:
        with self._lock:
            self._purge_expired(float(self._clock()))
            return len(self._entries)

    def _take(self, token: str, consume: bool) -> Dict[str, object]:
        clean_token = str(token or "")
        now = float(self._clock())
        with self._lock:
            entry = self._entries.get(clean_token)
            if entry is None:
                raise KnowledgeError(
                    "import_preview_not_found", "未找到导入预览，请重新选择文件。"
                )
            if now >= float(entry["expiresAt"]):
                del self._entries[clean_token]
                raise KnowledgeError(
                    "import_preview_expired", "导入预览已过期，请重新选择文件。"
                )
            if consume:
                del self._entries[clean_token]
            return copy.deepcopy(entry["payload"])

    def _purge_expired(self, now: float) -> None:
        expired = [
            token
            for token, entry in self._entries.items()
            if now >= float(entry["expiresAt"])
        ]
        for token in expired:
            del self._entries[token]

    @staticmethod
    def _safe_file_meta(
        file_name: str, file_meta: Dict[str, object]
    ) -> Dict[str, object]:
        safe = {"fileName": str(file_name or file_meta.get("fileName") or "")}
        for key in ("format", "rowCount", "mimeType", "sizeBytes"):
            if key in file_meta:
                safe[key] = copy.deepcopy(file_meta[key])
        return safe

    @classmethod
    def _safe_copy(cls, value):
        if isinstance(value, bytes):
            raise KnowledgeError(
                "invalid_import_preview", "导入预览不能缓存原始文件内容。"
            )
        if isinstance(value, dict):
            return {
                str(key): cls._safe_copy(entry)
                for key, entry in value.items()
                if str(key) not in ("contentBase64", "rawBytes", "content")
            }
        if isinstance(value, (list, tuple)):
            return [cls._safe_copy(entry) for entry in value]
        return copy.deepcopy(value)


DEFAULT_IMPORT_PREVIEW_STORE = ImportPreviewStore()


def generate_csv_template() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(IMPORT_COLUMNS)
    writer.writerow(_EXAMPLE_ROW)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def csv_safe_cell(value: str) -> str:
    text = "" if value is None else str(value)
    if text.startswith("'"):
        return "'" + text
    trimmed = text.lstrip()
    if trimmed and trimmed[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def csv_restore_cell(value: str) -> str:
    text = "" if value is None else str(value)
    if text.startswith("''"):
        return text[1:]
    if text.startswith("'"):
        candidate = text[1:]
        trimmed = candidate.lstrip()
        if trimmed and trimmed[0] in ("=", "+", "-", "@"):
            return candidate
    return text


def generate_xlsx_template() -> bytes:
    rows = (IMPORT_COLUMNS, _EXAMPLE_ROW)
    sheet_rows = []
    for row_index, values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(values, start=1):
            reference = "%s%d" % (_excel_column_name(column_index), row_index)
            cells.append(
                '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                % (reference, escape(str(value)))
            )
        sheet_rows.append('<row r="%d">%s</row>' % (row_index, "".join(cells)))

    parts = (
        (
            "[Content_Types].xml",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            b'</Types>',
        ),
        (
            "_rels/.rels",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            b'</Relationships>',
        ),
        (
            "xl/workbook.xml",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            b'<sheets><sheet name="\xe4\xbc\x81\xe4\xb8\x9a\xe7\x9f\xa5\xe8\xaf\x86\xe5\xaf\xbc\xe5\x85\xa5" sheetId="1" r:id="rId1"/></sheets>'
            b'</workbook>',
        ),
        (
            "xl/_rels/workbook.xml.rels",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            b'</Relationships>',
        ),
        (
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetData>%s</sheetData></worksheet>' % "".join(sheet_rows)
            ).encode("utf-8"),
        ),
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in parts:
            info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, content)
    return output.getvalue()


def parse_import_file(
    file_name: str, mime_type: str, content: bytes
) -> List[Dict[str, str]]:
    _validate_file_size(content)
    suffix = Path(str(file_name or "")).suffix.lower()
    if suffix == ".csv":
        _validate_import_mime(mime_type, _CSV_MIMES)
        return parse_csv(content, str(file_name or ""))
    if suffix == ".xlsx":
        _validate_import_mime(mime_type, _XLSX_MIMES)
        return parse_xlsx(content, str(file_name or ""))
    raise KnowledgeError(
        "unsupported_import_type", "仅支持 UTF-8 CSV 或标准 XLSX 模板。"
    )


def parse_csv(content: bytes, file_name: str) -> List[Dict[str, str]]:
    del file_name
    _validate_file_size(content)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise KnowledgeError("invalid_import_encoding", "CSV 文件必须使用 UTF-8 编码。")
    if "\x00" in text:
        raise KnowledgeError("invalid_import_encoding", "CSV 文件包含无效字符。")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        restore_export_cells = headers == [CSV_EXPORT_MARKER]
        if restore_export_cells:
            headers = next(reader, None)
        if headers is None or tuple(headers) != IMPORT_COLUMNS:
            raise KnowledgeError(
                "invalid_import_headers", "导入文件表头与标准模板不一致。"
            )
        rows = []
        for values in reader:
            row_number = reader.line_num
            if not values or not any(str(value).strip() for value in values):
                continue
            if len(values) != len(IMPORT_COLUMNS):
                raise KnowledgeError(
                    "invalid_import_row",
                    "第 %d 行的列数与标准模板不一致。" % row_number,
                )
            clean_values = [str(value).strip() for value in values]
            if restore_export_cells:
                clean_values = [csv_restore_cell(value) for value in clean_values]
            _validate_cell_lengths(clean_values, row_number)
            rows.append(
                _ImportRow(dict(zip(IMPORT_COLUMNS, clean_values)), row_number)
            )
            _validate_row_count(rows)
        return rows
    except csv.Error as exc:
        raise KnowledgeError("invalid_import_file", "CSV 文件格式无效：%s" % exc)


def parse_xlsx(content: bytes, file_name: str) -> List[Dict[str, str]]:
    del file_name
    _validate_file_size(content)
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            entries = archive.infolist()
            _validate_zip_entries(entries)
            _validate_zip_contents(archive, entries)
            names = {entry.filename for entry in entries}
            required = {"[Content_Types].xml", "_rels/.rels"}
            if not required.issubset(names):
                raise KnowledgeError(
                    "invalid_xlsx", "XLSX 文件缺少必要的工作簿结构。"
                )
            _validate_xlsx_package(archive, entries)
            root_relationships = _read_xml(archive, "_rels/.rels")
            workbook_path = _office_document_path(root_relationships, names)
            workbook_relationships_path = _relationship_part_path(workbook_path)
            if workbook_relationships_path not in names:
                raise KnowledgeError(
                    "invalid_xlsx", "XLSX 文件缺少工作簿关系结构。"
                )
            workbook = _read_xml(archive, workbook_path)
            workbook_rels = _read_xml(archive, workbook_relationships_path)
            sheet_path, shared_strings_path, worksheet_paths = _workbook_part_paths(
                workbook, workbook_rels, names, workbook_path
            )
            shared_strings = []
            if shared_strings_path:
                shared_strings = _parse_shared_strings(
                    archive.read(shared_strings_path)
                )
            first_worksheet_content = None
            for worksheet_path in worksheet_paths:
                worksheet_content = archive.read(worksheet_path)
                _scan_worksheet_xml(worksheet_content)
                if worksheet_path == sheet_path:
                    first_worksheet_content = worksheet_content
                else:
                    del worksheet_content
            if first_worksheet_content is None:
                raise KnowledgeError("invalid_xlsx", "XLSX 首个工作表不存在。")
            worksheet = _parse_xml_bytes(first_worksheet_content)
            return _parse_worksheet(worksheet, shared_strings)
    except KnowledgeError:
        raise
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError):
        raise KnowledgeError("invalid_xlsx", "XLSX 文件格式无效或已损坏。")


def validate_import_rows(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    valid_items = []
    item_rows = []
    errors = []
    term_tokens = set()
    style_names = set()

    for fallback_row_number, raw_row in enumerate(rows, start=2):
        row_number = int(
            getattr(
                raw_row,
                "_sourceRow",
                getattr(raw_row, "row_number", fallback_row_number),
            )
        )
        try:
            item = _map_row(raw_row)
            if item["type"] == "term":
                current_tokens = _term_tokens(item)
                if current_tokens.intersection(term_tokens):
                    raise _RowValidationError(
                        "duplicate_import_row", "与前面的术语写法重复。"
                    )
                term_tokens.update(current_tokens)
            else:
                style_key = (item["scope"], normalize_key(item["name"]))
                if style_key in style_names:
                    raise _RowValidationError(
                        "duplicate_import_row", "当前范围内存在重复的风格规则名称。"
                    )
                style_names.add(style_key)
            valid_items.append(item)
            item_rows.append({"rowNumber": row_number, "item": item})
        except _RowValidationError as exc:
            errors.append(
                {
                    "row": row_number,
                    "code": exc.code,
                    "message": "第 %d 行：%s" % (row_number, exc.message),
                }
            )

    return {
        "items": valid_items,
        "itemRows": item_rows,
        "errors": errors,
        "rowCount": len(rows),
    }


def build_import_preview(
    store,
    validated_result: Dict[str, object],
    file_meta: Dict[str, object],
    preview_store: Optional[ImportPreviewStore] = None,
) -> Dict[str, object]:
    previews = preview_store or DEFAULT_IMPORT_PREVIEW_STORE
    errors = list(validated_result.get("errors") or [])
    item_rows = _validated_item_rows(validated_result)
    existing_terms = store.list_items("global", "term")
    term_owners = {}
    for existing in existing_terms:
        for token in _term_tokens(existing):
            term_owners[token] = existing

    existing_styles = {}
    for scope in sorted(set(_SCOPE_MAP.values())):
        for existing in store.list_items(scope, "style"):
            existing_styles[(scope, normalize_key(existing["name"]))] = existing

    operations = []
    conflicts = []
    new_count = 0
    update_count = 0
    for entry in item_rows:
        row_number = int(entry["rowNumber"])
        item = entry["item"]
        if item.get("type") == "term":
            preferred_key = normalize_key(item["preferredText"])
            preferred_owner = term_owners.get(preferred_key)
            update_target = None
            if preferred_owner is not None and preferred_key == normalize_key(
                preferred_owner["preferredText"]
            ):
                update_target = preferred_owner
            colliding_owners = []
            for token in _term_tokens(item):
                owner = term_owners.get(token)
                if owner is not None and (
                    update_target is None or owner["id"] != update_target["id"]
                ):
                    colliding_owners.append(owner)
            if colliding_owners:
                existing = sorted(
                    colliding_owners,
                    key=lambda candidate: (
                        normalize_key(candidate["preferredText"]),
                        candidate["id"],
                    ),
                )[0]
                conflicts.append(
                    _term_conflict(row_number, item, existing)
                )
            elif update_target is not None:
                operations.append(
                    {
                        "rowNumber": row_number,
                        "action": "update",
                        "existingItemId": update_target["id"],
                        "item": copy.deepcopy(item),
                    }
                )
                update_count += 1
            else:
                operations.append(
                    {
                        "rowNumber": row_number,
                        "action": "create",
                        "item": copy.deepcopy(item),
                    }
                )
                new_count += 1
        elif item.get("type") == "style":
            existing = existing_styles.get(
                (item["scope"], normalize_key(item["name"]))
            )
            if existing is None:
                operations.append(
                    {
                        "rowNumber": row_number,
                        "action": "create",
                        "item": copy.deepcopy(item),
                    }
                )
                new_count += 1
            else:
                operations.append(
                    {
                        "rowNumber": row_number,
                        "action": "update",
                        "existingItemId": existing["id"],
                        "item": copy.deepcopy(item),
                    }
                )
                update_count += 1
        else:
            raise KnowledgeError(
                "invalid_knowledge_type", "知识条目类型必须为 term 或 style。"
            )

    stats = {
        "newCount": new_count,
        "updateCount": update_count,
        "conflictCount": len(conflicts),
        "errorCount": len(errors),
    }
    meta = dict(file_meta or {})
    meta.setdefault("rowCount", validated_result.get("rowCount", len(item_rows)))
    token_result = previews.create(
        str(meta.get("fileName") or ""),
        operations,
        conflicts,
        errors=errors,
        stats=stats,
        file_meta=meta,
    )
    return dict(
        token_result,
        errors=copy.deepcopy(errors),
        conflicts=copy.deepcopy(conflicts),
        **stats
    )


def apply_import_preview(
    store,
    preview_token: str,
    conflict_decisions: Optional[Sequence[Dict[str, object]]] = None,
    preview_store: Optional[ImportPreviewStore] = None,
) -> Dict[str, object]:
    previews = preview_store or DEFAULT_IMPORT_PREVIEW_STORE
    preview = previews.consume(preview_token)
    conflicts = list(preview.get("conflicts") or [])
    decisions = _normalize_conflict_decisions(conflict_decisions or [], conflicts)
    for conflict in conflicts:
        row_number = int(conflict["rowNumber"])
        decision = decisions.get(row_number, "keep_existing")
        if decision not in tuple(conflict.get("allowedDecisions") or ()):
            raise KnowledgeError(
                "invalid_import_decision",
                "第 %d 行的冲突处理方式无效。" % row_number,
            )

    stats = dict(preview.get("stats") or {})
    store_stats = {
        "conflictCount": int(stats.get("conflictCount", 0)),
        "errorCount": int(stats.get("errorCount", 0)),
    }
    return store.apply_preview(
        list(preview.get("items") or []),
        dict(preview.get("fileMeta") or {}),
        stats=store_stats,
    )


def export_csv(store, scope: str) -> bytes:
    items = []
    if scope == "global":
        items.extend(store.list_items("global", "term"))
    items.extend(store.list_items(scope, "style"))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([CSV_EXPORT_MARKER])
    writer.writerow(IMPORT_COLUMNS)
    for item in items:
        writer.writerow([csv_safe_cell(value) for value in _export_row(item)])
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def _validated_item_rows(
    validated_result: Dict[str, object]
) -> List[Dict[str, object]]:
    entries = validated_result.get("itemRows")
    if entries is not None:
        return copy.deepcopy(list(entries))
    return [
        {"rowNumber": index, "item": copy.deepcopy(item)}
        for index, item in enumerate(validated_result.get("items") or [], start=2)
    ]


def _term_conflict(
    row_number: int,
    incoming: Dict[str, object],
    existing: Dict[str, object],
) -> Dict[str, object]:
    return {
        "rowNumber": row_number,
        "type": "term_text_conflict",
        "incomingName": incoming["preferredText"],
        "existingItemId": existing["id"],
        "existingName": existing["preferredText"],
        "allowedDecisions": ["keep_existing", "skip"],
        "defaultDecision": "keep_existing",
        "message": "第 %d 行：术语写法与库内“%s”冲突，只能保留库内标准或跳过该行。"
        % (row_number, existing["preferredText"]),
    }


def _normalize_conflict_decisions(
    decisions: Sequence[Dict[str, object]],
    conflicts: Sequence[Dict[str, object]],
) -> Dict[int, str]:
    conflict_rows = {int(conflict["rowNumber"]) for conflict in conflicts}
    normalized = {}
    if isinstance(decisions, dict):
        iterable = [
            {"rowNumber": row_number, "decision": decision}
            for row_number, decision in decisions.items()
        ]
    else:
        iterable = decisions
    for entry in iterable:
        try:
            row_number = int(entry.get("rowNumber"))
        except (AttributeError, TypeError, ValueError):
            raise KnowledgeError(
                "invalid_import_decision", "导入冲突处理行号无效。"
            )
        decision = str(entry.get("decision") or "")
        if row_number not in conflict_rows or row_number in normalized:
            raise KnowledgeError(
                "invalid_import_decision", "导入冲突处理行号无效或重复。"
            )
        if decision not in ("keep_existing", "skip"):
            raise KnowledgeError(
                "invalid_import_decision",
                "第 %d 行只允许保留库内标准或跳过。" % row_number,
            )
        normalized[row_number] = decision
    return normalized


def _export_row(item: Dict[str, object]) -> Tuple[str, ...]:
    priority_labels = {"high": "高", "medium": "中", "low": "低"}
    scope_labels = {
        "global": "全局",
        "word.smart_write": "智能编写",
        "word.smart_imitation": "智能仿写",
        "word.document_review": "文档审查",
    }
    if item["type"] == "term":
        variants = ["别名:" + value for value in item["aliases"]]
        variants.extend("禁用:" + value for value in item["forbiddenVariants"])
        return (
            "术语",
            "全局",
            item["category"],
            item["preferredText"],
            _join_escaped_list(variants),
            "",
            "",
            _join_escaped_list(item["contextKeywords"]),
            priority_labels[item["priority"]],
            "否",
            "是" if item["enabled"] else "否",
            item["note"],
        )
    return (
        "风格",
        scope_labels[item["scope"]],
        item["name"],
        item["ruleText"],
        "",
        item["positiveExample"],
        item["negativeExample"],
        _join_escaped_list(item["contextKeywords"]),
        priority_labels[item["priority"]],
        "是" if item["alwaysApply"] else "否",
        "是" if item["enabled"] else "否",
        item["note"],
    )


def _join_escaped_list(values: Sequence[str]) -> str:
    return LIST_SEPARATOR.join(
        str(value).replace("\\", "\\\\").replace(LIST_SEPARATOR, "\\|")
        for value in values
    )


def _validate_file_size(content: bytes) -> None:
    if not isinstance(content, bytes) or not content:
        raise KnowledgeError("invalid_import_file", "导入文件为空或内容无效。")
    if len(content) > MAX_IMPORT_BYTES:
        raise KnowledgeError("import_file_too_large", "导入文件不能超过 5 MB。")


def _validate_import_mime(mime_type: str, allowed_mimes: Sequence[str]) -> None:
    normalized = str(mime_type or "").split(";", 1)[0].strip().casefold()
    if normalized not in allowed_mimes:
        raise KnowledgeError(
            "import_mime_mismatch", "文件扩展名与内容类型不匹配，请重新选择文件。"
        )


def _validate_cell_lengths(values: Sequence[str], row_number: int) -> None:
    for value in values:
        if len(value) > MAX_CELL_CHARS:
            raise KnowledgeError(
                "import_cell_too_long",
                "第 %d 行包含超过 2000 个字符的单元格。" % row_number,
            )


def _validate_row_count(rows: Sequence[Dict[str, str]]) -> None:
    if len(rows) > MAX_IMPORT_ROWS:
        raise KnowledgeError(
            "import_row_limit_exceeded", "导入文件最多包含 5000 条数据行。"
        )


def _validate_zip_entries(entries: Sequence[zipfile.ZipInfo]) -> None:
    if len(entries) > _MAX_XLSX_ENTRIES:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含过多内部文件。")
    seen_names = set()
    seen_normalized_names = set()
    expanded_bytes = 0
    for entry in entries:
        name = entry.filename
        path_parts = name.split("/")
        normalized = posixpath.normpath(name)
        unicode_normalized = unicodedata.normalize("NFKC", normalized)
        normalized_key = unicode_normalized.casefold()
        if (
            not name
            or name in seen_names
            or "\\" in name
            or name.startswith("/")
            or _WINDOWS_ABSOLUTE_RE.match(name)
            or any(part in ("", ".", "..") for part in path_parts)
            or normalized != name
            or unicode_normalized != normalized
            or normalized_key in seen_normalized_names
            or entry.flag_bits & 0x1
        ):
            raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的内部路径。")
        seen_names.add(name)
        seen_normalized_names.add(normalized_key)
        expanded_bytes += entry.file_size
        if expanded_bytes > MAX_XLSX_EXPANDED_BYTES:
            raise KnowledgeError("unsafe_xlsx", "XLSX 文件解压后内容超过 20 MB。")
        if entry.file_size >= _COMPRESSION_RATIO_MIN_BYTES:
            if entry.compress_size == 0:
                raise KnowledgeError("unsafe_xlsx", "XLSX 文件压缩结构异常。")
            if entry.file_size / float(entry.compress_size) > _MAX_COMPRESSION_RATIO:
                raise KnowledgeError("unsafe_xlsx", "XLSX 文件压缩比例异常。")


def _validate_zip_contents(
    archive: zipfile.ZipFile, entries: Sequence[zipfile.ZipInfo]
) -> None:
    expanded_bytes = 0
    for entry in entries:
        member_bytes = 0
        with archive.open(entry, "r") as source:
            while True:
                chunk = source.read(_ZIP_READ_CHUNK_BYTES)
                if not chunk:
                    break
                member_bytes += len(chunk)
                expanded_bytes += len(chunk)
                if expanded_bytes > MAX_XLSX_EXPANDED_BYTES:
                    raise KnowledgeError(
                        "unsafe_xlsx", "XLSX 文件实际解压内容超过 20 MB。"
                    )
        if member_bytes != entry.file_size:
            raise KnowledgeError("unsafe_xlsx", "XLSX 文件成员大小校验失败。")


def _validate_xlsx_package(
    archive: zipfile.ZipFile, entries: Sequence[zipfile.ZipInfo]
) -> None:
    lower_names = {entry.filename.lower() for entry in entries}
    if any(
        "vbaproject" in name
        or name.startswith("xl/macrosheets/")
        or name.startswith("xl/dialogsheets/")
        or name.startswith("xl/externallinks/")
        for name in lower_names
    ):
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件不得包含宏或外部链接。")

    content_types = archive.read("[Content_Types].xml")
    lower_content_types = content_types.lower()
    if b"macroenabled" in lower_content_types or b"vbaproject" in lower_content_types:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件不得包含宏。")
    _parse_xml_bytes(content_types)

    for entry in entries:
        if not entry.filename.lower().endswith(".rels"):
            continue
        relationships = _parse_xml_bytes(archive.read(entry))
        for relationship in relationships.iter():
            if _local_name(relationship.tag) != "Relationship":
                continue
            _validate_relationship(relationship)


def _read_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    try:
        content = archive.read(name)
    except KeyError:
        raise KnowledgeError("invalid_xlsx", "XLSX 文件缺少必要的 XML 结构。")
    return _parse_xml_bytes(content)


def _parse_xml_bytes(content: bytes) -> ElementTree.Element:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的 XML 声明。")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise KnowledgeError("invalid_xlsx", "XLSX 文件包含无效的 XML。")


def _scan_worksheet_xml(content: bytes) -> None:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的 XML 声明。")
    element_count = 0
    depth = 0
    try:
        for event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("start", "end")
        ):
            if event == "start":
                element_count += 1
                depth += 1
                if (
                    element_count > MAX_XLSX_WORKSHEET_ELEMENTS
                    or depth > MAX_XLSX_WORKSHEET_DEPTH
                ):
                    raise KnowledgeError(
                        "unsafe_xlsx", "XLSX 工作表 XML 结构超过安全预算。"
                    )
                if _local_name(element.tag) in ("f", "mergeCells", "mergeCell"):
                    raise KnowledgeError(
                        "unsafe_xlsx", "XLSX 模板不得包含公式或合并单元格。"
                    )
            else:
                depth -= 1
                element.clear()
    except ElementTree.ParseError:
        raise KnowledgeError("invalid_xlsx", "XLSX 文件包含无效的工作表 XML。")


def _workbook_part_paths(
    workbook: ElementTree.Element,
    relationships: ElementTree.Element,
    archive_names: Sequence[str],
    workbook_path: str,
) -> Tuple[str, str, Tuple[str, ...]]:
    relationship_map = {}
    shared_strings_path = ""
    worksheet_paths = []
    for relationship in relationships.iter():
        if _local_name(relationship.tag) != "Relationship":
            continue
        _validate_relationship(relationship)
        relationship_id = relationship.attrib.get("Id", "")
        target = relationship.attrib.get("Target", "")
        relationship_type = relationship.attrib.get("Type", "")
        part_path = _resolve_part_path(workbook_path, target)
        relationship_map[relationship_id] = (relationship_type, part_path)
        if relationship_type.endswith("/sharedStrings"):
            shared_strings_path = part_path
        if relationship_type.endswith("/worksheet"):
            if part_path not in archive_names:
                raise KnowledgeError("invalid_xlsx", "XLSX 工作表关系指向不存在的文件。")
            if part_path not in worksheet_paths:
                worksheet_paths.append(part_path)

    sheet = next(
        (element for element in workbook.iter() if _local_name(element.tag) == "sheet"),
        None,
    )
    if sheet is None:
        raise KnowledgeError("invalid_xlsx", "XLSX 文件没有可读取的工作表。")
    relationship_id = sheet.attrib.get("{%s}id" % _REL_NS, "")
    relationship = relationship_map.get(relationship_id)
    if relationship is None or not relationship[0].endswith("/worksheet"):
        raise KnowledgeError("invalid_xlsx", "XLSX 首个工作表关系无效。")
    sheet_path = relationship[1]
    if sheet_path not in archive_names:
        raise KnowledgeError("invalid_xlsx", "XLSX 首个工作表不存在。")
    if shared_strings_path and shared_strings_path not in archive_names:
        raise KnowledgeError("invalid_xlsx", "XLSX 共享字符串表不存在。")
    return sheet_path, shared_strings_path, tuple(worksheet_paths)


def _office_document_path(
    relationships: ElementTree.Element, archive_names: Sequence[str]
) -> str:
    matches = []
    for relationship in relationships.iter():
        if _local_name(relationship.tag) != "Relationship":
            continue
        _validate_relationship(relationship)
        if str(relationship.attrib.get("Type", "")).endswith("/officeDocument"):
            matches.append(
                _resolve_part_path("", relationship.attrib.get("Target", ""))
            )
    if len(matches) != 1 or matches[0] not in archive_names:
        raise KnowledgeError("invalid_xlsx", "XLSX 主工作簿关系无效。")
    return matches[0]


def _relationship_part_path(source_part: str) -> str:
    parent = posixpath.dirname(source_part)
    name = posixpath.basename(source_part)
    return posixpath.join(parent, "_rels", name + ".rels")


def _resolve_part_path(base_part: str, target: str) -> str:
    clean_target = str(target or "")
    parsed_target = urlsplit(clean_target)
    if (
        not clean_target
        or "\\" in clean_target
        or _WINDOWS_ABSOLUTE_RE.match(clean_target)
        or parsed_target.scheme
        or parsed_target.netloc
    ):
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的内部关系。")
    if ".." in PurePosixPath(clean_target).parts:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的内部关系。")
    if clean_target.startswith("/"):
        candidate = clean_target.lstrip("/")
    else:
        candidate = posixpath.join(posixpath.dirname(base_part), clean_target)
    normalized = posixpath.normpath(candidate)
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的内部关系。")
    return normalized


def _parse_shared_strings(content: bytes) -> List[str]:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件包含不安全的 XML 声明。")
    values = []
    path = []
    element_count = 0
    item_count = 0
    current_parts = None
    root_element = None
    try:
        for event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("start", "end")
        ):
            element_name = _local_name(element.tag)
            if event == "start":
                path.append(element_name)
                element_count += 1
                if root_element is None:
                    root_element = element
                    if element_name != "sst":
                        raise KnowledgeError(
                            "invalid_xlsx", "XLSX 共享字符串表根节点无效。"
                        )
                if (
                    element_count > MAX_XLSX_SHARED_STRING_ELEMENTS
                    or len(path) > MAX_XLSX_SHARED_STRING_DEPTH
                ):
                    raise KnowledgeError(
                        "unsafe_xlsx", "XLSX 共享字符串 XML 结构超过安全预算。"
                    )
                if element_name == "si":
                    if len(path) != 2 or current_parts is not None:
                        raise KnowledgeError(
                            "invalid_xlsx", "XLSX 共享字符串条目结构无效。"
                        )
                    item_count += 1
                    if item_count > MAX_XLSX_SHARED_STRING_ITEMS:
                        raise KnowledgeError(
                            "unsafe_xlsx", "XLSX 共享字符串条目超过模板预算。"
                        )
                    current_parts = []
                continue

            if element_name == "t" and current_parts is not None:
                if (
                    len(path) >= 2
                    and path[-2] == "si"
                    or len(path) >= 3
                    and path[-2] == "r"
                    and path[-3] == "si"
                ):
                    current_parts.append(element.text or "")
            if element_name == "si":
                values.append("".join(current_parts or []))
                current_parts = None

            is_root_child = len(path) == 2
            element.clear()
            if is_root_child and root_element is not None:
                root_element.clear()
            path.pop()
    except ElementTree.ParseError:
        raise KnowledgeError("invalid_xlsx", "XLSX 共享字符串 XML 无效。")
    return values


def _parse_worksheet(
    root: ElementTree.Element, shared_strings: Sequence[str]
) -> List[Dict[str, str]]:
    _validate_worksheet_safety(root)
    sheet_data = next(
        (element for element in root.iter() if _local_name(element.tag) == "sheetData"),
        None,
    )
    if sheet_data is None:
        raise KnowledgeError("invalid_xlsx", "XLSX 工作表缺少数据区域。")

    parsed_rows = []
    for fallback_row_number, row in enumerate(sheet_data, start=1):
        if _local_name(row.tag) != "row":
            continue
        raw_row_number = str(row.attrib.get("r", fallback_row_number))
        if (
            len(raw_row_number) > MAX_XLSX_ROW_DIGITS
            or not _NON_NEGATIVE_INTEGER_RE.fullmatch(raw_row_number)
        ):
            raise KnowledgeError("unsafe_xlsx", "XLSX 工作表行号超过安全预算。")
        row_number = int(raw_row_number)
        if row_number < 1 or row_number > MAX_XLSX_ROW_NUMBER:
            raise KnowledgeError("unsafe_xlsx", "XLSX 工作表行号超过安全预算。")
        values_by_column = {}
        for cell in row:
            if _local_name(cell.tag) != "c":
                continue
            reference = cell.attrib.get("r", "")
            if not reference or len(reference) > MAX_XLSX_CELL_REFERENCE_CHARS:
                raise KnowledgeError("unsafe_xlsx", "XLSX 单元格引用超过安全预算。")
            match = _CELL_REFERENCE_RE.match(reference)
            if match is None:
                raise KnowledgeError("invalid_xlsx", "XLSX 单元格引用无效。")
            column_name = match.group(1)
            row_digits = match.group(2)
            if (
                len(column_name) > MAX_XLSX_COLUMN_LETTERS
                or len(row_digits) > MAX_XLSX_ROW_DIGITS
            ):
                raise KnowledgeError("unsafe_xlsx", "XLSX 单元格引用超过安全预算。")
            column_index = _excel_column_index(column_name)
            reference_row = int(row_digits)
            if (
                column_index > len(IMPORT_COLUMNS)
                or reference_row > MAX_XLSX_ROW_NUMBER
            ):
                raise KnowledgeError("unsafe_xlsx", "XLSX 单元格引用超过模板范围。")
            if column_index in values_by_column:
                raise KnowledgeError("invalid_xlsx", "XLSX 工作表包含重复单元格。")
            values_by_column[column_index] = _xlsx_cell_text(cell, shared_strings)
        if not values_by_column or not any(value.strip() for value in values_by_column.values()):
            continue
        values = [values_by_column.get(index, "").strip() for index in range(1, len(IMPORT_COLUMNS) + 1)]
        _validate_cell_lengths(values, row_number)
        parsed_rows.append((row_number, values))

    if not parsed_rows or tuple(parsed_rows[0][1]) != IMPORT_COLUMNS:
        raise KnowledgeError("invalid_import_headers", "导入文件表头与标准模板不一致。")
    result = [
        _ImportRow(dict(zip(IMPORT_COLUMNS, values)), row_number)
        for row_number, values in parsed_rows[1:]
    ]
    _validate_row_count(result)
    return result


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: Sequence[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        inline_string = next(
            (element for element in cell if _local_name(element.tag) == "is"),
            None,
        )
        return "" if inline_string is None else _rich_text_value(inline_string)
    value_element = next(
        (element for element in cell if _local_name(element.tag) == "v"), None
    )
    value = "" if value_element is None else str(value_element.text or "")
    if cell_type == "s":
        if (
            not value
            or len(value) > MAX_XLSX_SHARED_STRING_INDEX_DIGITS
            or not _NON_NEGATIVE_INTEGER_RE.fullmatch(value)
        ):
            raise KnowledgeError("unsafe_xlsx", "XLSX 共享字符串索引超过安全预算。")
        index = int(value)
        if index >= len(shared_strings):
            raise KnowledgeError("invalid_xlsx", "XLSX 共享字符串引用无效。")
        return shared_strings[index]
    return value


def _rich_text_value(container: ElementTree.Element) -> str:
    values = []
    for child in container:
        child_name = _local_name(child.tag)
        if child_name == "t":
            values.append(child.text or "")
        elif child_name == "r":
            values.extend(
                run_child.text or ""
                for run_child in child
                if _local_name(run_child.tag) == "t"
            )
    return "".join(values)


def _map_row(raw_row: Dict[str, str]) -> Dict[str, object]:
    row = {
        column: str(raw_row.get(column, "") or "").strip()
        for column in IMPORT_COLUMNS
    }
    item_type = _mapped_value(row["类型"], _TYPE_MAP, "条目类型必须为“术语”或“风格”。")
    scope = _mapped_value(row["适用范围"], _SCOPE_MAP, "适用范围无效。")
    priority = _mapped_value(row["优先级"], _PRIORITY_MAP, "优先级必须为“高”“中”或“低”。")
    enabled = _boolean_value(row["启用"], "启用必须填写“是”或“否”。")
    name = _required(row["名称"], "名称不能为空。")
    primary_text = _required(row["标准写法/规则"], "标准写法或规则正文不能为空。")
    keywords = _split_list(row["关键词"])

    if item_type == "term":
        if scope != "global":
            raise _RowValidationError("invalid_knowledge_scope", "术语仅允许使用“全局”范围。")
        always_apply = _boolean_value(
            row["始终应用"], "始终应用必须填写“是”或“否”。"
        )
        if always_apply:
            raise _RowValidationError("invalid_import_value", "术语的“始终应用”必须为“否”。")
        if row["推荐示例"] or row["不推荐示例"]:
            raise _RowValidationError("invalid_import_value", "术语行不得填写推荐示例或不推荐示例。")
        aliases, forbidden = _split_term_variants(row["别名/禁用写法"])
        item = {
            "type": "term",
            "scope": "global",
            "category": name,
            "preferredText": primary_text,
            "aliases": aliases,
            "forbiddenVariants": forbidden,
            "definition": "",
            "contextKeywords": keywords,
            "priority": priority,
            "enabled": enabled,
            "note": row["备注"],
        }
        tokens = [primary_text] + aliases + forbidden
        normalized = [normalize_key(value) for value in tokens]
        if len(normalized) != len(set(normalized)):
            raise _RowValidationError(
                "duplicate_import_row", "同一术语的标准写法、别名和禁用写法不能重复。"
            )
        return item

    if row["别名/禁用写法"]:
        raise _RowValidationError("invalid_import_value", "风格行不得填写别名或禁用写法。")
    always_apply = _boolean_value(
        row["始终应用"], "始终应用必须填写“是”或“否”。"
    )
    return {
        "type": "style",
        "scope": scope,
        "name": name,
        "ruleText": primary_text,
        "positiveExample": row["推荐示例"],
        "negativeExample": row["不推荐示例"],
        "contextKeywords": keywords,
        "alwaysApply": always_apply,
        "priority": priority,
        "enabled": enabled,
        "note": row["备注"],
    }


def _mapped_value(value: str, mapping: Dict[str, object], message: str):
    mapped = mapping.get(value)
    if mapped is None:
        raise _RowValidationError("invalid_import_value", message)
    return mapped


def _boolean_value(value: str, message: str) -> bool:
    mapped = _BOOLEAN_MAP.get(value)
    if mapped is None:
        raise _RowValidationError("invalid_import_value", message)
    return mapped


def _required(value: str, message: str) -> str:
    if not value:
        raise _RowValidationError("missing_import_value", message)
    return value


def _split_list(value: str) -> List[str]:
    return _deduplicate(_split_escaped_list(value))


def _split_term_variants(value: str) -> Tuple[List[str], List[str]]:
    aliases = []
    forbidden = []
    for clean in _split_escaped_list(value):
        forbidden_prefix = next(
            (prefix for prefix in ("禁用:", "禁用：") if clean.startswith(prefix)),
            "",
        )
        alias_prefix = next(
            (prefix for prefix in ("别名:", "别名：") if clean.startswith(prefix)),
            "",
        )
        if forbidden_prefix:
            target = clean[len(forbidden_prefix) :].strip()
            if not target:
                raise _RowValidationError("invalid_import_value", "禁用写法不能为空。")
            forbidden.append(target)
        elif alias_prefix:
            target = clean[len(alias_prefix) :].strip()
            if not target:
                raise _RowValidationError("invalid_import_value", "别名不能为空。")
            aliases.append(target)
        else:
            aliases.append(clean)
    return _deduplicate(aliases), _deduplicate(forbidden)


def _split_escaped_list(value: str) -> List[str]:
    result = []
    current = []
    source = str(value or "")
    index = 0
    while index < len(source):
        character = source[index]
        if character == "\\":
            if index + 1 >= len(source):
                raise _RowValidationError(
                    "invalid_import_escape", "列表字段存在悬空转义符。"
                )
            escaped = source[index + 1]
            if escaped not in (LIST_SEPARATOR, "\\"):
                raise _RowValidationError(
                    "invalid_import_escape",
                    "列表字段仅支持 \\| 和 \\\\ 两种转义写法。",
                )
            current.append(escaped)
            index += 2
            continue
        if character == LIST_SEPARATOR:
            clean = "".join(current).strip()
            if clean:
                result.append(clean)
            current = []
        else:
            current.append(character)
        index += 1
    clean = "".join(current).strip()
    if clean:
        result.append(clean)
    return result


def _validate_relationship(relationship: ElementTree.Element) -> None:
    target_mode = str(relationship.attrib.get("TargetMode", "")).casefold()
    relationship_type = str(relationship.attrib.get("Type", ""))
    target = str(relationship.attrib.get("Target", ""))
    parsed_target = urlsplit(target)
    if (
        target_mode == "external"
        or relationship_type.casefold().endswith("/externallink")
        or not target
        or "\\" in target
        or _WINDOWS_ABSOLUTE_RE.match(target)
        or parsed_target.scheme
        or parsed_target.netloc
    ):
        raise KnowledgeError("unsafe_xlsx", "XLSX 文件不得包含外部或不安全的关系。")


def _validate_worksheet_safety(root: ElementTree.Element) -> None:
    if any(
        _local_name(element.tag) in ("f", "mergeCells", "mergeCell")
        for element in root.iter()
    ):
        raise KnowledgeError("unsafe_xlsx", "XLSX 模板不得包含公式或合并单元格。")


def _deduplicate(values: Sequence[str]) -> List[str]:
    result = []
    seen = set()
    for value in values:
        key = normalize_key(value)
        if key and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _term_tokens(item: Dict[str, object]) -> set:
    values = (
        [item["preferredText"]]
        + list(item["aliases"])
        + list(item["forbiddenVariants"])
    )
    return {normalize_key(value) for value in values if normalize_key(value)}


def _excel_column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _excel_column_index(name: str) -> int:
    result = 0
    for character in name.upper():
        result = result * 26 + (ord(character) - 64)
    return result


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]
