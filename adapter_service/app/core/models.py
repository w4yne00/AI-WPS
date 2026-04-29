from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Paragraph(BaseModel):
    index: int
    text: str
    style_name: Optional[str] = Field(default=None, alias="styleName")
    font_name: Optional[str] = Field(default=None, alias="fontName")
    font_size: Optional[float] = Field(default=None, alias="fontSize")
    alignment: Optional[str] = None
    outline_level: Optional[int] = Field(default=None, alias="outlineLevel")


class Heading(BaseModel):
    level: int
    text: str


class DocumentContent(BaseModel):
    plain_text: str = Field(alias="plainText")
    paragraphs: List[Paragraph]
    headings: List[Heading] = Field(default_factory=list)


class RequestOptions(BaseModel):
    template_id: Optional[str] = Field(default=None, alias="templateId")
    track_changes: bool = Field(default=True, alias="trackChanges")
    user_instruction: str = Field(default="", alias="userInstruction")
    rewrite_style: str = Field(default="default", alias="rewriteStyle")
    focus_point: str = Field(default="default", alias="focusPoint")
    length_mode: str = Field(default="default", alias="lengthMode")


class WordDocumentRequest(BaseModel):
    document_id: str = Field(alias="documentId")
    scene: Literal["word"]
    selection_mode: Literal["document", "selection"] = Field(alias="selectionMode")
    content: DocumentContent
    options: RequestOptions = Field(default_factory=RequestOptions)


class Issue(BaseModel):
    rule_id: str = Field(alias="ruleId")
    severity: Literal["info", "warning", "error"]
    message: str
    paragraph_index: Optional[int] = Field(default=None, alias="paragraphIndex")
    suggestion: Optional[str] = None
    auto_fixable: bool = Field(default=False, alias="autoFixable")


class FormatChange(BaseModel):
    paragraph_index: int = Field(alias="paragraphIndex")
    current_style: str = Field(alias="currentStyle")
    target_style: str = Field(alias="targetStyle")
    reason: str


class RewriteResult(BaseModel):
    original_text: str = Field(alias="originalText")
    rewritten_text: str = Field(alias="rewrittenText")
    rewrite_mode: str = Field(alias="rewriteMode")
    diff_hints: List[str] = Field(default_factory=list, alias="diffHints")
    provider: str = "mock"


class ApiEnvelope(BaseModel):
    success: bool
    trace_id: str = Field(alias="traceId")
    task_type: str = Field(alias="taskType")
    message: str
    data: dict
    errors: List[dict]


class ProofreadResponseData(BaseModel):
    issues: List[Issue] = Field(default_factory=list)


class FormatPreviewSummary(BaseModel):
    change_count: int = Field(alias="changeCount")
    template_id: str = Field(alias="templateId")


class FormatPreviewResponseData(BaseModel):
    changes: List[FormatChange] = Field(default_factory=list)
    summary: FormatPreviewSummary


class RewriteResponseData(RewriteResult):
    pass
