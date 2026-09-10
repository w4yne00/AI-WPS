const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { pptRoot: root } = require("./support/plugin-roots");

const helpersSource = fs.readFileSync(
  path.join(root, "taskpane-helpers.js"),
  "utf8"
);
const taskpaneSource = fs.readFileSync(
  path.join(root, "taskpane.js"),
  "utf8"
);
const taskpaneHtml = fs.readFileSync(
  path.join(root, "taskpane.html"),
  "utf8"
);

const context = { window: {} };
vm.createContext(context);
vm.runInContext(helpersSource, context);
const helpers = context.window.WpsAiPptHelpers;

// Test 1: Document Session Identification
function testDocumentSessionIdentification() {
  assert.strictEqual(typeof helpers.getDocumentSessionId, "function", "getDocumentSessionId should be a function");

  const pres1 = { Name: "演示文稿1.pptx", FullName: "/Users/wayne/Documents/演示文稿1.pptx" };
  const pres2 = { Name: "方案汇报.pptx", FullName: "/Users/wayne/Secret/方案汇报.pptx" };

  const session1_a = helpers.getDocumentSessionId(pres1);
  const session1_b = helpers.getDocumentSessionId(pres1);
  const session2 = helpers.getDocumentSessionId(pres2);

  // Must be stable for same presentation instance
  assert.strictEqual(session1_a, session1_b, "Session ID must be stable for same presentation");
  // Must differ between different presentations
  assert.notStrictEqual(session1_a, session2, "Different presentations must have different session IDs");
  // Must not leak full path
  assert.ok(!session1_a.includes("/Users/wayne"), "Session ID must not contain full path");
  assert.ok(!session2.includes("/Secret"), "Session ID must not contain full path");
}

// Test 2: Document Display Name extraction (no path leak)
function testDocumentDisplayName() {
  assert.strictEqual(typeof helpers.getDocumentDisplayName, "function", "getDocumentDisplayName should be a function");

  const pres = { Name: "演示文稿1.pptx", FullName: "/Users/wayne/Documents/演示文稿1.pptx" };
  const displayName = helpers.getDocumentDisplayName(pres);
  assert.strictEqual(displayName, "演示文稿1.pptx");
  assert.ok(!displayName.includes("/Users/wayne"));
}

// Test 3: Active Task Slot Guard
function testActiveTaskSlotGuard() {
  assert.strictEqual(typeof helpers.isTaskSlotBusy, "function", "isTaskSlotBusy should be a function");

  const slots = {};
  const host = "wpp";
  const taskType = "ppt.slide_assistant";
  const session1 = "doc_session_1";
  const session2 = "doc_session_2";

  // Initially not busy
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);

  // Claim slot for session1
  helpers.claimTaskSlot(slots, host, taskType, session1, "job-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), true);

  // Different document session is NOT busy
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session2), false);

  // Release slot for session1
  helpers.releaseTaskSlot(slots, host, taskType, session1, "job-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);
}

// Test 4: Active Result State Machine (Taskpane Source Contract)
function testActiveResultLifecycleSourceContract() {
  // 1. Must NOT have if (!state.result) guard that suppresses progress or failure text
  assert.ok(
    !taskpaneSource.includes('if (!state.result) {\n    setPlainResult(text);\n  }'),
    "showProgressText must unconditionally update output and not be blocked by if (!state.result)"
  );
  assert.ok(
    !taskpaneSource.includes('if (!state.result) {\n      setPlainResult(failureMessage);\n    }'),
    "failJob must unconditionally render failure message in output and not be blocked by if (!state.result)"
  );

  // 2. Submission must clear old state.result when validation passes
  assert.ok(
    taskpaneSource.includes("state.result = null;"),
    "Preparing valid submission must set state.result = null"
  );

  // 3. Document session and slot checks in taskpane
  assert.ok(
    taskpaneSource.includes("getDocumentSessionId"),
    "taskpane.js must invoke getDocumentSessionId"
  );
  assert.ok(
    taskpaneSource.includes("isTaskSlotBusy") || taskpaneSource.includes("activeTaskSlots"),
    "taskpane.js must guard active task slots per document session"
  );

  // 4. HTML must have history button and history panel/view
  assert.ok(
    taskpaneHtml.includes("btn-view-history"),
    "taskpane.html must contain btn-view-history button"
  );
  assert.ok(
    taskpaneHtml.includes("ppt-history-view") || taskpaneHtml.includes("ppt-history-panel"),
    "taskpane.html must contain history view container"
  );
}

