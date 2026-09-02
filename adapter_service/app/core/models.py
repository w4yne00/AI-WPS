from typing import Any, Dict, List, Literal, Optional
import re

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    root_validator,
    validator,
)

from app.core.outline_level import normalize_heading_level, normalize_outline_level


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return default


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _safe_bool(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "-1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


class Paragraph(BaseModel):
    index: int = 0
    text: str = ""
    style_name: Optional[str] = Field(default=None, alias="styleName")
    font_name: Optional[str] = Field(default=None, alias="fontName")
    font_size: Optional[float] = Field(default=None, alias="fontSize")
    alignment: Optional[str] = None
    outline_level: Optional[int] = Field(default=None, alias="outlineLevel")
    line_spacing: Optional[float] = Field(default=None, alias="lineSpacing")
    first_line_indent: Optional[float] = Field(default=None, alias="firstLineIndent")
    space_before: Optional[float] = Field(default=None, alias="spaceBefore")
    space_after: Optional[float] = Field(default=None, alias="spaceAfter")
    left_indent: Optional[float] = Field(default=None, alias="leftIndent")
    right_indent: Optional[float] = Field(default=None, alias="rightIndent")
    italic: Optional[bool] = None
    underline: Optional[Any] = None
    bold: Optional[bool] = None

    @validator("text", pre=True, always=True)
    def coerce_required_text(cls, value):
        return _safe_str(value)

    @validator("style_name", "font_name", "alignment", pre=True)
    def coerce_optional_string(cls, value):
        return _safe_str(value) if value is not None else None

    @validator(
        "font_size",
        "line_spacing",
        "first_line_indent",
        "space_before",
        "space_after",
        "left_indent",
        "right_indent",
        pre=True,
    )
    def coerce_optional_float(cls, value):
        return _safe_float(value)

    @validator("index", pre=True, always=True)
    def coerce_index(cls, value):
        return _safe_int(value) or 0

    @validator("outline_level", pre=True, always=True)
    def coerce_outline_level(cls, value):
        return normalize_outline_level(value)

    @validator("bold", "italic", pre=True)
    def coerce_optional_bool(cls, value):
        return _safe_bool(value)


class Heading(BaseModel):
    level: Optional[int] = None
    text: str = ""
    paragraph_index: Optional[int] = Field(default=None, alias="paragraphIndex")

    @validator("level", pre=True, always=True)
    def coerce_heading_level(cls, value):
        return normalize_heading_level(value)

    @validator("paragraph_index", pre=True)
    def coerce_paragraph_index(cls, value):
        return _safe_int(value)

    @validator("text", pre=True, always=True)
    def coerce_heading_text(cls, value):
        return _safe_str(value)


class DocumentContent(BaseModel):
    plain_text: str = Field(default="", alias="plainText")
    paragraphs: List[Paragraph] = Field(default_factory=list)
    headings: List[Heading] = Field(default_factory=list)
    document_structure: Dict[str, Any] = Field(default_factory=dict, alias="documentStructure")

    @validator("plain_text", pre=True, always=True)
    def coerce_plain_text(cls, value):
        return _safe_str(value)

    @validator("paragraphs", "headings", pre=True, always=True)
    def coerce_list(cls, value):
        return value if isinstance(value, list) else []

    @validator("document_structure", pre=True, always=True)
    def coerce_document_structure(cls, value):
        return value if isinstance(value, dict) else {}


class RequestOptions(BaseModel):
    template_id: Optional[str] = Field(default=None, alias="templateId")
    track_changes: bool = Field(default=True, alias="trackChanges")
    user_instruction: str = Field(default="", alias="userInstruction")
    rewrite_style: str = Field(default="default", alias="rewriteStyle")
    focus_point: str = Field(default="default", alias="focusPoint")
    length_mode: str = Field(default="default", alias="lengthMode")
    rewrite_action: str = Field(default="rewrite", alias="rewriteAction")
    technical_document_type: str = Field(default="technical_solution", alias="technicalDocumentType")
    technical_review_prompt: str = Field(default="", alias="technicalReviewPrompt")
    imitation_requirement: str = Field(default="", alias="imitationRequirement")
    imitation_reference_material: str = Field(default="", alias="imitationReferenceMaterial")


class WordDocumentRequest(BaseModel):
    document_id: str = Field(default="unnamed.docx", alias="documentId")
    scene: Literal["word"] = "word"
    selection_mode: Literal["document", "selection"] = Field(default="document", alias="selectionMode")
    writing_policy_scene: Literal[
        "auto", "yangqi", "cybersecurity", "official", "disabled"
    ] = Field(default="auto", alias="writingPolicyScene")
    client_job_id: str = Field(default="", alias="clientJobId")
    content: DocumentContent = Field(default_factory=DocumentContent)
    options: RequestOptions = Field(default_factory=RequestOptions)

    @validator("document_id", pre=True, always=True)
    def coerce_document_id(cls, value):
        return _safe_str(value, "unnamed.docx") or "unnamed.docx"

    @validator("scene", pre=True, always=True)
    def coerce_scene(cls, value):
        return "word"

    @validator("selection_mode", pre=True, always=True)
    def coerce_selection_mode(cls, value):
        return value if value in {"document", "selection"} else "document"

    @validator("client_job_id", pre=True, always=True)
    def coerce_client_job_id(cls, value):
        return _safe_str(value)


class ExcelAnalysisScope(BaseModel):
    scope_type: Literal["selection", "usedRange"] = Field(default="selection", alias="type")
    sheet_name: str = Field(default="", alias="sheetName")
    address: str = ""

    @validator("scope_type", pre=True, always=True)
    def coerce_scope_type(cls, value):
        return value if value in {"selection", "usedRange"} else "selection"

    @validator("sheet_name", "address", pre=True, always=True)
    def coerce_scope_text(cls, value):
        return _safe_str(value)


class ExcelAnalysisTable(BaseModel):
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    row_count: int = Field(default=0, alias="rowCount")
    column_count: int = Field(default=0, alias="columnCount")
    truncated: bool = False

    @validator("headers", pre=True, always=True)
    def coerce_headers(cls, value):
        if not isinstance(value, list):
            return []
        return [_safe_str(item) for item in value]

    @validator("rows", pre=True, always=True)
    def coerce_rows(cls, value):
        if not isinstance(value, list):
            return []
        normalized = []
        for row in value:
            if isinstance(row, list):
                normalized.append([_safe_str(cell) for cell in row])
        return normalized

    @validator("row_count", "column_count", pre=True, always=True)
    def coerce_counts(cls, value):
        return _safe_int(value) or 0

    @validator("truncated", pre=True, always=True)
    def coerce_truncated(cls, value):
        return bool(_safe_bool(value))


class ExcelAnalysisOptions(BaseModel):
    analysis_requirement: str = Field(default="", alias="analysisRequirement")

    @validator("analysis_requirement", pre=True, always=True)
    def coerce_requirement(cls, value):
        return _safe_str(value)


class ExcelAnalysisRequest(BaseModel):
    workbook_id: str = Field(default="active-workbook", alias="workbookId")
    scene: Literal["excel"] = "excel"
    client_job_id: str = Field(default="", alias="clientJobId")
    scope: ExcelAnalysisScope = Field(default_factory=ExcelAnalysisScope)
    table: ExcelAnalysisTable = Field(default_factory=ExcelAnalysisTable)
    options: ExcelAnalysisOptions = Field(default_factory=ExcelAnalysisOptions)

    @validator("workbook_id", pre=True, always=True)
    def coerce_workbook_id(cls, value):
        return _safe_str(value, "active-workbook") or "active-workbook"

    @validator("scene", pre=True, always=True)
    def coerce_excel_scene(cls, value):
        return "excel"

    @validator("client_job_id", pre=True, always=True)
    def coerce_excel_client_job_id(cls, value):
        return _safe_str(value)


class ExcelRange(ExcelAnalysisTable):
    address: str = ""

    @validator("address", pre=True, always=True)
    def coerce_address(cls, value):
        return _safe_str(value)


class ExcelWorksheet(BaseModel):
    name: str = ""
    active_range: ExcelRange = Field(default_factory=ExcelRange, alias="activeRange")

    @validator("name", pre=True, always=True)
    def coerce_name(cls, value):
        return _safe_str(value)


class ExcelWorkbookContext(BaseModel):
    workbook_id: str = Field(default="active-workbook", alias="workbookId")
    worksheets: List[ExcelWorksheet] = Field(default_factory=list)

    @validator("workbook_id", pre=True, always=True)
    def coerce_context_workbook_id(cls, value):
        return _safe_str(value, "active-workbook") or "active-workbook"

    @validator("worksheets", pre=True, always=True)
    def coerce_worksheets(cls, value):
        return value if isinstance(value, list) else []


class ExcelStructuredReport(BaseModel):
    overview: str = ""
    findings: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)


