const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { pptRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const css = fs.readFileSync(path.join(root, "taskpane.css"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

test("PPT settings markup exposes shared direct services card and editor", () => {
  // Shared direct service card on settings home
  assert.ok(html.includes('id="direct-services-card"'), "missing #direct-services-card in PPT taskpane.html");
  assert.ok(html.includes('id="direct-services-list"'), "missing #direct-services-list");
  assert.ok(html.includes('id="btn-new-direct-service"'), "missing #btn-new-direct-service");

  // Direct service editor
  assert.ok(html.includes('id="direct-service-editor-view"'), "missing #direct-service-editor-view");
  assert.ok(html.includes('id="direct-service-name"'), "missing #direct-service-name");
  assert.ok(html.includes('id="direct-service-url"'), "missing #direct-service-url");
  assert.ok(html.includes('id="direct-service-url-impact"'), "missing #direct-service-url-impact");
  assert.ok(html.includes('id="direct-service-default-model"'), "missing #direct-service-default-model");
  assert.ok(html.includes('id="btn-refresh-direct-service-models"'), "missing #btn-refresh-direct-service-models");
  assert.ok(html.includes('id="btn-validate-direct-service"'), "missing #btn-validate-direct-service");
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

  // PPT Task Model Selection section
  assert.ok(html.includes('id="ppt-task-direct-service-section"'), "missing #ppt-task-direct-service-section");
  assert.ok(html.includes('id="ppt-task-direct-service-select"'), "missing #ppt-task-direct-service-select");
  assert.ok(html.includes('id="ppt-task-model-select"'), "missing #ppt-task-model-select");
  assert.ok(html.includes('id="ppt-task-custom-model-check"'), "missing #ppt-task-custom-model-check");
  assert.ok(html.includes('id="ppt-task-custom-model-input"'), "missing #ppt-task-custom-model-input");
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
  assert.ok(html.includes('id="btn-clear-direct-service-key"'), "missing #btn-clear-direct-service-key");
});

test("Task Model Selection helpers: validateDirectServiceDraft and validateTaskModelSelectionDraft", () => {
  assert.strictEqual(typeof helpers.validateDirectServiceDraft, "function", "validateDirectServiceDraft helper must exist");
  assert.strictEqual(typeof helpers.validateTaskModelSelectionDraft, "function", "validateTaskModelSelectionDraft helper must exist");
  assert.strictEqual(typeof helpers.validateDirectTaskSelectionReadiness, "function", "validateDirectTaskSelectionReadiness helper must exist");
  assert.strictEqual(typeof helpers.evaluateDirectServiceDelete, "function", "evaluateDirectServiceDelete helper must exist");
  assert.strictEqual(typeof helpers.evaluateDirectServiceUrlImpact, "function", "evaluateDirectServiceUrlImpact helper must exist");
  assert.strictEqual(typeof helpers.isDirectServiceRevisionConflict, "function", "isDirectServiceRevisionConflict helper must exist");

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

test("Compact menu integration: includes shared direct service in PPT menu items", () => {
  assert.strictEqual(typeof helpers.buildTaskModelConfigMenuItems, "function");

  const profiles = [
    { id: "wf_1", name: "工作流总结方案", accessMethod: "workflow_platform", complete: true }
  ];
  const directServices = [
    { id: "direct_svc_1", name: "企业直连", defaultModel: "gpt-4o", keyConfigured: true, serviceBaseUrl: "https://api.example.com" }
  ];

  // Active is direct service for slide_assistant
  const items = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_1",
    taskType: "ppt.slide_assistant",
    directServices: directServices,
    taskModelSelection: { serviceId: "direct_svc_1", modelName: "gpt-4o" }
  });

  assert.ok(items.length >= 3, "should include profile, direct service, and manage items");
  const directItem = items.find(i => i.id === "direct_svc_1");
  assert.ok(directItem, "direct service item must exist");
  assert.strictEqual(directItem.selected, true);
  assert.strictEqual(directItem.label, "企业直连 · 模型直连");
  assert.strictEqual(directItem.label.includes("gpt-4o"), false, "compact menu must not expose model identifiers");

  // Active is direct service for structure_review
  const reviewItems = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_1",
    taskType: "ppt.structure_review",
    directServices: directServices,
    taskModelSelection: { serviceId: "direct_svc_1", modelName: "gpt-4o" }
  });
  const reviewDirectItem = reviewItems.find(i => i.id === "direct_svc_1");
  assert.ok(reviewDirectItem, "direct service item must also exist for structure_review");
  assert.strictEqual(reviewDirectItem.selected, true);

  const manageItem = items.find(i => i.id === "manage");
  assert.ok(manageItem, "manage item must exist");
  assert.strictEqual(manageItem.action, "manage");
});

test("Workflow platform configuration and tabs remain intact for both PPT tasks", () => {
  assert.ok(html.includes('data-workflow-task-tab="ppt.slide_assistant"'), "missing slide_assistant tab");
  assert.ok(html.includes('data-workflow-task-tab="ppt.structure_review"'), "missing structure_review tab");
  assert.ok(html.includes('id="btn-new-workflow-profile"'), "missing #btn-new-workflow-profile");
  assert.ok(html.includes('id="workflow-editor-view"'), "missing #workflow-editor-view");
});

test("Taskpane JS defines all required direct service handlers and helpers", () => {
  assert.ok(js.includes("function loadDirectServices("), "missing loadDirectServices in taskpane.js");
  assert.ok(js.includes("function renderDirectServicesList("), "missing renderDirectServicesList in taskpane.js");
  assert.ok(js.includes("function openDirectServiceEditor("), "missing openDirectServiceEditor in taskpane.js");
  assert.ok(js.includes("function closeDirectServiceEditor("), "missing closeDirectServiceEditor in taskpane.js");
  assert.ok(js.includes("function saveDirectServiceEditor("), "missing saveDirectServiceEditor in taskpane.js");
  assert.ok(js.includes("function refreshDirectServiceModelsInEditor("), "missing refreshDirectServiceModelsInEditor in taskpane.js");
  assert.ok(js.includes("function validateDirectService("), "missing validateDirectService in taskpane.js");
  assert.ok(js.includes("function renderTaskModelSelectionSection("), "missing renderTaskModelSelectionSection in taskpane.js");
  assert.ok(js.includes("function validateActiveDirectTaskSelection("), "missing validateActiveDirectTaskSelection in taskpane.js");
});

test("PPT direct services behavior: max 5 limit, single key, and activation rollback for slide assistant & structure review", async () => {
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
    "ppt-task-direct-service-section": { hidden: false },
    "ppt-task-direct-service-title": { textContent: "" },
    "ppt-task-direct-service-hint": { textContent: "" },
    "ppt-task-direct-service-select": { innerHTML: "", value: "" },
    "ppt-task-direct-params": { hidden: true },
    "ppt-task-model-select": { innerHTML: "", value: "" },
    "ppt-task-custom-model-check": { checked: false },
    "ppt-task-custom-model-row": { hidden: true },
    "ppt-task-custom-model-input": { value: "" },
    "ppt-task-temperature": { value: "" },
    "ppt-task-max-output": { value: "" },
    "ppt-task-context": { value: "" },
    "ppt-task-model-cost-warning": { hidden: true, textContent: "" },
    "ppt-task-model-validation-status": { textContent: "" },
    "task-model-config-trigger": {
      focus() {},
      setAttribute() {},
      removeAttribute() {}
    },
    "task-model-config-label": { textContent: "" },
    "task-model-config-status": { className: "" },
    "workflow-switch-feedback": { textContent: "" },
    "workflow-profile-strip": { hidden: false }
  };

  const requestsMade = [];
  let statusText = "";

  const state = {
    directServices: [],
    directServiceEditor: { open: false, mode: "create", serviceId: "", revision: 1, dirty: false },
    directServiceDeleteCandidate: null,
    taskModelSelections: {},
    settingsWorkflowTaskType: "ppt.slide_assistant",
    workflowTaskType: "ppt.slide_assistant",
    workflowProfiles: {
      "ppt.slide_assistant": { activeProfileId: "direct_svc_1", profiles: [] },
      "ppt.structure_review": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    workflowProfileSelections: {
      "ppt.slide_assistant": "direct_svc_1",
      "ppt.structure_review": "direct_svc_1"
    },
    taskModelConfigStatusByTask: {},
    taskModelConfigMenu: { open: false, highlightedIndex: -1, itemCount: 0, items: [] },
    taskApiKeys: {
      "ppt.slide_assistant": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" },
      "ppt.structure_review": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    },
    workflowProfileMutationBusy: false,
    busy: false,
    taskMode: "pptSlideAssistant"
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    escapeWorkflowText(s) { return s || ""; },
    setStatus(s) { statusText = s; },
    setWorkflowProfileMutationBusy(b) { state.workflowProfileMutationBusy = b; },
    describeFetchError(err) { return err && err.message || String(err); },
    setNodeTextIfChanged(node, val) { if (node) node.textContent = val; },
    focusTaskModelConfigTrigger() {},
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    renderWorkflowTaskTabs() {},
    renderModelInterfaceState() {},
    getCurrentWorkflowTaskType() { return state.workflowTaskType; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    isWorkflowInteractionBlocked() { return false; },
    loadWorkflowProfiles() { return Promise.resolve({}); },
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
  ctx.getWorkflowProfileById = loadFn("getWorkflowProfileById", ctx);
  ctx.activateWorkflowProfile = loadFn("activateWorkflowProfile", ctx);

  // 1. Max 5 services limit check
  state.directServices = [
    { id: "direct_svc_1", name: "S1", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_2", name: "S2", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_3", name: "S3", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_4", name: "S4", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" },
    { id: "direct_svc_5", name: "S5", revision: 1, keyConfigured: true, serviceBaseUrl: "https://api.example.com" }
  ];
  ctx.renderDirectServicesList();
  assert.strictEqual(mockNodes["btn-new-direct-service"].disabled, true, "New button must be disabled when 5 services exist");

  ctx.openDirectServiceEditor("create", "");
  assert.strictEqual(statusText, "最多只能保存 5 份共享直连服务。");
  assert.strictEqual(state.directServiceEditor.open, false);

  // 2. Open editor when < 5
  state.directServices.pop();
  ctx.openDirectServiceEditor("create", "");
  assert.strictEqual(state.directServiceEditor.open, true);
  assert.strictEqual(mockNodes["direct-service-editor-title"].textContent, "新建直连服务");
  assert.strictEqual(mockNodes["direct-service-key-label"].textContent, "API Key（仅需录入一次）");

  // 3. Activate direct service for ppt.slide_assistant
  requestsMade.length = 0;
  await ctx.activateWorkflowProfile("direct_svc_2", "ppt.slide_assistant", "direct_svc_1");
  const activateReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_2/activate"));
  assert.ok(activateReq, "must invoke direct service activation endpoint");
  assert.strictEqual(activateReq.payload.taskType, "ppt.slide_assistant");
  assert.deepStrictEqual(
    JSON.parse(JSON.stringify(activateReq.payload.taskModelSelection)),
    {
      serviceId: "direct_svc_2",
      modelName: "",
      customModel: false,
      temperature: null,
      maxOutputTokens: null,
      contextWindowTokens: null
    },
    "compact-menu activation must clear the previous service model override atomically"
  );
  assert.strictEqual(state.workflowProfileSelections["ppt.slide_assistant"], "direct_svc_2");

  // 4. Activate direct service for ppt.structure_review
  requestsMade.length = 0;
  state.settingsWorkflowTaskType = "ppt.structure_review";
  await ctx.activateWorkflowProfile("direct_svc_3", "ppt.structure_review", "direct_svc_1");
  const activateReviewReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_3/activate"));
  assert.ok(activateReviewReq, "must invoke direct service activation for ppt.structure_review");
  assert.strictEqual(activateReviewReq.payload.taskType, "ppt.structure_review");
  assert.strictEqual(state.workflowProfileSelections["ppt.structure_review"], "direct_svc_3");

  // 5. Activation failure rollback
  ctx.request = () => Promise.reject(new Error("网络超时"));
  await ctx.activateWorkflowProfile("direct_svc_4", "ppt.slide_assistant", "direct_svc_2");
  assert.strictEqual(state.workflowProfileSelections["ppt.slide_assistant"], "direct_svc_2", "must rollback to previous selection on failure");
  assert.strictEqual(state.taskModelConfigStatusByTask["ppt.slide_assistant"], "error");
});

test("PPT task model selection: parameters override, draft generation", () => {
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
    "ppt-task-direct-service-section": { hidden: false },
    "ppt-task-direct-service-title": { textContent: "" },
    "ppt-task-direct-service-hint": { textContent: "" },
    "ppt-task-direct-service-select": { innerHTML: "", value: "direct_svc_1" },
    "ppt-task-direct-params": { hidden: false },
    "ppt-task-model-select": { innerHTML: "", value: "gpt-4o" },
    "ppt-task-custom-model-check": { checked: false, disabled: false, title: "" },
    "ppt-task-custom-model-row": { hidden: true },
    "ppt-task-custom-model-input": { value: "" },
    "ppt-task-temperature": { value: "0.5" },
    "ppt-task-max-output": { value: "3000" },
    "ppt-task-context": { value: "32000" },
    "ppt-task-model-cost-warning": { hidden: false, textContent: "" },
    "ppt-task-model-validation-status": { textContent: "" }
  };

  const state = {
    settingsWorkflowTaskType: "ppt.slide_assistant",
    directServices: [
      { id: "direct_svc_1", name: "企业直连", defaultModel: "gpt-4o", keyConfigured: true, modelList: ["gpt-4o", "gpt-4o-mini"] }
    ],
    taskModelSelections: {
      "ppt.slide_assistant": { serviceId: "direct_svc_1", modelName: "gpt-4o", temperature: 0.5, maxOutputTokens: 3000, contextWindowTokens: 32000 }
    },
    workflowProfiles: {
      "ppt.slide_assistant": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    workflowProfileSelections: {
      "ppt.slide_assistant": "direct_svc_1"
    },
    taskApiKeys: {
      "ppt.slide_assistant": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    }
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    escapeWorkflowText(s) { return s || ""; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    renderWorkflowProfileManager() {}
  };

  ctx.findDirectService = loadFn("findDirectService", ctx);
  ctx.renderTaskModelSelectionSection = loadFn("renderTaskModelSelectionSection", ctx);
  ctx.getTaskModelSelectionDraft = loadFn("getTaskModelSelectionDraft", ctx);

  // Render selection section
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["ppt-task-direct-params"].hidden, false);
  assert.strictEqual(mockNodes["ppt-task-direct-service-title"].textContent, "智能总结接入选择");

  // Get draft
  const draft = ctx.getTaskModelSelectionDraft();
  assert.strictEqual(draft.serviceId, "direct_svc_1");
  assert.strictEqual(draft.modelName, "gpt-4o");
  assert.strictEqual(draft.temperature, 0.5);
  assert.strictEqual(draft.maxOutputTokens, 3000);
  assert.strictEqual(draft.contextWindowTokens, 32000);

  // Switch to ppt.structure_review
  state.settingsWorkflowTaskType = "ppt.structure_review";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["ppt-task-direct-service-title"].textContent, "结构审查接入选择");
});

test("Preflight readiness check: validateActiveDirectTaskSelection blocks unready services", () => {
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

  const state = {
    taskApiKeys: {
      "ppt.slide_assistant": { accessMethod: "direct_model", activeProfileId: "svc_1" }
    },
    directServices: [
      { id: "svc_1", name: "测试服务", keyConfigured: false, serviceBaseUrl: "https://api.example.com", modelList: ["gpt-4o"] }
    ],
    taskModelSelections: {
      "ppt.slide_assistant": { serviceId: "svc_1", modelName: "gpt-4o" }
    }
  };

  const ctx = {
    state,
    helpers,
    setStatus() {},
    findDirectService(id) {
      return (state.directServices || []).find(s => s.id === id) || null;
    }
  };

  ctx.validateActiveDirectTaskSelection = loadFn("validateActiveDirectTaskSelection", ctx);

  // Missing key blocks submission
  const noKey = ctx.validateActiveDirectTaskSelection("ppt.slide_assistant");
  assert.strictEqual(noKey.valid, false);
  assert.ok(noKey.error.includes("Key"));

  // Key configured allows submission
  state.directServices[0].keyConfigured = true;
  const withKey = ctx.validateActiveDirectTaskSelection("ppt.slide_assistant");
  assert.strictEqual(withKey.valid, true);

  // Workflow platform is bypassed (returns valid: true)
  state.taskApiKeys["ppt.slide_assistant"].accessMethod = "workflow_platform";
  const wf = ctx.validateActiveDirectTaskSelection("ppt.slide_assistant");
  assert.strictEqual(wf.valid, true);
});

test("Delete protection and URL impact warnings respect PPT task references", () => {
  const serviceWithRefs = {
    id: "svc_1",
    name: "网关",
    serviceBaseUrl: "https://old.example.com",
    referencedTasks: ["ppt.slide_assistant", "ppt.structure_review"]
  };

  // Evaluate delete
  const delEval = helpers.evaluateDirectServiceDelete(serviceWithRefs);
  assert.strictEqual(delEval.canDelete, false);
  assert.ok(delEval.message.includes("智能总结"));
  assert.ok(delEval.message.includes("结构审查"));

  // Evaluate URL impact
  const urlImpact = helpers.evaluateDirectServiceUrlImpact(serviceWithRefs, "https://new.example.com");
  assert.strictEqual(urlImpact.isModified, true);
  assert.ok(urlImpact.warning.includes("智能总结"));
  assert.ok(urlImpact.warning.includes("结构审查"));
});
