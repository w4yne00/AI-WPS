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
    "模型配置正在更新"
  ], "run action must guard workflow mutations");
}

function testTaskScopedProfileAndHelperContract() {
  includesAll(js, [
    'var PPT_WORKFLOW_TASK_TYPE = "ppt.slide_assistant";',
    'var PPT_STRUCTURE_WORKFLOW_TASK_TYPE = "ppt.structure_review";',
    "state.workflowTaskType",
    "helpers.workflowProfileOptionState(",
    "helpers.validateWorkflowProfileDraft(",
    "helpers.shouldActivateNewWorkflowProfile("
  ], "task-scoped PPT profiles and shared helpers");
  assert.ok(
    js.includes('taskType: state.workflowTaskType'),
    "new profiles must use the selected PPT task type"
  );
  includesAll(html, [
    'data-workflow-task-tab="ppt.slide_assistant"',
    'data-workflow-task-tab="ppt.structure_review"'
  ], "independent PPT workflow tabs");
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
    "syncWorkflowProfileSelectOptions(select, optionModels)",
    "state.workflowProfileMutationBusy"
  ], "profile dropdown option state");
  includesAll(binding, [
    'byId("workflow-profile-select").addEventListener("change"',
    "scheduleWorkflowProfileActivation(event.target.value)"
  ], "immediate dropdown activation");
  includesAll(activate, [
    "previousProfileId",
    "setWorkflowProfileMutationBusy(true)",
    "state.selectedProfileId = previousProfileId",
    "renderProfileStrip()",
    "切换模型配置失败"
  ], "activation rollback and busy state");
  const disable = functionSource("setRunDisabled");
  assert.ok(disable.includes('"workflow-profile-select"'), "busy tasks must disable the dropdown");
}

function testStableProfileSelectionInteraction() {
  const select = {
    children: [],
    disabled: false,
    attributes: {},
    appendChild(option) { this.children.push(option); },
    setAttribute(name, value) { this.attributes[name] = value; }
  };
  Object.defineProperty(select, "innerHTML", {
    get() { return ""; },
    set() { this.children = []; }
  });
  const nodes = {
    "workflow-profile-select": select,
    "workflow-switch-feedback": { textContent: "" }
  };
  const profileState = {
    workflowTaskType: "ppt.slide_assistant",
    selectedProfileId: "profile-a",
    profiles: {
      activeProfileId: "profile-a",
      profiles: [
        { id: "profile-a", name: "主模型", complete: true },
        { id: "profile-b", name: "备用模型", complete: true }
      ]
    },
    busy: false,
    workflowProfileMutationBusy: false
  };
  const syncOptions = loadPureFunction("syncWorkflowProfileSelectOptions", {
    document: { createElement() { return {}; } }
  });
  const render = loadPureFunction("renderProfileStrip", {
    state: profileState,
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    byId(id) { return nodes[id]; },
    workflowProfileOptionState(profile) {
      return { id: profile.id, label: profile.name, disabled: false };
    },
    activeProfileName() { return "主模型"; },
    setNodeTextIfChanged(node, value) { node.textContent = value; },
    syncWorkflowProfileSelectOptions: syncOptions,
    document: { createElement() { return {}; } }
  });
  render();
  const firstOptions = select.children.slice();
  render();
  assert.strictEqual(select.children[0], firstOptions[0]);
  assert.strictEqual(select.children[1], firstOptions[1]);

  let nextTimerId = 1;
  const pending = new Map();
  const activated = [];
  const activationState = { workflowProfileActivationTimer: null };
  const activationWindow = {
    setTimeout(callback) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      pending.set(timerId, callback);
      return timerId;
    },
    clearTimeout(timerId) { pending.delete(timerId); }
  };
  const cancelActivation = loadPureFunction("cancelWorkflowProfileActivation", {
    state: activationState,
    window: activationWindow
  });
  const scheduleActivation = loadPureFunction("scheduleWorkflowProfileActivation", {
    state: activationState,
    window: activationWindow,
    cancelWorkflowProfileActivation: cancelActivation,
    activateWorkflowProfile(profileId) { activated.push(profileId); }
  });
  scheduleActivation("profile-b");
  scheduleActivation("profile-c");
  assert.strictEqual(pending.size, 1);
  pending.values().next().value();
  assert.deepStrictEqual(activated, ["profile-c"]);
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
    "配置不完整"
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
    "if (!rawDraft.apiKey)",
    "模型配置已保存，但 API Key 更换失败；原 Key 保持不变",
    'byId("workflow-editor-error")',
    "state.workflowEditor.dirty = true"
  ], "ordered metadata and optional Key save");
  assert.ok(
    !saveEditor.includes("closeWorkflowEditor(true)"),
    "Key replacement failure must keep the editor open for direct retry"
  );
  appearsInOrder(saveEditor, [
    '{ method: "PATCH" }',
    "if (!rawDraft.apiKey)",
    '"/api-key"'
  ], "metadata must save before optional Key replacement");
  includesAll(remove, [
    "activeProfileId",
    "profile.name",
    "window.confirm",
    "请先切换到其他模型配置"
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
    'request("/provider/model-configurations/"'
  ], "activation must invalidate older profile GET requests");
  assert.ok(
    activate.indexOf("state.profileLoadRequestId += 1") <
      activate.indexOf('request("/provider/model-configurations/"'),
    "profile GET invalidation must happen before activation starts"
  );
  assert.ok(
    functionSource("handleWorkflowProfileAction").includes('action === "retry"'),
    "profile manager retry must reload profiles"
  );
}

