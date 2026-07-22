const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const root = "formal-plugin-kit/wps-ai-assistant_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const css = fs.readFileSync(`${root}/taskpane.css`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const sharedHelpers = require(`../wps-ai-assistant_1.0.0/taskpane-helpers.js`);

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

function loadPureFunction(name, helpers = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, { helpers });
}

function loadFunction(name, context = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, context);
}

const taskDefinitions = [
  ["word.smart_write", "智能编写"],
  ["word.smart_imitation", "智能仿写"],
  ["word.document_review", "文档审查"],
  ["word.format_review", "格式审查"]
];

// Static DOM contract: one task tab controls one compact list/editor surface.
assert.ok(html.includes('id="workflow-task-tabs"'));
assert.ok(html.includes('id="workflow-settings-home"'));
assert.ok(html.includes('id="workflow-profile-manager"'));
taskDefinitions.forEach(([taskType, label]) => {
  assert.ok(html.includes(`data-workflow-task-tab="${taskType}"`), taskType);
  assert.ok(html.includes(`>${label}</button>`), label);
});
assert.ok(!html.includes('id="btn-activate-workflow-profile"'));

// Provider name and shared-key editing are intentionally absent from the Word UI.
assert.ok(html.includes('id="provider-base-url"'));
[
  'id="provider-name"',
  'id="provider-api-key"',
  'id="btn-save-api-key"',
  'id="btn-clear-api-key"'
].forEach((token) => assert.ok(!html.includes(token), token));

const managerSource = functionSource("renderWorkflowProfileManager");
assert.ok(managerSource.includes("getSettingsWorkflowTaskType()"));
assert.ok(!managerSource.includes("TASK_API_KEY_DEFS.forEach"));
assert.ok(managerSource.includes('data-workflow-action="create-open"'));
assert.ok(managerSource.includes('data-workflow-action="edit-open"'));
assert.ok(managerSource.includes("canDeleteWorkflowProfile"));
assert.ok(!managerSource.includes('profile.note || "暂无备注"'));
assert.ok(managerSource.includes("if (profile.note)"));
assert.ok(managerSource.includes("workflow-profile-note"));

// Live model-interface state is derived from the URL and active workflow profiles.
[
  "configRefreshRequestId: 0",
  "modelInterfaceDetectable: false",
  "settingsRefreshController: null",
  "workflowHelpPinned: false"
].forEach((token) => assert.ok(js.includes(token), token));

const modelInterfaceSource = functionSource("renderModelInterfaceState");
assert.ok(modelInterfaceSource.includes("TASK_API_KEY_DEFS.map"));
assert.ok(modelInterfaceSource.includes("getWorkflowProfileData"));
assert.ok(modelInterfaceSource.includes("helpers.deriveModelInterfaceState"));
assert.ok(modelInterfaceSource.includes('"readiness-badge is-" + modelState.code'));
assert.ok(modelInterfaceSource.includes("modelState.label"));
assert.ok(modelInterfaceSource.includes('byId("provider-summary-url")'));
assert.ok(modelInterfaceSource.includes('setAttribute("title"'));
assert.ok(modelInterfaceSource.includes('byId("diagnostics-summary")'));

const refreshConfigSource = functionSource("refreshConfig");
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId + 1"));
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId = requestId"));
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId !== requestId"));
assert.ok(refreshConfigSource.includes("refreshAllWorkflowProfiles"));
assert.ok(refreshConfigSource.includes("state.modelInterfaceDetectable = true"));
assert.ok(refreshConfigSource.includes("state.modelInterfaceDetectable = false"));
assert.ok(refreshConfigSource.includes("renderModelInterfaceState"));
assert.ok(!refreshConfigSource.includes("providerConfigured"));
assert.ok(!refreshConfigSource.includes("refreshDiagnostics"));
assert.ok(refreshConfigSource.indexOf("state.configRefreshRequestId !== requestId") < refreshConfigSource.indexOf("setHealthBadge"));
assert.ok(refreshConfigSource.lastIndexOf("state.configRefreshRequestId !== requestId") < refreshConfigSource.lastIndexOf("setAdapterUnavailableState"));

