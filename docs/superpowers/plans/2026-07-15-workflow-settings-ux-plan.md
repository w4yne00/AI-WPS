# Word/Excel/PPT Workflow Settings UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the oversized three-host workflow settings forms with compact, host-isolated profile lists and full-width editors, remove the unified-key controls from the UI, and make task-page workflow selection activate immediately without changing model-task behavior.

**Architecture:** Keep the three existing WPS add-in packages isolated and preserve all adapter workflow-profile endpoints. Add the same small pure workflow-UI helpers to each host helper module, then implement host-local DOM rendering and state transitions using a shared ID/behavior contract. The adapter unified key and upgrade-preservation logic remain intact; only frontend controls and bindings are removed.

**Tech Stack:** ES5-compatible JavaScript, HTML/CSS WPS task panes, Node `assert` smoke tests, Python `unittest`, Bash delivery packaging, Playwright visual verification.

---

## File Map

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.{html,css,js}`: Word settings tabs, compact profile list, editor subview, immediate task-page switching.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.{html,css,js}`: Excel single-task version of the same interaction.
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.{html,css,js}`: PPT single-task version of the same interaction.
- Three `taskpane-helpers.js` files: pure option, validation, activation-default, and delete-protection helpers.
- `formal-plugin-kit/tests/taskpane-helpers.test.js`: Word/Excel pure workflow-helper contract.
- `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`: PPT pure workflow-helper contract.
- `formal-plugin-kit/tests/layout-smoke.test.js`: static markup, source, host isolation, version, and styling assertions.
- `adapter_service/tests/test_packaging_scripts.py`: frontend unified-key removal plus adapter/install compatibility assertions.
- Existing version metadata, README files, handoff, acceptance record, and one new `v0.18.1-alpha` delivery archive: release synchronization.

## Protection Boundaries

- Do not change `/chat-messages`, payload compatibility, think-tag stripping, provider timeouts, background-job polling, or authentication snapshot behavior.
- Do not change Word preview, comparison, copy, review state, or writeback paths.
- Do not remove `/provider/api-key`, the unified key file, adapter fallback, or installer preservation.
- Do not merge the Word, Excel, and PPT plugin directories or expose one host's task types in another host.
- Do not stage or delete unrelated historical archives already present in `dist-phase1-delivery-kit/`.

### Task 1: Define and test the shared workflow UI contract

**Files:**
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/tests/ppt-taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`

- [ ] **Step 1: Add failing Word/Excel helper assertions**

Load both host helper modules and require identical results:

```js
function assertWorkflowUiContract(helpers) {
  assert.deepStrictEqual(
    helpers.workflowProfileOptionState(
      { id: "p1", name: "生产版", keyConfigured: true },
      "p1"
    ),
    { id: "p1", label: "✓ 生产版", active: true, disabled: false }
  );
  assert.strictEqual(
    helpers.workflowProfileOptionState(
      { id: "p2", name: "旧版", keyConfigured: false },
      "p1"
    ).disabled,
    true
  );
  assert.deepStrictEqual(
    helpers.validateWorkflowProfileDraft({ name: "", note: "", apiKey: "" }, "create"),
    { ok: false, field: "name", message: "请输入工作流名称。" }
  );
  assert.deepStrictEqual(
    helpers.validateWorkflowProfileDraft({ name: "测试版", note: "", apiKey: "" }, "create"),
    { ok: false, field: "apiKey", message: "请输入工作流 API Key。" }
  );
  assert.strictEqual(
    helpers.validateWorkflowProfileDraft({ name: "生产版", note: "稳定", apiKey: "" }, "edit").ok,
    true
  );
  assert.strictEqual(helpers.shouldActivateNewWorkflowProfile(0, false), true);
  assert.strictEqual(helpers.shouldActivateNewWorkflowProfile(2, false), false);
  assert.strictEqual(helpers.shouldActivateNewWorkflowProfile(2, true), true);
}
```

- [ ] **Step 2: Add the same failing contract to the PPT helper VM test**

