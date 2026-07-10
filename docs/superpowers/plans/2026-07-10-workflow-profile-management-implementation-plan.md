# Workflow Profile Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users save multiple named Dify workflow API-key profiles for each Word and Excel task, manage them in settings, and explicitly switch the active profile from the task page without re-entering old keys.

**Architecture:** Add a focused `WorkflowProfileStore` that owns profile validation, legacy migration, active-profile persistence, and key-file lifecycle while retaining `taskApiKeyRefs` as a compatibility mirror. Expose CRUD and activation through the existing provider router, resolve the selected profile once for each new provider request, and add host-specific profile selectors and management UI to the existing Word and Excel task panes. Preserve all task payloads, timeouts, parsing, polling, preview, copy, and writeback behavior.

**Tech Stack:** Python 3.8, FastAPI, Pydantic, standard-library JSON/path/UUID handling, WPS JS add-ins using plain ES5 JavaScript/HTML/CSS, Node `assert` smoke tests, Python `unittest`/pytest-compatible tests.

---

## File Map

- Create `adapter_service/app/services/workflow_profiles.py`: profile constants, validation, migration, persistence, activation, deletion, and sanitized status building.
- Create `adapter_service/tests/test_workflow_profiles.py`: focused unit tests for migration, CRUD, activation, compatibility mirroring, and secret handling.
- Modify `adapter_service/app/api/provider.py`: workflow-profile request models and CRUD/activation endpoints; preserve legacy task-key endpoints.
- Create `adapter_service/tests/test_workflow_profile_api.py`: FastAPI endpoint contracts and Chinese validation errors.
- Modify `adapter_service/app/services/provider_client.py`: active profile resolution and sanitized profile diagnostics without changing provider transport.
- Modify `adapter_service/tests/test_enterprise_provider.py`: active-profile key precedence, legacy/unified fallback, and debug metadata tests.
- Modify both Word files `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`, `taskpane.js`, `taskpane.css`, and `taskpane-helpers.js`: Word-only selectors and profile manager.
- Modify both Excel files `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`, `taskpane.js`, `taskpane.css`, and `taskpane-helpers.js`: Excel-only selector and profile manager.
- Modify `formal-plugin-kit/tests/taskpane-helpers.test.js` and `formal-plugin-kit/tests/layout-smoke.test.js`: profile response normalization, explicit activation, host isolation, and protected behavior contracts.
- Modify `config/adapter.example.json`, README files, handoff and operations documentation: configuration schema, upgrade behavior, and usage.
- Modify existing version metadata and version assertions from `0.15.2-alpha` to `0.16.0-alpha`.
- Build `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz` after all tests pass.

## Protected Boundaries

- Do not alter `/chat-messages` payload negotiation, prompts, task paths, answer parsing, or think-tag stripping.
- Do not alter document-review or Excel-analysis `clientJobId` submission and recoverable polling.
- Do not alter smart-write preview, comparison highlighting, copy source, or Word writeback functions.
- Keep smart imitation preview/copy only and Excel analysis read-only.
- Keep API URL and all existing key files during installer upgrades.
- Keep Word and Excel Ribbon/task-pane feature isolation.

### Task 1: Build The Profile Store With Legacy Migration

**Files:**
- Create: `adapter_service/tests/test_workflow_profiles.py`
- Create: `adapter_service/app/services/workflow_profiles.py`

- [ ] **Step 1: Write failing tests for migration and sanitized listing**

Create tests using `TemporaryDirectory`, a temporary `adapter.json`, and a temporary key directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from app.services.workflow_profiles import WorkflowProfileStore