const providerLineSource = functionSource("setProviderLine");
assert.ok(providerLineSource.startsWith("function setProviderLine(providerName)"));
assert.ok(!providerLineSource.includes("configured"));

const loadProfilesSource = functionSource("loadWorkflowProfiles");
assert.ok(loadProfilesSource.includes("renderModelInterfaceState(state.modelInterfaceDetectable)"));

const settingsRefreshSource = functionSource("syncSettingsRefreshController");
assert.ok(settingsRefreshSource.includes('byId("settings-view").classList.contains("active")'));
assert.ok(settingsRefreshSource.includes('document.visibilityState !== "hidden"'));
assert.ok(settingsRefreshSource.includes('state.knowledgeView === "home"'));
assert.ok(settingsRefreshSource.includes("!state.workflowProfileEditor"));
assert.ok(settingsRefreshSource.includes("state.settingsRefreshController.start()"));
assert.ok(settingsRefreshSource.includes("state.settingsRefreshController.stop()"));

const initControllerIndex = js.lastIndexOf("helpers.createSettingsRefreshController");
const firstSwitchModeIndex = js.lastIndexOf("switchMode(getInitialMode())");
assert.ok(initControllerIndex >= 0 && initControllerIndex < firstSwitchModeIndex);
assert.ok(js.includes("intervalMs: 30000"));
assert.ok(js.includes('document.addEventListener("visibilitychange", syncSettingsRefreshController)'));

const refreshLifecycleState = {
  knowledgeView: "home",
  workflowProfileEditor: null,
  settingsRefreshController: {
    startCount: 0,
    stopCount: 0,
    start() { this.startCount += 1; },
    stop() { this.stopCount += 1; }
  }
};
let settingsViewActive = true;
const refreshLifecycleDocument = { visibilityState: "visible" };
const syncSettingsRefresh = loadFunction("syncSettingsRefreshController", {
  state: refreshLifecycleState,
  document: refreshLifecycleDocument,
  byId: () => ({ classList: { contains: () => settingsViewActive } })
});
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.startCount, 1);
refreshLifecycleDocument.visibilityState = "hidden";
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.stopCount, 1);
refreshLifecycleDocument.visibilityState = "visible";
refreshLifecycleState.knowledgeView = "scope";
syncSettingsRefresh();
refreshLifecycleState.knowledgeView = "home";
refreshLifecycleState.workflowProfileEditor = { mode: "edit" };
syncSettingsRefresh();
refreshLifecycleState.workflowProfileEditor = null;
settingsViewActive = false;
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.stopCount, 4);

// The host must delegate decisions to the shared helper API when it is available.
[
  "workflowProfileOptionState",
  "validateWorkflowProfileDraft",
  "shouldActivateNewWorkflowProfile"
].forEach((name) => assert.ok(js.includes(`helpers.${name}`), name));

// Behavioral source contract for the host fallbacks while the shared helper lands.
const optionState = loadPureFunction("getWorkflowProfileOptionState");
assert.strictEqual(optionState({ id: "p1", keyConfigured: false }, "p2", false).disabled, true);
assert.strictEqual(optionState({ id: "p1", keyConfigured: true }, "p2", true).disabled, true);
assert.strictEqual(optionState({ id: "p1", keyConfigured: true }, "p2", false).disabled, false);

const validateDraft = loadPureFunction("getWorkflowProfileDraftValidation");
assert.strictEqual(validateDraft({ name: "", apiKey: "secret" }, true).valid, false);
assert.strictEqual(validateDraft({ name: "流程 A", apiKey: "" }, true).valid, false);
assert.strictEqual(validateDraft({ name: "流程 A", apiKey: "" }, false).valid, true);

const shouldActivate = loadPureFunction("getShouldActivateNewWorkflowProfile");
assert.strictEqual(shouldActivate({ activeProfileId: "" }, false), true);
assert.strictEqual(shouldActivate({ activeProfileId: "active" }, false), false);
assert.strictEqual(shouldActivate({ activeProfileId: "active" }, true), true);

