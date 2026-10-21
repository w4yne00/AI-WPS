const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { wordRoot, etRoot } = require("./support/plugin-roots");

function pane(root, task, stalledRoute, phase) {
  const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  const nodes = new Map();
  const controls = [{ disabled: false }];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { disabled: false, textContent: "", querySelectorAll: () => controls });
    return nodes.get(id);
  };
  controls.push(node("btn-new-direct-service"));
  const oldService = { id: "direct_svc_old", complete: true, name: "旧服务" };
  const service = { id: "direct_svc_new", complete: true, name: "新服务", keyConfigured: true,
    serviceBaseUrl: "https://model.test/v1", defaultModel: "model", customModels: ["model"] };
  const state = { configurationMutationsAllowed: true, busy: false,
    directServices: [oldService, service], taskModelSelections: {}, taskModelConfigStatusByTask: {},
    taskApiKeys: { [task]: { accessMethod: "direct_model", activeProfileId: oldService.id } },
    workflowProfileSelections: { [task]: oldService.id }, workflowProfileRequestSequence: {},
    workflowProfileLoadSequences: {}, workflowProfiles: {}, workflowProfilesByTask: {}, profilesByTask: {},
    profileLoadRequestId: 0, workflowTaskType: task, currentView: "home" };
  const timers = new Map();
  const requests = [];
  let serial = 0;
  let resume;
  const stalled = new Promise(resolve => { resume = resolve; });
  const response = route => ({ ok: true, status: 200, json: async () => ({ success: true, data:
    route === "/provider/direct-services" ? { directServices: state.directServices } :
    route.includes("task-model-selections?") ? { taskModelSelections: [{ taskType: task, serviceId: service.id, modelName: "" }] } :
    { taskType: task, activeProfileId: service.id, profiles: [], taskModelSelection: { serviceId: service.id } }
  }) });
  const context = { state, helpers: require(path.join(root, "taskpane-helpers.js")),
    ADAPTER_BASE_URL: "http://adapter.test", SETTINGS_REFRESH_REQUEST_TIMEOUT_MS: 8000,
    TASK_API_KEY_DEFS: [{ taskType: task }], byId: node,
    getCurrentWorkflowTaskType: () => task, getSettingsWorkflowTaskType: () => task,
    getTaskPageWorkflowType: () => task, getWorkflowProfileData: () => ({ activeProfileId: oldService.id }),
    getWorkflowProfileById: (t, id) => id === service.id ? service : oldService,
    findWorkflowProfile: id => id === service.id ? service : oldService,
    findDirectService: () => service, isWorkflowInteractionBlocked: () => false,
    normalizeWorkflowProfileData: data => data, escapeWorkflowText: value => String(value || ""),
    setStatus: message => { node("status").textContent = message; },
    setNodeTextIfChanged: (target, message) => { target.textContent = message; },
    describeFetchError: error => error.message, describeSettingsError: error => error.message,
    setTimeout: (fn, delay) => { timers.set(++serial, { fn, delay }); return serial; },
    clearTimeout: id => timers.delete(id),
    fetch: async url => {
      const route = url.replace("http://adapter.test", "");
      requests.push(route);
      if (route === stalledRoute) return phase === "body" ? { ok: true, json: () => stalled } : stalled;
      return response(route);
    }
  };
  for (const name of ["renderWorkflowProfileStrip", "renderWorkflowTaskTabs", "renderWorkflowProfileManager",
    "renderTaskModelSelectionSection", "renderModelInterfaceState", "renderFullDocumentReviewEntry",
    "renderDirectServicesList", "renderProfileStrip", "renderProfileManager", "updateWorkflowEditorControls",
    "syncSettingsRefreshController", "focusTaskModelConfigTrigger"]) context[name] = () => {};
  function load(name) {
    const start = source.indexOf(`  function ${name}(`);
    const end = source.indexOf("\n  function ", start + 1);
    assert.ok(start >= 0 && end > start, name);
    context[name] = vm.runInNewContext(`(${source.slice(start, end)})`, context);
  }
  for (const name of ["request", "activateWorkflowProfile", "loadDirectServices"]) load(name);
  if (root === wordRoot) {
    for (const name of ["loadWorkflowProfiles", "nextWorkflowProfileRequestId", "isWorkflowProfileRequestCurrent",
      "renderDirectServicesList", "syncWorkflowProfileManagerBusyState", "setWorkflowProfileMutationBusy"]) load(name);
  } else {
    for (const name of ["loadWorkflowProfileForTask", "setWorkflowMutationBusy"]) load(name);
  }
  const activate = () => root === etRoot
    ? context.activateWorkflowProfile(service.id, oldService.id, task)
    : context.activateWorkflowProfile(service.id, task, oldService.id);
  return { state, service, requests, timers, activate, controls, node, renderServices: context.renderDirectServicesList,
    resume: () => resume(phase === "body"
    ? { success: true, data: {} } : response(stalledRoute)) };
}

