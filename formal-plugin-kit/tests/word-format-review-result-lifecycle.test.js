const test = require("node:test");
const assert = require("node:assert");
const cp = require("node:child_process");
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
    currentMode: "formatReview",
    lastTaskMode: "formatReview",
    deterministicFormatReviewJobId: "",
    deterministicFormatReviewPollStartedAt: 0,
    deterministicFormatReviewPollErrorCount: 0,
    deterministicFormatReviewEnabled: true,
    deterministicFormatReviewSnapshot: null,
    deterministicFormatReviewReport: null,
    deterministicFormatReviewIssueJobId: "",
    deterministicFormatReviewIssueCursorHistory: [""],
    deterministicFormatReviewIssueFilters: { sort: "source" },
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
            if (sel === ".btn-open-format-report" || sel === ".btn-open-full-report") {
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
    DETERMINISTIC_FORMAT_REVIEW_ACTIVE_JOB_STORAGE_KEY: "ai-wps-deterministic-format-review-active-job-v1",
    FRONTEND_BUILD_VERSION: "1.0.0",
    DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS: 5000,
    DETERMINISTIC_FORMAT_REVIEW_POLL_INTERVAL_MS: 1000,
    DETERMINISTIC_FORMAT_REVIEW_POLL_MAX_WAIT_MS: 60000,
    DETERMINISTIC_FORMAT_REVIEW_POLL_MAX_ERRORS: 5,
    DETERMINISTIC_FORMAT_REVIEW_POLL_RETRY_DELAY_MS: 1000,
    MODE_WORKFLOW_TASK_TYPES: {
      smartWrite: "word.smart_write",
      smartImitation: "word.smart_imitation",
      documentReview: "word.document_review",
      formatReview: "word.format_review"
    },
    TASK_API_KEY_DEFS: [
      { taskType: "word.smart_write", label: "智能编写" },
      { taskType: "word.smart_imitation", label: "智能仿写" },
      { taskType: "word.document_review", label: "文档审查" },
      { taskType: "word.format_review", label: "格式审查" }
    ],
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
    renderDocumentReviewResult: () => true,
    renderDocumentReviewJobProgress: () => {},
    resetSmartWritePreviewState: () => {},
    resetDocumentReviewState: () => {},
    restoreWritingPolicyScene: () => {},
    hideCompareForSmartImitation: () => {},
    updateRewritePromptPreview: () => {},
    loadAndRenderWritingHistory: () => {},
    updateHistoryBadge: () => {},
    describeFetchError: (err) => (err && err.message) || String(err || ""),
    describeDocumentReviewError: (err) => (err && err.message) || String(err || ""),
    getCurrentWorkflowTaskType: () => "word.format_review",
    modeConfig: {
      smartWrite: { title: "智能编写", showRewriteOptions: true },
      smartImitation: { title: "智能仿写" },
      documentReview: { title: "文档审查", showDocumentReviewOptions: true, primaryText: "开始审查" },
      formatReview: { title: "格式审查", showFixedTemplate: true, primaryText: "开始格式审查" },
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
    "loadDeterministicFormatReviewActiveJob",
    "saveDeterministicFormatReviewActiveJob",
    "clearDeterministicFormatReviewActiveJob",
    "clearDeterministicFormatReviewPresentation",
    "cleanupDeterministicFormatReviewTerminal",
    "restoreActiveReviewResult",
    "resumeDeterministicFormatReviewActiveJob",
    "renderDeterministicFormatReviewReport",
    "loadDeterministicFormatReviewReport",
    "loadDeterministicFormatReviewIssuePage",
    "renderDeterministicFormatReviewIssuePage",
    "renderDeterministicFormatReviewDiagnostics",
    "pollDeterministicFormatReviewJob",
    "switchMode",
    "switchWordHistoryView",
    "handleWritingHistoryViewItem",
    "handleWritingHistoryDeleteItem"
  ];

  const bundle = fns.map((fn) => functionSource(fn)).join("\n");
  vm.runInNewContext(bundle, ctx);
  return ctx;
}

