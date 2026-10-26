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

  // Verify word.document_review now includes direct services (Issue #180)
  const docReviewItems = helpers.buildTaskModelConfigMenuItems(profiles, {
    activeProfileId: "wf_1",
    taskType: "word.document_review",
    directServices: directServices
  });
  assert.strictEqual(docReviewItems.some(i => i.id === "direct_svc_1"), true);
});

test("format review settings keep vision check and drop manual image controls", () => {
  assert.equal(html.includes('id="word-task-image-input-mode"'), false);
  assert.equal(html.includes("图片输入模式"), false);
  assert.equal(html.includes('id="btn-authorize-task-images"'), false);
  assert.equal(html.includes('id="btn-revoke-task-images"'), false);
  assert.equal(html.includes('id="btn-validate-task-images"'), true);
  assert.equal(html.includes("验证视觉能力"), true);
  assert.equal(html.includes('id="word-task-vision-status"'), true);
  assert.equal(html.includes('id="btn-validate-task-model-selection"'), true);
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
    "word-task-vision-status": { textContent: "" },
    "btn-validate-task-model-selection": { hidden: false }
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
  ctx.formatReviewVisionStatusText = loadFn("formatReviewVisionStatusText", ctx);
  const renderFn = loadFn("renderTaskModelSelectionSection", ctx);

  // 1. Render for word.format_review
  renderFn();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false, "section must be visible for format_review");
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "接入选择");
  assert.strictEqual(mockNodes["word-task-image-mode-row"].hidden, false, "vision row must be visible for format_review");
  assert.strictEqual(mockNodes["word-task-vision-status"].textContent, "未验证");
  assert.strictEqual(mockNodes["btn-validate-task-model-selection"].hidden, true);

  state.taskModelSelections["word.format_review"].imageSemanticValidation = {
    validated: true, stale: false, message: ""
  };
  renderFn();
  assert.strictEqual(mockNodes["word-task-vision-status"].textContent, "视觉能力验证成功");

  state.taskModelSelections["word.format_review"].imageSemanticValidation = {
    validated: false, stale: false, message: "模型未能识别合成测试图片。"
  };
  renderFn();
  assert.strictEqual(mockNodes["word-task-vision-status"].textContent, "模型未能识别合成测试图片。");

  // 2. Render for word.smart_write: image mode row must be hidden
  state.settingsWorkflowTaskType = "word.smart_write";
  renderFn();
  assert.strictEqual(mockNodes["word-task-direct-service-section"].hidden, false);
  assert.strictEqual(mockNodes["word-task-direct-service-title"].textContent, "接入选择");
  assert.strictEqual(mockNodes["word-task-image-mode-row"].hidden, true, "image mode row must be hidden for smart_write");
  assert.strictEqual(mockNodes["btn-validate-task-model-selection"].hidden, true);
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
  assert.strictEqual(draftFormat.imageInputMode, "openai_image_url");

  // When smart_write, imageInputMode should not be attached or overridden
  currentTask = "word.smart_write";
  const draftWrite = draftFn();
  assert.strictEqual(draftWrite.imageInputMode, undefined);
});

test("Preflight gate: runDeterministicFormatReview invokes validateActiveDirectTaskSelection", () => {
  assert.ok(js.includes('validateActiveDirectTaskSelection("word.format_review")'),
    "runDeterministicFormatReview must call validateActiveDirectTaskSelection(\"word.format_review\")");
});