// Test 5: History Rendering Helper
function testHistoryRenderingHelper() {
  assert.strictEqual(typeof helpers.renderHistoryList, "function", "renderHistoryList should be a function");

  const items = [
    {
      id: "hist_1",
      taskType: "ppt.slide_assistant",
      jobId: "job-1",
      completedAt: "2026-09-09T16:00:00Z",
      documentDisplayName: "汇报.pptx",
      serviceName: "网关",
      modelName: "qwen",
      result: {
        suggestedTitle: "总结一",
        bullets: ["要点一"],
        conclusion: "结论一"
      }
    }
  ];

  const html = helpers.renderHistoryList(items);
  assert.ok(html.includes("汇报.pptx"), "History HTML must include document display name");
  assert.ok(html.includes("总结一"), "History HTML must include suggested title");
  assert.ok(html.includes("data-history-id=\"hist_1\""), "History HTML must include item id attribute");
}

function functionSource(name) {
  const start = taskpaneSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = taskpaneSource.indexOf("\n  function ", start + 1);
  return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
}

// Test 6: Active Result State Machine Regression (已有结果时的新进度、失败和成功均有回归测试)
function testActiveResultBehaviorWithExistingResult() {
  const elements = {
    "result-output": { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } } },
    "status-line": { textContent: "" },
    "btn-cancel-ppt-slide-job": { hidden: false, disabled: false },
    "history-unread-badge": { textContent: "0", hidden: true },
    "summary-result-section": { hidden: false },
    "ppt-history-view": { hidden: true }
  };

  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } }, hidden: false };
    }
    return elements[id];
  };

  const state = {
    result: { suggestedTitle: "旧标题" },
    activeTaskSlots: {},
    documentSessionId: "doc_1",
    jobId: "job_old",
    historyOpen: false,
    historyUnreadCount: 0
  };

  const ctx = {
    state,
    byId,
    safeText: (v) => String(v || "").trim(),
    setPlainResult: (text) => {
      elements["result-output"].textContent = text;
    },
    clearActiveJob: () => {},
    setPptJobActionVisibility: () => {},
    setRunDisabled: () => {},
    setStatus: (text) => {
      elements["status-line"].textContent = text;
    },
    renderResult: (res) => {
      state.result = res;
      elements["result-output"].textContent = res.suggestedTitle;
    },
    helpers,
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant",
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review"
  };

  const releaseTaskSlotsForJob = vm.runInNewContext(
    `(${functionSource("releaseTaskSlotsForJob")})`,
    ctx
  );
  ctx.releaseTaskSlotsForJob = releaseTaskSlotsForJob;

  const showProgressText = vm.runInNewContext(
    `(${functionSource("showProgressText")})`,
    ctx
  );

  const failJob = vm.runInNewContext(
    `(${functionSource("failJob")})`,
    ctx
  );

  const updateHistoryBadge = vm.runInNewContext(
    `(${functionSource("updateHistoryBadge")})`,
    ctx
  );
  ctx.updateHistoryBadge = updateHistoryBadge;

  const finishJob = vm.runInNewContext(
    `(${functionSource("finishJob")})`,
    ctx
  );

  // Claim a slot initially
  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1", "job_1");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1"), true);

  // Case 1: When previous result exists, new progress text MUST overwrite output
  showProgressText("正在生成第 2 步...");
  assert.strictEqual(elements["result-output"].textContent, "正在生成第 2 步...");

  // Case 2: When failure occurs, state.result must be cleared and output shows error
  failJob("job_1", "模型连接超时", "总结失败");
  assert.strictEqual(state.result, null, "state.result must be cleared to null on failure");
  assert.strictEqual(elements["result-output"].textContent, "模型连接超时");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1"), false, "Slot must be released on failure");

  // Case 3: New valid submission and completion
  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1", "job_2");
  finishJob("job_2", { suggestedTitle: "全新总结" });
  assert.deepStrictEqual(state.result, { suggestedTitle: "全新总结" });
  assert.strictEqual(elements["result-output"].textContent, "全新总结");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1"), false, "Slot must be released on completion");

  // Case 4: Completion while viewing history updates badge and does not overwrite current history view
  state.historyOpen = true;
  state.historyUnreadCount = 0;
  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.slide_assistant", "doc_1", "job_3");
  finishJob("job_3", { suggestedTitle: "后台完成的总结" });
  assert.strictEqual(state.historyUnreadCount, 1);
  assert.strictEqual(elements["history-unread-badge"].textContent, "1");
  assert.strictEqual(elements["history-unread-badge"].hidden, false);
}

