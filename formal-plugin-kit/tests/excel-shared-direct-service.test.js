const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const css = fs.readFileSync(path.join(root, "taskpane.css"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

test("Excel settings markup exposes shared direct services card and editor", () => {
  // Shared direct service card on settings home
  assert.ok(html.includes('id="direct-services-card"'), "missing #direct-services-card");
  assert.ok(html.includes('id="direct-services-list"'), "missing #direct-services-list");
  assert.ok(html.includes('id="btn-new-direct-service"'), "missing #btn-new-direct-service");

  // Direct service editor
  assert.ok(html.includes('id="direct-service-editor-view"'), "missing #direct-service-editor-view");
  assert.ok(html.includes('id="direct-service-name"'), "missing #direct-service-name");
  assert.ok(html.includes('id="direct-service-url"'), "missing #direct-service-url");
  assert.ok(html.includes('id="direct-service-default-model"'), "missing #direct-service-default-model");
  assert.ok(html.includes('id="btn-refresh-direct-service-models"'), "missing #btn-refresh-direct-service-models");
  assert.ok(html.includes('id="direct-service-models-status"'), "missing #direct-service-models-status");
  assert.ok(html.includes('id="direct-service-editor-error"'), "missing #direct-service-editor-error");
  assert.ok(html.includes('id="btn-save-direct-service"'), "missing #btn-save-direct-service");
  assert.ok(html.includes('id="btn-cancel-direct-service"'), "missing #btn-cancel-direct-service");

  // Delete dialog
  assert.ok(html.includes('id="direct-service-delete-dialog"'), "missing #direct-service-delete-dialog");
  assert.ok(html.includes('id="direct-service-delete-name"'), "missing #direct-service-delete-name");
  assert.ok(html.includes('id="direct-service-delete-warning"'), "missing #direct-service-delete-warning");
  assert.ok(html.includes('id="btn-confirm-direct-service-delete"'), "missing #btn-confirm-direct-service-delete");
  assert.ok(html.includes('id="btn-cancel-direct-service-delete"'), "missing #btn-cancel-direct-service-delete");

  // Excel Analysis task model selection section
  assert.ok(html.includes('id="excel-task-direct-service-section"'), "missing #excel-task-direct-service-section");
  assert.ok(html.includes('id="excel-task-direct-service-select"'), "missing #excel-task-direct-service-select");
  assert.ok(html.includes('id="excel-task-model-select"'), "missing #excel-task-model-select");
  assert.ok(html.includes('id="excel-task-custom-model-check"'), "missing #excel-task-custom-model-check");
  assert.ok(html.includes('id="excel-task-custom-model-input"'), "missing #excel-task-custom-model-input");
  assert.ok(html.includes('id="btn-validate-task-model-selection"'), "missing #btn-validate-task-model-selection");
  assert.ok(html.includes('id="btn-save-task-model-selection"'), "missing #btn-save-task-model-selection");
});

test("Single API Key input contract: strictly one key field, no confirm field, password type", () => {
  assert.ok(html.includes('id="direct-service-key"'), "missing #direct-service-key");
  assert.ok(
    html.includes('id="direct-service-key" type="password"') ||
    html.includes('type="password" id="direct-service-key"'),
    "#direct-service-key must be type password"
  );
  // Strictly single input - no confirm field
  assert.strictEqual(
    html.includes("direct-service-key-confirm"),
    false,
    "direct-service-key-confirm must NOT exist in HTML"
  );
});

test("Task Model Selection helpers: validateDirectServiceDraft and validateTaskModelSelectionDraft", () => {
  assert.strictEqual(typeof helpers.validateDirectServiceDraft, "function");
  assert.strictEqual(typeof helpers.validateTaskModelSelectionDraft, "function");

  // Direct service draft validation
  const invalidName = helpers.validateDirectServiceDraft({
    name: "",
    serviceBaseUrl: "https://api.openai.com/v1"
  });
  assert.strictEqual(invalidName.valid, false);
  assert.ok(invalidName.error.includes("名称"));

  const invalidUrl = helpers.validateDirectServiceDraft({
    name: "有效名称",
    serviceBaseUrl: "ftp://invalid-url"
  });
  assert.strictEqual(invalidUrl.valid, false);
  assert.ok(invalidUrl.error.includes("地址"));

  const validDraft = helpers.validateDirectServiceDraft({
    name: "企业直连网关",
    serviceBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o",
    apiKey: "sk-valid-key"
  });
  assert.strictEqual(validDraft.valid, true);

  // Task model selection draft validation
  const missingService = helpers.validateTaskModelSelectionDraft({
    serviceId: "",
    modelName: "gpt-4o"
  });
  assert.strictEqual(missingService.valid, false);

  const validSelection = helpers.validateTaskModelSelectionDraft({
    serviceId: "direct_svc_1",
    modelName: "gpt-4o",
    temperature: 0.7,
    maxOutputTokens: 2048,
    contextWindowTokens: 40000
  });
  assert.strictEqual(validSelection.valid, true);
});

test("Compact menu integration: includes shared direct service in Excel Analysis menu items", () => {
  const profiles = [
    {
      id: "wf_1",
      name: "默认工作流",
      accessMethod: "workflow_platform",
      complete: true
    }
  ];
  const directServices = [
    {
      id: "direct_svc_abc",
      name: "共享直连服务",
      serviceBaseUrl: "https://api.openai.com/v1",
      defaultModel: "gpt-4o",
      keyConfigured: true
    }
  ];
  const items = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_abc",
    taskType: "excel.analysis",
    directServices: directServices,
    taskModelSelection: {
      serviceId: "direct_svc_abc",
      effectiveModel: "gpt-4o"
    }
  });

  const directItem = items.find((it) => it.id === "direct_svc_abc");
  assert.ok(directItem, "direct service item must be in menu items");
  assert.strictEqual(directItem.selected, true);
  assert.ok(directItem.label.includes("共享直连服务"));
  assert.ok(directItem.label.includes("gpt-4o"));

  const switchEval = helpers.evaluateTaskModelConfigSwitch({
    previousId: "wf_1",
    requestedId: "direct_svc_abc",
    busy: false,
    mutationBusy: false
  });
  assert.strictEqual(switchEval.allowed, true);
  assert.strictEqual(switchEval.nextSelectionId, "direct_svc_abc");

  const busyEval = helpers.evaluateTaskModelConfigSwitch({
    previousId: "wf_1",
    requestedId: "direct_svc_abc",
    busy: true,
    mutationBusy: false
  });
  assert.strictEqual(busyEval.allowed, false);
  assert.strictEqual(busyEval.reason, "busy");
});

