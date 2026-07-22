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
  assert.ok(!js.includes("function renderWorkflowTaskTabs()"));
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
    'byId("status-line").textContent',
    'byId("settings-status-line").textContent'
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

assertCompactMarkupContract();
assertCompactCssContract();
assertFixedExcelWorkflowContract();
assertImmediateActivationContract();
assertEditorSaveContract();
assertDeleteAndBusyContracts();
assertExcelHostReviewFixContracts();
assertExcelAnalysisPreservationContract();

console.log("Excel workflow settings source contracts passed");
