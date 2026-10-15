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
  let start = taskpaneSource.indexOf(`  function ${name}(`);
  if (start < 0) {
    start = taskpaneSource.indexOf(`function ${name}(`);
  }
  assert.ok(start >= 0, `missing function ${name}`);
  const next = taskpaneSource.indexOf("\n  function ", start + 3);
  return taskpaneSource.slice(start, next === -1 ? taskpaneSource.length : next);
}

function createBaseContext(initialOverrides = {}) {
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        innerHTML: "",
        value: "",
        className: "",
        classList: {
          classes: new Set(),
          add: function(c) { this.classes.add(c); this[c] = true; },
          remove: function(c) { this.classes.delete(c); delete this[c]; },
          toggle: function(c, force) {
            if (force === undefined) {
              if (this.classes.has(c)) { this.classes.delete(c); delete this[c]; }
              else { this.classes.add(c); this[c] = true; }
            } else if (force) {
              this.classes.add(c); this[c] = true;
            } else {
              this.classes.delete(c); delete this[c];
            }
          },
          contains: function(c) { return this.classes.has(c); }
        },
        hidden: false,
        disabled: false,
        setAttribute: function(attr, val) { this[attr] = val; },
        getAttribute: function(attr) { return this[attr]; },
        addEventListener: function() {}
      };
    }
    return elements[id];
  };

  const state = {
    currentMode: "smartWrite",
    lastTaskMode: "smartWrite",
    writingJobId: "",
    writingJobTaskType: "",
    writingJobMode: "",
    activeTaskSlots: {},
    activeWritingJobs: {},
    activeWritingJobsByTask: {},
    activeResults: {},
    activeResultsByTask: {},
    smartWritePreviewModel: null,
    rewriteResult: null,
    latestDocumentPayload: { text: "选中的原文" },
    documentSessionId: "doc_1",
    historyOpen: false,
    historyUnreadCount: 0,
    historyItems: [],
    historyTaskType: "word.smart_write",
    historyLoadSequence: 0,
    pendingApplyAction: "",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    adapterHealthStatus: "healthy",
    ...(initialOverrides.state || {})
  };

  const ctx = {
    state,
    byId,
    document: {
      body: {
        attributes: {},
        setAttribute: function(attr, val) { this.attributes[attr] = val; },
        getAttribute: function(attr) { return this.attributes[attr]; }
      }
    },
    safeText: (v) => String(v || "").trim(),
    request: (url, body, options) => Promise.resolve({ success: true, data: { items: [] } }),
    setPlainResult: (text) => {
      byId("result-output").textContent = text;
    },
    setResult: (text) => {
      byId("result-output").textContent = text;
    },
    setWritingJob: (jobId, taskType, mode) => {
      state.writingJobId = jobId || "";
      state.writingJobTaskType = jobId ? (taskType || "") : "";
      state.writingJobMode = jobId ? (mode || "") : "";
    },
    clearWritingActiveJob: (jobId, taskType, docSessionId) => {},
    saveWritingActiveJob: (record) => {},
    loadWritingActiveJob: () => null,
    setModelTaskBusy: (busy) => {},
    setApplyEnabled: (en) => {
      byId("btn-apply").disabled = !en;
    },
    setStatus: (text) => {
      byId("status-line").textContent = text;
    },
    setTrace: (traceId) => {
      byId("trace-line").textContent = traceId || "";
    },
    recordTaskFirstRender: () => {},
    writingTaskLabel: (tt) => tt === "word.smart_imitation" ? "智能仿写" : "智能编写",
    describeFetchError: (err) => (err && err.message) || String(err || ""),
    hideCompareForSmartImitation: () => {},
    resetSmartWritePreviewState: () => {},
    resetDocumentReviewState: () => {},
    setInterruptedRetryVisible: () => {},
    closeTaskModelConfigMenu: () => {},
    switchView: () => {},
    renderWorkflowProfileStrip: () => {},
    renderWorkflowProfileManager: () => {},
    loadWorkflowProfiles: () => {},
    renderFullDocumentReviewEntry: () => {},
    restoreWritingPolicyScene: () => {},
    setWritingPolicyView: () => {},
    loadWritingPolicySummary: () => {},
    updateRewritePromptPreview: () => {},
    fillSmartImitationTemplateFromSelection: () => {},
    getActiveDocument: () => ({ Name: state.documentSessionId, FullName: state.documentSessionId }),
    getCurrentWorkflowTaskType: () => state.currentMode === "smartImitation" ? "word.smart_imitation" : "word.smart_write",
    setSmartWriteResult: (res, taskType) => {
      const activeRes = res || {};
      state.activeResultsByTask[taskType] = activeRes;
      byId("result-output").textContent = activeRes.rewrittenText || activeRes.plainText || "";
      return activeRes;
    },
    pollWritingJob: () => {},
    helpers: {
      ...helpers,
      getDocumentSessionId: (doc) => {
        if (!doc) return state.documentSessionId || "default";
        if (typeof doc === "string") return doc;
        if (doc.__sessionId) return doc.__sessionId;
        if (doc.Name === state.documentSessionId || doc.FullName === state.documentSessionId) {
          return state.documentSessionId;
        }
        return helpers.getDocumentSessionId(doc);
      }
    },
    modeConfig: {
      smartWrite: {
        title: "智能编写",
        showRewriteOptions: true,
        showInstruction: true,
        showTemplate: true,
        styleLabel: "表达风格",
        primaryText: "开始改写"
      },
      smartImitation: {
        title: "智能仿写",
        showInstruction: true,
        showSmartImitationOptions: true,
        styleLabel: "仿写风格",
        primaryText: "开始仿写"
      },
      settings: {
        title: "设置"
      }
    },
    ...(initialOverrides.ctx || {})
  };

  const fns = [
    "getWritingDocTaskKey",
    "isCurrentWritingJob",
    "getActiveWritingJobRecord",
    "setActiveWritingJobRecord",
    "getActiveResultRecord",
    "setActiveResultRecord",
    "releaseTaskSlotsForJob",
    "startWritingJob",
    "updateHistoryBadge",
    "failWritingJob",
    "completeWritingJob",
    "switchWordHistoryView",
    "loadAndRenderWritingHistory",
    "handleClearWritingHistory",
    "handleWritingHistoryDeleteItem",
    "handleWritingHistoryCopyItem",
    "resumeWritingActiveJob",
    "setMaterialImportVisible",
    "switchMode",
    "applyRewrite",
    "applyPreview"
  ];

  for (const fn of fns) {
    if (!ctx[fn]) {
      ctx[fn] = vm.runInNewContext(`(${functionSource(fn)}\n)`, ctx);
    }
  }

  return { ctx, state, elements, byId };
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

  // WPS may return a fresh JS proxy for the same open document on each access.
  const doc1FreshProxy = { Name: "技术方案1.docx", FullName: "/Users/wayne/Documents/技术方案1.docx" };
  const session1_fresh = helpers.getDocumentSessionId(doc1FreshProxy);
  assert.strictEqual(
    session1_fresh,
    session1_a,
    "Session ID must stay stable across different WPS proxies for the same document"
  );
}

