# Dify Chat Input Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the adapter automatically support both legacy Dify Chatflows that require `inputs.query` and new User Input node Chatflows that require an empty `inputs` object with top-level `query` and `files`.

**Architecture:** Keep every task on the existing unified `/chat-messages` path. Add two explicit request input modes inside `provider_client.py`, negotiate once by retrying only HTTP 400 responses, and cache the successful mode by provider URL, path, task type, and task API-key reference. Preserve all task prompts, authentication, timeout, answer parsing, frontend behavior, and writeback behavior.

**Tech Stack:** Python 3.8, standard-library `urllib`, `unittest`, existing FastAPI/standalone adapter packaging.

---

## File Map

- Modify `adapter_service/app/services/provider_client.py`: build both Dify Chat input shapes, negotiate on HTTP 400, cache the successful mode, and expose sanitized diagnostics.
- Modify `adapter_service/tests/test_enterprise_provider.py`: lock legacy behavior, new User Input node fallback, cache isolation, and non-400 behavior.
- Modify `docs/codex-handoff.md`: document the runtime compatibility behavior and protected boundaries.
- Modify `README.md` and `README-ZH.md`: add the compatibility release note.
- Modify existing version metadata and version assertions from `0.15.1-alpha` to `0.15.2-alpha`.
- Build `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260703.tar.gz`.

### Task 1: Define And Test Both Chat Input Shapes

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py:289-324`

- [ ] **Step 1: Write failing payload-shape tests**

Add imports for the two mode constants and extend the existing payload tests:

```python
import json
from io import BytesIO
from urllib.error import HTTPError

from app.core.errors import ProviderUnavailableError
from app.services.provider_client import (
    DIFY_INPUT_MODE_LEGACY,
    DIFY_INPUT_MODE_USER_INPUT,
    build_provider_request_payload,
)


def test_build_provider_request_payload_keeps_legacy_inputs_query(self) -> None:
    settings = AppSettings(provider_mode="blocking")

    payload = build_provider_request_payload(
        settings,
        {},
        "完整提示词",
        input_mode=DIFY_INPUT_MODE_LEGACY,
    )

    self.assertEqual(payload["inputs"], {"query": "完整提示词"})
    self.assertEqual(payload["query"], "完整提示词")
    self.assertEqual(payload["files"], [])


def test_build_provider_request_payload_supports_user_input_node(self) -> None:
    settings = AppSettings(provider_mode="blocking")

    payload = build_provider_request_payload(
        settings,
        {},
        "完整提示词",
        input_mode=DIFY_INPUT_MODE_USER_INPUT,
    )

    self.assertEqual(payload["inputs"], {})
    self.assertEqual(payload["query"], "完整提示词")
    self.assertEqual(payload["files"], [])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_keeps_legacy_inputs_query \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_supports_user_input_node -v
```

Expected: FAIL because the mode constants and `input_mode` argument do not exist.

- [ ] **Step 3: Implement the two explicit payload modes**

Add near the payload builders:

```python
DIFY_INPUT_MODE_LEGACY = "legacy-input-query"
DIFY_INPUT_MODE_USER_INPUT = "user-input-node"


def build_provider_request_payload(
    settings: AppSettings,
    input_data: Dict,
    query: str,
    input_mode: str = DIFY_INPUT_MODE_LEGACY,
) -> Dict:
    inputs = {"query": query} if input_mode == DIFY_INPUT_MODE_LEGACY else {}
    return {
        "inputs": inputs,
        "query": query,
        "conversation_id": "",
        "response_mode": settings.provider_mode,
        "user": "wps-ai-assistant",
        "files": [],
    }
```

Keep `build_route_request_payload` behavior unchanged because active task calls use `post_task` and `build_provider_request_payload`; do not restore task-route transport behavior.

- [ ] **Step 4: Run payload and existing provider-shape tests**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_keeps_legacy_inputs_query \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_supports_user_input_node \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_uses_unified_chat_sys_query_shape \
  adapter_service.tests.test_enterprise_provider.EnterpriseProviderTests.test_build_provider_request_payload_ignores_input_data_for_chat_message_shape -v
```