// Test 7: History List API Envelope Handling
function testHistoryListEnvelopeParsing() {
  const elements = {
    "ppt-history-content": { innerHTML: "" }
  };
  const byId = (id) => elements[id] || { innerHTML: "" };
  const state = { historyItems: [] };

  const rawApiResponse = {
    success: true,
    data: {
      items: [
        {
          id: "hist_123456_abcdefabcdef",
          taskType: "ppt.slide_assistant",
          jobId: "job_01",
          completedAt: "2026-09-09T16:00:00Z",
          documentDisplayName: "总结测试.pptx",
          serviceName: "模型服务",
          modelName: "test-model",
          result: { suggestedTitle: "测试总结标题" }
        }
      ],
      total: 1,
      taskType: "ppt.slide_assistant"
    }
  };

  const ctx = {
    state,
    byId,
    request: () => Promise.resolve(rawApiResponse),
    helpers,
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant"
  };

  const loadAndRenderHistory = vm.runInNewContext(
    `(${functionSource("loadAndRenderHistory")})`,
    ctx
  );

  loadAndRenderHistory();

  // Wait for promise tick
  return Promise.resolve().then(() => {
    assert.ok(Array.isArray(state.historyItems), "state.historyItems must be an Array");
    assert.strictEqual(state.historyItems.length, 1, "state.historyItems must contain 1 item");
    assert.ok(
      elements["ppt-history-content"].innerHTML.includes("总结测试.pptx"),
      "Rendered history must contain document display name"
    );
  });
}

// Test 8: Cross-Document Session Resume Isolation
function testCrossDocumentResumeIsolation() {
  let activeJobInStorage = {
    jobId: "job_docA",
    documentSessionId: "doc_session_A",
    sourceMode: "slide",
    stage: "job"
  };

  let polledJobId = null;
  let statusSet = "";
  let activePres = { Name: "DocB.pptx" };

  const state = {
    jobId: "",
    documentSessionId: "doc_session_B",
    taskMode: "pptSlideAssistant",
    currentView: "home",
    activeTaskSlots: {}
  };

  const ctx = {
    state,
    loadActiveJob: () => activeJobInStorage,
    clearActiveJob: () => { activeJobInStorage = null; },
    getActivePresentation: () => activePres,
    helpers: {
      ...helpers,
      getDocumentSessionId: (pres) => pres.Name === "DocB.pptx" ? "doc_session_B" : "doc_session_A"
    },
    setSourceMode: () => {},
    setStatus: (msg) => { statusSet = msg; },
    setRunDisabled: () => {},
    setInterruptedRetryVisible: () => {},
    showProgressText: () => {},
    pollPptSlideJob: (id) => { polledJobId = id; },
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant"
  };

  const resumeJob = vm.runInNewContext(
    `(${functionSource("resumeJob")})`,
    ctx
  );

  // Attempt 1: Current presentation is DocB (session B), active job is from DocA (session A)
  resumeJob();
  assert.strictEqual(polledJobId, null, "Must NOT resume job belonging to different document session");
  assert.strictEqual(state.jobId, "", "state.jobId must remain empty");

  // Attempt 2: Switch current presentation to DocA (session A)
  activePres = { Name: "DocA.pptx" };
  resumeJob();
  assert.strictEqual(polledJobId, "job_docA", "Must resume job matching current document session");
  assert.strictEqual(state.jobId, "job_docA");
}

