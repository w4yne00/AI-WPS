from fastapi import APIRouter

from app.core.models import (
    FormatPreviewResponseData,
    FormatPreviewSummary,
    ProofreadResponseData,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.core.logging import get_logger
from app.core.tracing import new_trace_id
from app.services.word.formatter import WordFormatter
from app.services.word.proofreader import WordProofreader
from app.services.word.rewriter import WordRewriter

router = APIRouter()
proofreader = WordProofreader()
formatter = WordFormatter()
rewriter = WordRewriter()
logger = get_logger(__name__)


@router.post("/word/proofread")
def proofread_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-proofread")
    issues = proofreader.proofread(request)
    payload = ProofreadResponseData(issues=issues)
    logger.info(
        "traceId=%s task=word.proofread templateId=%s issueCount=%s",
        trace_id,
        request.options.template_id or "general-office",
        len(issues),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.proofread",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/format-preview")
def preview_format_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-format-preview")
    preview = formatter.preview(request)
    payload = FormatPreviewResponseData(
        changes=preview["changes"],
        summary=FormatPreviewSummary(**preview["summary"]),
    )
    logger.info(
        "traceId=%s task=word.format_preview templateId=%s changeCount=%s",
        trace_id,
        payload.summary.template_id,
        payload.summary.change_count,
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.format_preview",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/rewrite")
def rewrite_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-rewrite")
    mode = request.options.rewrite_action or "rewrite"
    rewrite = rewriter.rewrite(request, trace_id=trace_id, mode=mode)
    payload = RewriteResponseData(**rewrite)
    logger.info(
        "traceId=%s task=word.rewrite mode=%s sourceLength=%s",
        trace_id,
        mode,
        len(payload.original_text),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.rewrite",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