test("renderWritingHistoryList renders format review cards", () => {
  const items = [
    {
      id: "hist_format_1",
      taskType: "word.format_review",
      jobId: "job-format-001",
      completedAt: "2026-09-10T10:00:00Z",
      documentDisplayName: "技术规范书.docx",
      serviceName: "Word 格式审查",
      modelName: "format-v2",
      result: {
        reportType: "format_review",
        reportId: "job-format-001",
        jobId: "job-format-001",
        issueCount: 4,
        duplicateGroupCount: 1,
        complianceStatus: "violations_found"
      }
    }
  ];

  const html = helpers.renderWritingHistoryList(items);

  assert.ok(html.includes("技术规范书.docx"), "Must include format review document name");
  assert.ok(html.includes("格式审查成果"), "Must include format review card title");
  assert.ok(html.includes("4 项问题"), "Must include format review issue count snippet");
  assert.ok(html.includes('data-history-id="hist_format_1"'), "Must include card history id");
  assert.ok(html.includes("btn-history-view"), "Must have view button");
  assert.ok(html.includes("btn-history-delete"), "Must have delete button");
  assert.ok(!html.includes("btn-history-copy"), "Must NOT have copy button for structured format report");
});

test("Behavioral: switchMode for formatReview displays history button and restores active result per document session", () => {
  const ctx = createBaseTestContext();

  ctx.setActiveResultRecord("word.format_review", "doc-session-1", {
    result: {
      reportType: "format_review",
      report: { summary: { issueCount: 2 } },
      jobId: "format-job-prev"
    },
    traceId: "format-job-prev",
    jobId: "format-job-prev",
    taskType: "word.format_review",
    documentSessionId: "doc-session-1"
  });

  ctx.switchMode("formatReview");

  const btnViewHistory = ctx.byId("btn-view-history");
  assert.strictEqual(btnViewHistory.hidden, false, "History button should be visible in formatReview mode");

  const activeRec = ctx.getActiveResultRecord("word.format_review", "doc-session-1");
  assert.ok(activeRec, "Active format review result must be restored for doc-session-1");
  assert.strictEqual(activeRec.jobId, "format-job-prev");

  // Switch to another document session without active result
  ctx.state.documentSessionId = "doc-session-2";
  ctx.switchMode("formatReview");
  const doc2Rec = ctx.getActiveResultRecord("word.format_review", "doc-session-2");
  assert.strictEqual(doc2Rec, null, "doc-session-2 should have no active format review result");
});

