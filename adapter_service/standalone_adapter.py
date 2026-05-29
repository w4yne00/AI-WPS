#!/usr/bin/env python3
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import load_settings, save_provider_base_url, save_task_api_key_ref
from app.core.models import (
    DocumentReviewResponseData,
    FormatReviewResponseData,
    FormatReviewSummary,
    RewriteResponseData,
    WordDocumentRequest,
)
from app.services.provider_client import (
    ProviderClient,
    clear_local_api_key,
    clear_route_api_key,
    get_last_provider_debug,
    normalize_task_api_key_ref,
    save_local_api_key,
    save_route_api_key,
)
from app.services.word.document_reviewer import WordDocumentReviewer
from app.services.word.format_reviewer import WordFormatReviewer
from app.services.word.rewriter import WordRewriter


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT_DIR / "templates"
VERSION = "0.12.9-alpha"


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


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


def document_review(payload):
    request = parse_word_request(payload)
    data = WordDocumentReviewer().review(request, trace_id="standalone-word-document-review")
    if hasattr(DocumentReviewResponseData, "model_validate"):
        return DocumentReviewResponseData.model_validate(data).model_dump(by_alias=True)
    return DocumentReviewResponseData(**data).dict(by_alias=True)


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
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
        path = urlparse(self.path).path
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

        if path == "/provider/debug-last":
            self._write(200, envelope("standalone-provider-debug-last", "provider.debug_last", get_last_provider_debug()))
            return

        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw_body or "{}")

        if path == "/word/smart-write":
            self._write(200, envelope("standalone-word-smart-write", "word.smart_write", smart_write(payload)))
            return

        if path == "/word/document-review":
            self._write(200, envelope("standalone-word-document-review", "word.document_review", document_review(payload)))
            return

        if path == "/word/format-review":
            self._write(200, envelope("standalone-word-format-review", "word.format_review", format_review(payload)))
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
            save_task_api_key_ref(task_type, api_key_ref)
            save_route_api_key(api_key_ref, payload.get("apiKey", ""))
            client = ProviderClient()
            self._write(200, envelope("standalone-provider-task-api-key", "provider.task_api_key", client.build_task_api_key_status().get(task_type, {}), message="saved"))
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
            client = ProviderClient()
            clear_route_api_key(client.get_task_api_key_ref(task_type))
            self._write(200, envelope("standalone-provider-task-api-key", "provider.task_api_key", ProviderClient().build_task_api_key_status().get(task_type, {}), message="cleared"))
            return

        self._write(
            404,
            envelope("standalone-not-found", "adapter.error", success=False, message="Not found", errors=[{"code": "NOT_FOUND", "message": path}]),
        )


def main():
    settings = load_settings()
    server = ThreadingHTTPServer(("127.0.0.1", settings.service_port), Handler)
    print("AI-WPS standalone adapter listening on http://127.0.0.1:{0}".format(settings.service_port))
    server.serve_forever()


if __name__ == "__main__":
    main()
