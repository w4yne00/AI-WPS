#!/usr/bin/env python3
import base64
import binascii
import json
import re
import socket
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import load_settings, save_provider_base_url
from app.core.errors import AdapterError
from app.core.models import (
    DocumentReviewResponseData,
    ExcelAnalysisRequest,
    ExcelAnalysisResponseData,
    FormatReviewResponseData,
    FormatReviewSummary,
    PptDocumentFileUploadRequest,
    PptSlideAssistantRequest,
    PptSlideAssistantResponseData,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.core.tracing import new_trace_id
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    get_last_provider_debug,
    normalize_task_api_key_ref,
    save_local_api_key,
)
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
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
from app.services.ppt.document_files import PptDocumentFileStore
from app.services.ppt.slide_assistant import PptSlideAssistant
from app.services.ppt.slide_assistant_jobs import PptSlideAssistantJobStore
from app.services.word.document_reviewer import WordDocumentReviewer
from app.services.word.document_review_jobs import DocumentReviewJobStore
from app.services.word.format_reviewer import WordFormatReviewer
from app.services.word.rewriter import WordRewriter
from app.services.word.smart_imitator import WordSmartImitator
from app.services.workflow_profiles import WorkflowProfileError, WorkflowProfileStore


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT_DIR / "templates"
VERSION = "0.19.1-alpha"
PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES = 15 * 1024 * 1024
WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES = 7 * 1024 * 1024
# CRUD and apply payloads are small JSON documents; keep a separate hard ceiling.
WRITING_POLICY_JSON_REQUEST_MAX_BYTES = 1 * 1024 * 1024
WRITING_POLICY_BODY_READ_TIMEOUT_SECONDS = 5.0
WRITING_POLICY_MAX_CHUNK_COUNT = 1024
WRITING_POLICY_MAX_CHUNK_LINE_BYTES = 128
WRITING_POLICY_MAX_TRAILER_COUNT = 64
WRITING_POLICY_MAX_TRAILER_BYTES = 16 * 1024
WRITING_POLICY_MAX_TRAILER_LINE_BYTES = 2048
WRITING_POLICY_TASK_TYPE = "writing_policy"
_SAFE_WRITING_POLICY_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HTTP_TOKEN_BYTES_RE = re.compile(br"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SAFE_TRAILER_VALUE_BYTES_RE = re.compile(br"^[\x09\x20-\x7e\x80-\xff]*$")
_HTTP_TCHAR_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_WRITING_POLICY_NOT_FOUND_CODES = {
    "writing_policy_item_not_found",
    "import_preview_not_found",
    "import_preview_expired",
}
_WRITING_POLICY_CONFLICT_CODES = {"term_text_conflict", "style_name_conflict"}
_WRITING_POLICY_TOO_LARGE_CODES = {"import_file_too_large"}
_WRITING_POLICY_UNAVAILABLE_CODES = {
    "writing_policy_data_corrupt",
    "writing_policy_store_unavailable",
    "writing_policy_storage_unavailable",
    "writing_policy_io_error",
    "writing_policy_internal_error",
    "writing_policy_initializing",
}
_WRITING_POLICY_ITEM_FIELDS = {
    "type",
    "scope",
    "category",
    "preferredText",
    "aliases",
    "forbiddenVariants",
    "definition",
    "contextKeywords",
    "priority",
    "enabled",
    "note",
    "name",
    "ruleText",
    "positiveExample",
    "negativeExample",
    "alwaysApply",
}
_WRITING_POLICY_STATIC_ROUTE_METHODS = {
    "/writing-policies/summary": ("GET",),
    "/writing-policies/items": ("GET", "POST"),
    "/writing-policies/import-template.csv": ("GET",),
    "/writing-policies/import-template.xlsx": ("GET",),
    "/writing-policies/imports/preview": ("POST",),
    "/writing-policies/imports/apply": ("POST",),
    "/writing-policies/export.csv": ("GET",),
    "/writing-policies/backup": ("GET",),
    "/writing-policies/diagnostics": ("GET",),
}
DOCUMENT_REVIEW_JOB_STORE = DocumentReviewJobStore()
EXCEL_ANALYSIS_JOB_STORE = ExcelAnalysisJobStore()
PPT_DOCUMENT_FILE_STORE = PptDocumentFileStore(cleanup_interval_seconds=60)
PPT_SLIDE_ASSISTANT_JOB_STORE = PptSlideAssistantJobStore(
    PptSlideAssistant(document_file_store=PPT_DOCUMENT_FILE_STORE)
)


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


def parse_excel_request(payload):
    if hasattr(ExcelAnalysisRequest, "model_validate"):
        return ExcelAnalysisRequest.model_validate(payload)
    return ExcelAnalysisRequest.parse_obj(payload)


def parse_ppt_request(payload):
    if hasattr(PptSlideAssistantRequest, "model_validate"):
        return PptSlideAssistantRequest.model_validate(payload)
    return PptSlideAssistantRequest.parse_obj(payload)


def parse_ppt_document_file_request(payload):
    if hasattr(PptDocumentFileUploadRequest, "model_validate"):
        return PptDocumentFileUploadRequest.model_validate(payload)
    return PptDocumentFileUploadRequest.parse_obj(payload)


def iter_template_documents():
    for pattern in ("company/*.json", "general/*.json"):
        for path in sorted(TEMPLATE_ROOT.glob(pattern)):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "id" in data:
                yield path, data


def list_templates():
    return [
        {"id": data["id"], "name": data.get("name", data["id"]), "path": str(path)}
        for path, data in iter_template_documents()
    ]


def smart_write(payload):
    request = parse_word_request(payload)
    data = WordRewriter().smart_write(request, trace_id="standalone-word-smart-write")
    if hasattr(RewriteResponseData, "model_validate"):
        return RewriteResponseData.model_validate(data).model_dump(by_alias=True)
    return RewriteResponseData(**data).dict(by_alias=True)


def smart_imitation(payload):
    request = parse_word_request(payload)
    data = WordSmartImitator().imitate(request, trace_id="standalone-word-smart-imitation")
    if hasattr(RewriteResponseData, "model_validate"):
        return RewriteResponseData.model_validate(data).model_dump(by_alias=True)
    return RewriteResponseData(**data).dict(by_alias=True)


def document_review(payload):
    request = parse_word_request(payload)
    data = WordDocumentReviewer().review(request, trace_id="standalone-word-document-review")
    if hasattr(DocumentReviewResponseData, "model_validate"):
        return DocumentReviewResponseData.model_validate(data).model_dump(by_alias=True)
    return DocumentReviewResponseData(**data).dict(by_alias=True)


def document_review_job_payload(job):
    data = dict(job)
    if data.get("result"):
        if hasattr(DocumentReviewResponseData, "model_validate"):
            result = DocumentReviewResponseData.model_validate(data["result"]).model_dump(by_alias=True)
        else:
            result = DocumentReviewResponseData(**data["result"]).dict(by_alias=True)
        data["result"] = result
    return data


def format_review(payload):
    request = parse_word_request(payload)
    data = WordFormatReviewer().review(request, trace_id="standalone-word-format-review")
    response = FormatReviewResponseData(
        summary=FormatReviewSummary(**data["summary"]),
        issues=data["issues"],
    )
    if hasattr(response, "model_dump"):
        return response.model_dump(by_alias=True)
    return response.dict(by_alias=True)


def excel_analysis(payload):
    request = parse_excel_request(payload)
    data = ExcelAnalyzer().analyze(request, trace_id="standalone-excel-analysis")
    if hasattr(ExcelAnalysisResponseData, "model_validate"):
        return ExcelAnalysisResponseData.model_validate(data).model_dump(by_alias=True)
    return ExcelAnalysisResponseData(**data).dict(by_alias=True)


def excel_analysis_job_payload(job):
    data = dict(job)
    if data.get("result"):
        if hasattr(ExcelAnalysisResponseData, "model_validate"):
            result = ExcelAnalysisResponseData.model_validate(data["result"]).model_dump(by_alias=True)
        else:
            result = ExcelAnalysisResponseData(**data["result"]).dict(by_alias=True)
        data["result"] = result
    return data


def ppt_slide_assistant_job_payload(job):
    data = dict(job)
    if data.get("result"):
        if hasattr(PptSlideAssistantResponseData, "model_validate"):
            result = PptSlideAssistantResponseData.model_validate(data["result"]).model_dump(by_alias=True)
        else:
            result = PptSlideAssistantResponseData(**data["result"]).dict(by_alias=True)
        data["result"] = result
    return data


def envelope(trace_id, task_type, data=None, success=True, message="completed", errors=None):
    return {
        "success": success,
        "traceId": trace_id,
        "taskType": task_type,
        "message": message,
        "data": data or {},
        "errors": errors or [],
    }


def _writing_policy_json(data=None, message="completed", status=200):
    trace_id = new_trace_id("writing-policies")
    return {
        "status": status,
        "headers": {"X-Trace-Id": trace_id},
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            data or {},
            message=message,
        ),
    }