function testFreshProxyCompletionRendersCurrentWritingResult() {
  const submittedDocument = {
    Name: "技术方案.docx",
    FullName: "/data/home/cloud/Documents/技术方案.docx"
  };
  const completionDocumentProxy = {
    Name: "技术方案.docx",
    FullName: "/data/home/cloud/Documents/技术方案.docx"
  };
  const submittedSession = helpers.getDocumentSessionId(submittedDocument);
  const { ctx, state, byId } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: submittedSession,
      writingJobId: "job-fresh-proxy",
      writingJobTaskType: "word.smart_write",
      writingJobMode: "smartWrite"
    },
    ctx: {
      getActiveDocument: () => completionDocumentProxy,
      helpers
    }
  });

  ctx.completeWritingJob(
    { rewrittenText: "## 当前任务结果\n\n- 已正确显示" },
    "trace-fresh-proxy",
    "word.smart_write",
    false,
    "smartWrite",
    "job-fresh-proxy",
    submittedSession
  );

  assert.strictEqual(
    byId("result-output").textContent,
    "## 当前任务结果\n\n- 已正确显示",
    "Current task result must render when WPS returns a fresh proxy for the same document"
  );
  assert.strictEqual(state.historyUnreadCount, 0, "Current task result must not be misclassified as background history");
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

// Test 6: Active Result State Machine Regression
function testActiveResultBehaviorWithExistingResult() {
  const { ctx, state, byId } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      writingJobId: "job_old",
      writingJobTaskType: "word.smart_write",
      writingJobMode: "smartWrite",
      documentSessionId: "doc_1",
      historyOpen: false,
      historyUnreadCount: 0
    }
  });

  ctx.setActiveResultRecord("word.smart_write", "doc_1", {
    result: { rewrittenText: "旧的成功改写文本。" },
    documentSessionId: "doc_1"
  });

  // Claim slot for job_1
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_1");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), true);

  // Case 1: When failure occurs, active result must be cleared, output shows error, slot released
  ctx.failWritingJob("job_1", "word.smart_write", "smartWrite", new Error("网络连接超时"), "doc_1");
  assert.strictEqual(ctx.getActiveResultRecord("word.smart_write", "doc_1"), null, "Active result must be set to null on failure");
  assert.ok(byId("result-output").textContent.includes("网络连接超时"), "Output must show failure error");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), false, "Slot must be released on failure");

  // Case 2: New valid submission and completion
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_2");
  ctx.completeWritingJob({ rewrittenText: "全新的智能编写结果。" }, "trace_2", "word.smart_write", false, "smartWrite", "job_2", "doc_1");
  assert.strictEqual(ctx.getActiveResultRecord("word.smart_write", "doc_1").result.rewrittenText, "全新的智能编写结果。");
  assert.strictEqual(byId("result-output").textContent, "全新的智能编写结果。");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), false, "Slot must be released on completion");

  // Case 3: Completion while viewing history updates badge and does not overwrite current history view
  state.historyOpen = true;
  state.historyUnreadCount = 0;
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_3");
  ctx.completeWritingJob({ rewrittenText: "后台完成的新编写结果。" }, "trace_3", "word.smart_write", false, "smartWrite", "job_3", "doc_1");
  assert.strictEqual(state.historyUnreadCount, 1, "Unread count must increment by 1");
  assert.strictEqual(byId("history-unread-badge").textContent, "1");
  assert.strictEqual(byId("history-unread-badge").hidden, false);
  assert.ok(byId("status-line").textContent.includes("后台"), "Status line must indicate background completion");
}