// Test 9: User notice on > 5 MiB archive skip
function testHistoryNoticeOnLargeResult() {
  const elements = {
    "result-output": { textContent: "", className: "", classList: { add: () => {}, remove: () => {} } },
    "status-line": { textContent: "" },
    "btn-cancel-ppt-slide-job": { hidden: false, disabled: false },
    "summary-result-section": { hidden: false }
  };
  const byId = (id) => elements[id] || { textContent: "", classList: { add: () => {}, remove: () => {} } };
  const state = {
    result: null,
    activeTaskSlots: {},
    documentSessionId: "doc_1",
    jobId: "job_oversize",
    historyOpen: false
  };

  const ctx = {
    state,
    byId,
    clearActiveJob: () => {},
    releaseTaskSlotsForJob: () => {},
    setPptJobActionVisibility: () => {},
    setRunDisabled: () => {},
    setStatus: (text) => { elements["status-line"].textContent = text; },
    renderResult: (res) => { state.result = res; },
    helpers
  };

  const finishJob = vm.runInNewContext(
    `(${functionSource("finishJob")})`,
    ctx
  );

  finishJob("job_oversize", {
    resultType: "document",
    deckTitle: "大型方案",
    historyNotice: "任务结果超过 5 MiB，未写入历史记录。"
  });

  assert.ok(
    elements["status-line"].textContent.includes("任务结果超过 5 MiB，未写入历史记录。"),
    "Status line must display historyNotice"
  );
}

// Test 10: Structure Review Task Slot Guard
function testStructureReviewTaskSlotGuard() {
  const slots = {};
  const host = "wpp";
  const taskType = "ppt.structure_review";
  const session1 = "doc_session_1";
  const session2 = "doc_session_2";

  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);
  helpers.claimTaskSlot(slots, host, taskType, session1, "job-s01");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), true);
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session2), false);

  helpers.releaseTaskSlot(slots, host, taskType, session1, "job-s01");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);
}

// Test 11: Structure Review Source Contract
function testStructureReviewSourceContract() {
  assert.ok(
    taskpaneHtml.includes("btn-view-structure-history") ||
      (taskpaneHtml.includes("structure-result-section") && taskpaneHtml.includes("btn-view-history")),
    "taskpane.html structure section must have a history view button"
  );

  assert.ok(
    !taskpaneSource.includes('if (!state.structureResult) {\n      byId("structure-result-output").textContent = failureMessage;\n    }'),
    "failStructureJob must unconditionally update structure-result-output and not freeze old result"
  );

  assert.ok(
    taskpaneSource.includes("state.structureResult = null;") ||
      taskpaneSource.includes("state.structureResult = null"),
    "submitStructureReviewJob or runPptStructureReview must clear state.structureResult upon valid submission"
  );
}