Call `assertWorkflowUiContract(context.window.WpsAiPptHelpers)` after defining the same assertions in `ppt-taskpane-helpers.test.js`.

- [ ] **Step 3: Run the helper tests and verify failure**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
```

Expected: FAIL because `workflowProfileOptionState`, `validateWorkflowProfileDraft`, and `shouldActivateNewWorkflowProfile` are not exported.

- [ ] **Step 4: Implement the pure helpers in all three host helper modules**

Use ES5-compatible code in each module:

```js
function workflowProfileOptionState(profile, activeProfileId) {
  var item = profile || {};
  var active = Boolean(item.id && item.id === activeProfileId);
  var configured = Boolean(item.keyConfigured);
  var name = String(item.name || "未命名工作流");
  return {
    id: String(item.id || ""),
    label: (active ? "✓ " : "") + name + (configured ? "" : "（Key 未配置）"),
    active: active,
    disabled: !configured
  };
}

function validateWorkflowProfileDraft(draft, mode) {
  var value = draft || {};
  var name = String(value.name || "").trim();
  var note = String(value.note || "").trim();
  var apiKey = String(value.apiKey || "").trim();
  if (!name) {
    return { ok: false, field: "name", message: "请输入工作流名称。" };
  }
  if (name.length > 40) {
    return { ok: false, field: "name", message: "工作流名称不能超过 40 个字。" };
  }
  if (note.length > 200) {
    return { ok: false, field: "note", message: "工作流备注不能超过 200 个字。" };
  }
  if (mode === "create" && !apiKey) {
    return { ok: false, field: "apiKey", message: "请输入工作流 API Key。" };
  }
  return { ok: true, name: name, note: note, apiKey: apiKey };
}

function shouldActivateNewWorkflowProfile(profileCount, requested) {
  return Number(profileCount || 0) === 0 || Boolean(requested);
}
```

Export all three functions from each helper module. Preserve existing helper names and exports.

- [ ] **Step 5: Run helper tests and commit**

Expected: both Node tests PASS.

```bash
git add formal-plugin-kit/tests/taskpane-helpers.test.js formal-plugin-kit/tests/ppt-taskpane-helpers.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js
git commit -m "test: define workflow settings UI contract"
```

### Task 2: Establish the compact markup contract

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`

- [ ] **Step 1: Replace old static assertions with failing compact-settings assertions**

For each host HTML, assert:

```js
assert.ok(!hostHtml.includes('id="provider-api-key"'));
assert.ok(!hostHtml.includes('id="btn-save-api-key"'));
assert.ok(!hostHtml.includes('id="btn-clear-api-key"'));
assert.ok(!hostHtml.includes('id="btn-activate-workflow-profile"'));
[
  'id="workflow-settings-home"',
  'id="btn-new-workflow-profile"',
  'id="workflow-profile-manager"',
  'id="workflow-editor-view"',
  'id="workflow-editor-name"',
  'id="workflow-editor-note"',
  'id="workflow-editor-key"',
  'id="workflow-editor-activate"',
  'id="btn-save-workflow-editor"',
  'id="btn-cancel-workflow-editor"',
  'id="workflow-delete-dialog"'
].forEach((marker) => assert.ok(hostHtml.includes(marker), marker));
```

Assert Word contains `id="workflow-task-tabs"`; Excel and PPT must not contain it. Assert all task-page dropdowns retain `workflow-profile-select` and add `workflow-switch-feedback`.

- [ ] **Step 2: Run layout smoke and verify failure**

Run `node formal-plugin-kit/tests/layout-smoke.test.js`.

Expected: FAIL on the old unified-key and activation-button markup.

- [ ] **Step 3: Replace the three settings structures**

Use the same IDs across all hosts. Word includes this task tab container:

```html
<div id="workflow-task-tabs" class="workflow-task-tabs" role="tablist" aria-label="选择 Word 功能"></div>
```

All hosts include:

