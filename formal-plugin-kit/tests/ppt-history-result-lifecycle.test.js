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

function harness(taskMode = "pptSlideAssistant") {
  const elements = {}, pending = [], timers = [];
  const state = {
    taskMode, historyOpen: true, historyItems: [], activeTaskSlots: {}, modelTasksAllowed: true,
    documentSessionId: "doc-a", workflowTaskType: "ppt.slide_assistant",
    result: { suggestedTitle: "旧总结" }, structureResult: { reviewConclusion: "旧审查" }
  };
  const ctx = {
    state, Date, Math,
    byId: id => elements[id] || (elements[id] = { value: "", hidden: false, textContent: "", innerHTML: "" }),
    request: () => { const d = deferred(); pending.push(d); return d.promise; },
    helpers: {
      getDocumentSessionId: () => "doc-a", getDocumentDisplayName: () => "测试.pptx",
      extractPresentationSlide: () => ({ slide: { textBlocks: ["足够长的当前页正文，用于测试新的总结结果显示及历史隔离。"] } }),
      extractPresentationStructure: () => ({ slides: [{ title: "新标题" }], scope: { startSlide: 1, endSlide: 1, totalSlides: 1 } }),
      validatePptDocumentFile: () => ({ valid: true, mimeType: "text/markdown" }),
      renderHistoryList: items => items.map(item => item.id).join(","), escapeHtml: text => text
    },
    document: {}, getActivePresentation: () => ({}), getWppApplication: () => ({}),
    setStatus: text => { state.status = text; }, setRunDisabled: busy => { state.busy = busy; },
    setPptJobActionVisibility() {},
    setTimeout: fn => timers.push(fn), beginTaskPerformance: () => ({}), setSummary() {},
    safeText: value => String(value || ""), buildPptSlideClientJobId: mode => "new-" + mode,
    showProgressText: text => { state.output = text; },
    submitPptSlideJob: payload => { state.submitted = payload; },
    submitStructureReviewJob: payload => { state.submitted = payload; },
    saveActiveJob() {}, readFileAsBase64: () => new Promise(() => {}),
    renderResult: result => { state.rendered = result; },
    renderStructureResult: result => { state.rendered = result; },
    renderMaterialOutlineView() {}, updateHistoryBadge() {},
    PPT_EXTRACTION_LIMITS: {}, PPT_STRUCTURE_MAX_SLIDES: 60,
    PPT_STRUCTURE_MAX_FALLBACK_CHARS: 120, PPT_STRUCTURE_MAX_FALLBACK_SLIDES: 10,
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review", PPT_DOCUMENT_SLIDE_COUNTS: { 10: true }
  };
  ctx.homeWorkflowTaskType = () => state.taskMode === "pptStructureReview" ? "ppt.structure_review" : "ppt.slide_assistant";
  ctx.loadAndRenderHistory = load("loadAndRenderHistory", ctx);
  ctx.switchHistoryView = load("switchHistoryView", ctx);
  ctx.isPptTaskDocumentActive = load("isPptTaskDocumentActive", ctx);
  return { ctx, state, elements, pending, timers };
}

for (const [name, mode] of [
  ["runCurrentSlideSummary", "pptSlideAssistant"],
  ["runDocumentSummary", "pptSlideAssistant"],
  ["runPptStructureReview", "pptStructureReview"]
]) {
  test(name + " starts a new task in the active preview when history is open", () => {
    const h = harness(mode);
    h.state.selectedDocument = { name: "资料.md", size: 10 };
    h.ctx.byId("ppt-slide-count").value = "10";
    load(name, h.ctx)();
    while (h.timers.length) h.timers.shift()();
    assert.equal(h.state.historyOpen, false);
    assert.equal(h.elements[mode === "pptStructureReview" ? "structure-result-section" : "summary-result-section"].hidden, false);
    assert.equal(h.elements["ppt-history-view"].hidden, true);
    assert.equal(mode === "pptStructureReview" ? h.state.structureResult : h.state.result, null);
  });
}

