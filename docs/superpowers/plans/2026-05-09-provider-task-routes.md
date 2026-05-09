# Provider Task Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add phase-1 task routing so all Word AI tasks use one provider/API key/workflow while passing a `task_id` for Dify workflow branching.

**Architecture:** Keep the existing single provider settings and add lightweight `taskRoutes` to adapter configuration. ProviderClient resolves a task route per Word task, injects `task_id` into current enterprise payloads, and keeps existing mock fallback and parser behavior.

**Tech Stack:** Python 3.8, FastAPI, pytest/unittest, WPS JS add-in, shell packaging scripts.

---

### Task 1: Config And Provider Route Tests

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/core/config.py`
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] Add tests for loading `taskRoutes`, default route fallback, and Dify payload `task_id` injection.
- [ ] Run targeted tests and verify they fail before implementation.
- [ ] Implement `TaskRoute`, `AppSettings.task_routes`, and provider payload route injection.
- [ ] Run targeted tests and verify they pass.

### Task 2: Runtime Config Surfaces

**Files:**
- Modify: `adapter_service/app/api/config.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `config/adapter.example.json`

- [ ] Return task route summaries from `/config` and route count from `/health`.
- [ ] Mirror compatible route metadata in standalone mode.
- [ ] Update example config with phase-1 route defaults.
- [ ] Run adapter API tests.

### Task 3: Version, Docs, And Deployment Manuals

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Create: `docs/operations/dify-single-workflow-task-routing.md`
- Create: `docs/operations/phase1-v0.9.0-deployment.md`

- [ ] Bump project version to `v0.9.0-alpha` and rule number `AI-WPS-P1-WORD-0.9.0-20260509`.
- [ ] Document Dify single workflow deployment and task_id branches.
- [ ] Document new one-click deployment package usage.
- [ ] Update handoff with current architecture, files, tests, and next prompt.

### Task 4: Packaging And Verification

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `adapter_service/app/main.py`
- Modify: `phase1-delivery-kit/README.md`
- Generated: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260509.tar.gz`

- [ ] Run unit tests for provider, Word APIs, and technical review.
- [ ] Build the phase-1 delivery kit.
- [ ] Verify the generated tarball exists and contains install scripts, docs, plugin files, adapter service, config, templates, and offline dependency packages.
- [ ] Commit and push all changes.