```html
<section id="workflow-settings-home">
  <div class="workflow-manager-head">
    <div><h3 id="workflow-manager-title">工作流</h3><p id="workflow-manager-summary"></p></div>
    <button id="btn-new-workflow-profile" type="button">新建工作流</button>
  </div>
  <div id="workflow-profile-manager"></div>
</section>
<section id="workflow-editor-view" hidden>
  <button id="btn-workflow-editor-back" class="icon-button is-back" type="button" aria-label="返回工作流列表"></button>
  <h3 id="workflow-editor-title">新建工作流</h3>
  <label class="field"><span>工作流名称</span><input id="workflow-editor-name" maxlength="40" /></label>
  <label class="field"><span>工作流备注</span><textarea id="workflow-editor-note" maxlength="200"></textarea></label>
  <label class="field"><span id="workflow-editor-key-label">API Key</span><input id="workflow-editor-key" type="password" /></label>
  <p id="workflow-editor-key-status" class="inline-status"></p>
  <label class="workflow-activate-check"><input id="workflow-editor-activate" type="checkbox" /> 保存并设为当前</label>
  <div id="workflow-editor-error" role="alert"></div>
  <div class="workflow-editor-actions"><button id="btn-cancel-workflow-editor" type="button">取消</button><button id="btn-save-workflow-editor" type="button">保存</button></div>
</section>
```

Add an in-page `role="dialog"` confirmation with workflow-name text, cancel, and destructive confirm buttons. Simplify provider settings to API URL summary/edit only; remove provider-name and unified-key inputs from the visible form.

- [ ] **Step 4: Run layout smoke and commit**

Expected: static markup assertions PASS. JavaScript may still fail later source assertions until Tasks 3-5.

```bash
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html
git commit -m "feat: add compact workflow settings markup"
```

### Task 3: Implement Word settings and immediate switching

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`

- [ ] **Step 1: Add failing Word source assertions**

Require `renderWorkflowTaskTabs`, `openWorkflowEditor`, `closeWorkflowEditor`, `saveWorkflowEditor`, `showWorkflowDeleteDialog`, and immediate activation from the dropdown change handler. Require absence of `saveProviderApiKey`, `clearProviderApiKey`, and their event bindings.

```js
assert.ok(wordJs.includes("function renderWorkflowTaskTabs()"));
assert.ok(wordJs.includes("function openWorkflowEditor(mode, taskType, profileId)"));
assert.ok(wordJs.includes("function saveWorkflowEditor()"));
assert.ok(wordJs.includes("activateWorkflowProfile(event.target.value, taskType)"));
assert.ok(!wordJs.includes("function saveProviderApiKey()"));
assert.ok(!wordJs.includes('byId("btn-save-api-key")'));
```

- [ ] **Step 2: Run layout smoke and verify failure**

Expected: FAIL because Word still renders expanded forms and two-step switching.

- [ ] **Step 3: Add Word settings state and tab rendering**

Extend state without touching task results:

```js
settingsWorkflowTaskType: "word.smart_write",
workflowEditor: { open: false, mode: "create", taskType: "", profileId: "", dirty: false },
workflowDeleteCandidate: null
```

When settings opens from a Word task, derive `settingsWorkflowTaskType` from `MODE_WORKFLOW_TASK_TYPES[state.settingsReturnMode]`. Render four buttons from `TASK_API_KEY_DEFS`; selecting a tab updates only the settings manager and loads that one task type.

- [ ] **Step 4: Replace expanded manager rendering with list rows**

Render only escaped name, one-line note, status, edit, activate, and delete controls. Use `helpers.canDeleteWorkflowProfile` for delete state and show a retry action when `loadError` exists. Do not render any per-row input.

- [ ] **Step 5: Implement the Word full-width editor flow**

`openWorkflowEditor` loads an existing profile or empty create draft, updates key status, defaults activation through `shouldActivateNewWorkflowProfile`, and swaps `workflow-settings-home`/`workflow-editor-view`. Input listeners set `workflowEditor.dirty = true`.

`saveWorkflowEditor` must:

```js
var checked = helpers.validateWorkflowProfileDraft(draft, state.workflowEditor.mode);
if (!checked.ok) {
  showWorkflowEditorError(checked.field, checked.message);
  return;
}
state.workflowProfileMutationBusy = true;
if (state.workflowEditor.mode === "create") {
  return request("/provider/workflow-profiles", {
    taskType: state.workflowEditor.taskType,
    name: checked.name,
    note: checked.note,
    apiKey: checked.apiKey,
    activate: helpers.shouldActivateNewWorkflowProfile(data.profileCount, activateChecked)
  }).then(finishEditorSave, failEditorSave);
}
return request("/provider/workflow-profiles/" + encodeURIComponent(profileId), {
  name: checked.name,
  note: checked.note
}, { method: "PATCH" }).then(function () {
  if (!checked.apiKey) { return finishEditorSave(); }
  return request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/api-key", {
    apiKey: checked.apiKey
  }).then(finishEditorSave, showPartialKeyFailure);
}, failEditorSave);
```

The partial failure text must say that name/note were saved, Key replacement failed, and the old Key remains active. Reload server state after every success or partial failure.

- [ ] **Step 6: Implement named delete confirmation and immediate switching**

Open the in-page dialog with the escaped workflow name. Reject active-profile deletion in the UI before calling `DELETE`; preserve the existing adapter rejection. On task-page `change`, save the previous active ID, call activation immediately, and restore the old option on failure. Disable all options without Key and disable the select while `state.busy` or `workflowProfileMutationBusy`.

- [ ] **Step 7: Simplify Word URL editing and preserve settings roundtrip**

Remove unified-key functions and listeners. Save only `{ baseUrl }`; do not clear provider name in adapter config. Keep the existing `toggleSettingsShortcut` behavior that preserves mode-specific input, result DOM, review state, and apply-button state.

- [ ] **Step 8: Run Word helper/layout tests and commit**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
git commit -m "feat: streamline Word workflow settings"
```

