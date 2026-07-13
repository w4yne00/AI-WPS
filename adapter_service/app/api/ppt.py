from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.models import PptSlideAssistantRequest, PptSlideAssistantResponseData
from app.core.tracing import new_trace_id
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore


router = APIRouter()
ppt_slide_assistant = PptSlideAssistant()
ppt_slide_jobs = PptSlideAssistantJobStore(ppt_slide_assistant)


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
        message = "PPT 单页助手后台任务不存在或已过期。"
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
        job = {
            **job,
            "result": PptSlideAssistantResponseData(**job["result"]).dict(by_alias=True),
        }
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "ppt.slide_assistant",
        "message": job["status"],
        "data": job,
        "errors": [],
    }