// Test 12: Structure Review Active Result Behavior With Existing Result
function testStructureReviewActiveResultBehaviorWithExistingResult() {
  const elements = {
    "structure-result-output": { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } } },
    "status-line": { textContent: "" },
    "btn-cancel-structure-review-job": { hidden: false, disabled: false },
    "btn-resubmit-structure-review": { hidden: true },
    "btn-copy-review-conclusion": { disabled: false },
    "btn-copy-recommended-outline": { disabled: false },
    "history-unread-badge": { textContent: "0", hidden: true },
    "structure-history-unread-badge": { textContent: "0", hidden: true },
    "structure-result-section": { hidden: false },
    "ppt-history-view": { hidden: true }
  };

  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } }, hidden: false, disabled: false };
    }
    return elements[id];
  };

  const state = {
    structureResult: { reviewConclusion: "旧审查结论", overallStoryline: "旧主线" },
    activeTaskSlots: {},
    documentSessionId: "doc_1",
    jobId: "job_struct_old",
    historyOpen: false,
    historyUnreadCount: 0,
    taskMode: "pptStructureReview"
  };

  const ctx = {
    state,
    byId,
    safeText: (v) => String(v || "").trim(),
    clearStructureActiveJob: () => {},
    setStructureJobActionVisibility: () => {},
    setRunDisabled: () => {},
    setStatus: (text) => { elements["status-line"].textContent = text; },
    renderStructureResult: (res) => {
      state.structureResult = res;
      elements["structure-result-output"].textContent = res.reviewConclusion || "结构审查已完成";
    },
    getActivePresentation: () => ({ Name: "演示文稿1.pptx" }),
    helpers,
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant"
  };

  const releaseTaskSlotsForJob = vm.runInNewContext(
    `(${functionSource("releaseTaskSlotsForJob")})`,
    ctx
  );
  ctx.releaseTaskSlotsForJob = releaseTaskSlotsForJob;

  const updateHistoryBadge = vm.runInNewContext(
    `(${functionSource("updateHistoryBadge")})`,
    ctx
  );
  ctx.updateHistoryBadge = updateHistoryBadge;

  const failStructureJob = vm.runInNewContext(
    `(${functionSource("failStructureJob")})`,
    ctx
  );

  const finishStructureJob = vm.runInNewContext(
    `(${functionSource("finishStructureJob")})`,
    ctx
  );

  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1", "job_struct_1");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1"), true);

  // Case 1: Failure must clear state.structureResult and output error message unconditionally
  failStructureJob("job_struct_1", "结构审查超时失败", "审查失败");
  assert.strictEqual(state.structureResult, null, "state.structureResult must be cleared on failure");
  assert.strictEqual(elements["structure-result-output"].textContent, "结构审查超时失败");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1"), false, "Slot must be released on failure");

  // Case 2: Successful finish
  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1", "job_struct_2");
  finishStructureJob("job_struct_2", { reviewConclusion: "全新审查结论" });
  assert.deepStrictEqual(state.structureResult, { reviewConclusion: "全新审查结论" });
  assert.strictEqual(elements["structure-result-output"].textContent, "全新审查结论");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1"), false, "Slot must be released on finish");

  // Case 3: Completion while viewing history updates badge and does not disrupt history view
  state.historyOpen = true;
  state.historyUnreadCount = 0;
  helpers.claimTaskSlot(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_1", "job_struct_3");
  finishStructureJob("job_struct_3", { reviewConclusion: "后台完成的审查" });
  assert.strictEqual(state.historyUnreadCount, 1);
  const badgeEl = elements["structure-history-unread-badge"] || elements["history-unread-badge"];
  assert.strictEqual(badgeEl.textContent, "1");
  assert.strictEqual(badgeEl.hidden, false);
}

// Test 13: Structure Review Cross-Document Resume Isolation
async function testStructureReviewCrossDocumentResumeIsolation() {
  let activeJobInStorage = {
    jobId: "job_struct_docA",
    documentSessionId: "doc_session_A",
    startedAt: 123456
  };

  let polledJobId = null;
  let activePres = { Name: "DocB.pptx" };

  const state = {
    jobId: "",
    documentSessionId: "doc_session_B",
    taskMode: "pptStructureReview",
    currentView: "home",
    activeTaskSlots: {}
  };

  const ctx = {
    state,
    byId: (id) => ({ value: "", textContent: "", hidden: false }),
    loadStructureActiveJob: () => activeJobInStorage,
    clearStructureActiveJob: () => { activeJobInStorage = null; },
    getActivePresentation: () => activePres,
    request: (url) => Promise.resolve({
      success: true,
      data: { jobId: "job_struct_docA", status: "running" }
    }),
    describeStructureProgress: () => ({ status: "审查中", detail: "已等待 5 秒" }),
    setStructureJobActionVisibility: () => {},
    helpers: {
      ...helpers,
      getDocumentSessionId: (pres) => pres.Name === "DocB.pptx" ? "doc_session_B" : "doc_session_A"
    },
    setStatus: () => {},
    setRunDisabled: () => {},
    pollStructureReviewJob: (id) => { polledJobId = id; },
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 5000,
    PPT_SLIDE_POLL_INTERVAL_MS: 1000
  };

  const resumeStructureReviewJob = vm.runInNewContext(
    `(${functionSource("resumeStructureReviewJob")})`,
    ctx
  );

  // Attempt 1: Current doc is DocB (session B), active job is from DocA (session A)
  await resumeStructureReviewJob();
  assert.strictEqual(polledJobId, null, "Must NOT resume structure review job belonging to different document session");
  assert.strictEqual(state.jobId, "");

  // Attempt 2: Switch to DocA (session A)
  activePres = { Name: "DocA.pptx" };
  await resumeStructureReviewJob();
  assert.strictEqual(state.jobId, "job_struct_docA", "Must resume structure review job for matching document session");
}

