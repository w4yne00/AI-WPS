const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const root = "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const css = fs.readFileSync(`${root}/taskpane.css`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");

function includesAll(source, tokens, label) {
  tokens.forEach((token) => {
    assert.ok(source.includes(token), `${label}: missing ${token}`);
  });
}

function excludesAll(source, tokens, label) {
  tokens.forEach((token) => {
    assert.ok(!source.includes(token), `${label}: must not include ${token}`);
  });
}

function appearsInOrder(source, tokens, label) {
  let position = -1;
  tokens.forEach((token) => {
    const next = source.indexOf(token, position + 1);
    assert.ok(next > position, `${label}: expected ${token} after previous contract token`);
    position = next;
  });
}

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = js.indexOf("\n  function ", start + 1);
  return js.slice(start, next >= 0 ? next : js.length);
}

function loadPureFunction(name, context = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, context);
}

function testStaticMarkupContract() {
  includesAll(html, [
    'id="settings-status-line"',
    'id="workflow-profile-select"',
    'id="workflow-switch-feedback"',
    'id="workflow-settings-home"',
    'id="workflow-profile-manager"',
    'id="btn-new-workflow-profile"',
    'id="workflow-editor-view"',
    'id="workflow-editor-title"',
    'id="workflow-editor-name"',
    'id="workflow-editor-note"',
    'id="workflow-editor-key"',
    'id="workflow-editor-error"',
    'id="workflow-editor-activate"',
    'id="btn-cancel-workflow-editor"',
    'id="btn-save-workflow-editor"',
    'id="provider-base-url"',
    'id="btn-save-provider-url"'
  ], "PPT workflow settings markup");
  excludesAll(html, [
    'id="btn-activate-workflow-profile"',
    'id="provider-api-key"',
    'id="btn-save-api-key"',
    'id="btn-clear-api-key"',
    "统一 API Key",
    "仅智能总结"
  ], "removed PPT controls and task labels");
}

function testStatusAndMutationBusyContract() {
  const setStatus = functionSource("setStatus");
  const setMutationBusy = functionSource("setWorkflowProfileMutationBusy");
  const run = functionSource("runPptSlideAssistant");
  includesAll(setStatus, [
    'byId("status-line")',
    'byId("settings-status-line")'
  ], "status must stay visible in home and settings views");
  includesAll(setMutationBusy, [
    'byId("btn-run-primary")',
    "state.busy || state.workflowProfileMutationBusy"
  ], "workflow mutations must disable the primary run action");
  includesAll(run, [
    "state.workflowProfileMutationBusy",
    "工作流配置正在更新"
  ], "run action must guard workflow mutations");
}

function testFixedTaskAndHelperContract() {
  includesAll(js, [
    'var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";',
    "helpers.workflowProfileOptionState(",
    "helpers.validateWorkflowProfileDraft(",
    "helpers.shouldActivateNewWorkflowProfile("
  ], "fixed PPT task and shared helpers");
  assert.ok(
    js.includes('taskType: PPT_WORKFLOW_TASK_TYPE'),
    "new profiles must use the fixed PPT task type"
  );
  excludesAll(js, [
    'request("/provider/api-key"',
    'request("/provider/task-api-key"'
  ], "unified and task Key frontend bindings");
}

function testImmediateActivationContract() {
  const render = functionSource("renderProfileStrip");
  const activate = functionSource("activateWorkflowProfile");
  const binding = functionSource("bindEvents");
  includesAll(render, [
    "workflowProfileOptionState",
    "option.disabled = optionState.disabled",
    "state.workflowProfileMutationBusy"
  ], "profile dropdown option state");
  includesAll(binding, [
    'byId("workflow-profile-select").addEventListener("change"',
    "activateWorkflowProfile(event.target.value)"
  ], "immediate dropdown activation");
  includesAll(activate, [
    "previousProfileId",
    "setWorkflowProfileMutationBusy(true)",
    "state.selectedProfileId = previousProfileId",
    "renderProfileStrip()",
    "切换工作流失败"
  ], "activation rollback and busy state");
  const disable = functionSource("setRunDisabled");
  assert.ok(disable.includes('"workflow-profile-select"'), "busy tasks must disable the dropdown");
}

