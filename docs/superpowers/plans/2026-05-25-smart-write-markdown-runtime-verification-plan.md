# Smart Write Markdown Runtime Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Smart Write Markdown rendering verifiable on target WPS installations by invalidating cached frontend resources and exposing sanitized response-format diagnostics.

**Architecture:** Keep the existing Markdown renderer and Dify `/chat-messages` integration unchanged. Add a build token at the WPS task-pane resource boundary, then extend provider debug sanitization with booleans derived from the model answer only.

**Tech Stack:** WPS JS task pane, Python adapter, Node assertion smoke tests, Python `unittest`, Bash delivery packaging.

---

### Task 1: Frontend build-token coverage

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`

- [ ] Add smoke assertions requiring `build=0.12.1-alpha`, versioned CSS/helper/script references, and a visible frontend version node.
- [ ] Run `node formal-plugin-kit/tests/layout-smoke.test.js` and confirm it fails before implementation.
- [ ] Add the fixed build token to the task-pane URL and its CSS/JS resource URLs; populate the frontend version text during initialization.
- [ ] Run the smoke test and `node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js` and confirm they pass.

### Task 2: Sanitized Markdown-format diagnostics

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] Extend `test_provider_debug_records_sanitized_request_and_response` with a Markdown answer and expected `answerFormat` booleans.
- [ ] Run the targeted unittest and confirm it fails because `answerFormat` is absent.
- [ ] Add a private Markdown-format summary helper and include its booleans in `_sanitize_provider_response`.
- [ ] Run the targeted unittest and the provider test suite and confirm they pass.

### Task 3: Release metadata and delivery

**Files:**
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `README-ZH.md`
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`
- Test: `adapter_service/tests/test_health.py`
- Test: `adapter_service/tests/test_packaging_scripts.py`

- [ ] Update release assertions from `0.12.0-alpha` to `0.12.1-alpha` and run them to confirm failure.
- [ ] Update runtime and documentation metadata to `v0.12.1-alpha` / `AI-WPS-P1-WORD-0.12.1-20260525`.
- [ ] Build `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260525.tar.gz`.
- [ ] Run Python, Node, syntax, compile and diff checks recorded in the handoff.
