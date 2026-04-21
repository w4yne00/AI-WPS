# WPS Phase 1 Foundation + Word Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Phase 1 baseline for the WPS AI assistant plugin on Kylin V10 ARM with an offline-installable WPS add-in, a local Python 3.8 adapter service, and Word capabilities for proofreading, formatting preview, and rewrite/continuation.

**Architecture:** The implementation uses a thin WPS JS/HTML plugin for UI and document object access, plus a local Python 3.8 HTTP adapter service that owns configuration, templates, task routing, rule engines, Dify integration, logging, and diagnostics. All runtime dependencies are packaged for offline deployment, and all document mutations require preview plus user confirmation.

**Tech Stack:** WPS JS/HTML add-in, TypeScript, Vite, Python 3.8, FastAPI or Flask-compatible local HTTP service, `pytest`, `requests`, offline wheel bundle, JSON template files, shell install scripts.

---

## Execution Notes

- Build the smallest working path first: `health -> config -> templates -> proofread -> format-preview -> rewrite`
- Do not implement Excel or PPT paths in this plan
- Keep all Word mutations behind preview plus explicit apply
- Keep business rules in external template files, not in UI code
- Prefer deterministic proofreading and formatting logic over model-driven formatting
- Package all Python dependencies as offline wheels before target deployment
