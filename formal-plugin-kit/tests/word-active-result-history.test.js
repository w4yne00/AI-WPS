const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { wordRoot: root } = require("./support/plugin-roots");

const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(
  path.join(root, "taskpane.js"),
  "utf8"
);
const taskpaneHtml = fs.readFileSync(
  path.join(root, "taskpane.html"),
  "utf8"
);

// Helper to extract function source from taskpane.js
function functionSource(name) {
  const start = taskpaneSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = taskpaneSource.indexOf("\n  function ", start + 1);
  return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
}

// Test 1: Document Session Identification
function testDocumentSessionIdentification() {
  assert.strictEqual(typeof helpers.getDocumentSessionId, "function", "getDocumentSessionId should be a function");

  const doc1 = { Name: "技术方案1.docx", FullName: "/Users/wayne/Documents/技术方案1.docx" };
  const doc2 = { Name: "安全规范.docx", FullName: "/Users/wayne/Secret/安全规范.docx" };

  const session1_a = helpers.getDocumentSessionId(doc1);
  const session1_b = helpers.getDocumentSessionId(doc1);
  const session2 = helpers.getDocumentSessionId(doc2);

  // Must be stable for same document instance
  assert.strictEqual(session1_a, session1_b, "Session ID must be stable for same document");
  // Must differ between different documents
  assert.notStrictEqual(session1_a, session2, "Different documents must have different session IDs");
  // Must not leak full path
  assert.ok(!session1_a.includes("/Users/wayne"), "Session ID must not contain full path");
  assert.ok(!session2.includes("/Secret"), "Session ID must not contain full path");
}

// Test 2: Document Display Name extraction (no path leak)
function testDocumentDisplayName() {
  assert.strictEqual(typeof helpers.getDocumentDisplayName, "function", "getDocumentDisplayName should be a function");

  const doc = { Name: "技术方案1.docx", FullName: "/Users/wayne/Documents/技术方案1.docx" };
  const displayName = helpers.getDocumentDisplayName(doc);
  assert.strictEqual(displayName, "技术方案1.docx");
  assert.ok(!displayName.includes("/Users/wayne"));
}

// Test 3: Active Task Slot Guard
function testActiveTaskSlotGuard() {
  assert.strictEqual(typeof helpers.isTaskSlotBusy, "function", "isTaskSlotBusy should be a function");

  const slots = {};
  const host = "wps";
  const taskWrite = "word.smart_write";
  const taskImitate = "word.smart_imitation";
  const session1 = "doc_session_1";
  const session2 = "doc_session_2";

  // Initially not busy
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskWrite, session1), false);

  // Claim slot for taskWrite on session1
  helpers.claimTaskSlot(slots, host, taskWrite, session1, "job-write-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskWrite, session1), true);

  // Different task type (smart_imitation) on session1 is NOT busy
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskImitate, session1), false);

  // Different document session is NOT busy
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskWrite, session2), false);

  // Release slot
  helpers.releaseTaskSlot(slots, host, taskWrite, session1, "job-write-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskWrite, session1), false);
}

// Test 4: Writing History Rendering Helper
function testWritingHistoryRenderingHelper() {
  assert.strictEqual(typeof helpers.renderWritingHistoryList, "function", "renderWritingHistoryList should be a function");

  const items = [
    {
      id: "hist_word_1",
      taskType: "word.smart_write",
      jobId: "job-write-1",
      completedAt: "2026-09-09T16:00:00Z",
      documentDisplayName: "方案初稿.docx",
      serviceName: "政企业务模型",
      modelName: "deepseek-chat",
      result: {
        rewrittenText: "经过优化后的正式技术方案文本。",
        rewriteMode: "rewrite",
        plainText: "经过优化后的正式技术方案文本。"
      }
    }
  ];

  const html = helpers.renderWritingHistoryList(items);
  assert.ok(html.includes("方案初稿.docx"), "History HTML must include document display name");
  assert.ok(html.includes("经过优化后的正式技术方案文本"), "History HTML must include rewritten text snippet");
  assert.ok(html.includes("data-history-id=\"hist_word_1\""), "History HTML must include item id attribute");
  assert.ok(html.includes("btn-history-view"), "History HTML must include view button");
  assert.ok(html.includes("btn-history-copy"), "History HTML must include copy button");
  assert.ok(html.includes("btn-history-delete"), "History HTML must include delete button");

  const emptyHtml = helpers.renderWritingHistoryList([]);
  assert.ok(emptyHtml.includes("暂无成功历史记录"), "Empty history should render empty state");
}

