# Task Routes Path ApiKeyRef Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single Dify workflow `task_id` branching model with adapter-side task routing where each Word task can use its own Dify path and API key reference.

**Architecture:** Keep one `providerBaseUrl` and extend `taskRoutes` with `path`, `apiKeyRef`, `payloadStyle`, `responseMode`, and `outputKey`. `ProviderClient` resolves the route per task, builds Dify chat or workflow request shapes according to the route, and reads route-specific keys from `run/provider_api_keys/<apiKeyRef>` with fallback to the existing default key and environment variable.

**Tech Stack:** Python 3.8 stdlib, existing FastAPI adapter, WPS JS taskpane, unittest.

---

### Task 1: Backend Route Model and Safe Summary

**Files:**
- Modify: `adapter_service/app/core/config.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [ ] Add failing tests for route fields: `path`, `apiKeyRef`, `payloadStyle`, `responseMode`, `outputKey`.
- [ ] Extend `TaskRoute` dataclass with those fields and defaults.
- [ ] Update `load_settings()` to parse route fields without breaking old configs.
- [ ] Update `task_routes_to_dict()` to expose safe route summaries without API key values.
- [ ] Run `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v`.

### Task 2: ProviderClient Route Resolution and Key Lookup

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [ ] Add failing tests for resolving route path/payload style and route-specific API key files.
- [ ] Add `ROUTE_KEY_DIR` and `get_api_key(api_key_ref=None)` with fallback order: route key file, default key file, provider env var.
- [ ] Add `resolve_task_url()`, `resolve_payload_style()`, and `build_route_request_payload()`.
- [ ] Update rewrite, proofread, format preview, and technical review provider calls to use route path/payload style/key.
- [ ] Run provider tests.

### Task 3: Provider Config API for Task Keys

**Files:**
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_packaging_scripts.py` or focused provider tests.

- [ ] Add route-specific key save endpoint: `POST /provider/task-api-key` with `apiKeyRef` and `apiKey`.
- [ ] Add route-specific key clear endpoint: `DELETE /provider/task-api-key/<apiKeyRef>`.
- [ ] Ensure config/status responses expose only configured flags.
- [ ] Add standalone parity for status/config enough for target diagnostics.

### Task 4: WPS Settings UI

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Test: `adapter_service/tests/test_packaging_scripts.py`

- [ ] Add tests asserting settings page contains task route controls.
- [ ] Add task route cards for rewrite, continue, proofread, format preview, and technical review.
- [ ] Display path, payloadStyle, apiKeyRef, and configured status.
- [ ] Allow saving/clearing route-specific keys from the settings page.
- [ ] Keep UI compact and clear; do not reintroduce multi-provider selection.

### Task 5: Config, Docs, Version, Verification

**Files:**
- Modify: `config/adapter.example.json`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Create: `docs/operations/dify-task-routes-path-apikeyref.md`

- [ ] Bump version to `v0.10.0-alpha` and rule `AI-WPS-P1-WORD-0.10.0-20260511`.
- [ ] Document new route fields and Dify app/workflow setup.
- [ ] Run unit tests and compile checks.
- [ ] Commit and push.