// Test 7: History List API Envelope Handling and Action Handlers
function testHistoryListEnvelopeParsingAndActions() {
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

  const { ctx, state, byId } = createBaseContext({
    state: {
      historyItems: [],
      currentMode: "smartWrite"
    },
    ctx: {
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
      copyText: (txt) => { copiedText = txt; }
    }
  });

  return ctx.loadAndRenderWritingHistory().then(() => {
    assert.strictEqual(state.historyItems.length, 1, "state.historyItems must contain 1 item");
    assert.ok(
      byId("word-history-content").innerHTML.includes("总结测试.docx"),
      "Rendered history must contain document display name"
    );

    // Test copy action
    ctx.handleWritingHistoryCopyItem("hist_word_99");
    assert.strictEqual(copiedText, "测试生成的改写文本。", "Copy action must copy rewrittenText");

    // Test delete single action
    return ctx.handleWritingHistoryDeleteItem("hist_word_99").then(() => {
      assert.strictEqual(deletedId, "hist_word_99", "Must call DELETE /history/{id}");
      assert.strictEqual(state.historyItems.length, 0, "History items must be removed from state");

      // Test clear history action
      return ctx.handleClearWritingHistory().then(() => {
        assert.strictEqual(clearedTaskType, "word.smart_write", "Must call DELETE /history?taskType=word.smart_write");
      });
    });
  });
}

// Test 8: Cross-Document Session Resume Isolation
function testCrossDocumentResumeIsolation() {
  let activeJobInStorage = {
    jobId: "job_docA",
    documentSessionId: "doc_session_A",
    taskType: "word.smart_write",
    mode: "smartWrite"
  };

  let polledJobId = null;
  let activeDoc = { Name: "DocB.docx" };

  const { ctx, state } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      writingJobId: "",
      documentSessionId: "doc_session_B"
    },
    ctx: {
      loadWritingActiveJob: () => activeJobInStorage,
      clearWritingActiveJob: () => { activeJobInStorage = null; },
      getActiveDocument: () => activeDoc,
      helpers: {
        ...helpers,
        getDocumentSessionId: (doc) => doc.Name === "DocB.docx" ? "doc_session_B" : "doc_session_A"
      },
      pollWritingJob: (id) => { polledJobId = id; }
    }
  });

  ctx.writingJobUsesEvents = vm.runInNewContext(
    `(${functionSource("writingJobUsesEvents")}\n)`,
    ctx
  );
  ctx.resumeWritingActiveJob = vm.runInNewContext(
    `(${functionSource("resumeWritingActiveJob")}\n)`,
    ctx
  );

  // Attempt 1: Current doc is DocB (session B), active job is from DocA (session A)
  ctx.resumeWritingActiveJob();
  assert.strictEqual(polledJobId, null, "Must NOT resume job belonging to different document session");
  assert.strictEqual(state.writingJobId, "", "state.writingJobId must remain empty");

  // Attempt 2: Switch current doc to DocA (session A)
  activeDoc = { Name: "DocA.docx" };
  ctx.resumeWritingActiveJob();
  assert.strictEqual(polledJobId, "job_docA", "Must resume job matching current document session");
  assert.strictEqual(state.writingJobId, "job_docA");
}

// Test 9: User notice on > 5 MiB archive skip
function testHistoryNoticeOnLargeResult() {
  const { ctx, byId } = createBaseContext();

  ctx.completeWritingJob({
    rewrittenText: "非常庞大的文档改写内容",
    historyNotice: "任务结果超过 5 MiB，未写入历史记录。"
  }, "trace_large", "word.smart_write", false, "smartWrite", "job_large", "doc_1");

  assert.ok(
    byId("status-line").textContent.includes("任务结果超过 5 MiB，未写入历史记录。"),
    "Status line must display historyNotice"
  );
}

// Test 10: Mode Switching Result Isolation
function testModeSwitchingResultIsolation() {
  const { ctx } = createBaseContext();
  ctx.setActiveResultRecord("word.smart_write", "doc_1", {
    result: { rewrittenText: "这是智能编写的结果。" },
    documentSessionId: "doc_1"
  });
  ctx.setActiveResultRecord("word.smart_imitation", "doc_1", {
    result: { rewrittenText: "这是智能仿写的结果。" },
    documentSessionId: "doc_1"
  });

  assert.strictEqual(
    ctx.getActiveResultRecord("word.smart_write", "doc_1").result.rewrittenText,
    "这是智能编写的结果。"
  );
  assert.strictEqual(
    ctx.getActiveResultRecord("word.smart_imitation", "doc_1").result.rewrittenText,
    "这是智能仿写的结果。"
  );
  assert.notStrictEqual(
    ctx.getActiveResultRecord("word.smart_write", "doc_1"),
    ctx.getActiveResultRecord("word.smart_imitation", "doc_1"),
    "Results of smart_write and smart_imitation must remain isolated"
  );
}

// Test 11: Review Item 2 - Precise Slot Release and Global Active Task Clearing
function testPreciseSlotReleaseAndIsolation() {
  const { ctx, state } = createBaseContext();
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_write", "doc_1", "job_1");
  helpers.claimTaskSlot(state.activeTaskSlots, "wps", "word.smart_imitation", "doc_2", "job_2");

  state.writingJobId = "job_2";
  state.writingJobTaskType = "word.smart_imitation";
  state.writingJobMode = "smartImitation";

  // Job 1 (Doc 1) finishes in background
  ctx.completeWritingJob({ rewrittenText: "Doc 1 结果" }, "tr_1", "word.smart_write", false, "smartWrite", "job_1", "doc_1");

  // Job 1 slot should be released, Job 2 slot must remain busy
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_write", "doc_1"), false, "Job 1 slot should be released");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_imitation", "doc_2"), true, "Job 2 slot should remain busy");
  // Global active job must NOT be cleared because job_1 is not current global job
  assert.strictEqual(state.writingJobId, "job_2", "Global active job must remain job_2");

  // Now job_2 completes
  ctx.completeWritingJob({ rewrittenText: "Doc 2 结果" }, "tr_2", "word.smart_imitation", false, "smartImitation", "job_2", "doc_2");
  assert.strictEqual(helpers.isTaskSlotBusy(state.activeTaskSlots, "wps", "word.smart_imitation", "doc_2"), false, "Job 2 slot should be released");
  assert.strictEqual(state.writingJobId, "", "Global active job should now be cleared");
}

