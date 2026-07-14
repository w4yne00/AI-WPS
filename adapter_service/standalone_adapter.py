#!/usr/bin/env python3
import json
import sys
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
VERSION = "0.17.0-alpha"
PPT_DOCUMENT_UPLOAD_REQUEST_MAX_BYTES = 15 * 1024 * 1024
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
                        message="Excel 智能分析后台任务不存在或已过期。",
                        errors=[{"code": "EXCEL_ANALYSIS_JOB_NOT_FOUND", "message": "Excel 智能分析后台任务不存在或已过期。"}],
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
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        if path == "/ppt/document-files" and length <= 0:
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
        try:
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw_body or "{}")
        except (UnicodeDecodeError, ValueError):
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
            job = PPT_SLIDE_ASSISTANT_JOB_STORE.start(request, trace_id=trace_id)
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
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw_body or "{}")
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

    def do_DELETE(self):
        path = urlparse(self.path).path
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
