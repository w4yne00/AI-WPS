#!/usr/bin/env python3
import json
import os
import re
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import load_settings
from app.services.provider_client import ProviderClient, clear_local_api_key, save_local_api_key


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT_DIR / "templates"

SPACE_BEFORE_CHINESE_PUNCTUATION = re.compile(r"\s+[，。！？；：]")


def iter_template_documents():
    for pattern in ("company/*.json", "general/*.json"):
        for path in sorted(TEMPLATE_ROOT.glob(pattern)):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "id" not in data:
                continue
            yield path, data


def load_template(template_id):
    for _, data in iter_template_documents():
        if data["id"] == template_id:
            return data
    if template_id != "general-office":
        return load_template("general-office")
    raise FileNotFoundError("Template not found: {0}".format(template_id))


def list_templates():
    templates = []
    for path, data in iter_template_documents():
        templates.append(
            {
                "id": data["id"],
                "name": data.get("name", data["id"]),
                "path": str(path),
            }
        )
    return templates


def body_paragraphs(payload):
    return [p for p in payload["content"].get("paragraphs", []) if p.get("text", "").strip()]


def font_matches(font_name, rule):
    expected = [rule.get("fontName", "")]
    expected.extend(rule.get("fontAliases", []))
    return font_name.lower() in {item.lower() for item in expected if item}