function testBackgroundSmartWriteCompletionUsesSubmissionSnapshot() {
  const smartWritePayload = {
    selectionMode: "selection",
    content: { plainText: "智能编写提交时的原选区" },
    options: {}
  };
  const imitationPayload = {
    selectionMode: "selection",
    content: { plainText: "随后启动的智能仿写模板" },
    options: { imitationRequirement: "保持风格" }
  };
  const { ctx, state } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: "doc_shared",
      latestDocumentPayload: smartWritePayload
    },
    ctx: {
      WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
      buildWritingClientJobId: () => "job-write-snapshot",
      beginTaskPerformance: () => ({ clickTimestamp: Date.now() }),
      writingJobPath: () => "/word/smart-write/jobs",
      request: () => new Promise(() => {})
    }
  });

  ctx.startWritingJob(
    smartWritePayload,
    "word.smart_write",
    "smartWrite",
    "doc_shared",
    "测试文档.docx"
  );

  state.currentMode = "smartImitation";
  state.writingJobId = "job-imitation-current";
  state.latestDocumentPayload = imitationPayload;

  ctx.completeWritingJob(
    { rewrittenText: "智能编写完成结果" },
    "trace-write-snapshot",
    "word.smart_write",
    false,
    "smartWrite",
    "job-write-snapshot",
    "doc_shared"
  );

  const resultRecord = ctx.getActiveResultRecord("word.smart_write", "doc_shared");
  assert.strictEqual(
    resultRecord.documentPayload.content.plainText,
    "智能编写提交时的原选区",
    "Background completion must bind the document snapshot captured by its own submission"
  );
  assert.strictEqual(
    state.pendingApplyAction,
    "",
    "Background smart-write completion must not grant apply permission to the imitation view"
  );

  ctx.switchMode("smartWrite");
  assert.strictEqual(
    state.latestDocumentPayload.content.plainText,
    "智能编写提交时的原选区",
    "Returning to smart write must restore its own submission snapshot"
  );
  assert.strictEqual(state.pendingApplyAction, "rewrite");
}

function testApplyRewriteUsesActiveResultSnapshot() {
  const writeTarget = { Text: "" };
  const { ctx, state } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: "doc_shared",
      latestSelectionMode: "selection",
      latestDocumentPayload: {
        selectionMode: "selection",
        content: { plainText: "智能仿写模板" }
      },
      rewriteResult: { rewrittenText: "智能编写完成结果" },
      pendingApplyAction: "rewrite"
    },
    ctx: {
      getActiveDocument: () => ({ Name: "doc_shared", FullName: "doc_shared" }),
      getWritableSelection: () => writeTarget,
      getSelectionText: () => "智能编写提交时的原选区",
      shouldUseStructuredSmartWriteResult: () => false,
      applyRewriteText: (target, text) => {
        target.Text = text;
        return { ok: true, formatted: false, reason: "test" };
      }
    }
  });

  ctx.setActiveResultRecord("word.smart_write", "doc_shared", {
    result: state.rewriteResult,
    taskType: "word.smart_write",
    documentSessionId: "doc_shared",
    pendingApplyAction: "rewrite",
    documentPayload: {
      selectionMode: "selection",
      content: { plainText: "智能编写提交时的原选区" }
    }
  });

  ctx.applyRewrite();

  assert.strictEqual(
    writeTarget.Text,
    "智能编写完成结果",
    "Writeback must validate and write against the active result's submission snapshot"
  );
}

// Test 12: Review Item 3 - Document Session Dimension Isolation
function testDocumentSessionDimensionIsolation() {
  const { ctx } = createBaseContext();
  const res1 = { result: { rewrittenText: "文档1的改写结果" }, documentSessionId: "doc_session_1" };
  const res2 = { result: { rewrittenText: "文档2的改写结果" }, documentSessionId: "doc_session_2" };

  ctx.setActiveResultRecord("word.smart_write", "doc_session_1", res1);
  ctx.setActiveResultRecord("word.smart_write", "doc_session_2", res2);

  assert.strictEqual(ctx.getActiveResultRecord("word.smart_write", "doc_session_1").result.rewrittenText, "文档1的改写结果");
  assert.strictEqual(ctx.getActiveResultRecord("word.smart_write", "doc_session_2").result.rewrittenText, "文档2的改写结果");

  // Test active writing job isolation
  const job1 = { jobId: "job_1", documentSessionId: "doc_session_1" };
  const job2 = { jobId: "job_2", documentSessionId: "doc_session_2" };

  ctx.setActiveWritingJobRecord("word.smart_write", "doc_session_1", job1);
  ctx.setActiveWritingJobRecord("word.smart_write", "doc_session_2", job2);

  assert.strictEqual(ctx.getActiveWritingJobRecord("word.smart_write", "doc_session_1").jobId, "job_1");
  assert.strictEqual(ctx.getActiveWritingJobRecord("word.smart_write", "doc_session_2").jobId, "job_2");

  // Deleting job 1 does not delete job 2
  ctx.setActiveWritingJobRecord("word.smart_write", "doc_session_1", null);
  assert.strictEqual(ctx.getActiveWritingJobRecord("word.smart_write", "doc_session_1"), null);
  assert.strictEqual(ctx.getActiveWritingJobRecord("word.smart_write", "doc_session_2").jobId, "job_2");
}

