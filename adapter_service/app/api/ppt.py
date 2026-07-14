from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.models import (
    PptDocumentFileUploadRequest,
    PptSlideAssistantRequest,
    PptSlideAssistantResponseData,
)
from app.core.tracing import new_trace_id
from app.services.ppt.document_files import PptDocumentFileStore
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore


router = APIRouter()
ppt_document_files = PptDocumentFileStore()
ppt_slide_assistant = PptSlideAssistant(document_file_store=ppt_document_files)
ppt_slide_jobs = PptSlideAssistantJobStore(ppt_slide_assistant)


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
def get_ppt_slide_assistant_job(job_id: str):
    job = ppt_slide_jobs.get(job_id)
    if not job:
        message = "智能总结后台任务不存在或已过期。"
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "traceId": job_id,
                "taskType": "ppt.slide_assistant",
                "message": message,
                "data": {"jobId": job_id, "status": "not_found"},
                "errors": [{"code": "PPT_SLIDE_JOB_NOT_FOUND", "message": message}],
            },
        )
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
