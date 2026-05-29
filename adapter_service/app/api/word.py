from fastapi import APIRouter

from app.core.models import (
    DocumentReviewResponseData,
    FormatReviewResponseData,
    FormatReviewSummary,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.core.logging import get_logger
from app.core.tracing import new_trace_id
from app.services.word.document_reviewer import WordDocumentReviewer
from app.services.word.format_reviewer import WordFormatReviewer
from app.services.word.rewriter import WordRewriter

router = APIRouter()
format_reviewer = WordFormatReviewer()
rewriter = WordRewriter()
document_reviewer = WordDocumentReviewer()
logger = get_logger(__name__)


@router.post("/word/smart-write")
def smart_write_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-write")
    write = rewriter.smart_write(request, trace_id=trace_id)
    payload = RewriteResponseData(**write)
    logger.info(
        "traceId=%s task=word.smart_write action=%s sourceLength=%s",
        trace_id,
        payload.rewrite_mode,
        len(payload.original_text),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.smart_write",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/document-review")
def document_review_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-document-review")
    review = document_reviewer.review(request, trace_id=trace_id)
    payload = DocumentReviewResponseData(**review)
    logger.info(
        "traceId=%s task=word.document_review documentType=%s issueCount=%s",
        trace_id,
        payload.document_type,
        len(payload.issues),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.document_review",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/format-review")
def format_review_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-format-review")
    review = format_reviewer.review(request, trace_id=trace_id)
    payload = FormatReviewResponseData(
        issues=review["issues"],
        summary=FormatReviewSummary(**review["summary"]),
    )
    logger.info(
        "traceId=%s task=word.format_review templateId=%s issueCount=%s",
        trace_id,
        payload.summary.template_id,
        payload.summary.issue_count,
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.format_review",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
