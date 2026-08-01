from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
from app.services.word.document_review_jobs import DocumentReviewJobStore
from app.services.word.format_reviewer import WordFormatReviewer
from app.services.word.smart_imitator import WordSmartImitator
from app.services.word.rewriter import WordRewriter

router = APIRouter()
format_reviewer = WordFormatReviewer()
rewriter = WordRewriter()
smart_imitator = WordSmartImitator()
document_reviewer = WordDocumentReviewer()
document_review_jobs = DocumentReviewJobStore(document_reviewer)
logger = get_logger(__name__)


def _missing_document_review_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "文档审查任务不存在，可能因 adapter 重启而中断，请重新提交审查。"
        if interrupted
        else "文档审查后台任务不存在或已过期。"
    )
    code = (
        "DOCUMENT_REVIEW_JOB_INTERRUPTED"
        if interrupted
        else "DOCUMENT_REVIEW_JOB_NOT_FOUND"
    )
    data = (
        {
            "jobId": job_id,
            "status": "failed",
            "phase": "failed",
            "queuePosition": None,
            "canCancel": False,
        }
        if interrupted
        else {"jobId": job_id, "status": "not_found"}
    )
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "traceId": job_id,
            "taskType": "word.document_review",
            "message": message,
            "data": data,
            "errors": [
                {
                    "code": code,
                    "message": message,
                }
            ],
        },
    )


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


@router.post("/word/smart-imitation")
def smart_imitation_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-imitation")
    imitation = smart_imitator.imitate(request, trace_id=trace_id)
    payload = RewriteResponseData(**imitation)
    logger.info(
        "traceId=%s task=word.smart_imitation templateLength=%s resultLength=%s",
        trace_id,
        len(payload.original_text),
        len(payload.rewritten_text),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.smart_imitation",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/word/document-review")
def document_review_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-document-review")
    review = document_review_jobs.run_sync(request, trace_id=trace_id)
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


@router.post("/word/document-review/jobs")
def start_document_review_job(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-document-review")
    job = document_review_jobs.start(request, trace_id=trace_id)
    logger.info("traceId=%s task=word.document_review jobStatus=%s", trace_id, job["status"])
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.document_review",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/word/document-review/jobs/{job_id}")
def get_document_review_job(job_id: str, resume: bool = False):
    job = document_review_jobs.get(job_id)
    if not job:
        return _missing_document_review_response(job_id, interrupted=resume)
    if job.get("result"):
        job = {**job, "result": DocumentReviewResponseData(**job["result"]).dict(by_alias=True)}
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "word.document_review",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/word/document-review/jobs/{job_id}")
def cancel_document_review_job(job_id: str, resume: bool = False):
    job = document_review_jobs.cancel(job_id)
    if not job:
        return _missing_document_review_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "word.document_review",
        "message": "cancelled",
        "data": job,
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