test("Behavioral: resumeDeterministicFormatReviewActiveJob recovers unfinished jobs and rejects completed jobs", async () => {
  const ctx = createBaseTestContext();
  let pollStarted = false;
  ctx.pollDeterministicFormatReviewJob = (jid) => {
    pollStarted = true;
  };

  // 1. Unfinished running job with matching document session -> resumes
  ctx.storage["ai-wps:review-active-job:word.format_review:doc-session-1"] = JSON.stringify({
    jobId: "format-job-running",
    host: "wps",
    taskType: "word.format_review",
    documentSessionId: "doc-session-1",
    startedAt: Date.now()
  });

  ctx.request = (url) => {
    if (url.includes("/word/format-review/jobs/format-job-running")) {
      return Promise.resolve({ data: { status: "running", jobId: "format-job-running" } });
    }
    return Promise.resolve({ data: {} });
  };

  const resumedRunning = ctx.resumeDeterministicFormatReviewActiveJob();
  assert.strictEqual(resumedRunning, true, "Should return true when attempting resume");
  assert.strictEqual(
    helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.format_review", "doc-session-1"),
    true,
    "Task slot must be claimed on resume"
  );
  await new Promise((r) => setTimeout(r, 10));
  assert.strictEqual(pollStarted, true, "Polling should be initiated for running job");

  // 2. Completed job -> must NOT be loaded via active recovery
  const ctxCompleted = createBaseTestContext();

  ctxCompleted.storage["ai-wps:review-active-job:word.format_review:doc-session-1"] = JSON.stringify({
    jobId: "format-job-completed",
    host: "wps",
    taskType: "word.format_review",
    documentSessionId: "doc-session-1",
    startedAt: Date.now()
  });

  let loadedReport = false;
  ctxCompleted.loadDeterministicFormatReviewReport = () => {
    loadedReport = true;
    return Promise.resolve();
  };

  ctxCompleted.request = (url) => {
    if (url.includes("/word/format-review/jobs/format-job-completed")) {
      return Promise.resolve({ data: { status: "completed", jobId: "format-job-completed" } });
    }
    return Promise.resolve({ data: {} });
  };

  const resumedCompleted = ctxCompleted.resumeDeterministicFormatReviewActiveJob();
  assert.strictEqual(resumedCompleted, true, "Initial resume check begins");
  await new Promise((r) => setTimeout(r, 10));

  assert.strictEqual(loadedReport, false, "Completed report must NOT be loaded through active recovery");
  assert.strictEqual(
    helpers.isTaskSlotBusy(ctxCompleted.state.activeTaskSlots, "wps", "word.format_review", "doc-session-1"),
    false,
    "Task slot must be free after completed job ignored"
  );
});

test("Behavioral: Opening a format review history report sets viewingHistoryReport, preserves active result, and provides return path", async () => {
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

  const ctx = createBaseTestContext();
  ctx.state.historyItems = [
    {
      id: "hist_fmt_1",
      taskType: "word.format_review",
      jobId: "format-job-hist-1",
      documentDisplayName: "历史文档.docx",
      result: {
        reportType: "format_review",
        reportId: "format-job-hist-1",
        issueCount: 3
      }
    }
  ];

  ctx.setActiveResultRecord("word.format_review", "doc-session-1", {
    result: { reportType: "format_review", text: "当前活跃格式审查结果" },
    jobId: "active-format-job"
  });

  ctx.request = (url) => {
    if (url.includes("/word/format-review/jobs/format-job-hist-1/report")) {
      return Promise.resolve({
        data: {
          issueCount: 3,
          summary: { issueCount: 3, complianceStatus: "violations_found" }
        }
      });
    }
    return Promise.resolve({ data: {} });
  };

  ctx.btn = btnElement;
  vm.runInNewContext(`p = handleWritingHistoryViewItem("hist_fmt_1", btn);`, ctx);
  await ctx.p;

  assert.ok(cardElement.detail, "Detail element must be created");
  assert.ok(cardElement.detail.openBtn, "Open button must be created");
  cardElement.detail.openBtn.click();

  assert.ok(ctx.state.viewingHistoryReport, "viewingHistoryReport must be set");
  assert.strictEqual(ctx.state.viewingHistoryReport.jobId, "format-job-hist-1");

  const activeBefore = ctx.getActiveResultRecord("word.format_review", "doc-session-1");
  assert.ok(activeBefore, "Active result must not be deleted when viewing history");

  ctx.restoreActiveReviewResult();
  assert.strictEqual(ctx.state.viewingHistoryReport, null, "viewingHistoryReport should be cleared on return");
  assert.strictEqual(ctx.state.status, "已恢复当前格式审查结果。");
});

test("Behavioral: Expired format review report shows unavailable notice in history detail", async () => {
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

  const ctx = createBaseTestContext();
  ctx.state.historyItems = [
    {
      id: "hist_fmt_expired",
      taskType: "word.format_review",
      jobId: "format-job-expired",
      result: {
        reportType: "format_review",
        reportId: "format-job-expired",
        issueCount: 2
      }
    }
  ];

  ctx.request = () => Promise.reject(new Error("Report expired"));

  ctx.btn = btnElement;
  vm.runInNewContext(`p = handleWritingHistoryViewItem("hist_fmt_expired", btn);`, ctx);
  await ctx.p;

  assert.ok(cardElement.detail, "Detail should exist");
  assert.ok(cardElement.detail.innerHTML.includes("history-report-expired"), "Should display expired notice");
  assert.ok(!cardElement.detail.innerHTML.includes("btn-open-format-report"), "Should NOT show open button on expired report");
});