test("资料大纲开始新任务时返回活动预览", () => {
  const h = harness("pptMaterialOutline");
  h.ctx.ensureMaterialOutline = () => ({ submit: () => { h.state.submitted = true; } });
  const marker = 'byId("btn-run-outline").addEventListener("click", function () {';
  const start = source.indexOf(marker) + marker.length;
  const end = source.indexOf("\n      });", start);
  vm.runInNewContext("(function () {" + source.slice(start, end) + "})", h.ctx)();
  assert.equal(h.state.submitted, true);
  assert.equal(h.state.historyOpen, false);
  assert.equal(h.elements["outline-result-section"].hidden, false);
});

for (const outcome of ["resolve", "reject"]) {
  test("旧历史" + outcome + "不能覆盖切换任务后的历史", async () => {
    const h = harness();
    h.ctx.loadAndRenderHistory();
    h.state.taskMode = "pptStructureReview";
    h.ctx.loadAndRenderHistory();
    h.pending[1].resolve({ data: { items: [{ id: "新审查历史" }] } });
    await flush();
    h.pending[0][outcome](outcome === "resolve" ? { data: { items: [{ id: "旧总结历史" }] } } : new Error("旧总结错误"));
    await flush();
    assert.equal(h.elements["ppt-history-content"].innerHTML, "新审查历史");
    assert.equal(h.state.historyItems[0].id, "新审查历史");
  });
}

test("同一任务旧历史刷新不能覆盖较新的历史", async () => {
  const h = harness();
  h.ctx.loadAndRenderHistory();
  h.ctx.loadAndRenderHistory();
  h.pending[1].resolve({ data: { items: [{ id: "最新历史" }] } });
  await flush();
  h.pending[0].resolve({ data: { items: [{ id: "先前历史" }] } });
  await flush();
  assert.equal(h.elements["ppt-history-content"].innerHTML, "最新历史");
});

test("清空历史后，先前的历史读取响应不能恢复旧记录", async () => {
  const h = harness();
  h.ctx.loadAndRenderHistory();
  load("handleClearHistory", h.ctx)();
  h.pending[1].resolve({ success: true });
  await flush();
  h.pending[0].resolve({ data: { items: [{ id: "已清空的历史" }] } });
  await flush();
  assert.equal(h.elements["ppt-history-content"].innerHTML, "");
  assert.equal(h.state.historyItems.length, 0);
});

for (const name of ["handleClearHistory", "handleHistoryDeleteItem"]) {
  test(name + " invalidates a history read started while deletion was pending", async () => {
    const h = harness();
    h.state.historyItems = [{ id: "待删除历史" }, { id: "保留历史" }];
    load(name, h.ctx)("待删除历史");
    h.ctx.loadAndRenderHistory();
    h.pending[0].resolve({ success: true });
    await flush();
    h.pending[1].resolve({ data: { items: [{ id: "待删除历史" }, { id: "保留历史" }] } });
    await flush();
    assert.equal(h.elements["ppt-history-content"].innerHTML, name === "handleClearHistory" ? "" : "保留历史");
    assert.equal(h.state.historyItems.some(item => item.id === "待删除历史"), false);
  });

  for (const outcome of ["resolve", "reject"]) {
    test(name + " delayed " + outcome + " cannot update a different ribbon task", async () => {
      const h = harness();
      load(name, h.ctx)("旧任务历史");
      h.state.taskMode = "pptStructureReview";
      h.state.historyItems = [{ id: "新审查历史" }];
      h.ctx.byId("ppt-history-content").innerHTML = "新审查历史已展开内容";
      h.state.status = "新审查任务状态";
      h.pending[0][outcome](outcome === "resolve" ? { success: true } : new Error("旧任务删除失败"));
      await flush();
      assert.equal(h.elements["ppt-history-content"].innerHTML, "新审查历史已展开内容");
      assert.equal(h.state.historyItems[0].id, "新审查历史");
      assert.equal(h.state.status, "新审查任务状态");
    });
  }
}