test("vision check uses the saved selection and refuses an unsaved draft", async () => {
  const saved = { serviceId: "direct_svc_1", modelName: "vision", imageInputMode: "openai_image_url" };
  const calls = [];
  const nodes = { "word-task-vision-status": { textContent: "" }, "word-task-model-validation-status": { textContent: "" } };
  const ctx = {
    state: { taskModelSelections: { "word.format_review": saved } },
    getSettingsWorkflowTaskType: () => "word.format_review",
    getTaskModelSelectionDraft: () => ({ serviceId: saved.serviceId, modelName: saved.modelName, imageInputMode: saved.imageInputMode }),
    findDirectService: () => ({ name: "测试服务", serviceBaseUrl: "https://example.com/v1", revision: 7 }),
    byId: id => nodes[id],
    window: { confirm: () => true },
    setWorkflowProfileMutationBusy() {},
    describeFetchError: error => error.message,
    request: async (route, payload) => {
      calls.push({ route, payload });
      return { data: { taskModelSelection: { ...saved, imageSemanticValidation: { validated: true, stale: false } } } };
    }
  };
  ctx.formatReviewSelectionBinding = loadFn("formatReviewSelectionBinding", ctx);
  const action = loadFn("performTaskImageAction", ctx);
  await action("validate-image");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].route, "/provider/task-model-selections/word.format_review/validate-image");
  assert.equal(calls[0].payload.serviceId, undefined);
  assert.equal(nodes["word-task-vision-status"].textContent, "视觉能力验证成功");

  calls.length = 0;
  ctx.getTaskModelSelectionDraft = () => ({ ...saved, modelName: "other" });
  await action("validate-image");
  assert.equal(calls.length, 0);
  assert.match(nodes["word-task-vision-status"].textContent, /请先确认/);
});

test("catalog confirm validates before save and manual save does not", async () => {
  const calls = [];
  const nodes = {
    "word-task-model-validation-status": { textContent: "" },
    "word-task-vision-status": { textContent: "" },
    "word-task-model-select": { value: "catalog-model" },
    "word-task-direct-service-select": { value: "direct_svc_1" },
    "word-task-temperature": { value: "" },
    "word-task-max-output": { value: "" },
    "word-task-context": { value: "" }
  };
  const service = {
    id: "direct_svc_1",
    defaultModel: "catalog-model",
    modelList: ["catalog-model"],
    customModels: ["hand-model"],
    modelCatalog: { usableForSelection: true, models: ["catalog-model"] }
  };
  const ctx = {
    state: { taskModelSelections: { "word.format_review": { serviceId: "direct_svc_1", modelName: "old" } }, workflowProfileSelections: {}, taskApiKeys: {} },
    helpers,
    TASK_API_KEY_DEFS: [{ taskType: "word.format_review", label: "格式审查" }],
    byId: id => nodes[id] || null,
    getSettingsWorkflowTaskType: () => "word.format_review",
    findDirectService: () => service,
    setWorkflowProfileMutationBusy() {},
    setStatus() {},
    describeFetchError: error => error.message,
    loadWorkflowProfiles: async () => {},
    loadDirectServices: async () => {},
    request: async (route, payload) => {
      calls.push({ route, payload });
      if (route.endsWith("/validate") && payload.modelName === "catalog-model" && calls.filter(item => item.route.endsWith("/validate")).length === 1) {
        throw new Error("协议未通过");
      }
      return { data: { taskModelSelection: { serviceId: "direct_svc_1", modelName: payload.modelName || payload.taskModelSelection && payload.taskModelSelection.modelName } } };
    }
  };
  ctx.getTaskModelSelectionDraft = loadFn("getTaskModelSelectionDraft", ctx);
  ctx.formatReviewSelectionBinding = loadFn("formatReviewSelectionBinding", ctx);
  ctx.formatReviewUsesCatalogConfirm = loadFn("formatReviewUsesCatalogConfirm", ctx);
  const save = loadFn("saveTaskModelSelection", ctx);
  await save();
  assert.equal(calls.some(item => item.route.endsWith("/activate")), false);
  assert.match(nodes["word-task-model-validation-status"].textContent, /协议未通过/);

  calls.length = 0;
  ctx.request = async (route, payload) => {
    calls.push(route);
    return { data: { taskModelSelection: { serviceId: "direct_svc_1", modelName: "catalog-model", imageSemanticValidation: { validated: false, message: "识图失败" } } } };
  };
  await save();
  assert.deepEqual(calls.slice(0, 3), [
    "/provider/task-model-selections/word.format_review/validate",
    "/provider/task-model-selections/word.format_review/validate-image",
    "/provider/direct-services/direct_svc_1/activate"
  ]);

  calls.length = 0;
  nodes["word-task-model-select"].value = "hand-model";
  let activateSeen = false;
  ctx.request = async (route) => {
    calls.push(route);
    if (route.endsWith("/activate")) activateSeen = true;
    if (!activateSeen) throw new Error("probe before save");
    return { data: { taskModelSelection: { serviceId: "direct_svc_1", modelName: "hand-model" } } };
  };
  await save();
  assert.equal(calls[0], "/provider/direct-services/direct_svc_1/activate");
});