// Test 13: Review Item 4 - Resumed Running Task Polls With resumed=false and Renders Completed Result
function testResumeTaskRunningToCompletedRendersResult() {
  let scheduledPollArgs = null;
  let pollCount = 0;
  let lastRequestPromise = null;

  const { ctx, byId } = createBaseContext({
    ctx: {
      request: () => {
        pollCount += 1;
        if (pollCount === 1) {
          lastRequestPromise = Promise.resolve({ data: { status: "running" }, traceId: "tr_run" });
        } else {
          lastRequestPromise = Promise.resolve({
            data: { status: "completed", result: { rewrittenText: "已完成的恢复改写文本" } },
            traceId: "tr_done"
          });
        }
        return lastRequestPromise;
      },
      scheduleWritingPoll: (jobId, taskType, mode, resumed, delayMs, docSessionId) => {
        scheduledPollArgs = { jobId, taskType, mode, resumed, delayMs, docSessionId };
      },
      renderWritingJobProgress: () => {},
      isFatalWritingPollError: () => false,
      writingJobPath: () => "/word/smart-write/jobs",
      WRITING_POLL_REQUEST_TIMEOUT_MS: 5000,
      WRITING_POLL_INTERVAL_MS: 1000
    }
  });

  ctx.pollWritingJob = vm.runInNewContext(`(${functionSource("pollWritingJob")}\n)`, ctx);

  // Poll 1 with resumed = true
  ctx.pollWritingJob("job_resume_1", "word.smart_write", "smartWrite", true, "doc_1");

  return lastRequestPromise.then(() => {
    assert.ok(scheduledPollArgs, "Must have scheduled next poll");
    assert.strictEqual(scheduledPollArgs.resumed, true, "A recovered job must remain read-only across subsequent polls");

    // Poll 2 with scheduled args (resumed = false)
    ctx.pollWritingJob(
      scheduledPollArgs.jobId,
      scheduledPollArgs.taskType,
      scheduledPollArgs.mode,
      scheduledPollArgs.resumed,
      scheduledPollArgs.docSessionId
    );
    return lastRequestPromise;
  }).then(() => {
    return new Promise((resolve) => setImmediate(resolve));
  }).then(() => {
    assert.strictEqual(
      byId("result-output").textContent,
      "已完成的恢复改写文本",
      "Result must be rendered upon terminal completion of resumed job"
    );
  });
}

// Regression: a recovered job may already be completed on the first status read.
function testResumeTaskAlreadyCompletedRendersResult() {
  let lastRequestPromise;
  const { ctx, byId } = createBaseContext({
    ctx: {
      request: () => {
        lastRequestPromise = Promise.resolve({
          data: { status: "completed", result: { rewrittenText: "恢复时已经完成的改写文本" } },
          traceId: "tr_already_done"
        });
        return lastRequestPromise;
      },
      renderWritingJobProgress: () => {},
      isFatalWritingPollError: () => false,
      writingJobPath: () => "/word/smart-write/jobs",
      WRITING_POLL_REQUEST_TIMEOUT_MS: 5000,
      WRITING_POLL_INTERVAL_MS: 1000
    }
  });

  ctx.pollWritingJob = vm.runInNewContext(`(${functionSource("pollWritingJob")}\n)`, ctx);
  ctx.pollWritingJob("job_resume_done", "word.smart_write", "smartWrite", true, "doc_1");

  return lastRequestPromise.then(() => new Promise((resolve) => setImmediate(resolve))).then(() => {
    assert.strictEqual(
      byId("result-output").textContent,
      "恢复时已经完成的改写文本",
      "A recovered completed result must be restored to the current preview"
    );
  });
}

// Test 14: Review Item 5 - Background Failure Does Not Overwrite Foreground View
function testBackgroundFailureDoesNotOverwriteForeground() {
  const { ctx, state, byId } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: "doc_foreground",
      writingJobId: "job_fg"
    }
  });

  ctx.setActiveResultRecord("word.smart_write", "doc_foreground", {
    result: { rewrittenText: "前台文档的有效改写内容" },
    documentSessionId: "doc_foreground"
  });
  byId("result-output").textContent = "前台文档的有效改写内容";

  // Background failure on doc_background
  ctx.failWritingJob("job_bg", "word.smart_write", "smartWrite", new Error("后台网络超时"), "doc_background");

  assert.strictEqual(
    byId("result-output").textContent,
    "前台文档的有效改写内容",
    "Foreground result-output must not be overwritten by background failure"
  );
  assert.strictEqual(state.writingJobId, "job_fg", "Foreground writingJobId must not be cleared");
  const fgRecord = ctx.getActiveResultRecord("word.smart_write", "doc_foreground");
  assert.ok(fgRecord, "Foreground active result record must remain intact");
}

// Test 15: Review Item 6 - Exiting History View Restores rewriteResult and Writeback
function testHistoryReturnRestoresResultAndWriteback() {
  const { ctx, state, byId } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: "doc_1",
      latestDocumentPayload: { text: "选中的原文" }
    }
  });

  ctx.setActiveResultRecord("word.smart_write", "doc_1", {
    result: { rewrittenText: "改写后的专业文本", rewriteMode: "rewrite" },
    traceId: "tr_ret",
    pendingApplyAction: "rewrite",
    documentPayload: {
      selectionMode: "selection",
      content: { plainText: "选中的原文" }
    },
    documentSessionId: "doc_1",
    resumed: false
  });

  // Enter history
  ctx.switchWordHistoryView(true);
  assert.strictEqual(state.historyOpen, true);

  // Exit history
  ctx.switchWordHistoryView(false);
  assert.strictEqual(state.historyOpen, false);
  assert.ok(state.rewriteResult, "state.rewriteResult must not be undefined or null");
  assert.strictEqual(state.rewriteResult.rewrittenText, "改写后的专业文本");
  assert.strictEqual(state.pendingApplyAction, "rewrite", "state.pendingApplyAction must be restored to rewrite");
  assert.strictEqual(byId("btn-apply").disabled, false, "btn-apply must be enabled");
}

