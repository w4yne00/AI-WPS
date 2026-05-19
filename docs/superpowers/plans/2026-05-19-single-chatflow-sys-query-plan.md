# Single Chatflow sys.query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse adapter AI calls back to one Dify Chat application using `/chat-messages` and top-level `query`.

**Architecture:** Keep current Word API endpoints and prompt builders. Replace runtime task-route selection with one provider endpoint and one global API key, while keeping legacy route fields inert for compatibility.

**Tech Stack:** Python 3.8, FastAPI, unittest, vanilla JS/HTML.

---

## Files

- Modify: `config/adapter.example.json`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/config.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: tests and docs matching the behavior.

## Task 1: Single Chat Payload

- [ ] Add tests that `build_route_request_payload` or replacement unified payload sends top-level `query`, empty `inputs`, `/chat-messages` style fields, and no `source_text` Start variable dependency.
- [ ] Run `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v` and confirm failure.
- [ ] Implement unified Chat payload and route URL behavior.
- [ ] Re-run tests and confirm pass.

## Task 2: Unified Key Configuration

- [ ] Add tests that provider configuration depends on `providerBaseUrl` plus global key, not task route keys.
- [ ] Run provider tests and confirm failure.
- [ ] Update `ProviderClient.is_configured`, diagnostics, `/config`, and standalone config output.
- [ ] Re-run tests and confirm pass.

## Task 3: Settings UI

- [ ] Add layout smoke assertions that global API key controls exist and task route controls do not.
- [ ] Run `node formal-plugin-kit/tests/layout-smoke.test.js` and confirm failure.
- [ ] Restore unified API key UI and remove task route list rendering from the settings page.
- [ ] Run layout smoke and `node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`.

## Task 4: Version, Docs, Delivery

- [ ] Update version to `0.11.2-alpha` and version rule `AI-WPS-P1-WORD-0.11.2-20260519`.
- [ ] Update README, README-ZH, handoff, and config example.
- [ ] Run Python tests, JS checks, compileall, `git diff --check`.
- [ ] Build the Phase 1 delivery kit and validate tar contents.

## Self-Review

- Spec coverage: plan covers unified Chat payload, unified key, UI, version/docs, and delivery.
- Placeholder scan: no placeholders remain.
- Type consistency: fields remain `providerBaseUrl`, `providerChatPath`, `providerConfigured`, `providerAuthSource`, and legacy `taskRoutes` is inert.