class ExcelAnalysisResult(BaseModel):
    structured_report: ExcelStructuredReport = Field(default_factory=ExcelStructuredReport, alias="structuredReport")
    plain_text: str = Field(default="", alias="plainText")
    provider: str = "mock"


class ExcelAnalysisResponseData(ExcelAnalysisResult):
    pass


class ExcelFormulaCell(BaseModel):
    address: str = ""
    text: str = ""
    value_type: Literal[
        "blank", "text", "number", "boolean", "formula", "error", "unknown"
    ] = Field(default="unknown", alias="valueType")
    formula: str = ""

    @validator("address", "text", "formula", pre=True, always=True)
    def coerce_formula_cell_text(cls, value):
        return _safe_str(value)

    @validator("value_type", pre=True, always=True)
    def coerce_formula_cell_type(cls, value):
        supported = {
            "blank",
            "text",
            "number",
            "boolean",
            "formula",
            "error",
            "unknown",
        }
        return value if value in supported else "unknown"


class ExcelFormulaSelection(BaseModel):
    sheet_name: str = Field(default="", alias="sheetName")
    address: str = ""
    headers: List[str] = Field(default_factory=list)
    cells: List[List[ExcelFormulaCell]] = Field(default_factory=list)
    row_count: int = Field(default=0, alias="rowCount")
    column_count: int = Field(default=0, alias="columnCount")
    truncated: bool = False

    @validator("sheet_name", "address", pre=True, always=True)
    def coerce_formula_selection_text(cls, value):
        return _safe_str(value)

    @validator("headers", pre=True, always=True)
    def coerce_formula_headers(cls, value):
        if not isinstance(value, list):
            return []
        return [_safe_str(item) for item in value]

    @validator("cells", pre=True, always=True)
    def coerce_formula_cells(cls, value):
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, list)]

    @validator("row_count", "column_count", pre=True, always=True)
    def coerce_formula_counts(cls, value):
        return _safe_int(value) or 0

    @validator("truncated", pre=True, always=True)
    def coerce_formula_truncated(cls, value):
        return bool(_safe_bool(value))