def _writing_policy_bytes(content, content_type, file_name):
    trace_id = new_trace_id("writing-policies")
    return {
        "status": 200,
        "content": content,
        "headers": {
            "Content-Type": content_type,
            "Content-Disposition": 'attachment; filename="%s"' % file_name,
            "Content-Length": str(len(content)),
            "X-Trace-Id": trace_id,
        },
    }


def _writing_policy_error(error):
    if isinstance(error, AdapterError):
        code = error.code
        message = error.message
        status = error.status_code
    elif isinstance(error, WritingPolicyError):
        raw_code = str(error.code or "")
        safe_code = raw_code if _SAFE_WRITING_POLICY_CODE_RE.fullmatch(raw_code) else "writing_policy_error"
        code = safe_code.upper()
        if raw_code in _WRITING_POLICY_NOT_FOUND_CODES:
            status, message = 404, "未找到指定规范条目或导入预览。"
        elif raw_code in _WRITING_POLICY_CONFLICT_CODES:
            status, message = 409, error.message
        elif raw_code in _WRITING_POLICY_TOO_LARGE_CODES:
            status, message = 413, "导入文件超过 5 MB 限制。"
        elif raw_code in _WRITING_POLICY_UNAVAILABLE_CODES or any(
            marker in raw_code
            for marker in (
                "corrupt",
                "unavailable",
                "storage",
                "store",
                "database",
                "_io",
                "internal",
            )
        ):
            status, message = 503, "写作规范库暂时不可用，请稍后重试。"
        elif raw_code.startswith(("invalid_", "unsupported_", "import_", "duplicate_")):
            status, message = 400, error.message
        else:
            status, message = 400, "写作规范请求无法处理。"
    elif isinstance(error, (OSError, sqlite3.DatabaseError)):
        code = "WRITING_POLICY_STORAGE_UNAVAILABLE"
        status, message = 503, "写作规范库暂时不可用，请稍后重试。"
    else:
        code = "WRITING_POLICY_SERVICE_UNAVAILABLE"
        status, message = 503, "写作规范库暂时不可用，请稍后重试。"

    trace_id = new_trace_id("writing-policies")
    return {
        "status": status,
        "headers": {"X-Trace-Id": trace_id},
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            success=False,
            message=message,
            errors=[{"code": code, "message": message}],
        ),
    }


def _writing_policy_validation(
    message="请求参数无效，请检查后重试。",
    code="REQUEST_VALIDATION_FAILED",
):
    trace_id = new_trace_id("writing-policies")
    return {
        "status": 400,
        "headers": {"X-Trace-Id": trace_id},
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            success=False,
            message=message,
            errors=[{"code": code, "message": message}],
        ),
    }


def _writing_policy_body_too_large():
    message = "写作规范导入预览请求超过 7 MB 限制。"
    trace_id = new_trace_id("writing-policies")
    return {
        "status": 413,
        "headers": {"X-Trace-Id": trace_id},
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            success=False,
            message=message,
            errors=[{"code": "IMPORT_REQUEST_TOO_LARGE", "message": message}],
        ),
    }


