# Task Route Key Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v0.11.1-alpha route selection deterministic by removing global key status from normal task routing, merging default task routes into old configs, and adding route diagnostics.

**Architecture:** Keep the existing FastAPI adapter and static WPS taskpane structure. Add small focused helpers in `app.core.config` and `ProviderClient`, expose diagnostics through the existing provider router, and update the taskpane settings summary to show URL status instead of global key status.

**Tech Stack:** Python 3.8, FastAPI, unittest, vanilla JS/HTML, shell scripts.

---

## Files

- Modify: `adapter_service/app/core/config.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/config.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/tests/test_config.py`
- Modify: `adapter_service/tests/test_health.py`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

## Task 1: Config Route Merge and Task Key Semantics

**Files:**
- Modify: `adapter_service/app/core/config.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Write failing tests**

Add tests that load an old `adapter.json` with no `taskRoutes` and assert that default routes from `adapter.example.json` are present. Add a test that `word.smart_write` does not fall back to env/default key when `apiKeyRef=smart_write`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: new config merge test fails because default routes are not merged into old configs.

- [ ] **Step 3: Implement config merge**

Update `load_settings()` so default task routes from `adapter.example.json` are merged when user config omits them. Preserve user route overrides.

- [ ] **Step 4: Verify tests pass**

Run the same unittest command. Expected: pass.

## Task 2: Route Diagnostics API

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/provider.py`
- Test: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Write failing tests**

Add tests for a diagnostics payload that contains `word.smart_write` URL, `apiKeyRef`, `payloadStyle`, `outputKey`, `configured`, and `authSource`, and does not contain API Key values.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: diagnostics helper or route is missing.

- [ ] **Step 3: Implement diagnostics**

Add `ProviderClient.build_route_diagnostics()` and expose `GET /provider/route-diagnostics`.

- [ ] **Step 4: Verify tests pass**

Run the same unittest command. Expected: pass.

## Task 3: Health and Config Cleanup

**Files:**
- Modify: `adapter_service/app/api/config.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_config.py`
- Test: `adapter_service/tests/test_health.py`

- [ ] **Step 1: Write failing tests**

Assert `/config` and `/health` return `providerBaseUrlConfigured` and `taskRouteConfiguredCount`, and no longer return `providerAuthSource`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_config adapter_service.tests.test_health -v
```

Expected: tests fail on missing new fields or old global auth field still present.

- [ ] **Step 3: Implement cleanup**

Update FastAPI and standalone responses to use URL/task-route status fields.

- [ ] **Step 4: Verify tests pass**

Run the same unittest command. Expected: pass.

## Task 4: Taskpane Settings UI Cleanup

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Write failing JS smoke assertion**

Assert the rendered settings markup no longer includes `provider-auth-line` or `密钥：未检测`, while task route items still render per-task key controls.

- [ ] **Step 2: Run JS test and verify failure**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: test fails because the legacy provider auth line still exists.

- [ ] **Step 3: Implement UI cleanup**

Remove the global auth status element and JS state/update calls. Keep task route key save/clear controls.

- [ ] **Step 4: Verify JS test and syntax**

Run:

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
```

Expected: pass.

## Task 5: Version and Documentation

**Files:**
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: Write/update version tests**

Update packaging tests to assert `EXPECTED_VERSION` is `0.11.1-alpha`.

- [ ] **Step 2: Run version-related tests**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected before implementation: failure if the script still uses `0.10.1-alpha`.

- [ ] **Step 3: Update version constants and docs**

Set app, health, standalone, manifest/docs references to `0.11.1-alpha` and version rule `AI-WPS-P1-WORD-0.11.1-20260519`.

- [ ] **Step 4: Verify full relevant suite**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite -v
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
```

Expected: pass, with documented skips only if local FastAPI/Pydantic deps are unavailable.

## Self-Review

- Spec coverage: tasks cover config merge, task-only keys, diagnostics, UI cleanup, version sync, and docs.
- Placeholder scan: no implementation placeholder remains; each task has concrete files and commands.
- Type consistency: field names are consistent with the design: `providerBaseUrlConfigured`, `taskRouteConfiguredCount`, `apiKeyRef`, `authSource`, `outputKey`.
