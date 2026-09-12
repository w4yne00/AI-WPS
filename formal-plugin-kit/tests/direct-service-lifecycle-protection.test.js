const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

test("Direct Service Lifecycle: markup includes URL impact disclosure and Key clear action", () => {
  // URL impact disclosure element
  assert.ok(html.includes('id="direct-service-url-impact"'), "missing #direct-service-url-impact in taskpane.html");

  // Key actions: Clear key button
  assert.ok(html.includes('id="btn-clear-direct-service-key"'), "missing #btn-clear-direct-service-key in taskpane.html");

  // Single password input for Key, no echo
  assert.ok(html.includes('id="direct-service-key"'), "missing #direct-service-key");
  assert.ok(
    html.includes('id="direct-service-key" type="password"') ||
    html.includes('type="password" id="direct-service-key"'),
    "#direct-service-key must be type password"
  );

  // Delete dialog elements
  assert.ok(html.includes('id="direct-service-delete-dialog"'), "missing #direct-service-delete-dialog");
  assert.ok(html.includes('id="direct-service-delete-warning"'), "missing #direct-service-delete-warning");
  assert.ok(html.includes('id="btn-confirm-direct-service-delete"'), "missing #btn-confirm-direct-service-delete");
});

test("Direct Service Lifecycle Helpers: evaluateDirectServiceDelete and evaluateDirectServiceUrlImpact", () => {
  assert.strictEqual(typeof helpers.formatReferencedTasks, "function", "formatReferencedTasks helper must exist");
  assert.strictEqual(typeof helpers.evaluateDirectServiceDelete, "function", "evaluateDirectServiceDelete helper must exist");
  assert.strictEqual(typeof helpers.evaluateDirectServiceUrlImpact, "function", "evaluateDirectServiceUrlImpact helper must exist");
  assert.strictEqual(typeof helpers.isDirectServiceRevisionConflict, "function", "isDirectServiceRevisionConflict helper must exist");

  // formatReferencedTasks
  const formatted = helpers.formatReferencedTasks(["excel.analysis", "word.smart_write"]);
  assert.ok(formatted.includes("表格智能分析") || formatted.includes("智能分析"), "should format excel.analysis label");
  assert.ok(formatted.includes("文字智能编写") || formatted.includes("智能编写"), "should format word.smart_write label");

  // evaluateDirectServiceDelete
  const inUse = helpers.evaluateDirectServiceDelete({
    id: "svc_1",
    name: "在用服务",
    referencedTasks: ["excel.analysis"]
  });
  assert.strictEqual(inUse.canDelete, false);
  assert.ok(inUse.message.includes("智能分析"));

  const notInUse = helpers.evaluateDirectServiceDelete({
    id: "svc_2",
    name: "空闲服务",
    referencedTasks: []
  });
  assert.strictEqual(notInUse.canDelete, true);
  assert.strictEqual(notInUse.message, "");

  // evaluateDirectServiceUrlImpact
  const unchanged = helpers.evaluateDirectServiceUrlImpact(
    { serviceBaseUrl: "https://api.openai.com/v1", referencedTasks: ["excel.analysis"] },
    "https://api.openai.com/v1"
  );
  assert.strictEqual(unchanged.isModified, false);
  assert.strictEqual(unchanged.warning, "");

  const changedWithRefs = helpers.evaluateDirectServiceUrlImpact(
    { serviceBaseUrl: "https://api.openai.com/v1", referencedTasks: ["excel.analysis", "ppt.slide_assistant"] },
    "https://new-gateway.corp.com/v1"
  );
  assert.strictEqual(changedWithRefs.isModified, true);
  assert.ok(changedWithRefs.warning.includes("新地址") || changedWithRefs.warning.includes("影响"));
  assert.ok(changedWithRefs.warning.includes("智能分析") || changedWithRefs.warning.includes("幻灯片"));

  // isDirectServiceRevisionConflict
  assert.strictEqual(helpers.isDirectServiceRevisionConflict({ code: "DIRECT_SERVICE_REVISION_CONFLICT" }), true);
  assert.strictEqual(helpers.isDirectServiceRevisionConflict({ adapterCode: "DIRECT_SERVICE_REVISION_CONFLICT" }), true);
  assert.strictEqual(helpers.isDirectServiceRevisionConflict({ status: 409 }), true);
  assert.strictEqual(helpers.isDirectServiceRevisionConflict({ code: "PARAM_INVALID", status: 400 }), false);
});

