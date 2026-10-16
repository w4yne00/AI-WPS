const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const wordRoot = path.join(__dirname, "../wps-ai-assistant_1.0.0");
const excelRoot = path.join(__dirname, "../wps-ai-assistant-et_1.0.0");
const pptRoot = path.join(__dirname, "../wps-ai-assistant-wpp_1.0.0");

test("Word taskpane: renderTaskModelSelectionSection hides validate button for smart_write and smart_imitation", () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function renderTaskModelSelectionSection(");
  const end = js.indexOf("\n  function ", start + 1);
  assert.ok(start > 0 && end > start, "renderTaskModelSelectionSection function must exist");

  const elements = {};
  function getEl(id) {
    if (!elements[id]) {
      elements[id] = { id, hidden: false, textContent: "", value: "", placeholder: "", innerHTML: "" };
    }
    return elements[id];
  }

  const tasksToTest = [
    { task: "word.smart_write", expectedHidden: true },
    { task: "word.smart_imitation", expectedHidden: true },
    { task: "word.format_review", expectedHidden: false },
    { task: "word.document_review", expectedHidden: false },
  ];

  for (const { task, expectedHidden } of tasksToTest) {
    elements["btn-validate-task-model-selection"] = { id: "btn-validate-task-model-selection", hidden: !expectedHidden };
    const context = {
      state: { workflowProfileSelections: {}, taskModelSelections: {} },
      getWorkflowProfileData: () => ({ activeProfileId: "direct_svc_1" }),
      byId: getEl,
      getSettingsWorkflowTaskType: () => task,
      findDirectService: () => ({ id: "svc_1", name: "Test Svc", modelList: ["gpt-4o"], defaultModel: "gpt-4o" }),
      helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
      renderCustomModelsList: () => {},
      escapeWorkflowText: s => s,
    };

    const render = vm.runInNewContext(`(${js.slice(start, end)})`, context);
    render(task);

    const btn = getEl("btn-validate-task-model-selection");
    assert.strictEqual(
      btn.hidden,
      expectedHidden,
      `For task ${task}, btn-validate-task-model-selection hidden should be ${expectedHidden}`
    );
  }
});

test("Word taskpane: catalog model save validates first and aborts on validation failure", async () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function saveTaskModelSelection(");
  const end = js.indexOf("\n  function ", start + 1);

  const taskType = "word.smart_write";
  const saved = { serviceId: "svc_old", modelName: "old-model", customModel: false };
  const draft = { serviceId: "svc_1", modelName: "gpt-4o", customModel: false };
  const state = { taskModelSelections: { [taskType]: saved }, taskApiKeys: {}, workflowProfileSelections: {} };
  const status = { textContent: "" };
  const requests = [];

  const context = {
    state,
    helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
    getTaskModelSelectionDraft: () => draft,
    getSettingsWorkflowTaskType: () => taskType,
    findDirectService: () => ({ id: "svc_1", defaultModel: "gpt-4o", modelList: ["gpt-4o"], keyConfigured: true }),
    byId: id => (id.endsWith("-model-select") ? { value: "gpt-4o" } : status),
    setStatus: msg => { status.textContent = msg; },
    setWorkflowMutationBusy() {},
    setWorkflowProfileMutationBusy() {},
    loadWorkflowProfiles: async () => {},
    loadProfiles: async () => {},
    loadDirectServices: async () => {},
    describeFetchError: error => error.message,
    TASK_API_KEY_DEFS: [],
    request: async (url, body) => {
      requests.push({ url, body });
      if (url.includes("/validate")) {
        const err = new Error("Provider authentication failed");
        err.status = 401;
        throw err;
      }
      return { data: { taskModelSelection: { ...body.taskModelSelection } } };
    }
  };

  const save = vm.runInNewContext(`(${js.slice(start, end)})`, context);
  await save();

  // Validate was called
  const valReq = requests.find(r => r.url.includes("/validate"));
  assert.ok(valReq, "Must call /validate before saving catalog model");

  // Activate was NOT called
  const actReq = requests.find(r => r.url.includes("/activate"));
  assert.strictEqual(actReq, undefined, "Must NOT call /activate when validation fails");

  // State preserved
  assert.strictEqual(state.taskModelSelections[taskType], saved, "Original selection must be preserved");
  assert.match(status.textContent, /验证失败/, "Error status must be displayed");
});

test("Word taskpane: catalog model save activates after successful validation", async () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function saveTaskModelSelection(");
  const end = js.indexOf("\n  function ", start + 1);

  const taskType = "word.smart_write";
  const saved = { serviceId: "svc_old", modelName: "old-model", customModel: false };
  const draft = { serviceId: "svc_1", modelName: "gpt-4o", customModel: false };
  const state = { taskModelSelections: { [taskType]: saved }, taskApiKeys: {}, workflowProfileSelections: {} };
  const status = { textContent: "" };
  const requests = [];

  const context = {
    state,
    helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
    getTaskModelSelectionDraft: () => draft,
    getSettingsWorkflowTaskType: () => taskType,
    findDirectService: () => ({ id: "svc_1", defaultModel: "gpt-4o", modelList: ["gpt-4o"], keyConfigured: true }),
    byId: id => (id.endsWith("-model-select") ? { value: "gpt-4o" } : status),
    setStatus: msg => { status.textContent = msg; },
    setWorkflowMutationBusy() {},
    setWorkflowProfileMutationBusy() {},
    loadWorkflowProfiles: async () => {},
    loadProfiles: async () => {},
    loadDirectServices: async () => {},
    describeFetchError: error => error.message,
    TASK_API_KEY_DEFS: [{ taskType, label: "智能编写" }],
    request: async (url, body) => {
      requests.push({ url, body });
      if (url.includes("/validate")) {
        return { data: { validation: { success: true, streamingCapability: "validated" } } };
      }
      return { data: { taskModelSelection: { serviceId: "svc_1", modelName: "gpt-4o", customModel: false } } };
    }
  };

  const save = vm.runInNewContext(`(${js.slice(start, end)})`, context);
  await save();

  // Validate was called first, then activate
  assert.strictEqual(requests.length >= 2, true);
  assert.ok(requests[0].url.includes("/validate"), "First request must be /validate");
  assert.ok(requests[1].url.includes("/activate"), "Second request must be /activate");

  // Activated state updated
  assert.strictEqual(state.taskModelSelections[taskType].serviceId, "svc_1");
  assert.strictEqual(state.taskModelSelections[taskType].modelName, "gpt-4o");
  assert.match(status.textContent, /设为当前/, "Status should show saved/active");
});

