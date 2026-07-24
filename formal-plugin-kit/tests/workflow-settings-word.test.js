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
assert.ok(!managerSource.includes("else if (!data.profiles.length)"));
assert.ok(managerSource.includes("if (data.profiles.length)"));

// Live model-interface state is derived from the URL and active workflow profiles.
[
  "configRefreshRequestId: 0",
  "configRefreshPromise: null",
  "configRefreshActiveRequestId: 0",
  "configRefreshActiveSilent: false",
  "configRefreshQueued: false",
  "configRefreshQueuedSilent: true",
  "modelInterfaceDetectable: false",
  "settingsRefreshController: null",
  "workflowHelpPinned: false",
  "providerUrlEditorOpen: false"
].forEach((token) => assert.ok(js.includes(token), token));

const modelInterfaceSource = functionSource("renderModelInterfaceState");
assert.ok(modelInterfaceSource.includes("TASK_API_KEY_DEFS.map"));
assert.ok(modelInterfaceSource.includes("getWorkflowProfileData"));
assert.ok(modelInterfaceSource.includes("helpers.deriveModelInterfaceState"));
assert.ok(modelInterfaceSource.includes('"readiness-badge is-" + modelState.code'));
assert.ok(modelInterfaceSource.includes("modelState.label"));
assert.ok(modelInterfaceSource.includes('byId("provider-summary-url")'));
assert.ok(modelInterfaceSource.includes('setNodeAttributeIfChanged(summary, "title"'));
assert.ok(modelInterfaceSource.includes('byId("diagnostics-summary")'));

const refreshConfigSource = functionSource("refreshConfig");
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId + 1"));
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId = requestId"));
assert.ok(refreshConfigSource.includes("state.configRefreshRequestId !== requestId"));
assert.ok(refreshConfigSource.includes("state.configRefreshPromise"));
assert.ok(refreshConfigSource.includes("state.configRefreshActiveSilent"));
assert.ok(refreshConfigSource.includes("state.configRefreshQueuedSilent"));
assert.ok(refreshConfigSource.includes("Boolean(options && options.silent)"));
assert.ok(refreshConfigSource.includes("refreshAllWorkflowProfiles"));
assert.ok(refreshConfigSource.includes("state.modelInterfaceDetectable = true"));
assert.ok(refreshConfigSource.includes("state.modelInterfaceDetectable = false"));
assert.ok(refreshConfigSource.includes("renderModelInterfaceState"));
assert.ok(!refreshConfigSource.includes("providerConfigured"));
assert.ok(!refreshConfigSource.includes("refreshDiagnostics"));
assert.ok(!refreshConfigSource.includes("setStatus("));
assert.ok(!refreshConfigSource.includes("setTrace("));
assert.ok(!refreshConfigSource.includes("setResult("));
assert.ok(!refreshConfigSource.includes("setAdapterUnavailableState("));
assert.ok(!refreshConfigSource.includes(".finally("));
assert.ok(refreshConfigSource.includes("SETTINGS_REFRESH_REQUEST_TIMEOUT_MS"));
assert.ok(refreshConfigSource.indexOf("state.configRefreshRequestId !== requestId") < refreshConfigSource.indexOf("setHealthBadge"));

const providerLineSource = functionSource("setProviderLine");
assert.ok(providerLineSource.startsWith("function setProviderLine(providerName)"));
assert.ok(!providerLineSource.includes("configured"));

const loadProfilesSource = functionSource("loadWorkflowProfiles");
assert.ok(loadProfilesSource.includes("renderModelInterfaceState(state.modelInterfaceDetectable)"));
assert.ok(loadProfilesSource.includes("configRefreshRequestId"));
assert.ok(loadProfilesSource.includes("previousProfileData"));

const saveProviderUrlSource = functionSource("saveProviderBaseUrl");
const invalidateBeforeUrlRefresh = saveProviderUrlSource.indexOf("invalidateConfigRefresh()");
assert.ok(invalidateBeforeUrlRefresh >= 0);
assert.ok(invalidateBeforeUrlRefresh < saveProviderUrlSource.indexOf("refreshConfig({ silent: false })"));

