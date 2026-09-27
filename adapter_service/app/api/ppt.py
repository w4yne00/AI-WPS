import atexit

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.excel import excel_material_store
from app.api.word import material_import_service as word_material_import_service
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
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.material_outline import PptMaterialOutlineCoordinator


router = APIRouter()
ppt_document_files = PptDocumentFileStore(cleanup_interval_seconds=60)
ppt_slide_assistant = PptSlideAssistant(document_file_store=ppt_document_files)
ppt_slide_jobs = PptSlideAssistantJobStore(ppt_slide_assistant)
ppt_structure_reviewer = PptStructureReviewer()
ppt_structure_review_jobs = PptStructureReviewJobStore(ppt_structure_reviewer)
ppt_material_store = PptMaterialStore(
    word_store=word_material_import_service._store,
    excel_store=excel_material_store,
)
ppt_material_outline = PptMaterialOutlineCoordinator(store=ppt_material_store)


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


def _outline_envelope(data: dict, trace_id: str = "", message: str = "completed") -> dict:
    return {
        "success": True,
        "traceId": trace_id or str(data.get("jobId", data.get("materialId", ""))),
        "taskType": "ppt.material_outline",
        "message": message,
        "data": data,
        "errors": [],
    }


@router.post("/ppt/materials/clone-from-source")
def clone_ppt_material(request: dict) -> dict:
    trace_id = new_trace_id("ppt-material-clone")
    data = ppt_material_store.clone_from_source(
        source_session_id=str(request.get("sourceSessionId") or "").strip(),
        target_session_id=str(request.get("targetDocumentSessionId") or "").strip(),
        target_doc_identity=str(request.get("targetDocumentIdentity") or "").strip(),
    )
    return _outline_envelope(data, trace_id=trace_id, message="cloned")


@router.post("/ppt/materials/import")
def import_ppt_material(request: dict) -> dict:
    trace_id = new_trace_id("ppt-material-import")
    data = ppt_material_store.import_material(
        session_id=str(request.get("documentSessionId") or "").strip(),
        doc_identity=str(request.get("documentIdentity") or "").strip(),
        file_name=str(request.get("fileName") or "").strip(),
        content_base64=str(request.get("contentBase64") or "").strip(),
    )
    return _outline_envelope(data, trace_id=trace_id, message="imported")


@router.get("/ppt/materials/catalog")
def get_ppt_materials_catalog(documentSessionId: str = "") -> dict:
    trace_id = new_trace_id("ppt-material-catalog")
    data = ppt_material_store.get_catalog(documentSessionId)
    return _outline_envelope(data, trace_id=trace_id, message="catalog")


@router.put("/ppt/materials/{material_id}")
def update_ppt_material(material_id: str, request: dict) -> dict:
    data = ppt_material_store.update_material(
        session_id=str(request.get("documentSessionId") or "").strip(),
        material_id=material_id,
        file_name=str(request.get("fileName") or "").strip(),
        content_base64=str(request.get("contentBase64") or "").strip(),
    )
    return _outline_envelope(data, trace_id=material_id, message="updated")


@router.delete("/ppt/materials/{material_id}")
def delete_ppt_material(material_id: str, documentSessionId: str = "") -> dict:
    data = ppt_material_store.delete_material(
        session_id=documentSessionId,
        material_id=material_id,
    )
    return _outline_envelope(data, trace_id=material_id, message="deleted")


@router.post("/ppt/materials/bind-document")
def bind_ppt_materials_document(request: dict) -> dict:
    trace_id = new_trace_id("ppt-material-bind")
    data = ppt_material_store.bind_document(
        old_session_id=str(request.get("oldDocumentSessionId") or "").strip(),
        new_session_id=str(request.get("newDocumentSessionId") or "").strip(),
        new_doc_identity=str(request.get("newDocumentIdentity") or "").strip(),
    )
    return _outline_envelope(data, trace_id=trace_id, message="bound")


@router.get("/ppt/material-outline/conflicts")
def get_ppt_material_conflicts(documentSessionId: str = "", userFacts: str = "") -> dict:
    trace_id = new_trace_id("ppt-material-conflicts")
    conflicts = ppt_material_outline.detect_conflicts(
        document_session_id=documentSessionId,
        user_facts=userFacts,
    )
    return _outline_envelope({"conflicts": conflicts}, trace_id=trace_id, message="conflicts")


@router.post("/ppt/material-outline/conflicts")
def post_ppt_material_conflicts(request: dict) -> dict:
    trace_id = new_trace_id("ppt-material-conflicts")
    session_id = str(request.get("documentSessionId") or "").strip()
    user_facts = str(request.get("userFacts") or "").strip()
    conflicts = ppt_material_outline.detect_conflicts(
        document_session_id=session_id,
        user_facts=user_facts,
    )
    return _outline_envelope({"conflicts": conflicts}, trace_id=trace_id, message="conflicts")


@router.post("/ppt/material-outline/jobs")
def start_ppt_material_outline_job(request: dict) -> dict:
    trace_id = new_trace_id("ppt-material-outline")
    job = ppt_material_outline.submit_job(request, trace_id=trace_id)
    return _outline_envelope(job, trace_id=job.get("traceId", trace_id), message=job.get("status", "accepted"))


@router.get("/ppt/material-outline/jobs/{job_id}")
def get_ppt_material_outline_job(job_id: str, documentSessionId: str = "") -> dict:
    job = ppt_material_outline.query_job(job_id, document_session_id=documentSessionId)
    return _outline_envelope(job, trace_id=job.get("traceId", job_id), message=job.get("status", "completed"))


@router.post("/ppt/material-outline/jobs/{job_id}/cancel")
def cancel_ppt_material_outline_job(job_id: str, request: dict) -> dict:
    session_id = str(request.get("documentSessionId") or "").strip()
    job = ppt_material_outline.cancel_job(job_id, document_session_id=session_id)
    return _outline_envelope(job, trace_id=job.get("traceId", job_id), message=job.get("status", "cancelled"))