test("Word taskpane: manual model save activates immediately and probes in background", async () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function saveTaskModelSelection(");
  const end = js.indexOf("\n  function ", start + 1);

  const taskType = "word.smart_imitation";
  const draft = { serviceId: "svc_1", modelName: "my-custom-model", customModel: true };
  const state = { taskModelSelections: {}, taskApiKeys: {}, workflowProfileSelections: {} };
  const status = { textContent: "" };
  const requests = [];

  let probeResolve;
  const probePromise = new Promise(resolve => { probeResolve = resolve; });

  const context = {
    state,
    helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
    getTaskModelSelectionDraft: () => draft,
    getSettingsWorkflowTaskType: () => taskType,
    findDirectService: () => ({ id: "svc_1", defaultModel: "", customModels: ["my-custom-model"], keyConfigured: true }),
    byId: id => (id.endsWith("-model-select") ? { value: "my-custom-model" } : status),
    setStatus: msg => { status.textContent = msg; },
    setWorkflowMutationBusy() {},
    setWorkflowProfileMutationBusy() {},
    loadWorkflowProfiles: async () => {},
    loadProfiles: async () => {},
    loadDirectServices: async () => {},
    describeFetchError: error => error.message,
    TASK_API_KEY_DEFS: [{ taskType, label: "智能仿写" }],
    request: async (url, body) => {
      requests.push({ url, body });
      if (url.includes("/activate")) {
        return { data: { taskModelSelection: { serviceId: "svc_1", modelName: "my-custom-model", customModel: true } } };
      }
      if (url.includes("/validate")) {
        probeResolve();
        return { data: { validation: { success: true, streamingCapability: "validated" } } };
      }
      return {};
    }
  };

  const save = vm.runInNewContext(`(${js.slice(start, end)})`, context);
  await save();

  // First request must be activate!
  assert.ok(requests[0].url.includes("/activate"), "Manual model must activate immediately");
  assert.strictEqual(state.taskModelSelections[taskType].modelName, "my-custom-model");

  // Wait for background probe
  await probePromise;
  const valReq = requests.find(r => r.url.includes("/validate"));
  assert.ok(valReq, "Background probe must be launched");
});

test("Word taskpane: manual model background probe failure does NOT rollback saved selection", async () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function saveTaskModelSelection(");
  const end = js.indexOf("\n  function ", start + 1);

  const taskType = "word.smart_write";
  const draft = { serviceId: "svc_1", modelName: "unsupported-stream-model", customModel: true };
  const state = { taskModelSelections: {}, taskApiKeys: {}, workflowProfileSelections: {} };
  const status = { textContent: "" };
  const requests = [];

  let probeReject;
  const probePromise = new Promise((_, reject) => { probeReject = reject; });

  const context = {
    state,
    helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
    getTaskModelSelectionDraft: () => draft,
    getSettingsWorkflowTaskType: () => taskType,
    findDirectService: () => ({ id: "svc_1", defaultModel: "", customModels: ["unsupported-stream-model"], keyConfigured: true }),
    byId: id => (id.endsWith("-model-select") ? { value: "unsupported-stream-model" } : status),
    setStatus: msg => { status.textContent = msg; },
    setWorkflowMutationBusy() {},
    setWorkflowProfileMutationBusy() {},
    loadWorkflowProfiles: async () => {},
    loadProfiles: async () => {},
    loadDirectServices: async () => {},
    describeFetchError: error => error.message,
    TASK_API_KEY_DEFS: [{ taskType, label: "智能编写" }],
    request: async (url, body) => {
      requests.push({ url, body });
      if (url.includes("/activate")) {
        return { data: { taskModelSelection: { serviceId: "svc_1", modelName: "unsupported-stream-model", customModel: true } } };
      }
      if (url.includes("/validate")) {
        const err = new Error("Streaming not supported");
        probeReject(err);
        throw err;
      }
      return {};
    }
  };

  const save = vm.runInNewContext(`(${js.slice(start, end)})`, context);
  await save();

  // Activate succeeded
  assert.strictEqual(state.taskModelSelections[taskType].modelName, "unsupported-stream-model");

  // Wait for probe to fail
  try { await probePromise; } catch (e) {}

  // Selection must still be preserved!
  assert.strictEqual(state.taskModelSelections[taskType].modelName, "unsupported-stream-model");
  assert.match(status.textContent, /普通调用|已保存/, "Status should reflect saved state with fallback notice");
});

test("Excel and PPT: validate button remains visible and unchanged", () => {
  for (const [host, root] of [["excel", excelRoot], ["ppt", pptRoot]]) {
    const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
    assert.match(
      html,
      /btn-validate-task-model-selection/,
      `${host} taskpane.html must retain btn-validate-task-model-selection`
    );
  }
});
