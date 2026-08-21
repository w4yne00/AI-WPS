from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.models import (
    DocumentReviewResponseData,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.core.logging import get_logger
from app.core.errors import AdapterError
from app.core.tracing import new_trace_id
from app.services.word.document_reviewer import WordDocumentReviewer
from app.services.word.document_review_jobs import DocumentReviewJobStore
from app.services.word.deterministic_format_review import (
    WORD_FORMAT_REVIEW_SYNC_RETIRED_CODE,
    WORD_FORMAT_REVIEW_SYNC_RETIRED_MESSAGE,
    deterministic_format_review_service,
)
from app.services.word.full_document_review import full_document_review_service
from app.services.word.smart_imitator import WordSmartImitator
from app.services.word.rewriter import WordRewriter
from app.services.word.writing_jobs import SmartImitationJobStore, SmartWriteJobStore

router = APIRouter()
rewriter = WordRewriter()
smart_imitator = WordSmartImitator()
document_reviewer = WordDocumentReviewer()
document_review_jobs = DocumentReviewJobStore(document_reviewer)
smart_write_jobs = SmartWriteJobStore(rewriter)
smart_imitation_jobs = SmartImitationJobStore(smart_imitator)
logger = get_logger(__name__)


@router.post("/word/document-review/full/snapshots")
def create_full_document_review_snapshot(request: dict) -> dict:
    data = full_document_review_service.create_session(request)
    return _full_review_envelope(data, message="created")


@router.put("/word/document-review/full/snapshots/{session_id}/batches/{sequence}")
def upload_full_document_review_batch(
    session_id: str, sequence: int, request: dict
) -> dict:
    data = full_document_review_service.upload_batch(session_id, sequence, request)
    return _full_review_envelope(data, message="uploaded")


@router.post("/word/document-review/full/snapshots/{session_id}/commit")
def commit_full_document_review_snapshot(session_id: str, request: dict) -> dict:
    data = full_document_review_service.commit_snapshot(session_id, request)
    return _full_review_envelope(data, message="committed")


@router.delete("/word/document-review/full/snapshots/{session_id}")
def delete_full_document_review_snapshot(session_id: str, request: dict) -> dict:
    data = full_document_review_service.delete_snapshot(session_id, request)
    return _full_review_envelope(data, message="deleted")


@router.post("/word/document-review/full/jobs")
def start_full_document_review_job(request: dict) -> dict:
    trace_id = new_trace_id("word-full-document-review")
    data = full_document_review_service.start_job(request, trace_id)
    return _full_review_envelope(data, trace_id=trace_id, message="accepted")


@router.get("/word/document-review/full/jobs/{job_id}")
def get_full_document_review_job(job_id: str):
    data = full_document_review_service.get_job(job_id)
    if data is None:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_JOB_NOT_FOUND",
            "全篇审查任务不存在或已过期。",
            status_code=404,
        )
    return _full_review_envelope(data, trace_id=data.get("traceId", job_id), message=data["status"])


@router.get("/word/document-review/full/jobs/{job_id}/issues")
def list_full_document_review_issues(
    job_id: str,
    pageSize: str = "",
    cursor: str = "",
    severity: str = "",
    category: str = "",
    location: str = "",
    status: str = "",
    sort: str = "source",
):
    try:
        parsed_page_size = int(pageSize) if pageSize else None
    except (TypeError, ValueError):
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_ISSUE_PAGE_SIZE_INVALID",
            "问题分页大小必须是 1 到 100 之间的整数。",
        )
    data = full_document_review_service.list_issues(
        job_id,
        page_size=parsed_page_size,
        cursor=cursor,
        severity=severity,
        category=category,
        location=location,
        status=status,
        sort=sort,
    )
    return _full_review_envelope(data, trace_id=job_id, message="issues")


@router.patch("/word/document-review/full/jobs/{job_id}/issues/{issue_id}")
def update_full_document_review_issue(job_id: str, issue_id: str, request: dict):
    allowed_fields = {"status", "anchorVerification"}
    if (
        not isinstance(request, dict)
        or not set(request)
        or not set(request).issubset(allowed_fields)
    ):
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_ISSUE_REQUEST_INVALID",
            "问题更新请求格式无效。",
        )
    data = full_document_review_service.update_issue_status(
        job_id,
        issue_id,
        request.get("status"),
        request.get("anchorVerification"),
    )
    return _full_review_envelope(data, trace_id=job_id, message="issue updated")


@router.delete("/word/document-review/full/jobs/{job_id}")
def cancel_full_document_review_job(job_id: str):
    data = full_document_review_service.cancel_job(job_id)
    if data is None:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_JOB_NOT_FOUND",
            "全篇审查任务不存在或已过期。",
            status_code=404,
        )
    return _full_review_envelope(data, trace_id=data.get("traceId", job_id), message=data["status"])


@router.get("/word/document-review/full/jobs/{job_id}/report")
def get_full_document_review_report(job_id: str, format: str = "summary"):
    if format == "summary":
        data = full_document_review_service.get_report(job_id)
        return _full_review_envelope(data, trace_id=job_id, message="completed")
    exported = full_document_review_service.export_report(job_id, format)
    if format == "markdown":
        return PlainTextResponse(
            exported,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="word-full-review.md"'},
        )
    return _full_review_envelope(exported, trace_id=job_id, message="exported")


