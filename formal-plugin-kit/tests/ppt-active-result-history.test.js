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
    PPT_WORKFLOW_TASK_TYPE: "ppt.slide_assistant"
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

function runAll() {
  testDocumentSessionIdentification();
  testDocumentDisplayName();
  testActiveTaskSlotGuard();
  testActiveResultLifecycleSourceContract();
  testHistoryRenderingHelper();
  testActiveResultBehaviorWithExistingResult();
  testCrossDocumentResumeIsolation();
  testHistoryNoticeOnLargeResult();
  testHistoryListEnvelopeParsing().then(() => {
    console.log("All PPT active result and history tests passed!");
  });
}

runAll();