function testEscapedFallbackContract() {
  const escaped = loadPureFunction("escaped", { helpers: {} });
  const describeSettingsError = loadPureFunction("describeSettingsError", {
    safeText(value) {
      return String(value === null || typeof value === "undefined" ? "" : value).trim();
    }
  });
  assert.strictEqual(
    escaped('<img src=x onerror="alert(1)">&\''),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;"
  );
  assert.strictEqual(
    describeSettingsError(new Error("Failed to fetch")),
    "无法连接本地 adapter，请确认服务已启动。"
  );
  assert.strictEqual(
    describeSettingsError({ name: "AbortError", message: "aborted" }),
    "请求超时，请确认本地 adapter 正常运行。"
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
  includesAll(functionSource("runPptStructureReview"), [
    'startSlide = safeText(byId("ppt-structure-start-slide").value)',
    'endSlide = safeText(byId("ppt-structure-end-slide").value)'
  ], "large-deck range inputs must distinguish blank values from an entered zero");
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
  assert.match(
    css,
    /@media \(max-width: 380px\)[\s\S]*?\.structure-range-grid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/,
    "320px PPT pane must stack the structure review range inputs"
  );
  assert.ok(!css.includes(".workflow-profile-list-row .settings-card"), "workflow rows must not nest cards");
}

function testLiveSettingsExperienceContract() {
  const refresh = functionSource("refreshSettings");
  const manager = functionSource("renderProfileManager");
  const loadProfiles = functionSource("loadProfiles");
  const syncRefresh = functionSource("syncSettingsRefreshController");
  const refreshEligibility = functionSource("isSettingsRefreshEligible");
  const diagnostics = functionSource("refreshDiagnostics");
  const copyDiagnostics = functionSource("copyDiagnostics");
  const bindings = functionSource("bindEvents");

  includesAll(js, [
    "settingsRefreshController",
    "configRefreshRequestId",
    "configRefreshPromise",
    "modelInterfaceDetectable",
    "providerUrlEditorOpen",
    "workflowHelpPinned",
    "deriveModelInterfaceState"
  ], "PPT live settings state");
  includesAll(functionSource("renderModelInterfaceState"), [
    "TASK_API_KEY_DEFS.forEach",
    "state.profilesByTask[definition.taskType]",
    "TASK_API_KEY_DEFS.map",
    'byId("provider-readiness-badge")',
    'byId("diagnostics-summary")'
  ], "PPT model interface readiness");
  includesAll(functionSource("renderProfileStrip"), [
    "select.setAttribute(",
    '"aria-label"',
    '"选择结构审查模型配置"',
    '"选择智能总结模型配置"'
  ], "task-specific workflow selector label");
  includesAll(refresh, [
    "configRefreshRequestId",
    "configRefreshPromise",
    "SETTINGS_REFRESH_REQUEST_TIMEOUT_MS",
    "loadProfiles(requestId",
    "renderModelInterfaceState",
    "releaseRefresh"
  ], "PPT guarded settings refresh");
  excludesAll(refresh, [
    "refreshDiagnostics()",
    "setStatus(",
    "setResult("
  ], "PPT settings refresh isolation");
  includesAll(loadProfiles, [
    "Promise.all(TASK_API_KEY_DEFS.map",
    "state.profilesByTask",
    "previousProfiles",
    "superseded: true",
    "failed: true",
    "loadError"
  ], "PPT profile refresh preservation");
  assert.ok(
    functionSource("isFatalStructurePollError").includes("PPT_STRUCTURE_AUTH_SNAPSHOT_FAILED"),
    "auth snapshot failures must not be polled as interrupted jobs"
  );
  assert.ok(!manager.includes('profile.note || "无备注"'), "empty PPT notes must not render a placeholder");
  includesAll(refreshEligibility, [
    'state.currentView === "settings"',
    'document.visibilityState !== "hidden"',
    "!state.workflowEditor.open",
    "!state.providerUrlEditorOpen",
    "!state.workflowProfileMutationBusy"
  ], "PPT refresh eligibility");
  includesAll(syncRefresh, [
    "isSettingsRefreshEligible()",
    "invalidateSettingsRefresh"
  ], "PPT refresh lifecycle");
  assert.ok(diagnostics.includes("setSettingsStatus"), "diagnostics feedback must stay in settings");
  assert.ok(!diagnostics.includes("setStatus("), "diagnostics must not overwrite task status");
  includesAll(copyDiagnostics, [
    "state.diagnosticsText",
    "setSettingsStatus"
  ], "PPT diagnostics copy isolation");
  includesAll(bindings, [
    'byId("workflow-task-tabs").addEventListener("keydown"',
    'byId("diagnostics-disclosure").addEventListener("toggle"',
    'document.addEventListener("visibilitychange"',
    '"workflow-help-button"',
    '"workflow-help-popover"'
  ], "PPT settings interaction bindings");
}

testStaticMarkupContract();
testStatusAndMutationBusyContract();
testTaskScopedProfileAndHelperContract();
testImmediateActivationContract();
testStableProfileSelectionInteraction();
testManagerAndEditorContract();
testProfileLoadFailureAndRequestOrderingContract();
testEscapedFallbackContract();
testPptWorkflowPreservationContract();
testNarrowLayoutContract();
testLiveSettingsExperienceContract();

console.log("PPT workflow settings source contract passed.");