@router.delete("/word/document-review/full/jobs/{job_id}/result")
def delete_full_document_review_result(job_id: str) -> dict:
    data = full_document_review_service.delete_result(job_id)
    return _full_review_envelope(data, trace_id=job_id, message="deleted")


def _full_review_envelope(
    data: dict, trace_id: str = "", message: str = "completed"
) -> dict:
    return {
        "success": True,
        "traceId": trace_id or str(data.get("jobId", data.get("sessionId", data.get("snapshotId", "")))),
        "taskType": "word.document_review.full",
        "message": message,
        "data": data,
        "errors": [],
    }


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
    write = smart_write_jobs.run_sync(request, trace_id=trace_id)
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
    imitation = smart_imitation_jobs.run_sync(request, trace_id=trace_id)
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


def _missing_writing_job_response(job_id: str, task_type: str, interrupted: bool = False):
    label = "智能编写" if task_type == "word.smart_write" else "智能仿写"
    code_prefix = "SMART_WRITE" if task_type == "word.smart_write" else "SMART_IMITATION"
    message = (
        "{0}任务不存在，可能因 Adapter 重启而中断，请重新提交。".format(label)
        if interrupted
        else "{0}后台任务不存在或已过期。".format(label)
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
            "taskType": task_type,
            "message": message,
            "data": data,
            "errors": [
                {
                    "code": "{0}_JOB_{1}".format(
                        code_prefix, "INTERRUPTED" if interrupted else "NOT_FOUND"
                    ),
                    "message": message,
                }
            ],
        },
    )


def _writing_job_envelope(job: dict, task_type: str) -> dict:
    payload = dict(job)
    if payload.get("result"):
        payload["result"] = RewriteResponseData(**payload["result"]).dict(by_alias=True)
    return {
        "success": True,
        "traceId": payload.get("traceId", payload.get("jobId", "")),
        "taskType": task_type,
        "message": payload["status"],
        "data": payload,
        "errors": [],
    }


@router.post("/word/smart-write/jobs")
def start_smart_write_job(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-write")
    return _writing_job_envelope(smart_write_jobs.start(request, trace_id), "word.smart_write")


@router.get("/word/smart-write/jobs/{job_id}")
def get_smart_write_job(job_id: str, resume: bool = False):
    job = smart_write_jobs.get(job_id)
    if not job:
        return _missing_writing_job_response(job_id, "word.smart_write", resume)
    return _writing_job_envelope(job, "word.smart_write")


@router.delete("/word/smart-write/jobs/{job_id}")
def cancel_smart_write_job(job_id: str, resume: bool = False):
    job = smart_write_jobs.cancel(job_id)
    if not job:
        return _missing_writing_job_response(job_id, "word.smart_write", resume)
    return _writing_job_envelope(job, "word.smart_write")


@router.post("/word/smart-imitation/jobs")
def start_smart_imitation_job(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-imitation")
    return _writing_job_envelope(
        smart_imitation_jobs.start(request, trace_id), "word.smart_imitation"
    )


@router.get("/word/smart-imitation/jobs/{job_id}")
def get_smart_imitation_job(job_id: str, resume: bool = False):
    job = smart_imitation_jobs.get(job_id)
    if not job:
        return _missing_writing_job_response(job_id, "word.smart_imitation", resume)
    return _writing_job_envelope(job, "word.smart_imitation")


@router.delete("/word/smart-imitation/jobs/{job_id}")
def cancel_smart_imitation_job(job_id: str, resume: bool = False):
    job = smart_imitation_jobs.cancel(job_id)
    if not job:
        return _missing_writing_job_response(job_id, "word.smart_imitation", resume)
    return _writing_job_envelope(job, "word.smart_imitation")


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
def format_review_word() -> dict:
    raise AdapterError(
        WORD_FORMAT_REVIEW_SYNC_RETIRED_CODE,
        WORD_FORMAT_REVIEW_SYNC_RETIRED_MESSAGE,
        status_code=410,
    )


@router.post("/word/format-review/snapshots")
def create_deterministic_format_review_snapshot(request: dict) -> dict:
    data = deterministic_format_review_service.create_snapshot(request)
    return _deterministic_format_review_envelope(data, message="created")


@router.put("/word/format-review/snapshots/{snapshot_id}/batches/{sequence}")
def upload_deterministic_format_review_batch(
    snapshot_id: str, sequence: int, request: dict
) -> dict:
    data = deterministic_format_review_service.upload_batch(snapshot_id, sequence, request)
    return _deterministic_format_review_envelope(data, message="uploaded")


@router.post("/word/format-review/snapshots/{snapshot_id}/commit")
def commit_deterministic_format_review_snapshot(
    snapshot_id: str, request: dict
) -> dict:
    data = deterministic_format_review_service.commit_snapshot(snapshot_id, request)
    return _deterministic_format_review_envelope(data, message="committed")


@router.post("/word/format-review/snapshots/{snapshot_id}/image-groups")
def allocate_deterministic_format_review_image_group(
    snapshot_id: str, request: dict
) -> dict:
    data = deterministic_format_review_service.allocate_image_group(snapshot_id, request)
    return _deterministic_format_review_envelope(data, message=data.get("status", "allocated"))


@router.post("/word/format-review/snapshots/{snapshot_id}/image-groups/{group_id}/commit")
def commit_deterministic_format_review_image_group(
    snapshot_id: str, group_id: str, request: dict
) -> dict:
    data = deterministic_format_review_service.commit_image_group(snapshot_id, group_id, request)
    return _deterministic_format_review_envelope(data, message="committed")


@router.post("/word/format-review/jobs")
def start_deterministic_format_review_job(request: dict) -> dict:
    trace_id = new_trace_id("word-deterministic-format-review")
    data = deterministic_format_review_service.start_job(request, trace_id)
    return _deterministic_format_review_envelope(
        data, trace_id=trace_id, message="accepted"
    )


@router.get("/word/format-review/jobs/{job_id}")
def get_deterministic_format_review_job(job_id: str) -> dict:
    data = deterministic_format_review_service.get_job(job_id)
    if data is None:
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_JOB_NOT_FOUND",
            "确定性格式审查后台任务不存在或已过期。",
            status_code=404,
        )
    return _deterministic_format_review_envelope(
        data, trace_id=data.get("traceId", job_id), message=data["status"]
    )


@router.get("/word/format-review/jobs/{job_id}/issues")
def list_deterministic_format_review_issues(
    job_id: str,
    pageSize: str = "",
    cursor: str = "",
    ruleId: str = "",
    severity: str = "",
    dataStatus: str = "",
    status: str = "",
    duplicateGroupId: str = "",
    sort: str = "source",
):
    try:
        parsed_page_size = int(pageSize) if pageSize else None
    except (TypeError, ValueError):
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_ISSUE_PAGE_SIZE_INVALID",
            "问题分页大小必须是 1 到 100 之间的整数。",
        )
    data = deterministic_format_review_service.list_issues(
        job_id,
        page_size=parsed_page_size,
        cursor=cursor,
        rule_id=ruleId,
        severity=severity,
        data_status=dataStatus,
        status=status,
        duplicate_group_id=duplicateGroupId,
        sort=sort,
    )
    return _deterministic_format_review_envelope(data, trace_id=job_id, message="issues")