test("Workflow platform configuration and tabs remain intact", () => {
  assert.ok(html.includes('id="workflow-profile-manager"'));
  assert.ok(html.includes('id="btn-new-workflow-profile"'));
  assert.ok(html.includes('data-workflow-task-tab="excel.analysis"'));
  assert.ok(html.includes('data-workflow-task-tab="excel.formula_assistant"'));
  assert.ok(html.includes('data-workflow-task-tab="excel.smart_fill"'));
});

test("Taskpane JS exports and defines all required direct service handlers", () => {
  assert.ok(js.includes("function loadDirectServices("), "missing loadDirectServices");
  assert.ok(js.includes("function renderDirectServicesList("), "missing renderDirectServicesList");
  assert.ok(js.includes("function openDirectServiceEditor("), "missing openDirectServiceEditor");
  assert.ok(js.includes("function closeDirectServiceEditor("), "missing closeDirectServiceEditor");
  assert.ok(js.includes("function saveDirectServiceEditor("), "missing saveDirectServiceEditor");
  assert.ok(js.includes("function refreshDirectServiceModelsInEditor("), "missing refreshDirectServiceModelsInEditor");
  assert.ok(js.includes("function openDirectServiceDeleteDialog("), "missing openDirectServiceDeleteDialog");
  assert.ok(js.includes("function confirmDirectServiceDelete("), "missing confirmDirectServiceDelete");
  assert.ok(js.includes("function renderTaskModelSelectionSection("), "missing renderTaskModelSelectionSection");
  assert.ok(js.includes("function validateTaskModelSelection("), "missing validateTaskModelSelection");
  assert.ok(js.includes("function saveTaskModelSelection("), "missing saveTaskModelSelection");
});

