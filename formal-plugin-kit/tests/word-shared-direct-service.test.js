const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { wordRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const css = fs.readFileSync(path.join(root, "taskpane.css"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

test("Word settings markup exposes shared direct services card and editor", () => {
  // Shared direct service card on settings home
  assert.ok(html.includes('id="direct-services-card"'), "missing #direct-services-card in Word taskpane.html");
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

  // Word Task Model Selection section
  assert.ok(html.includes('id="word-task-direct-service-section"'), "missing #word-task-direct-service-section");
  assert.ok(html.includes('id="word-task-direct-service-select"'), "missing #word-task-direct-service-select");
  assert.ok(html.includes('id="word-task-model-select"'), "missing #word-task-model-select");
  assert.ok(html.includes('id="word-task-custom-model-check"'), "missing #word-task-custom-model-check");
  assert.ok(html.includes('id="word-task-custom-model-input"'), "missing #word-task-custom-model-input");
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

test("Compact menu integration: includes shared direct service in Word writing menu items", () => {
  assert.strictEqual(typeof helpers.buildTaskModelConfigMenuItems, "function");

  const profiles = [
    { id: "wf_1", name: "工作流编写方案", accessMethod: "workflow_platform", complete: true }
  ];
  const directServices = [
    { id: "direct_svc_1", name: "企业直连", defaultModel: "gpt-4o", keyConfigured: true, serviceBaseUrl: "https://api.example.com" }
  ];

  // Active is direct service
  const items = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_1",
    taskType: "word.smart_write",
    directServices: directServices,
    taskModelSelection: { serviceId: "direct_svc_1", modelName: "gpt-4o" }
  });

  assert.ok(items.length >= 3, "should include profile, direct service, and manage items");
  const directItem = items.find(i => i.id === "direct_svc_1");
  assert.ok(directItem, "direct service item must exist");
  assert.strictEqual(directItem.selected, true);
  assert.strictEqual(directItem.label, "企业直连 · 模型直连");
  assert.strictEqual(directItem.label.includes("gpt-4o"), false, "compact menu must not expose model identifiers");

  const reviewItems = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "wf_1",
    taskType: "word.document_review",
    directServices: directServices,
    taskModelSelection: { serviceId: "direct_svc_1", modelName: "gpt-4o" }
  });
  assert.strictEqual(
    reviewItems.some(item => item.id === "direct_svc_1"),
    false,
    "document review must not expose shared direct services"
  );

  const manageItem = items.find(i => i.id === "manage");
  assert.ok(manageItem, "manage item must exist");
  assert.strictEqual(manageItem.action, "manage");
});

test("Workflow platform configuration and tabs remain intact for all 4 Word tasks", () => {
  assert.ok(html.includes('data-workflow-task-tab="word.smart_write"'), "missing smart_write tab");
  assert.ok(html.includes('data-workflow-task-tab="word.smart_imitation"'), "missing smart_imitation tab");
  assert.ok(html.includes('data-workflow-task-tab="word.document_review"'), "missing document_review tab");
  assert.ok(html.includes('data-workflow-task-tab="word.format_review"'), "missing format_review tab");
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

test("Word direct services behavior: max 5 limit, single key, and activation rollback for smart write & imitation", async () => {
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
    "word-task-direct-service-section": { hidden: false },
    "word-task-direct-service-title": { textContent: "" },
    "word-task-direct-service-hint": { textContent: "" },
    "word-task-direct-service-select": { innerHTML: "", value: "" },
    "word-task-direct-params": { hidden: true },
    "word-task-model-select": { innerHTML: "", value: "" },
    "word-task-custom-model-check": { checked: false },
    "word-task-custom-model-row": { hidden: true },
    "word-task-custom-model-input": { value: "" },
    "word-task-temperature": { value: "" },
    "word-task-max-output": { value: "" },
    "word-task-context": { value: "" },
    "word-task-model-cost-warning": { hidden: true, textContent: "" },
    "word-task-model-validation-status": { textContent: "" },
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
    settingsWorkflowTaskType: "word.smart_write",
    workflowProfiles: {
      "word.smart_write": { activeProfileId: "direct_svc_1", profiles: [] },
      "word.smart_imitation": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    workflowProfileSelections: {
      "word.smart_write": "direct_svc_1",
      "word.smart_imitation": "direct_svc_1"
    },
    taskModelConfigStatusByTask: {},
    taskModelConfigMenu: { open: false, highlightedIndex: -1, itemCount: 0, items: [] },
    taskApiKeys: {
      "word.smart_write": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" },
      "word.smart_imitation": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    },
    workflowProfileMutationBusy: false,
    modelTaskBusy: false,
    currentMode: "smartWrite"
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
    getCurrentWorkflowTaskType() { return state.settingsWorkflowTaskType; },
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

  // 3. Activate direct service for smart_write
  requestsMade.length = 0;
  await ctx.activateWorkflowProfile("direct_svc_2", "word.smart_write", "direct_svc_1");
  const activateReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_2/activate"));
  assert.ok(activateReq, "must invoke direct service activation endpoint");
  assert.strictEqual(activateReq.payload.taskType, "word.smart_write");
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
  assert.strictEqual(state.workflowProfileSelections["word.smart_write"], "direct_svc_2");

  // 4. Activate direct service for smart_imitation
  requestsMade.length = 0;
  state.settingsWorkflowTaskType = "word.smart_imitation";
  await ctx.activateWorkflowProfile("direct_svc_3", "word.smart_imitation", "direct_svc_1");
  const activateImitationReq = requestsMade.find(r => r.url.includes("/provider/direct-services/direct_svc_3/activate"));
  assert.ok(activateImitationReq, "must invoke direct service activation for smart_imitation");
  assert.strictEqual(activateImitationReq.payload.taskType, "word.smart_imitation");
  assert.strictEqual(state.workflowProfileSelections["word.smart_imitation"], "direct_svc_3");

  // 5. Activation failure rollback
  ctx.request = () => Promise.reject(new Error("网络超时"));
  await ctx.activateWorkflowProfile("direct_svc_4", "word.smart_write", "direct_svc_2");
  assert.strictEqual(state.workflowProfileSelections["word.smart_write"], "direct_svc_2", "must rollback to previous selection on failure");
  assert.strictEqual(state.taskModelConfigStatusByTask["word.smart_write"], "error");
});

test("Word task model selection: parameters override, draft generation, and review tab isolation", () => {
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
    "word-task-direct-service-section": { hidden: false },
    "word-task-direct-service-title": { textContent: "" },
    "word-task-direct-service-hint": { textContent: "" },
    "word-task-direct-service-select": { innerHTML: "", value: "direct_svc_1" },
    "word-task-direct-params": { hidden: false },
    "word-task-model-select": { innerHTML: "", value: "gpt-4o" },
    "word-task-custom-model-check": { checked: false, disabled: false, title: "" },
    "word-task-custom-model-row": { hidden: true },
    "word-task-custom-model-input": { value: "" },
    "word-task-temperature": { value: "0.5" },
    "word-task-max-output": { value: "3000" },
    "word-task-context": { value: "32000" },
    "word-task-model-cost-warning": { hidden: false, textContent: "" },
    "word-task-model-validation-status": { textContent: "" }
  };

  const state = {
    settingsWorkflowTaskType: "word.smart_write",
    directServices: [
      { id: "direct_svc_1", name: "企业直连", defaultModel: "gpt-4o", keyConfigured: true, modelList: ["gpt-4o", "gpt-4o-mini"] }
    ],
    taskModelSelections: {
      "word.smart_write": { serviceId: "direct_svc_1", modelName: "gpt-4o", temperature: 0.5, maxOutputTokens: 3000, contextWindowTokens: 32000 }
    },
    workflowProfiles: {
      "word.smart_write": { activeProfileId: "direct_svc_1", profiles: [] }
    },
    workflowProfileSelections: {
      "word.smart_write": "direct_svc_1"
    },
    taskApiKeys: {
      "word.smart_write": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    }
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    escapeWorkflowText(s) { return s || ""; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    getCurrentWorkflowTaskType() { return state.settingsWorkflowTaskType; }
  };

  ctx.findDirectService = loadFn("findDirectService", ctx);
  ctx.getWorkflowProfileData = loadFn("getWorkflowProfileData", ctx);
  ctx.renderTaskModelSelectionSection = loadFn("renderTaskModelSelectionSection", ctx);
  ctx.getTaskModelSelectionDraft = loadFn("getTaskModelSelectionDraft", ctx);

  // 1. Render smart_write task model selection
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false);
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "智能编写接入选择");

  // 2. Draft generation
  const draft = ctx.getTaskModelSelectionDraft();
  assert.strictEqual(draft.serviceId, "direct_svc_1");
  assert.strictEqual(draft.modelName, "gpt-4o");
  assert.strictEqual(draft.temperature, 0.5);
  assert.strictEqual(draft.maxOutputTokens, 3000);
  assert.strictEqual(draft.contextWindowTokens, 32000);

  // 3. Switch to smart_imitation
  state.settingsWorkflowTaskType = "word.smart_imitation";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false);
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "智能仿写接入选择");

  // 4. Review tabs isolation: hidden on document_review and format_review
  state.settingsWorkflowTaskType = "word.document_review";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, true, "task direct service section must be hidden for document_review");

  state.settingsWorkflowTaskType = "word.format_review";
  ctx.renderTaskModelSelectionSection();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, true, "task direct service section must be hidden for format_review");
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
    directServices: [
      { id: "direct_svc_ready", name: "就绪服务", defaultModel: "gpt-4o", keyConfigured: true, serviceBaseUrl: "https://api.example.com", modelList: ["gpt-4o"] },
      { id: "direct_svc_nokey", name: "无Key服务", defaultModel: "gpt-4o", keyConfigured: false, serviceBaseUrl: "https://api.example.com", modelList: ["gpt-4o"] }
    ],
    taskModelSelections: {
      "word.smart_write": { serviceId: "direct_svc_ready", modelName: "gpt-4o" },
      "word.smart_imitation": { serviceId: "direct_svc_nokey", modelName: "gpt-4o" }
    },
    taskApiKeys: {
      "word.smart_write": { activeProfileId: "direct_svc_ready", accessMethod: "direct_model" },
      "word.smart_imitation": { activeProfileId: "direct_svc_nokey", accessMethod: "direct_model" }
    }
  };

  const ctx = {
    state,
    helpers,
    byId() { return null; }
  };
  ctx.findDirectService = loadFn("findDirectService", ctx);
  const validateFn = loadFn("validateActiveDirectTaskSelection", ctx);

  // Ready service passes
  const readyResult = validateFn("word.smart_write");
  assert.strictEqual(readyResult.valid, true);

  // Service without key is blocked
  const nokeyResult = validateFn("word.smart_imitation");
  assert.strictEqual(nokeyResult.valid, false);
  assert.ok(nokeyResult.error.includes("API Key") || nokeyResult.error.includes("未配置"));
});

