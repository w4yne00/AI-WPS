from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.models import ExcelAnalysisRequest, ExcelAnalysisResponseData
from app.core.tracing import new_trace_id
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

router = APIRouter()
excel_analyzer = ExcelAnalyzer()
excel_analysis_jobs = ExcelAnalysisJobStore(excel_analyzer)
logger = get_logger(__name__)


def _missing_excel_analysis_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "智能分析任务不存在，可能因 adapter 重启而中断，请重新提交分析。"
        if interrupted
        else "智能分析后台任务不存在或已过期。"
    )
    code = (
        "EXCEL_ANALYSIS_JOB_INTERRUPTED"
        if interrupted
        else "EXCEL_ANALYSIS_JOB_NOT_FOUND"
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
            "taskType": "excel.analysis",
            "message": message,
            "data": data,
            "errors": [{"code": code, "message": message}],
        },
    )


@router.post("/excel/analysis")
def excel_analysis(request: ExcelAnalysisRequest) -> dict:
    trace_id = new_trace_id("excel-analysis")
    analysis = excel_analysis_jobs.run_sync(request, trace_id=trace_id)
    payload = ExcelAnalysisResponseData(**analysis)
    logger.info(
        "traceId=%s task=excel.analysis sheet=%s rows=%s columns=%s",
        trace_id,
        request.scope.sheet_name,
        request.table.row_count,
        request.table.column_count,
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.analysis",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }


@router.post("/excel/analysis/jobs")
def start_excel_analysis_job(request: ExcelAnalysisRequest) -> dict:
    trace_id = new_trace_id("excel-analysis")
    job = excel_analysis_jobs.start(request, trace_id=trace_id)
    logger.info("traceId=%s task=excel.analysis jobStatus=%s", trace_id, job["status"])
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.analysis",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/excel/analysis/jobs/{job_id}")
def get_excel_analysis_job(job_id: str, resume: bool = False):
    job = excel_analysis_jobs.get(job_id)
    if not job:
        return _missing_excel_analysis_response(job_id, interrupted=resume)
    if job.get("result"):
        job = {**job, "result": ExcelAnalysisResponseData(**job["result"]).dict(by_alias=True)}
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.analysis",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/excel/analysis/jobs/{job_id}")
def cancel_excel_analysis_job(job_id: str, resume: bool = False):
    job = excel_analysis_jobs.cancel(job_id)
    if not job:
        return _missing_excel_analysis_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.analysis",
        "message": "cancelled",
        "data": job,
        "errors": [],
    }