// The wrappers normalize the shared helper signatures used by all three hosts.
const integratedOptionState = loadPureFunction("getWorkflowProfileOptionState", sharedHelpers);
assert.strictEqual(integratedOptionState({ id: "p1", name: "A", keyConfigured: true }, "p2", true).disabled, true);
const integratedValidation = loadPureFunction("getWorkflowProfileDraftValidation", sharedHelpers);
assert.strictEqual(integratedValidation({ name: "流程 A", note: "", apiKey: "secret" }, true).valid, true);
assert.strictEqual(integratedValidation({ name: "流程 A", note: "", apiKey: "" }, false).valid, true);
const integratedActivation = loadPureFunction("getShouldActivateNewWorkflowProfile", sharedHelpers);
assert.strictEqual(integratedActivation({ profileCount: 0, activeProfileId: "" }, false), true);
assert.strictEqual(integratedActivation({ profileCount: 2, activeProfileId: "p1" }, false), false);

const stripSource = functionSource("renderWorkflowProfileStrip");
assert.ok(stripSource.includes("option.disabled = optionState.disabled"));
assert.ok(stripSource.includes("select.disabled = isWorkflowInteractionBlocked()"));

const selectChangeSource = functionSource("handleWorkflowProfileSelectionChange");
assert.ok(selectChangeSource.includes("activateWorkflowProfile"));
assert.ok(selectChangeSource.includes("previousProfileId"));

const activateSource = functionSource("activateWorkflowProfile");
assert.ok(activateSource.includes("previousProfileId"));
assert.ok(activateSource.includes("state.workflowProfileSelections[taskType] = previousProfileId"));

const deleteSource = functionSource("deleteWorkflowProfile");
assert.ok(deleteSource.includes("canDeleteWorkflowProfile"));
assert.ok(deleteSource.includes("profile.name"));
assert.ok(deleteSource.includes("确认删除工作流“"));

const saveEditSource = functionSource("saveWorkflowProfileEdit");
const patchIndex = saveEditSource.indexOf('{ method: "PATCH" }');
const replaceKeyIndex = saveEditSource.indexOf('"/api-key"');
assert.ok(patchIndex >= 0, "edit must PATCH metadata");
assert.ok(replaceKeyIndex > patchIndex, "key replacement must follow metadata PATCH");
assert.ok(saveEditSource.includes("if (!apiKey)"), "blank edit key must skip replacement");
assert.ok(saveEditSource.includes("名称和备注已保存，但密钥更换失败"));

const toggleSource = functionSource("toggleSettingsShortcut");
[
  "resetSmartWritePreviewState",
  "resetDocumentReviewState",
  "setApplyEnabled",
  'innerHTML = ""'
].forEach((token) => assert.ok(!toggleSource.includes(token), token));
assert.ok(toggleSource.includes('switchView("settings")'));
assert.ok(toggleSource.includes('switchView("home")'));

const diagnosticsToggleSource = functionSource("handleDiagnosticsDisclosureToggle");
assert.ok(diagnosticsToggleSource.includes("event.currentTarget.open"));
assert.ok(diagnosticsToggleSource.includes("refreshDiagnostics()"));
const knowledgeViewSource = functionSource("setKnowledgeView");
assert.ok(knowledgeViewSource.includes('view === "home"'));
assert.ok(knowledgeViewSource.includes("diagnosticsDisclosure.open = false"));
assert.ok(knowledgeViewSource.includes("syncSettingsRefreshController()"));

const reviewFailures = [];

function reviewCheck(name, check) {
  try {
    check();
  } catch (error) {
    reviewFailures.push(`${name}: ${error.message}`);
  }
}

reviewCheck("settings status is visible and synchronized", () => {
  assert.ok(html.includes('id="settings-status-line"'), "missing visible settings status line");
  assert.ok(functionSource("setStatus").includes('byId("settings-status-line")'));
});