test("Direct Service request preserves adapter error metadata", async () => {
  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const ctx = {
    ADAPTER_BASE_URL: "http://127.0.0.1:18100",
    state: { configurationMutationsAllowed: true, modelTasksAllowed: true },
    fetch() {
      return Promise.resolve({
        ok: false,
        status: 409,
        json() {
          return Promise.resolve({
            data: { currentRevision: 4 },
            errors: [{
              code: "DIRECT_SERVICE_IN_USE",
              message: "该服务仍被任务引用。",
              referencedTasks: ["excel.analysis"]
            }]
          });
        }
      });
    },
    Promise,
    Error,
    JSON,
    String,
    Array,
    encodeURIComponent,
    setTimeout,
    clearTimeout
  };
  const requestFn = vm.runInNewContext(`(${functionSource("request")})`, ctx);

  await assert.rejects(
    requestFn("/provider/direct-services/direct_svc_used", null, { method: "DELETE" }),
    error => {
      assert.strictEqual(error.adapterCode, "DIRECT_SERVICE_IN_USE");
      assert.strictEqual(error.code, "DIRECT_SERVICE_IN_USE");
      assert.strictEqual(error.status, 409);
      assert.deepStrictEqual(Array.from(error.referencedTasks), ["excel.analysis"]);
      assert.strictEqual(error.data.currentRevision, 4);
      return true;
    }
  );
});

test("Direct Service Delete Dialog blocks deletion when service is referenced", () => {
  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const mockNodes = {
    "direct-service-delete-dialog": { hidden: true },
    "direct-service-delete-name": { textContent: "" },
    "direct-service-delete-warning": { textContent: "" },
    "btn-confirm-direct-service-delete": { disabled: false }
  };

  const state = {
    directServices: [
      {
        id: "direct_svc_used",
        name: "被引用的服务",
        revision: 2,
        referencedTasks: ["excel.analysis"]
      },
      {
        id: "direct_svc_free",
        name: "空闲服务",
        revision: 1,
        referencedTasks: []
      }
    ],
    directServiceDeleteCandidate: null,
    taskModelSelections: { "excel.analysis": { serviceId: "direct_svc_used" } }
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    getWorkflowProfileData() { return { activeProfileId: "direct_svc_used" }; },
    findDirectService(id) {
      return state.directServices.find(s => s.id === id);
    }
  };

  const openDeleteFn = vm.runInNewContext(`(${functionSource("openDirectServiceDeleteDialog")})`, ctx);

  // 1. Open for referenced service -> delete button must be disabled, warning shown
  openDeleteFn("direct_svc_used");
  assert.strictEqual(mockNodes["direct-service-delete-dialog"].hidden, false);
  assert.strictEqual(mockNodes["btn-confirm-direct-service-delete"].disabled, true, "confirm delete button must be disabled when in use");
  assert.ok(mockNodes["direct-service-delete-warning"].textContent.includes("智能分析") || mockNodes["direct-service-delete-warning"].textContent.includes("excel.analysis"));

  // 2. Open for free service -> delete button enabled, warning cleared
  openDeleteFn("direct_svc_free");
  assert.strictEqual(mockNodes["btn-confirm-direct-service-delete"].disabled, false, "confirm delete button must be enabled when free");
  assert.strictEqual(mockNodes["direct-service-delete-warning"].textContent, "");
});

