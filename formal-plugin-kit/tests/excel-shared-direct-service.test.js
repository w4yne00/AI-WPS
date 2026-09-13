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

test("Code review fixes: loadDirectServices array-to-map, draft customModel, and revision sync", async () => {
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

  // 1. Validator key field & mode checks
  const createEmptyKey = helpers.validateDirectServiceDraft({
    name: "测试服务",
    serviceBaseUrl: "https://api.openai.com/v1",
    apiKey: ""
  }, "create");
  assert.strictEqual(createEmptyKey.valid, false);
  assert.ok(createEmptyKey.error.includes("必须配置 API Key"));

  const editEmptyKeyConfigured = helpers.validateDirectServiceDraft({
    name: "测试服务",
    serviceBaseUrl: "https://api.openai.com/v1",
    apiKey: "",
    keyConfigured: true
  }, "edit");
  assert.strictEqual(editEmptyKeyConfigured.valid, true);

  // 2. Draft returns customModel
  const mockNodes = {
    "excel-task-direct-service-select": { value: "direct_svc_1" },
    "excel-task-custom-model-check": { checked: true },
    "excel-task-custom-model-input": { value: "deepseek-custom-v3" },
    "excel-task-model-select": { value: "" },
    "excel-task-temperature": { value: "0.8" },
    "excel-task-max-output": { value: "2048" },
    "excel-task-context": { value: "64000" }
  };

  const draftCtx = {
    byId(id) { return mockNodes[id] || null; }
  };
  const getDraft = loadFn("getTaskModelSelectionDraft", draftCtx);
  const draft = getDraft();
  assert.strictEqual(draft.customModel, true, "draft must contain customModel: true");
  assert.strictEqual(draft.modelName, "deepseek-custom-v3");
  assert.strictEqual(draft.serviceId, "direct_svc_1");

  // 3. loadDirectServices converts taskModelSelections array to map
  const state = {
    directServices: [],
    taskModelSelections: {},
    taskApiKeys: {
      "excel.analysis": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    },
    workflowProfileSelections: {},
    configRefreshRequestId: 1
  };

  const loadCtx = {
    state,
    TASK_API_KEY_DEFS: [{ taskType: "excel.analysis" }],
    renderDirectServicesList() {},
    renderTaskModelSelectionSection() {},
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    request(url) {
      if (url.includes("/provider/direct-services")) {
        return Promise.resolve({
          data: {
            directServices: [
              { id: "direct_svc_1", name: "S1", revision: 1 }
            ]
          }
        });
      }
      if (url.includes("/provider/task-model-selections")) {
        return Promise.resolve({
          data: {
            taskModelSelections: [
              {
                taskType: "excel.analysis",
                serviceId: "direct_svc_1",
                modelName: "gpt-4o",
                temperature: 0.5
              }
            ]
          }
        });
      }
      return Promise.resolve({ data: {} });
    }
  };

  const loadDirectServices = loadFn("loadDirectServices", loadCtx);
  await loadDirectServices();
  assert.ok(state.taskModelSelections["excel.analysis"], "taskModelSelections must be converted to object keyed by taskType");
  assert.strictEqual(state.taskModelSelections["excel.analysis"].serviceId, "direct_svc_1");
  assert.strictEqual(state.workflowProfileSelections["excel.analysis"], "direct_svc_1", "active direct service selection must be restored");

  // 4. refreshDirectServiceModelsInEditor updates revision
  state.directServiceEditor = {
    serviceId: "direct_svc_1",
    revision: 1,
    open: true
  };
  const statusNode = { textContent: "" };
  const refreshCtx = {
    state,
    byId(id) {
      if (id === "direct-service-models-status") return statusNode;
      return null;
    },
    findDirectService() {
      return { id: "direct_svc_1", revision: 2, modelList: ["m1", "m2"] };
    },
    loadDirectServices() { return Promise.resolve(); },
    describeFetchError(e) { return String(e); },
    request(url) {
      return Promise.resolve({
        data: {
          directService: {
            id: "direct_svc_1",
            revision: 2,
            modelList: ["m1", "m2"]
          }
        }
      });
    }
  };
  const refreshFn = loadFn("refreshDirectServiceModelsInEditor", refreshCtx);
  await refreshFn();
  assert.strictEqual(state.directServiceEditor.revision, 2, "editor revision must be updated to 2 after refresh");
  assert.ok(statusNode.textContent.includes("2 个模型"), "status must reflect model count");
});