// Test 16: Review Item 7 - Switching Mode While History Open Syncs History Context
function testModeSwitchHistoryContextSync() {
  let loadedTaskType = "";
  const { ctx, state } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      historyOpen: true,
      historyTaskType: "word.smart_write"
    },
    ctx: {
      loadAndRenderWritingHistory: (tt) => {
        loadedTaskType = tt;
      }
    }
  });

  ctx.switchMode("smartImitation");
  assert.strictEqual(state.currentMode, "smartImitation");
  assert.strictEqual(state.historyTaskType, "word.smart_imitation");
  assert.strictEqual(loadedTaskType, "word.smart_imitation");
}

// Test 17: Review Item 8 - Real switchMode Path Restores pendingApplyAction and applyPreview Works
function testRealSwitchModePathAndWritebackEligibility() {
  let applyRewriteCalled = false;
  const { ctx, state, byId } = createBaseContext({
    state: {
      currentMode: "smartWrite",
      documentSessionId: "doc_1",
      latestDocumentPayload: { text: "选中的原文" }
    },
    ctx: {
      applyRewrite: () => {
        applyRewriteCalled = true;
      }
    }
  });

  ctx.setActiveResultRecord("word.smart_write", "doc_1", {
    result: { rewrittenText: "准备写回的内容" },
    traceId: "tr_sw",
    pendingApplyAction: "rewrite",
    documentPayload: {
      selectionMode: "selection",
      content: { plainText: "选中的原文" }
    },
    documentSessionId: "doc_1",
    resumed: false
  });

  // Switch to smartImitation
  ctx.switchMode("smartImitation");
  assert.strictEqual(state.currentMode, "smartImitation");
  assert.strictEqual(byId("btn-apply").hidden, true);

  // Switch back to smartWrite
  ctx.switchMode("smartWrite");
  assert.strictEqual(state.currentMode, "smartWrite");
  assert.strictEqual(byId("btn-apply").hidden, false);
  assert.strictEqual(byId("btn-apply").disabled, false);
  assert.strictEqual(state.pendingApplyAction, "rewrite");

  // Click "写回" button
  ctx.applyPreview();
  assert.strictEqual(applyRewriteCalled, true, "applyPreview must invoke applyRewrite");
}

async function runAll() {
  testDocumentSessionIdentification();
  testFreshProxyCompletionRendersCurrentWritingResult();
  testDocumentDisplayName();
  testActiveTaskSlotGuard();
  testWritingHistoryRenderingHelper();
  testWordActiveResultMarkupContract();
  testActiveResultBehaviorWithExistingResult();
  testCrossDocumentResumeIsolation();
  testHistoryNoticeOnLargeResult();
  testModeSwitchingResultIsolation();
  testPreciseSlotReleaseAndIsolation();
  testBackgroundSmartWriteCompletionUsesSubmissionSnapshot();
  testApplyRewriteUsesActiveResultSnapshot();
  testDocumentSessionDimensionIsolation();
  testBackgroundFailureDoesNotOverwriteForeground();
  testHistoryReturnRestoresResultAndWriteback();
  testModeSwitchHistoryContextSync();
  testRealSwitchModePathAndWritebackEligibility();
  await testHistoryListEnvelopeParsingAndActions();
  await testResumeTaskRunningToCompletedRendersResult();
  await testResumeTaskAlreadyCompletedRendersResult();
  console.log("All Word active result and history tests passed!");
}

runAll().catch((err) => {
  console.error(err);
  process.exit(1);
});

const test = require('node:test');
function writingSubmissionHarness(taskType = 'word.smart_write') {
  const pending = [];
  const timers = [];
  const mode = taskType === 'word.smart_imitation' ? 'smartImitation' : 'smartWrite';
  const h = createBaseContext({ state: { currentMode: mode }, ctx: {
    Date, Math, setTimeout: fn => timers.push(fn), clearTimeout() {},
    WRITING_POLL_REQUEST_TIMEOUT_MS: 1000,
    WRITING_POLL_INTERVAL_MS: 1000, WRITING_POLL_RETRY_DELAY_MS: 1000,
    DOCUMENT_REVIEW_PHASE_TEXT: {}, SMART_WRITE_EXTRACTION_OPTIONS: {},
    request: (url, payload) => new Promise((resolve, reject) => pending.push({url, payload: payload && JSON.parse(JSON.stringify(payload)), resolve, reject})),
    beginTaskPerformance: () => ({}), bindTaskPerformanceTrace() {},
    setDocumentReviewCancelVisible() {}, scheduleWritingPoll() {},
    isFatalWritingPollError: error => error.status === 400,
    resolveSelectionScope: () => ({ok: true}), getWritingPolicyScene: () => 'auto',
    extractDocument: () => ({content: {plainText: '同一段原文'}, selectionMode: 'selection'}),
  }});
  h.ctx.setModelTaskBusy = busy => { h.state.modelTaskBusy = busy; };
  for (const name of ['buildWritingClientJobId', 'writingJobPath', 'writingJobUsesEvents', 'renderWritingJobProgress', 'pollWritingJob', 'pollWritingJobEvents', 'runSmartWriteAction', 'runSmartImitationAction']) {
    h.ctx[name] = vm.runInNewContext(`(${functionSource(name)}\n)`, h.ctx);
  }
  h.byId('imitation-template-text').value = '仿写模板';
  h.byId('imitation-requirement').value = '同一要求';
  h.pending = pending; h.timers = timers; h.taskType = taskType; h.mode = mode;
  h.start = () => h.ctx[mode === 'smartWrite' ? 'runSmartWriteAction' : 'runSmartImitationAction']();
  return h;
}
const flushWritingPromises = () => new Promise(resolve => setImmediate(resolve));