test("Delete protection and URL impact warnings respect Word task references", () => {
  const serviceWithRefs = {
    id: "direct_svc_1",
    name: "公用直连网关",
    serviceBaseUrl: "https://api.gateway.com/v1",
    referencedTasks: ["word.smart_write", "word.smart_imitation"]
  };

  // Delete evaluation
  const deleteEval = helpers.evaluateDirectServiceDelete(serviceWithRefs);
  assert.strictEqual(deleteEval.canDelete, false);
  assert.ok(deleteEval.message.includes("智能编写"));
  assert.ok(deleteEval.message.includes("智能仿写"));

  // URL change evaluation
  const urlImpact = helpers.evaluateDirectServiceUrlImpact(serviceWithRefs, "https://api.gateway.com/v2");
  assert.strictEqual(urlImpact.isModified, true);
  assert.ok(urlImpact.warning.includes("智能编写"));
  assert.ok(urlImpact.warning.includes("智能仿写"));
  assert.ok(urlImpact.warning.includes("立即调用新地址"));
});

test("shared direct-service reads fail closed and preserve the last good snapshot", async () => {
  const vm = require("node:vm");

  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const previousServices = [{ id: "direct_svc_existing", name: "现有服务" }];
  const state = {
    directServices: previousServices,
    taskModelSelections: { "word.smart_write": { serviceId: "direct_svc_existing" } },
    taskApiKeys: {},
    workflowProfileSelections: {},
    configRefreshRequestId: 7
  };
  const expectedError = new Error("task selections unavailable");
  const ctx = {
    state,
    TASK_API_KEY_DEFS: [{ taskType: "word.smart_write" }],
    renderDirectServicesList() {},
    renderTaskModelSelectionSection() {},
    renderWorkflowProfileStrip() {},
    renderWorkflowProfileManager() {},
    request(url) {
      if (url === "/provider/direct-services") {
        return Promise.resolve({ data: { directServices: [{ id: "direct_svc_new" }] } });
      }
      return Promise.reject(expectedError);
    }
  };
  const loadDirectServices = vm.runInNewContext(`(${functionSource("loadDirectServices")})`, ctx);

  await assert.rejects(loadDirectServices(7), /task selections unavailable/);
  assert.strictEqual(state.directServices, previousServices, "partial reads must not replace the last good snapshot");
  assert.strictEqual(state.taskModelSelections["word.smart_write"].serviceId, "direct_svc_existing");
});