test("image buttons bind only the vision check", () => {
  const listeners = {};
  const calls = [];
  const ctx = { helpers, byId: id => ({ addEventListener: (event, fn) => { listeners[id] = fn; } }),
    performTaskImageAction: (...args) => calls.push(args) };
  for (const name of ["handleDirectServiceAction", "closeDirectServiceEditor", "saveDirectServiceEditor", "refreshDirectServiceModelsInEditor", "validateDirectServiceInEditor", "clearDirectServiceKey", "confirmDirectServiceDelete", "closeDirectServiceDeleteDialog", "handleDirectServiceEditorInput", "handleTaskDirectServiceChange", "handleTaskCustomModelChange", "validateTaskModelSelection", "saveTaskModelSelection"]) ctx[name] = () => {};
  const source = functionSource("bindDirectServiceEvents");
  for (const match of source.matchAll(/:\s*(\w+),/g)) if (!(match[1] in ctx)) ctx[match[1]] = () => {};
  loadFn("bindDirectServiceEvents", ctx)();
  assert.equal(listeners["btn-authorize-task-images"], undefined);
  assert.equal(listeners["btn-revoke-task-images"], undefined);
  listeners["btn-validate-task-images"]();
  assert.deepEqual(calls, [[]]);
});

test("real format submission reaches background jobs when semantic validation is pending", async () => {
  const selection = { serviceId: 'direct_svc_1', modelName: 'vision', modelAvailable: true,
    formatSemanticReadiness: { code: 'validation_required' }, imageSemanticReadiness: { code: 'authorization_required' } };
  const service = { id: 'direct_svc_1', defaultModel: 'vision', keyConfigured: true, modelList: ['vision'],
    modelCatalog: { usableForSelection: true, status: 'fresh', models: ['vision'] } };
  const calls = [];
  let complete;
  const completed = new Promise(resolve => { complete = resolve; });
  const noop = () => {};
  const ctx = { helpers: { ...helpers, getDocumentSessionId: () => 'doc-1', getDocumentDisplayName: () => 'test.docx', buildDeterministicFormatReviewBatches: () => [] },
    state: { deterministicFormatReviewEnabled: true, activeTaskSlots: {}, taskModelSelections: { 'word.format_review': selection },
      taskApiKeys: { 'word.format_review': { accessMethod: 'direct_model', activeProfileId: service.id } } },
    findDirectService: () => service, getActiveDocument: () => ({}), resolveSelectionScope: () => ({ ok: true }),
    setStatus: noop, setPlainResult: noop, setResult: message => complete(new Error(message)), setActiveResultRecord: noop, switchWordHistoryView: noop,
    clearDeterministicFormatReviewPresentation: noop, clearDeterministicFormatReviewActiveJob: noop, setModelTaskBusy: noop,
    setTimeout, DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS: 1000,
    extractDeterministicFormatReviewSnapshot: () => ({ blocks: [], contentSha256: 'c', structureSha256: 's', formatSha256: 'f', documentIdentity: {}, coverage: {}, editSequence: '1' }),
    ensureDeterministicFormatReviewPreparation: noop, setTrace: noop, uploadDeterministicFormatReviewBatches: async () => {},
    exportDeterministicFormatReviewImageGroups: async () => {}, saveDeterministicFormatReviewActiveJob: noop,
    setActiveReviewJobRecord: noop, setDocumentReviewCancelVisible: noop, pollDeterministicFormatReviewJob: () => complete(),
    cleanupDeterministicFormatReviewTerminal: noop, discardDeterministicFormatReviewSnapshot: noop, describeFetchError: error => error.message,
    request: async route => { calls.push(route); return { data: { snapshotId: 'snapshot-1', snapshotToken: 'token', jobId: 'job-1' } }; }
  };
  ctx.validateActiveDirectTaskSelection = loadFn('validateActiveDirectTaskSelection', ctx);
  loadFn('runDeterministicFormatReview', ctx)();
  const error = await completed;
  assert.equal(error, undefined);
  assert.ok(calls.includes('/word/format-review/jobs'));
  assert.equal(ctx.state.deterministicFormatReviewJobId, 'job-1');
});


