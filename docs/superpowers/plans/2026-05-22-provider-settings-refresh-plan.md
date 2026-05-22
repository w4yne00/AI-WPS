# Provider Settings Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make uvicorn Word tasks observe provider URL changes saved after adapter startup.

**Architecture:** Default provider clients reload config-backed settings before provider configuration checks and forwarding. Explicitly injected settings stay fixed so test and internal call boundaries remain deterministic.

**Tech Stack:** Python provider client, unittest, adapter packaging.

---

### Task 1: Reproduce Stale Settings

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [x] Add a test where default `ProviderClient()` loads an empty startup URL,
  then sees a configured URL on the next settings load.
- [x] Run the test and verify it fails because the old settings are cached.

### Task 2: Refresh Config-Backed Provider Clients

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`

- [x] Track whether a provider client was built from default config loading.
- [x] Reload settings before `is_configured()` and `post_task()` for default
  clients.
- [x] Keep `ProviderClient(settings)` instances fixed.
- [x] Run targeted provider tests for the new behavior and mock diagnostics.

### Task 3: Document, Validate, Package

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`

- [x] Bump the release to `v0.11.7-alpha`.
- [x] Run the full Python, JS, Bash syntax, compile, and diff checks.
- [x] Rebuild and inspect the Phase 1 delivery package.