Expected: PASS.

### Task 2: Negotiate On HTTP 400 And Cache The Successful Mode

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py:710-970`

- [ ] **Step 1: Write failing HTTP negotiation tests**

Use a local fake response context manager and patched `urllib_request.urlopen`:

```python
class FakeProviderResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def make_http_error(status, body):
    return HTTPError(
        "https://aibot.example/v1/chat-messages",
        status,
        "Bad Request",
        {},
        BytesIO(json.dumps(body, ensure_ascii=False).encode("utf-8")),
    )
```

Add this helper to `EnterpriseProviderTests`:

```python
def _configured_provider_client(
    self,
    base_url="https://aibot.example/v1",
    task_api_key_refs=None,
):
    return ProviderClient(
        AppSettings(
            provider_base_url=base_url,
            provider_chat_path="/chat-messages",
            provider_mode="blocking",
            task_api_key_refs=task_api_key_refs or {},
        )
    )
```

Add tests:

```python
@patch("app.services.provider_client.urllib_request.urlopen")
def test_post_task_retries_http_400_with_user_input_node(self, urlopen) -> None:
    urlopen.side_effect = [
        make_http_error(400, {"code": "invalid_param", "message": "query is not allowed in inputs"}),
        FakeProviderResponse({"answer": "新版工作流结果"}),
    ]
    client = self._configured_provider_client()

    with patch("app.services.provider_client._PROVIDER_INPUT_MODE_CACHE", {}):
        result = client.post_task("word.smart_write", "trace-new-dify", {}, "完整提示词")

    self.assertEqual(result["answer"], "新版工作流结果")
    first_body = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
    second_body = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
    self.assertEqual(first_body["inputs"], {"query": "完整提示词"})
    self.assertEqual(second_body["inputs"], {})


@patch("app.services.provider_client.urllib_request.urlopen")
def test_post_task_reuses_cached_user_input_mode(self, urlopen) -> None:
    urlopen.side_effect = [
        make_http_error(400, {"code": "invalid_param"}),
        FakeProviderResponse({"answer": "第一次"}),
        FakeProviderResponse({"answer": "第二次"}),
    ]
    client = self._configured_provider_client()

    with patch("app.services.provider_client._PROVIDER_INPUT_MODE_CACHE", {}):
        client.post_task("word.smart_write", "trace-first", {}, "第一次提示词")
        client.post_task("word.smart_write", "trace-second", {}, "第二次提示词")

    third_body = json.loads(urlopen.call_args_list[2].args[0].data.decode("utf-8"))
    self.assertEqual(third_body["inputs"], {})
    self.assertEqual(urlopen.call_count, 3)


@patch("app.services.provider_client.urllib_request.urlopen")
def test_post_task_does_not_retry_non_400_http_errors(self, urlopen) -> None:
    urlopen.side_effect = make_http_error(500, {"message": "server error"})
    client = self._configured_provider_client()

    with patch("app.services.provider_client._PROVIDER_INPUT_MODE_CACHE", {}):
        with self.assertRaises(ProviderUnavailableError):
            client.post_task("word.smart_write", "trace-500", {}, "完整提示词")

    self.assertEqual(urlopen.call_count, 1)
```

Patch `_PROVIDER_INPUT_MODE_CACHE` with a fresh dictionary in each cache-related test so tests do not share process state.

- [ ] **Step 2: Run negotiation tests and verify RED**

Run the three new tests with `python3 -m unittest ... -v`.

Expected: the first test raises `ProviderUnavailableError` after the first HTTP 400, the cache test does not reach a third successful request, and the non-400 test already makes one call.

- [ ] **Step 3: Add cache keys and sanitized HTTP error body parsing**

Add:

```python
DIFY_INPUT_MODES = (DIFY_INPUT_MODE_LEGACY, DIFY_INPUT_MODE_USER_INPUT)
_PROVIDER_INPUT_MODE_CACHE: Dict[str, str] = {}