function savedManualProbeHarness(inherit = false) {
  const nodes = Object.fromEntries([
    "word-task-direct-service-section", "word-task-direct-service-title", "word-task-direct-params",
    "word-task-model-cost-warning", "word-task-model-validation-status", "word-task-image-mode-row",
    "word-task-vision-status", "btn-validate-task-model-selection"
  ].map(id => [id, { textContent: "", hidden: false }]));
  Object.assign(nodes, {
    "word-task-direct-service-select": { value: "direct_svc_1" },
    "word-task-model-select": { value: inherit ? "" : "hand-model" },
    "word-task-temperature": { value: "0.2" },
    "word-task-max-output": { value: "2048" },
    "word-task-context": { value: "32000" }
  });
  const service = { id: "direct_svc_1", name: "测试服务", revision: 3,
    serviceBaseUrl: "https://example.com/v1", defaultModel: "hand-model",
    modelList: ["catalog-model"], customModels: ["hand-model"] };
  const probes = [];
  const calls = [];
  const ctx = {
    state: { settingsWorkflowTaskType: "word.format_review", directServices: [service],
      taskModelSelections: {}, workflowProfileSelections: {}, taskApiKeys: {}, workflowProfiles: {} },
    helpers,
    TASK_API_KEY_DEFS: [{ taskType: "word.format_review", label: "格式审查" }],
    byId: id => nodes[id] || null,
    getSettingsWorkflowTaskType: () => ctx.state.settingsWorkflowTaskType,
    findDirectService: id => ctx.state.directServices.find(item => item.id === id),
    escapeWorkflowText: value => value || "",
    setWorkflowProfileMutationBusy: value => { ctx.state.workflowProfileMutationBusy = value; },
    setStatus() {},
    describeFetchError: error => error.message,
    loadWorkflowProfiles: async () => {},
    loadDirectServices: async () => { ctx.renderTaskModelSelectionSection(); },
    request: (route, payload) => {
      calls.push(route);
      if (route.endsWith("/activate")) {
        return Promise.resolve({ data: { taskModelSelection: { ...payload.taskModelSelection,
          taskType: "word.format_review" } } });
      }
      return new Promise((resolve, reject) => probes.push({ route, resolve, reject }));
    }
  };
  for (const name of ["formatReviewSelectionBinding", "getWorkflowProfileData", "getTaskModelSelectionDraft", "formatReviewVisionStatusText",
    "formatReviewUsesCatalogConfirm", "renderTaskModelSelectionSection", "saveTaskModelSelection"])
    ctx[name] = loadFn(name, ctx);
  return { ctx, nodes, probes, calls, service };
}

const flushProbeCallbacks = () => new Promise(resolve => setImmediate(resolve));

for (const inherit of [false, true]) {
  test(`saved ${inherit ? "inherited" : "explicit"} manual model remains usable while both automatic probes run`, async () => {
    const { ctx, nodes, probes, calls } = savedManualProbeHarness(inherit);
    await ctx.saveTaskModelSelection();
    assert.equal(calls[0], "/provider/direct-services/direct_svc_1/activate");
    assert.equal(ctx.state.taskApiKeys["word.format_review"].configured, true);
    assert.equal(ctx.state.workflowProfileMutationBusy, false);
    assert.equal(probes.length, 2, "the real save function must launch both background probes");
    assert.match(nodes["word-task-model-validation-status"].textContent, /正在.*语义/);
    assert.match(nodes["word-task-vision-status"].textContent, /正在.*视觉/);
    probes[1].resolve({ data: { taskModelSelection: { imageSemanticValidation: { validated: true, stale: false } } } });
    await flushProbeCallbacks();
    assert.match(nodes["word-task-vision-status"].textContent, /验证成功/);
    probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false }, customModelValidated: true } });
    await flushProbeCallbacks();
    const selection = ctx.state.taskModelSelections["word.format_review"];
    assert.equal(selection.formatSemanticValidation.success, true);
    assert.equal(selection.imageSemanticValidation.validated, true, "semantic response must preserve visual evidence");
    ctx.renderTaskModelSelectionSection();
    assert.match(nodes["word-task-model-validation-status"].textContent, /语义.*成功/);
    assert.match(nodes["word-task-vision-status"].textContent, /视觉.*成功/);
  });
}