for (const task of ["word.smart_write", "word.smart_imitation"]) {
  for (const source of ["catalog", "manual"]) {
    test(`${task} ${source} switch only saves and reads local configuration without probing the model`, async () => {
      const p = pane(wordRoot, task);
      p.service.modelList = source === "catalog" ? ["model"] : [];
      p.service.customModels = source === "manual" ? ["model"] : [];
      await p.activate();
      await new Promise(resolve => setImmediate(resolve));
      assert.deepEqual(p.requests.sort(), [
        "/provider/direct-services/direct_svc_new/activate",
        "/provider/direct-services",
        "/provider/task-model-selections?host=word",
        "/provider/model-configurations?taskType=" + encodeURIComponent(task)
      ].sort());
      assert.equal(p.state.workflowProfileSelections[task], "direct_svc_new");
      assert.equal(p.state.workflowProfileMutationBusy, false);
    });
  }
}

for (const [root, task] of [[wordRoot, "word.smart_write"], [etRoot, "excel.analysis"]]) {
  for (const route of ["/provider/direct-services/direct_svc_new/activate", "/provider/direct-services",
    "/provider/model-configurations?taskType=" + encodeURIComponent(task)]) {
    for (const phase of ["headers", "body"]) {
      test(`${task} switch releases the interface when ${route} stalls at ${phase}`, async () => {
        const p = pane(root, task, route, phase);
        let finished = false;
        const pending = p.activate().then(() => { finished = true; });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(p.state.workflowProfileMutationBusy, true);
        for (const timer of [...p.timers.values()]) timer.fn();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(finished, true, "a stalled switch must have a deadline");
        await pending;
        assert.equal(p.state.workflowProfileMutationBusy, false);
        const notice = p.node("status").textContent;
        assert.match(notice, /超时|超过.*等待|刷新.*失败/);
        if (route.endsWith("/activate")) assert.match(notice, /确认/, "a write timeout cannot claim that backend activation was rolled back");
        p.resume();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(p.node("status").textContent, notice, "a late response must not revive the expired switch");
      });
    }
  }
}

test("Word successful direct switch restores the disabled settings controls", async () => {
  const p = pane(wordRoot, "word.smart_write");
  await p.activate();
  assert.equal(p.state.workflowProfileMutationBusy, false);
  assert.equal(p.controls[0].disabled, false, "clearing busy must update the actual controls");
});

for (const fail of [false, true]) {
  test(`Word ${fail ? "timed out" : "successful"} switch keeps the five-service creation limit`, async () => {
    const p = pane(wordRoot, "word.smart_write", fail ? "/provider/direct-services/direct_svc_new/activate" : undefined, "headers");
    p.state.directServices.push(...[3, 4, 5].map(index => ({ id: "direct_svc_" + index, name: "服务" + index })));
    p.renderServices();
    assert.equal(p.node("btn-new-direct-service").disabled, true);
    const pending = p.activate();
    await new Promise(resolve => setImmediate(resolve));
    if (fail) for (const timer of [...p.timers.values()]) timer.fn();
    await pending;
    assert.equal(p.state.workflowProfileMutationBusy, false);
    assert.equal(p.node("btn-new-direct-service").disabled, true, "restoring busy controls must retain the service limit");
  });
}

for (const task of ["word.smart_write", "word.smart_imitation"]) {
  for (const route of ["/provider/direct-services", "/provider/model-configurations?taskType=" + encodeURIComponent(task)]) {
    test(`${task} switch reports the ${route} refresh failure without probing the model`, async () => {
      const p = pane(wordRoot, task, route, "headers");
      const pending = p.activate();
      await new Promise(resolve => setImmediate(resolve));
      for (const timer of [...p.timers.values()]) if (timer.delay === 8000) timer.fn();
      await pending;
      assert.equal(p.state.workflowProfileMutationBusy, false);
      const notice = p.node("status").textContent;
      assert.match(notice, /刷新最新列表失败/);
      assert.ok(p.requests.every(route => !route.endsWith("/validate")), "refresh failure must not trigger a model probe");
    });
  }
}
