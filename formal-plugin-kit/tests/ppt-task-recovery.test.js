const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pptRoot } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(pptRoot, "taskpane.js"), "utf8");
function load(name, ctx) {
  const start = source.indexOf("  function " + name + "(");
  const next = source.indexOf("\n  function ", start + 3);
  const nextVar = source.indexOf("\n  var ", start + 3);
  const end = nextVar >= 0 && nextVar < next ? nextVar : next;
  assert.ok(start >= 0, name);
  return vm.runInNewContext("(" + source.slice(start, end) + ")", ctx);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(structure = false) {
  const elements = {}, pending = [], requests = [], timers = [];
  const state = {
    jobId: "job-a", busy: true, pollErrors: 0, startedAt: Date.now(),
    taskMode: structure ? "pptStructureReview" : "pptSlideAssistant",
    documentSessionId: "doc-a", activeTaskSlots: { slot: { jobId: "job-a" } }
  };
  const ctx = {
    state, Date, Math,
    byId: id => elements[id] || (elements[id] = { hidden: true, disabled: false, textContent: "", removeAttribute(name) { this[name] = false; } }),
    request: (url, payload, options) => { const d = deferred(); pending.push(d); requests.push({ url, payload, options }); return d.promise; },
    setStatus: text => { state.status = text; }, setPlainResult: text => { state.output = text; },
    showProgressText: text => { state.output = text; }, safeText: value => String(value || ""),
    setRunDisabled: busy => { state.busy = busy; },
    clearActiveJob: () => { state.cleared = true; }, clearStructureActiveJob: () => { state.cleared = true; },
    saveActiveJob() {}, saveStructureActiveJob() {},
    getActivePresentation: () => ({}), helpers: { getDocumentSessionId: () => "doc-a" },
    setTimeout: fn => timers.push(fn),
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant", PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 10000, PPT_SLIDE_POLL_MAX_ERRORS: 3,
    PPT_SLIDE_POLL_MAX_WAIT_MS: 3600000, PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS: 15000,
    PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS: 30000
  };
  for (const name of ["isPptTaskDocumentActive", "releaseTaskSlotsForJob", "setPptJobActionVisibility", "setStructureJobActionVisibility", "setInterruptedRetryVisible", "isFatalPollError", "isFatalStructurePollError", "failJob", "failStructureJob", "schedulePoll"]) ctx[name] = load(name, ctx);
  return { ctx, state, elements, pending, requests, timers };
}

for (const [name, button] of [["setPptJobActionVisibility", "btn-cancel-ppt-slide-job"], ["setStructureJobActionVisibility", "btn-cancel-structure-review-job"]]) {
  for (const status of ["submitting", "running"]) {
    test(name + " offers cancel while " + status, () => {
      const h = harness();
      h.ctx[name](status === "submitting" ? null : { status, canCancel: false });
      assert.equal(h.ctx.byId(button).hidden, false);
    });
  }
}
for (const [name, structure] of [["isFatalPollError", false], ["isFatalStructurePollError", true]]) {
  for (const error of [{ status: 404 }, { adapterCode: "LONG_TASK_NOT_FOUND" }]) {
    test(name + " treats a missing job as terminal: " + JSON.stringify(error), () => {
      const h = harness(structure);
      assert.equal(Boolean(h.ctx[name](error)), true);
    });
  }
}
for (const [name, structure] of [["submitPptSlideJob", false], ["submitStructureReviewJob", true]]) {
  test(name + " releases busy state and slot when model selection rejects submission", () => {
    const h = harness(structure);
    h.ctx.validateActiveDirectTaskSelection = () => ({ valid: false, error: "模型不可用" });
    load(name, h.ctx)({ clientJobId: "job-a", documentSessionId: "doc-a" });
    assert.equal(h.state.busy, false);
    assert.equal(h.state.jobId, "");
    assert.equal(Object.keys(h.state.activeTaskSlots).length, 0);
    assert.equal(h.requests.length, 0);
  });
}
for (const [name, structure, retry] of [["failJob", false, "btn-resubmit-interrupted-job"], ["failStructureJob", true, "btn-resubmit-structure-review"]]) {
  test(name + " unlocks explicit retry after a missing/failed task", () => {
    const h = harness(structure);
    h.ctx[name]("job-a", "任务不存在，请重新提交", "任务中断", "doc-a");
    assert.equal(h.state.busy, false);
    assert.equal(h.state.jobId, "");
    assert.equal(Object.keys(h.state.activeTaskSlots).length, 0);
    assert.equal(h.ctx.byId(retry).hidden, false);
  });
}
for (const error of [{ status: 404 }, { adapterCode: "PPT_STRUCTURE_JOB_NOT_FOUND" }]) {
  test("structure resume missing task restores retry: " + JSON.stringify(error), async () => {
    const h = harness(true);
    h.state.jobId = "";
    h.ctx.loadStructureActiveJob = () => ({ jobId: "job-a", documentSessionId: "doc-a" });
    load("resumeStructureReviewJob", h.ctx)();
    h.pending[0].reject(Object.assign(new Error("任务不存在"), error));
    await flush();
    assert.equal(h.state.busy, false);
    assert.equal(Object.keys(h.state.activeTaskSlots).length, 0);
    assert.equal(h.ctx.byId("btn-resubmit-structure-review").hidden, false);
  });
}

test("结构审查恢复首次查询超时后保留任务，可继续查询且不重复提交", async () => {
  const h = harness(true);
  h.state.jobId = "";
  h.state.busy = false;
  h.state.activeTaskSlots = {};
  h.ctx.loadStructureActiveJob = () => ({ jobId: "job-a", documentSessionId: "doc-a" });
  const resume = load("resumeStructureReviewJob", h.ctx)();
  h.pending[0].reject(Object.assign(new Error("请求超时"), { name: "AbortError" }));
  await resume;
  assert.equal(h.state.jobId, "job-a");
  assert.equal(h.state.pollPaused, true);
  assert.equal(h.state.busy, false);
  assert.equal(h.ctx.byId("btn-resubmit-structure-review").hidden, false);
  h.ctx.pollStructureReviewJob = load("pollStructureReviewJob", h.ctx);
  load("runPptStructureReview", h.ctx)();
  assert.equal(h.requests.length, 2);
  assert.match(h.requests[1].url, /\/jobs\/job-a/);
  assert.equal(h.requests[1].payload, null);
});
for (const [name, structure] of [["pollPptSlideJob", false], ["pollStructureReviewJob", true]]) {
  test(name + " stops automatic retries after repeated connection failure and keeps the job for explicit resume", async () => {
    const h = harness(structure);
    h.state.pollErrors = 3;
    load(name, h.ctx)("job-a", "doc-a");
    h.pending[0].reject(new Error("连接失败"));
    await flush();
    assert.equal(h.state.pollPaused, true);
    assert.equal(h.state.busy, false);
    assert.equal(h.state.jobId, "job-a");
    assert.equal(h.timers.length, 0);
    assert.match(h.state.status, /继续查询/);
  });
  test(name + " does not treat an unconfirmed submission 404 as an interrupted job", async () => {
    const h = harness(structure);
    h.state.submitPending = true;
    load(name, h.ctx)("job-a", "doc-a");
    h.pending[0].reject(Object.assign(new Error("任务尚未登记"), { status: 404 }));
    await flush();
    assert.equal(h.state.jobId, "job-a");
    assert.equal(h.state.busy, true);
    assert.equal(h.timers.length, 1);
  });
}

for (const [name, structure, cancel] of [["submitPptSlideJob", false, "cancelQueuedPptSlideJob"], ["submitStructureReviewJob", true, "cancelQueuedStructureReviewJob"]]) {
  test(name + " retries the pending cancel after delayed acceptance without a second model POST", async () => {
    const h = harness(structure);
    h.ctx[cancel] = () => { h.state.cancelRetried = true; };
    h.ctx.pollPptSlideJob = () => {};
    h.ctx.pollStructureReviewJob = () => {};
    h.ctx.helpers.describePptJobProgress = () => ({ status: "运行中", detail: "" });
    h.ctx.describeStructureProgress = () => ({ status: "运行中", detail: "" });
    load(name, h.ctx)({ clientJobId: "job-a", documentSessionId: "doc-a" });
    h.state.cancelRequested = true;
    h.pending[0].resolve({ success: true, data: { jobId: "job-a", status: "running" } });
    await flush();
    assert.equal(h.state.cancelRetried, true);
    assert.equal(h.requests.length, 1);
    assert.equal(h.state.submitPending, false);
  });
}

for (const [name, structure, run] of [["cancelQueuedPptSlideJob", false, "runPptSlideAssistant"], ["cancelQueuedStructureReviewJob", true, "runPptStructureReview"]]) {
  test(name + " leaves unknown cancel retryable without losing the submission", async () => {
    const h = harness(structure);
    h.state.submitPending = true;
    load(name, h.ctx)();
    h.pending[0].reject(Object.assign(new Error("尚未登记"), { status: 404 }));
    await flush();
    assert.equal(h.state.jobId, "job-a");
    assert.equal(h.state.cancelRequested, true);
    assert.equal(h.state.pollPaused, true);
    assert.equal(h.state.busy, false);
    assert.doesNotMatch(h.state.status, /已停止/);
  });
  test(run + " resumes a paused task only with GET and keeps the original job ID", () => {
    const h = harness(structure);
    h.state.pollPaused = true;
    h.state.busy = false;
    h.ctx.pollPptSlideJob = load("pollPptSlideJob", h.ctx);
    h.ctx.pollStructureReviewJob = load("pollStructureReviewJob", h.ctx);
    load(run, h.ctx)();
    assert.equal(h.requests.length, 1);
    assert.match(h.requests[0].url, /\/jobs\/job-a/);
    assert.equal(h.requests[0].payload, null);
  });
}

test("停止文档上传后，迟到读取不得上传或发起模型任务", async () => {
  const h = harness();
  const read = deferred();
  h.state.jobId = "";
  h.state.workflowTaskType = "ppt.slide_assistant";
  h.state.selectedDocument = { name: "资料.md", size: 12 };
  Object.assign(h.ctx, {
    buildPptSlideClientJobId: () => "upload-a", beginTaskPerformance: () => ({}),
    readFileAsBase64: () => read.promise, PPT_DOCUMENT_SLIDE_COUNTS: { 10: true },
    loadActiveJob: () => ({ jobId: "upload-a", stage: "uploading" })
  });
  h.ctx.helpers.validatePptDocumentFile = () => ({ valid: true });
  h.ctx.helpers.claimTaskSlot = (slots, host, taskType, session, id) => { slots.slot = { jobId: id }; };
  h.ctx.byId("ppt-slide-count").value = "10";
  load("runDocumentSummary", h.ctx)();
  assert.equal(h.state.jobId, "upload-a");
  load("cancelQueuedPptSlideJob", h.ctx)();
  read.resolve("dGVzdA==");
  await flush();
  assert.equal(h.state.jobId, "");
  assert.equal(h.state.busy, false);
  assert.equal(h.requests.length, 0);
});

test("总结恢复按文档保存任务，并保留未确认的取消意图", () => {
  const h = harness();
  const values = new Map();
  h.ctx.window = { localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key), get length() { return values.size; }, key: i => [...values.keys()][i] } };
  h.ctx.PPT_SLIDE_ACTIVE_JOB_STORAGE_KEY = "legacy-slide-job";
  h.ctx.loadActiveJob = load("loadActiveJob", h.ctx);
  const save = load("saveActiveJob", h.ctx);
  h.state.cancelRequested = true;
  save({ jobId: "job-a", documentSessionId: "doc-a", startedAt: 1 });
  h.state.jobId = "job-b";
  save({ jobId: "job-b", documentSessionId: "doc-b", startedAt: 2 });
  assert.equal(h.ctx.loadActiveJob("doc-a").jobId, "job-a");
  assert.equal(h.ctx.loadActiveJob("doc-a").cancelRequested, true);
  load("clearActiveJob", h.ctx)("job-a", "doc-a");
  assert.equal(h.ctx.loadActiveJob("doc-a"), null);
  assert.equal(h.ctx.loadActiveJob("doc-b").jobId, "job-b");
});