test("Direct Service Editor warns on revision conflict and prevents automatic merging", async () => {
  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const mockNodes = {
    "direct-service-editor-view": { hidden: false },
    "direct-services-list": { hidden: true },
    "btn-new-direct-service": { hidden: true },
    "direct-service-name": { value: "我的服务修改" },
    "direct-service-url": { value: "https://api.openai.com/v1" },
    "direct-service-key": { value: "" },
    "direct-service-default-model": { value: "gpt-4o" },
    "direct-service-editor-error": { textContent: "" }
  };

  let statusText = "";
  const state = {
    directServiceEditor: {
      open: true,
      mode: "edit",
      serviceId: "direct_svc_test",
      revision: 1
    },
    workflowProfileMutationBusy: false
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    setWorkflowMutationBusy(b) { state.workflowProfileMutationBusy = b; },
    setStatus(s) { statusText = s; },
    describeFetchError(err) { return (err && err.message) || String(err); },
    closeDirectServiceEditor() { state.directServiceEditor.open = false; },
    loadDirectServices() { return Promise.resolve(); },
    request(url, payload, options) {
      // Simulate 409 revision conflict
      const err = new Error("配置已被修改，版本发生冲突。");
      err.code = "DIRECT_SERVICE_REVISION_CONFLICT";
      err.status = 409;
      return Promise.reject(err);
    }
  };

  const saveFn = vm.runInNewContext(`(${functionSource("saveDirectServiceEditor")})`, ctx);
  saveFn();

  // Wait tick for promise rejection
  await new Promise(resolve => setTimeout(resolve, 50));

  assert.strictEqual(state.workflowProfileMutationBusy, false);
  const errMsg = mockNodes["direct-service-editor-error"].textContent;
  assert.ok(
    errMsg.includes("版本冲突") || errMsg.includes("DIRECT_SERVICE_REVISION_CONFLICT") || errMsg.includes("已停止保存"),
    "error box should explicitly indicate revision conflict"
  );
  assert.ok(
    errMsg.includes("刷新") || errMsg.includes("重新编辑"),
    "error box should guide user to refresh and re-edit"
  );
  // Editor should stay open so user's draft is not silently discarded or merged
  assert.strictEqual(state.directServiceEditor.open, true, "editor should remain open without auto-merging");
});

test("Direct Service Key Clear action performs DELETE /api-key with expectedRevision", async () => {
  function functionSource(name) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start !== -1, `function ${name} must exist in taskpane.js`);
    const next = js.indexOf("\n  function ", start + 3);
    return js.slice(start, next === -1 ? js.length : next);
  }

  const mockNodes = {
    "direct-service-key": { value: "some-unwanted-draft-key", placeholder: "" },
    "direct-service-key-status": { textContent: "已配置" },
    "direct-service-editor-error": { textContent: "" }
  };

  const requestsMade = [];
  let statusText = "";
  const state = {
    directServices: [{ id: "direct_svc_1", revision: 3, keyConfigured: true }],
    directServiceEditor: {
      open: true,
      mode: "edit",
      serviceId: "direct_svc_1",
      revision: 3
    },
    workflowProfileMutationBusy: false
  };

  const ctx = {
    state,
    helpers,
    byId(id) { return mockNodes[id] || null; },
    setWorkflowMutationBusy(b) { state.workflowProfileMutationBusy = b; },
    setStatus(s) { statusText = s; },
    describeFetchError(err) { return (err && err.message) || String(err); },
    loadDirectServices() {
      state.directServices[0].keyConfigured = false;
      state.directServices[0].revision = 4;
      return Promise.resolve();
    },
    findDirectService(id) { return state.directServices[0]; },
    request(url, payload, options) {
      requestsMade.push({ url, payload, method: options && options.method || "GET" });
      return Promise.resolve({
        data: {
          directService: {
            id: "direct_svc_1",
            keyConfigured: false,
            revision: 4
          }
        }
      });
    }
  };

  const clearKeyFn = vm.runInNewContext(`(${functionSource("clearDirectServiceApiKey")})`, ctx);
  clearKeyFn();

  await new Promise(resolve => setTimeout(resolve, 50));

  const clearReq = requestsMade.find(r => r.url.includes("/api-key") && r.method === "DELETE");
  assert.ok(clearReq, "must issue DELETE /api-key request");
  assert.ok(clearReq.url.includes("expectedRevision=3"), "DELETE must pass expectedRevision");
  assert.strictEqual(mockNodes["direct-service-key"].value, "", "input value must be reset to empty");
});