const settingsRefreshSource = functionSource("syncSettingsRefreshController");
assert.ok(settingsRefreshSource.includes('byId("settings-view").classList.contains("active")'));
assert.ok(settingsRefreshSource.includes('document.visibilityState !== "hidden"'));
assert.ok(settingsRefreshSource.includes('state.knowledgeView === "home"'));
assert.ok(settingsRefreshSource.includes("!state.workflowProfileEditor"));
assert.ok(settingsRefreshSource.includes("!state.providerUrlEditorOpen"));
assert.ok(settingsRefreshSource.includes("!state.workflowProfileMutationBusy"));
assert.ok(settingsRefreshSource.includes("state.settingsRefreshController.start()"));
assert.ok(settingsRefreshSource.includes("state.settingsRefreshController.stop()"));
assert.ok(settingsRefreshSource.includes("invalidateConfigRefresh()"));

const initControllerIndex = js.lastIndexOf("helpers.createSettingsRefreshController");
const firstSwitchModeIndex = js.lastIndexOf("switchMode(getInitialMode())");
assert.ok(initControllerIndex >= 0 && initControllerIndex < firstSwitchModeIndex);
assert.ok(js.includes("intervalMs: 30000"));
assert.ok(js.includes("refreshConfig({ silent: true })"));
assert.ok(js.includes('document.addEventListener("visibilitychange", syncSettingsRefreshController)'));

const refreshLifecycleState = {
  configRefreshRequestId: 0,
  configRefreshQueued: false,
  configRefreshQueuedSilent: true,
  knowledgeView: "home",
  workflowProfileEditor: null,
  providerUrlEditorOpen: false,
  workflowProfileMutationBusy: false,
  settingsRefreshController: {
    startCount: 0,
    stopCount: 0,
    running: false,
    start() { this.startCount += 1; this.running = true; },
    stop() { this.stopCount += 1; this.running = false; },
    isRunning() { return this.running; }
  }
};
let settingsViewActive = true;
const refreshLifecycleDocument = { visibilityState: "visible" };
const syncSettingsRefresh = loadFunction("syncSettingsRefreshController", {
  state: refreshLifecycleState,
  document: refreshLifecycleDocument,
  byId: () => ({ classList: { contains: () => settingsViewActive } }),
  invalidateConfigRefresh: loadFunction("invalidateConfigRefresh", { state: refreshLifecycleState })
});
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.startCount, 1);
refreshLifecycleDocument.visibilityState = "hidden";
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.stopCount, 1);
refreshLifecycleDocument.visibilityState = "visible";
syncSettingsRefresh();
refreshLifecycleState.knowledgeView = "scope";
syncSettingsRefresh();
refreshLifecycleState.knowledgeView = "home";
syncSettingsRefresh();
refreshLifecycleState.workflowProfileEditor = { mode: "edit" };
syncSettingsRefresh();
refreshLifecycleState.workflowProfileEditor = null;
syncSettingsRefresh();
refreshLifecycleState.providerUrlEditorOpen = true;
syncSettingsRefresh();
refreshLifecycleState.providerUrlEditorOpen = false;
syncSettingsRefresh();
refreshLifecycleState.workflowProfileMutationBusy = true;
syncSettingsRefresh();
refreshLifecycleState.workflowProfileMutationBusy = false;
syncSettingsRefresh();
settingsViewActive = false;
syncSettingsRefresh();
assert.strictEqual(refreshLifecycleState.settingsRefreshController.stopCount, 6);
assert.strictEqual(refreshLifecycleState.configRefreshRequestId, 6);

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
  ["ArrowLeft", "ArrowRight", "Home", "End", "preventDefault", ".click()", ".focus()", "scrollWorkflowTaskTabIntoView"].forEach(
    (token) => assert.ok(keydownSource.includes(token), token)
  );
  const scrollSource = functionSource("scrollWorkflowTaskTabIntoView");
  assert.ok(scrollSource.includes("prefers-reduced-motion: reduce"));
  assert.ok(scrollSource.includes('behavior: reducedMotion ? "auto" : "smooth"'));
  assert.ok(scrollSource.includes('block: "nearest"'));
  assert.ok(scrollSource.includes('inline: "nearest"'));
  assert.ok(scrollSource.includes("scrollIntoView(true)"));
  assert.ok(scrollSource.includes("try"));
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
  assert.ok(js.includes("state.providerUrlEditorOpen = true"));
  assert.ok(functionSource("closeProviderUrlEditor").includes("state.providerUrlEditorOpen = false"));
  assert.ok(functionSource("closeProviderUrlEditor").includes("suppressRefreshSync !== true"));
  assert.ok(functionSource("bindEvents").includes("syncSettingsRefreshController()"));
});