def normalize_line_spacing(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 10:
        return numeric / 240.0
    return numeric


def paragraph_style_rule(paragraph, template):
    style_name = paragraph.get("styleName") or ""
    if style_name in template.get("styles", {}):
        return template["styles"][style_name]
    outline_level = paragraph.get("outlineLevel") or 0
    if outline_level > 0:
        return template.get("headings", {}).get("level{0}".format(outline_level), {})
    return template.get("body", {})


def proofread(payload):
    issues = []
    template_id = payload.get("options", {}).get("templateId") or "general-office"
    template = load_template(template_id)
    for paragraph in body_paragraphs(payload):
        rule = paragraph_style_rule(paragraph, template)
        if rule.get("fontName") and paragraph.get("fontName") and not font_matches(paragraph.get("fontName"), rule):
            issues.append(
                {
                    "ruleId": "template_font",
                    "severity": "warning",
                    "message": "Paragraph font does not match the selected Word template.",
                    "paragraphIndex": paragraph.get("index"),
                    "suggestion": "Use {0} for this paragraph style.".format(rule.get("fontName")),
                    "autoFixable": True,
                }
            )
        if rule.get("fontSize") is not None and paragraph.get("fontSize") is not None:
            if abs(float(paragraph.get("fontSize")) - float(rule.get("fontSize"))) > 0.01:
                issues.append(
                    {
                        "ruleId": "template_font_size",
                        "severity": "warning",
                        "message": "Paragraph font size does not match the selected Word template.",
                        "paragraphIndex": paragraph.get("index"),
                        "suggestion": "Use {0} pt for this paragraph style.".format(rule.get("fontSize")),
                        "autoFixable": True,
                    }
                )
        if rule.get("lineSpacing") is not None and paragraph.get("lineSpacing") is not None:
            normalized = normalize_line_spacing(paragraph.get("lineSpacing"))
            if normalized is not None and abs(normalized - float(rule.get("lineSpacing"))) > 0.05:
                issues.append(
                    {
                        "ruleId": "template_line_spacing",
                        "severity": "warning",
                        "message": "Paragraph line spacing does not match the selected Word template.",
                        "paragraphIndex": paragraph.get("index"),
                        "suggestion": "Use {0} line spacing.".format(rule.get("lineSpacing")),
                        "autoFixable": True,
                    }
                )

    headings = payload["content"].get("headings", [])
    current_level = 0
    for heading in headings:
      level = heading.get("level", 0)
      if level > current_level + 1:
        issues.append(
            {
                "ruleId": "heading_hierarchy",
                "severity": "warning",
                "message": "Heading levels skip an intermediate level.",
                "suggestion": "Insert the missing heading level or lower this heading level.",
                "autoFixable": False,
            }
        )
      current_level = level

    paragraphs = body_paragraphs(payload)
    fonts = [p.get("fontName") for p in paragraphs if p.get("fontName")]
    if fonts:
        dominant_font = Counter(fonts).most_common(1)[0][0]
        for paragraph in paragraphs:
            if paragraph.get("fontName") and paragraph.get("fontName") != dominant_font:
                issues.append(
                    {
                        "ruleId": "font_consistency",
                        "severity": "warning",
                        "message": "Body text uses a mixed font family.",
                        "paragraphIndex": paragraph.get("index"),
                        "suggestion": "Align the paragraph font with the dominant body font.",
                        "autoFixable": True,
                    }
                )

    sizes = [p.get("fontSize") for p in paragraphs if p.get("fontSize") is not None]
    if sizes:
        dominant_size = Counter(sizes).most_common(1)[0][0]
        for paragraph in paragraphs:
            if paragraph.get("fontSize") is not None and paragraph.get("fontSize") != dominant_size:
                issues.append(
                    {
                        "ruleId": "font_size_consistency",
                        "severity": "warning",
                        "message": "Body text uses a mixed font size.",
                        "paragraphIndex": paragraph.get("index"),
                        "suggestion": "Align the paragraph size with the dominant body size.",
                        "autoFixable": True,
                    }
                )

    for paragraph in paragraphs:
        text = paragraph.get("text", "")
        if "  " in text:
            issues.append(
                {
                    "ruleId": "double_space",
                    "severity": "info",
                    "message": "Repeated whitespace found in the paragraph.",
                    "paragraphIndex": paragraph.get("index"),
                    "suggestion": "Collapse consecutive spaces to a single space.",
                    "autoFixable": True,
                }
            )
        if SPACE_BEFORE_CHINESE_PUNCTUATION.search(text):
            issues.append(
                {
                    "ruleId": "punctuation_spacing",
                    "severity": "info",
                    "message": "Space detected before Chinese punctuation.",
                    "paragraphIndex": paragraph.get("index"),
                    "suggestion": "Remove the space before punctuation.",
                    "autoFixable": True,
                }
            )
    if template.get("aiProofread", {}).get("enabled"):
        text = payload["content"].get("plainText", "").strip()
        try:
            typo_items = ProviderClient(load_settings()).proofread_typos(text, "standalone-word-proofread")
        except Exception:
            typo_items = []
        for item in typo_items:
            issues.append(
                {
                    "ruleId": template.get("aiProofread", {}).get("ruleId", "ai_typo"),
                    "severity": "warning",
                    "message": "AI detected a possible typo or wording issue: {0}".format(item.get("original", "")),
                    "suggestion": "{0}{1}".format(
                        item.get("suggestion", ""),
                        "（{0}）".format(item.get("reason", "")) if item.get("reason") else "",
                    ),
                    "autoFixable": False,
                }
            )
    return issues


def format_preview(payload):
    template_id = payload.get("options", {}).get("templateId") or "general-office"
    template = load_template(template_id)
    body = template.get("body", {})
    changes = []

    for paragraph in body_paragraphs(payload):
        current_style = paragraph.get("styleName") or "Body"
        rule = paragraph_style_rule(paragraph, template)
        target_style = rule.get("styleName", current_style)
        reason_parts = []
        if rule.get("fontName") and paragraph.get("fontName") and not font_matches(paragraph.get("fontName"), rule):
            reason_parts.append("align font with template")
        if rule.get("fontSize") is not None and paragraph.get("fontSize") is not None:
            if abs(float(paragraph.get("fontSize")) - float(rule.get("fontSize"))) > 0.01:
                reason_parts.append("align font size with template")
        if rule.get("lineSpacing") is not None and paragraph.get("lineSpacing") is not None:
            normalized = normalize_line_spacing(paragraph.get("lineSpacing"))
            if normalized is not None and abs(normalized - float(rule.get("lineSpacing"))) > 0.05:
                reason_parts.append("align line spacing with template")
        if (paragraph.get("outlineLevel") or 0) == 0 and rule.get("firstLineIndentChars") and not paragraph.get("text", "").startswith("  "):
            reason_parts.append("apply body first-line indent")

        if reason_parts or current_style != target_style:
            changes.append(
                {
                    "paragraphIndex": paragraph.get("index"),
                    "currentStyle": current_style,
                    "targetStyle": target_style,
                    "reason": "; ".join(reason_parts) or "normalize paragraph style",
                }
            )

    return {
        "changes": changes,
        "summary": {
            "changeCount": len(changes),
            "templateId": template["id"],
        },
    }


def rewrite(payload):
    options = payload.get("options", {})
    mode = options.get("rewriteAction", "rewrite")
    source_text = payload["content"].get("plainText", "").strip()
    if not source_text:
        source_text = "\n".join(
            paragraph.get("text", "")
            for paragraph in payload["content"].get("paragraphs", [])
            if paragraph.get("text", "").strip()
        ).strip()

    provider_result = ProviderClient(load_settings()).rewrite(
        source_text,
        mode,
        trace_id="standalone-word-rewrite",
        user_instruction=options.get("userInstruction", ""),
        style=options.get("rewriteStyle", "default"),
        focus=options.get("focusPoint", "default"),
        length=options.get("lengthMode", "default"),
    )
    rewritten_text = provider_result["rewrittenText"]
    diff_hints = ["Text content changed"]
    if len(rewritten_text) > len(source_text):
        diff_hints.append("Expanded content length")
    if len(rewritten_text) < len(source_text):
        diff_hints.append("Compressed content length")

    return {
        "originalText": source_text,
        "rewrittenText": rewritten_text,
        "rewriteMode": mode,
        "diffHints": diff_hints,
        "provider": provider_result.get("provider", "mock"),
    }


class Handler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            settings = load_settings()
            provider = ProviderClient(settings)
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-health",
                    "taskType": "adapter.health",
                    "message": "completed",
                    "data": {
                        "service": "wps-ai-adapter",
                        "status": "ok",
                        "version": "0.6.1-alpha",
                        "mode": "standalone",
                        "providerType": settings.provider_type,
                        "providerConfigured": provider.is_configured(),
                        "providerAuthSource": provider.get_auth_source(),
                    },
                    "errors": [],
                },
            )
            return
        if path == "/provider/status":
            provider = ProviderClient(load_settings())
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-provider-status",
                    "taskType": "provider.status",
                    "message": "completed",
                    "data": {
                        "configured": provider.is_configured(),
                        "authSource": provider.get_auth_source(),
                        "providerType": provider.settings.provider_type,
                    },
                    "errors": [],
                },
            )
            return
        if path == "/templates":
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-templates",
                    "taskType": "adapter.templates",
                    "message": "completed",
                    "data": {"templates": list_templates()},
                    "errors": [],
                },
            )
            return
        self._write(
            404,
            {
                "success": False,
                "traceId": "standalone-not-found",
                "taskType": "adapter.error",
                "message": "Not found",
                "data": {},
                "errors": [{"code": "NOT_FOUND", "message": path}],
            },
        )

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw_body or "{}")

        if path == "/word/proofread":
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-word-proofread",
                    "taskType": "word.proofread",
                    "message": "completed",
                    "data": {"issues": proofread(payload)},
                    "errors": [],
                },
            )
            return

        if path == "/word/format-preview":
            preview = format_preview(payload)
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-word-format-preview",
                    "taskType": "word.format_preview",
                    "message": "completed",
                    "data": preview,
                    "errors": [],
                },
            )
            return

        if path == "/word/rewrite":
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-word-rewrite",
                    "taskType": "word.rewrite",
                    "message": "completed",
                    "data": rewrite(payload),
                    "errors": [],
                },
            )
            return
        if path == "/provider/api-key":
            api_key = payload.get("apiKey", "").strip()
            if not api_key:
                self._write(
                    400,
                    {
                        "success": False,
                        "traceId": "standalone-provider-save",
                        "taskType": "provider.api_key",
                        "message": "API key is required.",
                        "data": {},
                        "errors": [{"code": "API_KEY_REQUIRED", "message": "API key is required."}],
                    },
                )
                return
            save_local_api_key(api_key)
            provider = ProviderClient(load_settings())
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-provider-save",
                    "taskType": "provider.api_key",
                    "message": "saved",
                    "data": {
                        "configured": provider.is_configured(),
                        "authSource": provider.get_auth_source(),
                    },
                    "errors": [],
                },
            )
            return

        self._write(
            404,
            {
                "success": False,
                "traceId": "standalone-not-found",
                "taskType": "adapter.error",
                "message": "Not found",
                "data": {},
                "errors": [{"code": "NOT_FOUND", "message": path}],
            },
        )

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == "/provider/api-key":
            clear_local_api_key()
            provider = ProviderClient(load_settings())
            self._write(
                200,
                {
                    "success": True,
                    "traceId": "standalone-provider-clear",
                    "taskType": "provider.api_key",
                    "message": "cleared",
                    "data": {
                        "configured": provider.is_configured(),
                        "authSource": provider.get_auth_source(),
                    },
                    "errors": [],
                },
            )
            return

        self._write(
            404,
            {
                "success": False,
                "traceId": "standalone-not-found",
                "taskType": "adapter.error",
                "message": "Not found",
                "data": {},
                "errors": [{"code": "NOT_FOUND", "message": path}],
            },
        )


def main():
    port = int(os.environ.get("ADAPTER_PORT", sys.argv[1] if len(sys.argv) > 1 else "18100"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("standalone_adapter_started port={0}".format(port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