test("automatic probe failures retain the saved choice and expose each specific failure", async () => {
  const { ctx, nodes, probes } = savedManualProbeHarness();
  await ctx.saveTaskModelSelection();
  probes[0].reject(new Error("语义返回了非协议内容"));
  probes[1].reject(new Error("模型不支持图片输入"));
  await flushProbeCallbacks();
  assert.match(nodes["word-task-model-validation-status"].textContent, /语义返回了非协议内容/);
  assert.match(nodes["word-task-vision-status"].textContent, /模型不支持图片输入/);
  const selection = ctx.state.taskModelSelections["word.format_review"];
  assert.equal(selection.formatSemanticValidation.success, false);
  assert.equal(selection.imageSemanticValidation.validated, false);
  assert.equal(selection.modelName, "hand-model");
  assert.equal(ctx.state.taskApiKeys["word.format_review"].configured, true);
  assert.equal(ctx.state.workflowProfileMutationBusy, false);
});

for (const outcome of ["success", "failure"]) {
  for (const change of ["task", "draft", "service", "save"]) {
    test(`old automatic ${outcome} cannot overwrite state after changing ${change}`, async () => {
      const { ctx, nodes, probes, service } = savedManualProbeHarness();
      await ctx.saveTaskModelSelection();
      if (change === "task") ctx.state.settingsWorkflowTaskType = "word.smart_write";
      if (change === "draft") nodes["word-task-temperature"].value = "0.8";
      if (change === "service") service.revision += 1;
      if (change === "save") await ctx.saveTaskModelSelection();
      nodes["word-task-model-validation-status"].textContent = "当前语义状态";
      nodes["word-task-vision-status"].textContent = "当前视觉状态";
      const before = JSON.stringify(ctx.state.taskModelSelections);
      if (outcome === "success") {
        probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
        probes[1].resolve({ data: { taskModelSelection: { imageSemanticValidation: { validated: true, stale: false } } } });
      } else {
        probes[0].reject(new Error("过期语义错误"));
        probes[1].reject(new Error("过期视觉错误"));
      }
      await flushProbeCallbacks();
      assert.equal(nodes["word-task-model-validation-status"].textContent, "当前语义状态");
      assert.equal(nodes["word-task-vision-status"].textContent, "当前视觉状态");
      assert.equal(JSON.stringify(ctx.state.taskModelSelections), before);
      assert.equal(nodes["word-task-temperature"].value, change === "draft" ? "0.8" : 0.2);
    });
  }
}


test("automatic responses preserve other unsaved draft fields without refreshing the form", async () => {
  const { ctx, nodes, probes } = savedManualProbeHarness();
  await ctx.saveTaskModelSelection();
  nodes["word-task-max-output"].value = "4096";
  nodes["word-task-context"].value = "64000";
  probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
  probes[1].resolve({ data: { taskModelSelection: { imageSemanticValidation: { validated: true, stale: false } } } });
  await flushProbeCallbacks();
  assert.equal(nodes["word-task-max-output"].value, "4096");
  assert.equal(nodes["word-task-context"].value, "64000");
  assert.equal(ctx.state.taskModelSelections["word.format_review"].maxOutputTokens, 2048);
});

test("changing a parameter back still supersedes automatic probes through real input handlers", async () => {
  const { ctx, nodes, probes } = savedManualProbeHarness();
  const listeners = {};
  for (const [id, node] of Object.entries(nodes)) node.addEventListener = (event, fn) => { listeners[id + ":" + event] = fn; };
  const source = functionSource("bindDirectServiceEvents");
  for (const match of source.matchAll(/:\s*(\w+),/g)) if (!(match[1] in ctx)) ctx[match[1]] = () => {};
  loadFn("bindDirectServiceEvents", ctx)();
  await ctx.saveTaskModelSelection();
  nodes["word-task-temperature"].value = "0.8";
  listeners["word-task-temperature:input"]();
  nodes["word-task-temperature"].value = "0.2";
  listeners["word-task-temperature:input"]();
  probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
  probes[1].reject(new Error("旧视觉失败"));
  await flushProbeCallbacks();
  assert.match(nodes["word-task-model-validation-status"].textContent, /参数已修改/);
  assert.equal(nodes["word-task-vision-status"].textContent, "未验证");
  assert.notEqual(ctx.state.taskModelSelections["word.format_review"].formatSemanticValidation.success, true);
});

