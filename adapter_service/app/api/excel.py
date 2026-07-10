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


@router.post("/excel/analysis")
def excel_analysis(request: ExcelAnalysisRequest) -> dict:
    trace_id = new_trace_id("excel-analysis")
    analysis = excel_analyzer.analyze(request, trace_id=trace_id)
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
def get_excel_analysis_job(job_id: str):
    job = excel_analysis_jobs.get(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "traceId": job_id,
                "taskType": "excel.analysis",
                "message": "Excel 智能分析后台任务不存在或已过期。",
                "data": {"jobId": job_id, "status": "not_found"},
                "errors": [{"code": "EXCEL_ANALYSIS_JOB_NOT_FOUND", "message": "Excel 智能分析后台任务不存在或已过期。"}],
            },
        )
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
