import atexit

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.models import (
    PptDocumentFileUploadRequest,
    PptSlideAssistantRequest,
    PptSlideAssistantResponseData,
    PptStructureReviewRequest,
    PptStructureReviewResponseData,
)
from app.core.tracing import new_trace_id
from app.services.ppt.document_files import PptDocumentFileStore
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore
from app.services.ppt.structure_review import PptStructureReviewer
from app.services.ppt.structure_review_jobs import PptStructureReviewJobStore


router = APIRouter()
ppt_document_files = PptDocumentFileStore(cleanup_interval_seconds=60)
ppt_slide_assistant = PptSlideAssistant(document_file_store=ppt_document_files)
ppt_slide_jobs = PptSlideAssistantJobStore(ppt_slide_assistant)
ppt_structure_reviewer = PptStructureReviewer()
ppt_structure_review_jobs = PptStructureReviewJobStore(ppt_structure_reviewer)


def close_ppt_resources() -> None:
    ppt_slide_jobs.close()


atexit.register(close_ppt_resources)


def _missing_ppt_slide_job_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "智能总结任务不存在，可能因 adapter 重启而中断，请重新提交总结。"
        if interrupted
        else "智能总结后台任务不存在或已过期。"
    )
    code = (
        "PPT_SLIDE_JOB_INTERRUPTED"
        if interrupted
        else "PPT_SLIDE_JOB_NOT_FOUND"
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
            "taskType": "ppt.slide_assistant",
            "message": message,
            "data": data,
            "errors": [{"code": code, "message": message}],
        },
    )


def _missing_ppt_structure_job_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "结构审查任务不存在，可能因 adapter 重启而中断，请重新提交审查。"
        if interrupted
        else "结构审查后台任务不存在或已过期。"
    )
    code = "PPT_STRUCTURE_JOB_INTERRUPTED" if interrupted else "PPT_STRUCTURE_JOB_NOT_FOUND"
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
            "taskType": "ppt.structure_review",
            "message": message,
            "data": data,
            "errors": [{"code": code, "message": message}],
        },
    )


@router.post("/ppt/document-files")
def upload_ppt_document_file(request: PptDocumentFileUploadRequest) -> dict:
    trace_id = new_trace_id("ppt-document-file")
    data = ppt_document_files.store(
        request.file_name,
        request.mime_type,
        request.size_bytes,
        request.content_base64,
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "ppt.slide_assistant",
        "message": "文档已安全接收。",
        "data": data,
        "errors": [],
    }


@router.post("/ppt/slide-assistant/jobs")
def start_ppt_slide_assistant_job(request: PptSlideAssistantRequest) -> dict:
    trace_id = new_trace_id("ppt-slide-assistant")
    job = ppt_slide_jobs.start(request, trace_id=trace_id)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "ppt.slide_assistant",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/ppt/slide-assistant/jobs/{job_id}")
def get_ppt_slide_assistant_job(job_id: str, resume: bool = False):
    job = ppt_slide_jobs.get(job_id)
    if not job:
        return _missing_ppt_slide_job_response(job_id, interrupted=resume)
    if job.get("result"):
        if hasattr(PptSlideAssistantResponseData, "model_validate"):
            result = PptSlideAssistantResponseData.model_validate(job["result"]).model_dump(
                by_alias=True
            )
        else:
            result = PptSlideAssistantResponseData(**job["result"]).dict(by_alias=True)
        job = {
            **job,
            "result": result,
        }
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.slide_assistant",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/ppt/slide-assistant/jobs/{job_id}")
def cancel_ppt_slide_assistant_job(job_id: str, resume: bool = False):
    job = ppt_slide_jobs.cancel(job_id)
    if not job:
        return _missing_ppt_slide_job_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.slide_assistant",
        "message": "任务已取消。",
        "data": job,
        "errors": [],
    }


@router.post("/ppt/structure-review/jobs")
def start_ppt_structure_review_job(request: PptStructureReviewRequest) -> dict:
    trace_id = new_trace_id("ppt-structure-review")
    job = ppt_structure_review_jobs.start(request, trace_id=trace_id)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "ppt.structure_review",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/ppt/structure-review/jobs/{job_id}")
def get_ppt_structure_review_job(job_id: str, resume: bool = False):
    job = ppt_structure_review_jobs.get(job_id)
    if not job:
        return _missing_ppt_structure_job_response(job_id, interrupted=resume)
    if job.get("result"):
        if hasattr(PptStructureReviewResponseData, "model_validate"):
            result = PptStructureReviewResponseData.model_validate(job["result"]).model_dump(
                by_alias=True
            )
        else:
            result = PptStructureReviewResponseData(**job["result"]).dict(by_alias=True)
        job = {**job, "result": result}
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.structure_review",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/ppt/structure-review/jobs/{job_id}")
def cancel_ppt_structure_review_job(job_id: str, resume: bool = False):
    job = ppt_structure_review_jobs.cancel(job_id)
    if not job:
        return _missing_ppt_structure_job_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.structure_review",
        "message": "任务已取消。",
        "data": job,
        "errors": [],
    }
