# Uvicorn Adapter Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the start-kit scripts operate and diagnose the uvicorn adapter consistently and make mock fallback visible in provider debug output.

**Architecture:** Preserve the existing provider fallback behavior, but record a sanitized debug event before returning mock data. Route operator scripts through `start_uvicorn_adapter.sh`, expose provider diagnostics from health/status/log commands, and keep stop behavior robust when PID tracking is stale.

**Tech Stack:** Bash operations scripts, Python provider client tests, offline adapter packaging.

---

### Task 1: Lock Provider Fallback Diagnostics

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py`

- [x] Add a failing test proving smart-write mock fallback writes a sanitized
  `provider_not_configured` debug record.
- [x] Extend provider debug sanitization with safe fallback fields.
- [x] Record mock debug events before smart write, legacy rewrite, and technical
  review return fallback data.

### Task 2: Lock Uvicorn Script Behavior

**Files:**
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `adapter-start-kit/scripts/*.sh`

- [x] Add packaging checks for uvicorn start/restart, provider diagnostic URLs,
  mock log hints, and port-listener stop logic.
- [x] Make `start_adapter.sh` call `start_uvicorn_adapter.sh`.
- [x] Make restart use uvicorn start after stop.
- [x] Expand health/status/log scripts with provider readiness and debug output.
- [x] Expand stop and environment checks for target-machine uvicorn operations.

### Task 3: Validate and Package

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `adapter-start-kit/README.md`
- Modify: `docs/codex-handoff.md`

- [x] Bump version to `v0.11.6-alpha` and document `provider=mock`.
- [x] Run the full Python and JS check set from `docs/codex-handoff.md`.
- [x] Run Bash syntax checks for the start-kit scripts.
- [x] Rebuild and inspect the Phase 1 delivery package.
