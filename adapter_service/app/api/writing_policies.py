import base64
import binascii
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, Path as PathParameter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.errors import AdapterError
from app.core.tracing import new_trace_id
from app.services.writing_policy.imports import (
    DEFAULT_IMPORT_PREVIEW_STORE,
    XLSX_MIME,
    apply_import_preview,
    build_import_preview,
    generate_csv_template,
    generate_xlsx_template,
    parse_import_file,
    validate_import_rows,
)
from app.services.writing_policy.models import WritingPolicyError, MAX_IMPORT_BYTES
from app.services.writing_policy.service import get_writing_policy_service


router = APIRouter()
TASK_TYPE = "writing_policy"
_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_NOT_FOUND_CODES = {
    "writing_policy_item_not_found",
    "writing_policy_pack_not_found",
    "import_preview_not_found",
    "import_preview_expired",
}
_CONFLICT_CODES = {"term_text_conflict", "style_name_conflict"}
_TOO_LARGE_CODES = {"import_file_too_large"}
_UNAVAILABLE_CODES = {
    "writing_policy_data_corrupt",
    "writing_policy_store_unavailable",
    "writing_policy_storage_unavailable",
    "writing_policy_io_error",
    "writing_policy_internal_error",
    "writing_policy_initializing",
}


if hasattr(BaseModel, "model_validate"):
    from pydantic import ConfigDict

    class _AliasModel(BaseModel):
        model_config = ConfigDict(populate_by_name=True, extra="forbid")

else:

    class _AliasModel(BaseModel):
        class Config:
            allow_population_by_field_name = True
            extra = "forbid"


class WritingPolicyItemRequest(_AliasModel):
    type: Optional[str] = None
    scope: Optional[str] = None
    category: Optional[str] = None
    preferred_text: Optional[str] = Field(default=None, alias="preferredText")
    aliases: Optional[List[str]] = None
    forbidden_variants: Optional[List[str]] = Field(
        default=None, alias="forbiddenVariants"
    )
    definition: Optional[str] = None
    context_keywords: Optional[List[str]] = Field(
        default=None, alias="contextKeywords"
    )
    priority: Optional[str] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None
    name: Optional[str] = None
    rule_text: Optional[str] = Field(default=None, alias="ruleText")
    positive_example: Optional[str] = Field(default=None, alias="positiveExample")
    negative_example: Optional[str] = Field(default=None, alias="negativeExample")
    always_apply: Optional[bool] = Field(default=None, alias="alwaysApply")


class ImportPreviewRequest(_AliasModel):
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    content_base64: str = Field(alias="contentBase64")


class ImportConflictDecision(_AliasModel):
    row_number: int = Field(alias="rowNumber")
    decision: str


class ImportApplyRequest(_AliasModel):
    preview_token: str = Field(alias="previewToken")
    accepted_conflict_rows: List[ImportConflictDecision] = Field(
        default_factory=list, alias="acceptedConflictRows"
    )


def _model_payload(model: BaseModel, *, exclude_none: bool = False) -> Dict[str, object]:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True, exclude_none=exclude_none)
    return model.dict(by_alias=True, exclude_none=exclude_none)


def _envelope(data: Dict[str, object], message: str = "completed") -> dict:
    return {
        "success": True,
        "traceId": new_trace_id("writing-policies"),
        "taskType": TASK_TYPE,
        "message": message,
        "data": data,
        "errors": [],
    }


def _safe_writing_policy_code(code: object) -> str:
    value = str(code or "")
    if not _SAFE_ERROR_CODE_RE.fullmatch(value):
        value = "writing_policy_error"
    return value.upper()


def _is_unavailable_code(code: str) -> bool:
    if code in _UNAVAILABLE_CODES:
        return True
    return any(
        marker in code
        for marker in (
            "corrupt",
            "unavailable",
            "storage",
            "store",
            "database",
            "_io",
            "internal",
        )
    )


def _adapter_error(error: Exception) -> AdapterError:
    if isinstance(error, AdapterError):
        return error
    if isinstance(error, WritingPolicyError):
        code = str(error.code or "")
        public_code = _safe_writing_policy_code(code)
        if code in _NOT_FOUND_CODES:
            message = (
                "未找到指定预置规范包。"
                if code == "writing_policy_pack_not_found"
                else "未找到指定规范条目或导入预览。"
            )
            return AdapterError(public_code, message, 404)
        if code in _CONFLICT_CODES:
            return AdapterError(public_code, error.message, 409)
        if code in _TOO_LARGE_CODES:
            return AdapterError(public_code, "导入文件超过 5 MB 限制。", 413)
        if _is_unavailable_code(code):
            return AdapterError(
                public_code,
                "写作规范库暂时不可用，请稍后重试。",
                503,
            )
        known_input_prefixes = (
            "invalid_",
            "unsupported_",
            "import_",
            "duplicate_",
        )
        if code.startswith(known_input_prefixes):
            return AdapterError(public_code, error.message, 400)
        return AdapterError(public_code, "写作规范请求无法处理。", 400)
    if isinstance(error, (OSError, sqlite3.DatabaseError)):
        return AdapterError(
            "WRITING_POLICY_STORAGE_UNAVAILABLE",
            "写作规范库暂时不可用，请稍后重试。",
            503,
        )
    return AdapterError(
        "WRITING_POLICY_SERVICE_UNAVAILABLE",
        "写作规范库暂时不可用，请稍后重试。",
        503,
    )


def _raise_mapped(error: Exception):
    raise _adapter_error(error)


def _store():
    return get_writing_policy_service().store