@router.patch("/word/format-review/jobs/{job_id}/issues/{issue_id}")
def update_deterministic_format_review_issue(job_id: str, issue_id: str, request: dict):
    allowed_fields = {"status", "anchorVerification"}
    if (
        not isinstance(request, dict)
        or not set(request)
        or not set(request).issubset(allowed_fields)
    ):
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_ISSUE_REQUEST_INVALID",
            "格式问题更新请求格式无效。",
        )
    data = deterministic_format_review_service.update_issue(
        job_id,
        issue_id,
        status=request.get("status"),
        anchor_verification=request.get("anchorVerification"),
    )
    return _deterministic_format_review_envelope(data, trace_id=job_id, message="issue updated")


@router.delete("/word/format-review/jobs/{job_id}")
def cancel_deterministic_format_review_job(job_id: str) -> dict:
    data = deterministic_format_review_service.cancel_job(job_id)
    if data is None:
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_JOB_NOT_FOUND",
            "确定性格式审查后台任务不存在或已过期。",
            status_code=404,
        )
    return _deterministic_format_review_envelope(
        data, trace_id=data.get("traceId", job_id), message=data["status"]
    )


@router.get("/word/format-review/jobs/{job_id}/report")
def get_deterministic_format_review_report(job_id: str, format: str = "summary"):
    if format == "summary":
        data = deterministic_format_review_service.get_report(job_id)
        return _deterministic_format_review_envelope(data, trace_id=job_id, message="completed")
    exported = deterministic_format_review_service.export_report(job_id, format)
    if format == "markdown":
        return PlainTextResponse(
            exported,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="word-format-review.md"'},
        )
    return _deterministic_format_review_envelope(exported, trace_id=job_id, message="exported")


@router.delete("/word/format-review/jobs/{job_id}/report")
def delete_deterministic_format_review_report(job_id: str) -> dict:
    data = deterministic_format_review_service.delete_report(job_id)
    return _deterministic_format_review_envelope(data, trace_id=job_id, message="deleted")


@router.delete("/word/format-review/snapshots/{snapshot_id}")
def delete_deterministic_format_review_snapshot(snapshot_id: str, request: dict) -> dict:
    data = deterministic_format_review_service.delete_snapshot(snapshot_id, request)
    return _deterministic_format_review_envelope(data, message="deleted")


def _deterministic_format_review_envelope(
    data: dict, trace_id: str = "", message: str = "completed"
) -> dict:
    return {
        "success": True,
        "traceId": trace_id or str(data.get("jobId", data.get("snapshotId", ""))),
        "taskType": "word.format_review.deterministic",
        "message": message,
        "data": data,
        "errors": [],
    }