def _writing_policy_request_error(status, code, message):
    trace_id = new_trace_id("writing-policies")
    return {
        "status": status,
        "headers": {"X-Trace-Id": trace_id},
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            success=False,
            message=message,
            errors=[{"code": code, "message": message}],
        ),
    }


def _writing_policy_store():
    return get_writing_policy_service().store


def _is_writing_policy_path(path):
    return path == "/writing-policies" or path.startswith(
        "/writing-policies/"
    )


def writing_policy_allowed_methods(path):
    methods = _WRITING_POLICY_STATIC_ROUTE_METHODS.get(path)
    if methods is not None:
        return methods
    item_prefix = "/writing-policies/items/"
    if path.startswith(item_prefix):
        raw_item_id = path[len(item_prefix):]
        if raw_item_id and "/" not in raw_item_id and "/" not in unquote(raw_item_id):
            return ("PATCH", "DELETE")
    return None


def _writing_policy_route_error(status, code, message, allowed_methods=()):
    trace_id = new_trace_id("writing-policies")
    headers = {"X-Trace-Id": trace_id}
    if allowed_methods:
        headers["Allow"] = ", ".join(allowed_methods)
    return {
        "status": status,
        "headers": headers,
        "body": envelope(
            trace_id,
            WRITING_POLICY_TASK_TYPE,
            success=False,
            message=message,
            errors=[{"code": code, "message": message}],
        ),
    }