test("Excel settings tabs dynamically show task direct service section for all 3 tasks with proper titles", async () => {
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

  const mockNodes = {
    "excel-task-direct-service-section": { hidden: true },
    "excel-task-direct-service-title": { textContent: "" },
    "excel-task-direct-service-select": { innerHTML: "", value: "" },
    "excel-task-direct-params": { hidden: true },
    "excel-task-model-select": { innerHTML: "", value: "" },
    "excel-task-custom-model-check": { checked: false, disabled: false, title: "" },
    "excel-task-custom-model-row": { hidden: true },
    "excel-task-custom-model-input": { value: "" },
    "excel-task-temperature": { value: "" },
    "excel-task-max-output": { value: "" },
    "excel-task-context": { value: "" },
    "excel-task-model-cost-warning": { hidden: true, textContent: "" },
    "excel-task-model-validation-status": { textContent: "" }
  };

  const state = {
    workflowTaskType: "excel.formula_assistant",
    directServices: [
      { id: "direct_svc_1", name: "共享直连服务", defaultModel: "gpt-4o", modelList: ["gpt-4o", "formula-pro"], keyConfigured: true, serviceBaseUrl: "https://api.openai.com/v1" }
    ],
    taskModelSelections: {
      "excel.formula_assistant": {
        serviceId: "direct_svc_1",
        modelName: "formula-pro",
        temperature: 0.2,
        maxOutputTokens: 1024,
        contextWindowTokens: 32000
      },
      "excel.smart_fill": {
        serviceId: "direct_svc_1",
        modelName: "fill-pro",
        customModel: true,
        temperature: 0.1,
        maxOutputTokens: 2048,
        contextWindowTokens: 40000
      }
    },
    workflowProfilesByTask: {
      "excel.formula_assistant": { activeProfileId: "direct_svc_1", profiles: [] },
      "excel.smart_fill": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    taskApiKeys: {
      "excel.formula_assistant": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" },
      "excel.smart_fill": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    }
  };

  const ctx = {
    state,
    helpers,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
    EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    byId(id) { return mockNodes[id] || null; },
    escaped(s) { return s || ""; },
    findDirectService(id) { return state.directServices.find(s => s.id === id) || null; },
    getWorkflowProfileData(taskType) {
      const base = state.workflowProfilesByTask[taskType] || { activeProfileId: "", profiles: [] };
      return {
        activeProfileId: base.activeProfileId,
        profiles: base.profiles,
        directServices: state.directServices,
        taskModelSelection: state.taskModelSelections[taskType] || null
      };
    }
  };

  ctx.getSettingsWorkflowTaskType = js.includes("function getSettingsWorkflowTaskType(")
    ? loadFn("getSettingsWorkflowTaskType", ctx)
    : () => state.workflowTaskType;

  ctx.renderTaskModelSelectionSection = loadFn("renderTaskModelSelectionSection", ctx);

  // 1. Render for formula assistant
  state.workflowTaskType = "excel.formula_assistant";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["excel-task-direct-service-section"].hidden, false, "section must NOT be hidden for formula_assistant");
  assert.strictEqual(mockNodes["excel-task-direct-service-title"].textContent, "公式助手接入选择");
  assert.strictEqual(mockNodes["excel-task-temperature"].value, 0.2);
  assert.strictEqual(mockNodes["excel-task-max-output"].value, 1024);

  // 2. Render for smart fill
  state.workflowTaskType = "excel.smart_fill";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["excel-task-direct-service-section"].hidden, false, "section must NOT be hidden for smart_fill");
  assert.strictEqual(mockNodes["excel-task-direct-service-title"].textContent, "智能填写接入选择");
  assert.strictEqual(mockNodes["excel-task-temperature"].value, 0.1);
  assert.strictEqual(mockNodes["excel-task-max-output"].value, 2048);
  assert.strictEqual(mockNodes["excel-task-custom-model-check"].checked, true);
  assert.strictEqual(mockNodes["excel-task-custom-model-input"].value, "fill-pro");
});

