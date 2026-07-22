const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const root = "formal-plugin-kit/wps-ai-assistant-et_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const css = fs.readFileSync(`${root}/taskpane.css`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");

function functionSource(name) {
  const start = js.indexOf(`  function ${name}(`);
  assert.notStrictEqual(start, -1, `missing function ${name}`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

function loadFunction(name, context = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, context);
}

function assertIncludesAll(source, markers) {
  markers.forEach((marker) => assert.ok(source.includes(marker), marker));
}

function assertAppearsInOrder(source, markers, label) {
  let position = -1;
  markers.forEach((marker) => {
    const next = source.indexOf(marker, position + 1);
    assert.ok(next > position, `${label}: expected ${marker} after previous marker`);
    position = next;
  });
}

function assertCompactMarkupContract() {
  [
    'id="workflow-settings-home"',
    'id="btn-new-workflow-profile"',
    'id="workflow-profile-manager"',
    'id="workflow-editor-view"',
    'id="workflow-editor-name"',
    'id="workflow-editor-note"',
    'id="workflow-editor-key"',
    'id="workflow-editor-activate"',
    'id="workflow-editor-error"',
    'id="btn-save-workflow-editor"',
    'id="btn-cancel-workflow-editor"',
    'id="workflow-delete-dialog"',
    'id="workflow-delete-name"',
    'id="btn-confirm-workflow-delete"',
    'id="workflow-switch-feedback"'
  ].forEach((marker) => assert.ok(html.includes(marker), marker));

  [
    'id="provider-name"',
    'id="provider-api-key"',
    'id="btn-save-api-key"',
    'id="btn-clear-api-key"',
    'id="btn-activate-workflow-profile"'
  ].forEach((marker) => assert.ok(!html.includes(marker), marker));

  assert.ok(html.includes('id="workflow-task-tabs" class="workflow-task-tabs" role="tablist" aria-label="Excel 任务"'));
  assert.ok(html.includes('role="tab" data-workflow-task-tab="excel.analysis" aria-selected="true">智能分析</button>'));
  assert.strictEqual((html.match(/data-workflow-task-tab=/g) || []).length, 1, "Excel must expose one task tab");
  ["word.smart_write", "word.smart_imitation", "word.document_review", "word.format_review", "ppt.slide_assistant"]
    .forEach((task) => assert.ok(!html.includes(`data-workflow-task-tab="${task}"`), `Excel exposes ${task}`));

  assert.ok(html.includes('id="provider-base-url"'));
  assert.ok(html.includes('id="btn-save-provider-url"'));
  assert.ok(html.includes('role="dialog"'));
}

function assertCompactCssContract() {
  assertIncludesAll(css, [
    ".workflow-profile-list",
    ".workflow-profile-list-row",
    ".workflow-profile-note",
    ".workflow-editor-view",
    ".workflow-editor-actions",
    ".workflow-delete-dialog",
    ".workflow-empty-state",
    "text-overflow: ellipsis",
    "overflow-x: hidden",
    "@media (max-width: 420px)"
  ]);
  assert.ok(css.includes("grid-template-columns: minmax(0, 1fr) auto"));
}

function assertFixedExcelWorkflowContract() {
  assert.ok(js.includes('var EXCEL_WORKFLOW_TASK_TYPE = "excel.analysis";'));
  assert.ok(js.includes("function renderWorkflowTaskTabs()"));
  assertIncludesAll(js, [
    "helpers.workflowProfileOptionState",
    "helpers.validateWorkflowProfileDraft",
    "helpers.shouldActivateNewWorkflowProfile"
  ]);
  assert.ok(!js.includes('data-workflow-task="excel.analysis"'));
  assert.ok(!js.includes("function saveProviderApiKey()"));
  assert.ok(!js.includes("function clearProviderApiKey()"));
  assert.ok(!js.includes('byId("provider-name")'));
  assert.ok(!js.includes('byId("provider-api-key")'));
  assert.ok(!js.includes('byId("btn-save-api-key")'));
  assert.ok(!js.includes('byId("btn-clear-api-key")'));
  assert.ok(!js.includes('byId("btn-activate-workflow-profile")'));

  const saveUrl = functionSource("saveProviderBaseUrl");
  assert.ok(saveUrl.includes('{ baseUrl: baseUrl }'));
  assert.ok(!saveUrl.includes("providerName"));
}

function assertImmediateActivationContract() {
  const renderStrip = functionSource("renderWorkflowProfileStrip");
  const activate = functionSource("activateWorkflowProfile");
  const bind = functionSource("bindEvents");

  assertIncludesAll(renderStrip, [
    "helpers.workflowProfileOptionState",
    "option.disabled = optionState.disabled",
    "select.disabled = state.busy || state.workflowProfileMutationBusy"
  ]);
  assert.ok(bind.includes('byId("workflow-profile-select").addEventListener("change"'));
  assert.ok(bind.includes("activateWorkflowProfile(event.target.value"));
  assert.ok(!bind.includes("workflowProfileSelection = event.target.value"));
  assertIncludesAll(activate, [
    "previousProfileId",
    "state.workflowProfileSelection = previousProfileId",
    "切换工作流失败"
  ]);
}

function assertEditorSaveContract() {
  const openEditor = functionSource("openWorkflowEditor");
  const saveEditor = functionSource("saveWorkflowEditor");
  assert.ok(functionSource("closeWorkflowEditor").includes("workflowEditor"));
  assert.ok(functionSource("showWorkflowDeleteDialog").includes("workflow-delete-name"));
  assert.ok(openEditor.includes("shouldActivateNewWorkflowProfile"));
  assert.ok(saveEditor.includes("helpers.validateWorkflowProfileDraft"));
  assert.ok(saveEditor.includes("EXCEL_WORKFLOW_TASK_TYPE"));

  const patchIndex = saveEditor.indexOf('method: "PATCH"');
  const keyPathIndex = saveEditor.indexOf('encodeURIComponent(profileId) + "/api-key"');
  const emptyKeyGuardIndex = saveEditor.indexOf("if (!checked.apiKey)");
  assert.ok(patchIndex >= 0, "edit must PATCH name and note");
  assert.ok(emptyKeyGuardIndex > patchIndex, "empty Key guard must follow PATCH success");
  assert.ok(keyPathIndex > emptyKeyGuardIndex, "Key replacement must be optional and ordered after PATCH");
  assertIncludesAll(saveEditor, [
    "名称和备注已保存",
    "Key 更换失败",
    "原 Key 仍然有效"
  ]);
}

function assertDeleteAndBusyContracts() {
  const renderManager = functionSource("renderWorkflowProfileManager");
  const confirmDelete = functionSource("confirmWorkflowProfileDelete");
  assert.ok(renderManager.includes("helpers.canDeleteWorkflowProfile"));
  assertIncludesAll(confirmDelete, [
    "activeProfileId",
    "当前工作流不能删除",
    'method: "DELETE"'
  ]);
  assert.ok(js.includes("state.busy = Boolean(isBusy)"));
  assert.ok(js.includes("renderWorkflowProfileStrip()"));
}

function assertExcelHostReviewFixContracts() {
  const setStatus = functionSource("setStatus");
  const loadProfiles = functionSource("loadWorkflowProfiles");
  const activate = functionSource("activateWorkflowProfile");
  const setMutationBusy = functionSource("setWorkflowMutationBusy");
  const finishMutation = functionSource("finishWorkflowMutation");
  const finishEditorSave = functionSource("finishWorkflowEditorSave");
  const partialKeyFailure = functionSource("showPartialKeyFailure");
  const confirmDelete = functionSource("confirmWorkflowProfileDelete");
  const closeEditor = functionSource("closeWorkflowEditor");
  const renderManager = functionSource("renderWorkflowProfileManager");
  const handleAction = functionSource("handleWorkflowProfileAction");
  const runAnalysis = functionSource("runExcelAnalysisAction");

  assert.ok(html.includes('id="settings-status-line"'), "settings must expose a live status line");
  assertIncludesAll(setStatus, [
    'setNodeTextIfChanged(byId("status-line")',
    'setNodeTextIfChanged(byId("settings-status-line")'
  ]);

  assert.ok(js.includes("workflowProfileLoadSequence: 0"), "workflow GETs need a request sequence");
  assertIncludesAll(loadProfiles, [
    "requestSequence",
    "++state.workflowProfileLoadSequence",
    "requestSequence !== state.workflowProfileLoadSequence"
  ]);
  assertAppearsInOrder(activate, [
    "state.workflowProfileLoadSequence += 1",
    'request("/provider/workflow-profiles/"'
  ], "activation must invalidate older profile GETs before mutation");

  [
    [finishMutation, "delete reload busy"],
    [finishEditorSave, "save reload busy"],
    [partialKeyFailure, "partial save reload busy"]
  ].forEach(([source, label]) => {
    assertAppearsInOrder(source, [
      "loadWorkflowProfiles()",
      "setWorkflowMutationBusy(false)"
    ], label);
  });
  assertIncludesAll(setMutationBusy, [
    'byId("btn-confirm-workflow-delete").disabled',
    'byId("btn-cancel-workflow-delete").disabled',
    'byId("btn-run-primary").disabled'
  ]);
  assert.ok(
    confirmDelete.includes("state.workflowProfileMutationBusy"),
    "delete confirmation must reject duplicate busy actions"
  );

  assertIncludesAll(closeEditor, [
    'byId("workflow-editor-key").value = ""',
    'byId("workflow-editor-key").type = "password"'
  ]);
  const escapeHtml = vm.runInNewContext(`(${functionSource("escaped")})`, { helpers: {} });
  assert.strictEqual(
    escapeHtml('<img src="x" onerror=\'alert(1)\'>&'),
    "&lt;img src=&quot;x&quot; onerror=&#39;alert(1)&#39;&gt;&amp;"
  );

  assert.ok(
    runAnalysis.includes("state.workflowProfileMutationBusy"),
    "analysis submission must reject workflow mutations"
  );
  assert.ok(
    setMutationBusy.includes("state.busy || state.workflowProfileMutationBusy"),
    "workflow mutations must disable the primary analysis button"
  );

  assert.ok(renderManager.includes("data.loadError"), "manager must render the profile load error");
  assert.ok(renderManager.includes('data-workflow-action="retry"'), "load errors must offer retry");
  assert.ok(
    renderManager.includes("state.workflowProfileMutationBusy || Boolean(data.loadError)"),
    "load errors must disable new profile creation"
  );
  assert.ok(handleAction.includes('action === "retry"'));
}

function assertExcelAnalysisPreservationContract() {
  assertIncludesAll(html, [
    'id="excel-analysis-requirement"',
    'id="excel-range-summary"',
    'id="btn-run-primary"',
    'id="result-view-switch"',
    'id="btn-result-preview"',
    'id="btn-result-plain"',
    'id="btn-copy-result"',
    'id="result-output"'
  ]);
  assertIncludesAll(js, [
    'var EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY = "ai-wps-excel-analysis-active-job-v1";',
    'request("/excel/analysis/jobs"',
    'request("/excel/analysis/jobs/"',
    "function extractExcelRange()",
    "function pollExcelAnalysisJob(jobId, stopWaiting)",
    "function resumeExcelAnalysisActiveJob()",
    "function renderExcelAnalysisResult(data)",
    "analysisRequirement",
    "structuredReport",
    "plainText",
    "clientJobId"
  ]);
  const switchMode = functionSource("switchMode");
  assert.ok(switchMode.includes('state.currentMode = settingsMode ? "settings" : "excelAnalysis"'));
  assert.ok(switchMode.includes("resumeExcelAnalysisActiveJob()"));
  [
    "state.analysisRequirement =",
    "state.analysisResult = null",
    "state.copyText =",
    'byId("result-output").innerHTML = ""'
  ].forEach((marker) => assert.ok(!switchMode.includes(marker), marker));
}

function assertLiveSettingsExperienceContract() {
  [
    "configRefreshRequestId: 0",
    "configRefreshPromise: null",
    "configRefreshActiveRequestId: 0",
    "configRefreshActiveSilent: false",
    "configRefreshQueued: false",
    "configRefreshQueuedSilent: true",
    "modelInterfaceDetectable: false",
    "modelInterfaceConfigDetectable: false",
    "settingsRefreshController: null",
    "workflowHelpPinned: false",
    "providerUrlEditorOpen: false",
    'settingsProbeTraceId: ""'
  ].forEach((token) => assert.ok(js.includes(token), token));

  const providerLine = functionSource("setProviderLine");
  assert.ok(providerLine.startsWith("  function setProviderLine(providerName)"));
  assert.ok(!providerLine.includes("configured"));

  const modelInterface = functionSource("renderModelInterfaceState");
  assertIncludesAll(modelInterface, [
    "EXCEL_WORKFLOW_TASK_TYPE",
    "getWorkflowProfileData",
    "helpers.deriveModelInterfaceState",
    '"readiness-badge is-" + modelState.code',
    "modelState.label",
    'byId("provider-summary-url")',
    'setNodeAttributeIfChanged(summary, "title"',
    'byId("diagnostics-summary")'
  ]);

  const refresh = functionSource("refreshConfig");
  assertIncludesAll(refresh, [
    "options",
    "silent",
    "state.configRefreshRequestId + 1",
    "state.configRefreshRequestId = requestId",
    "state.configRefreshRequestId !== requestId",
    "state.configRefreshPromise",
    "state.configRefreshQueued",
    "state.configRefreshActiveSilent",
    "state.configRefreshQueuedSilent",
    "SETTINGS_REFRESH_REQUEST_TIMEOUT_MS",
    "loadWorkflowProfiles(requestId",
    "state.modelInterfaceDetectable = true",
    "state.modelInterfaceDetectable = false",
    "renderModelInterfaceState"
  ]);
  assert.ok(refresh.includes("profileResult.superseded"));
  assert.ok(refresh.includes("profileResult.failed"));
  ["providerConfigured", "refreshDiagnostics", "setStatus(", "setResult(", "setTrace(", "setAdapterUnavailableState(", ".finally("].forEach(
    (token) => assert.ok(!refresh.includes(token), token)
  );

  const loadProfiles = functionSource("loadWorkflowProfiles");
  assertIncludesAll(loadProfiles, [
    "previousProfileData",
    "configRefreshRequestId",
    "requestOptions",
    "renderModelInterfaceState(state.modelInterfaceDetectable)"
  ]);
  assert.ok(loadProfiles.includes("superseded: true"));
  assert.ok(loadProfiles.includes("failed: true"));
  assert.ok(!loadProfiles.includes("state.workflowProfileSelection = \"\""));

  const saveUrl = functionSource("saveProviderBaseUrl");
  const saveUrlRefreshIndex = saveUrl.indexOf("refreshConfig({ silent: false })");
  assert.ok(saveUrl.indexOf("invalidateConfigRefresh()") >= 0);
  assert.ok(saveUrlRefreshIndex >= 0);
  assert.ok(saveUrl.indexOf("invalidateConfigRefresh()") < saveUrlRefreshIndex);

  const syncRefresh = functionSource("syncSettingsRefreshController");
  assertIncludesAll(syncRefresh, [
    'byId("settings-view").classList.contains("active")',
    'document.visibilityState !== "hidden"',
    "!state.workflowEditor.open",
    "!state.providerUrlEditorOpen",
    "!state.workflowProfileMutationBusy",
    "state.settingsRefreshController.start()",
    "state.settingsRefreshController.stop()",
    "invalidateConfigRefresh()"
  ]);
  const controllerIndex = js.lastIndexOf("helpers.createSettingsRefreshController");
  const switchIndex = js.lastIndexOf("switchMode(getInitialMode())");
  assert.ok(controllerIndex >= 0 && controllerIndex < switchIndex);
  assert.ok(js.includes("intervalMs: 30000"));
  assert.ok(js.includes("refreshConfig({ silent: true })"));
  assert.ok(js.includes('document.addEventListener("visibilitychange", syncSettingsRefreshController)'));

  const diagnostics = functionSource("handleDiagnosticsDisclosureToggle");
  assertIncludesAll(diagnostics, ["event.currentTarget.open", "refreshDiagnostics()"]);
  const refreshDiagnostics = functionSource("refreshDiagnostics");
  assert.ok(refreshDiagnostics.includes("setSettingsStatus"));
  assert.ok(!refreshDiagnostics.includes("setStatus("));
  const copyDiagnostics = functionSource("copyDiagnostics");
  assert.ok(copyDiagnostics.includes("setSettingsStatus"));
  assert.ok(copyDiagnostics.includes("fallbackCopy(text, setSettingsStatus)"));
  assert.ok(copyDiagnostics.includes("return navigator.clipboard.writeText"));
  assert.ok(!copyDiagnostics.includes("setStatus("));
  const fallbackCopy = functionSource("fallbackCopy");
  assert.ok(fallbackCopy.includes("feedback"));
  assert.ok(functionSource("copyResult").includes("fallbackCopy(text)"));
  const switchMode = functionSource("switchMode");
  assert.ok(switchMode.includes('byId("diagnostics-disclosure").open = false'));

  const manager = functionSource("renderWorkflowProfileManager");
  assert.ok(manager.includes("if (profile.note)"));
  assert.ok(manager.includes("workflow-profile-note"));
  assert.ok(!manager.includes('profile.note || "无备注"'));
  assert.ok(!manager.includes('profile.note || "暂无备注"'));

  const tabs = functionSource("renderWorkflowTaskTabs");
  const tabKeys = functionSource("handleWorkflowTaskTabKeydown");
  assert.ok(tabs.includes("tabIndex = active ? 0 : -1"));
  ["ArrowLeft", "ArrowRight", "Home", "End", "preventDefault", ".click()", ".focus()", "scrollWorkflowTaskTabIntoView"].forEach(
    (token) => assert.ok(tabKeys.includes(token), token)
  );
  const scroll = functionSource("scrollWorkflowTaskTabIntoView");
  assertIncludesAll(scroll, [
    "prefers-reduced-motion: reduce",
    'behavior: reducedMotion ? "auto" : "smooth"',
    'block: "nearest"',
    'inline: "nearest"',
    "scrollIntoView(true)"
  ]);

  const bind = functionSource("bindEvents");
  assertIncludesAll(bind, [
    'byId("workflow-task-tabs").addEventListener("keydown"',
    'byId("diagnostics-disclosure").addEventListener("toggle"',
    'workflowHelpButton.addEventListener("click"',
    'workflowHelpButton.addEventListener("mouseenter"',
    'workflowHelpButton.addEventListener("focusin"',
    'document.addEventListener("click"',
    'document.addEventListener("keydown"',
    'event.key === "Escape"',
    "workflowHelpButton.focus()"
  ]);

  const showProviderEditor = functionSource("showProviderEditor");
  const hideProviderEditor = functionSource("hideProviderEditor");
  assertIncludesAll(showProviderEditor, [
    "state.providerUrlEditorOpen = true",
    "syncSettingsRefreshController()"
  ]);
  assertIncludesAll(hideProviderEditor, [
    "state.providerUrlEditorOpen = false",
    "syncSettingsRefreshController()"
  ]);

  const mutationBusy = functionSource("setWorkflowMutationBusy");
  assert.ok(mutationBusy.includes("syncSettingsRefreshController()"));

  const healthBadge = functionSource("setHealthBadge");
  const workflowStrip = functionSource("renderWorkflowProfileStrip");
  assert.ok(healthBadge.includes("setNodeClassNameIfChanged"));
  assert.ok(healthBadge.includes("setNodeTextIfChanged"));
  assert.ok(workflowStrip.includes("setNodeTextIfChanged("));
  assert.ok(workflowStrip.includes("feedback,"));
  assert.ok(modelInterface.includes("setNodeClassNameIfChanged"));
  assert.ok(modelInterface.includes("setNodeTextIfChanged"));
}

assertCompactMarkupContract();
assertCompactCssContract();
assertFixedExcelWorkflowContract();
assertImmediateActivationContract();
assertEditorSaveContract();
assertDeleteAndBusyContracts();
assertExcelHostReviewFixContracts();
assertExcelAnalysisPreservationContract();
assertLiveSettingsExperienceContract();

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
    requests: 0,
    requestTimeouts: [],
    jsonTimeouts: [],
    settingsStatus: [],
    renderDetectable: [],
    healthBadges: [],
    providerLines: [],
    taskStatus: 0,
    taskResult: 0,
    taskTrace: 0,
    adapterUnavailable: 0,
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
    modelInterfaceConfigDetectable: true,
    settingsProbeTraceId: "",
    providerBaseUrl: "https://cached.example.test/v1",
    providerUrlEditorOpen: false,
    workflowEditor: { open: false },
    workflowProfileMutationBusy: false,
    analysisResult: { structuredReport: "既有分析" },
    copyText: "既有分析",
    diagnosticsCopyText: "既有诊断"
  };
  const context = {
    state,
    SETTINGS_REFRESH_REQUEST_TIMEOUT_MS: 8000,
    request(path, payload, requestOptions) {
      assert.strictEqual(path, "/health");
      calls.requests += 1;
      calls.requestTimeouts.push(requestOptions && requestOptions.timeoutMs);
      return health.promise;
    },
    readAdapterJson(path, requestOptions) {
      calls.jsonTimeouts.push(requestOptions && requestOptions.timeoutMs);
      return Promise.resolve(options.config || {
        success: true,
        data: { providerBaseUrl: "https://fresh.example.test/v1" }
      });
    },
    loadWorkflowProfiles() {
      return options.profilePromise || Promise.resolve(options.profileResult === undefined ? {} : options.profileResult);
    },
    setSettingsStatus(value) { calls.settingsStatus.push(value); },
    setHealthBadge(mode, text) { calls.healthBadges.push([mode, text]); },
    setProviderLine(value) { calls.providerLines.push(value); },
    applyProviderConfig(value) {
      calls.applyProviderConfig += 1;
      if (options.applyProviderConfig) options.applyProviderConfig(value);
    },
    renderModelInterfaceState(value) { calls.renderDetectable.push(value); },
    describeFetchError(error) { return error && error.message || String(error); },
    isSettingsRefreshEligible() { return false; },
    setStatus() { calls.taskStatus += 1; },
    setResult() { calls.taskResult += 1; },
    setTrace() { calls.taskTrace += 1; },
    setAdapterUnavailableState() { calls.adapterUnavailable += 1; }
  };
  return { health, calls, state, refreshConfig: loadFunction("refreshConfig", context) };
}