for (const taskType of ['word.smart_write', 'word.smart_imitation']) {
  test(taskType + ' identical inputs execute new submissions, hide old results, and reject rapid clicks', async () => {
    const h = writingSubmissionHarness(taskType);
    h.start();
    h.start();
    assert.ok(h.timers.length <= 1, 'preparation must not be queued twice');
    if (h.timers.length) h.timers.shift()();
    assert.equal(h.pending.length, 1);
    const first = h.pending[0];
    first.resolve({data: {jobId: first.payload.clientJobId, status: 'completed', result: {rewrittenText: '上一轮成功'}}});
    await flushWritingPromises();
    assert.equal(h.byId('result-output').textContent, '上一轮成功');
    h.start();
    if (h.timers.length) h.timers.shift()();
    assert.equal(h.pending.length, 2);
    const second = h.pending[1];
    assert.notEqual(second.payload.clientJobId, first.payload.clientJobId);
    assert.equal(second.payload.content.plainText, first.payload.content.plainText);
    assert.equal(h.ctx.getActiveResultRecord(taskType, 'doc_1'), null);
    assert.notEqual(h.byId('result-output').textContent, '上一轮成功');
    second.resolve({data: {jobId: second.payload.clientJobId, status: 'failed', error: {message: '本轮失败'}}});
    await flushWritingPromises();
    assert.equal(h.byId('result-output').textContent, '本轮失败');
    assert.equal(h.ctx.getActiveResultRecord(taskType, 'doc_1'), null);
  });

  for (const outcome of ['completed', 'failed', 'cancelled', 'running', 'network-error']) {
    test(taskType + ' late ' + outcome + ' poll cannot overwrite a newer task', async () => {
      const h = writingSubmissionHarness(taskType);
      h.ctx.setActiveWritingJobRecord(taskType, 'doc_1', {jobId: 'old-job'});
      h.ctx.pollWritingJob('old-job', taskType, h.mode, false, 'doc_1');
      h.ctx.setActiveWritingJobRecord(taskType, 'doc_1', {jobId: 'new-job'});
      h.ctx.setWritingJob('new-job', taskType, h.mode);
      h.byId('result-output').textContent = '本轮进度';
      h.byId('status-line').textContent = '本轮状态';
      if (outcome === 'network-error') h.pending[0].reject(Error('旧网络错误'));
      else h.pending[0].resolve({data: {status: outcome, result: {rewrittenText: '旧结果'}, error: {message: '旧错误'}}});
      await flushWritingPromises();
      assert.equal(h.byId('result-output').textContent, '本轮进度');
      assert.equal(h.byId('status-line').textContent, '本轮状态');
      assert.equal(h.state.writingJobId, 'new-job');
      assert.equal(h.ctx.getActiveWritingJobRecord(taskType, 'doc_1').jobId, 'new-job');
    });
  }

  test(taskType + ' uncertain submit resumes the same ID without another POST', async () => {
    const h = writingSubmissionHarness(taskType);
    h.start(); if (h.timers.length) h.timers.shift()();
    const first = h.pending[0];
    first.reject(Error('response lost'));
    await flushWritingPromises();
    assert.equal(h.pending.length, 2);
    assert.equal(h.pending[1].payload, null);
    assert.ok(h.pending[1].url.includes(first.payload.clientJobId));
    h.start();
    assert.equal(h.pending.filter(call => call.payload).length, 1);
    h.pending[1].resolve({data: {status: 'completed', result: {rewrittenText: '恢复的本轮结果'}}});
    await flushWritingPromises();
    assert.equal(h.byId('result-output').textContent, '恢复的本轮结果');
  });
}

for (const taskType of ['word.smart_write', 'word.smart_imitation']) {
  test(taskType + ' late event failure cannot clear a newer task', async () => {
    const h = writingSubmissionHarness(taskType);
    h.ctx.setActiveWritingJobRecord(taskType, 'doc_1', {jobId:'old-job'});
    h.ctx.pollWritingJobEvents('old-job', taskType, h.mode, false, 'doc_1', 0, 0);
    h.ctx.setActiveWritingJobRecord(taskType, 'doc_1', {jobId:'new-job'});
    h.ctx.setWritingJob('new-job', taskType, h.mode);
    h.byId('result-output').textContent = '本轮正文';
    h.pending[0].resolve({data:{terminal:true,status:'failed',error:{message:'旧错误'},events:[]}});
    await flushWritingPromises();
    assert.equal(h.byId('result-output').textContent, '本轮正文');
    assert.equal(h.state.writingJobId, 'new-job');
    assert.equal(h.ctx.getActiveWritingJobRecord(taskType, 'doc_1').jobId, 'new-job');
  });
}

test('an old submit response cannot replace a newer writing task', async () => {
  const h = writingSubmissionHarness();
  h.start(); h.timers.shift()();
  h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_1', {jobId:'new-job'});
  h.ctx.setWritingJob('new-job', h.taskType, h.mode);
  h.byId('result-output').textContent = '本轮进度';
  h.pending[0].resolve({data:{jobId:h.pending[0].payload.clientJobId,status:'completed',result:{rewrittenText:'旧结果'}}});
  await flushWritingPromises();
  assert.equal(h.byId('result-output').textContent, '本轮进度');
  assert.equal(h.state.writingJobId, 'new-job');
});

