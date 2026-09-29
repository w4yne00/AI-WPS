from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.word import material_import_service as word_material_import_service
from app.core.logging import get_logger
from app.core.models import (
    ExcelAnalysisRequest,
    ExcelAnalysisResponseData,
    ExcelFormulaAssistantRequest,
    ExcelFormulaAssistantResponseData,
    ExcelSmartFillRequest,
    ExcelSmartFillWriteCommitRequest,
)
from app.core.tracing import new_trace_id
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
from app.services.excel.formula_assistant import ExcelFormulaAssistant
from app.services.excel.formula_assistant_jobs import ExcelFormulaAssistantJobStore
from app.services.excel.smart_fill import ExcelSmartFill
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
from app.services.excel.material_store import ExcelMaterialStore
from app.services.excel.material_ledger import ExcelMaterialLedgerCoordinator

router = APIRouter()
excel_analyzer = ExcelAnalyzer()
excel_analysis_jobs = ExcelAnalysisJobStore(excel_analyzer)
excel_formula_assistant = ExcelFormulaAssistant()
excel_formula_assistant_jobs = ExcelFormulaAssistantJobStore(excel_formula_assistant)
excel_smart_fill = ExcelSmartFill()
excel_smart_fill_jobs = ExcelSmartFillJobStore(excel_smart_fill)
excel_material_store = ExcelMaterialStore(word_store=word_material_import_service._store)
excel_material_ledger = ExcelMaterialLedgerCoordinator(store=excel_material_store)
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


def _missing_excel_formula_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "公式助手任务不存在，可能因 adapter 重启而中断，请重新提交。"
        if interrupted
        else "公式助手后台任务不存在或已过期。"
    )
    code = (
        "EXCEL_FORMULA_JOB_INTERRUPTED"
        if interrupted
        else "EXCEL_FORMULA_JOB_NOT_FOUND"
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
            "taskType": "excel.formula_assistant",
            "message": message,
            "data": data,
            "errors": [{"code": code, "message": message}],
        },
    )


def _missing_excel_smart_fill_response(
    job_id: str, interrupted: bool = False
) -> JSONResponse:
    message = (
        "智能填写任务不存在，可能因 adapter 重启而中断，请重新提交。"
        if interrupted
        else "智能填写后台任务不存在或已过期。"
    )
    code = (
        "EXCEL_SMART_FILL_JOB_INTERRUPTED"
        if interrupted
        else "EXCEL_SMART_FILL_JOB_NOT_FOUND"
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
            "taskType": "excel.smart_fill",
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


@router.post("/excel/formula-assistant/jobs")
def start_excel_formula_job(request: ExcelFormulaAssistantRequest) -> dict:
    trace_id = new_trace_id("excel-formula")
    job = excel_formula_assistant_jobs.start(request, trace_id=trace_id)
    logger.info(
        "traceId=%s task=excel.formula_assistant jobStatus=%s",
        trace_id,
        job["status"],
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.formula_assistant",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/excel/formula-assistant/jobs/{job_id}")
def get_excel_formula_job(job_id: str, resume: bool = False):
    job = excel_formula_assistant_jobs.get(job_id)
    if not job:
        return _missing_excel_formula_response(job_id, interrupted=resume)
    if job.get("result"):
        job = {
            **job,
            "result": ExcelFormulaAssistantResponseData(
                **job["result"]
            ).dict(by_alias=True),
        }
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.formula_assistant",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/excel/formula-assistant/jobs/{job_id}")
def cancel_excel_formula_job(job_id: str, resume: bool = False):
    job = excel_formula_assistant_jobs.cancel(job_id)
    if not job:
        return _missing_excel_formula_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.formula_assistant",
        "message": "cancelled",
        "data": job,
        "errors": [],
    }


@router.post("/excel/smart-fill")
def excel_smart_fill_preview(request: ExcelSmartFillRequest) -> dict:
    trace_id = new_trace_id("excel-smart-fill")
    result = excel_smart_fill_jobs.run_sync(request, trace_id=trace_id)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.smart_fill",
        "message": "completed",
        "data": result,
        "errors": [],
    }


@router.post("/excel/smart-fill/jobs")
def start_excel_smart_fill_job(request: ExcelSmartFillRequest) -> dict:
    trace_id = new_trace_id("excel-smart-fill")
    job = excel_smart_fill_jobs.start(request, trace_id=trace_id)
    logger.info(
        "traceId=%s task=excel.smart_fill jobStatus=%s itemCount=%s",
        trace_id,
        job["status"],
        len(request.items),
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.smart_fill",
        "message": "accepted",
        "data": job,
        "errors": [],
    }


@router.get("/excel/smart-fill/jobs/{job_id}")
def get_excel_smart_fill_job(job_id: str, resume: bool = False):
    job = excel_smart_fill_jobs.get(job_id)
    if not job:
        return _missing_excel_smart_fill_response(job_id, interrupted=resume)
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.smart_fill",
        "message": job["status"],
        "data": job,
        "errors": [],
    }


@router.delete("/excel/smart-fill/jobs/{job_id}")
def cancel_excel_smart_fill_job(job_id: str, resume: bool = False):
    job = excel_smart_fill_jobs.cancel(job_id)
    if not job:
        return _missing_excel_smart_fill_response(job_id, interrupted=resume)
    is_running = job.get("status") == "running" and job.get("cancelRequested")
    message = "cancel_requested" if is_running else "cancelled"
    return {
        "success": True,
        "traceId": job.get("traceId", job_id),
        "taskType": "excel.smart_fill",
        "message": message,
        "data": job,
        "errors": [],
    }


