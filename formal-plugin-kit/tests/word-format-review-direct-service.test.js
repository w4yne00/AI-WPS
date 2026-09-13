const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

function loadFn(name, ctx) {
  return vm.runInNewContext(`(${functionSource(name)})`, ctx);
}

test("Compact menu integration: word.format_review includes shared direct services", () => {
  assert.strictEqual(typeof helpers.buildTaskModelConfigMenuItems, "function");

  const profiles = [
    { id: "wf_1", name: "工作流格式方案", accessMethod: "workflow_platform", complete: true }
  ];
  const directServices = [
    { id: "direct_svc_1", name: "通用大模型服务", defaultModel: "gpt-4o", keyConfigured: true, serviceBaseUrl: "https://api.example.com" }
  ];

  const items = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "direct_svc_1",
    taskType: "word.format_review",
    directServices: directServices,
    taskModelSelection: { serviceId: "direct_svc_1", modelName: "gpt-4o" }
  });

  assert.ok(items.length >= 3, "should include profile, direct service, and manage items");
  const directItem = items.find(i => i.id === "direct_svc_1");
  assert.ok(directItem, "direct service item must exist for word.format_review");
  assert.strictEqual(directItem.selected, true);
  assert.strictEqual(directItem.label, "通用大模型服务 · 模型直连");
  assert.strictEqual(directItem.label.includes("gpt-4o"), false, "compact menu must not expose model identifiers");

  // Verify word.document_review still excludes direct services
  const docReviewItems = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "wf_1",
    taskType: "word.document_review",
    directServices: directServices
  });
  assert.strictEqual(docReviewItems.some(i => i.id === "direct_svc_1"), false);
});

test("Word taskpane HTML contains format review image input mode control", () => {
  assert.ok(html.includes('id="word-task-image-mode-row"'), "missing #word-task-image-mode-row in taskpane.html");
  assert.ok(html.includes('id="word-task-image-input-mode"'), "missing #word-task-image-input-mode in taskpane.html");
  assert.ok(html.includes('value="openai_image_url"'), "missing openai_image_url option");
  assert.ok(html.includes('value="disabled"'), "missing disabled option");
});

test("getWorkflowProfileData exposes direct services and selection for word.format_review", () => {
  const state = {
    workflowProfiles: {
      "word.format_review": {
        taskType: "word.format_review",
        activeProfileId: "direct_svc_1",
        profileCount: 1,
        profiles: [{ id: "direct_svc_1", name: "通用服务" }]
      }
    },
    directServices: [{ id: "direct_svc_1", name: "通用服务" }],
    taskModelSelections: {
      "word.format_review": { serviceId: "direct_svc_1", modelName: "gpt-4o", imageInputMode: "openai_image_url" }
    },
    taskApiKeys: {
      "word.format_review": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    },
    workflowProfileSelections: {}
  };
  const ctx = { state, helpers };
  const getProfileData = loadFn("getWorkflowProfileData", ctx);
  const data = getProfileData("word.format_review");

  assert.strictEqual(data.activeProfileId, "direct_svc_1");
  assert.ok(Array.isArray(data.directServices) && data.directServices.length === 1);
  assert.ok(data.taskModelSelection);
  assert.strictEqual(data.taskModelSelection.serviceId, "direct_svc_1");
  assert.strictEqual(data.taskModelSelection.imageInputMode, "openai_image_url");
});

test("renderTaskModelSelectionSection supports word.format_review with image mode toggle", () => {
  const state = {
    settingsWorkflowTaskType: "word.format_review",
    directServices: [{ id: "direct_svc_1", name: "通用服务", defaultModel: "gpt-4o" }],
    taskModelSelections: {
      "word.format_review": { serviceId: "direct_svc_1", modelName: "gpt-4o", imageInputMode: "openai_image_url" }
    },
    taskApiKeys: {
      "word.format_review": { activeProfileId: "direct_svc_1", accessMethod: "direct_model" }
    },
    workflowProfiles: {},
    workflowProfileSelections: {}
  };

  const mockNodes = {
    "word-task-direct-service-section": { hidden: true },
    "word-task-direct-service-title": { textContent: "" },
    "word-task-direct-service-hint": { textContent: "" },
    "word-task-direct-service-select": { innerHTML: "", value: "direct_svc_1" },
    "word-task-direct-params": { hidden: true },
    "word-task-model-select": { innerHTML: "", value: "" },
    "word-task-custom-model-check": { checked: false, disabled: false, title: "" },
    "word-task-custom-model-row": { hidden: true },
    "word-task-custom-model-input": { value: "" },
    "word-task-temperature": { value: "" },
    "word-task-max-output": { value: "" },
    "word-task-context": { value: "" },
    "word-task-model-cost-warning": { hidden: true, textContent: "" },
    "word-task-model-validation-status": { textContent: "" },
    "word-task-image-mode-row": { hidden: true },
    "word-task-image-input-mode": { value: "" }
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    getSettingsWorkflowTaskType() { return state.settingsWorkflowTaskType; },
    escapeWorkflowText(s) { return s || ""; },
    findDirectService(id) { return state.directServices.find(s => s.id === id) || null; }
  };
  ctx.getWorkflowProfileData = loadFn("getWorkflowProfileData", ctx);
  const renderFn = loadFn("renderTaskModelSelectionSection", ctx);

  // 1. Render for word.format_review
  renderFn();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false, "section must be visible for format_review");
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "格式审查接入选择");
  assert.strictEqual(mockNodes["word-task-image-mode-row"].hidden, false, "image mode row must be visible for format_review");
  assert.strictEqual(mockNodes["word-task-image-input-mode"].value, "openai_image_url");

  // 2. Render for word.smart_write: image mode row must be hidden
  state.settingsWorkflowTaskType = "word.smart_write";
  renderFn();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false);
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "智能编写接入选择");
  assert.strictEqual(mockNodes["word-task-image-mode-row"].hidden, true, "image mode row must be hidden for smart_write");
});

test("getTaskModelSelectionDraft collects imageInputMode for word.format_review", () => {
  const mockNodes = {
    "word-task-direct-service-select": { value: "direct_svc_1" },
    "word-task-custom-model-check": { checked: false },
    "word-task-model-select": { value: "gpt-4o" },
    "word-task-temperature": { value: "0.2" },
    "word-task-max-output": { value: "2048" },
    "word-task-context": { value: "32000" },
    "word-task-image-input-mode": { value: "disabled" }
  };
  let currentTask = "word.format_review";
  const ctx = {
    byId(id) { return mockNodes[id] || null; },
    getSettingsWorkflowTaskType() { return currentTask; }
  };
  const draftFn = loadFn("getTaskModelSelectionDraft", ctx);

  const draftFormat = draftFn();
  assert.strictEqual(draftFormat.serviceId, "direct_svc_1");
  assert.strictEqual(draftFormat.modelName, "gpt-4o");
  assert.strictEqual(draftFormat.imageInputMode, "disabled");

  // When smart_write, imageInputMode should not be attached or overridden
  currentTask = "word.smart_write";
  const draftWrite = draftFn();
  assert.strictEqual(draftWrite.imageInputMode, undefined);
});

test("Preflight gate: runDeterministicFormatReview invokes validateActiveDirectTaskSelection", () => {
  assert.ok(js.includes('validateActiveDirectTaskSelection("word.format_review")'),
    "runDeterministicFormatReview must call validateActiveDirectTaskSelection(\"word.format_review\")");
});