reviewCheck("diagnostics feedback stays inside settings", () => {
  const refreshDiagnosticsSource = functionSource("refreshDiagnostics");
  const copyDiagnosticsSource = functionSource("copyDiagnostics");
  assert.ok(refreshDiagnosticsSource.includes("setSettingsStatus"));
  assert.ok(!refreshDiagnosticsSource.includes("setStatus("));
  assert.ok(copyDiagnosticsSource.includes("setSettingsStatus"));
  assert.ok(copyDiagnosticsSource.includes("fallbackCopy(text, setSettingsStatus)"));
  assert.ok(!copyDiagnosticsSource.includes("setStatus("));
  assert.ok(functionSource("fallbackCopy").includes("feedback"));
});

reviewCheck("workflow mutations pause settings refresh", () => {
  assert.ok(functionSource("setWorkflowProfileMutationBusy").includes("syncSettingsRefreshController()"));
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

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createRefreshHarness(options = {}) {
  const health = options.health || deferred();
  const calls = {
    request: 0,
    requestTimeouts: [],
    jsonTimeouts: [],
    settingsStatus: [],
    renderDetectable: [],
    healthBadges: [],
    providerLines: [],
    traces: [],
    setStatus: 0,
    setResult: 0,
    setAdapterUnavailableState: 0,
    applyProviderConfig: 0
  };
  const state = {
    configRefreshRequestId: 0,
    configRefreshPromise: null,
    configRefreshActiveRequestId: 0,
    configRefreshActiveSilent: false,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    modelInterfaceDetectable: true,
    providerBaseUrl: "https://cached.example.test/v1",
    rewriteResult: { text: "既有任务结果" },
    copyText: "既有任务结果",
    diagnosticsCopyText: "既有诊断"
  };
  const context = {
    state,
    SETTINGS_REFRESH_REQUEST_TIMEOUT_MS: 8000,
    TASK_API_KEY_DEFS: taskDefinitions.map(([taskType, label]) => ({ taskType, label })),
    request(path, payload, requestOptions) {
      assert.strictEqual(path, "/health");
      calls.request += 1;
      calls.requestTimeouts.push(requestOptions && requestOptions.timeoutMs);
      return health.promise;
    },
    readAdapterJson(path, requestOptions) {
      calls.jsonTimeouts.push(requestOptions && requestOptions.timeoutMs);
      if (path === "/config") {
        return Promise.resolve(options.config || { success: true, data: { providerBaseUrl: "https://fresh.example.test/v1" } });
      }
      return Promise.resolve({ success: true, data: { templates: [] } });
    },
    refreshAllWorkflowProfiles() {
      if (options.profilePromise) return options.profilePromise;
      return Promise.resolve(options.profileResults || [{}, {}, {}, {}]);
    },
    setSettingsStatus(message) { calls.settingsStatus.push(message); },
    setHealthBadge(mode, text) { calls.healthBadges.push([mode, text]); },
    setProviderLine(value) { calls.providerLines.push(value); },
    setTrace(value) { calls.traces.push(value); },
    applyProviderConfig() { calls.applyProviderConfig += 1; },
    resolveSelectionScope() {},
    renderFallbackTemplateOptions() {},
    mergeTemplates(value) { return value; },
    renderTemplateOptions() {},
    renderModelInterfaceState(value) { calls.renderDetectable.push(value); },
    describeFetchError(error) { return error && error.message || String(error); },
    isSettingsRefreshEligible() { return false; },
    setStatus() { calls.setStatus += 1; },
    setResult() { calls.setResult += 1; },
    setAdapterUnavailableState() { calls.setAdapterUnavailableState += 1; }
  };
  return {
    health,
    calls,
    state,
    refreshConfig: loadFunction("refreshConfig", context)
  };
}

async function runSettingsRefreshBehaviorTests() {
  const configFailure = createRefreshHarness({
    config: { success: false, data: {}, errors: [{ message: "配置读取失败" }] }
  });
  const configFailurePromise = configFailure.refreshConfig();
  configFailure.health.resolve({ traceId: "health-config-failure", data: { providerType: "enterprise-dify-chat" } });
  await configFailurePromise;
  assert.strictEqual(configFailure.state.modelInterfaceDetectable, false);
  assert.strictEqual(configFailure.calls.renderDetectable.at(-1), false);
  assert.strictEqual(configFailure.calls.applyProviderConfig, 0);
  assert.strictEqual(configFailure.state.copyText, "既有任务结果");
  assert.strictEqual(configFailure.state.diagnosticsCopyText, "既有诊断");
  assert.deepStrictEqual(configFailure.state.rewriteResult, { text: "既有任务结果" });
  assert.deepStrictEqual(configFailure.calls.healthBadges, [["badge-ok", "已连接"]]);
  assert.deepStrictEqual(configFailure.calls.providerLines, ["enterprise-dify-chat"]);
  assert.deepStrictEqual(configFailure.calls.traces, []);
  assert.strictEqual(configFailure.calls.setStatus, 0);
  assert.strictEqual(configFailure.calls.setResult, 0);
  assert.strictEqual(configFailure.calls.setAdapterUnavailableState, 0);

  const healthFailure = createRefreshHarness();
  healthFailure.calls.healthBadges.push(["badge-ok", "已连接"]);
  const healthFailurePromise = healthFailure.refreshConfig();
  healthFailure.health.reject(new Error("本地 adapter 未启动"));
  await healthFailurePromise;
  assert.deepStrictEqual(healthFailure.calls.healthBadges.at(-1), ["badge-warn", "待启动"]);
  assert.strictEqual(healthFailure.calls.healthBadges.length, 2);
  assert.strictEqual(healthFailure.state.modelInterfaceDetectable, false);
  assert.strictEqual(healthFailure.calls.renderDetectable.at(-1), false);
  assert.strictEqual(healthFailure.state.copyText, "既有任务结果");
  assert.deepStrictEqual(healthFailure.state.rewriteResult, { text: "既有任务结果" });
  assert.strictEqual(healthFailure.calls.setResult, 0);
  assert.strictEqual(healthFailure.calls.setAdapterUnavailableState, 0);

  const profileFailure = createRefreshHarness({ profileResults: [{}, null, {}, {}] });
  const profileFailurePromise = profileFailure.refreshConfig();
  profileFailure.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await profileFailurePromise;
  assert.strictEqual(profileFailure.state.modelInterfaceDetectable, false);
  assert.strictEqual(profileFailure.calls.renderDetectable.at(-1), false);
  assert.deepStrictEqual(profileFailure.calls.healthBadges, [["badge-ok", "已连接"]]);

  const concurrent = createRefreshHarness();
  const firstRefresh = concurrent.refreshConfig();
  const secondRefresh = concurrent.refreshConfig();
  assert.strictEqual(firstRefresh, secondRefresh);
  assert.strictEqual(concurrent.calls.request, 1);
  concurrent.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await firstRefresh;
  assert.strictEqual(concurrent.state.modelInterfaceDetectable, true);
  assert.deepStrictEqual(concurrent.calls.requestTimeouts, [8000]);
  assert.deepStrictEqual(concurrent.calls.jsonTimeouts, [8000, 8000]);

  const stopped = createRefreshHarness();
  const stoppedPromise = stopped.refreshConfig();
  let controllerRunning = true;
  stopped.state.settingsRefreshController = {
    start() { controllerRunning = true; },
    stop() { controllerRunning = false; },
    isRunning() { return controllerRunning; }
  };
  const syncStoppedController = loadFunction("syncSettingsRefreshController", {
    state: stopped.state,
    document: { visibilityState: "visible" },
    byId: () => ({ classList: { contains: () => false } }),
    invalidateConfigRefresh() { stopped.state.configRefreshRequestId += 1; }
  });
  syncStoppedController();
  assert.strictEqual(controllerRunning, false);
  stopped.health.resolve({ traceId: "late-trace", data: { providerType: "enterprise-dify-chat" } });
  await stoppedPromise;
  assert.deepStrictEqual(stopped.calls.renderDetectable, []);
  assert.strictEqual(stopped.calls.setStatus, 0);
  assert.deepStrictEqual(stopped.calls.traces, []);
  assert.strictEqual(stopped.calls.setResult, 0);

  const lateProfiles = deferred();
  const stoppedDuringProfiles = createRefreshHarness({ profilePromise: lateProfiles.promise });
  const stoppedDuringProfilesPromise = stoppedDuringProfiles.refreshConfig();
  stoppedDuringProfiles.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await Promise.resolve();
  await Promise.resolve();
  let profileControllerRunning = true;
  stoppedDuringProfiles.state.settingsRefreshController = {
    start() { profileControllerRunning = true; },
    stop() { profileControllerRunning = false; },
    isRunning() { return profileControllerRunning; }
  };
  const stopDuringProfiles = loadFunction("syncSettingsRefreshController", {
    state: stoppedDuringProfiles.state,
    document: { visibilityState: "hidden" },
    byId: () => ({ classList: { contains: () => true } }),
    invalidateConfigRefresh() { stoppedDuringProfiles.state.configRefreshRequestId += 1; }
  });
  stopDuringProfiles();
  lateProfiles.resolve([{}, {}, {}, {}]);
  await stoppedDuringProfilesPromise;
  assert.deepStrictEqual(stoppedDuringProfiles.calls.renderDetectable, []);
  assert.ok(!stoppedDuringProfiles.calls.settingsStatus.includes("就绪"));

  const reducedMotionCalls = [];
  const scrollReduced = loadFunction("scrollWorkflowTaskTabIntoView", {
    window: { matchMedia: () => ({ matches: true }) }
  });
  scrollReduced({ scrollIntoView(value) { reducedMotionCalls.push(value); } });
  assert.strictEqual(reducedMotionCalls[0].behavior, "auto");

  const fallbackCalls = [];
  const scrollFallback = loadFunction("scrollWorkflowTaskTabIntoView", {
    window: { matchMedia: () => ({ matches: false }) }
  });
  scrollFallback({
    scrollIntoView(value) {
      fallbackCalls.push(value);
      if (typeof value === "object") throw new Error("旧 WebView 不支持对象参数");
    }
  });
  assert.strictEqual(fallbackCalls.length, 2);
  assert.strictEqual(fallbackCalls[1], true);

  const cachedTaskType = "word.smart_write";
  const cachedProfiles = {
    taskType: cachedTaskType,
    activeProfileId: "stable-active",
    profileCount: 2,
    profiles: [
      { id: "stable-active", name: "稳定主档案", keyConfigured: true },
      { id: "stable-backup", name: "稳定备用档案", keyConfigured: true }
    ]
  };
  const loadState = {
    configRefreshRequestId: 0,
    modelInterfaceDetectable: true,
    workflowProfiles: { [cachedTaskType]: cachedProfiles },
    workflowProfileSelections: { [cachedTaskType]: "stable-backup" }
  };
  let loadRenderCount = 0;
  const loadProfilesFailure = loadFunction("loadWorkflowProfiles", {
    state: loadState,
    request() { return Promise.reject(new Error("临时读取失败")); },
    nextWorkflowProfileRequestId() { return 1; },
    isWorkflowProfileRequestCurrent() { return true; },
    describeFetchError(error) { return error.message; },
    renderWorkflowProfileStrip() { loadRenderCount += 1; },
    renderWorkflowProfileManager() { loadRenderCount += 1; },
    renderModelInterfaceState() { loadRenderCount += 1; }
  });
  const failedLoadResult = await loadProfilesFailure(cachedTaskType);
  assert.strictEqual(failedLoadResult, null);
  assert.strictEqual(loadState.workflowProfiles[cachedTaskType].activeProfileId, "stable-active");
  assert.deepStrictEqual(loadState.workflowProfiles[cachedTaskType].profiles, cachedProfiles.profiles);
  assert.strictEqual(loadState.workflowProfileSelections[cachedTaskType], "stable-backup");
  assert.strictEqual(loadState.workflowProfiles[cachedTaskType].loadError, "临时读取失败");
  assert.strictEqual(loadRenderCount, 3);

  const emptyLoadState = {
    configRefreshRequestId: 0,
    modelInterfaceDetectable: true,
    workflowProfiles: {},
    workflowProfileSelections: {}
  };
  const firstLoadFailure = loadFunction("loadWorkflowProfiles", {
    state: emptyLoadState,
    request() { return Promise.reject(new Error("首次读取失败")); },
    nextWorkflowProfileRequestId() { return 1; },
    isWorkflowProfileRequestCurrent() { return true; },
    describeFetchError(error) { return error.message; },
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderModelInterfaceState() {}
  });
  await firstLoadFailure(cachedTaskType);
  assert.strictEqual(emptyLoadState.workflowProfiles[cachedTaskType].activeProfileId, "");
  assert.strictEqual(Array.isArray(emptyLoadState.workflowProfiles[cachedTaskType].profiles), true);
  assert.strictEqual(emptyLoadState.workflowProfiles[cachedTaskType].profiles.length, 0);
  assert.strictEqual(emptyLoadState.workflowProfiles[cachedTaskType].loadError, "首次读取失败");
}

runSettingsRefreshBehaviorTests().then(() => {
  console.log("Word workflow settings tests passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
