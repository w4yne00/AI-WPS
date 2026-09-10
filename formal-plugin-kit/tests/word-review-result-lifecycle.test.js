const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");

const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

function functionSource(name) {
  let start = taskpaneSource.indexOf(`  function ${name}(`);
  if (start < 0) {
    start = taskpaneSource.indexOf(`function ${name}(`);
  }
  assert.ok(start >= 0, `missing function ${name}`);
  const next = taskpaneSource.indexOf("\n  function ", start + 3);
  return taskpaneSource.slice(start, next === -1 ? taskpaneSource.length : next);
}

function createBaseTestContext(initialOverrides = {}) {
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
        addEventListener: function() {},
        querySelectorAll: function() { return []; }
      };
    }
    return elements[id];
  };

  const storage = {};
  const state = {
    currentMode: "documentReview",
    lastTaskMode: "documentReview",
    documentReviewJobId: "",
    fullDocumentReviewJobId: "",
    documentReviewPollStartedAt: 0,
    documentReviewPollErrorCount: 0,
    fullDocumentReviewPollErrorCount: 0,
    fullDocumentReviewEnabled: true,
    fullDocumentReviewPreparing: false,
    fullDocumentReviewCancelRequested: false,
    fullDocumentReviewReportMetadata: null,
    fullDocumentReviewIssueFilters: null,
    fullDocumentReviewIssueCursorHistory: [""],
    activeTaskSlots: {},
    activeReviewJobs: {},
    activeResults: {},
    activeResultsByTask: {},
    viewingHistoryReport: null,
    documentSessionId: "doc-session-1",
    documentDisplayName: "测试文档.docx",
    historyItems: [],
    historyOpen: false,
    ...(initialOverrides.state || {})
  };

  const ctx = {
    state,
    byId,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    Promise: Promise,
    console: console,
    request: (url) => Promise.resolve({ data: {} }),
    document: {
      body: {
        attributes: {},
        setAttribute: function(attr, val) { this.attributes[attr] = val; },
        getAttribute: function(attr) { return this.attributes[attr]; }
      },
      createElement: (tag) => {
        const el = {
          tagName: tag.toUpperCase(),
          className: "",
          innerHTML: "",
          style: {},
          setAttribute: () => {},
          listeners: {},
          addEventListener: function(evt, handler) {
            (this.listeners[evt] = this.listeners[evt] || []).push(handler);
          },
          querySelector: function(sel) {
            if (sel === ".btn-open-full-report") {
              return this.openBtn;
            }
            return null;
          },
          querySelectorAll: () => []
        };
        el.openBtn = {
          listeners: {},
          addEventListener: function(evt, handler) {
            (this.listeners[evt] = this.listeners[evt] || []).push(handler);
          },
          click: function() {
            (this.listeners["click"] || []).forEach(function(h) { h(); });
          }
        };
        return el;
      }
    },
    window: {
      localStorage: {
        getItem: (k) => storage[k] || null,
        setItem: (k, v) => { storage[k] = String(v); },
        removeItem: (k) => { delete storage[k]; },
        get length() { return Object.keys(storage).length; },
        key: (i) => Object.keys(storage)[i] || null
      }
    },
    storage,
    helpers: {
      ...helpers,
      getDocumentSessionId: () => state.documentSessionId,
      getDocumentDisplayName: () => state.documentDisplayName
    },
    getActiveDocument: () => ({ Name: state.documentDisplayName, __sessionId: state.documentSessionId }),
    FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY: "ai-wps-full-document-review-active-job-v1",
    DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY: "ai-wps-document-review-active-job-v1",
    FRONTEND_BUILD_VERSION: "1.0.0",
    DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS: 5000,
    DOCUMENT_REVIEW_POLL_INTERVAL_MS: 1000,
    DOCUMENT_REVIEW_EXTRACTION_OPTIONS: {},
    DOCUMENT_REVIEW_PHASE_TEXT: {},
    setModelTaskBusy: (b) => { state.modelTaskBusy = b; },
    setStatus: (msg) => {
      state.status = msg;
      byId("status-line").textContent = msg;
    },
    setResult: (msg) => {
      state.result = msg;
      byId("result-output").textContent = msg;
    },
    setPlainResult: (msg) => {
      state.result = msg;
      byId("result-output").textContent = msg;
    },
    setTrace: (tr) => { state.traceId = tr; },
    setApplyEnabled: () => {},
    setDocumentReviewCancelVisible: () => {},
    setReviewRecordActionsVisible: () => {},
    setInterruptedRetryVisible: () => {},
    closeTaskModelConfigMenu: () => {},
    switchView: () => {},
    renderWorkflowProfileStrip: () => {},
    loadWorkflowProfiles: () => {},
    renderFullDocumentReviewEntry: () => {},
    renderFullDocumentReviewReport: () => Promise.resolve(),
    renderDocumentReviewResult: (res) => {
      state.renderedReviewResult = res;
      return true;
    },
    renderDocumentReviewJobProgress: () => {},
    resetSmartWritePreviewState: () => {},
    resetDocumentReviewState: () => {},
    restoreWritingPolicyScene: () => {},
    hideCompareForSmartImitation: () => {},
    updateRewritePromptPreview: () => {},
    loadAndRenderWritingHistory: () => {},
    describeFetchError: (err) => (err && err.message) || String(err || ""),
    describeDocumentReviewError: (err) => (err && err.message) || String(err || ""),
    describeDocumentReviewPollError: (err) => (err && err.message) || String(err || ""),
    isFatalDocumentReviewPollError: () => true,
    isFullDocumentReviewPermanentPollError: () => true,
    buildDocumentReviewClientJobId: () => "client-job-" + Date.now(),
    getWritingPolicyScene: () => "auto",
    getCurrentWorkflowTaskType: () => "word.document_review",
    getFullDocumentReviewReadiness: () => ({ fullDocumentReviewReady: true }),
    setDocumentReviewJobId: (id) => { state.documentReviewJobId = id; },
    startDocumentReviewWaitFeedback: () => () => {},
    stopDocumentReviewWaitFeedback: () => {},
    modeConfig: {
      smartWrite: { title: "智能编写", showRewriteOptions: true },
      smartImitation: { title: "智能仿写" },
      documentReview: { title: "文档审查", showDocumentReviewOptions: true, primaryText: "开始审查" },
      settings: { title: "设置" }
    },
    ...(initialOverrides.ctx || {})
  };

  const fns = [
    "getWritingDocTaskKey",
    "getReviewActiveJobStorageKey",
    "getActiveReviewJobRecord",
    "setActiveReviewJobRecord",
    "getActiveResultRecord",
    "setActiveResultRecord",
    "releaseTaskSlotsForJob",
    "cleanupDocumentReviewTerminal",
    "cleanupFullDocumentReviewTerminal",
    "restoreActiveReviewResult",
    "loadDocumentReviewActiveJob",
    "saveDocumentReviewActiveJob",
    "clearDocumentReviewActiveJob",
    "loadFullDocumentReviewActiveJob",
    "saveFullDocumentReviewActiveJob",
    "clearFullDocumentReviewActiveJob",
    "resumeDocumentReviewActiveJob",
    "resumeFullDocumentReviewActiveJob",
    "pollDocumentReviewJob",
    "pollFullDocumentReviewJob",
    "switchMode",
    "switchWordHistoryView",
    "handleWritingHistoryViewItem",
    "handleWritingHistoryDeleteItem"
  ];

  const bundle = fns.map((fn) => functionSource(fn)).join("\n");
  vm.runInNewContext(bundle, ctx);
  return ctx;
}