test("Direct services behavior: max 5 limit, single key contract, and activation rollback", async () => {
  const vm = require("node:vm");

  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  function loadFn(name, ctx) {
    return vm.runInNewContext(`(${functionSource(name)})`, ctx);
  }

  // Create mock DOM & state
  const mockNodes = {
    "direct-services-list": { innerHTML: "", hidden: false },
    "btn-new-direct-service": { disabled: false, hidden: false },
    "direct-service-editor-view": { hidden: true },
    "direct-service-editor-title": { textContent: "" },
    "direct-service-name": { value: "", focus() {} },
    "direct-service-url": { value: "" },
    "direct-service-key": { value: "", placeholder: "" },
    "direct-service-key-label": { textContent: "" },
    "direct-service-key-status": { textContent: "" },
    "direct-service-default-model": { value: "" },
    "direct-service-models-status": { textContent: "" },
    "btn-refresh-direct-service-models": { disabled: false },
    "direct-service-editor-error": { textContent: "" },
    "direct-service-delete-dialog": { hidden: true },
    "direct-service-delete-name": { textContent: "" },
    "direct-service-delete-warning": { textContent: "" },
    "excel-task-direct-service-section": { hidden: false },
    "excel-task-direct-service-select": { innerHTML: "", value: "" },
    "excel-task-direct-params": { hidden: true },
    "excel-task-model-select": { innerHTML: "", value: "" },
    "excel-task-custom-model-check": { checked: false },
    "excel-task-custom-model-row": { hidden: true },
    "excel-task-custom-model-input": { value: "" },
    "excel-task-temperature": { value: "" },
    "excel-task-max-output": { value: "" },
    "excel-task-context": { value: "" },
    "excel-task-model-validation-status": { textContent: "" },
    "task-model-config-trigger": {
      focus() {},
      setAttribute() {},
      removeAttribute() {}
    },
    "workflow-switch-feedback": { textContent: "" }
  };

  const requestsMade = [];
  let statusText = "";

  const state = {
    directServices: [],
    directServiceEditor: { open: false, mode: "create", serviceId: "", revision: 1, dirty: false },
    directServiceDeleteCandidate: null,
    taskModelSelections: {},
    workflowTaskType: "excel.analysis",
    workflowProfilesByTask: {
      "excel.analysis": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    workflowProfileSelections: { "excel.analysis": "direct_svc_1" },
    workflowProfileLoadSequences: {},
    taskModelConfigStatusByTask: {},
    taskApiKeys: {
      "excel.analysis": { activeProfileId: "direct_svc_1" }
    },
    workflowProfileMutationBusy: false,
    busy: false
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    escaped(s) { return s || ""; },
    setStatus(s) { statusText = s; },
    setWorkflowMutationBusy(b) { state.workflowProfileMutationBusy = b; },
    describeFetchError(err) { return err && err.message || String(err); },
    setNodeTextIfChanged(node, val) { if (node) node.textContent = val; },
    focusTaskModelConfigTrigger() {},
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderModelInterfaceState() {},
    loadWorkflowProfiles() { return Promise.resolve({}); },
    loadWorkflowProfileForTask() { return Promise.resolve({}); },
    request(url, payload, options) {
      requestsMade.push({ url, payload, method: options && options.method || "POST" });
      if (url.includes("/activate")) {
        return Promise.resolve({ data: { active: true } });
      }
      return Promise.resolve({ data: {} });
    }
  };

  ctx.findDirectService = loadFn("findDirectService", ctx);
  ctx.renderDirectServicesList = loadFn("renderDirectServicesList", ctx);
  ctx.openDirectServiceEditor = loadFn("openDirectServiceEditor", ctx);
  ctx.closeDirectServiceEditor = loadFn("closeDirectServiceEditor", ctx);
  ctx.renderTaskModelSelectionSection = loadFn("renderTaskModelSelectionSection", ctx);
  ctx.getWorkflowProfileData = loadFn("getWorkflowProfileData", ctx);
  ctx.findWorkflowProfile = loadFn("findWorkflowProfile", ctx);
  ctx.activateWorkflowProfile = loadFn("activateWorkflowProfile", ctx);

  // 1. Max 5 direct services enforcement
  state.directServices = [
    { id: "direct_svc_1", name: "S1", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_2", name: "S2", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_3", name: "S3", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_4", name: "S4", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_5", name: "S5", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" }
  ];
  ctx.renderDirectServicesList();
  assert.strictEqual(mockNodes["btn-new-direct-service"].disabled, true, "new button must be disabled when 5 services exist");

  // Attempt to open editor for create when limit reached
  ctx.openDirectServiceEditor("create", "");
  assert.strictEqual(statusText, "最多只能保存 5 份共享直连服务。");
  assert.strictEqual(state.directServiceEditor.open, false);

  // 2. Open editor when < 5 services
  state.directServices.pop(); // now 4
  ctx.openDirectServiceEditor("create", "");
  assert.strictEqual(state.directServiceEditor.open, true);
  assert.strictEqual(mockNodes["direct-service-editor-title"].textContent, "新建直连服务");
  assert.strictEqual(mockNodes["direct-service-key-label"].textContent, "API Key（仅需录入一次）");
  assert.strictEqual(mockNodes["direct-service-key"].value, "", "key input must be empty, no echo");

  // 3. Compact menu immediate activation of direct service
  requestsMade.length = 0;
  await ctx.activateWorkflowProfile("direct_svc_2", "direct_svc_1", "excel.analysis");
  const activateReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_2/activate"));
  assert.ok(activateReq, "must call direct service activate endpoint");
  assert.strictEqual(activateReq.payload.taskType, "excel.analysis");
  assert.strictEqual(state.workflowProfileSelections["excel.analysis"], "direct_svc_2");

  // 4. Activation failure rollback
  ctx.request = () => Promise.reject(new Error("网络断开"));
  await ctx.activateWorkflowProfile("direct_svc_3", "direct_svc_2", "excel.analysis");
  assert.strictEqual(state.workflowProfileSelections["excel.analysis"], "direct_svc_2", "must rollback to previous on failure");
  assert.strictEqual(state.taskModelConfigStatusByTask["excel.analysis"], "error");
});
