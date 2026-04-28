#!/usr/bin/env python3
import json
import os
import re
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT_DIR / "templates"

SPACE_BEFORE_CHINESE_PUNCTUATION = re.compile(r"\s+[，。！？；：]")


def load_template(template_id):
    for pattern in ("company/*.json", "general/*.json"):
        for path in sorted(TEMPLATE_ROOT.glob(pattern)):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["id"] == template_id:
                return data
    if template_id != "general-office":
        return load_template("general-office")
    raise FileNotFoundError("Template not found: {0}".format(template_id))


def list_templates():
    templates = []
    for pattern in ("company/*.json", "general/*.json"):
        for path in sorted(TEMPLATE_ROOT.glob(pattern)):
            data = json.loads(path.read_text(encoding="utf-8"))
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


def proofread(payload):
    issues = []
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
    return issues


def format_preview(payload):
    template_id = payload.get("options", {}).get("templateId") or "general-office"
    template = load_template(template_id)
    body = template.get("body", {})
    body_font = body.get("fontName")
    body_size = body.get("fontSize")
    changes = []

    for paragraph in body_paragraphs(payload):
        current_style = paragraph.get("styleName") or "Body"
        target_style = current_style
        reason_parts = []
        outline_level = paragraph.get("outlineLevel") or 0
        if outline_level > 0:
            target_style = "Heading {0}".format(outline_level)
            heading = template.get("headings", {}).get("level{0}".format(outline_level), {})
            if paragraph.get("fontName") != heading.get("fontName"):
                reason_parts.append("align heading font with template")
            if paragraph.get("fontSize") != heading.get("fontSize"):
                reason_parts.append("align heading size with template")
        else:
            target_style = "Body"
            if paragraph.get("fontName") != body_font:
                reason_parts.append("align body font with template")
            if paragraph.get("fontSize") != body_size:
                reason_parts.append("align body size with template")
            if not paragraph.get("text", "").startswith("  "):
                reason_parts.append("apply body indent and spacing defaults")

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
    selection_mode = payload.get("selectionMode", "document")
    mode = "continue" if selection_mode == "selection" else "rewrite"
    source_text = payload["content"].get("plainText", "").strip()
    if not source_text:
        source_text = "\n".join(
            paragraph.get("text", "")
            for paragraph in payload["content"].get("paragraphs", [])
            if paragraph.get("text", "").strip()
        ).strip()

    prefix = {
        "rewrite": "Rewritten draft:",
        "continue": "Continued draft:",
        "polish": "Polished draft:",
        "formalize": "Formalized draft:",
    }.get(mode, "Rewritten draft:")
    rewritten_text = "{0}\n{1}".format(prefix, source_text)
    diff_hints = ["Text content changed"]
    if len(rewritten_text) > len(source_text):
        diff_hints.append("Expanded content length")

    return {
        "originalText": source_text,
        "rewrittenText": rewritten_text,
        "rewriteMode": mode,
        "diffHints": diff_hints,
    }


class Handler(BaseHTTPRequestHandler):
    def _write(self, status_code, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        sys.stdout.write(fmt % args + "\n")
        sys.stdout.flush()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
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
                        "version": "0.1.0",
                        "mode": "standalone",
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