class ExcelFormulaOptions(BaseModel):
    mode: Literal["generate", "explain"] = "generate"
    requirement: str = ""

    @validator("mode", pre=True, always=True)
    def coerce_formula_mode(cls, value):
        return value if value in {"generate", "explain"} else "generate"

    @validator("requirement", pre=True, always=True)
    def coerce_formula_requirement(cls, value):
        return _safe_str(value)


class ExcelFormulaAssistantRequest(BaseModel):
    workbook_id: str = Field(default="active-workbook", alias="workbookId")
    scene: Literal["excel"] = "excel"
    client_job_id: str = Field(default="", alias="clientJobId")
    selection: ExcelFormulaSelection = Field(default_factory=ExcelFormulaSelection)
    options: ExcelFormulaOptions = Field(default_factory=ExcelFormulaOptions)

    @validator("workbook_id", pre=True, always=True)
    def coerce_formula_workbook_id(cls, value):
        return _safe_str(value, "active-workbook") or "active-workbook"

    @validator("scene", pre=True, always=True)
    def coerce_formula_scene(cls, value):
        return "excel"

    @validator("client_job_id", pre=True, always=True)
    def coerce_formula_client_job_id(cls, value):
        return _safe_str(value)


class ExcelFormulaAssistantResult(BaseModel):
    mode: Literal["generate", "explain"] = "generate"
    original_formula: str = Field(default="", alias="originalFormula")
    primary_formula: str = Field(default="", alias="primaryFormula")
    alternative_formula: str = Field(default="", alias="alternativeFormula")
    suggested_target: str = Field(default="", alias="suggestedTarget")
    explanation: str = ""
    components: List[str] = Field(default_factory=list)
    reference_ranges: List[str] = Field(default_factory=list, alias="referenceRanges")
    issues: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    compatibility_notes: List[str] = Field(default_factory=list, alias="compatibilityNotes")
    local_check: Dict[str, Any] = Field(default_factory=dict, alias="localCheck")
    raw_final_result: str = Field(default="", alias="rawFinalResult")
    parse_diagnostic: str = Field(default="", alias="parseDiagnostic")
    copy_text: str = Field(default="", alias="copyText")
    provider: str = "mock"


class ExcelFormulaAssistantResponseData(ExcelFormulaAssistantResult):
    pass


class _StrictExcelSmartFillModel(BaseModel):
    class Config:
        allow_population_by_field_name = True
        extra = "forbid"