test("first activation accepts probe results after the real service refresh adds task references", async () => {
  const { ctx, nodes, probes, service } = savedManualProbeHarness();
  const request = ctx.request;
  let savedSelection;
  ctx.request = (route, payload) => {
    if (route === "/provider/direct-services") return Promise.resolve({ data: {
      directServices: [{ ...service, referencedTasks: ["word.format_review"], taskModelSelections: [JSON.parse(JSON.stringify(savedSelection))] }]
    } });
    if (route === "/provider/task-model-selections?host=word") return Promise.resolve({ data: { taskModelSelections: [savedSelection] } });
    if (route.endsWith("/activate")) savedSelection = { ...payload.taskModelSelection, taskType: "word.format_review" };
    return request(route, payload);
  };
  for (const name of ["renderDirectServicesList", "renderWorkflowProfileStrip", "renderWorkflowProfileManager"]) ctx[name] = () => {};
  ctx.loadDirectServices = loadFn("loadDirectServices", ctx);
  await ctx.saveTaskModelSelection();
  probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
  probes[1].resolve({ data: { taskModelSelection: { imageSemanticValidation: { validated: true, stale: false } } } });
  await flushProbeCallbacks();
  assert.equal(ctx.state.taskModelSelections["word.format_review"].formatSemanticValidation.success, true);
  assert.equal(ctx.state.taskModelSelections["word.format_review"].imageSemanticValidation.validated, true);
  assert.match(nodes["word-task-vision-status"].textContent, /视觉.*成功/);
});

for (const semanticOutcome of ["success", "failure"]) {
  for (const first of ["semantic", "manual"]) {
    test(`manual vision only supersedes visual probes: semantic ${semanticOutcome}, ${first} finishes first`, async () => {
      const { ctx, nodes, probes } = savedManualProbeHarness();
      await ctx.saveTaskModelSelection();
      const saved = ctx.state.taskModelSelections["word.format_review"];
      const manualResponse = { ...saved,
        formatSemanticValidation: { success: false, stale: false, message: "响应中的旧语义记录" },
        imageSemanticValidation: { validated: true, stale: false, message: "manual vision" } };
      const manual = loadFn("performTaskImageAction", ctx)();
      assert.equal(probes.length, 3);
      async function finishSemantic() {
        if (semanticOutcome === "success") probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
        else probes[0].reject(new Error("本次语义协议失败"));
        await flushProbeCallbacks();
      }
      async function finishManual() {
        probes[2].resolve({ data: { taskModelSelection: manualResponse } });
        await manual;
      }
      if (first === "manual") {
        await finishManual();
        assert.equal(ctx.state.taskModelSelections["word.format_review"].formatSemanticValidation.pending, true,
          "manual visual response must preserve ongoing semantic validation");
        await finishSemantic();
      } else {
        await finishSemantic();
        await finishManual();
      }
      probes[1].reject(new Error("旧视觉错误"));
      await flushProbeCallbacks();
      const selection = ctx.state.taskModelSelections["word.format_review"];
      assert.equal(selection.imageSemanticValidation.message, "manual vision");
      assert.equal(selection.formatSemanticValidation.success, semanticOutcome === "success");
      assert.match(nodes["word-task-model-validation-status"].textContent,
        semanticOutcome === "success" ? /语义.*成功/ : /本次语义协议失败/);
      assert.match(nodes["word-task-vision-status"].textContent, /视觉.*成功/);
      ctx.renderTaskModelSelectionSection();
      assert.match(nodes["word-task-model-validation-status"].textContent,
        semanticOutcome === "success" ? /语义.*成功/ : /本次语义协议失败/);
      assert.equal(ctx.state.workflowProfileMutationBusy, false);
    });
  }
}