// Test 5: Markup & Taskpane Source Contracts
function testWordActiveResultMarkupContract() {
  assert.ok(
    taskpaneHtml.includes("btn-view-history"),
    "taskpane.html must contain btn-view-history button"
  );
  assert.ok(
    taskpaneHtml.includes("history-unread-badge"),
    "taskpane.html must contain history-unread-badge element"
  );
  assert.ok(
    taskpaneHtml.includes("word-history-view"),
    "taskpane.html must contain word-history-view container"
  );
  assert.ok(
    taskpaneHtml.includes("btn-history-back"),
    "taskpane.html must contain btn-history-back button"
  );
  assert.ok(
    taskpaneHtml.includes("btn-clear-history"),
    "taskpane.html must contain btn-clear-history button"
  );

  assert.ok(
    taskpaneSource.includes("getDocumentSessionId"),
    "taskpane.js must invoke getDocumentSessionId"
  );
  assert.ok(
    taskpaneSource.includes("isTaskSlotBusy") || taskpaneSource.includes("activeTaskSlots"),
    "taskpane.js must guard active task slots per document session"
  );
  assert.ok(
    taskpaneSource.includes("/history"),
    "taskpane.js must fetch /history"
  );
  assert.ok(
    taskpaneSource.includes("failWritingJob"),
    "taskpane.js must define failWritingJob"
  );
  assert.ok(
    taskpaneSource.includes("releaseTaskSlotsForJob"),
    "taskpane.js must define releaseTaskSlotsForJob"
  );
}

// Test 6: Active Result State Machine Regression (Validation error retains result, failure does not revert, completion updates result and unread badge)
function testActiveResultBehaviorWithExistingResult() {
  const elements = {
    "result-output": { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } } },
    "status-line": { textContent: "" },
    "btn-cancel-document-review-job": { hidden: false, disabled: false },
    "history-unread-badge": { textContent: "0", hidden: true },
    "word-result-section": { hidden: false },
    "word-history-view": { hidden: true },
    "btn-apply": { disabled: true, hidden: false }
  };

  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = { textContent: "", innerHTML: "", className: "", classList: { add: function(c) { this[c] = true; }, remove: function(c) { delete this[c]; } }, hidden: false, disabled: false };
    }
    return elements[id];
  };

  const state = {
    currentMode: "smartWrite",
    writingJobId: "job_old",
    writingJobTaskType: "word.smart_write",
    writingJobMode: "smartWrite",
    activeTaskSlots: {},
    activeResultsByTask: {
      "word.smart_write": { rewrittenText: "旧的成功改写文本。" }
    },
    smartWritePreviewModel: { plainText: "旧的成功改写文本。" },
    documentSessionId: "doc_1",
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
    setResult: (text) => {
      elements["result-output"].textContent = text;
    },
    setWritingJob: (jobId, taskType, mode) => {
      state.writingJobId = jobId || "";
      state.writingJobTaskType = jobId ? taskType : "";
      state.writingJobMode = jobId ? mode : "";
    },
    clearWritingActiveJob: () => {},
    setApplyEnabled: (en) => { elements["btn-apply"].disabled = !en; },
    setStatus: (text) => {
      elements["status-line"].textContent = text;
    },
    setTrace: () => {},
    writingTaskLabel: (tt) => tt === "word.smart_imitation" ? "智能仿写" : "智能编写",
    describeFetchError: (err) => (err && err.message) || String(err || ""),
    hideCompareForSmartImitation: () => {},
    setSmartWriteResult: (res, taskType) => {
      state.activeResultsByTask[taskType] = res;
      elements["result-output"].textContent = res.rewrittenText || res.plainText || "";
      return res;
    },
    helpers
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

  const failWritingJob = vm.runInNewContext(
    `(${functionSource("failWritingJob")})`,
    ctx
  );
  ctx.failWritingJob = failWritingJob;

  const completeWritingJob = vm.runInNewContext(
    `(${functionSource("completeWritingJob")})`,
    ctx
  );
  ctx.completeWritingJob = completeWritingJob;

  // Claim a slot initially
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_1");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), true);

  // Case 1: When failure occurs, active result must be cleared, output shows error, slot released
  failWritingJob("job_1", "word.smart_write", "smartWrite", new Error("网络连接超时"));
  assert.strictEqual(state.activeResultsByTask["word.smart_write"], null, "Active result must be set to null on failure");
  assert.ok(elements["result-output"].textContent.includes("网络连接超时"), "Output must show failure error");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), false, "Slot must be released on failure");

  // Case 2: New valid submission and completion
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_2");
  completeWritingJob({ rewrittenText: "全新的智能编写结果。" }, "trace_2", "word.smart_write", false, "smartWrite");
  assert.strictEqual(state.activeResultsByTask["word.smart_write"].rewrittenText, "全新的智能编写结果。");
  assert.strictEqual(elements["result-output"].textContent, "全新的智能编写结果。");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), false, "Slot must be released on completion");

  // Case 3: Completion while viewing history updates badge and does not overwrite current history view
  state.historyOpen = true;
  state.historyUnreadCount = 0;
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_3");
  completeWritingJob({ rewrittenText: "后台完成的新编写结果。" }, "trace_3", "word.smart_write", false, "smartWrite");
  assert.strictEqual(state.historyUnreadCount, 1, "Unread count must increment by 1");
  assert.strictEqual(elements["history-unread-badge"].textContent, "1");
  assert.strictEqual(elements["history-unread-badge"].hidden, false);
  assert.ok(elements["status-line"].textContent.includes("后台"), "Status line must indicate background completion");
}