test("saveTaskModelSelection and validateTaskModelSelection support formula assistant and smart fill", async () => {
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

  const requestsMade = [];
  const mockNodes = {
    "excel-task-direct-service-select": { value: "direct_svc_1" },
    "excel-task-model-select": { value: "formula-v1" },
    "excel-task-custom-model-check": { checked: false },
    "excel-task-custom-model-input": { value: "" },
    "excel-task-temperature": { value: "0.5" },
    "excel-task-max-output": { value: "1000" },
    "excel-task-context": { value: "32000" },
    "excel-task-model-validation-status": { textContent: "" },
    "excel-task-model-cost-warning": { hidden: false, textContent: "" }
  };

  const state = {
    workflowTaskType: "excel.formula_assistant",
    directServices: [{ id: "direct_svc_1", name: "S1", serviceBaseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o", keyConfigured: true, modelList: ["gpt-4o", "formula-v1", "fill-v1"] }],
    taskModelSelections: {},
    workflowProfileSelections: {},
    taskApiKeys: { "excel.formula_assistant": {} },
    workflowProfilesByTask: { "excel.formula_assistant": { activeProfileId: "direct_svc_1" } }
  };

  const ctx = {
    state,
    helpers,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
    EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    byId(id) { return mockNodes[id] || null; },
    findDirectService(id) { return state.directServices.find(s => s.id === id) || null; },
    setWorkflowMutationBusy() {},
    setWorkflowProfileMutationBusy() {},
    setStatus() {},
    describeFetchError(e) { return String(e); },
    loadWorkflowProfileForTask() { return Promise.resolve(); },
    loadDirectServices() { return Promise.resolve(); },
    getWorkflowProfileData(taskType) {
      return state.workflowProfilesByTask[taskType] || { activeProfileId: "" };
    },
    getSettingsWorkflowTaskType: js.includes("function getSettingsWorkflowTaskType(")
      ? loadFn("getSettingsWorkflowTaskType", { state, EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis", EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant", EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill" })
      : () => state.workflowTaskType,
    request(url, payload, options) {
      requestsMade.push({ url, payload, method: (options && options.method) || "POST" });
      if (url.includes("/activate")) {
        return Promise.resolve({
          data: {
            taskType: payload.taskType,
            taskModelSelection: payload.taskModelSelection || {
              serviceId: "direct_svc_1",
              modelName: "formula-v1"
            }
          }
        });
      }
      if (url.includes("/validate")) {
        return Promise.resolve({ data: { validation: { success: true } } });
      }
      return Promise.resolve({ data: {} });
    }
  };

  ctx.getTaskModelSelectionDraft = loadFn("getTaskModelSelectionDraft", ctx);
  ctx.validateTaskModelSelection = loadFn("validateTaskModelSelection", ctx);
  ctx.saveTaskModelSelection = loadFn("saveTaskModelSelection", ctx);

  // 1. Validate for formula assistant
  await ctx.validateTaskModelSelection();
  const valReq = requestsMade.find(r => r.url.includes("/provider/task-model-selections/excel.formula_assistant/validate"));
  assert.ok(valReq, "must validate against excel.formula_assistant endpoint");

  // 2. Save for formula assistant
  requestsMade.length = 0;
  await ctx.saveTaskModelSelection();
  const actReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_1/activate"));
  assert.ok(actReq, "must call activate");
  assert.strictEqual(actReq.payload.taskType, "excel.formula_assistant");
  assert.strictEqual(state.workflowProfileSelections["excel.formula_assistant"], "direct_svc_1");

  // 3. Save for smart fill
  state.workflowTaskType = "excel.smart_fill";
  state.workflowProfilesByTask["excel.smart_fill"] = { activeProfileId: "direct_svc_1" };
  state.taskApiKeys["excel.smart_fill"] = {};
  mockNodes["excel-task-model-select"].value = "fill-v1";
  requestsMade.length = 0;
  await ctx.saveTaskModelSelection();
  const actReqFill = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_1/activate"));
  assert.ok(actReqFill, "must call activate for smart_fill");
  assert.strictEqual(actReqFill.payload.taskType, "excel.smart_fill");
  assert.strictEqual(state.workflowProfileSelections["excel.smart_fill"], "direct_svc_1");
});

test("Delete protection and URL change impact disclose formula assistant and smart fill", () => {
  const service = {
    id: "direct_svc_shared",
    name: "企业通用直连",
    serviceBaseUrl: "https://old.api.example.com/v1",
    referencedTasks: ["excel.analysis", "excel.formula_assistant", "excel.smart_fill"]
  };

  const deleteEval = helpers.evaluateDirectServiceDelete(service);
  assert.strictEqual(deleteEval.canDelete, false);
  assert.ok(deleteEval.message.includes("表格公式助手"));
  assert.ok(deleteEval.message.includes("表格智能填写"));

  const impactMsg = helpers.evaluateDirectServiceUrlImpact(service, "https://new.api.example.com/v1");
  assert.ok(impactMsg.includes("表格公式助手"));
  assert.ok(impactMsg.includes("表格智能填写"));
});

test("Readiness gate blocks formula assistant and smart fill when direct service model is unavailable", () => {
  assert.strictEqual(typeof helpers.validateDirectTaskSelectionReadiness, "function");

  const service = {
    id: "direct_svc_1",
    name: "企业直连",
    serviceBaseUrl: "https://api.example.com",
    keyConfigured: true,
    defaultModel: "gpt-4o",
    modelList: ["gpt-4o"],
    modelCatalog: {
      status: "unavailable",
      usableForSelection: false,
      models: []
    }
  };

  // Model catalog unavailable without custom model
  const formulaReadiness = helpers.validateDirectTaskSelectionReadiness(
    { serviceId: "direct_svc_1", modelName: "gpt-4o", customModel: false },
    { service }
  );
  assert.strictEqual(formulaReadiness.ok, false);
  assert.ok(formulaReadiness.error.includes("不可用"));

  // Model catalog expired
  const expiredService = {
    ...service,
    modelCatalog: {
      status: "expired",
      usableForSelection: true,
      models: ["gpt-4o"]
    }
  };
  const fillReadiness = helpers.validateDirectTaskSelectionReadiness(
    { serviceId: "direct_svc_1", modelName: "gpt-4o", customModel: false },
    { service: expiredService }
  );
  assert.strictEqual(fillReadiness.ok, false);
  assert.ok(fillReadiness.error.includes("过期"));
});

// Exercise production save + both reload functions; only the HTTP and DOM boundaries are fake.
function selectionSaveHarness(taskType, options = {}) {
  const vm = require("node:vm");
  const oldSelection = { taskType, serviceId: "direct_svc_old", modelName: "old-model", temperature: 0.2, maxOutputTokens: 1000, contextWindowTokens: 16000 };
  const draft = { serviceId: "direct_svc_new", modelName: "new-model", customModel: false, temperature: 0.7, maxOutputTokens: 2000, contextWindowTokens: 32000, ...options.draft };
  const services = ["old", "new"].map(name => ({ id: `direct_svc_${name}`, name, keyConfigured: true, serviceBaseUrl: "https://example.com/v1", defaultModel: `${name}-model`, modelList: draft.customModel ? [] : [`${name}-model`] }));
  const persisted = { active: oldSelection.serviceId, selection: { ...oldSelection } };
  const state = {
    workflowTaskType: taskType, lastValidatedCustomModel: null,
    taskApiKeys: { [taskType]: { activeProfileId: oldSelection.serviceId, accessMethod: "direct_model", keyConfigured: true } },
    taskModelSelections: { [taskType]: { ...oldSelection, ...options.saved } },
    workflowProfileSelections: { [taskType]: oldSelection.serviceId },
    workflowProfilesByTask: {}, workflowProfileLoadSequences: {}, directServices: services
  };
  const reloadSnapshots = [];
  const ctx = {
    state, helpers, TASK_API_KEY_DEFS: [{ taskType }],
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis", EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant", EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    getSettingsWorkflowTaskType: () => taskType,
    getTaskModelSelectionDraft: () => ({ ...draft }),
    byId: () => ({ textContent: "" }), setStatus() {}, setWorkflowMutationBusy() {},
    describeFetchError: e => e.message,
    renderDirectServicesList() {}, renderTaskModelSelectionSection() {},
    renderWorkflowProfileStrip() {}, renderWorkflowProfileManager() {}, renderModelInterfaceState() {},
    async request(url, payload) {
      if (url.endsWith("/activate")) {
        if (options.fail) throw new Error("DIRECT_SERVICE_MODEL_REQUIRED");
        persisted.active = payload.taskModelSelection.serviceId;
        persisted.selection = { ...payload.taskModelSelection, taskType, effectiveModel: payload.taskModelSelection.modelName || "new-model" };
        return { data: { taskModelSelection: { ...persisted.selection } } };
      }
      if (payload) { persisted.selection = { ...payload, taskType }; return { data: {} }; }
      reloadSnapshots.push(JSON.parse(JSON.stringify(state.taskModelSelections[taskType])));
      if (url.includes("model-configurations?")) return { data: { activeConfigurationId: "", configurations: [] } };
      if (url.includes("task-model-selections?")) return { data: { taskModelSelections: [persisted.selection] } };
      if (url === "/provider/direct-services") return { data: { directServices: services } };
      throw new Error(`Unexpected URL: ${url}`);
    }
  };
  for (const name of ["emptyWorkflowProfileData", "normalizeWorkflowProfileData", "getWorkflowProfileData", "findDirectService", "loadWorkflowProfileForTask", "loadDirectServices", "saveTaskModelSelection"]) {
    const start = js.indexOf(`function ${name}(`);
    const end = js.indexOf("\n  function ", start + 3);
    ctx[name] = vm.runInNewContext(`(${js.slice(start, end)})`, ctx);
  }
  return { ctx, state, persisted, reloadSnapshots };
}

for (const taskType of ["excel.analysis", "excel.formula_assistant", "excel.smart_fill"]) {
  test(`${taskType}: saving new service survives real profile and service reloads`, async () => {
    const h = selectionSaveHarness(taskType);
    await h.ctx.saveTaskModelSelection();
    assert.equal(h.state.workflowProfileSelections[taskType], "direct_svc_new");
    assert.equal(h.ctx.getWorkflowProfileData(taskType).activeProfileId, "direct_svc_new");
    assert.equal(h.state.taskApiKeys[taskType].activeProfileId, "direct_svc_new");
    assert.equal(h.state.taskApiKeys[taskType].accessMethod, "direct_model");
    assert.equal(h.state.taskApiKeys[taskType].keyConfigured, true);
    assert.ok(h.reloadSnapshots.every(s => s.effectiveModel === "new-model"), "activation response must be applied before reload");
  });
  test(`${taskType}: failed activation preserves service, model and all parameter overrides`, async () => {
    const h = selectionSaveHarness(taskType, { fail: true, draft: { modelName: "" } });
    const before = JSON.stringify(h.persisted);
    const uiBefore = JSON.stringify(h.state);
    await assert.rejects(h.ctx.saveTaskModelSelection(), /DIRECT_SERVICE_MODEL_REQUIRED/);
    assert.equal(JSON.stringify(h.persisted), before);
    assert.equal(JSON.stringify(h.state), uiBefore);
  });
  test(`${taskType}: reopened pane reuses matching persisted custom model validation`, async () => {
    const h = selectionSaveHarness(taskType, {
      draft: { customModel: true, modelName: "custom-model" },
      saved: { serviceId: "direct_svc_new", modelName: "custom-model", customModel: true, customModelValidated: true }
    });
    await h.ctx.saveTaskModelSelection();
    assert.equal(h.persisted.selection.temperature, 0.7);
    assert.equal(h.persisted.selection.modelName, "custom-model");
  });
  for (const saved of [
    { serviceId: "direct_svc_old", modelName: "custom-model", customModelValidated: true },
    { serviceId: "direct_svc_new", modelName: "other-model", customModelValidated: true },
    { serviceId: "direct_svc_new", modelName: "custom-model", customModelValidated: false }
  ]) {
    test(`${taskType}: rejects unmatched persisted custom validation ${JSON.stringify(saved)}`, async () => {
      const h = selectionSaveHarness(taskType, { draft: { customModel: true, modelName: "custom-model" }, saved });
      await assert.rejects(h.ctx.saveTaskModelSelection(), /请先验证调用/);
      assert.equal(h.persisted.active, "direct_svc_old");
    });
  }
}