@router.post("/excel/smart-fill/jobs/{job_id}/write-commits")
def commit_excel_smart_fill_write(job_id: str, request: ExcelSmartFillWriteCommitRequest) -> dict:
    result = excel_smart_fill_jobs.commit_write(job_id, request)
    job = excel_smart_fill_jobs.get(job_id)
    message = "write_committed" if result.get("writeCommitted") else (
        "write_reserved" if result.get("writeReserved") else "write_released"
    )
    return {
        "success": True,
        "traceId": (job or {}).get("traceId", job_id),
        "taskType": "excel.smart_fill",
        "message": message,
        "data": result,
        "errors": [],
    }


def _ledger_envelope(data: dict, trace_id: str = "", message: str = "completed") -> dict:
    return {
        "success": True,
        "traceId": trace_id or str(data.get("jobId", data.get("materialId", ""))),
        "taskType": "excel.material_ledger",
        "message": message,
        "data": data,
        "errors": [],
    }


@router.get("/materials/reusable-sources")
def get_reusable_sources() -> dict:
    trace_id = new_trace_id("reusable-sources")
    sources = excel_material_store.list_reusable_sources()
    return _ledger_envelope({"sources": sources}, trace_id=trace_id, message="reusable_sources")


@router.post("/excel/materials/clone-from-source")
def clone_excel_material(request: dict) -> dict:
    trace_id = new_trace_id("excel-material-clone")
    data = excel_material_store.clone_from_source(
        source_session_id=str(request.get("sourceSessionId") or "").strip(),
        target_session_id=str(request.get("targetDocumentSessionId") or "").strip(),
        target_doc_identity=str(request.get("targetDocumentIdentity") or "").strip(),
    )
    return _ledger_envelope(data, trace_id=trace_id, message="cloned")


@router.post("/excel/materials/import")
def import_excel_material(request: dict) -> dict:
    trace_id = new_trace_id("excel-material-import")
    data = excel_material_store.import_request(request)
    return _ledger_envelope(data, trace_id=trace_id, message="imported")


@router.get("/excel/materials/catalog")
def get_excel_materials_catalog(documentSessionId: str = "") -> dict:
    trace_id = new_trace_id("excel-material-catalog")
    data = excel_material_store.get_catalog(documentSessionId)
    return _ledger_envelope(data, trace_id=trace_id, message="catalog")


@router.put("/excel/materials/{material_id}")
def update_excel_material(material_id: str, request: dict) -> dict:
    data = excel_material_store.import_request(request, material_id)
    return _ledger_envelope(data, trace_id=material_id, message="updated")


@router.delete("/excel/materials/{material_id}")
def delete_excel_material(material_id: str, documentSessionId: str = "") -> dict:
    data = excel_material_store.delete_material(
        session_id=documentSessionId,
        material_id=material_id,
    )
    return _ledger_envelope(data, trace_id=material_id, message="deleted")


@router.post("/excel/materials/bind-document")
def bind_excel_materials_document(request: dict) -> dict:
    trace_id = new_trace_id("excel-material-bind")
    data = excel_material_store.bind_document(
        old_session_id=str(request.get("oldDocumentSessionId") or "").strip(),
        new_session_id=str(request.get("newDocumentSessionId") or "").strip(),
        new_doc_identity=str(request.get("newDocumentIdentity") or "").strip(),
    )
    return _ledger_envelope(data, trace_id=trace_id, message="bound")


@router.get("/excel/material-ledger/conflicts")
def get_excel_material_conflicts(documentSessionId: str = "", userFacts: str = "") -> dict:
    trace_id = new_trace_id("excel-material-conflicts")
    conflicts = excel_material_ledger.detect_conflicts(
        document_session_id=documentSessionId,
        user_facts=userFacts,
    )
    return _ledger_envelope({"conflicts": conflicts}, trace_id=trace_id, message="conflicts")


@router.post("/excel/material-ledger/conflicts")
def post_excel_material_conflicts(request: dict) -> dict:
    trace_id = new_trace_id("excel-material-conflicts")
    session_id = str(request.get("documentSessionId") or "").strip()
    user_facts = str(request.get("userFacts") or "").strip()
    conflicts = excel_material_ledger.detect_conflicts(
        document_session_id=session_id,
        user_facts=user_facts,
    )
    return _ledger_envelope({"conflicts": conflicts}, trace_id=trace_id, message="conflicts")


@router.post("/excel/material-ledger/jobs")
def start_excel_material_ledger_job(request: dict) -> dict:
    trace_id = new_trace_id("excel-material-ledger")
    job = excel_material_ledger.submit_job(request, trace_id=trace_id)
    return _ledger_envelope(job, trace_id=job.get("traceId", trace_id), message=job.get("status", "accepted"))


@router.get("/excel/material-ledger/jobs/{job_id}")
def get_excel_material_ledger_job(job_id: str, documentSessionId: str = "") -> dict:
    job = excel_material_ledger.query_job(job_id, document_session_id=documentSessionId)
    return _ledger_envelope(job, trace_id=job.get("traceId", job_id), message=job.get("status", "completed"))


@router.post("/excel/material-ledger/jobs/{job_id}/cancel")
def cancel_excel_material_ledger_job(job_id: str, request: dict) -> dict:
    session_id = str(request.get("documentSessionId") or "").strip()
    job = excel_material_ledger.cancel_job(job_id, document_session_id=session_id)
    return _ledger_envelope(job, trace_id=job.get("traceId", job_id), message=job.get("status", "cancelled"))
