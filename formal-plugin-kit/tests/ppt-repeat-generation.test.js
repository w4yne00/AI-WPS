const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pptRoot } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(pptRoot, "taskpane.js"), "utf8");
function load(name, ctx) {
  const start = source.indexOf("  function " + name + "(");
  const end = source.indexOf("\n  function ", start + 3);
  return vm.runInNewContext("(" + source.slice(start, end) + ")", ctx);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const pending = [], requests = [], elements = {};
  const state = { jobId: "", documentSessionId: "doc-a", result: { suggestedTitle: "old" }, activeTaskSlots: {} };
  const ctx = {
    state, Date, helpers: { describePptJobProgress: () => ({ status: "running", detail: "progress" }) },
    byId: id => elements[id] || (elements[id] = {}),
    request: (url, payload) => { const d = deferred(); pending.push(d); requests.push({ url, payload }); return d.promise; },
    PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 10000,
    setStatus: text => { state.status = text; },
    showProgressText: text => { state.output = text; },
    saveActiveJob: job => { state.saved = job; },
    saveStructureActiveJob: job => { state.saved = job; },
    setInterruptedRetryVisible() {}, setPptJobActionVisibility() {}, setStructureJobActionVisibility() {},
    pollPptSlideJob: id => { state.polled = id; }, pollStructureReviewJob: id => { state.polled = id; },
    isFatalPollError: () => true, isFatalStructurePollError: () => true,
    failJob: (id, message) => { state.jobId = ""; state.output = message; },
    failStructureJob: (id, message) => { state.jobId = ""; state.output = message; },
    describeStructureProgress: () => ({ status: "running", detail: "progress" })
  };
  ctx.isPptTaskDocumentActive = load("isPptTaskDocumentActive", ctx);
  return { ctx, state, pending, requests, elements };
}
for (const name of ["submitPptSlideJob", "submitStructureReviewJob"]) {
  test(name + " ignores delayed rejection from a previous submission", async () => {
    const h = harness(), submit = load(name, h.ctx);
    submit({ clientJobId: "old", documentSessionId: "doc-a" });
    submit({ clientJobId: "new", documentSessionId: "doc-a" });
    h.state.output = "new progress";
    h.pending[0].reject(new Error("old error"));
    await flush();
    assert.equal(h.state.jobId, "new");
    assert.equal(h.state.output, "new progress");
  });
  test(name + " ignores delayed success from a previous submission", async () => {
    const h = harness(), submit = load(name, h.ctx);
    submit({ clientJobId: "old", documentSessionId: "doc-a" });
    submit({ clientJobId: "new", documentSessionId: "doc-a" });
    h.pending[0].resolve({ data: { jobId: "old", status: "running" } });
    await flush();
    assert.equal(h.state.jobId, "new");
    assert.equal(h.state.polled, undefined);
    assert.equal(h.state.saved.jobId, "new");
  });
}
test("current slide repeated clicks during extraction submit once; next generation gets a new ID", () => {
  const h = harness(), timers = [];
  Object.assign(h.state, { modelTasksAllowed: true, workflowTaskType: "ppt.slide_assistant", sourceMode: "slide" });
  Object.assign(h.ctx, {
    setTimeout: fn => timers.push(fn), Math,
    getActivePresentation: () => ({}), getWppApplication: () => ({}),
    setRunDisabled: busy => { h.state.busy = busy; },
    beginTaskPerformance: () => ({}), setSummary() {},
    safeText: value => String(value || ""), PPT_EXTRACTION_LIMITS: {},
    setPlainResult: text => { h.state.output = text; }
  });
  Object.assign(h.ctx.helpers, {
    extractPresentationSlide: () => ({ slide: { textBlocks: ["A sufficiently long slide body for testing repeated generation"] } }),
    getDocumentSessionId: () => "doc-a", getDocumentDisplayName: () => "demo"
  });
  h.ctx.buildPptSlideClientJobId = load("buildPptSlideClientJobId", h.ctx);
  h.ctx.submitPptSlideJob = load("submitPptSlideJob", h.ctx);
  h.ctx.runCurrentSlideSummary = load("runCurrentSlideSummary", h.ctx);
  const run = load("runPptSlideAssistant", h.ctx);
  run(); run();
  while (timers.length) timers.shift()();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].payload.documentSessionId, "doc-a");
  assert.equal(h.state.result, null);
  const firstId = h.requests[0].payload.clientJobId;
  h.state.jobId = ""; h.state.busy = false;
  run(); while (timers.length) timers.shift()();
  assert.equal(h.requests.length, 2);
  assert.notEqual(h.requests[1].payload.clientJobId, firstId);
});
test("uploaded document recovery reuses its job ID and document session", () => {
  const h = harness();
  Object.assign(h.state, { taskMode: "pptSlideAssistant", currentView: "home" });
  const active = { jobId: "uploaded-job", documentSessionId: "doc-a", sourceMode: "document", stage: "uploaded", fileToken: "file-token", requestedSlideCount: 5 };
  Object.assign(h.ctx, {
    loadActiveJob: () => active, getActivePresentation: () => ({}),
    setSourceMode() {}, setRunDisabled() {},
    submitPptSlideJob: payload => h.requests.push(payload)
  });
  h.ctx.helpers.getDocumentSessionId = () => "doc-a";
  load("resumeJob", h.ctx)();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].clientJobId, "uploaded-job");
  assert.equal(h.requests[0].documentSessionId, "doc-a");
});
for (const outcome of ["resolve", "reject"]) {
  test("template deck " + outcome + " from another document cannot change the visible status", async () => {
    const h = harness(), d = deferred();
    let session = "doc-a";
    const ctrl = { startGenerate: () => d.promise };
    Object.assign(h.ctx, { ensureTemplateDeck: () => ctrl, getActivePresentation: () => ({}) });
    h.ctx.helpers.getDocumentSessionId = () => session;
    const marker = 'byId("btn-ppt-generate-template-deck").addEventListener("click", function () {';
    const start = source.indexOf(marker) + marker.length;
    const end = source.indexOf('\n      });\n    }', start);
    const click = vm.runInNewContext('(function () {' + source.slice(start, end) + '})', h.ctx);
    click(); session = "doc-b"; h.state.status = "B progress";
    d[outcome](outcome === "reject" ? new Error("A failed") : {});
    await flush();
    assert.equal(h.state.status, "B progress");
  });
}
test("summary submission retains its originating session when the pane changes documents", async () => {
  const h = harness();
  let completedSession;
  Object.assign(h.ctx, {
    finishJob: (id, result, session) => { completedSession = session; },
    getTerminalCompletionTimestamp: () => 100
  });
  load("submitPptSlideJob", h.ctx)({ clientJobId: "job-a", documentSessionId: "doc-a" });
  h.state.documentSessionId = "doc-b";
  h.pending[0].resolve({ data: { jobId: "job-a", status: "completed", result: {} } });
  await flush();
  assert.equal(completedSession, "doc-a");
  assert.equal(h.state.saved.documentSessionId, "doc-a");
});

for (const outcome of ["stale", "completed", "failed"]) {
  test("旧精简" + outcome + "不能覆盖当前任务窗格提示", async () => {
    const h = harness(), d = deferred();
    let session = "doc-a";
    Object.assign(h.ctx, {
      ensureTemplateDeck: () => ({ simplifyPage: () => d.promise }),
      getActivePresentation: () => ({})
    });
    h.ctx.helpers.getDocumentSessionId = () => session;
    const marker = 'byId("ppt-template-deck-preview").addEventListener("click", function (event) {';
    const start = source.indexOf(marker) + marker.length;
    const end = source.indexOf('\n      });\n    }', start);
    const click = vm.runInNewContext('(function (event) {' + source.slice(start, end) + '})', h.ctx);
    click({ target: { getAttribute: name => name === "data-deck-action" ? "simplify" : "page-a" } });
    if (outcome !== "stale") session = "doc-b";
    h.state.status = "当前任务已确认";
    if (outcome === "failed") d.reject(new Error("A精简失败"));
    else d.resolve(outcome === "stale" ? null : { title: "A精简结果" });
    await flush();
    assert.equal(h.state.status, "当前任务已确认");
  });
}