reviewCheck("workflow activation is blocked while review or mutation is active", () => {
  const blocked = vm.runInNewContext(`(${functionSource("isWorkflowInteractionBlocked")})`, {
    state: { documentReviewJobId: "", workflowProfileMutationBusy: false }
  });
  assert.strictEqual(blocked(), false);
  const blockedByReview = vm.runInNewContext(`(${functionSource("isWorkflowInteractionBlocked")})`, {
    state: { documentReviewJobId: "job-1", workflowProfileMutationBusy: false }
  });
  assert.strictEqual(blockedByReview(), true);
  const blockedByMutation = vm.runInNewContext(`(${functionSource("isWorkflowInteractionBlocked")})`, {
    state: { documentReviewJobId: "", workflowProfileMutationBusy: true }
  });
  assert.strictEqual(blockedByMutation(), true);
  assert.ok(stripSource.includes("isWorkflowInteractionBlocked()"));
  assert.ok(activateSource.includes("isWorkflowInteractionBlocked()"));
  assert.ok(functionSource("runPrimaryAction").includes("state.workflowProfileMutationBusy"));
  const jobSetterSource = functionSource("setDocumentReviewJobId");
  assert.ok(jobSetterSource.includes("renderWorkflowProfileStrip()"));
  assert.strictEqual((js.match(/state\.documentReviewJobId\s*=/g) || []).length, 1);
});

reviewCheck("dirty workflow editor uses one discard confirmation", () => {
  const confirmSource = functionSource("confirmWorkflowEditorDiscard");
  assert.ok(confirmSource.includes("workflowProfileEditor.dirty"));
  assert.ok(confirmSource.includes("window.confirm"));
  assert.ok(functionSource("handleWorkflowTaskTabClick").includes("confirmWorkflowEditorDiscard()"));
  assert.ok(functionSource("handleWorkflowProfileManagerAction").includes("confirmWorkflowEditorDiscard()"));
  assert.ok(toggleSource.includes("confirmWorkflowEditorDiscard()"));
  assert.ok(functionSource("bindEvents").includes('addEventListener("input", markWorkflowProfileEditorDirty)'));
});

reviewCheck("workflow tabs support roving keyboard navigation", () => {
  const tabsSource = functionSource("renderWorkflowTaskTabs");
  const keydownSource = functionSource("handleWorkflowTaskTabKeydown");
  assert.ok(tabsSource.includes("tabIndex = active ? 0 : -1"));
  ["ArrowLeft", "ArrowRight", "Home", "End", "preventDefault", ".click()", ".focus()", "scrollIntoView"].forEach(
    (token) => assert.ok(keydownSource.includes(token), token)
  );
  assert.ok(keydownSource.includes('behavior: "smooth"'));
  assert.ok(keydownSource.includes('block: "nearest"'));
  assert.ok(keydownSource.includes('inline: "nearest"'));
});

reviewCheck("first workflow activation checkbox is checked in the DOM", () => {
  assert.ok(managerSource.includes("shouldCheckActivate"));
  assert.ok(managerSource.includes(" checked"));
});

reviewCheck("workflow load errors can retry and cannot create", () => {
  assert.ok(managerSource.includes('data-workflow-action="reload"'), "missing reload action");
  assert.ok(managerSource.includes("createDisabledAttribute"), "new action is not disabled for loadError");
  assert.ok(functionSource("handleWorkflowProfileManagerAction").includes('action === "reload"'));
});

reviewCheck("workflow loads use per-task request sequencing", () => {
  const loadSource = functionSource("loadWorkflowProfiles");
  assert.ok(js.includes("workflowProfileRequestSequence: {}"));
  assert.ok(loadSource.includes("requestId"));
  assert.ok(loadSource.includes("isWorkflowProfileRequestCurrent"));
  assert.ok(activateSource.includes("invalidateWorkflowProfileRequests(taskType)"));
});

reviewCheck("provider URL editor supports summary edit and cancel folding", () => {
  assert.ok(html.includes('id="provider-url-details"'));
  assert.ok(html.includes("<summary"));
  assert.ok(html.includes('id="btn-cancel-provider-url"'));
  assert.ok(css.includes(".provider-url-details"));
});

if (reviewFailures.length) {
  throw new Error(`Word review regressions:\n- ${reviewFailures.join("\n- ")}`);
}

// The full-width subpage and compact rows must stay inside a 420px Word pane.
assert.ok(css.includes(".workflow-task-tabs"));
assert.ok(css.includes(".workflow-settings-subpage"));
assert.ok(css.includes("minmax(0, 1fr)"));
assert.ok(css.includes("max-width: 100%"));
assert.ok(css.includes("overflow-x: hidden"));
assert.ok(!css.includes(".workflow-profile-row .settings-card"));

console.log("Word workflow settings tests passed");