// Test 14: Structure Review History Rendering (includes jobId)
function testStructureReviewHistoryRendering() {
  const items = [
    {
      id: "hist_struct_1",
      taskType: "ppt.structure_review",
      jobId: "job-s1",
      completedAt: "2026-09-10T10:00:00Z",
      documentDisplayName: "技术架构.pptx",
      serviceName: "模型服务",
      modelName: "review-model",
      result: {
        resultType: "structure_review",
        reviewedRange: { startSlide: 1, endSlide: 10, totalSlides: 10 },
        reviewConclusion: "本次审查第 1–10 页，主线清晰。",
        overallStoryline: "整体架构推进有序",
        plainText: "本次审查第 1–10 页结论..."
      }
    }
  ];

  const html = helpers.renderHistoryList(items);
  assert.ok(html.includes("技术架构.pptx"), "History HTML must include document name");
  assert.ok(html.includes('data-history-id="hist_struct_1"'), "History HTML must include data-history-id");
  assert.ok(html.includes("审查") || html.includes("1–10"), "History HTML must include review info");
  assert.ok(html.includes("任务号：job-s1"), "History HTML must include job ID in card");
}

// Test 15: Multi-Window LocalStorage Isolation
function testStructureReviewMultiWindowLocalStorageIsolation() {
  const localStorageMock = (function() {
    let store = {};
    return {
      getItem: (k) => Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null,
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
      clear: () => { store = {}; },
      get length() { return Object.keys(store).length; },
      key: (i) => Object.keys(store)[i] || null,
      _dump: () => store
    };
  })();

  let activePres = { Name: "Doc1.pptx" };
  const state = { documentSessionId: "doc_session_1" };

  const ctx = {
    window: { localStorage: localStorageMock },
    state,
    helpers: {
      ...helpers,
      getDocumentSessionId: (pres) => pres && pres.Name === "Doc2.pptx" ? "doc_session_2" : "doc_session_1"
    },
    getActivePresentation: () => activePres,
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_STRUCTURE_ACTIVE_JOB_STORAGE_KEY: "ai-wps:wpp:ppt.structure_review:active_job"
  };

  const getStructureActiveJobStorageKey = vm.runInNewContext(
    `(${functionSource("getStructureActiveJobStorageKey")})`,
    ctx
  );
  ctx.getStructureActiveJobStorageKey = getStructureActiveJobStorageKey;
  const saveStructureActiveJob = vm.runInNewContext(
    `(${functionSource("saveStructureActiveJob")})`,
    ctx
  );
  ctx.saveStructureActiveJob = saveStructureActiveJob;
  const loadStructureActiveJob = vm.runInNewContext(
    `(${functionSource("loadStructureActiveJob")})`,
    ctx
  );
  ctx.loadStructureActiveJob = loadStructureActiveJob;
  const clearStructureActiveJob = vm.runInNewContext(
    `(${functionSource("clearStructureActiveJob")})`,
    ctx
  );
  ctx.clearStructureActiveJob = clearStructureActiveJob;

  // 1. Save active job for doc 1
  saveStructureActiveJob({ jobId: "job-doc-1", documentSessionId: "doc_session_1", startedAt: 1000 });
  // 2. Save active job for doc 2
  activePres = { Name: "Doc2.pptx" };
  state.documentSessionId = "doc_session_2";
  saveStructureActiveJob({ jobId: "job-doc-2", documentSessionId: "doc_session_2", startedAt: 2000 });

  // 3. Verify storage keys are distinct
  assert.strictEqual(
    JSON.parse(localStorageMock.getItem("ai-wps:wpp:ppt.structure_review:doc_session_1")).jobId,
    "job-doc-1"
  );
  assert.strictEqual(
    JSON.parse(localStorageMock.getItem("ai-wps:wpp:ppt.structure_review:doc_session_2")).jobId,
    "job-doc-2"
  );

  // 4. Loading for Doc2 returns Doc2's job
  const job2 = loadStructureActiveJob("doc_session_2");
  assert.strictEqual(job2.jobId, "job-doc-2");

  // 5. Switching active pres back to Doc1 and loading returns Doc1's job
  activePres = { Name: "Doc1.pptx" };
  state.documentSessionId = "doc_session_1";
  const job1 = loadStructureActiveJob("doc_session_1");
  assert.strictEqual(job1.jobId, "job-doc-1");

  // 6. Clearing Doc1 does NOT delete Doc2
  clearStructureActiveJob("job-doc-1", "doc_session_1");
  assert.strictEqual(loadStructureActiveJob("doc_session_1"), null);
  assert.strictEqual(loadStructureActiveJob("doc_session_2").jobId, "job-doc-2");
}