class ExcelSmartFillTargetItem(_StrictExcelSmartFillModel):
    item_id: StrictStr = Field(alias="itemId", min_length=1, max_length=128)
    address: StrictStr = Field(min_length=1, max_length=128)
    row: StrictInt = Field(ge=1, le=1048576)
    column: StrictInt = Field(ge=1, le=16384)
    original_value: StrictStr = Field(default="", alias="originalValue", max_length=2000)
    original_value_type: Literal[
        "blank", "text", "number", "boolean", "error", "formula", "unknown"
    ] = Field(default="blank", alias="originalValueType")
    original_formula: StrictStr = Field(default="", alias="originalFormula", max_length=2000)
    is_formula: StrictBool = Field(default=False, alias="isFormula")
    is_merged: StrictBool = Field(default=False, alias="isMerged")
    is_protected: StrictBool = Field(default=False, alias="isProtected")
    is_hidden: StrictBool = Field(default=False, alias="isHidden")
    snapshot_hash: StrictStr = Field(default="", alias="snapshotHash", max_length=64)

    @validator("item_id", "address", pre=True)
    def validate_target_item_text(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("target item text must be a non-empty string")
        return value.strip()

    @validator("snapshot_hash", pre=True)
    def validate_snapshot_hash(cls, value):
        if not isinstance(value, str):
            raise ValueError("snapshot hash must be a string")
        normalized = value.strip().lower()
        if normalized and not all(char in "0123456789abcdef" for char in normalized):
            raise ValueError("snapshot hash must be hexadecimal")
        return normalized


class ExcelSmartFillTarget(_StrictExcelSmartFillModel):
    sheet_name: StrictStr = Field(alias="sheetName", min_length=1, max_length=255)
    address: StrictStr = Field(min_length=1, max_length=128)
    column_header: StrictStr = Field(default="", alias="columnHeader", max_length=2000)
    row_context: List[StrictStr] = Field(
        default_factory=list, alias="rowContext", max_items=50
    )
    items: List[ExcelSmartFillTargetItem] = Field(
        min_items=1, max_items=500
    )

    @validator("sheet_name", "address", pre=True)
    def validate_target_text(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("target text must be a non-empty string")
        return value.strip()

    @validator("column_header", pre=True)
    def validate_target_column_header(cls, value):
        if not isinstance(value, str):
            raise ValueError("target column header must be a string")
        return value.strip()

    @validator("row_context", pre=True)
    def validate_target_row_context(cls, value):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("target row context must contain strings")
        return value

    @validator("items")
    def validate_unique_target_items(cls, value):
        item_ids = [item.item_id for item in value]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("target item ids must be unique")
        return value


class ExcelSmartFillSource(_StrictExcelSmartFillModel):
    sheet_name: StrictStr = Field(alias="sheetName", min_length=1, max_length=255)
    address: StrictStr = Field(default="", max_length=128)
    snapshot_hash: StrictStr = Field(default="", alias="snapshotHash", max_length=64)
    headers: List[StrictStr] = Field(default_factory=list, max_items=50)
    rows: List[List[StrictStr]] = Field(default_factory=list, max_items=500)
    row_count: StrictInt = Field(default=0, alias="rowCount", ge=0, le=1048576)
    column_count: StrictInt = Field(default=0, alias="columnCount", ge=0, le=16384)
    truncated: StrictBool = False

    @validator("sheet_name", pre=True)
    def validate_source_sheet_name(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("source sheet name must be a non-empty string")
        return value.strip()

    @validator("address", pre=True)
    def validate_source_address(cls, value):
        if not isinstance(value, str):
            raise ValueError("source address must be a string")
        return value.strip()

    @validator("snapshot_hash", pre=True)
    def validate_source_snapshot_hash(cls, value):
        if not isinstance(value, str):
            raise ValueError("source snapshot hash must be a string")
        normalized = value.strip().lower()
        if normalized and not all(char in "0123456789abcdef" for char in normalized):
            raise ValueError("source snapshot hash must be hexadecimal")
        return normalized

    @validator("headers", pre=True)
    def validate_source_headers(cls, value):
        if not isinstance(value, list):
            raise ValueError("source headers must be a list")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("source headers must contain strings")
        return value

    @validator("rows", pre=True)
    def validate_source_rows(cls, value):
        if not isinstance(value, list):
            raise ValueError("source rows must be a list")
        if any(
            not isinstance(row, list) or any(not isinstance(cell, str) for cell in row)
            for row in value
        ):
            raise ValueError("source rows must contain string arrays")
        if any(len(row) > 50 for row in value):
            raise ValueError("source rows may contain at most 50 columns")
        return value

    @root_validator(skip_on_failure=True)
    def validate_source_matrix(cls, values):
        rows = values.get("rows") or []
        headers = values.get("headers") or []
        row_count = values.get("row_count")
        column_count = values.get("column_count")
        address = values.get("address") or ""
        if row_count != len(rows):
            raise ValueError("source rowCount must equal the number of data rows")
        if column_count != len(headers):
            raise ValueError("source columnCount must equal the number of headers")
        if any(len(row) != column_count for row in rows):
            raise ValueError("source rows must have consistent width")
        if _parse_smart_fill_a1_rectangle(address) is None:
            raise ValueError("source address must be a contiguous A1 rectangle")
        return values


_SMART_FILL_ITEM_ID = re.compile(r"^sf_[0-9a-f]{32}$")
_SMART_FILL_A1_CELL = re.compile(r"^\$?([A-Za-z]+)\$?([0-9]+)$")


def _parse_smart_fill_a1_rectangle(address):
    raw = str(address or "").strip()
    if "!" in raw:
        raw = raw.split("!")[-1]
    parts = [part.strip() for part in raw.split(":") if part.strip()]
    if not parts or len(parts) > 2:
        return None
    start = _SMART_FILL_A1_CELL.match(parts[0])
    if not start:
        return None
    end = _SMART_FILL_A1_CELL.match(parts[-1])
    if not end:
        return None
    return (
        start.group(1).upper(),
        int(start.group(2)),
        end.group(1).upper(),
        int(end.group(2)),
    )


class ExcelSmartFillItem(_StrictExcelSmartFillModel):
    item_id: StrictStr = Field(alias="itemId", min_length=8, max_length=128)
    source_row_index: StrictInt = Field(alias="sourceRowIndex", ge=1, le=500)
    source_row_label: StrictStr = Field(default="", alias="sourceRowLabel", max_length=128)

    @validator("item_id", pre=True)
    def validate_fill_item_id(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("item id must be a non-empty string")
        text = value.strip()
        if not _SMART_FILL_ITEM_ID.match(text):
            raise ValueError("item id must be an unguessable sf_ hex token")
        return text

    @validator("source_row_label", pre=True)
    def validate_source_row_label(cls, value):
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("source row label must be a string")
        return value.strip()


class ExcelSmartFillRequest(_StrictExcelSmartFillModel):
    workbook_id: StrictStr = Field(
        default="active-workbook", alias="workbookId", min_length=1, max_length=128
    )
    scene: Literal["excel"] = "excel"
    client_job_id: StrictStr = Field(default="", alias="clientJobId", max_length=128)
    items: List[ExcelSmartFillItem] = Field(min_items=1, max_items=500)
    source: ExcelSmartFillSource
    user_instruction: StrictStr = Field(
        alias="userInstruction", min_length=1, max_length=4000
    )

    @validator("workbook_id", pre=True)
    def validate_smart_fill_workbook_id(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("workbook id must be a non-empty string")
        return value.strip()

    @validator("client_job_id", pre=True)
    def validate_smart_fill_client_job_id(cls, value):
        if not isinstance(value, str):
            raise ValueError("smart fill text fields must be strings")
        return value

    @validator("user_instruction", pre=True)
    def validate_smart_fill_instruction(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("user instruction is required")
        return value

    @validator("items")
    def validate_unique_fill_items(cls, value):
        item_ids = [item.item_id for item in value]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item ids must be unique")
        return value

    @root_validator(skip_on_failure=True)
    def validate_smart_fill_text_budget(cls, values):
        source = values.get("source")
        items = values.get("items") or []
        user_instruction = values.get("user_instruction", "")
        total_text_length = len(user_instruction)
        if source is not None:
            total_text_length += sum(len(item) for item in source.headers)
            total_text_length += sum(
                len(cell) for row in source.rows for cell in row
            )
            if len(items) != len(source.rows):
                raise ValueError("fill items must match source data rows")
        if total_text_length > 200000:
            raise ValueError("smart fill text exceeds 200000 characters")
        return values


class PptSlideInput(BaseModel):
    index: int = 1
    title: str = ""
    subtitle: str = ""
    text_blocks: List[str] = Field(default_factory=list, alias="textBlocks")
    previous_title: str = Field(default="", alias="previousTitle")
    next_title: str = Field(default="", alias="nextTitle")
    truncated: bool = False

    @validator("index", pre=True, always=True)
    def coerce_index(cls, value):
        return _safe_int(value) or 1

    @validator("title", "subtitle", "previous_title", "next_title", pre=True, always=True)
    def coerce_slide_text(cls, value):
        return _safe_str(value)

    @validator("text_blocks", pre=True, always=True)
    def coerce_text_blocks(cls, value):
        if not isinstance(value, list):
            return []
        return [_safe_str(item) for item in value]

    @validator("truncated", pre=True, always=True)
    def coerce_slide_truncated(cls, value):
        return bool(_safe_bool(value))


class PptDocumentFileUploadRequest(BaseModel):
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(default="", alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    content_base64: str = Field(alias="contentBase64")

    @validator("file_name", "mime_type", "content_base64", pre=True, always=True)
    def coerce_document_upload_text(cls, value):
        return _safe_str(value)

    @validator("size_bytes", pre=True, always=True)
    def coerce_document_upload_size(cls, value):
        return _safe_int(value) or 0


class PptDocumentSlide(BaseModel):
    index: int
    role: str = ""
    title: str = ""
    subtitle: str = ""
    bullets: List[str] = Field(default_factory=list)
    conclusion: str = ""
    layout_suggestion: str = Field(default="", alias="layoutSuggestion")
    visual_suggestion: str = Field(default="", alias="visualSuggestion")

    @validator("index", pre=True, always=True)
    def coerce_document_slide_index(cls, value):
        return _safe_int(value) or 1

    @validator(
        "role",
        "title",
        "subtitle",
        "conclusion",
        "layout_suggestion",
        "visual_suggestion",
        pre=True,
        always=True,
    )
    def coerce_document_slide_text(cls, value):
        return _safe_str(value)

    @validator("bullets", pre=True, always=True)
    def coerce_document_slide_bullets(cls, value):
        if not isinstance(value, list):
            return []
        return [_safe_str(item) for item in value]


class PptSlideAssistantRequest(BaseModel):
    presentation_id: str = Field(default="active-presentation", alias="presentationId")
    scene: Literal["ppt"] = "ppt"
    source_mode: Literal["slide", "document"] = Field(default="slide", alias="sourceMode")
    client_job_id: str = Field(default="", alias="clientJobId")
    slide: Optional[PptSlideInput] = None
    file_token: str = Field(default="", alias="fileToken")
    requested_slide_count: int = Field(default=10, alias="requestedSlideCount")
    user_instruction: str = Field(default="", alias="userInstruction")

    @validator("presentation_id", pre=True, always=True)
    def coerce_presentation_id(cls, value):
        return _safe_str(value, "active-presentation") or "active-presentation"

    @validator("scene", pre=True, always=True)
    def coerce_ppt_scene(cls, value):
        return "ppt"

    @validator("source_mode", pre=True, always=True)
    def coerce_ppt_source_mode(cls, value):
        normalized = _safe_str(value, "slide").strip().lower()
        return normalized if normalized in {"slide", "document"} else "slide"

    @validator("client_job_id", "file_token", "user_instruction", pre=True, always=True)
    def coerce_ppt_request_text(cls, value):
        return _safe_str(value)

    @validator("slide", pre=True, always=True)
    def preserve_legacy_default_slide(cls, value, values):
        if values.get("source_mode") == "document":
            return value
        return value if value is not None else PptSlideInput()

    @validator("requested_slide_count", pre=True, always=True)
    def coerce_requested_slide_count(cls, value):
        count = _safe_int(value)
        return count if count in {5, 8, 10, 12, 15} else 10


class PptSlideAssistantResponseData(BaseModel):
    result_type: Literal["slide", "document"] = Field(default="slide", alias="resultType")
    mode_used: Optional[Literal["generate", "optimize"]] = Field(default=None, alias="modeUsed")
    suggested_title: str = Field(default="", alias="suggestedTitle")
    bullets: List[str] = Field(default_factory=list)
    conclusion: str = ""
    deck_title: str = Field(default="", alias="deckTitle")
    document_summary: str = Field(default="", alias="documentSummary")
    recommended_slide_count: Optional[int] = Field(default=None, alias="recommendedSlideCount")
    slides: List[PptDocumentSlide] = Field(default_factory=list)
    global_style_advice: str = Field(default="", alias="globalStyleAdvice")
    plain_text: str = Field(default="", alias="plainText")
    raw_answer: Optional[str] = Field(default=None, alias="rawAnswer")
    parse_fallback_reason: Optional[str] = Field(default=None, alias="parseFallbackReason")
    provider: str = "mock"


class PptStructureReviewScope(BaseModel):
    total_slides: int = Field(default=0, alias="totalSlides")
    start_slide: int = Field(default=1, alias="startSlide")
    end_slide: int = Field(default=0, alias="endSlide")

    @validator("total_slides", "start_slide", "end_slide", pre=True, always=True)
    def coerce_structure_scope_integer(cls, value):
        numeric = _safe_float(value)
        if (
            numeric is None
            or numeric != numeric
            or numeric in (float("inf"), float("-inf"))
        ):
            return 0
        integer = int(numeric)
        return integer if numeric == integer else 0


class PptStructureReviewSlide(BaseModel):
    index: int = 1
    title: str = ""
    subtitle: str = ""
    body_fallback: str = Field(default="", alias="bodyFallback")
    body_fallback_omitted: bool = Field(default=False, alias="bodyFallbackOmitted")
    shape_names: List[str] = Field(default_factory=list, alias="shapeNames")

    @validator("index", pre=True, always=True)
    def coerce_structure_slide_index(cls, value):
        return _safe_int(value) or 1

    @validator("title", "subtitle", "body_fallback", pre=True, always=True)
    def coerce_structure_slide_text(cls, value):
        return _safe_str(value)

    @validator("body_fallback_omitted", pre=True, always=True)
    def coerce_structure_fallback_omitted(cls, value):
        return bool(_safe_bool(value))

    @validator("shape_names", pre=True, always=True)
    def coerce_structure_shape_names(cls, value):
        if not isinstance(value, list):
            return []
        names = []
        for item in value:
            text = _safe_str(item).strip()
            if text and text not in names:
                names.append(text)
        return names


class PptStructureReviewRequest(BaseModel):
    presentation_id: str = Field(default="active-presentation", alias="presentationId")
    scene: Literal["ppt"] = "ppt"
    client_job_id: str = Field(default="", alias="clientJobId")
    scope: PptStructureReviewScope = Field(default_factory=PptStructureReviewScope)
    slides: List[PptStructureReviewSlide] = Field(default_factory=list)

    @validator("presentation_id", pre=True, always=True)
    def coerce_structure_presentation_id(cls, value):
        return _safe_str(value, "active-presentation") or "active-presentation"

    @validator("scene", pre=True, always=True)
    def coerce_structure_scene(cls, value):
        return "ppt"

    @validator("client_job_id", pre=True, always=True)
    def coerce_structure_client_job_id(cls, value):
        return _safe_str(value)

    @validator("slides", pre=True, always=True)
    def coerce_structure_slides(cls, value):
        return value if isinstance(value, list) else []


class PptStructureReviewResponseData(BaseModel):
    reviewed_range: Dict[str, Any] = Field(default_factory=dict, alias="reviewedRange")
    overall_storyline: str = Field(default="", alias="overallStoryline")
    inferred_chapters: List[Dict[str, Any]] = Field(default_factory=list, alias="inferredChapters")
    high_priority_issues: List[Dict[str, Any]] = Field(default_factory=list, alias="highPriorityIssues")
    general_suggestions: List[Dict[str, Any]] = Field(default_factory=list, alias="generalSuggestions")
    slide_recommendations: List[Dict[str, Any]] = Field(default_factory=list, alias="slideRecommendations")
    recommended_outline: List[Dict[str, Any]] = Field(default_factory=list, alias="recommendedOutline")
    review_conclusion: str = Field(default="", alias="reviewConclusion")
    outline_text: str = Field(default="", alias="outlineText")
    plain_text: str = Field(default="", alias="plainText")
    page_roles: List[Dict[str, Any]] = Field(default_factory=list, alias="pageRoles")
    raw_answer: Optional[str] = Field(default=None, alias="rawAnswer")
    parse_fallback_reason: Optional[str] = Field(default=None, alias="parseFallbackReason")
    provider: str = "mock"


class WritingPolicyUsageItem(BaseModel):
    id: str
    type: Literal["term", "style", "anti_template"]
    name: str


class WritingPolicyConflict(BaseModel):
    name: str
    winner_id: str = Field(alias="winnerId")
    item_ids: List[str] = Field(default_factory=list, alias="itemIds")


class WritingPolicyUsage(BaseModel):
    applied: bool
    degraded: bool = False
    degraded_reason: str = Field(default="", alias="degradedReason")
    requested_scene: Optional[str] = Field(default=None, alias="requestedScene")
    scene: Optional[str] = None
    scene_label: str = Field(default="", alias="sceneLabel")
    auto_fallback: bool = Field(default=False, alias="autoFallback")
    preset_version: Optional[str] = Field(default=None, alias="presetVersion")
    pack_name: Optional[str] = Field(default=None, alias="packName")
    pack_names: List[str] = Field(default_factory=list, alias="packNames")
    preset_versions: List[Dict[str, str]] = Field(
        default_factory=list,
        alias="presetVersions",
    )
    term_match_count: int = Field(default=0, alias="termMatchCount")
    style_rule_count: int = Field(default=0, alias="styleRuleCount")
    anti_template_rule_count: int = Field(
        default=0,
        alias="antiTemplateRuleCount",
    )
    truncated_count: int = Field(default=0, alias="truncatedCount")
    matched_items: List[WritingPolicyUsageItem] = Field(default_factory=list, alias="matchedItems")
    conflict_count: int = Field(default=0, alias="conflictCount")
    conflicts: List[WritingPolicyConflict] = Field(default_factory=list)


class WritingPolicyAudit(BaseModel):
    enabled: bool = True
    passed: bool = False
    degraded: bool = False
    degraded_reason: str = Field(default="", alias="degradedReason")
    summary: str = ""
    needs_review: List[Dict[str, Any]] = Field(default_factory=list, alias="needsReview")
    expression_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list,
        alias="expressionSuggestions",
    )


class RewriteResult(BaseModel):
    original_text: str = Field(alias="originalText")
    rewritten_text: str = Field(alias="rewrittenText")
    rewrite_mode: str = Field(alias="rewriteMode")
    diff_hints: List[str] = Field(default_factory=list, alias="diffHints")
    provider: str = "mock"
    writing_policy_usage: Optional[WritingPolicyUsage] = Field(default=None, alias="writingPolicyUsage")
    writing_policy_audit: Optional[WritingPolicyAudit] = Field(
        default=None,
        alias="writingPolicyAudit",
    )


class DocumentReviewIssue(BaseModel):
    category: Literal["typo", "expression", "logic", "fluency", "professional"]
    severity: Literal["high", "medium", "low"]
    location: Optional[str] = None
    original_text: Optional[str] = Field(default=None, alias="originalText")
    problem: str
    suggestion: str
    suggested_rewrite: Optional[str] = Field(default=None, alias="suggestedRewrite")


class ApiEnvelope(BaseModel):
    success: bool
    trace_id: str = Field(alias="traceId")
    task_type: str = Field(alias="taskType")
    message: str
    data: dict
    errors: List[dict]


class FormatReviewIssue(BaseModel):
    issue_id: str = Field(default="", alias="issueId")
    rule_id: str = Field(alias="ruleId")
    category: Literal["format"] = "format"
    severity: Literal["info", "warning", "error"] = "warning"
    paragraph_index: Optional[int] = Field(default=None, alias="paragraphIndex")
    role: str = "body"
    current_level: Optional[int] = Field(default=None, alias="currentLevel")
    previous_level: Optional[int] = Field(default=None, alias="previousLevel")
    anchor_id: str = Field(default="", alias="anchorId")
    source_anchor: Dict[str, Any] = Field(default_factory=dict, alias="sourceAnchor")
    property_path: str = Field(default="", alias="propertyPath")
    unit: str = ""
    tolerance: Optional[float] = None
    evidence: List[Any] = Field(default_factory=list)
    data_status: str = Field(default="verified", alias="dataStatus")
    duplicate_group_id: str = Field(default="", alias="duplicateGroupId")
    duplicate_group_size: int = Field(default=1, alias="duplicateGroupSize")
    anchor_verification: Literal["verified", "unverified"] = Field(
        default="unverified", alias="anchorVerification"
    )
    source: str = ""
    template_hash: str = Field(default="", alias="templateHash")
    rule_version: str = Field(default="", alias="ruleVersion")
    rule_pack_sha256: str = Field(default="", alias="rulePackSha256")
    message: str
    current_value: Any = Field(default="", alias="currentValue")
    expected_value: Any = Field(default="", alias="expectedValue")
    suggestion: str = ""


class FormatReviewSummary(BaseModel):
    scope: Literal["document", "selection"] = "document"
    template_id: str = Field(alias="templateId")
    rule_pack_id: str = Field(default="", alias="rulePackId")
    rule_pack_version: str = Field(default="", alias="rulePackVersion")
    rule_pack_source_name: str = Field(default="", alias="rulePackSourceName")
    rule_pack_source_version: str = Field(default="", alias="rulePackSourceVersion")
    rule_pack_sha256: str = Field(default="", alias="rulePackSha256")
    rule_pack_integrity: Dict[str, str] = Field(default_factory=dict, alias="rulePackIntegrity")
    authorized_algorithm_version: str = Field(default="", alias="authorizedAlgorithmVersion")
    paragraph_count: int = Field(default=0, alias="paragraphCount")
    issue_count: int = Field(default=0, alias="issueCount")
    provider: str = "local"
    ai_classified_paragraph_count: int = Field(default=0, alias="aiClassifiedParagraphCount")
    local_fallback_paragraph_count: int = Field(default=0, alias="localFallbackParagraphCount")
    ai_batch_count: int = Field(default=0, alias="aiBatchCount")
    ai_attempted: bool = Field(default=False, alias="aiAttempted")
    ai_call_count: int = Field(default=0, alias="aiCallCount")
    ai_retry_count: int = Field(default=0, alias="aiRetryCount")
    ai_correction_count: int = Field(default=0, alias="aiCorrectionCount")
    ai_skipped_count: int = Field(default=0, alias="aiSkippedCount")
    ai_parse_error_count: int = Field(default=0, alias="aiParseErrorCount")
    ai_request_error_count: int = Field(default=0, alias="aiRequestErrorCount")
    ai_invalid_role_count: int = Field(default=0, alias="aiInvalidRoleCount")
    ai_out_of_batch_count: int = Field(default=0, alias="aiOutOfBatchCount")
    ai_invalid_binding_count: int = Field(default=0, alias="aiInvalidBindingCount")
    ai_low_confidence_count: int = Field(default=0, alias="aiLowConfidenceCount")
    ai_conflict_count: int = Field(default=0, alias="aiConflictCount")
    ai_candidate_count: int = Field(default=0, alias="aiCandidateCount")
    ai_accepted_count: int = Field(default=0, alias="aiAcceptedCount")
    ai_out_of_range_count: int = Field(default=0, alias="aiOutOfRangeCount")
    ai_fallback_reason: str = Field(default="", alias="aiFallbackReason")
    table_caption_candidate_count: int = Field(default=0, alias="tableCaptionCandidateCount")
    table_caption_suggested_count: int = Field(default=0, alias="tableCaptionSuggestedCount")
    table_caption_restricted_count: int = Field(default=0, alias="tableCaptionRestrictedCount")
    table_caption_not_assessable_count: int = Field(default=0, alias="tableCaptionNotAssessableCount")
    table_caption_call_count: int = Field(default=0, alias="tableCaptionCallCount")
    table_caption_semantic_status: str = Field(default="not_needed", alias="tableCaptionSemanticStatus")
    image_count: int = Field(default=0, alias="imageCount")
    supported_image_count: int = Field(default=0, alias="supportedImageCount")
    missing_figure_caption_count: int = Field(default=0, alias="missingFigureCaptionCount")
    text_evidence_only_count: int = Field(default=0, alias="textEvidenceOnlyCount")
    image_not_assessable_count: int = Field(default=0, alias="imageNotAssessableCount")
    pixel_export_count: int = Field(default=0, alias="pixelExportCount")
    pixel_upload_count: int = Field(default=0, alias="pixelUploadCount")
    pixel_inspected_count: int = Field(default=0, alias="pixelInspectedCount")
    figure_caption_candidate_count: int = Field(default=0, alias="figureCaptionCandidateCount")
    figure_caption_suggested_count: int = Field(default=0, alias="figureCaptionSuggestedCount")
    figure_caption_pixel_inspected_count: int = Field(default=0, alias="figureCaptionPixelInspectedCount")
    figure_caption_text_evidence_only_count: int = Field(default=0, alias="figureCaptionTextEvidenceOnlyCount")
    figure_caption_not_assessable_count: int = Field(default=0, alias="figureCaptionNotAssessableCount")
    figure_caption_call_count: int = Field(default=0, alias="figureCaptionCallCount")
    figure_caption_semantic_status: str = Field(default="not_needed", alias="figureCaptionSemanticStatus")
    image_semantic_status: str = Field(default="disabled", alias="imageSemanticStatus")
    image_semantic_reason: str = Field(default="image_semantics_disabled", alias="imageSemanticReason")
    image_target_host: str = Field(default="", alias="imageTargetHost")
    semantic_status: str = Field(default="not_needed", alias="semanticStatus")
    model_configuration_name: str = Field(default="", alias="modelConfigurationName")
    model_configuration_id: str = Field(default="", alias="modelConfigurationId")
    model_configuration_version: int = Field(default=0, alias="modelConfigurationVersion")
    access_method: str = Field(default="", alias="accessMethod")
    snapshot_binding: Dict[str, str] = Field(default_factory=dict, alias="snapshotBinding")


class FormatReviewResponseData(BaseModel):
    summary: FormatReviewSummary
    issues: List[FormatReviewIssue] = Field(default_factory=list)


class RewriteResponseData(RewriteResult):
    pass


class DocumentReviewResponseData(BaseModel):
    document_type: str = Field(alias="documentType")
    review_prompt: str = Field(alias="reviewPrompt")
    scope: Literal["document", "selection"] = "document"
    summary: str
    issues: List[DocumentReviewIssue] = Field(default_factory=list)
    provider: str = "mock"
    raw_answer: str = Field(default="", alias="rawAnswer")
    parse_fallback_reason: str = Field(default="", alias="parseFallbackReason")
    writing_policy_usage: Optional[WritingPolicyUsage] = Field(default=None, alias="writingPolicyUsage")
    writing_policy_audit: Optional[WritingPolicyAudit] = Field(
        default=None,
        alias="writingPolicyAudit",
    )
