from fastapi import APIRouter

from app.core.models import (
    FormatPreviewResponseData,
    FormatPreviewSummary,
    ProofreadResponseData,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.services.word.formatter import WordFormatter
from app.services.word.proofreader import WordProofreader
from app.services.word.rewriter import WordRewriter

router = APIRouter()
proofreader = WordProofreader()
formatter = WordFormatter()
rewriter = WordRewriter()


@router.post("/word/proofread")
def proofread_word(request: WordDocumentRequest) -> dict:
    issues = proofreader.proofread(request)
    payload = ProofreadResponseData(issues=issues)
    return {
        "success": True,
        "traceId": "trace-word-proofread",
        "taskType": "word.proofread",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/format-preview")
def preview_format_word(request: WordDocumentRequest) -> dict:
    preview = formatter.preview(request)
    payload = FormatPreviewResponseData(
        changes=preview["changes"],
        summary=FormatPreviewSummary(**preview["summary"]),
    )
    return {
        "success": True,
        "traceId": "trace-word-format-preview",
        "taskType": "word.format_preview",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/rewrite")
def rewrite_word(request: WordDocumentRequest) -> dict:
    trace_id = "trace-word-rewrite"
    mode = "continue" if request.selection_mode == "selection" else "rewrite"
    rewrite = rewriter.rewrite(request, trace_id=trace_id, mode=mode)
    payload = RewriteResponseData(**rewrite)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.rewrite",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