// Test 16: Presentation Switching During Finish Isolation
function testStructureReviewPresentationSwitchingDuringFinish() {
  const elements = {
    "structure-result-output": { textContent: "初始内容" },
    "status-line": { textContent: "" },
    "btn-copy-review-conclusion": { disabled: false },
    "btn-copy-recommended-outline": { disabled: false }
  };
  const byId = (id) => elements[id] || { disabled: false, textContent: "" };

  let activePres = { Name: "Doc2.pptx" };
  const state = {
    documentSessionId: "doc_session_2",
    structureResult: null,
    structureResultsBySession: {},
    jobId: ""
  };

  let renderedResults = [];

  const ctx = {
    state,
    byId,
    clearStructureActiveJob: () => {},
    releaseTaskSlotsForJob: () => {},
    setStructureJobActionVisibility: () => {},
    setRunDisabled: () => {},
    setStatus: () => {},
    renderStructureResult: (res) => {
      renderedResults.push(res);
      elements["structure-result-output"].textContent = res.reviewConclusion;
    },
    getActivePresentation: () => activePres,
    helpers: {
      ...helpers,
      getDocumentSessionId: (pres) => pres && pres.Name === "Doc2.pptx" ? "doc_session_2" : "doc_session_1"
    }
  };

  const finishStructureJob = vm.runInNewContext(
    `(${functionSource("finishStructureJob")})`,
    ctx
  );

  // Background job for Doc1 finishes while user is on Doc2
  finishStructureJob("job-doc-1", { reviewConclusion: "Doc1后台结果" }, "doc_session_1");

  // Verify: Doc1 result stored in session cache, but foreground Doc2 UI remains untouched
  assert.deepStrictEqual(state.structureResultsBySession["doc_session_1"], { reviewConclusion: "Doc1后台结果" });
  assert.strictEqual(state.structureResult, null, "Foreground state.structureResult must not be overwritten");
  assert.strictEqual(elements["structure-result-output"].textContent, "初始内容", "Foreground text must not be overwritten");
  assert.strictEqual(renderedResults.length, 0, "Foreground renderer must not be called");

  // Now switch presentation to Doc1 and finish a job for Doc1
  activePres = { Name: "Doc1.pptx" };
  state.documentSessionId = "doc_session_1";
  finishStructureJob("job-doc-1-fg", { reviewConclusion: "Doc1前台结果" }, "doc_session_1");

  assert.strictEqual(state.structureResult.reviewConclusion, "Doc1前台结果");
  assert.strictEqual(elements["structure-result-output"].textContent, "Doc1前台结果");
  assert.strictEqual(renderedResults.length, 1);
}

// Test 17: Resuming Completed Task Clears Storage Without Populating Active Results View
async function testStructureReviewResumeCompletedClearsStorageAndLeavesUIClean() {
  let clearedJob = null;
  const elements = {
    "structure-result-output": { textContent: "默认空状态" },
    "status-line": { textContent: "" },
    "btn-resubmit-structure-review": { hidden: true }
  };
  const byId = (id) => elements[id] || { hidden: true, textContent: "" };

  const state = {
    jobId: "",
    documentSessionId: "doc_session_1",
    structureResult: null,
    currentView: "home",
    activeTaskSlots: {}
  };

  const ctx = {
    state,
    byId,
    loadStructureActiveJob: () => ({ jobId: "job-completed-01", documentSessionId: "doc_session_1" }),
    clearStructureActiveJob: (id) => { clearedJob = id; },
    getActivePresentation: () => ({ Name: "Doc1.pptx" }),
    request: (url) => Promise.resolve({
      success: true,
      data: {
        jobId: "job-completed-01",
        status: "completed",
        result: { reviewConclusion: "历史旧结果，不应进活动视图" }
      }
    }),
    describeStructureProgress: () => ({ status: "", detail: "" }),
    setStructureJobActionVisibility: () => {},
    helpers: {
      ...helpers,
      getDocumentSessionId: () => "doc_session_1"
    },
    setStatus: () => {},
    setRunDisabled: () => {},
    pollStructureReviewJob: () => { assert.fail("Must not poll completed job"); },
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 5000
  };

  const resumeStructureReviewJob = vm.runInNewContext(
    `(${functionSource("resumeStructureReviewJob")})`,
    ctx
  );

  await resumeStructureReviewJob();

  // Must clear active storage
  assert.strictEqual(clearedJob, "job-completed-01", "Storage must be cleared for completed job");
  // Must NOT populate state.jobId
  assert.strictEqual(state.jobId, "", "state.jobId must remain empty");
  // Must NOT set state.structureResult
  assert.strictEqual(state.structureResult, null, "state.structureResult must remain null");
  // Must NOT touch structure-result-output
  assert.strictEqual(elements["structure-result-output"].textContent, "默认空状态");
}