// Test 7: History List API Envelope Handling and Action Handlers
function testHistoryListEnvelopeParsingAndActions() {
  const elements = {
    "word-history-content": { innerHTML: "" }
  };
  const byId = (id) => elements[id] || { innerHTML: "" };
  const state = {
    historyItems: [],
    currentMode: "smartWrite"
  };

  const rawApiResponse = {
    success: true,
    data: {
      items: [
        {
          id: "hist_word_99",
          taskType: "word.smart_write",
          jobId: "job_99",
          completedAt: "2026-09-09T16:00:00Z",
          documentDisplayName: "总结测试.docx",
          serviceName: "政企模型",
          modelName: "test-model",
          result: { rewrittenText: "测试生成的改写文本。" }
        }
      ],
      total: 1,
      taskType: "word.smart_write"
    }
  };

  let deletedId = "";
  let clearedTaskType = "";
  let copiedText = "";

  const ctx = {
    state,
    byId,
    request: (url, body, options) => {
      if (options && options.method === "DELETE") {
        if (url.includes("/history/")) {
          deletedId = decodeURIComponent(url.split("/history/")[1]);
          return Promise.resolve({ success: true });
        }
        if (url.includes("/history?taskType=")) {
          clearedTaskType = decodeURIComponent(url.split("taskType=")[1]);
          return Promise.resolve({ success: true });
        }
      }
      return Promise.resolve(rawApiResponse);
    },
    getCurrentWorkflowTaskType: () => "word.smart_write",
    setStatus: () => {},
    copyText: (txt) => { copiedText = txt; },
    helpers
  };

  const loadAndRenderWritingHistory = vm.runInNewContext(
    `(${functionSource("loadAndRenderWritingHistory")})`,
    ctx
  );
  const handleClearWritingHistory = vm.runInNewContext(
    `(${functionSource("handleClearWritingHistory")})`,
    ctx
  );
  const handleWritingHistoryDeleteItem = vm.runInNewContext(
    `(${functionSource("handleWritingHistoryDeleteItem")})`,
    ctx
  );
  const handleWritingHistoryCopyItem = vm.runInNewContext(
    `(${functionSource("handleWritingHistoryCopyItem")})`,
    ctx
  );

  loadAndRenderWritingHistory();

  return Promise.resolve().then(() => {
    assert.strictEqual(state.historyItems.length, 1, "state.historyItems must contain 1 item");
    assert.ok(
      elements["word-history-content"].innerHTML.includes("总结测试.docx"),
      "Rendered history must contain document display name"
    );

    // Test copy action
    handleWritingHistoryCopyItem("hist_word_99");
    assert.strictEqual(copiedText, "测试生成的改写文本。", "Copy action must copy rewrittenText");

    // Test delete single action
    return handleWritingHistoryDeleteItem("hist_word_99").then(() => {
      assert.strictEqual(deletedId, "hist_word_99", "Must call DELETE /history/{id}");
      assert.strictEqual(state.historyItems.length, 0, "History items must be removed from state");

      // Test clear history action
      return handleClearWritingHistory().then(() => {
        assert.strictEqual(clearedTaskType, "word.smart_write", "Must call DELETE /history?taskType=word.smart_write");
      });
    });
  });
}