test("direct-service busy state covers new controls and closing the editor clears the API key", () => {
  const vm = require("node:vm");

  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  function control() {
    return { disabled: false };
  }
  const directControls = [control(), control(), control()];
  const taskControls = [control(), control()];
  const roots = {
    "workflow-profile-manager": { querySelectorAll() { return []; } },
    "workflow-editor-view": { querySelectorAll() { return []; } },
    "direct-services-card": { querySelectorAll() { return directControls; } },
    "word-task-direct-service-section": { querySelectorAll() { return taskControls; } },
    "btn-new-workflow-profile": control(),
    "direct-service-editor-view": { hidden: false },
    "direct-services-list": { hidden: true },
    "btn-new-direct-service": { hidden: true, disabled: false },
    "direct-service-editor-error": { textContent: "old error" },
    "direct-service-url-impact": { hidden: false, textContent: "old warning" },
    "direct-service-key": { value: "sk-plaintext-must-not-remain" }
  };
  const state = {
    workflowProfileMutationBusy: true,
    directServiceOperationId: 3,
    directServiceEditor: { open: true, serviceId: "direct_svc_1" }
  };
  const ctx = {
    state,
    byId(id) { return roots[id] || null; },
    syncSettingsRefreshController() {},
    renderWorkflowProfileStrip() {},
    renderWorkflowTaskTabs() {}
  };
  const syncBusy = vm.runInNewContext(`(${functionSource("syncWorkflowProfileManagerBusyState")})`, ctx);
  const closeEditor = vm.runInNewContext(`(${functionSource("closeDirectServiceEditor")})`, ctx);

  syncBusy();
  directControls.concat(taskControls).forEach(node => assert.strictEqual(node.disabled, true));

  closeEditor();
  assert.strictEqual(roots["direct-service-key"].value, "", "hidden editor must not retain plaintext API keys");
  assert.strictEqual(state.directServiceEditor.open, false);
  assert.ok(state.directServiceOperationId > 3, "closing the editor must invalidate older async callbacks");
});