for (const taskType of ['word.smart_write', 'word.smart_imitation']) {
  test(taskType + ' obsolete completion and failure cannot replace a finished newer result', () => {
    const h = writingSubmissionHarness(taskType);
    h.ctx.setActiveWritingJobRecord(taskType, 'doc_1', {jobId:'new-job'});
    h.ctx.setWritingJob('new-job', taskType, h.mode);
    h.ctx.completeWritingJob({rewrittenText:'新结果'}, 'new-trace', taskType, false, h.mode, 'new-job', 'doc_1');
    h.ctx.completeWritingJob({rewrittenText:'旧结果'}, 'old-trace', taskType, false, h.mode, 'old-job', 'doc_1');
    h.ctx.failWritingJob('old-job', taskType, h.mode, Error('旧错误'), 'doc_1');
    assert.equal(h.byId('result-output').textContent, '新结果');
    assert.equal(h.ctx.getActiveResultRecord(taskType, 'doc_1').result.rewrittenText, '新结果');
  });
}

test('background submit acceptance does not replace another document foreground job or status', async () => {
  const h = writingSubmissionHarness();
  h.start(); h.timers.shift()();
  const oldId = h.pending[0].payload.clientJobId;
  h.state.documentSessionId = 'doc_2';
  h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_2', {jobId:'foreground-job'});
  h.ctx.setWritingJob('foreground-job', h.taskType, h.mode);
  h.byId('status-line').textContent = '前台进度';
  h.pending[0].resolve({data:{jobId:oldId,status:'completed',result:{rewrittenText:'后台结果'}}});
  await flushWritingPromises();
  assert.equal(h.state.writingJobId, 'foreground-job');
  assert.equal(h.byId('status-line').textContent, '前台进度');
  assert.equal(h.ctx.getActiveResultRecord(h.taskType, 'doc_1').result.rewrittenText, '后台结果');
});

test('streaming preview does not replace the history view', () => {
  const h = writingSubmissionHarness();
  h.state.historyOpen = true;
  h.state.writingJobId = 'active-job';
  h.state.writingJobPreviews = {preview:{jobId:'active-job',taskType:h.taskType,documentSessionId:'doc_1',mode:h.mode,text:'本轮增量正文'}};
  h.byId('result-output').textContent = '正在查看的历史';
  const render = vm.runInNewContext(`(${functionSource('renderWritingJobPreview')}\n)`, h.ctx);
  render('preview');
  assert.equal(h.byId('result-output').textContent, '正在查看的历史');
  assert.equal(h.pending.length, 0);
});

test('a background event completion cannot stop the foreground waiting feedback', async () => {
  const h = writingSubmissionHarness();
  let stopped = 0;
  h.ctx.stopWritingWaitFeedback = () => {stopped += 1;};
  h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_1', {jobId:'background-job'});
  h.ctx.pollWritingJobEvents('background-job', h.taskType, h.mode, false, 'doc_1', 0, 0);
  h.state.documentSessionId = 'doc_2';
  h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_2', {jobId:'foreground-job'});
  h.ctx.setWritingJob('foreground-job', h.taskType, h.mode);
  h.pending[0].resolve({data:{terminal:true,status:'completed',events:[]}});
  await flushWritingPromises();
  assert.equal(stopped, 0);
  assert.equal(h.state.writingJobId, 'foreground-job');
});

for (const action of ['rewrite', 'continue', 'summarize', 'custom']) {
  test('smart write ' + action + ' submits identical input again with a fresh task ID', async () => {
    const h = writingSubmissionHarness();
    h.state.writeAction = action;
    h.ctx.extractDocument = (selection, requestedAction) => ({selectionMode:selection,content:{plainText:'同一段原文'},options:{rewriteAction:requestedAction}});
    for (let round = 0; round < 2; round += 1) {
      h.start(); h.timers.shift()();
      const call = h.pending[round];
      assert.equal(call.payload.options.rewriteAction, action);
      call.resolve({data:{jobId:call.payload.clientJobId,status:'completed',result:{rewrittenText:'正文'}}});
      await flushWritingPromises();
    }
    assert.equal(h.pending.length, 2);
    assert.notEqual(h.pending[0].payload.clientJobId, h.pending[1].payload.clientJobId);
    assert.deepEqual(h.pending[0].payload.content, h.pending[1].payload.content);
  });
}

for (const outcome of ['cancelled', 'completed', 'network-error']) {
  test('late writing cancellation ' + outcome + ' cannot overwrite a newer task', async () => {
    const h = writingSubmissionHarness();
    h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_1', {jobId:'old-job'});
    h.ctx.setWritingJob('old-job', h.taskType, h.mode);
    const cancel = vm.runInNewContext(`(${functionSource('cancelQueuedWritingJob')}\n)`, h.ctx);
    cancel();
    h.ctx.setActiveWritingJobRecord(h.taskType, 'doc_1', {jobId:'new-job'});
    h.ctx.setWritingJob('new-job', h.taskType, h.mode);
    h.state.modelTaskBusy = true;
    h.byId('result-output').textContent = '本轮进度';
    h.byId('status-line').textContent = '本轮状态';
    if (outcome === 'network-error') h.pending[0].reject(Error('旧取消错误'));
    else h.pending[0].resolve({data:{status:outcome,result:{rewrittenText:'旧结果'}}});
    await flushWritingPromises();
    assert.equal(h.byId('result-output').textContent, '本轮进度');
    assert.equal(h.byId('status-line').textContent, '本轮状态');
    assert.equal(h.state.writingJobId, 'new-job');
    assert.equal(h.state.modelTaskBusy, true);
  });
}
