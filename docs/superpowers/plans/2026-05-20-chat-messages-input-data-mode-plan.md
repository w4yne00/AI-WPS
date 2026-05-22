# Chat Messages input_data/mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the single Chat Messages request envelope to match the target interface screenshots: `input_data` plus `mode`, with all task context in top-level `query`.

**Architecture:** Keep the v0.11.2 single-provider, single-key, no-route architecture. Only change the Dify request body field names and version/docs/tests around that contract.

**Tech Stack:** Python 3.8-compatible adapter service, WPS HTML/JS task pane, unittest, Node syntax/layout checks, shell packaging.

---

### Task 1: Lock the Request Envelope With Tests

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Update payload tests**

Change request payload assertions to expect:

```python
self.assertEqual(payload["input_data"], {})
self.assertEqual(payload["query"], "请改写。")
self.assertEqual(payload["conversation_id"], "")
self.assertEqual(payload["mode"], "blocking")
self.assertNotIn("inputs", payload)
self.assertNotIn("response_mode", payload)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected before implementation: payload tests fail because current code returns `inputs` and `response_mode`.

### Task 2: Implement the Envelope Change

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] **Step 1: Update payload helpers**

Return this shape from both `build_provider_request_payload()` and `build_route_request_payload()`:

```python
{
    "input_data": {},
    "query": query,
    "conversation_id": "",
    "mode": response_mode_or_settings_provider_mode,
    "user": "wps-ai-assistant",
    "files": [],
}
```

- [ ] **Step 2: Keep post_task route behavior unchanged**

`ProviderClient.post_task()` should still post to `providerBaseUrl + providerChatPath` and ignore task-specific `input_data`.

- [ ] **Step 3: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: tests pass.

### Task 3: Version and Documentation

**Files:**
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/app/api/health.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`

- [ ] **Step 1: Bump version**

Set adapter, health, diagnostics, startup script, manifest, README, and handoff version references to `0.11.3-alpha`.

- [ ] **Step 2: Document the exact body**

Document that `/chat-messages` uses `input_data`, `query`, `conversation_id`, `mode`, `user`, and `files`, and does not use `inputs` or `response_mode`.

### Task 4: Full Verification and Package

**Files:**
- Modify: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260520.tar.gz` or current dated package path if packaging script keeps the existing date.

- [ ] **Step 1: Run full checks**

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite -v
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
```

- [ ] **Step 2: Rebuild delivery package**

```bash
bash packaging/build_phase1_delivery_kit.sh
```

- [ ] **Step 3: Validate package contents**

```bash
tar -xOf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260520.tar.gz ai-wps-phase1-delivery-20260520/packages/adapter-start-kit/scripts/start_uvicorn_adapter.sh | rg '0\.11\.3-alpha'
tar -xOf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260520.tar.gz ai-wps-phase1-delivery-20260520/packages/adapter-start-kit/config/adapter.example.json | rg 'enterprise-dify-chat|/chat-messages'
```

If the packaging script still emits a 20260519 filename, run the same checks against that path.