test("direct-service refresh ignores duplicates and stale completion callbacks", async () => {
  const vm = require("node:vm");

  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  let resolveRequest;
  let requestCount = 0;
  const pending = new Promise(resolve => { resolveRequest = resolve; });
  const statusNode = { textContent: "idle" };
  const state = {
    workflowProfileMutationBusy: false,
    directServiceOperationId: 0,
    directServiceEditor: { open: true, serviceId: "direct_svc_old", revision: 1 }
  };
  const ctx = {
    state,
    byId(id) { return id === "direct-service-models-status" ? statusNode : null; },
    setWorkflowMutationBusy(value) { state.workflowProfileMutationBusy = value; },
    findDirectService() { return null; },
    loadDirectServices() { return Promise.resolve(); },
    describeFetchError(error) { return error.message; },
    formatDirectServiceCatalogStatus() { return "旧服务目录"; },
    request() {
      requestCount += 1;
      return pending;
    }
  };
  const refresh = vm.runInNewContext(`(${functionSource("refreshDirectServiceModelsInEditor")})`, ctx);

  const first = refresh();
  const duplicate = refresh();
  assert.strictEqual(requestCount, 1, "duplicate clicks while busy must not issue another request");
  assert.strictEqual(state.workflowProfileMutationBusy, true);
  assert.ok(first && typeof first.then === "function", "async handlers must return their operation promise");
  assert.strictEqual(duplicate, undefined);

  state.directServiceOperationId += 1;
  state.directServiceEditor = { open: true, serviceId: "direct_svc_new", revision: 9 };
  statusNode.textContent = "new editor status";
  resolveRequest({ data: { directService: { id: "direct_svc_old", revision: 2, modelList: ["old-model"] } } });
  await first;

  assert.strictEqual(state.directServiceEditor.revision, 9, "stale callback must not mutate the newer editor");
  assert.strictEqual(statusNode.textContent, "new editor status", "stale callback must not overwrite the newer editor status");
});