test("taskpane.js syntax and integrity check", () => {
  const taskpanePath = path.join(root, "taskpane.js");
  const result = cp.spawnSync(process.execPath, ["--check", taskpanePath], {
    encoding: "utf8"
  });
  assert.strictEqual(
    result.status,
    0,
    `taskpane.js syntax error:\n${result.stderr || result.stdout}`
  );
});

test("Behavioral: Background format review completion for document A does not contaminate document B", async () => {
  let currentDocSession = "doc-session-A";
  const ctx = createBaseTestContext({
    ctx: {
      getActiveDocument: () => ({ Name: "文档A.docx", __sessionId: currentDocSession }),
      helpers: {
        ...helpers,
        getDocumentSessionId: () => currentDocSession,
        getDocumentDisplayName: () => (currentDocSession === "doc-session-A" ? "文档A.docx" : "文档B.docx")
      }
    },
    state: {
      documentSessionId: "doc-session-A",
      documentDisplayName: "文档A.docx",
      deterministicFormatReviewJobId: "job-fmt-A"
    }
  });

  // Setup active review job for doc-session-A
  ctx.setActiveReviewJobRecord("word.format_review", "doc-session-A", {
    jobId: "job-fmt-A",
    status: "running",
    taskType: "word.format_review"
  });

  const reportA = {
    issueCount: 5,
    summary: { issueCount: 5, complianceStatus: "violations_found" }
  };

  ctx.request = (url) => {
    if (url.includes("/word/format-review/jobs/job-fmt-A/report")) {
      return Promise.resolve({ data: reportA, traceId: "trace-fmt-A" });
    }
    if (url.includes("/word/format-review/jobs/job-fmt-A/issues")) {
      return Promise.resolve({ data: { items: [], total: 5 } });
    }
    if (url.includes("/word/format-review/jobs/job-fmt-A")) {
      return Promise.resolve({ data: { jobId: "job-fmt-A", status: "completed" } });
    }
    return Promise.resolve({ data: {} });
  };

  // Switch to Document B before poll completes
  currentDocSession = "doc-session-B";
  ctx.state.documentSessionId = "doc-session-B";
  ctx.state.documentDisplayName = "文档B.docx";
  ctx.setStatus("正在编辑文档B");
  ctx.setPlainResult("文档B正文");

  // Trigger report load for Document A's job with targetDocSession = "doc-session-A"
  await ctx.loadDeterministicFormatReviewReport("job-fmt-A", "doc-session-A");

  // 1. Result for Document A must be recorded
  const recA = ctx.getActiveResultRecord("word.format_review", "doc-session-A");
  assert.ok(recA, "Document A active result must be saved");
  assert.strictEqual(recA.jobId, "job-fmt-A");
  assert.strictEqual(recA.result.report.issueCount, 5);

  // 2. Document B must NOT be contaminated
  const recB = ctx.getActiveResultRecord("word.format_review", "doc-session-B");
  assert.strictEqual(recB, null, "Document B must NOT have Document A's result");
  assert.strictEqual(ctx.state.deterministicFormatReviewReport, null, "Active UI state report must not be updated to Document A while viewing Document B");

  // 3. User switches back to Document A and restores result
  currentDocSession = "doc-session-A";
  ctx.state.documentSessionId = "doc-session-A";
  ctx.state.documentDisplayName = "文档A.docx";
  ctx.restoreActiveReviewResult();

  assert.ok(ctx.state.deterministicFormatReviewReport, "Document A report restored after switching back");
  assert.strictEqual(ctx.state.deterministicFormatReviewReport.issueCount, 5);
});
