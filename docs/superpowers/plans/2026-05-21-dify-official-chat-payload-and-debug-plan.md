# Dify Official Chat Payload and Debug Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Dify official `/chat-messages` payload fields and add sanitized adapter diagnostics for the last provider call.

**Architecture:** Keep one provider URL and one API key. Build the complete WPS task prompt once, send it to both top-level `query` and `inputs.query`, and expose only safe call metadata for troubleshooting.

**Tech Stack:** Python 3.8-compatible adapter, FastAPI/standalone HTTP handlers, unittest, WPS HTML/JS task pane.

---

### Task 1: Tests

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Payload tests**

Assert that payloads include:

```python
self.assertEqual(payload["query"], prompt)
self.assertEqual(payload["inputs"], {"query": prompt})
self.assertEqual(payload["response_mode"], "blocking")
self.assertNotIn("input_data", payload)
self.assertNotIn("mode", payload)
```

- [ ] **Step 2: Debug tests**

Add tests that reset debug state, simulate a provider response/error update, and assert:

```python
self.assertEqual(debug["request"]["inputsKeys"], ["query"])
self.assertIn("queryPreview", debug["request"])
self.assertNotIn("Authorization", str(debug))
self.assertNotIn(full_prompt, str(debug))
```

### Task 2: Adapter Payload

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] **Step 1: Change helper output**

`build_provider_request_payload()` and `build_route_request_payload()` return:

```python
{
    "inputs": {"query": query},
    "query": query,
    "conversation_id": "",
    "response_mode": response_mode,
    "user": "wps-ai-assistant",
    "files": [],
}
```

- [ ] **Step 2: Keep task inputs out of the provider request**

`post_task()` still calls `build_provider_request_payload(self.settings, {}, query)`.

### Task 3: Debug Endpoint

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/standalone_adapter.py`

- [ ] **Step 1: Add debug state helpers**

Add module-level `record_provider_debug()` and `get_last_provider_debug()` helpers.

- [ ] **Step 2: Record request/response**

In `post_task()`, record sanitized request metadata before calling upstream, update it with response metadata on success, and update it with error metadata on HTTP/URL errors.

- [ ] **Step 3: Expose endpoint**

Add `GET /provider/debug-last` in FastAPI and standalone modes.

### Task 4: Version, Docs, Package

**Files:**
- Modify version references to `0.11.4-alpha`.
- Modify `README.md`, `README-ZH.md`, `docs/codex-handoff.md`, `phase1-delivery-kit/README.md`.

- [ ] **Step 1: Run full checks**

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_config adapter_service.tests.test_health adapter_service.tests.test_packaging_scripts adapter_service.tests.test_rewriter_modes adapter_service.tests.test_word_rewrite -v
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
PYTHONPYCACHEPREFIX=/private/tmp/ai-wps-pycache PYTHONPATH=adapter_service python3 -m compileall adapter_service/app adapter_service/standalone_adapter.py
git diff --check
```

- [ ] **Step 2: Rebuild package**

```bash
bash packaging/build_phase1_delivery_kit.sh
```