test("renderWritingHistoryList renders document review and full document review cards", () => {
  const items = [
    {
      id: "hist_rev_1",
      taskType: "word.document_review",
      jobId: "job-review-001",
      completedAt: "2026-09-10T08:00:00Z",
      documentDisplayName: "合同初稿.docx",
      serviceName: "Word 文档审查",
      modelName: "review-v1",
      result: {
        reportType: "document_review",
        jobId: "job-review-001",
        summary: "审查发现 2 项问题，主要涉及术语和表达。",
        issueCount: 2,
        categoryCounts: { professional: 1, expression: 1 },
        severityCounts: { high: 1, low: 1 }
      }
    },
    {
      id: "hist_full_1",
      taskType: "word.document_review",
      jobId: "job-full-002",
      completedAt: "2026-09-10T09:00:00Z",
      documentDisplayName: "技术白皮书.docx",
      serviceName: "Word 全篇文档审查",
      modelName: "review-direct-v1",
      result: {
        reportType: "full_document_review",
        reportId: "job-full-002",
        jobId: "job-full-002",
        summary: "全篇审查完成，共发现 5 项问题。",
        issueCount: 5,
        categoryCounts: { professional: 3, logic: 2 },
        severityCounts: { high: 2, medium: 3 },
        statusCounts: { open: 5 },
        enumerationStatus: "complete",
        reportExpiresAt: Date.now() / 1000 + 86400
      }
    }
  ];

  const html = helpers.renderWritingHistoryList(items);

  assert.ok(html.includes("合同初稿.docx"), "Must include regular review document name");
  assert.ok(html.includes("文档审查成果"), "Must include regular review card title");
  assert.ok(html.includes("审查发现 2 项问题"), "Must include regular review summary snippet");
  assert.ok(html.includes('data-history-id="hist_rev_1"'), "Must include card history id");

  assert.ok(html.includes("技术白皮书.docx"), "Must include full review document name");
  assert.ok(html.includes("全篇审查成果"), "Must include full review card title");
  assert.ok(html.includes("全篇审查完成，共发现 5 项问题"), "Must include full review summary snippet");
  assert.ok(html.includes('data-history-id="hist_full_1"'), "Must include full review history id");
});