def _provider_input_mode_cache_key(settings: AppSettings, task_type: str, api_key_ref: str) -> str:
    return "|".join(
        [
            settings.provider_base_url.rstrip("/"),
            settings.provider_chat_path or "/chat-messages",
            task_type,
            api_key_ref,
        ]
    )


def _read_http_error_body(exc: error.HTTPError, limit: int = 480) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    return raw[:limit]
```

Do not include the API key value in the cache key or diagnostics.

- [ ] **Step 4: Implement one-time HTTP 400 negotiation**

In `ProviderClient.post_task`:

1. Resolve the cache key.
2. Use cached mode when present, otherwise legacy mode.
3. On HTTP 400, retry exactly once with the alternate mode.
4. Cache only a successful mode.
5. Keep existing 401/403 handling, timeout conversion, and unavailable errors.

The control flow should be equivalent to:

```python
cache_key = _provider_input_mode_cache_key(
    self.settings,
    task_type,
    self.get_task_api_key_ref(task_type),
)
preferred_mode = _PROVIDER_INPUT_MODE_CACHE.get(cache_key, DIFY_INPUT_MODE_LEGACY)
attempt_modes = [preferred_mode]
alternate_mode = (
    DIFY_INPUT_MODE_USER_INPUT
    if preferred_mode == DIFY_INPUT_MODE_LEGACY
    else DIFY_INPUT_MODE_LEGACY
)
attempt_modes.append(alternate_mode)

for attempt_index, input_mode in enumerate(attempt_modes, start=1):
    route_payload = build_provider_request_payload(
        self.settings,
        {},
        query,
        input_mode=input_mode,
    )
    try:
        body = self._send_chat_request(...)
        _PROVIDER_INPUT_MODE_CACHE[cache_key] = input_mode
        return body
    except error.HTTPError as exc:
        error_body = _read_http_error_body(exc)
        if exc.code == 400 and attempt_index == 1:
            continue
        if exc.code in (401, 403):
            raise ProviderAuthError() from exc
        raise ProviderUnavailableError(
            "Enterprise AI returned HTTP {0}.".format(exc.code)
        ) from exc
```

Keep the two-attempt loop inside `post_task`; do not introduce a new transport abstraction. Preserve the existing URL construction, headers, timeout selection, JSON response parsing, `URLError`, socket timeout, 401/403, and non-JSON response handling.

- [ ] **Step 5: Add and verify cache isolation tests**

Add tests that change one field at a time:

```python
def test_input_mode_cache_is_isolated_by_task_type(...):
    # Negotiate word.smart_write to user-input-node.
    # First word.document_review request must still use legacy inputs.query.


def test_input_mode_cache_is_isolated_by_provider_url(...):
    # Negotiate URL A to user-input-node.
    # First request to URL B must still use legacy inputs.query.


def test_input_mode_cache_is_isolated_by_task_api_key_ref(...):
    # Negotiate ref A to user-input-node.
    # First request using ref B must still use legacy inputs.query.
```

Run all new negotiation and isolation tests.

Expected: PASS with no more than two calls for a first-time HTTP 400 negotiation and one call for cached requests.

### Task 3: Preserve Diagnostics And Existing Error Semantics

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py:334-390, 850-970`

- [ ] **Step 1: Write failing diagnostics tests**

After an old-format 400 and successful new-format retry, assert:

```python
debug = get_last_provider_debug()
self.assertEqual(debug["inputMode"], "user-input-node")
self.assertTrue(debug["compatibilityFallback"])
self.assertEqual(debug["attemptCount"], 2)
self.assertNotIn("完整提示词", json.dumps(debug, ensure_ascii=False))
```