async function runSettingsBehaviorTests() {
  const configFailure = createRefreshHarness({
    config: { success: false, data: {}, errors: [{ message: "配置读取失败" }] }
  });
  const configFailurePromise = configFailure.refreshConfig();
  configFailure.health.resolve({ traceId: "probe-1", data: { providerType: "enterprise-dify-chat" } });
  await configFailurePromise;
  assert.deepStrictEqual(configFailure.calls.healthBadges, [["badge-ok", "已连接"]]);
  assert.strictEqual(configFailure.state.settingsProbeTraceId, "probe-1");
  assert.strictEqual(configFailure.state.modelInterfaceDetectable, false);
  assert.deepStrictEqual(configFailure.state.analysisResult, { structuredReport: "既有分析" });
  assert.strictEqual(configFailure.state.copyText, "既有分析");
  assert.strictEqual(configFailure.calls.taskStatus, 0);
  assert.strictEqual(configFailure.calls.taskResult, 0);
  assert.strictEqual(configFailure.calls.taskTrace, 0);
  assert.strictEqual(configFailure.calls.adapterUnavailable, 0);

  const healthFailure = createRefreshHarness();
  const healthFailurePromise = healthFailure.refreshConfig();
  healthFailure.health.reject(new Error("adapter 未启动"));
  await healthFailurePromise;
  assert.deepStrictEqual(healthFailure.calls.healthBadges.at(-1), ["badge-warn", "待启动"]);
  assert.strictEqual(healthFailure.state.modelInterfaceDetectable, false);
  assert.strictEqual(healthFailure.calls.taskResult, 0);

  const profileFailure = createRefreshHarness({ profileResult: null });
  const profileFailurePromise = profileFailure.refreshConfig();
  profileFailure.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await profileFailurePromise;
  assert.deepStrictEqual(profileFailure.calls.healthBadges, [["badge-ok", "已连接"]]);
  assert.strictEqual(profileFailure.state.modelInterfaceDetectable, false);

  const supersededProfile = createRefreshHarness({ profileResult: { superseded: true } });
  const supersededProfilePromise = supersededProfile.refreshConfig({ silent: true });
  supersededProfile.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await supersededProfilePromise;
  assert.strictEqual(supersededProfile.state.modelInterfaceDetectable, true);
  assert.deepStrictEqual(supersededProfile.calls.renderDetectable, []);
  assert.deepStrictEqual(supersededProfile.calls.settingsStatus, []);

  const concurrent = createRefreshHarness();
  const firstRefresh = concurrent.refreshConfig();
  const secondRefresh = concurrent.refreshConfig();
  assert.strictEqual(firstRefresh, secondRefresh);
  assert.strictEqual(concurrent.calls.requests, 1);
  concurrent.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await firstRefresh;
  assert.strictEqual(concurrent.state.modelInterfaceDetectable, true);
  assert.deepStrictEqual(concurrent.calls.requestTimeouts, [8000]);
  assert.deepStrictEqual(concurrent.calls.jsonTimeouts, [8000]);

  const silent = createRefreshHarness();
  const silentPromise = silent.refreshConfig({ silent: true });
  silent.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await silentPromise;
  assert.deepStrictEqual(silent.calls.settingsStatus, []);

  const silentFailure = createRefreshHarness();
  const silentFailurePromise = silentFailure.refreshConfig({ silent: true });
  silentFailure.health.reject(new Error("静默刷新失败"));
  await silentFailurePromise;
  assert.deepStrictEqual(silentFailure.calls.settingsStatus, ["配置刷新失败：静默刷新失败"]);

  const promoted = createRefreshHarness();
  const promotedSilent = promoted.refreshConfig({ silent: true });
  const promotedInteractive = promoted.refreshConfig({ silent: false });
  assert.strictEqual(promotedSilent, promotedInteractive);
  promoted.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await promotedInteractive;
  assert.deepStrictEqual(promoted.calls.settingsStatus, ["正在刷新配置...", "就绪"]);

  const stopped = createRefreshHarness();
  const stoppedPromise = stopped.refreshConfig();
  let running = true;
  stopped.state.workflowEditor = { open: false };
  stopped.state.settingsRefreshController = {
    start() { running = true; },
    stop() { running = false; },
    isRunning() { return running; }
  };
  const stopRefresh = loadFunction("syncSettingsRefreshController", {
    state: stopped.state,
    document: { visibilityState: "visible" },
    byId: () => ({ classList: { contains: () => false } }),
    invalidateConfigRefresh() { stopped.state.configRefreshRequestId += 1; }
  });
  stopRefresh();
  stopped.health.resolve({ traceId: "late", data: { providerType: "enterprise-dify-chat" } });
  await stoppedPromise;
  assert.strictEqual(running, false);
  assert.deepStrictEqual(stopped.calls.healthBadges, []);
  assert.deepStrictEqual(stopped.calls.renderDetectable, []);

  const interleavedProfileResult = deferred();
  const interleaved = createRefreshHarness({ profilePromise: interleavedProfileResult.promise });
  interleaved.state.busy = false;
  interleaved.state.settingsRefreshController = {
    starts: 0,
    stops: 0,
    running: true,
    start() {
      if (!this.running) { this.starts += 1; this.running = true; }
    },
    stop() {
      if (this.running) { this.stops += 1; this.running = false; }
    },
    isRunning() { return this.running; }
  };
  const interleavedControls = {};
  const interleavedById = (id) => {
    if (id === "settings-view") return { classList: { contains() { return true; } } };
    interleavedControls[id] = interleavedControls[id] || { disabled: false };
    return interleavedControls[id];
  };
  const interleavedSync = loadFunction("syncSettingsRefreshController", {
    state: interleaved.state,
    document: { visibilityState: "visible" },
    byId: interleavedById,
    invalidateConfigRefresh() {
      interleaved.state.configRefreshRequestId += 1;
      interleaved.state.configRefreshQueued = false;
      interleaved.state.configRefreshQueuedSilent = true;
    }
  });
  const setInterleavedMutationBusy = loadFunction("setWorkflowMutationBusy", {
    state: interleaved.state,
    byId: interleavedById,
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderWorkflowTaskTabs() {},
    syncSettingsRefreshController: interleavedSync
  });
  const interleavedRefresh = interleaved.refreshConfig({ silent: true });
  interleaved.health.resolve({ data: { providerType: "enterprise-dify-chat" } });
  await Promise.resolve();
  await Promise.resolve();
  setInterleavedMutationBusy(true);
  assert.strictEqual(interleaved.state.settingsRefreshController.stops, 1);
  interleavedProfileResult.resolve({ failed: true });
  await interleavedRefresh;
  assert.strictEqual(interleaved.state.modelInterfaceDetectable, true);
  assert.deepStrictEqual(interleaved.calls.renderDetectable, []);
  assert.deepStrictEqual(interleaved.calls.settingsStatus, []);
  setInterleavedMutationBusy(false);
  assert.strictEqual(interleaved.state.settingsRefreshController.starts, 1);

  const lifecycleState = {
    configRefreshRequestId: 0,
    configRefreshQueued: false,
    workflowEditor: { open: false },
    providerUrlEditorOpen: false,
    workflowProfileMutationBusy: false,
    settingsRefreshController: {
      starts: 0,
      stops: 0,
      running: false,
      start() { this.starts += 1; this.running = true; },
      stop() { this.stops += 1; this.running = false; },
      isRunning() { return this.running; }
    }
  };
  let settingsActive = true;
  const lifecycleDocument = { visibilityState: "visible" };
  const syncLifecycle = loadFunction("syncSettingsRefreshController", {
    state: lifecycleState,
    document: lifecycleDocument,
    byId: () => ({ classList: { contains: () => settingsActive } }),
    invalidateConfigRefresh() {
      lifecycleState.configRefreshRequestId += 1;
      lifecycleState.configRefreshQueued = false;
    }
  });
  syncLifecycle();
  lifecycleDocument.visibilityState = "hidden";
  syncLifecycle();
  lifecycleDocument.visibilityState = "visible";
  syncLifecycle();
  lifecycleState.workflowEditor.open = true;
  syncLifecycle();
  lifecycleState.workflowEditor.open = false;
  syncLifecycle();
  lifecycleState.workflowProfileMutationBusy = true;
  syncLifecycle();
  lifecycleState.workflowProfileMutationBusy = false;
  syncLifecycle();
  settingsActive = false;
  syncLifecycle();
  assert.strictEqual(lifecycleState.settingsRefreshController.starts, 4);
  assert.strictEqual(lifecycleState.settingsRefreshController.stops, 4);
  assert.strictEqual(lifecycleState.configRefreshRequestId, 4);

  const mutationControls = {};
  const mutationState = {
    busy: false,
    workflowProfileMutationBusy: false,
    workflowEditor: { open: false },
    providerUrlEditorOpen: false,
    configRefreshRequestId: 0,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    settingsRefreshController: {
      starts: 0,
      stops: 0,
      running: true,
      start() {
        if (!this.running) { this.starts += 1; this.running = true; }
      },
      stop() {
        if (this.running) { this.stops += 1; this.running = false; }
      },
      isRunning() { return this.running; }
    }
  };
  const mutationById = (id) => {
    if (id === "settings-view") {
      return { classList: { contains() { return true; } } };
    }
    mutationControls[id] = mutationControls[id] || { disabled: false };
    return mutationControls[id];
  };
  const mutationSync = loadFunction("syncSettingsRefreshController", {
    state: mutationState,
    document: { visibilityState: "visible" },
    byId: mutationById,
    invalidateConfigRefresh() {
      mutationState.configRefreshRequestId += 1;
      mutationState.configRefreshQueued = false;
      mutationState.configRefreshQueuedSilent = true;
    }
  });
  const setMutationBusy = loadFunction("setWorkflowMutationBusy", {
    state: mutationState,
    byId: mutationById,
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderWorkflowTaskTabs() {},
    syncSettingsRefreshController: mutationSync
  });
  setMutationBusy(true); // Activation begins while automatic refresh is running.
  assert.strictEqual(mutationState.settingsRefreshController.stops, 1);
  assert.strictEqual(mutationState.configRefreshRequestId, 1);
  setMutationBusy(false);
  assert.strictEqual(mutationState.settingsRefreshController.starts, 1);
  setMutationBusy(true); // Deletion begins after activation completes.
  setMutationBusy(false);
  assert.strictEqual(mutationState.settingsRefreshController.stops, 2);
  assert.strictEqual(mutationState.settingsRefreshController.starts, 2);

  const providerNodes = {
    "provider-edit-view": { hidden: true },
    "provider-summary-card": { classList: { add() {}, remove() {} } },
    "btn-edit-provider-url": { hidden: false },
    "provider-base-url": { value: "用户草稿", focus() {} }
  };
  const providerState = {
    configRefreshRequestId: 0,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    providerBaseUrl: "https://stable.example.test/v1",
    providerUrlEditorOpen: false,
    workflowEditor: { open: false },
    settingsRefreshController: {
      starts: 0,
      stops: 0,
      running: true,
      start() {
        if (!this.running) {
          this.starts += 1;
          this.running = true;
        }
      },
      stop() {
        if (this.running) {
          this.stops += 1;
          this.running = false;
        }
      },
      isRunning() { return this.running; }
    }
  };
  const providerSync = loadFunction("syncSettingsRefreshController", {
    state: providerState,
    document: { visibilityState: "visible" },
    byId() { return { classList: { contains() { return true; } } }; },
    invalidateConfigRefresh() {
      providerState.configRefreshRequestId += 1;
      providerState.configRefreshQueued = false;
      providerState.configRefreshQueuedSilent = true;
    }
  });
  const showProviderEditor = loadFunction("showProviderEditor", {
    state: providerState,
    byId(id) { return providerNodes[id]; },
    syncSettingsRefreshController: providerSync
  });
  const hideProviderEditor = loadFunction("hideProviderEditor", {
    state: providerState,
    byId(id) { return providerNodes[id]; },
    syncSettingsRefreshController: providerSync
  });
  showProviderEditor();
  assert.strictEqual(providerState.providerUrlEditorOpen, true);
  assert.strictEqual(providerNodes["provider-edit-view"].hidden, false);
  assert.strictEqual(providerNodes["provider-base-url"].value, "用户草稿");
  assert.strictEqual(providerState.settingsRefreshController.stops, 1);
  assert.strictEqual(providerState.configRefreshRequestId, 1);
  hideProviderEditor();
  assert.strictEqual(providerState.providerUrlEditorOpen, false);
  assert.strictEqual(providerNodes["provider-edit-view"].hidden, true);
  assert.strictEqual(providerNodes["provider-base-url"].value, providerState.providerBaseUrl);
  assert.strictEqual(providerState.settingsRefreshController.starts, 1);
  hideProviderEditor();
  assert.strictEqual(providerState.settingsRefreshController.starts, 1);
  showProviderEditor();
  assert.strictEqual(providerState.settingsRefreshController.stops, 2);
  hideProviderEditor({ type: "click", currentTarget: { id: "btn-back-provider-summary" } });
  assert.strictEqual(providerState.settingsRefreshController.starts, 2);
  assert.strictEqual(providerState.settingsRefreshController.running, true);

  const saveCalls = { hide: 0, invalidate: 0, refresh: 0, sync: 0 };
  const saveState = { providerBaseUrl: "", providerUrlEditorOpen: true };
  const saveProviderBaseUrl = loadFunction("saveProviderBaseUrl", {
    state: saveState,
    byId() { return { value: " https://saved.example.test/v1 " }; },
    setSettingsStatus() {},
    request(path, payload) {
      assert.strictEqual(path, "/provider/base-url");
      assert.strictEqual(payload.baseUrl, "https://saved.example.test/v1");
      return Promise.resolve({ data: { providerBaseUrl: "https://saved.example.test/v1" } });
    },
    setProviderBaseUrl(value) { saveState.providerBaseUrl = value; },
    hideProviderEditor(suppressRefreshSync) {
      assert.strictEqual(suppressRefreshSync, true);
      saveState.providerUrlEditorOpen = false;
      saveCalls.hide += 1;
    },
    invalidateConfigRefresh() { saveCalls.invalidate += 1; },
    refreshConfig(options) {
      assert.strictEqual(options.silent, false);
      saveCalls.refresh += 1;
      return Promise.resolve();
    },
    syncSettingsRefreshController() { saveCalls.sync += 1; },
    describeFetchError(error) { return error.message; }
  });
  await saveProviderBaseUrl();
  assert.strictEqual(saveState.providerBaseUrl, "https://saved.example.test/v1");
  assert.strictEqual(saveState.providerUrlEditorOpen, false);
  assert.deepStrictEqual(saveCalls, { hide: 1, invalidate: 1, refresh: 1, sync: 1 });

  const draftInput = { value: "用户正在输入的新地址" };
  const draftRefresh = createRefreshHarness({
    applyProviderConfig(value) {
      draftInput.value = value.providerBaseUrl || "";
    }
  });
  const draftPromise = draftRefresh.refreshConfig({ silent: true });
  draftRefresh.state.configRefreshRequestId += 1;
  draftRefresh.health.resolve({ traceId: "stale", data: { providerType: "enterprise-dify-chat" } });
  await draftPromise;
  assert.strictEqual(draftRefresh.calls.renderDetectable.length, 0);
  assert.strictEqual(draftRefresh.calls.providerLines.length, 0);
  assert.strictEqual(draftRefresh.calls.applyProviderConfig, 0);
  assert.strictEqual(draftInput.value, "用户正在输入的新地址");

  let diagnosticsRefreshes = 0;
  const toggleDiagnostics = loadFunction("handleDiagnosticsDisclosureToggle", {
    refreshDiagnostics() { diagnosticsRefreshes += 1; }
  });
  toggleDiagnostics({ currentTarget: { open: false } });
  toggleDiagnostics({ currentTarget: { open: true } });
  assert.strictEqual(diagnosticsRefreshes, 1);

  const diagnosticsSettingsStatus = [];
  let diagnosticsTaskStatusCalls = 0;
  const refreshDiagnostics = loadFunction("refreshDiagnostics", {
    state: { diagnosticsCopyText: "" },
    readAdapterJson() { return Promise.resolve({ success: true, data: {} }); },
    setDiagnosticsResult() {},
    renderProviderDiagnostics() { return "诊断结果"; },
    setSettingsStatus(message) { diagnosticsSettingsStatus.push(message); },
    setStatus() { diagnosticsTaskStatusCalls += 1; }
  });
  await refreshDiagnostics();
  assert.deepStrictEqual(diagnosticsSettingsStatus, ["诊断信息已刷新。"]);
  assert.strictEqual(diagnosticsTaskStatusCalls, 0);

  const copySettingsStatus = [];
  let copyTaskStatusCalls = 0;
  let fallbackFeedback = null;
  const copyDiagnostics = loadFunction("copyDiagnostics", {
    state: { diagnosticsCopyText: "诊断内容" },
    byId() { return { textContent: "" }; },
    navigator: {
      clipboard: {
        writeText() { return Promise.reject(new Error("clipboard unavailable")); }
      }
    },
    setSettingsStatus(message) { copySettingsStatus.push(message); },
    setStatus() { copyTaskStatusCalls += 1; },
    fallbackCopy(text, feedback) {
      assert.strictEqual(text, "诊断内容");
      fallbackFeedback = feedback;
      feedback("诊断信息已通过兼容方式复制。");
    }
  });
  await copyDiagnostics();
  assert.strictEqual(fallbackFeedback instanceof Function, true);
  assert.deepStrictEqual(copySettingsStatus, ["诊断信息已通过兼容方式复制。"]);
  assert.strictEqual(copyTaskStatusCalls, 0);

  const successfulCopySettings = [];
  await loadFunction("copyDiagnostics", {
    state: { diagnosticsCopyText: "诊断内容" },
    byId() { return { textContent: "" }; },
    navigator: { clipboard: { writeText() { return Promise.resolve(); } } },
    setSettingsStatus(message) { successfulCopySettings.push(message); },
    setStatus() { copyTaskStatusCalls += 1; },
    fallbackCopy() { throw new Error("successful clipboard copy must not fall back"); }
  })();
  assert.deepStrictEqual(successfulCopySettings, ["诊断信息已复制。"]);
  assert.strictEqual(copyTaskStatusCalls, 0);

  const emptyCopyStatus = [];
  loadFunction("copyDiagnostics", {
    state: { diagnosticsCopyText: "" },
    byId() { return { textContent: "" }; },
    navigator: {},
    setSettingsStatus(message) { emptyCopyStatus.push(message); },
    setStatus() { copyTaskStatusCalls += 1; },
    fallbackCopy() { throw new Error("empty diagnostics must not copy"); }
  })();
  assert.deepStrictEqual(emptyCopyStatus, ["暂无可复制的诊断信息。"]);
  assert.strictEqual(copyTaskStatusCalls, 0);

  function trackedNode(textValue, classValue) {
    let textWrites = 0;
    let classWrites = 0;
    let text = textValue;
    let className = classValue;
    const node = {};
    Object.defineProperty(node, "textContent", {
      get() { return text; },
      set(value) { textWrites += 1; text = value; }
    });
    Object.defineProperty(node, "className", {
      get() { return className; },
      set(value) { classWrites += 1; className = value; }
    });
    node.counts = () => ({ textWrites, classWrites });
    return node;
  }

  const healthNode = trackedNode("已连接", "badge badge-ok");
  const setNodeTextIfChanged = loadFunction("setNodeTextIfChanged");
  const setNodeClassNameIfChanged = loadFunction("setNodeClassNameIfChanged");
  const setHealthBadge = loadFunction("setHealthBadge", {
    byId() { return healthNode; },
    setNodeTextIfChanged,
    setNodeClassNameIfChanged
  });
  setHealthBadge("badge-ok", "已连接");
  setHealthBadge("badge-ok", "已连接");
  assert.deepStrictEqual(healthNode.counts(), { textWrites: 0, classWrites: 0 });
  setHealthBadge("badge-warn", "待启动");
  assert.deepStrictEqual(healthNode.counts(), { textWrites: 1, classWrites: 1 });

  const settingsStatusNode = trackedNode("就绪", "");
  const setSettingsStatus = loadFunction("setSettingsStatus", {
    byId() { return settingsStatusNode; },
    setNodeTextIfChanged
  });
  setSettingsStatus("就绪");
  setSettingsStatus("就绪");
  assert.strictEqual(settingsStatusNode.counts().textWrites, 0);
  setSettingsStatus("配置刷新失败");
  assert.strictEqual(settingsStatusNode.counts().textWrites, 1);

  const readinessBadge = trackedNode("已就绪", "readiness-badge is-ready");
  const diagnosticsSummary = trackedNode("已就绪", "");
  const providerSummary = trackedNode("https://ready.example.test/v1", "");
  providerSummary.title = "https://ready.example.test/v1";
  providerSummary.setAttribute = function (name, value) { this[name] = value; };
  const readinessState = {
    providerBaseUrl: "https://ready.example.test/v1",
    workflowProfiles: { activeProfileId: "active", profiles: [{ id: "active", keyConfigured: true }] }
  };
  const renderReadiness = loadFunction("renderModelInterfaceState", {
    state: readinessState,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    getWorkflowProfileData() { return readinessState.workflowProfiles; },
    helpers: {
      deriveModelInterfaceState(input) {
        return input.detectable
          ? { code: "ready", label: "已就绪" }
          : { code: "unavailable", label: "无法检测" };
      }
    },
    byId(id) {
      if (id === "provider-readiness-badge") return readinessBadge;
      if (id === "provider-summary-url") return providerSummary;
      return diagnosticsSummary;
    },
    setNodeTextIfChanged,
    setNodeClassNameIfChanged,
    setNodeAttributeIfChanged: loadFunction("setNodeAttributeIfChanged")
  });
  renderReadiness(true);
  renderReadiness(true);
  assert.deepStrictEqual(readinessBadge.counts(), { textWrites: 0, classWrites: 0 });
  assert.strictEqual(diagnosticsSummary.counts().textWrites, 0);
  renderReadiness(false);
  assert.deepStrictEqual(readinessBadge.counts(), { textWrites: 1, classWrites: 1 });
  assert.strictEqual(diagnosticsSummary.counts().textWrites, 1);

  const workflowFeedback = trackedNode("当前：主流程", "");
  setNodeTextIfChanged(workflowFeedback, "当前：主流程");
  setNodeTextIfChanged(workflowFeedback, "当前：主流程");
  assert.strictEqual(workflowFeedback.counts().textWrites, 0);
  setNodeTextIfChanged(workflowFeedback, "正在切换...");
  assert.strictEqual(workflowFeedback.counts().textWrites, 1);

  const normalCopyFeedback = [];
  const normalCopyDocument = {
    body: { appendChild() {}, removeChild() {} },
    createElement() {
      return {
        value: "",
        style: {},
        setAttribute() {},
        select() {}
      };
    },
    execCommand() { return true; }
  };
  loadFunction("fallbackCopy", {
    document: normalCopyDocument,
    setStatus(message) { normalCopyFeedback.push(message); }
  })("普通分析结果");
  assert.deepStrictEqual(normalCopyFeedback, ["结果已复制。"]);

  const helpState = { workflowHelpPinned: false };
  const helpButton = {
    expanded: "false",
    setAttribute(name, value) { if (name === "aria-expanded") this.expanded = value; }
  };
  const helpPopover = { hidden: true };
  const setHelpOpen = loadFunction("setWorkflowHelpOpen", {
    state: helpState,
    byId(id) { return id === "workflow-help-button" ? helpButton : helpPopover; }
  });
  setHelpOpen(true, true);
  assert.strictEqual(helpState.workflowHelpPinned, true);
  assert.strictEqual(helpPopover.hidden, false);
  assert.strictEqual(helpButton.expanded, "true");
  setHelpOpen(false, false);
  assert.strictEqual(helpPopover.hidden, true);

  let prevented = 0;
  let clicked = 0;
  let focused = 0;
  let scrolled = 0;
  const onlyTab = {
    click() { clicked += 1; },
    focus() { focused += 1; }
  };
  const handleTabKey = loadFunction("handleWorkflowTaskTabKeydown", {
    state: { workflowProfileMutationBusy: false },
    byId() { return { querySelectorAll() { return [onlyTab]; } }; },
    scrollWorkflowTaskTabIntoView() { scrolled += 1; }
  });
  handleTabKey({ target: onlyTab, key: "End", preventDefault() { prevented += 1; } });
  assert.deepStrictEqual([prevented, clicked, focused, scrolled], [1, 1, 1, 1]);

  const cachedProfiles = {
    taskType: "excel.analysis",
    activeProfileId: "stable-active",
    profileCount: 2,
    profiles: [
      { id: "stable-active", name: "稳定主档案", keyConfigured: true },
      { id: "stable-backup", name: "稳定备用档案", keyConfigured: true }
    ]
  };
  const firstProfileRequest = deferred();
  const secondProfileRequest = deferred();
  const supersededLoadState = {
    configRefreshRequestId: 0,
    modelInterfaceDetectable: true,
    modelInterfaceConfigDetectable: true,
    workflowProfiles: cachedProfiles,
    workflowProfileSelection: "stable-active",
    workflowProfileLoadSequence: 0
  };
  let profileRequestCount = 0;
  let supersededRenderCount = 0;
  const supersededLoad = loadFunction("loadWorkflowProfiles", {
    state: supersededLoadState,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    request() {
      profileRequestCount += 1;
      return profileRequestCount === 1 ? firstProfileRequest.promise : secondProfileRequest.promise;
    },
    describeFetchError(error) { return error.message; },
    emptyWorkflowProfileData() { return { taskType: "excel.analysis", activeProfileId: "", profileCount: 0, profiles: [] }; },
    normalizeWorkflowProfileData(value) { return value; },
    renderWorkflowProfileStrip() { supersededRenderCount += 1; },
    renderWorkflowProfileManager() { supersededRenderCount += 1; },
    renderModelInterfaceState() { supersededRenderCount += 1; }
  });
  const oldLoadPromise = supersededLoad();
  const currentLoadPromise = supersededLoad();
  firstProfileRequest.reject(new Error("旧请求被新请求取代"));
  const oldLoadResult = await oldLoadPromise;
  assert.strictEqual(oldLoadResult.superseded, true);
  assert.strictEqual(supersededLoadState.modelInterfaceDetectable, true);
  assert.strictEqual(supersededRenderCount, 0);
  secondProfileRequest.resolve({ data: cachedProfiles });
  await currentLoadPromise;
  assert.strictEqual(supersededRenderCount, 3);

  const loadState = {
    configRefreshRequestId: 0,
    modelInterfaceDetectable: false,
    modelInterfaceConfigDetectable: true,
    workflowProfiles: cachedProfiles,
    workflowProfileSelection: "stable-backup",
    workflowProfileLoadSequence: 0
  };
  const failedLoad = loadFunction("loadWorkflowProfiles", {
    state: loadState,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    request() { return Promise.reject(new Error("临时读取失败")); },
    describeFetchError(error) { return error.message; },
    emptyWorkflowProfileData() { return { taskType: "excel.analysis", activeProfileId: "", profileCount: 0, profiles: [] }; },
    normalizeWorkflowProfileData(value) { return value; },
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderModelInterfaceState() {}
  });
  const failedLoadResult = await failedLoad();
  assert.strictEqual(failedLoadResult.failed, true);
  assert.strictEqual(loadState.workflowProfiles.activeProfileId, "stable-active");
  assert.deepStrictEqual(loadState.workflowProfiles.profiles, cachedProfiles.profiles);
  assert.strictEqual(loadState.workflowProfileSelection, "stable-backup");
  assert.strictEqual(loadState.workflowProfiles.loadError, "临时读取失败");

  const restoredState = {
    configRefreshRequestId: 0,
    modelInterfaceDetectable: false,
    modelInterfaceConfigDetectable: true,
    workflowProfiles: cachedProfiles,
    workflowProfileSelection: "stable-backup",
    workflowProfileLoadSequence: 0
  };
  const restoredLoad = loadFunction("loadWorkflowProfiles", {
    state: restoredState,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    request() { return Promise.resolve({ data: cachedProfiles }); },
    describeFetchError(error) { return error.message; },
    emptyWorkflowProfileData() { return { taskType: "excel.analysis", activeProfileId: "", profileCount: 0, profiles: [] }; },
    normalizeWorkflowProfileData(value) { return value; },
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderModelInterfaceState() {}
  });
  await restoredLoad();
  assert.strictEqual(restoredState.modelInterfaceDetectable, true);

  const reducedCalls = [];
  loadFunction("scrollWorkflowTaskTabIntoView", {
    window: { matchMedia: () => ({ matches: true }) }
  })({ scrollIntoView(value) { reducedCalls.push(value); } });
  assert.strictEqual(reducedCalls[0].behavior, "auto");

  const fallbackCalls = [];
  loadFunction("scrollWorkflowTaskTabIntoView", {
    window: { matchMedia: () => ({ matches: false }) }
  })({
    scrollIntoView(value) {
      fallbackCalls.push(value);
      if (typeof value === "object") throw new Error("旧 WebView");
    }
  });
  assert.strictEqual(fallbackCalls[1], true);
}

runSettingsBehaviorTests().then(() => {
  console.log("Excel workflow settings source contracts passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