test("Behavioral: switchMode for documentReview displays history button and restores active result per document session", () => {
  const ctx = createBaseTestContext();

  ctx.setActiveResultRecord("word.document_review", "doc-session-1", {
    result: { issues: [{ id: 1, title: "问题1" }] },
    taskType: "word.document_review",
    documentSessionId: "doc-session-1"
  });

  ctx.switchMode("documentReview");

  const btnHistory = ctx.byId("btn-view-history");
  assert.strictEqual(btnHistory.hidden, false, "History button should be visible in documentReview mode");
  assert.ok(ctx.state.renderedReviewResult, "Active review result should be restored for doc-session-1");
  assert.strictEqual(ctx.state.renderedReviewResult.issues[0].title, "问题1");

  ctx.state.documentSessionId = "doc-session-2";
  ctx.state.renderedReviewResult = null;
  ctx.switchMode("documentReview");

  assert.strictEqual(ctx.state.renderedReviewResult, null, "doc-session-2 should not see doc-session-1 active result");
  assert.strictEqual(ctx.state.result, "等待运行。", "doc-session-2 should show default waiting state");
});

test("Behavioral: runFullDocumentReview immediately clears previous report and active result on submission", async () => {
  const ctx = createBaseTestContext();
  const requests = [];

  ctx.state.fullDocumentReviewReportMetadata = { snapshotId: "old-snap" };
  ctx.byId("full-document-review-issue-controls").hidden = false;
  ctx.setActiveResultRecord("word.document_review", "doc-session-1", {
    result: { oldReport: true },
    taskType: "word.document_review"
  });

  ctx.extractFullDocumentReviewBodyYielding = () => Promise.resolve({
    documentId: "doc-id-1",
    contentSha256: "hash1",
    structureSha256: "shash1",
    reviewCharacterCount: 100,
    blocks: [{}],
    tableCount: 0,
    cellCount: 0,
    batches: [{ sequence: 1, batchId: "b1", blocks: [], characterCount: 100, contentSha256: "h", structureSha256: "s", range: {} }],
    editSignal: "sig1"
  });
  ctx.ensureFullDocumentReviewPreparation = () => {};
  ctx.uploadFullDocumentReviewBatches = () => Promise.resolve();
  ctx.request = (url, body) => {
    requests.push({ url, body });
    if (url.includes("/snapshots") && !url.includes("/commit")) {
      return Promise.resolve({ data: { sessionId: "s1", uploadToken: "tok1" } });
    }
    if (url.includes("/commit")) {
      return Promise.resolve({ data: { snapshotId: "snap-new-1", snapshotToken: "stok1", capacity: {} } });
    }
    if (url.includes("/jobs")) {
      return Promise.resolve({ data: { jobId: "job-full-123" } });
    }
    return Promise.resolve({ data: {} });
  };
  ctx.pollFullDocumentReviewJob = () => {};

  const runFullSrc = functionSource("runFullDocumentReview");
  vm.runInNewContext(`${runFullSrc}\np = runFullDocumentReview();`, ctx);

  assert.strictEqual(ctx.state.fullDocumentReviewReportMetadata, null, "Report metadata must be cleared immediately");
  assert.strictEqual(ctx.byId("full-document-review-issue-controls").hidden, true, "Issue controls must be hidden immediately");
  assert.strictEqual(ctx.getActiveResultRecord("word.document_review", "doc-session-1"), null, "Active review result must be cleared immediately");

  await ctx.p;

  const snapReq = requests.find((r) => r.url === "/word/document-review/full/snapshots");
  assert.ok(snapReq, "Snapshot request must be sent");
  assert.strictEqual(snapReq.body.host, "wps");
  assert.strictEqual(snapReq.body.documentSessionId, "doc-session-1");
  assert.strictEqual(snapReq.body.documentDisplayName, "测试文档.docx");

  const jobReq = requests.find((r) => r.url === "/word/document-review/full/jobs");
  assert.ok(jobReq, "Job request must be sent");
  assert.strictEqual(jobReq.body.host, "wps");
  assert.strictEqual(jobReq.body.documentSessionId, "doc-session-1");
  assert.strictEqual(jobReq.body.documentDisplayName, "测试文档.docx");

  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-session-1"),
    true,
    "Full review task slot must be claimed"
  );
});