// Test 18: Resuming Running Task Sets Active State And Begins Polling
async function testStructureReviewResumeRunningSetsActiveStateAndBeginsPolling() {
  let polledJob = null;
  const elements = {
    "structure-result-output": { textContent: "" },
    "status-line": { textContent: "" },
    "btn-resubmit-structure-review": { hidden: false }
  };
  const byId = (id) => elements[id] || { hidden: true, textContent: "", disabled: false };

  const state = {
    jobId: "",
    documentSessionId: "doc_session_1",
    currentView: "home",
    activeTaskSlots: {}
  };

  const ctx = {
    state,
    byId,
    loadStructureActiveJob: () => ({ jobId: "job-running-01", documentSessionId: "doc_session_1", startedAt: 1000 }),
    clearStructureActiveJob: () => {},
    getActivePresentation: () => ({ Name: "Doc1.pptx" }),
    request: (url) => Promise.resolve({
      success: true,
      data: {
        jobId: "job-running-01",
        status: "running",
        queuePosition: 0,
        elapsedSeconds: 5
      }
    }),
    describeStructureProgress: (job, id) => ({ status: "正在审查中...", detail: "已等待 5 秒" }),
    setStructureJobActionVisibility: () => {},
    helpers: {
      ...helpers,
      getDocumentSessionId: () => "doc_session_1",
      claimTaskSlot: helpers.claimTaskSlot
    },
    setStatus: (s) => { elements["status-line"].textContent = s; },
    setRunDisabled: () => {},
    pollStructureReviewJob: (id) => { polledJob = id; },
    setTimeout: (fn) => fn(),
    PPT_STRUCTURE_WORKFLOW_TASK_TYPE: "ppt.structure_review",
    PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS: 5000,
    PPT_SLIDE_POLL_INTERVAL_MS: 0
  };

  const resumeStructureReviewJob = vm.runInNewContext(
    `(${functionSource("resumeStructureReviewJob")})`,
    ctx
  );

  await resumeStructureReviewJob();

  assert.strictEqual(state.jobId, "job-running-01", "state.jobId must be set to running job");
  assert.strictEqual(state.resumeExpected, true, "state.resumeExpected must be true");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wpp", "ppt.structure_review", "doc_session_1"), true, "Slot must be claimed");
  assert.strictEqual(polledJob, "job-running-01", "Polling must be initiated");
}

async function runAll() {
  testDocumentSessionIdentification();
  testDocumentDisplayName();
  testActiveTaskSlotGuard();
  testActiveResultLifecycleSourceContract();
  testHistoryRenderingHelper();
  testActiveResultBehaviorWithExistingResult();
  testCrossDocumentResumeIsolation();
  testHistoryNoticeOnLargeResult();
  testStructureReviewTaskSlotGuard();
  testStructureReviewSourceContract();
  testStructureReviewActiveResultBehaviorWithExistingResult();
  await testStructureReviewCrossDocumentResumeIsolation();
  testStructureReviewHistoryRendering();
  testStructureReviewMultiWindowLocalStorageIsolation();
  testStructureReviewPresentationSwitchingDuringFinish();
  await testStructureReviewResumeCompletedClearsStorageAndLeavesUIClean();
  await testStructureReviewResumeRunningSetsActiveStateAndBeginsPolling();
  await testHistoryListEnvelopeParsing();
  console.log("All PPT active result and history tests passed!");
}

runAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