for (const name of ["pollPptSlideJob", "pollStructureReviewJob"]) {
  for (const outcome of ["running", "transient", "interrupted"]) {
  test(name + " keeps " + outcome + " from a different document out of the current preview", async () => {
    const h = harness(name === "pollStructureReviewJob" ? "pptStructureReview" : "pptSlideAssistant");
    let session = "doc-a";
    Object.assign(h.state, { jobId: "job-a", startedAt: Date.now(), pollErrors: 0 });
    Object.assign(h.ctx, {
      PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 10000, PPT_SLIDE_POLL_INTERVAL_MS: 3000,
      PPT_SLIDE_POLL_MAX_ERRORS: 240, PPT_SLIDE_POLL_MAX_WAIT_MS: 3600000,
      PPT_SLIDE_POLL_ERROR_RETRY_DELAY_MS: 15000, PPT_SLIDE_POLL_SLOW_RETRY_DELAY_MS: 30000,
      clearActiveJob() {}, clearStructureActiveJob() {}, releaseTaskSlotsForJob() {}, setInterruptedRetryVisible() {},
      isFatalPollError: () => false, isFatalStructurePollError: () => false,
      saveStructureActiveJob() {}, setPptJobActionVisibility() {}, setStructureJobActionVisibility() {},
      describeStructureProgress: () => ({ status: "A 进度", detail: "A 任务正文" }),
      schedulePoll: () => { h.state.scheduled = true; }
    });
    h.ctx.helpers.getDocumentSessionId = () => session;
    h.ctx.helpers.describePptJobProgress = () => ({ status: "A 进度", detail: "A 任务正文" });
    load(name, h.ctx)("job-a", "doc-a");
    session = "doc-b";
    h.state.status = "B 任务状态";
    h.state.output = "B 当前结果";
    h.ctx.byId("structure-result-output").textContent = "B 当前结果";
    if (outcome === "running") h.pending[0].resolve({ data: { status: "running" } });
    else {
      const error = new Error("A 查询失败");
      if (outcome === "interrupted") error.adapterCode = name === "pollPptSlideJob" ? "PPT_SLIDE_JOB_INTERRUPTED" : "PPT_STRUCTURE_JOB_INTERRUPTED";
      h.pending[0].reject(error);
    }
    await flush();
    assert.equal(h.state.status, "B 任务状态");
    assert.equal(h.state.output, "B 当前结果");
    assert.equal(h.ctx.byId("structure-result-output").textContent, "B 当前结果");
    if (outcome !== "interrupted") assert.ok(h.state.scheduled || h.timers.length, "后台任务仍应继续恢复轮询");
  });
  }
}

for (const name of ["submitPptSlideJob", "submitStructureReviewJob"]) {
  for (const outcome of ["running", "transient"]) {
  test(name + " keeps delayed " + outcome + " from changing another document preview", async () => {
    const h = harness();
    let session = "doc-a";
    Object.assign(h.ctx, {
      PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 10000,
      saveStructureActiveJob() {}, setPptJobActionVisibility() {}, setStructureJobActionVisibility() {}, setInterruptedRetryVisible() {},
      isFatalPollError: () => false, isFatalStructurePollError: () => false,
      describeStructureProgress: () => ({ status: "A 进度", detail: "A 正文" }),
      pollPptSlideJob: () => { h.state.scheduled = true; }, pollStructureReviewJob: () => { h.state.scheduled = true; }
    });
    h.ctx.helpers.getDocumentSessionId = () => session;
    h.ctx.helpers.describePptJobProgress = () => ({ status: "A 进度", detail: "A 正文" });
    load(name, h.ctx)({ clientJobId: "job-a", documentSessionId: "doc-a" });
    session = "doc-b";
    h.state.status = "B 任务状态";
    h.state.output = "B 当前结果";
    h.ctx.byId("structure-result-output").textContent = "B 当前结果";
    if (outcome === "running") h.pending[0].resolve({ data: { jobId: "job-a", status: "running" } });
    else h.pending[0].reject(new Error("A 提交响应暂时中断"));
    await flush();
    assert.equal(h.state.status, "B 任务状态");
    assert.equal(h.state.output, "B 当前结果");
    assert.equal(h.ctx.byId("structure-result-output").textContent, "B 当前结果");
    assert.equal(h.state.scheduled, true);
  });
  }
}