test("Behavioral: runDocumentReview and runFullDocumentReview guard document session slots", () => {
  const ctx = createBaseTestContext();
  let requested = false;
  ctx.request = () => { requested = true; return Promise.resolve({}); };

  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "wps", "word.document_review", "doc-session-1", "existing-job-1");

  const runDocSrc = functionSource("runDocumentReview");
  vm.runInNewContext(`${runDocSrc}\nrunDocumentReview();`, ctx);

  assert.strictEqual(requested, false, "runDocumentReview should not make requests when slot is busy");
  assert.strictEqual(ctx.state.status, "当前文档已存在进行中的文档审查任务，请等待其完成。");

  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-session-1", "existing-full-1");
  const runFullSrc = functionSource("runFullDocumentReview");
  vm.runInNewContext(`${runFullSrc}\nrunFullDocumentReview();`, ctx);

  assert.strictEqual(requested, false, "runFullDocumentReview should not make requests when slot is busy");
  assert.strictEqual(ctx.state.status, "当前文档已存在进行中的全篇审查任务，请等待其完成。");
});

test("Behavioral: runDocumentReview transmits document identity and claims slot", async () => {
  const ctx = createBaseTestContext();
  let capturedBody = null;

  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "document" });
  ctx.extractDocument = () => ({ text: "段落正文", selectionMode: "document" });
  ctx.pollDocumentReviewJob = () => {};
  ctx.request = (url, body) => {
    capturedBody = body;
    return Promise.resolve({ data: { jobId: "review-job-777" } });
  };

  const runDocSrc = functionSource("runDocumentReview");
  vm.runInNewContext(`${runDocSrc}\nrunDocumentReview();`, ctx);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.ok(capturedBody, "Request should be executed");
  assert.strictEqual(capturedBody.host, "wps");
  assert.strictEqual(capturedBody.documentSessionId, "doc-session-1");
  assert.strictEqual(capturedBody.documentDisplayName, "测试文档.docx");
  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review", "doc-session-1"),
    true,
    "Task slot must be claimed for document review"
  );
});

test("Behavioral: Terminal cleanup in pollFullDocumentReviewJob releases slot and saves result per document session", async () => {
  const ctx = createBaseTestContext();

  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-submitted", "job-full-completed");
  ctx.state.fullDocumentReviewJobId = "job-full-completed";
  ctx.state.documentSessionId = "doc-switched";

  ctx.request = (url) => {
    if (url.includes("/report")) {
      return Promise.resolve({ data: { summary: "全篇审查全部完成", issueCount: 0 } });
    }
    return Promise.resolve({ data: { status: "completed" } });
  };

  ctx.pollFullDocumentReviewJob("job-full-completed", "doc-submitted");

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-submitted"),
    false,
    "Submitted document task slot must be released upon completion"
  );

  const activeRec = ctx.getActiveResultRecord("word.document_review", "doc-submitted");
  assert.ok(activeRec, "Active review result must be recorded for submitted document session");
  assert.strictEqual(activeRec.jobId, "job-full-completed");
  assert.strictEqual(activeRec.result.report.summary, "全篇审查全部完成");

  assert.strictEqual(
    ctx.getActiveResultRecord("word.document_review", "doc-switched"),
    null,
    "Switched document must not have result recorded"
  );
});