@router.get("/writing-policies/summary")
def get_summary() -> dict:
    try:
        return _envelope(_store().summary())
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/packs")
def get_packs() -> dict:
    try:
        packs = get_writing_policy_service().list_packs()
        return _envelope({"count": len(packs), "packs": packs})
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/items")
def list_items(
    scope: Optional[str] = None,
    item_type: Optional[str] = Query(default=None, alias="type"),
    query: str = "",
    layer: str = "organization",
    pack_id: str = Query(default="", alias="packId"),
) -> dict:
    try:
        item_type = item_type if isinstance(item_type, str) else None
        pack_id = pack_id if isinstance(pack_id, str) else ""
        if layer == "preset":
            if not pack_id:
                raise WritingPolicyError(
                    "invalid_writing_policy_pack",
                    "浏览预置规范时必须指定规范包。",
                )
            items = get_writing_policy_service().list_preset_items(pack_id)
            if item_type:
                items = [item for item in items if item.get("type") == item_type]
            if query:
                normalized = query.casefold()
                items = [
                    item
                    for item in items
                    if normalized
                    in str(
                        item.get("name")
                        or item.get("preferredText")
                        or ""
                    ).casefold()
                ]
            return _envelope(
                {
                    "layer": "preset",
                    "packId": pack_id,
                    "type": item_type or "",
                    "query": query,
                    "count": len(items),
                    "items": items,
                }
            )
        if not scope or not item_type:
            raise WritingPolicyError(
                "invalid_writing_policy_query",
                "浏览组织规范时必须指定范围和类型。",
            )
        items = _store().list_items(scope, item_type, query)
        return _envelope(
            {
                "scope": scope,
                "type": item_type,
                "query": query,
                "count": len(items),
                "items": items,
            }
        )
    except Exception as error:
        _raise_mapped(error)


@router.post("/writing-policies/items")
def create_item(request: WritingPolicyItemRequest) -> dict:
    try:
        item = _store().create_item(_model_payload(request, exclude_none=True))
        return _envelope({"item": item}, "created")
    except Exception as error:
        _raise_mapped(error)


@router.patch("/writing-policies/items/{itemId}")
def update_item(
    item_id: str = PathParameter(alias="itemId"),
    request: WritingPolicyItemRequest = Body(),
) -> dict:
    try:
        item = _store().update_item(
            item_id, _model_payload(request, exclude_none=True)
        )
        return _envelope({"item": item}, "updated")
    except Exception as error:
        _raise_mapped(error)


@router.delete("/writing-policies/items/{itemId}")
def delete_item(item_id: str = PathParameter(alias="itemId")) -> dict:
    try:
        item = _store().delete_item(item_id)
        return _envelope({"deleted": True, "item": item}, "deleted")
    except Exception as error:
        _raise_mapped(error)


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": 'attachment; filename="%s"' % filename,
        },
    )


@router.get("/writing-policies/import-template.csv")
def download_csv_template() -> Response:
    try:
        return _download(
            generate_csv_template(),
            "text/csv",
            "writing-policies-import-template.csv",
        )
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/import-template.xlsx")
def download_xlsx_template() -> Response:
    try:
        return _download(
            generate_xlsx_template(),
            XLSX_MIME,
            "writing-policies-import-template.xlsx",
        )
    except Exception as error:
        _raise_mapped(error)


def _decode_import_content(request: ImportPreviewRequest) -> bytes:
    try:
        encoded = request.content_base64.encode("ascii")
        content = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        raise WritingPolicyError("invalid_import_base64", "导入文件 Base64 内容无效。")
    if request.size_bytes < 0 or request.size_bytes != len(content):
        raise WritingPolicyError(
            "import_size_mismatch", "声明的文件大小与实际内容不一致。"
        )
    if len(content) > MAX_IMPORT_BYTES:
        raise WritingPolicyError("import_file_too_large", "导入文件超过 5 MB 限制。")
    return content


@router.post("/writing-policies/imports/preview")
def preview_import(request: ImportPreviewRequest) -> dict:
    try:
        content = _decode_import_content(request)
        rows = parse_import_file(request.file_name, request.mime_type, content)
        validated = validate_import_rows(rows)
        suffix = Path(request.file_name).suffix.lower().lstrip(".")
        preview = build_import_preview(
            _store(),
            validated,
            {
                "fileName": request.file_name,
                "format": suffix,
                "rowCount": validated.get("rowCount", len(rows)),
                "mimeType": request.mime_type,
                "sizeBytes": len(content),
            },
            preview_store=DEFAULT_IMPORT_PREVIEW_STORE,
        )
        return _envelope(preview, "previewed")
    except Exception as error:
        _raise_mapped(error)


@router.post("/writing-policies/imports/apply")
def apply_import(request: ImportApplyRequest) -> dict:
    try:
        decisions = [
            _model_payload(decision) for decision in request.accepted_conflict_rows
        ]
        result = apply_import_preview(
            _store(),
            request.preview_token,
            decisions,
            preview_store=DEFAULT_IMPORT_PREVIEW_STORE,
        )
        return _envelope(result, "applied")
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/export.csv")
def export_writing_policy_csv(scope: str) -> Response:
    try:
        return _download(
            _store().export_csv(scope),
            "text/csv",
            "writing-policies-export.csv",
        )
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/backup")
def backup_writing_policy() -> Response:
    try:
        return _download(
            _store().database_snapshot_bytes(),
            "application/vnd.sqlite3",
            "writing-policies-backup.db",
        )
    except Exception as error:
        _raise_mapped(error)


@router.get("/writing-policies/diagnostics")
def get_diagnostics() -> dict:
    try:
        return _envelope(get_writing_policy_service().diagnostics())
    except Exception as error:
        _raise_mapped(error)