function testManagerAndEditorContract() {
  const manager = functionSource("renderProfileManager");
  const openEditor = functionSource("openWorkflowEditor");
  const saveEditor = functionSource("saveWorkflowEditor");
  const remove = functionSource("deleteWorkflowProfile");
  includesAll(manager, [
    "workflow-profile-list",
    "workflow-profile-list-row",
    "workflow-profile-note",
    "data-profile-action=",
    "编辑",
    "当前",
    "Key 未配置"
  ], "compact workflow list");
  includesAll(openEditor, [
    "workflow-settings-home",
    "workflow-editor-view",
    "shouldActivateNewWorkflowProfile"
  ], "full-width create/edit page");
  includesAll(saveEditor, [
    "validateWorkflowProfileDraft",
    '{ method: "PATCH" }',
    '"/api-key"',
    "if (!draft.apiKey)",
    "名称和备注已保存，但 Key 更换失败；原 Key 保持不变",
    'byId("workflow-editor-error")',
    "state.workflowEditor.dirty = true"
  ], "ordered metadata and optional Key save");
  assert.ok(
    !saveEditor.includes("closeWorkflowEditor(true)"),
    "Key replacement failure must keep the editor open for direct retry"
  );
  appearsInOrder(saveEditor, [
    '{ method: "PATCH" }',
    "if (!draft.apiKey)",
    '"/api-key"'
  ], "metadata must save before optional Key replacement");
  includesAll(remove, [
    "activeProfileId",
    "profile.name",
    "window.confirm",
    "请先切换到其他工作流"
  ], "named delete confirmation and current-profile guard");
  includesAll(functionSource("closeWorkflowEditor"), [
    'byId("workflow-editor-key").value = ""',
    'byId("workflow-editor-error").textContent = ""'
  ], "closing the editor must clear sensitive and transient feedback fields");
}

function testProfileLoadFailureAndRequestOrderingContract() {
  const load = functionSource("loadProfiles");
  const manager = functionSource("renderProfileManager");
  const openEditor = functionSource("openWorkflowEditor");
  const activate = functionSource("activateWorkflowProfile");
  includesAll(load, [
    "profileLoadRequestId",
    "requestId !== state.profileLoadRequestId",
    "loadError"
  ], "profile GET responses must be ordered and preserve load errors");
  includesAll(manager, [
    'data-profile-action="retry"',
    'byId("btn-new-workflow-profile").disabled',
    "state.profiles.loadError"
  ], "profile load failure must disable create and expose retry");
  includesAll(openEditor, [
    "state.profiles.loadError",
    "shouldActivateNewWorkflowProfile"
  ], "load failure must not masquerade as an empty profile list");
  assert.ok(
    openEditor.indexOf("state.profiles.loadError") < openEditor.indexOf("shouldActivateNewWorkflowProfile"),
    "load error must be considered before first-profile auto activation"
  );
  includesAll(activate, [
    "state.profileLoadRequestId += 1",
    'request("/provider/workflow-profiles/"'
  ], "activation must invalidate older profile GET requests");
  assert.ok(
    activate.indexOf("state.profileLoadRequestId += 1") <
      activate.indexOf('request("/provider/workflow-profiles/"'),
    "profile GET invalidation must happen before activation starts"
  );
  assert.ok(
    functionSource("handleWorkflowProfileAction").includes('action === "retry"'),
    "profile manager retry must reload profiles"
  );
}

function testEscapedFallbackContract() {
  const escaped = loadPureFunction("escaped", { helpers: {} });
  assert.strictEqual(
    escaped('<img src=x onerror="alert(1)">&\''),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;"
  );
  assert.ok(
    functionSource("renderProfileManager").includes("escaped("),
    "profile manager must route dynamic HTML through the safe escape wrapper"
  );
}

function testPptWorkflowPreservationContract() {
  includesAll(js, [
    'function setSourceMode(mode)',
    'state.sourceMode = documentMode ? "document" : "slide"',
    '"/ppt/document-files"',
    '"/ppt/slide-assistant/jobs"',
    "saveActiveJob(",
    "pollPptSlideJob(",
    "renderResult(",
    "buildPptDocumentPlainText",
    "buildPptDocumentOutline",
    "handleDocumentResultCopy"
  ], "PPT mode, upload, background task, result, and copy preservation");
  const switchView = functionSource("switchView");
  excludesAll(switchView, [
    "state.sourceMode =",
    "state.selectedDocument =",
    "state.result ="
  ], "settings round trip must preserve PPT task state");
}

function testNarrowLayoutContract() {
  includesAll(css, [
    ".workflow-profile-list",
    ".workflow-profile-list-row",
    ".workflow-profile-note",
    ".workflow-editor-view",
    ".workflow-editor-actions",
    "text-overflow: ellipsis",
    "minmax(0, 1fr)",
    "max-width: 420px",
    "overflow-x: hidden"
  ], "compact 420px PPT layout");
  assert.ok(!css.includes(".workflow-profile-list-row .settings-card"), "workflow rows must not nest cards");
}

testStaticMarkupContract();
testStatusAndMutationBusyContract();
testFixedTaskAndHelperContract();
testImmediateActivationContract();
testManagerAndEditorContract();
testProfileLoadFailureAndRequestOrderingContract();
testEscapedFallbackContract();
testPptWorkflowPreservationContract();
testNarrowLayoutContract();

console.log("PPT workflow settings source contract passed.");