test("task selection save uses one atomic activation request", () => {
  const vm = require("node:vm");

  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const nodes = {
    "word-task-direct-service-select": { value: "direct_svc_1" },
    "word-task-custom-model-check": { checked: false },
    "word-task-model-select": { value: "write-model" },
    "word-task-custom-model-input": { value: "" },
    "word-task-temperature": { value: "0.4" },
    "word-task-max-output": { value: "2048" },
    "word-task-context": { value: "32000" },
    "word-task-model-validation-status": { textContent: "" }
  };
  const state = {
    workflowProfileMutationBusy: false,
    settingsWorkflowTaskType: "word.smart_write",
    lastValidatedCustomModel: null,
    directServices: [{ id: "direct_svc_1", serviceBaseUrl: "https://api.example.com/v1", keyConfigured: true, modelList: ["write-model"] }]
  };
  const requests = [];
  const ctx = {
    state,
    helpers,
    byId(id) { return nodes[id] || null; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    findDirectService(id) { return state.directServices.find(service => service.id === id); },
    setWorkflowProfileMutationBusy(value) { state.workflowProfileMutationBusy = value; },
    setStatus() {},
    describeFetchError(error) { return error.message; },
    loadWorkflowProfiles() { return Promise.resolve(); },
    loadDirectServices() { return Promise.resolve(); },
    request(url, payload, options) {
      requests.push({ url, payload, method: options && options.method });
      return new Promise(() => {});
    }
  };
  ctx.getTaskModelSelectionDraft = vm.runInNewContext(`(${functionSource("getTaskModelSelectionDraft")})`, ctx);
  const save = vm.runInNewContext(`(${functionSource("saveTaskModelSelection")})`, ctx);

  save();
  assert.strictEqual(requests.length, 1);
  assert.strictEqual(requests[0].url, "/provider/direct-services/direct_svc_1/activate");
  assert.strictEqual(requests[0].method, undefined);
  assert.strictEqual(requests[0].payload.taskType, "word.smart_write");
  assert.deepStrictEqual(
    JSON.parse(JSON.stringify(requests[0].payload.taskModelSelection)),
    {
      serviceId: "direct_svc_1",
      modelName: "write-model",
      customModel: false,
      temperature: 0.4,
      maxOutputTokens: 2048,
      contextWindowTokens: 32000
    }
  );
});

test("formal direct-service event binding invokes the production handlers", () => {
  const ids = [
    "btn-new-direct-service",
    "direct-services-list",
    "btn-direct-service-editor-back",
    "btn-cancel-direct-service",
    "btn-save-direct-service",
    "btn-refresh-direct-service-models",
    "btn-validate-direct-service",
    "btn-cancel-direct-service-delete",
    "btn-confirm-direct-service-delete",
    "btn-clear-direct-service-key",
    "direct-service-name",
    "direct-service-url",
    "direct-service-key",
    "direct-service-default-model",
    "word-task-direct-service-select",
    "word-task-custom-model-check",
    "btn-validate-task-model-selection",
    "btn-save-task-model-selection"
  ];
  const nodes = Object.fromEntries(ids.map(id => [id, new EventTarget()]));
  const calls = [];
  helpers.bindDirectServiceEvents({
    byId(id) { return nodes[id] || null; },
    handlers: {
      openCreate() { calls.push(["open", "create", ""]); },
      listAction() { calls.push(["list"]); },
      closeEditor() { calls.push(["close"]); },
      saveEditor() { calls.push(["save"]); },
      refreshModels() { calls.push(["refresh"]); },
      validateService() { calls.push(["validate-service"]); },
      cancelDelete() { calls.push(["cancel-delete"]); },
      confirmDelete() { calls.push(["confirm-delete"]); },
      clearKey() { calls.push(["clear-key"]); },
      editorInput() { calls.push(["editor-input"]); },
      taskServiceChange() { calls.push(["task-service-change"]); },
      customModelChange() { calls.push(["custom-change"]); },
      validateTaskSelection() { calls.push(["validate-task"]); },
      saveTaskSelection() { calls.push(["save-task"]); }
    }
  });

  nodes["btn-new-direct-service"].dispatchEvent(new Event("click"));
  nodes["btn-save-direct-service"].dispatchEvent(new Event("click"));
  nodes["btn-refresh-direct-service-models"].dispatchEvent(new Event("click"));
  nodes["btn-validate-direct-service"].dispatchEvent(new Event("click"));
  nodes["btn-validate-task-model-selection"].dispatchEvent(new Event("click"));
  nodes["btn-save-task-model-selection"].dispatchEvent(new Event("click"));

  assert.deepStrictEqual(calls.slice(0, 6), [
    ["open", "create", ""],
    ["save"],
    ["refresh"],
    ["validate-service"],
    ["validate-task"],
    ["save-task"]
  ]);
});