### Task 4: Implement the Excel settings flow

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`

- [ ] **Step 1: Add failing Excel source assertions**

Require the same editor functions, immediate dropdown activation, no unified-key handlers, fixed `excel.analysis`, and no Word tab renderer.

- [ ] **Step 2: Run layout smoke and verify failure**

Expected: FAIL on Excel's expanded rows and two-step activation source.

- [ ] **Step 3: Implement the fixed-task Excel manager and editor**

Use the Task 3 state machine with `taskType: "excel.analysis"`. Do not add task tabs. Reuse the same IDs, validation, save ordering, partial failure wording, delete dialog, missing-Key option disabling, and dirty-form protection.

- [ ] **Step 4: Make the Excel task-page dropdown activate immediately**

Replace selection-only behavior with `activateWorkflowProfile(event.target.value)`. Restore `state.workflowProfiles.activeProfileId` on failure and disable switching while Excel analysis is busy or a profile mutation is active.

- [ ] **Step 5: Remove Excel unified-key UI bindings and simplify URL saving**

Delete `saveProviderApiKey` and `clearProviderApiKey` from the task pane only. Keep adapter diagnostics and config readback unchanged.

- [ ] **Step 6: Run tests and commit**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
git commit -m "feat: streamline Excel workflow settings"
```

### Task 5: Implement the PPT settings flow

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`

- [ ] **Step 1: Add failing PPT source assertions**

Require the shared editor function names, fixed `ppt.slide_assistant`, immediate activation, delete-name confirmation, and absence of `/provider/api-key` frontend calls.

- [ ] **Step 2: Run layout smoke and verify failure**

Expected: FAIL because PPT still uses `profileAction` with expanded inputs.

- [ ] **Step 3: Replace `profileAction` with the fixed-task manager/editor state machine**

Use `PPT_WORKFLOW_TASK_TYPE` for every request. Preserve current-page/document mode state and all result-copy handlers. Use `helpers.workflowProfileOptionState` and disable missing-Key options.

- [ ] **Step 4: Implement immediate switching and remove unified-key bindings**

Activate on `workflow-profile-select` change, restore old selection on failure, and disable the select while `state.busy`. Keep `POST /provider/base-url` and remove only the visible unified-key save/clear calls.

- [ ] **Step 5: Run tests and commit**

```bash
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
node --check formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
git commit -m "feat: streamline PPT workflow settings"
```

### Task 6: Apply the unified compact visual system

**Files:**
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`