test("Behavioral: Opening a history report sets viewingHistoryReport, preserves active result, and provides return path", async () => {
  const cardElement = {
    className: "word-history-card",
    querySelector: () => null,
    insertBefore: function(el) { cardElement.detail = el; },
    appendChild: function(el) { cardElement.detail = el; }
  };
  const btnElement = {
    closest: (sel) => (sel === ".word-history-card" ? cardElement : null),
    textContent: "查看"
  };

  const ctx = createBaseTestContext();

  ctx.setActiveResultRecord("word.document_review", "doc-session-1", {
    result: { text: "当前活跃审查结果" },
    taskType: "word.document_review",
    documentSessionId: "doc-session-1"
  });

  ctx.state.historyItems = [
    {
      id: "hist_1",
      taskType: "word.document_review",
      jobId: "full-job-hist",
      result: {
        reportType: "full_document_review",
        reportId: "full-job-hist",
        summary: "历史报告摘要"
      }
    }
  ];

  ctx.request = () => Promise.resolve({ data: { summary: "历史报告数据" } });

  ctx.btn = btnElement;
  vm.runInNewContext(`p = handleWritingHistoryViewItem("hist_1", btn);`, ctx);
  await ctx.p;

  assert.ok(cardElement.detail, "Detail element should be attached to card");
  assert.ok(cardElement.detail.openBtn, "Open button should exist on detail");
  cardElement.detail.openBtn.click();

  assert.ok(ctx.state.viewingHistoryReport, "viewingHistoryReport should be set when viewing history");
  assert.strictEqual(ctx.state.viewingHistoryReport.jobId, "full-job-hist");

  const activeBefore = ctx.getActiveResultRecord("word.document_review", "doc-session-1");
  assert.ok(activeBefore, "Active review result must not be deleted when viewing history");
  assert.strictEqual(activeBefore.result.text, "当前活跃审查结果");

  ctx.restoreActiveReviewResult();
  assert.strictEqual(ctx.state.viewingHistoryReport, null, "viewingHistoryReport should be cleared on return");
  assert.strictEqual(ctx.state.status, "已恢复当前文档审查结果。");
});

test("Behavioral: Document switching isolates task slots across document sessions", () => {
  const slots = {};
  const host = "wps";
  const taskType = "word.document_review";

  helpers.claimTaskSlot(slots, host, taskType, "doc-session-A", "job-A-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-A"),
    true,
    "Document A slot should be busy"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-B"),
    false,
    "Document B slot should be free"
  );

  const fullTaskType = "word.document_review.full";
  helpers.claimTaskSlot(slots, host, fullTaskType, "doc-session-B", "job-B-full-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-B"),
    true,
    "Document B full review slot should be busy"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-A"),
    false,
    "Document A full review slot should be free"
  );

  helpers.releaseTaskSlot(slots, host, taskType, "doc-session-A", "job-A-001");
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, taskType, "doc-session-A"),
    false,
    "Document A slot should now be free"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(slots, host, fullTaskType, "doc-session-B"),
    true,
    "Document B full review slot remains busy"
  );
});

