const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const wordRoot = path.join(__dirname, "../wps-ai-assistant_1.0.0");
const excelRoot = path.join(__dirname, "../wps-ai-assistant-et_1.0.0");
const pptRoot = path.join(__dirname, "../wps-ai-assistant-wpp_1.0.0");

test("Word taskpane: renderTaskModelSelectionSection hides validate button for all three automatic-validation tasks", () => {
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
    { task: "word.format_review", expectedHidden: true },
    { task: "word.document_review", expectedHidden: false },
    { task: "word.material_composer", expectedHidden: false },
  ];

  for (const { task, expectedHidden } of tasksToTest) {
    for (const activeProfileId of ["direct_svc_1", ""]) {
      elements["btn-validate-task-model-selection"] = { id: "btn-validate-task-model-selection", hidden: !expectedHidden };
      const context = {
        state: { workflowProfileSelections: {}, taskModelSelections: {} },
        getWorkflowProfileData: () => ({ activeProfileId }),
        byId: getEl,
        getSettingsWorkflowTaskType: () => task,
        findDirectService: () => ({ id: "svc_1", name: "Test Svc", modelList: ["gpt-4o"], defaultModel: "gpt-4o" }),
        helpers: require(path.join(wordRoot, "taskpane-helpers.js")),
        renderCustomModelsList: () => {},
        escapeWorkflowText: s => s,
        formatReviewVisionStatusText: () => "",
      };

      const render = vm.runInNewContext(`(${js.slice(start, end)})`, context);
      render(task);

      const btn = getEl("btn-validate-task-model-selection");
      assert.strictEqual(
        btn.hidden,
        expectedHidden,
        `For task ${task}, btn-validate-task-model-selection hidden should be ${expectedHidden}, active profile ${activeProfileId}`
      );
    }
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

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function confirmationPane(taskType, manual = false) {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const service = { id: "direct_svc_new", name: "新服务", keyConfigured: true,
    defaultModel: manual ? "manual-model" : "catalog-model", modelList: ["catalog-model"],
    customModels: manual ? ["manual-model"] : [] };
  const saved = { serviceId: "direct_svc_old", modelName: "old-model" };
  const draft = { serviceId: service.id, modelName: "", customModel: false };
  const state = { taskModelSelections: { [taskType]: saved }, taskApiKeys: {},
    workflowProfileSelections: { [taskType]: saved.serviceId }, taskModelConfigStatusByTask: {} };
  const status = { textContent: "" };
  const probe = deferred();
  const calls = [];
  let currentTask = taskType;
  const ctx = {
    state, helpers: require(path.join(wordRoot, "taskpane-helpers.js")), TASK_API_KEY_DEFS: [],
    getTaskModelSelectionDraft: () => ({ ...draft }),
    getSettingsWorkflowTaskType: () => currentTask, getCurrentWorkflowTaskType: () => currentTask,
    findDirectService: () => service, getWorkflowProfileData: () => ({ activeProfileId: saved.serviceId }),
    getWorkflowProfileById: () => ({ complete: true }), isWorkflowInteractionBlocked: () => false,
    byId: id => id.endsWith("-model-select") ? { value: draft.modelName } : status,
    setWorkflowProfileMutationBusy: busy => { state.workflowProfileMutationBusy = busy; },
    loadWorkflowProfiles: async () => {}, loadDirectServices: async () => {},
    renderWorkflowProfileStrip() {}, renderWorkflowTaskTabs() {}, renderWorkflowProfileManager() {},
    renderTaskModelSelectionSection() {}, renderModelInterfaceState() {}, focusTaskModelConfigTrigger() {},
    setNodeTextIfChanged: (node, text) => { node.textContent = text; },
    setStatus: text => { status.textContent = text; }, describeFetchError: error => error.message,
    request: async (url, body) => {
      calls.push(url);
      if (url.endsWith("/validate")) return probe.promise;
      return { data: { taskModelSelection: { ...body.taskModelSelection } } };
    }
  };
  for (const name of ["formatReviewUsesCatalogConfirm", "saveTaskModelSelection", "activateWorkflowProfile"]) {
    const start = js.indexOf("  function " + name + "(");
    const end = js.indexOf("\n  function ", start + 1);
    ctx[name] = vm.runInNewContext("(" + js.slice(start, end) + ")", ctx);
  }
  return { ...ctx, context: ctx, draft, service, saved, status, calls, probe,
    switchTask: task => { currentTask = task; } };
}

for (const taskType of ["word.smart_write", "word.smart_imitation", "word.format_review"]) {
  for (const fail of [false, true]) {
    test(`${taskType} settings validation ${fail ? "failure" : "success"} releases busy after leaving the task`, async () => {
      const p = confirmationPane(taskType);
      const pending = p.saveTaskModelSelection();
      p.switchTask("word.document_review");
      p.status.textContent = "另一个任务";
      if (fail) p.probe.reject(new Error("旧验证失败"));
      else p.probe.resolve({ data: { success: true, streamingCapability: "validated" } });
      await pending;
      assert.strictEqual(p.state.workflowProfileMutationBusy, false);
      assert.strictEqual(p.calls.length, 1, "leaving the task must not activate its old draft or start another probe");
      assert.strictEqual(p.state.taskModelSelections[taskType], p.saved);
      assert.strictEqual(p.status.textContent, "另一个任务");
    });
  }
  for (const stage of ["activation", "refresh"]) {
    test(`${taskType} settings ${stage} completion releases busy without overwriting the new task`, async () => {
      const p = confirmationPane(taskType);
      const response = deferred();
      if (stage === "activation") {
        const request = p.context.request;
        p.context.request = (url, body) => url.endsWith("/activate") ? response.promise : request(url, body);
        p.context.loadDirectServices = async () => { p.status.textContent = "刷新覆盖了当前页面"; };
      } else {
        p.context.loadWorkflowProfiles = () => response.promise;
      }
      p.probe.resolve({ data: { success: true, streamingCapability: "validated" } });
      const pending = p.saveTaskModelSelection();
      await new Promise(resolve => setImmediate(resolve));
      p.switchTask("word.document_review");
      p.status.textContent = "另一个任务";
      response.resolve({ data: { taskModelSelection: { ...p.draft } } });
      await pending;
      assert.strictEqual(p.state.workflowProfileMutationBusy, false);
      assert.strictEqual(p.state.taskModelSelections[taskType].serviceId, p.service.id);
      assert.strictEqual(p.status.textContent, "另一个任务");
    });
  }
}

for (const taskType of ["word.smart_write", "word.smart_imitation"]) {
  test(`${taskType} catalog unsupported keeps the saved selection and draft`, async () => {
    const p = confirmationPane(taskType);
    p.probe.resolve({ data: { streamingCapability: "unsupported" } });
    await p.saveTaskModelSelection();
    assert.deepStrictEqual(p.calls, [`/provider/task-model-selections/${taskType}/validate`]);
    assert.strictEqual(p.state.taskModelSelections[taskType], p.saved);
    assert.strictEqual(p.draft.serviceId, p.service.id);
    assert.match(p.status.textContent, /不支持流式|未通过流式/);
  });

  test(`${taskType} compact catalog switch validates once before activation`, async () => {
    const p = confirmationPane(taskType);
    const pending = p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
    await p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
    assert.deepStrictEqual(p.calls, [`/provider/task-model-selections/${taskType}/validate`]);
    p.probe.resolve({ data: { streamingCapability: "validated" } });
    await pending;
    assert.strictEqual(p.calls[1], `/provider/direct-services/${p.service.id}/activate`);
  });

  test(`${taskType} compact unsupported switch preserves previous activation`, async () => {
    const p = confirmationPane(taskType);
    p.probe.resolve({ data: { streamingCapability: "unsupported" } });
    await p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
    assert.strictEqual(p.calls.length, 1);
    assert.ok(p.calls[0].endsWith("/validate"));
    assert.strictEqual(p.state.workflowProfileSelections[taskType], p.saved.serviceId);
    assert.strictEqual(p.state.taskModelSelections[taskType], p.saved);
  });

  test(`${taskType} compact inherited manual model activates without awaiting probe`, async () => {
    const p = confirmationPane(taskType, true);
    await p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
    assert.deepStrictEqual(p.calls, [`/provider/direct-services/${p.service.id}/activate`,
      `/provider/task-model-selections/${taskType}/validate`]);
    assert.strictEqual(p.state.workflowProfileMutationBusy, false);
    p.probe.reject(new Error("探测失败"));
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(p.state.taskModelSelections[taskType].serviceId, p.service.id);
  });

  test(`${taskType} compact validation cannot activate after switching tasks`, async () => {
    const p = confirmationPane(taskType);
    const pending = p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
    p.switchTask("word.document_review");
    p.probe.resolve({ data: { streamingCapability: "validated" } });
    await pending;
    assert.strictEqual(p.calls.length, 1);
    assert.strictEqual(p.state.workflowProfileSelections[taskType], p.saved.serviceId);
    assert.strictEqual(p.state.workflowProfileMutationBusy, false);
  });

  for (const stage of ["activation", "refresh"]) {
    test(`${taskType} compact ${stage} completion releases busy after switching tasks`, async () => {
      const p = confirmationPane(taskType);
      const response = deferred();
      if (stage === "activation") {
        const request = p.context.request;
        p.context.request = (url, body) => url.endsWith("/activate") ? response.promise : request(url, body);
      } else {
        p.context.loadWorkflowProfiles = () => response.promise;
      }
      p.probe.resolve({ data: { streamingCapability: "validated" } });
      const pending = p.activateWorkflowProfile(p.service.id, taskType, p.saved.serviceId);
      await new Promise(resolve => setImmediate(resolve));
      p.switchTask("word.document_review");
      p.status.textContent = "另一个任务";
      response.resolve({ data: { taskModelSelection: { ...p.draft } } });
      await pending;
      assert.strictEqual(p.state.workflowProfileMutationBusy, false);
      assert.strictEqual(p.state.taskModelSelections[taskType].serviceId, p.service.id);
      assert.strictEqual(p.status.textContent, "另一个任务");
    });
  }

  for (const fail of [false, true]) {
    test(`${taskType} stale manual probe ${fail ? "failure" : "success"} leaves edited selection feedback intact`, async () => {
      const p = confirmationPane(taskType, true);
      await p.saveTaskModelSelection();
      p.draft.serviceId = "direct_svc_other";
      p.draft.modelName = "other-model";
      p.status.textContent = "正在编辑另一个模型";
      if (fail) p.probe.reject(new Error("旧探测失败"));
      else p.probe.resolve({ data: { streamingCapability: "validated" } });
      await new Promise(resolve => setImmediate(resolve));
      assert.strictEqual(p.status.textContent, "正在编辑另一个模型");
    });
  }
}

test("Word service changes preserve validate button visibility for each task", () => {
  const js = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
  const start = js.indexOf("  function handleTaskDirectServiceSelectChange(");
  const end = js.indexOf("\n  function ", start + 1);
  for (const task of ["word.smart_write", "word.smart_imitation", "word.format_review", "word.document_review", "word.material_composer"]) {
    const elements = {};
    const context = {
      state: {},
      byId: id => elements[id] || (elements[id] = { value: id.endsWith("service-select") ? "direct_svc_1" : "", hidden: false }),
      getSettingsWorkflowTaskType: () => task,
      findDirectService: () => ({ defaultModel: "catalog-model", modelList: ["catalog-model"] }),
      helpers: { ...require(path.join(wordRoot, "taskpane-helpers.js")), renderModelOptionsWithCustom() {} },
      renderCustomModelsList() {}, escapeWorkflowText: value => value
    };
    const change = vm.runInNewContext("(" + js.slice(start, end) + ")", context);
    change();
    assert.strictEqual(elements["btn-validate-task-model-selection"].hidden,
      ["word.smart_write", "word.smart_imitation", "word.format_review"].includes(task), task);
  }
});