- [ ] **Step 1: Add failing CSS contract assertions**

Require all hosts to define `.workflow-task-tabs`, `.workflow-profile-list`, `.workflow-profile-list-row`, `.workflow-editor-view`, `.workflow-editor-actions`, `.workflow-delete-dialog`, `.workflow-empty-state`, and single-line note truncation. Require host action colors to remain Word blue, Excel green, and PPT orange.

- [ ] **Step 2: Run layout smoke and verify failure**

Expected: FAIL because the old expanded-grid CSS remains.

- [ ] **Step 3: Replace expanded profile form CSS**

Use stable single-column geometry:

```css
.workflow-profile-list-row {
  min-height: 58px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  border-top: 1px solid var(--line);
}
.workflow-profile-note {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.workflow-editor-actions {
  position: sticky;
  bottom: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: var(--surface);
}
```

Keep cards at 8px radius or less, avoid nested cards, keep text at fixed sizes, and ensure destructive actions are visually secondary until confirmation.

- [ ] **Step 4: Add Word-only tabs and responsive rules**

Tabs must scroll internally or wrap without causing page-level horizontal overflow below 420 px. At narrow width, keep row actions fixed and allow names/notes to shrink.

- [ ] **Step 5: Run layout smoke and commit**

```bash
node formal-plugin-kit/tests/layout-smoke.test.js
git add formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css
git commit -m "style: unify compact workflow settings"
```

### Task 7: Lock compatibility and regression coverage

**Files:**
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Replace the obsolete unified-key frontend test**

Rename the packaging test to `test_taskpane_settings_hides_unified_key_but_keeps_workflow_profiles`. Assert all three HTML files omit unified-key controls while adapter and installer files still contain:

```python
self.assertNotIn('id="provider-api-key"', word_html)
self.assertNotIn('id="provider-api-key"', excel_html)
self.assertNotIn('id="provider-api-key"', ppt_html)
self.assertIn('path == "/provider/api-key"', standalone_adapter)
self.assertIn("run/provider_api_key", installer)
self.assertIn("run/provider_api_keys", installer)
```

- [ ] **Step 2: Add source assertions for protected task logic**

Keep assertions for Word result-state roundtrip, Excel/PPT background-job endpoints, 1800-second provider budgets, task-specific API keys, and no cross-host Ribbon entries. Do not weaken existing assertions to make the UI change pass.