class WorkflowProfileStoreTests(unittest.TestCase):
    def test_list_migrates_legacy_task_key_without_moving_secret(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            key_dir = root / "provider_api_keys"
            key_dir.mkdir()
            config_path.write_text(
                json.dumps({"taskApiKeyRefs": {"word.smart_write": "smart_write_old"}}),
                encoding="utf-8",
            )
            (key_dir / "smart_write_old").write_text("app-old-secret\n", encoding="utf-8")

            result = WorkflowProfileStore(config_path, key_dir).list_for_task("word.smart_write")

            self.assertEqual(result["activeProfileId"], result["profiles"][0]["id"])
            self.assertEqual(result["profiles"][0]["name"], "当前配置")
            self.assertTrue(result["profiles"][0]["keyConfigured"])
            self.assertNotIn("apiKey", json.dumps(result))
            self.assertEqual((key_dir / "smart_write_old").read_text(encoding="utf-8").strip(), "app-old-secret")

    def test_list_does_not_expose_secret_or_other_task_profiles(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store_with_two_tasks(Path(tmp))

            result = store.list_for_task("word.smart_write")

            self.assertEqual([item["taskType"] for item in result["profiles"]], ["word.smart_write"])
            self.assertNotIn("app-smart-secret", json.dumps(result, ensure_ascii=False))
            self.assertNotIn("app-excel-secret", json.dumps(result, ensure_ascii=False))
```

The test helper `_store_with_two_tasks` must create profiles through the public `create_profile` API rather than writing profile internals directly.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_workflow_profiles -v
```

Expected: FAIL because `app.services.workflow_profiles` does not exist.

- [ ] **Step 3: Implement the minimal store types, validation, and migration**

Create the module with these public constants:

```python
SUPPORTED_WORKFLOW_TASKS = (
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
    "word.format_review",
    "excel.analysis",
)
MAX_PROFILES_PER_TASK = 20
DEFAULT_PROFILE_KEY_DIR = Path(__file__).resolve().parents[3] / "run" / "provider_api_keys"


class WorkflowProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

Implement `WorkflowProfileStore.__init__(config_path=DEFAULT_CONFIG_PATH, key_dir=DEFAULT_PROFILE_KEY_DIR)` plus the exact public methods `list_for_task`, `create_profile`, `update_profile`, `replace_api_key`, `activate_profile`, `delete_profile`, and `get_active_profile`. Defining the key directory locally avoids a circular import with `provider_client.py`. Each method returns the sanitized dictionary shape asserted by the tests. Use `uuid.uuid4().hex` to generate `profile_<hex>` and `workflow_<hex>` identifiers. Guard every read-modify-write sequence with a module-level `threading.RLock`, load the full payload with `load_config_payload`, validate in memory, then persist once with `save_config_payload`. Migration must reuse the legacy ref and update only `workflowProfiles` plus `activeWorkflowProfiles`.

- [ ] **Step 4: Run the store tests and verify GREEN**

Run the same unittest command. Expected: PASS.

- [ ] **Step 5: Commit the isolated store**

```bash
git add adapter_service/app/services/workflow_profiles.py adapter_service/tests/test_workflow_profiles.py
git commit -m "feat: add workflow profile store"
```

### Task 2: Lock CRUD, Validation, Activation, And Key Lifecycle

**Files:**
- Modify: `adapter_service/tests/test_workflow_profiles.py`
- Modify: `adapter_service/app/services/workflow_profiles.py`

- [ ] **Step 1: Add failing CRUD and validation tests**

Add separate tests for these behaviors:

```python
def test_activate_updates_active_profile_and_legacy_ref(self) -> None:
    profile = store.create_profile("word.smart_write", "新版", "app-new")
    store.activate_profile(profile["id"])
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    self.assertEqual(payload["activeWorkflowProfiles"]["word.smart_write"], profile["id"])
    self.assertEqual(payload["taskApiKeyRefs"]["word.smart_write"], profile["apiKeyRef"])

def test_duplicate_name_is_rejected_case_insensitively(self) -> None:
    store.create_profile("word.smart_write", "稳定版", "app-one")
    with self.assertRaisesRegex(WorkflowProfileError, "名称已存在"):
        store.create_profile("word.smart_write", " 稳定版 ", "app-two")

def test_active_profile_cannot_be_deleted(self) -> None:
    profile = store.create_profile("excel.analysis", "生产版", "app-excel", activate=True)
    with self.assertRaisesRegex(WorkflowProfileError, "先切换"):
        store.delete_profile(profile["id"])

def test_deleting_inactive_profile_removes_only_its_key_file(self) -> None:
    active = store.create_profile("word.format_review", "当前版", "app-current", activate=True)
    inactive = store.create_profile("word.format_review", "历史版", "app-old")
    store.delete_profile(inactive["id"])
    self.assertTrue((key_dir / active["apiKeyRef"]).exists())
    self.assertFalse((key_dir / inactive["apiKeyRef"]).exists())
```

Also cover unsupported task type, blank/overlong name, overlong note, blank key, 20-profile limit, cross-task isolation, rename collision, replacement key file permissions, and activation when the key file is missing.

- [ ] **Step 2: Run tests and verify expected failures**

Expected: failures identify each missing validation or lifecycle rule, not test setup errors.

- [ ] **Step 3: Implement minimal CRUD and atomic persistence**

Normalize names with `.strip()` and compare `.casefold()`. Write keys with a temporary file in the same directory, set mode `0o600`, then replace the target file. Delete only an inactive profile’s generated key ref; never derive a path from profile name. Return sanitized profile dictionaries with `keyConfigured`, but keep `apiKeyRef` available for compatibility and diagnostics.

- [ ] **Step 4: Run the focused suite and verify GREEN**

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_workflow_profiles -v
```

Expected: PASS.

- [ ] **Step 5: Commit validation and lifecycle behavior**

```bash
git add adapter_service/app/services/workflow_profiles.py adapter_service/tests/test_workflow_profiles.py
git commit -m "feat: manage workflow profile lifecycle"
```

### Task 3: Expose Profile APIs And Preserve Legacy Task-Key APIs

**Files:**
- Create: `adapter_service/tests/test_workflow_profile_api.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/app/services/workflow_profiles.py`

- [ ] **Step 1: Write failing API contract tests**

Patch `app.api.provider.get_workflow_profile_store` to return a temporary store and use `TestClient(app)`. Cover:

```python
response = client.post("/provider/workflow-profiles", json={
    "taskType": "word.smart_write",
    "name": "稳定版",
    "apiKey": "app-secret",
    "note": "生产",
    "activate": True,
})
self.assertEqual(response.status_code, 200)
self.assertEqual(response.json()["data"]["profile"]["name"], "稳定版")
self.assertNotIn("app-secret", response.text)

listed = client.get("/provider/workflow-profiles", params={"taskType": "word.smart_write"})
self.assertEqual(listed.json()["data"]["profileCount"], 1)

duplicate = client.post("/provider/workflow-profiles", json={
    "taskType": "word.smart_write", "name": "稳定版", "apiKey": "app-other"
})
self.assertEqual(duplicate.status_code, 409)
self.assertIn("名称已存在", duplicate.text)
```

Add PATCH, key replacement, activation, deletion, unsupported task, missing-key activation and secret-redaction tests. Add a compatibility test proving `POST /provider/task-api-key` creates or updates “当前配置” and `DELETE /provider/task-api-key/{taskType}` clears only the current profile key.

- [ ] **Step 2: Run API tests and verify RED**

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_workflow_profile_api -v
```

Expected: FAIL with 404 for the new endpoints.

- [ ] **Step 3: Add Pydantic models, store dependency, and endpoint handlers**

Use aliased request models:

```python
class WorkflowProfileCreateRequest(BaseModel):
    task_type: str = Field(alias="taskType")
    name: str
    api_key: str = Field(alias="apiKey")
    note: str = ""
    activate: bool = False


class WorkflowProfileUpdateRequest(BaseModel):
    name: str
    note: str = ""


class WorkflowProfileApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")
```

Translate `WorkflowProfileError.code` to stable 400/404/409 responses via `AdapterError`. Keep old endpoint paths and response shape, delegating their mutation to the profile store.

- [ ] **Step 4: Run API and existing provider API tests**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_workflow_profile_api \
  adapter_service.tests.test_health \
  adapter_service.tests.test_config -v
```

Expected: PASS.

- [ ] **Step 5: Commit API contracts**

```bash
git add adapter_service/app/api/provider.py adapter_service/app/services/workflow_profiles.py adapter_service/tests/test_workflow_profile_api.py
git commit -m "feat: expose workflow profile APIs"
```

### Task 4: Resolve Active Profiles In Provider Calls And Diagnostics

**Files:**
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/app/services/provider_client.py`

- [ ] **Step 1: Write failing key-precedence and diagnostics tests**

Add tests that patch the default profile store and key paths:

```python
def test_active_workflow_profile_key_precedes_legacy_and_unified_keys(self) -> None:
    profile = store.create_profile("word.smart_write", "生产版", "app-profile", activate=True)
    (key_dir / "legacy_ref").write_text("app-legacy", encoding="utf-8")
    local_key.write_text("app-unified", encoding="utf-8")

    key = client.get_api_key_for_task("word.smart_write", key_base_path=key_dir)

    self.assertEqual(key, "app-profile")
    self.assertEqual(client.get_task_api_key_ref("word.smart_write"), profile["apiKeyRef"])

def test_provider_debug_reports_profile_identity_without_secret(self) -> None:
    client.post_task("word.smart_write", "trace-profile", {}, "提示词")
    debug = get_last_provider_debug()
    self.assertEqual(debug["workflowProfileId"], profile["id"])
    self.assertEqual(debug["workflowProfileName"], "生产版")
    self.assertNotIn("app-profile", json.dumps(debug, ensure_ascii=False))
```

Retain explicit tests for legacy task-ref fallback and unified-key fallback when no profile exists.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: active profile metadata is absent or the old ref is selected.

- [ ] **Step 3: Integrate profile resolution without changing transport**

At the beginning of each new `post_task`, resolve one active profile snapshot and use its ref for that request. Pass the resolved profile metadata into debug recording. Do not re-resolve during HTTP 400 input-mode retry. Do not change `build_provider_request_payload`, URL, timeout, error mapping, answer extraction, or cache-key semantics beyond using the selected `apiKeyRef` already expected by the cache.

Extend `build_task_api_key_status` with `activeProfileId`, `activeProfileName`, and `profileCount` while preserving existing fields.

- [ ] **Step 4: Run provider regression tests**

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider -v
```

Expected: PASS, including Dify input compatibility and all timeout tests.

- [ ] **Step 5: Commit provider integration**

```bash
git add adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_provider.py
git commit -m "feat: route tasks through active workflow profiles"
```

### Task 5: Add Pure Frontend Profile Helpers

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`

- [ ] **Step 1: Write failing helper tests**

Test normalized response handling and task isolation:

```javascript
const profileData = helpers.normalizeWorkflowProfileData({
  activeProfileId: "profile_word",
  profiles: [
    { id: "profile_word", taskType: "word.smart_write", name: "稳定版", keyConfigured: true },
    { id: "profile_excel", taskType: "excel.analysis", name: "表格版", keyConfigured: true }
  ]
}, "word.smart_write");

assert.strictEqual(profileData.activeProfileId, "profile_word");
assert.deepStrictEqual(profileData.profiles.map((item) => item.id), ["profile_word"]);
assert.strictEqual(helpers.getActiveWorkflowProfileName(profileData), "稳定版");
assert.strictEqual(helpers.canDeleteWorkflowProfile(profileData.profiles[0], "profile_word"), false);
```

Cover malformed responses, missing active profile, HTML-sensitive profile names, unconfigured keys, and empty lists.

- [ ] **Step 2: Run helper tests and verify RED**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
```

Expected: FAIL because the helper exports do not exist.

- [ ] **Step 3: Implement identical ES5-compatible helpers in both plugin packages**

Add and export these complete ES5-compatible helpers in both packages:

```javascript
function normalizeWorkflowProfileData(data, taskType) {
  var source = data && typeof data === "object" ? data : {};
  var profiles = Array.isArray(source.profiles) ? source.profiles : [];
  var normalized = profiles.filter(function (profile) {
    return profile && profile.taskType === taskType && profile.id;
  }).map(function (profile) {
    return {
      id: String(profile.id),
      taskType: taskType,
      name: String(profile.name || "未命名工作流"),
      note: String(profile.note || ""),
      keyConfigured: Boolean(profile.keyConfigured),
      createdAt: String(profile.createdAt || ""),
      updatedAt: String(profile.updatedAt || "")
    };
  });
  var activeId = String(source.activeProfileId || "");
  var activeExists = normalized.some(function (profile) {
    return profile.id === activeId;
  });
  return {
    taskType: taskType,
    activeProfileId: activeExists ? activeId : "",
    profileCount: normalized.length,
    profiles: normalized
  };
}

function getActiveWorkflowProfileName(data) {
  var profiles = data && Array.isArray(data.profiles) ? data.profiles : [];
  var activeId = data ? data.activeProfileId : "";
  for (var index = 0; index < profiles.length; index += 1) {
    if (profiles[index].id === activeId) {
      return profiles[index].name;
    }
  }
  return "尚未配置";
}

function canDeleteWorkflowProfile(profile, activeProfileId) {
  return Boolean(profile && profile.id && profile.id !== activeProfileId);
}

function workflowProfileStatusText(profile, activeProfileId) {
  if (!profile || !profile.keyConfigured) {
    return "密钥未配置";
  }
  return profile.id === activeProfileId ? "当前使用" : "可切换";
}
```

Use text nodes or the existing HTML escaping helper when rendering names. Do not include API Key values in helper state.

- [ ] **Step 4: Run helper tests and verify GREEN**

Expected: `taskpane-helpers tests passed`.

- [ ] **Step 5: Commit pure frontend behavior**

```bash
git add formal-plugin-kit/tests/taskpane-helpers.test.js \
  formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js
git commit -m "test: define workflow profile frontend behavior"
```

### Task 6: Implement Word Profile Selection And Management

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`

- [ ] **Step 1: Add failing Word UI contract tests**

Assert the Word task pane contains:

```javascript
assert.ok(html.includes('id="workflow-profile-strip"'));
assert.ok(html.includes('id="workflow-profile-select"'));
assert.ok(html.includes('id="btn-activate-workflow-profile"'));
assert.ok(html.includes('id="workflow-profile-manager"'));
assert.ok(js.includes('/provider/workflow-profiles'));
assert.ok(js.includes('/activate'));
var taskTypePattern = /\{ taskType: "(word\.[^"]+)"/g;
var wordTaskTypes = [];
var taskTypeMatch;
while ((taskTypeMatch = taskTypePattern.exec(js)) !== null) {
  wordTaskTypes.push(taskTypeMatch[1]);
}
assert.deepStrictEqual(wordTaskTypes.slice(0, 4), [
  "word.smart_write",
  "word.smart_imitation",
  "word.document_review",
  "word.format_review"
]);
assert.ok(!html.includes('Excel 智能分析工作流'));
```

Retain assertions for smart-write writeback, smart-imitation no-writeback, document-review polling and format-review extraction.

- [ ] **Step 2: Run smoke tests and verify RED**

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected: FAIL because the profile controls are absent.

- [ ] **Step 3: Add the Word quick selector and settings manager**

Add one unframed compact strip between scope and controls. Map the active Word mode to its exact task type. Populate the dropdown by calling:

```javascript
request("/provider/workflow-profiles?taskType=" + encodeURIComponent(taskType))
```

Selecting an option only updates local selection; `btn-activate-workflow-profile` must issue the activation POST. Disable activation while a task is running and display “从下一次任务开始生效” after success.

Replace the old task-key rows with profile rows. Implement create, rename/note update, separate key replacement, activation, and inactive deletion. Clear password inputs after every successful save. On list failure, disable profile controls but leave `btn-run-primary` behavior unchanged.

Use existing button and field styles plus focused additions with stable heights and responsive wrapping. Do not add nested cards or expose raw keys.

- [ ] **Step 4: Run Word UI tests and verify GREEN**

Run both commands from Step 2. Expected: PASS.

- [ ] **Step 5: Commit Word UI**

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html \
  formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js \
  formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css \
  formal-plugin-kit/tests/layout-smoke.test.js \
  adapter_service/tests/test_packaging_scripts.py
git commit -m "feat: manage Word workflow profiles"
```

### Task 7: Implement Excel Profile Selection And Management

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`

- [ ] **Step 1: Add failing Excel host-isolation tests**

Assert the Excel pane contains the same selector and manager IDs scoped to `excel.analysis`, contains no Word task profile labels, and still contains no apply/writeback controls. Assert Excel activation calls the same provider API and does not modify active-job storage functions.

- [ ] **Step 2: Run layout smoke and verify RED**

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: FAIL because Excel profile controls are absent.

- [ ] **Step 3: Add Excel selector and manager**

Reuse the Word interaction contract but hard-code the visible task scope to `excel.analysis`. Keep the selector available only in Excel analysis mode and the manager only in settings. Leave `runExcelAnalysisAction`, `saveExcelAnalysisActiveJob`, `pollExcelAnalysisJob`, and all read-only extraction/result functions unchanged.

- [ ] **Step 4: Run frontend regression tests**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit Excel UI**

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js \
  formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css \
  formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: manage Excel workflow profiles"
```

### Task 8: Update Configuration, Documentation, Version, And Package

**Files:**
- Modify: `config/adapter.example.json`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Create: `docs/operations/workflow-profile-management.md`
- Modify: all existing `0.15.2-alpha` runtime metadata and test assertions to `0.16.0-alpha`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz`

- [ ] **Step 1: Add failing version and package-preservation assertions**

Update existing assertions to require `0.16.0-alpha`. Extend packaging tests to assert the installer still backs up and restores:

```text
config/adapter.json
run/provider_api_key
run/provider_api_keys/
```

Add documentation assertions only where the repository already uses such static checks.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: version assertions fail before metadata is updated.

- [ ] **Step 3: Update metadata and user documentation**

Document profile creation, switching, deletion protection, “next task” semantics, old-key migration, host isolation, and secret handling. Add empty example fields:

```json
"workflowProfiles": {},
"activeWorkflowProfiles": {}
```

Do not place example secrets in the repository. Update frontend cache tokens, both manifests, both Ribbon taskpane URLs, adapter health/diagnostic versions, start-script expected version, README version rules, and delivery date to `20260710`.

- [ ] **Step 4: Run the complete regression suite**

```bash
PYTHONPATH=adapter_service python3 -m unittest discover -s adapter_service/tests -v
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected: all tests PASS with no protected-contract regressions.

- [ ] **Step 5: Build and validate the delivery archive**

```bash
DATE_TAG=20260710 bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz | rg \
  'workflow-profile-management|wps-ai-assistant-et_1.0.0|wps-ai-assistant_1.0.0|adapter_service/app/services/workflow_profiles.py'
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz
```

Expected: archive contains both plugins, adapter profile service and operations guide; checksum is recorded in `docs/codex-handoff.md`.

- [ ] **Step 6: Review the final diff for secret and scope safety**

```bash
git diff --check
rg -n 'app-[A-Za-z0-9_-]{12,}' adapter_service formal-plugin-kit config docs README.md README-ZH.md
git status --short
```

Expected: no whitespace errors, no real-looking API keys, and no unrelated files staged.

- [ ] **Step 7: Commit release metadata and package**

```bash
git add README.md README-ZH.md docs/codex-handoff.md docs/operations/workflow-profile-management.md \
  config/adapter.example.json adapter_service adapter-start-kit formal-plugin-kit \
  phase1-delivery-kit packaging dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz
git commit -m "release: package workflow profile management"
```

## Final Acceptance Checklist

- [ ] Two profiles can be saved for each of the five task types without overwriting each other.
- [ ] Switching a profile changes only the next new task and is visible in sanitized diagnostics.
- [ ] Restarting WPS and adapter preserves profiles and the current selection.
- [ ] Installing the new package over an existing target preserves URL, unified key, legacy task keys, all profile keys, and active selections.
- [ ] Old `taskApiKeyRefs` configurations migrate without moving or deleting their key files.
- [ ] Word never displays Excel profiles; Excel never displays Word profiles.
- [ ] Smart write/writeback, smart imitation preview-only, document-review polling, format review, and Excel read-only analysis remain unchanged.