test("Behavioral: Pane reopen recovers review jobs only when host, taskType, and documentSessionId match", () => {
  const ctx = createBaseTestContext();

  ctx.storage["ai-wps-full-document-review-active-job-v1"] = JSON.stringify({
    jobId: "full-job-999",
    host: "wps",
    taskType: "word.document_review.full",
    documentSessionId: "doc-session-X"
  });

  ctx.state.documentSessionId = "doc-session-X";
  const resumedMatching = ctx.resumeFullDocumentReviewActiveJob();
  assert.strictEqual(resumedMatching, true, "Should resume when session matches");
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, "full-job-999");
  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-session-X"),
    true,
    "Should claim task slot on resume"
  );

  ctx.state.fullDocumentReviewJobId = "";
  ctx.state.documentSessionId = "doc-session-Y";
  const resumedMismatchedDoc = ctx.resumeFullDocumentReviewActiveJob();
  assert.strictEqual(resumedMismatchedDoc, false, "Should not resume on foreign documentSessionId");
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, "", "Job ID should remain empty");

  ctx.storage["ai-wps-full-document-review-active-job-v1"] = JSON.stringify({
    jobId: "full-job-foreign-host",
    host: "word",
    taskType: "word.document_review.full",
    documentSessionId: "doc-session-X"
  });
  ctx.state.documentSessionId = "doc-session-X";
  const resumedMismatchedHost = ctx.resumeFullDocumentReviewActiveJob();
  assert.strictEqual(resumedMismatchedHost, false, "Should not resume on foreign host");

  ctx.storage["ai-wps-document-review-active-job-v1"] = JSON.stringify({
    jobId: "reg-job-888",
    host: "wps",
    taskType: "word.document_review",
    documentSessionId: "doc-session-A"
  });

  ctx.state.documentSessionId = "doc-session-B";
  ctx.resumeDocumentReviewActiveJob();
  assert.strictEqual(ctx.state.documentReviewJobId, "", "Regular review should not resume on different doc");

  ctx.state.documentSessionId = "doc-session-A";
  ctx.resumeDocumentReviewActiveJob();
  assert.strictEqual(ctx.state.documentReviewJobId, "reg-job-888", "Regular review should resume when doc matches");
  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review", "doc-session-A"),
    true,
    "Regular review slot should be claimed"
  );
});

test("Behavioral: Expired report shows clear unavailable notice in history detail", async () => {
  const cardElement = {
    className: "word-history-card",
    querySelector: () => null,
    insertBefore: () => {},
    appendChild: (el) => { cardElement.detail = el; }
  };
  const btnElement = {
    closest: (sel) => (sel === ".word-history-card" ? cardElement : null),
    textContent: "查看"
  };
  let requestedUrl = "";

  const ctx = createBaseTestContext();
  ctx.state.historyItems = [
    {
      id: "hist_expired_1",
      taskType: "word.document_review",
      jobId: "full-job-expired",
      result: {
        reportType: "full_document_review",
        reportId: "full-job-expired",
        summary: "历史全篇审查摘要"
      }
    }
  ];
  ctx.request = (url) => {
    requestedUrl = url;
    const err = new Error("全篇审查尚未生成可用的结构化报告。");
    err.httpStatus = 404;
    err.adapterCode = "FULL_DOCUMENT_REVIEW_REPORT_NOT_AVAILABLE";
    return Promise.reject(err);
  };

  ctx.btn = btnElement;
  vm.runInNewContext(`p = handleWritingHistoryViewItem("hist_expired_1", btn);`, ctx);
  await ctx.p;

  assert.ok(requestedUrl.includes("/word/document-review/full/jobs/full-job-expired/report"));
  assert.ok(cardElement.detail, "Detail element should be attached");
  assert.ok(
    cardElement.detail.innerHTML.includes("专用报告已过期或不可用"),
    "Detail element must notify user that dedicated report has expired"
  );
});

test("Behavioral: History deletion calls DELETE API and updates list", async () => {
  let deletedId = "";
  const container = { innerHTML: "" };
  const ctx = createBaseTestContext();
  ctx.state.historyItems = [
    { id: "h1", taskType: "word.document_review" },
    { id: "h2", taskType: "word.document_review" }
  ];
  ctx.byId = (id) => id === "word-history-content" ? container : ctx.byId(id);
  ctx.request = (url, body, options) => {
    if (options && options.method === "DELETE") {
      deletedId = url.replace("/history/", "");
      return Promise.resolve({ success: true, data: { deleted: true } });
    }
    return Promise.resolve({});
  };

  vm.runInNewContext(`p = handleWritingHistoryDeleteItem("h1");`, ctx);
  await ctx.p;

  assert.strictEqual(deletedId, "h1", "DELETE /history/h1 should be called");
  assert.strictEqual(ctx.state.historyItems.length, 1, "historyItems should have 1 item left");
  assert.strictEqual(ctx.state.historyItems[0].id, "h2");
});