- [ ] **Step 3: Run focused and full automated tests**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/ppt-taskpane-helpers.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
```

Expected: all Node tests PASS; Python suite reports 205 or more tests OK with only environment-conditional skips.

- [ ] **Step 4: Run syntax and whitespace checks**

Run `node --check` on all Word/Excel/PPT `taskpane.js`, `taskpane-helpers.js`, and `ribbon.js`; run `bash -n` on the build, installer, and smoke scripts; run `git diff --check`.

- [ ] **Step 5: Commit compatibility coverage**

```bash
git add adapter_service/tests/test_packaging_scripts.py formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "test: protect workflow settings compatibility"
```

### Task 8: Perform browser visual and interaction verification

**Files:**
- Modify if defects are found: the three host `taskpane.{html,css,js}` files and relevant tests

- [ ] **Step 1: Start a local static server and open each host at 420x900**

Verify Word settings for all four tabs; Excel and PPT settings for their fixed task type. Use stubbed `/config` and workflow-profile responses containing empty, one-profile, multi-profile, missing-Key, and load-error states.

- [ ] **Step 2: Exercise the complete interaction path**

For each host: open settings, edit URL, open/cancel create, create and auto-activate first profile, edit name/note without Key replacement, replace Key, cancel a dirty form, switch from the task page, reject active deletion, and confirm inactive deletion.

- [ ] **Step 3: Verify protected task state**

Seed Word result DOM and apply-button state, Excel analysis output, and PPT summary output before entering settings. Confirm every value is unchanged after returning. Confirm the workflow dropdown is disabled while each host's busy state is true.

- [ ] **Step 4: Capture and inspect screenshots**

Capture Word blue, Excel green, and PPT orange screenshots for settings list, editor, and delete confirmation at 420x900 and 320x700. Check canvas pixels are nonblank, page width equals viewport width, no controls overlap, notes truncate, and sticky actions remain visible.

- [ ] **Step 5: Fix any issue test-first and rerun affected checks**

Add a layout/helper assertion reproducing each defect before changing code. Rerun the focused Node test and screenshot before continuing.

### Task 9: Version, document, package, and deliver v0.18.1-alpha

**Files:**
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Modify: `adapter-start-kit/scripts/start_uvicorn_adapter.sh`
- Modify: current version assertions and runtime metadata returned by `rg -l "0\.18\.0-alpha" ...`
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260715-v0181.tar.gz`

- [ ] **Step 1: Change version assertions first**

Require `0.18.1-alpha`, rule `AI-WPS-P1-WORD-EXCEL-PPT-0.18.1-20260715`, and package tag `20260715-v0181`. Run version tests and verify they fail before metadata changes.

- [ ] **Step 2: Synchronize active runtime and cache metadata**

Update adapter diagnostics, standalone adapter, start-script expected version, three manifests, task-pane/ribbon cache tokens, three frontend build constants, README current-version tables, handoff, delivery README, and acceptance record. Historical release rows and historical package names remain unchanged.

- [ ] **Step 3: Document the user-visible change**

Record compact workflow lists, Word function tabs, full-width editor, immediate selection, hidden unified-key UI, preserved adapter fallback, current-profile delete protection, and unchanged model/result/writeback chains.

- [ ] **Step 4: Run the complete release verification suite**

Repeat Task 7 tests and syntax checks. Expected: all pass with synchronized `0.18.1-alpha` assertions.

- [ ] **Step 5: Build and inspect the combined package**

```bash
DATE_TAG=20260715-v0181 bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260715-v0181.tar.gz | rg 'wps-ai-assistant(_1.0.0|-et_1.0.0|-wpp_1.0.0)|prompt-templates/(excel-smart-analysis|ppt-smart-summary)-prompt-template.md|installer/install_phase1.sh'
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260715-v0181.tar.gz
```

Extract or stream-check all three task panes to confirm the compact settings markup is inside the archive and unified-key controls are absent. Confirm the installer still backs up and restores `config/adapter.json`, `run/provider_api_key`, and `run/provider_api_keys/`.

- [ ] **Step 6: Record the real checksum and commit only intended release files**

Update handoff and acceptance documentation with the actual SHA256. Explicitly stage source, tests, docs, version metadata, and the new `20260715-v0181` archive. Do not stage unrelated historical archive deletions, modifications, or untracked files.

```bash
git commit -m "release: ship workflow settings UX"
```

- [ ] **Step 7: Push `main` only after user approval**

Fetch `origin/main`, verify no remote-only commits, then push the completed local commits to `origin/main`. Report the final commit, package path, SHA256, automated tests, visual checks, and remaining Kylin V10/WPS target-machine validation.

## Completion Criteria

- Three settings pages share the same compact interaction and retain host-specific colors.
- Word shows one task type at a time; Excel and PPT never expose other hosts' task types.
- Task-page selection activates immediately and safely restores on failure.
- The UI has no unified-key controls, but existing unified-key fallback and upgrade preservation remain tested.
- Existing profiles, keys, active selections, long tasks, previews, copies, and Word writeback are unchanged.
- One `v0.18.1-alpha` combined package passes content and checksum verification.