def _required_text(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise WritingPolicyError("invalid_request", "%s 不能为空。" % field)
    return value


def _decode_writing_policy_import(payload):
    allowed = {"fileName", "mimeType", "sizeBytes", "contentBase64"}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise WritingPolicyError("invalid_import_request", "导入预览参数不完整。")
    file_name = _required_text(payload, "fileName")
    mime_type = _required_text(payload, "mimeType")
    size_bytes = payload.get("sizeBytes")
    content_base64 = payload.get("contentBase64")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
        raise WritingPolicyError("invalid_import_size", "导入文件大小无效。")
    if not isinstance(content_base64, str):
        raise WritingPolicyError("invalid_import_base64", "导入文件 Base64 内容无效。")
    try:
        content = base64.b64decode(content_base64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        raise WritingPolicyError("invalid_import_base64", "导入文件 Base64 内容无效。")
    if size_bytes < 0 or size_bytes != len(content):
        raise WritingPolicyError(
            "import_size_mismatch", "声明的文件大小与实际内容不一致。"
        )
    if len(content) > MAX_IMPORT_BYTES:
        raise WritingPolicyError("import_file_too_large", "导入文件超过 5 MB 限制。")
    return file_name, mime_type, content


def _parse_import_decisions(payload):
    if not isinstance(payload, dict) or set(payload) - {"previewToken", "acceptedConflictRows"}:
        raise WritingPolicyError("invalid_import_request", "导入应用参数无效。")
    token = _required_text(payload, "previewToken")
    decisions = payload.get("acceptedConflictRows", [])
    if not isinstance(decisions, list):
        raise WritingPolicyError("invalid_import_request", "冲突处理决定格式无效。")
    normalized = []
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"rowNumber", "decision"}:
            raise WritingPolicyError("invalid_import_request", "冲突处理决定格式无效。")
        row_number = decision.get("rowNumber")
        action = decision.get("decision")
        if (
            isinstance(row_number, bool)
            or not isinstance(row_number, int)
            or not isinstance(action, str)
        ):
            raise WritingPolicyError("invalid_import_request", "冲突处理决定格式无效。")
        normalized.append({"rowNumber": row_number, "decision": action})
    return token, normalized


def dispatch_writing_policy(method, path, query="", payload=None, body_size=None):
    if not _is_writing_policy_path(path):
        return None
    method = str(method or "").upper()
    allowed_methods = writing_policy_allowed_methods(path)
    if allowed_methods is None:
        return _writing_policy_route_error(
            404,
            "NOT_FOUND",
            "写作规范接口不存在。",
        )
    if method not in allowed_methods:
        return _writing_policy_route_error(
            405,
            "METHOD_NOT_ALLOWED",
            "写作规范接口不支持当前请求方法。",
            allowed_methods,
        )
    payload = payload if payload is not None else {}
    if (
        method == "POST"
        and path == "/writing-policies/imports/preview"
        and body_size is not None
        and body_size > WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES
    ):
        return _writing_policy_body_too_large()

    try:
        params = parse_qs(query or "", keep_blank_values=True)
        if method == "GET" and path == "/writing-policies/summary":
            return _writing_policy_json(_writing_policy_store().summary())
        if method == "GET" and path == "/writing-policies/items":
            scope = str(params.get("scope", [""])[0]).strip()
            item_type = str(params.get("type", [""])[0]).strip()
            search = str(params.get("query", [""])[0])
            if not scope or not item_type:
                return _writing_policy_validation()
            items = _writing_policy_store().list_items(scope, item_type, search)
            return _writing_policy_json(
                {
                    "scope": scope,
                    "type": item_type,
                    "query": search,
                    "count": len(items),
                    "items": items,
                }
            )
        if method == "POST" and path == "/writing-policies/items":
            if not isinstance(payload, dict) or set(payload) - _WRITING_POLICY_ITEM_FIELDS:
                return _writing_policy_validation()
            return _writing_policy_json(
                {"item": _writing_policy_store().create_item(dict(payload))}, "created"
            )

        item_prefix = "/writing-policies/items/"
        if path.startswith(item_prefix) and path != item_prefix:
            item_id = unquote(path[len(item_prefix):]).strip("/")
            if "/" in item_id or not item_id:
                return _writing_policy_validation()
            if method == "PATCH":
                if not isinstance(payload, dict) or set(payload) - _WRITING_POLICY_ITEM_FIELDS:
                    return _writing_policy_validation()
                item = _writing_policy_store().update_item(item_id, dict(payload))
                return _writing_policy_json({"item": item}, "updated")
            if method == "DELETE":
                item = _writing_policy_store().delete_item(item_id)
                return _writing_policy_json({"deleted": True, "item": item}, "deleted")

        if method == "GET" and path == "/writing-policies/import-template.csv":
            return _writing_policy_bytes(
                generate_csv_template(),
                "text/csv",
                "writing-policies-import-template.csv",
            )
        if method == "GET" and path == "/writing-policies/import-template.xlsx":
            return _writing_policy_bytes(
                generate_xlsx_template(),
                XLSX_MIME,
                "writing-policies-import-template.xlsx",
            )
        if method == "POST" and path == "/writing-policies/imports/preview":
            file_name, mime_type, content = _decode_writing_policy_import(payload)
            rows = parse_import_file(file_name, mime_type, content)
            validated = validate_import_rows(rows)
            suffix = Path(file_name).suffix.lower().lstrip(".")
            preview = build_import_preview(
                _writing_policy_store(),
                validated,
                {
                    "fileName": file_name,
                    "format": suffix,
                    "rowCount": validated.get("rowCount", len(rows)),
                    "mimeType": mime_type,
                    "sizeBytes": len(content),
                },
                preview_store=DEFAULT_IMPORT_PREVIEW_STORE,
            )
            return _writing_policy_json(preview, "previewed")
        if method == "POST" and path == "/writing-policies/imports/apply":
            token, decisions = _parse_import_decisions(payload)
            result = apply_import_preview(
                _writing_policy_store(),
                token,
                decisions,
                preview_store=DEFAULT_IMPORT_PREVIEW_STORE,
            )
            return _writing_policy_json(result, "applied")
        if method == "GET" and path == "/writing-policies/export.csv":
            scope = str(params.get("scope", [""])[0]).strip()
            if not scope:
                return _writing_policy_validation()
            return _writing_policy_bytes(
                _writing_policy_store().export_csv(scope),
                "text/csv",
                "writing-policies-export.csv",
            )
        if method == "GET" and path == "/writing-policies/backup":
            return _writing_policy_bytes(
                _writing_policy_store().database_snapshot_bytes(),
                "application/vnd.sqlite3",
                "writing-policies-backup.db",
            )
        if method == "GET" and path == "/writing-policies/diagnostics":
            return _writing_policy_json(get_writing_policy_service().diagnostics())
        return _writing_policy_route_error(404, "NOT_FOUND", "写作规范接口不存在。")
    except Exception as error:
        return _writing_policy_error(error)


class Handler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Trace-Id")

    def _write(self, status_code, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_bytes(self, status_code, content, headers):
        self.send_response(status_code)
        self._set_cors_headers()
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _write_writing_policy_response(self, response):
        if "body" in response:
            payload = json.dumps(
                response["body"], ensure_ascii=False
            ).encode("utf-8")
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(payload)),
            }
            headers.update(response.get("headers", {}))
            self._write_bytes(response["status"], payload, headers)
            return
        self._write_bytes(response["status"], response["content"], response["headers"])

    def _reject_writing_policy_route_or_method(self, method, path):
        if not _is_writing_policy_path(path):
            return False
        allowed_methods = writing_policy_allowed_methods(path)
        if allowed_methods is not None and method in allowed_methods:
            return False
        self.close_connection = True
        self._write_writing_policy_response(
            dispatch_writing_policy(method, path)
        )
        return True

    def _header_values(self, name):
        get_all = getattr(self.headers, "get_all", None)
        if callable(get_all):
            return [str(value) for value in (get_all(name) or [])]
        value = self.headers.get(name)
        return [] if value is None else [str(value)]

    def _writing_policy_body_framing(self, preview):
        content_lengths = self._header_values("Content-Length")
        transfer_encodings = self._header_values("Transfer-Encoding")
        framing_error = _writing_policy_request_error(
            400,
            "INVALID_REQUEST_FRAMING",
            "请求体传输格式无效，请检查后重试。",
        )
        if len(content_lengths) > 1 or len(transfer_encodings) > 1:
            return None, None, framing_error
        if transfer_encodings:
            if (
                not preview
                or content_lengths
                or transfer_encodings[0].strip().lower() != "chunked"
            ):
                return None, None, framing_error
            return "chunked", None, None

        if not content_lengths:
            return "content-length", 0, None
        raw_length = content_lengths[0].strip()
        if len(raw_length) > 20 or not re.fullmatch(r"[0-9]+", raw_length):
            return None, None, framing_error
        length = int(raw_length)
        limit = (
            WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES
            if preview
            else WRITING_POLICY_JSON_REQUEST_MAX_BYTES
        )
        if length > limit:
            if preview:
                return None, None, _writing_policy_body_too_large()
            return None, None, _writing_policy_request_error(
                413,
                "WRITING_POLICY_JSON_REQUEST_TOO_LARGE",
                "写作规范 JSON 请求超过 1 MB 限制。",
            )
        return "content-length", length, None

    def _read_writing_policy_body(self, preview):
        mode, length, rejection = self._writing_policy_body_framing(preview)
        if rejection is not None:
            return None, rejection

        connection = getattr(self, "connection", None)
        previous_timeout = None
        timeout_changed = False
        deadline = (
            time.monotonic()
            + WRITING_POLICY_BODY_READ_TIMEOUT_SECONDS
        )
        try:
            if connection is not None:
                previous_timeout = connection.gettimeout()
                timeout_changed = True
            if mode == "chunked":
                return self._read_writing_policy_chunked_body(deadline)
            if not length:
                return b"{}", None
            body = self._read_writing_policy_exact(length, deadline)
            if len(body) != length:
                return None, _writing_policy_request_error(
                    400,
                    "INCOMPLETE_REQUEST_BODY",
                    "请求体不完整，请重新提交。",
                )
            return body, None
        except (socket.timeout, TimeoutError):
            return None, _writing_policy_request_error(
                400,
                "REQUEST_BODY_TIMEOUT",
                "读取请求体超时，请重新提交。",
            )
        except OSError:
            return None, _writing_policy_request_error(
                400,
                "INCOMPLETE_REQUEST_BODY",
                "请求体不完整，请重新提交。",
            )
        finally:
            if timeout_changed:
                try:
                    connection.settimeout(previous_timeout)
                except OSError:
                    pass

    def _set_writing_policy_read_timeout(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("writing-policy request-body deadline exceeded")
        connection = getattr(self, "connection", None)
        if connection is not None:
            connection.settimeout(remaining)

    def _read_writing_policy_once(self, size, deadline):
        self._set_writing_policy_read_timeout(deadline)
        read_once = getattr(self.rfile, "read1", None)
        if callable(read_once):
            return read_once(size)
        return self.rfile.read(size)

    def _read_writing_policy_exact(self, size, deadline):
        content = bytearray()
        while len(content) < size:
            part = self._read_writing_policy_once(size - len(content), deadline)
            if not part:
                break
            content.extend(part)
        return bytes(content)

    def _read_writing_policy_line(self, limit, deadline):
        line = bytearray()
        while len(line) <= limit:
            part = self._read_writing_policy_once(1, deadline)
            if not part:
                break
            line.extend(part)
            if part == b"\n":
                break
        return bytes(line)

    @staticmethod
    def _skip_chunk_bws(value, index):
        while index < len(value) and value[index] in (9, 32):
            index += 1
        return index

    @staticmethod
    def _consume_chunk_token(value, index):
        start = index
        while index < len(value) and value[index] in _HTTP_TCHAR_BYTES:
            index += 1
        return index if index > start else None

    @staticmethod
    def _consume_chunk_quoted_string(value, index):
        if index >= len(value) or value[index] != 34:
            return None
        index += 1
        while index < len(value):
            octet = value[index]
            if octet == 34:
                return index + 1
            if octet == 92:
                index += 1
                if index >= len(value):
                    return None
                escaped = value[index]
                if not (
                    escaped in (9, 32)
                    or 33 <= escaped <= 126
                    or 128 <= escaped <= 255
                ):
                    return None
                index += 1
                continue
            if (
                octet in (9, 32, 33)
                or 35 <= octet <= 91
                or 93 <= octet <= 126
                or 128 <= octet <= 255
            ):
                index += 1
                continue
            return None
        return None

    def _valid_chunk_extensions(self, value, index):
        while index < len(value):
            index = self._skip_chunk_bws(value, index)
            if index >= len(value) or value[index] != 59:
                return False
            index = self._skip_chunk_bws(value, index + 1)
            token_end = self._consume_chunk_token(value, index)
            if token_end is None:
                return False
            index = token_end

            equals_index = self._skip_chunk_bws(value, index)
            if equals_index < len(value) and value[equals_index] == 61:
                index = self._skip_chunk_bws(value, equals_index + 1)
                if index >= len(value):
                    return False
                if value[index] == 34:
                    value_end = self._consume_chunk_quoted_string(value, index)
                else:
                    value_end = self._consume_chunk_token(value, index)
                if value_end is None:
                    return False
                index = value_end
        return True

    def _parse_writing_policy_chunk_size(self, value):
        size_end = 0
        while size_end < len(value) and value[size_end] in b"0123456789abcdefABCDEF":
            size_end += 1
        if size_end == 0 or not self._valid_chunk_extensions(value, size_end):
            return None
        return int(value[:size_end], 16)

    def _read_writing_policy_chunked_body(self, deadline):
        body = bytearray()
        chunk_count = 0
        while True:
            size_line = self._read_writing_policy_line(
                WRITING_POLICY_MAX_CHUNK_LINE_BYTES,
                deadline,
            )
            if (
                not size_line
                or len(size_line) > WRITING_POLICY_MAX_CHUNK_LINE_BYTES
                or not size_line.endswith(b"\r\n")
            ):
                return None, self._invalid_chunked_body()
            chunk_size = self._parse_writing_policy_chunk_size(size_line[:-2])
            if chunk_size is None:
                return None, self._invalid_chunked_body()
            if chunk_size == 0:
                return self._read_writing_policy_trailers(body, deadline)

            chunk_count += 1
            if chunk_count > WRITING_POLICY_MAX_CHUNK_COUNT:
                return None, self._invalid_chunked_body()
            if (
                len(body) + chunk_size
                > WRITING_POLICY_IMPORT_PREVIEW_REQUEST_MAX_BYTES
            ):
                del body
                return None, _writing_policy_body_too_large()
            chunk = self._read_writing_policy_exact(chunk_size, deadline)
            terminator = self._read_writing_policy_exact(2, deadline)
            if len(chunk) != chunk_size or terminator != b"\r\n":
                return None, self._invalid_chunked_body()
            body.extend(chunk)

    def _read_writing_policy_trailers(self, body, deadline):
        trailer_count = 0
        trailer_bytes = 0
        while True:
            trailer = self._read_writing_policy_line(
                WRITING_POLICY_MAX_TRAILER_LINE_BYTES,
                deadline,
            )
            if not trailer:
                return None, self._invalid_chunked_body()
            trailer_bytes += len(trailer)
            if (
                len(trailer) > WRITING_POLICY_MAX_TRAILER_LINE_BYTES
                or trailer_bytes > WRITING_POLICY_MAX_TRAILER_BYTES
                or not trailer.endswith(b"\r\n")
            ):
                return None, self._invalid_chunked_body()
            if trailer == b"\r\n":
                return bytes(body), None
            trailer_count += 1
            if trailer_count > WRITING_POLICY_MAX_TRAILER_COUNT:
                return None, self._invalid_chunked_body()
            name, separator, value = trailer[:-2].partition(b":")
            if (
                not separator
                or not _HTTP_TOKEN_BYTES_RE.fullmatch(name)
                or not _SAFE_TRAILER_VALUE_BYTES_RE.fullmatch(value)
            ):
                return None, self._invalid_chunked_body()

    @staticmethod
    def _invalid_chunked_body():
        return _writing_policy_request_error(
            400,
            "INVALID_CHUNKED_BODY",
            "分块请求格式无效，请检查后重试。",
        )

    def _read_writing_policy_preview_body(self):
        return self._read_writing_policy_body(preview=True)

    def _read_writing_policy_json_body(self):
        return self._read_writing_policy_body(preview=False)

    def log_message(self, fmt, *args):
        sys.stdout.write(fmt % args + "\n")
        sys.stdout.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        writing_policy_response = dispatch_writing_policy(
            "GET", path, query=parsed.query
        )
        if writing_policy_response is not None:
            self._write_writing_policy_response(writing_policy_response)
            return
        if path == "/health":
            settings = load_settings()
            provider = ProviderClient(settings)
            self._write(
                200,
                envelope(
                    "standalone-health",
                    "adapter.health",
                    {
                        "service": "wps-ai-adapter",
                        "status": "ok",
                        "version": VERSION,
                        "mode": "standalone",
                        "providerName": settings.provider_name,
                        "providerType": settings.provider_type,
                        "providerBaseUrlConfigured": bool(settings.provider_base_url.strip()),
                        "providerConfigured": provider.is_configured(),
                        "providerAuthSource": provider.get_auth_source(),
                        "taskApiKeys": provider.build_task_api_key_status(),
                        "taskRouteCount": 0,
                        "taskRouteConfiguredCount": 0,
                    },
                ),
            )
            return

        if path == "/config":
            settings = load_settings()
            provider = ProviderClient(settings)
            self._write(
                200,
                envelope(
                    "standalone-config",
                    "adapter.config",
                    {
                        "servicePort": settings.service_port,
                        "providerName": settings.provider_name,
                        "providerType": settings.provider_type,
                        "providerBaseUrl": settings.provider_base_url,
                        "providerChatPath": settings.provider_chat_path,
                        "providerMode": settings.provider_mode,
                        "providerBaseUrlConfigured": bool(settings.provider_base_url.strip()),
                        "providerConfigured": provider.is_configured(),
                        "providerAuthSource": provider.get_auth_source(),
                        "taskApiKeys": provider.build_task_api_key_status(),
                        "taskRouteConfiguredCount": 0,
                        "taskRoutes": {},
                        "logPath": settings.log_path,
                        "templateRoot": settings.template_root,
                        "timeoutSeconds": settings.timeout_seconds,
                    },
                ),
            )
            return

        if path == "/templates":
            self._write(200, envelope("standalone-templates", "adapter.templates", {"templates": list_templates()}))
            return

        if path == "/provider/status":
            provider = ProviderClient(load_settings())
            self._write(
                200,
                envelope(
                    "standalone-provider-status",
                    "provider.status",
                    {
                        "configured": provider.is_configured(),
                        "providerName": provider.settings.provider_name,
                        "providerType": provider.settings.provider_type,
                        "authSource": provider.get_auth_source(),
                    },
                ),
            )
            return

        if path == "/provider/route-diagnostics":
            provider = ProviderClient(load_settings())
            self._write(200, envelope("standalone-route-diagnostics", "provider.route_diagnostics", provider.build_route_diagnostics()))
            return

        if path == "/provider/task-api-keys":
            provider = ProviderClient(load_settings())
            self._write(200, envelope("standalone-provider-task-api-keys", "provider.task_api_keys", provider.build_task_api_key_status()))
            return

        if path == "/provider/workflow-profiles":
            task_type = str(parse_qs(parsed.query).get("taskType", [""])[0]).strip()
            try:
                data = WorkflowProfileStore().list_for_task(task_type)
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profiles", "provider.workflow_profiles", data))
            return

        if path == "/provider/debug-last":
            self._write(200, envelope("standalone-provider-debug-last", "provider.debug_last", get_last_provider_debug()))
            return

        if path.startswith("/word/document-review/jobs/"):
            job_id = unquote(path.rsplit("/", 1)[-1])
            job = DOCUMENT_REVIEW_JOB_STORE.get(job_id)
            if not job:
                self._write(
                    404,
                    envelope(
                        job_id,
                        "word.document_review",
                        {"jobId": job_id, "status": "not_found"},
                        success=False,
                        message="文档审查后台任务不存在或已过期。",
                        errors=[{"code": "DOCUMENT_REVIEW_JOB_NOT_FOUND", "message": "文档审查后台任务不存在或已过期。"}],
                    ),
                )
                return
            self._write(200, envelope(job.get("traceId", job_id), "word.document_review", document_review_job_payload(job), message=job["status"]))
            return

        if path.startswith("/excel/analysis/jobs/"):
            job_id = unquote(path.rsplit("/", 1)[-1])
            job = EXCEL_ANALYSIS_JOB_STORE.get(job_id)
            if not job:
                self._write(
                    404,
                    envelope(
                        job_id,
                        "excel.analysis",
                        {"jobId": job_id, "status": "not_found"},
                        success=False,
                        message="智能分析后台任务不存在或已过期。",
                        errors=[{"code": "EXCEL_ANALYSIS_JOB_NOT_FOUND", "message": "智能分析后台任务不存在或已过期。"}],
                    ),
                )
                return
            self._write(200, envelope(job.get("traceId", job_id), "excel.analysis", excel_analysis_job_payload(job), message=job["status"]))
            return

        if path.startswith("/ppt/slide-assistant/jobs/"):
            job_id = unquote(path.rsplit("/", 1)[-1])
            job = PPT_SLIDE_ASSISTANT_JOB_STORE.get(job_id)
            if not job:
                message = "智能总结后台任务不存在或已过期。"
                self._write(
                    404,
                    envelope(
                        job_id,
                        "ppt.slide_assistant",
                        {"jobId": job_id, "status": "not_found"},
                        success=False,
                        message=message,
                        errors=[{"code": "PPT_SLIDE_JOB_NOT_FOUND", "message": message}],
                    ),
                )
                return
            self._write(
                200,
                envelope(
                    job.get("traceId", job_id),
                    "ppt.slide_assistant",
                    ppt_slide_assistant_job_payload(job),
                    message=job["status"],
                ),
            )
            return

        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_writing_policy_route_or_method("POST", path):
            return
        is_writing_policy = _is_writing_policy_path(path)
        if is_writing_policy:
            if path == "/writing-policies/imports/preview":
                raw_bytes, rejection = self._read_writing_policy_preview_body()
            else:
                raw_bytes, rejection = self._read_writing_policy_json_body()
            if rejection is not None:
                self.close_connection = True
                self._write_writing_policy_response(rejection)
                return
        else:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = 0
            if path == "/ppt/document-files" and (
                length <= 0 or self.headers.get("Transfer-Encoding")
            ):
                message = "上传请求缺少有效的 Content-Length，请重新选择文件。"
                self._write(
                    411,
                    envelope(
                        "standalone-ppt-document-file",
                        "ppt.slide_assistant",
                        success=False,
                        message=message,
                        errors=[{"code": "CONTENT_LENGTH_REQUIRED", "message": message}],
                    ),
                )
                return
            if path == "/ppt/document-files" and length > PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES:
                message = "上传请求超过 15 MB 限制，请重新选择文件。"
                self._write(
                    413,
                    envelope(
                        "standalone-ppt-document-file",
                        "ppt.slide_assistant",
                        success=False,
                        message=message,
                        errors=[{"code": "PPT_DOCUMENT_TOO_LARGE", "message": message}],
                    ),
                )
                return
            raw_bytes = self.rfile.read(length) if length else b"{}"
        try:
            raw_body = raw_bytes.decode("utf-8")
            payload = json.loads(raw_body or "{}")
        except (UnicodeDecodeError, ValueError):
            if _is_writing_policy_path(path):
                self._write_writing_policy_response(_writing_policy_validation())
                return
            message = "请求内容格式无效，请检查后重试。"
            self._write(
                400,
                envelope(
                    "standalone-validation",
                    "ppt.slide_assistant" if path.startswith("/ppt/") else "adapter.validation",
                    success=False,
                    message=message,
                    errors=[{"code": "REQUEST_VALIDATION_FAILED", "message": message}],
                ),
            )
            return

        writing_policy_response = dispatch_writing_policy(
            "POST",
            path,
            query=parsed.query,
            payload=payload,
            body_size=len(raw_bytes),
        )
        if writing_policy_response is not None:
            self._write_writing_policy_response(writing_policy_response)
            return

        if path == "/ppt/document-files":
            trace_id = new_trace_id("standalone-ppt-document-file")
            try:
                request = parse_ppt_document_file_request(payload)
                data = PPT_DOCUMENT_FILE_STORE.store(
                    request.file_name,
                    request.mime_type,
                    request.size_bytes,
                    request.content_base64,
                )
            except AdapterError as error:
                self._write(
                    error.status_code,
                    envelope(
                        trace_id,
                        "ppt.slide_assistant",
                        success=False,
                        message=error.message,
                        errors=[{"code": error.code, "message": error.message}],
                    ),
                )
                return
            except ValueError:
                message = "上传请求参数无效，请重新选择文件。"
                self._write(
                    400,
                    envelope(
                        trace_id,
                        "ppt.slide_assistant",
                        success=False,
                        message=message,
                        errors=[{"code": "REQUEST_VALIDATION_FAILED", "message": message}],
                    ),
                )
                return
            self._write(
                200,
                envelope(
                    trace_id,
                    "ppt.slide_assistant",
                    data,
                    message="文档已安全接收。",
                ),
            )
            return

        if path == "/provider/workflow-profiles":
            try:
                profile = WorkflowProfileStore().create_profile(
                    payload.get("taskType", ""),
                    payload.get("name", ""),
                    payload.get("apiKey", ""),
                    note=payload.get("note", ""),
                    activate=bool(payload.get("activate", False)),
                )
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profile", "provider.workflow_profile", {"profile": profile}, message="saved"))
            return

        profile_prefix = "/provider/workflow-profiles/"
        if path.startswith(profile_prefix) and path.endswith("/api-key"):
            profile_id = unquote(path[len(profile_prefix):-len("/api-key")]).strip("/")
            try:
                profile = WorkflowProfileStore().replace_api_key(profile_id, payload.get("apiKey", ""))
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profile-key", "provider.workflow_profile", {"profile": profile}, message="saved"))
            return

        if path.startswith(profile_prefix) and path.endswith("/activate"):
            profile_id = unquote(path[len(profile_prefix):-len("/activate")]).strip("/")
            try:
                data = WorkflowProfileStore().activate_profile(profile_id)
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profile-activate", "provider.workflow_profile", data, message="activated"))
            return

        if path == "/word/smart-write":
            self._write(200, envelope("standalone-word-smart-write", "word.smart_write", smart_write(payload)))
            return

        if path == "/word/smart-imitation":
            self._write(200, envelope("standalone-word-smart-imitation", "word.smart_imitation", smart_imitation(payload)))
            return

        if path == "/word/document-review":
            self._write(200, envelope("standalone-word-document-review", "word.document_review", document_review(payload)))
            return

        if path == "/word/document-review/jobs":
            request = parse_word_request(payload)
            trace_id = new_trace_id("standalone-word-document-review")
            job = DOCUMENT_REVIEW_JOB_STORE.start(request, trace_id=trace_id)
            self._write(200, envelope(trace_id, "word.document_review", document_review_job_payload(job), message="accepted"))
            return

        if path == "/word/format-review":
            self._write(200, envelope("standalone-word-format-review", "word.format_review", format_review(payload)))
            return

        if path == "/excel/analysis":
            self._write(200, envelope("standalone-excel-analysis", "excel.analysis", excel_analysis(payload)))
            return

        if path == "/excel/analysis/jobs":
            request = parse_excel_request(payload)
            trace_id = new_trace_id("standalone-excel-analysis")
            job = EXCEL_ANALYSIS_JOB_STORE.start(request, trace_id=trace_id)
            self._write(200, envelope(trace_id, "excel.analysis", excel_analysis_job_payload(job), message="accepted"))
            return

        if path == "/ppt/slide-assistant/jobs":
            trace_id = new_trace_id("standalone-ppt-slide-assistant")
            try:
                request = parse_ppt_request(payload)
            except ValueError:
                message = "智能总结请求参数无效，请重新读取内容后重试。"
                self._write(
                    400,
                    envelope(
                        trace_id,
                        "ppt.slide_assistant",
                        success=False,
                        message=message,
                        errors=[{"code": "REQUEST_VALIDATION_FAILED", "message": message}],
                    ),
                )
                return
            try:
                job = PPT_SLIDE_ASSISTANT_JOB_STORE.start(request, trace_id=trace_id)
            except AdapterError as error:
                self._write(
                    error.status_code,
                    envelope(
                        trace_id,
                        "ppt.slide_assistant",
                        success=False,
                        message=error.message,
                        errors=[{"code": error.code, "message": error.message}],
                    ),
                )
                return
            self._write(
                200,
                envelope(
                    trace_id,
                    "ppt.slide_assistant",
                    ppt_slide_assistant_job_payload(job),
                    message="accepted",
                ),
            )
            return

        if path == "/provider/base-url":
            try:
                save_provider_base_url(payload.get("baseUrl", ""), provider_name=payload.get("providerName"))
            except ValueError as error:
                self._write(400, envelope("standalone-provider-base-url", "provider.base_url", success=False, message=str(error), errors=[{"code": "INVALID_BASE_URL", "message": str(error)}]))
                return
            client = ProviderClient()
            self._write(
                200,
                envelope(
                    "standalone-provider-base-url",
                    "provider.base_url",
                    {
                        "providerName": client.settings.provider_name,
                        "providerBaseUrl": client.settings.provider_base_url,
                        "providerType": client.settings.provider_type,
                    },
                    message="saved",
                ),
            )
            return

        if path == "/provider/api-key":
            save_local_api_key(payload.get("apiKey", ""))
            client = ProviderClient()
            self._write(200, envelope("standalone-provider-api-key", "provider.api_key", {"configured": client.is_configured(), "authSource": client.get_auth_source()}, message="saved"))
            return

        if path == "/provider/task-api-key":
            task_type = str(payload.get("taskType", "")).strip()
            api_key_ref = str(payload.get("apiKeyRef") or normalize_task_api_key_ref(task_type)).strip()
            try:
                WorkflowProfileStore().save_legacy_task_api_key(task_type, api_key_ref, payload.get("apiKey", ""))
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            client = ProviderClient()
            self._write(200, envelope("standalone-provider-task-api-key", "provider.task_api_key", client.build_task_api_key_status().get(task_type, {}), message="saved"))
            return

        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_writing_policy_route_or_method("PATCH", path):
            return
        try:
            if _is_writing_policy_path(path):
                raw_bytes, rejection = self._read_writing_policy_json_body()
                if rejection is not None:
                    self.close_connection = True
                    self._write_writing_policy_response(rejection)
                    return
                raw_body = raw_bytes.decode("utf-8")
            else:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw_body or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            if _is_writing_policy_path(path):
                self._write_writing_policy_response(_writing_policy_validation())
                return
            self._write(400, envelope("standalone-validation", "adapter.validation", success=False, message="请求内容格式无效，请检查后重试。"))
            return
        writing_policy_response = dispatch_writing_policy(
            "PATCH",
            path,
            query=parsed.query,
            payload=payload,
            body_size=len(raw_bytes) if _is_writing_policy_path(path) else length,
        )
        if writing_policy_response is not None:
            self._write_writing_policy_response(writing_policy_response)
            return
        prefix = "/provider/workflow-profiles/"
        if path.startswith(prefix):
            profile_id = unquote(path[len(prefix):]).strip("/")
            try:
                profile = WorkflowProfileStore().update_profile(
                    profile_id,
                    payload.get("name", ""),
                    payload.get("note", ""),
                )
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profile-update", "provider.workflow_profile", {"profile": profile}, message="saved"))
            return
        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )

    def do_PUT(self):
        path = urlparse(self.path).path
        if _is_writing_policy_path(path):
            self.close_connection = True
            self._write_writing_policy_response(
                dispatch_writing_policy("PUT", path)
            )
            return
        self.send_error(501, "Unsupported method (%r)" % self.command)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        writing_policy_response = dispatch_writing_policy(
            "DELETE", path, query=parsed.query
        )
        if writing_policy_response is not None:
            self._write_writing_policy_response(writing_policy_response)
            return
        if path == "/provider/api-key":
            clear_local_api_key()
            client = ProviderClient()
            self._write(200, envelope("standalone-provider-api-key", "provider.api_key", {"configured": client.is_configured(), "authSource": client.get_auth_source()}, message="cleared"))
            return

        prefix = "/provider/task-api-key/"
        if path.startswith(prefix):
            task_type = unquote(path[len(prefix):])
            try:
                WorkflowProfileStore().clear_active_api_key(task_type)
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-provider-task-api-key", "provider.task_api_key", ProviderClient().build_task_api_key_status().get(task_type, {}), message="cleared"))
            return

        profile_prefix = "/provider/workflow-profiles/"
        if path.startswith(profile_prefix):
            profile_id = unquote(path[len(profile_prefix):]).strip("/")
            try:
                data = WorkflowProfileStore().delete_profile(profile_id)
            except WorkflowProfileError as error:
                self._write_workflow_error(error)
                return
            self._write(200, envelope("standalone-workflow-profile-delete", "provider.workflow_profile", data, message="deleted"))
            return

        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )

    def _write_workflow_error(self, error):
        status_code = 404 if error.code == "WORKFLOW_PROFILE_NOT_FOUND" else 400
        if error.code in {
            "WORKFLOW_PROFILE_ACTIVE",
            "WORKFLOW_PROFILE_LIMIT",
            "WORKFLOW_PROFILE_NAME_DUPLICATE",
        }:
            status_code = 409
        self._write(
            status_code,
            envelope(
                "standalone-workflow-profile-error",
                "provider.workflow_profile",
                success=False,
                message=error.message,
                errors=[{"code": error.code, "message": error.message}],
            ),
        )


def main():
    settings = load_settings()
    server = ThreadingHTTPServer(("127.0.0.1", settings.service_port), Handler)
    print("AI-WPS standalone adapter listening on http://127.0.0.1:{0}".format(settings.service_port))
    server.serve_forever()


if __name__ == "__main__":
    main()