test("switching to another task and back supersedes both automatic responses", async () => {
  const { ctx, nodes, probes } = savedManualProbeHarness();
  for (const name of ["syncSettingsRefreshController", "renderWorkflowTaskTabs", "renderWorkflowProfileManager"]) ctx[name] = () => {};
  ctx.confirmWorkflowEditorDiscard = () => true;
  const switchTask = loadFn("handleWorkflowTaskTabClick", ctx);
  await ctx.saveTaskModelSelection();
  switchTask({ target: { getAttribute: () => "word.smart_write" } });
  switchTask({ target: { getAttribute: () => "word.format_review" } });
  probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
  probes[1].reject(new Error("切换前的视觉失败"));
  await flushProbeCallbacks();
  assert.equal(nodes["word-task-model-validation-status"].textContent, "");
  assert.equal(nodes["word-task-vision-status"].textContent, "未验证");
  assert.notEqual(ctx.state.taskModelSelections["word.format_review"].formatSemanticValidation.success, true);
});


test("real busy/controller refresh preserves in-flight probes across replacement of the same saved configuration", async () => {
  const { ctx, nodes, probes, service } = savedManualProbeHarness();
  const request = ctx.request;
  let persisted;
  let refreshCount = 0;
  const clone = value => JSON.parse(JSON.stringify(value));
  nodes["settings-view"] = { classList: { contains: () => true } };
  ctx.document = { visibilityState: "visible" };
  ctx.state.writingPolicyView = "home";
  ctx.state.configRefreshRequestId = 0;
  ctx.SETTINGS_REFRESH_REQUEST_TIMEOUT_MS = 1000;
  ctx.readAdapterJson = async route => route === "/templates" ? { data: { templates: [] } } : { data: {} };
  ctx.applyAdapterHealthState = () => ({ status: "ready" });
  ctx.mergeTemplates = items => items;
  ctx.refreshAllWorkflowProfiles = async () => [{}];
  ctx.request = (route, payload) => {
    if (route === "/health") { refreshCount += 1; return Promise.resolve({ data: {} }); }
    if (route === "/provider/direct-services") return Promise.resolve({ data: { directServices: [clone(service)] } });
    if (route === "/provider/task-model-selections?host=word") return Promise.resolve({ data: { taskModelSelections: [clone(persisted)] } });
    if (route.endsWith("/activate")) persisted = { ...payload.taskModelSelection, taskType: "word.format_review" };
    return request(route, payload);
  };
  for (const name of ["renderDirectServicesList", "renderWorkflowProfileStrip", "renderWorkflowProfileManager",
    "renderWorkflowTaskTabs", "syncWorkflowProfileManagerBusyState", "setSettingsStatus", "setProviderLine",
    "applyProviderConfig", "renderTemplateOptions", "renderModelInterfaceState"]) ctx[name] = () => {};
  for (const name of ["loadDirectServices", "setWorkflowProfileMutationBusy", "syncSettingsRefreshController", "refreshConfig",
    "isSettingsRefreshEligible", "invalidateConfigRefresh"]) ctx[name] = loadFn(name, ctx);
  ctx.state.settingsRefreshController = helpers.createSettingsRefreshController({
    refresh: () => ctx.refreshConfig({ silent: true }), setIntervalFn: () => 1, clearIntervalFn() {}
  });
  await ctx.saveTaskModelSelection();
  const activatedObject = ctx.state.taskModelSelections["word.format_review"];
  await flushProbeCallbacks();
  assert.equal(refreshCount, 1, "releasing the real busy state starts the real refresh controller");
  assert.notEqual(ctx.state.taskModelSelections["word.format_review"], activatedObject, "the real list refresh replaces the selection object");
  assert.match(nodes["word-task-model-validation-status"].textContent, /正在.*语义/);
  assert.match(nodes["word-task-vision-status"].textContent, /正在.*视觉/);
  probes[0].resolve({ data: { formatSemanticValidation: { success: true, stale: false } } });
  probes[1].resolve({ data: { taskModelSelection: { imageSemanticValidation: { validated: true, stale: false } } } });
  await flushProbeCallbacks();
  assert.equal(ctx.state.taskModelSelections["word.format_review"].formatSemanticValidation.success, true);
  assert.equal(ctx.state.taskModelSelections["word.format_review"].imageSemanticValidation.validated, true);
  assert.match(nodes["word-task-model-validation-status"].textContent, /语义.*成功/);
  assert.match(nodes["word-task-vision-status"].textContent, /视觉.*成功/);
});
