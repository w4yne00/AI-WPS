from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


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

    @validator("index", "outline_level", pre=True, always=True)
    def coerce_integer(cls, value):
        return _safe_int(value) or 0

    @validator("bold", "italic", pre=True)
    def coerce_optional_bool(cls, value):
        return _safe_bool(value)


class Heading(BaseModel):
    level: int = 0
    text: str = ""
    paragraph_index: Optional[int] = Field(default=None, alias="paragraphIndex")

    @validator("level", "paragraph_index", pre=True)
    def coerce_heading_integer(cls, value):
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


class RewriteResult(BaseModel):
    original_text: str = Field(alias="originalText")
    rewritten_text: str = Field(alias="rewrittenText")
    rewrite_mode: str = Field(alias="rewriteMode")
    diff_hints: List[str] = Field(default_factory=list, alias="diffHints")
    provider: str = "mock"


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
    rule_id: str = Field(alias="ruleId")
    category: Literal["format"] = "format"
    severity: Literal["info", "warning", "error"] = "warning"
    paragraph_index: Optional[int] = Field(default=None, alias="paragraphIndex")
    role: str = "body"
    message: str
    current_value: str = Field(default="", alias="currentValue")
    expected_value: str = Field(default="", alias="expectedValue")
    suggestion: str = ""


class FormatReviewSummary(BaseModel):
    scope: Literal["document", "selection"] = "document"
    template_id: str = Field(alias="templateId")
    paragraph_count: int = Field(default=0, alias="paragraphCount")
    issue_count: int = Field(default=0, alias="issueCount")
    provider: str = "local"
    ai_classified_paragraph_count: int = Field(default=0, alias="aiClassifiedParagraphCount")
    local_fallback_paragraph_count: int = Field(default=0, alias="localFallbackParagraphCount")
    ai_batch_count: int = Field(default=0, alias="aiBatchCount")
    ai_attempted: bool = Field(default=False, alias="aiAttempted")
    ai_parse_error_count: int = Field(default=0, alias="aiParseErrorCount")
    ai_request_error_count: int = Field(default=0, alias="aiRequestErrorCount")
    ai_invalid_role_count: int = Field(default=0, alias="aiInvalidRoleCount")
    ai_out_of_batch_count: int = Field(default=0, alias="aiOutOfBatchCount")
    ai_fallback_reason: str = Field(default="", alias="aiFallbackReason")


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