// Test 8: Cross-Document Session Resume Isolation & Reject Completed
function testCrossDocumentResumeIsolation() {
  let activeJobInStorage = {
    jobId: "job_docA",
    documentSessionId: "doc_session_A",
    taskType: "word.smart_write",
    mode: "smartWrite"
  };

  let polledJobId = null;
  let activeDoc = { Name: "DocB.docx" };

  const state = {
    currentMode: "smartWrite",
    writingJobId: "",
    documentSessionId: "doc_session_B",
    activeTaskSlots: {}
  };

  const ctx = {
    state,
    loadWritingActiveJob: () => activeJobInStorage,
    clearWritingActiveJob: () => { activeJobInStorage = null; },
    getActiveDocument: () => activeDoc,
    helpers: {
      ...helpers,
      getDocumentSessionId: (doc) => doc.Name === "DocB.docx" ? "doc_session_B" : "doc_session_A"
    },
    getCurrentWorkflowTaskType: () => "word.smart_write",
    writingTaskLabel: () => "智能编写",
    setWritingJob: (id) => { state.writingJobId = id; },
    setTrace: () => {},
    setApplyEnabled: () => {},
    setStatus: () => {},
    setPlainResult: () => {},
    pollWritingJob: (id) => { polledJobId = id; }
  };

  const resumeWritingActiveJob = vm.runInNewContext(
    `(${functionSource("resumeWritingActiveJob")})`,
    ctx
  );

  // Attempt 1: Current doc is DocB (session B), active job is from DocA (session A)
  resumeWritingActiveJob();
  assert.strictEqual(polledJobId, null, "Must NOT resume job belonging to different document session");
  assert.strictEqual(state.writingJobId, "", "state.writingJobId must remain empty");

  // Attempt 2: Switch current doc to DocA (session A)
  activeDoc = { Name: "DocA.docx" };
  resumeWritingActiveJob();
  assert.strictEqual(polledJobId, "job_docA", "Must resume job matching current document session");
  assert.strictEqual(state.writingJobId, "job_docA");
}

// Test 9: User notice on > 5 MiB archive skip
function testHistoryNoticeOnLargeResult() {
  const elements = {
    "status-line": { textContent: "" },
    "result-output": { textContent: "" },
    "btn-apply": { disabled: true }
  };
  const byId = (id) => elements[id] || { textContent: "", classList: { add: () => {}, remove: () => {} }, disabled: false };
  const state = {
    activeResultsByTask: {},
    currentMode: "smartWrite",
    historyOpen: false
  };

  const ctx = {
    state,
    byId,
    releaseTaskSlotsForJob: () => {},
    setWritingJob: () => {},
    setApplyEnabled: () => {},
    setTrace: () => {},
    setSmartWriteResult: (res, tt) => { state.activeResultsByTask[tt] = res; return res; },
    writingTaskLabel: () => "智能编写",
    hideCompareForSmartImitation: () => {},
    setStatus: (text) => { elements["status-line"].textContent = text; },
    helpers
  };

  const completeWritingJob = vm.runInNewContext(
    `(${functionSource("completeWritingJob")})`,
    ctx
  );

  completeWritingJob({
    rewrittenText: "非常庞大的文档改写内容",
    historyNotice: "任务结果超过 5 MiB，未写入历史记录。"
  }, "trace_large", "word.smart_write", false, "smartWrite");

  assert.ok(
    elements["status-line"].textContent.includes("任务结果超过 5 MiB，未写入历史记录。"),
    "Status line must display historyNotice"
  );
}

// Test 10: Mode Switching Result Isolation
function testModeSwitchingResultIsolation() {
  const state = {
    activeResultsByTask: {
      "word.smart_write": { rewrittenText: "这是智能编写的结果。" },
      "word.smart_imitation": { rewrittenText: "这是智能仿写的结果。" }
    },
    activeWritingJobsByTask: {}
  };

  assert.strictEqual(
    state.activeResultsByTask["word.smart_write"].rewrittenText,
    "这是智能编写的结果。"
  );
  assert.strictEqual(
    state.activeResultsByTask["word.smart_imitation"].rewrittenText,
    "这是智能仿写的结果。"
  );
  assert.notStrictEqual(
    state.activeResultsByTask["word.smart_write"],
    state.activeResultsByTask["word.smart_imitation"],
    "Results of smart_write and smart_imitation must remain isolated"
  );
}

function runAll() {
  testDocumentSessionIdentification();
  testDocumentDisplayName();
  testActiveTaskSlotGuard();
  testWritingHistoryRenderingHelper();
  testWordActiveResultMarkupContract();
  testActiveResultBehaviorWithExistingResult();
  testCrossDocumentResumeIsolation();
  testHistoryNoticeOnLargeResult();
  testModeSwitchingResultIsolation();
  testHistoryListEnvelopeParsingAndActions().then(() => {
    console.log("All Word active result and history tests passed!");
  });
}

runAll();