After both attempts return HTTP 400, assert:

```python
debug = get_last_provider_debug()
self.assertEqual(debug["error"]["status"], 400)
self.assertIn("invalid_param", debug["error"]["bodyPreview"])
self.assertLessEqual(len(debug["error"]["bodyPreview"]), 480)
```

- [ ] **Step 2: Run diagnostics tests and verify RED**

Expected: FAIL because `inputMode`, `compatibilityFallback`, `attemptCount`, and `bodyPreview` are not recorded.

- [ ] **Step 3: Add attempt metadata to existing debug records**

Include only non-sensitive metadata:

```python
{
    "inputMode": input_mode,
    "compatibilityFallback": attempt_index > 1,
    "attemptCount": attempt_index,
}
```

For HTTP errors include:

```python
"error": {
    "type": "HTTPError",
    "status": exc.code,
    "message": str(exc),
    "bodyPreview": error_body,
}
```

Keep `_sanitize_provider_body` in the path for request payloads so full prompts never appear in `/provider/debug-last`.

- [ ] **Step 4: Run all provider tests**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: PASS.

### Task 4: Version, Documentation, Regression Tests, And Delivery Package

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: current version metadata and corresponding tests in `adapter_service`, `formal-plugin-kit`, and `adapter-start-kit`
- Build: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260703.tar.gz`

- [ ] **Step 1: Update compatibility documentation**

Document:

- `/chat-messages` remains unchanged.
- Legacy mode sends `inputs.query`.
- User Input node mode sends `inputs: {}` with top-level `query` and `files`.
- HTTP 400 triggers one compatibility retry.
- Successful mode is cached per URL/path/task/key reference.
- No frontend, task prompt, timeout, result parser, or writeback changes.

- [ ] **Step 2: Bump the synchronized version**

Update current runtime and cache metadata from `0.15.1-alpha` to `0.15.2-alpha`, preserving historical release entries. Use version rule:

```text
AI-WPS-P1-WORD-EXCEL-0.15.2-20260703
```

- [ ] **Step 3: Run complete verification**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/app/services/provider_client.py adapter_service/standalone_adapter.py adapter_service/app/main.py
bash -n packaging/build_phase1_delivery_kit.sh
bash -n phase1-delivery-kit/installer/install_phase1.sh
git diff --check
```

Expected: all tests pass; only existing FastAPI-dependent skips remain.

- [ ] **Step 4: Build and inspect the delivery package**

Run:

```bash
DATE_TAG=20260703 bash packaging/build_phase1_delivery_kit.sh
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260703.tar.gz
```

Extract to a temporary directory and verify the package contains:

- `provider_client.py` with both input modes and HTTP 400 fallback.
- Version `0.15.2-alpha`.
- Both Word and Excel add-ins.
- Existing configuration-preservation installer logic.

- [ ] **Step 5: Commit implementation deliberately**

Stage only source, tests, documentation, version metadata, and the new `20260703` package. Do not stage unrelated historical package deletions or modifications.

```bash
git add adapter_service/app/services/provider_client.py \
  adapter_service/tests/test_enterprise_provider.py \
  README.md README-ZH.md docs/codex-handoff.md \
  adapter-start-kit/scripts/start_uvicorn_adapter.sh \
  adapter_service/app/api/health.py adapter_service/app/main.py \
  adapter_service/standalone_adapter.py \
  adapter_service/tests/test_health.py \
  adapter_service/tests/test_packaging_scripts.py \
  adapter_service/tests/test_review_mode_contract.py \
  formal-plugin-kit/tests/layout-smoke.test.js \
  formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json \
  formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js \
  formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html \
  formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js \
  phase1-delivery-kit/README.md \
  dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260703.tar.gz
git commit -m "fix: support old and new dify chat inputs"
```

Expected: the commit contains no unrelated old delivery archives.
