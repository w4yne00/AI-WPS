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
    "setMaterialImportVisible",
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

test("Behavioral: resumeDeterministicFormatReviewActiveJob recovers running and completed jobs", async () => {
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

  // 2. Completed job -> restore the completed report into the current preview.
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

  assert.strictEqual(loadedReport, true, "Completed report must be loaded through active recovery");
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

test("late format review summary cannot replace a newly running job result", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  ctx.request = () => new Promise((resolve) => { deliver = resolve; });
  let rendered = false;
  ctx.loadDeterministicFormatReviewIssuePage = () => { rendered = true; return Promise.resolve(); };
  ctx.state.deterministicFormatReviewJobId = "old-job";
  const pending = ctx.loadDeterministicFormatReviewReport("old-job", "doc-session-1");
  ctx.state.deterministicFormatReviewJobId = "new-job";
  ctx.setActiveResultRecord("word.format_review", "doc-session-1", { jobId: "new-job" });
  deliver({ data: { summary: { issueCount: 1 } } });
  await pending;
  assert.strictEqual(ctx.getActiveResultRecord("word.format_review", "doc-session-1").jobId, "new-job");
  assert.strictEqual(rendered, false);
});

test("late format report completion cannot clear a newer task busy state or status", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  ctx.state.deterministicFormatReviewJobId = "old-job";
  ctx.request = () => Promise.resolve({ data: { status: "completed" } });
  ctx.loadDeterministicFormatReviewReport = () => new Promise((resolve) => { deliver = resolve; });
  ctx.pollDeterministicFormatReviewJob("old-job", "doc-session-1");
  await Promise.resolve();
  ctx.state.deterministicFormatReviewJobId = "new-job";
  ctx.state.modelTaskBusy = true;
  ctx.state.status = "new task running";
  deliver();
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(ctx.state.modelTaskBusy, true);
  assert.strictEqual(ctx.state.status, "new task running");
});

test("late format report error cannot replace a newer task preview", async () => {
  const ctx = createBaseTestContext();
  let rejectReport;
  ctx.state.deterministicFormatReviewJobId = "old-job";
  ctx.request = () => Promise.resolve({ data: { status: "completed" } });
  ctx.loadDeterministicFormatReviewReport = () => new Promise((resolve, reject) => { rejectReport = reject; });
  ctx.pollDeterministicFormatReviewJob("old-job", "doc-session-1");
  await Promise.resolve();
  ctx.state.deterministicFormatReviewJobId = "new-job";
  ctx.state.modelTaskBusy = true;
  ctx.state.status = "new task running";
  rejectReport(new Error("old report failed"));
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(ctx.state.modelTaskBusy, true);
  assert.strictEqual(ctx.state.status, "new task running");
});

test("format review submits identical input again with a fresh client job ID after completion", async () => {
  const ctx = createBaseTestContext();
  const jobs = [];
  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "document" });
  ctx.extractDeterministicFormatReviewSnapshot = () => ({ blocks: [], contentSha256: "same", structureSha256: "same", formatSha256: "same", documentIdentity: {}, coverage: {}, editSequence: "1" });
  ctx.helpers.buildDeterministicFormatReviewBatches = () => [];
  ctx.ensureDeterministicFormatReviewPreparation = () => {};
  ctx.uploadDeterministicFormatReviewBatches = () => Promise.resolve();
  ctx.exportDeterministicFormatReviewImageGroups = () => Promise.resolve();
  ctx.pollDeterministicFormatReviewJob = () => {};
  ctx.discardDeterministicFormatReviewSnapshot = () => {};
  ctx.request = (url, body) => {
    if (url === "/word/format-review/jobs") jobs.push({ ...body });
    return Promise.resolve({ data: { snapshotId: "same-snapshot", snapshotToken: "token", jobId: "job-" + jobs.length } });
  };
  vm.runInNewContext(functionSource("runDeterministicFormatReview"), ctx);
  await ctx.runDeterministicFormatReview();
  ctx.cleanupDeterministicFormatReviewTerminal("doc-session-1", ctx.state.deterministicFormatReviewJobId);
  await ctx.runDeterministicFormatReview();
  assert.strictEqual(jobs.length, 2);
  assert.ok(jobs[0].clientJobId);
  assert.strictEqual(jobs[0].snapshotId, jobs[1].snapshotId);
  assert.notStrictEqual(jobs[0].clientJobId, jobs[1].clientJobId);
});

test("late format issue page cannot render after a new result or history view is selected", async () => {
  for (const change of ["new-result", "history", "document"]) {
    const ctx = createBaseTestContext();
    let deliver;
    let rendered = false;
    ctx.request = () => new Promise((resolve) => { deliver = resolve; });
    ctx.renderDeterministicFormatReviewIssuePage = () => { rendered = true; };
    const pending = ctx.loadDeterministicFormatReviewIssuePage("old-job", {}, "");
    if (change === "new-result") ctx.setActiveResultRecord("word.format_review", "doc-session-1", { jobId: "new-job" });
    if (change === "history") ctx.state.viewingHistoryReport = { jobId: "history-job" };
    if (change === "document") ctx.state.documentSessionId = "doc-B";
    deliver({ data: { issues: [] } });
    await pending;
    assert.strictEqual(rendered, false, change);
  }
});

test("format summary completes its originating document after switching to another active job", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  ctx.state.deterministicFormatReviewJobId = "job-A";
  ctx.setActiveReviewJobRecord("word.format_review", "doc-A", { jobId: "job-A" });
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "wps", "word.format_review", "doc-A", "job-A");
  ctx.request = (url) => url.includes("/report") ? new Promise(resolve => { deliver = resolve; }) : Promise.resolve({ data: { status: "completed" } });
  ctx.pollDeterministicFormatReviewJob("job-A", "doc-A");
  await Promise.resolve();
  ctx.state.documentSessionId = "doc-B";
  ctx.state.deterministicFormatReviewJobId = "job-B";
  ctx.state.modelTaskBusy = true;
  deliver({ data: { summary: { issueCount: 0 } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(ctx.getActiveReviewJobRecord("word.format_review", "doc-A"), null);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.format_review", "doc-A"), false);
  assert.strictEqual(ctx.getActiveResultRecord("word.format_review", "doc-A").jobId, "job-A");
  assert.strictEqual(ctx.state.deterministicFormatReviewJobId, "job-B");
  assert.strictEqual(ctx.state.modelTaskBusy, true);
});

test("format history page remains valid when a background active result arrives", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  let rendered = false;
  ctx.state.viewingHistoryReport = { jobId: "history-job" };
  ctx.request = () => new Promise(resolve => { deliver = resolve; });
  ctx.renderDeterministicFormatReviewIssuePage = () => { rendered = true; };
  const pending = ctx.loadDeterministicFormatReviewIssuePage("history-job", {}, "");
  ctx.setActiveResultRecord("word.format_review", "doc-session-1", { jobId: "background-job" });
  deliver({ data: { issues: [] } });
  await pending;
  assert.strictEqual(rendered, true);
});

for (const entry of [
  { name: "runDocumentReview", mode: "documentReview", taskType: "word.document_review" },
  { name: "runFullDocumentReview", mode: "documentReview", taskType: "word.document_review" },
  { name: "runDeterministicFormatReview", mode: "formatReview", taskType: "word.format_review" }
]) {
  for (const historyReport of [false, true]) {
    test(entry.name + " starts in the current preview after " + (historyReport ? "viewing a historical report" : "opening history"), async () => {
      const ctx = createBaseTestContext({ state: {
        currentMode: entry.mode,
        fullDocumentReviewEnabled: true,
        historyOpen: !historyReport,
        viewingHistoryReport: historyReport ? { jobId: "old-history-job" } : null,
        historyItems: [{ id: "old-history-item", taskType: entry.taskType }]
      } });
      ctx.getCurrentWorkflowTaskType = () => entry.taskType;
      ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "selection" });
      ctx.clearDocumentReviewActiveJob = () => {};
      ctx.getFullDocumentReviewReadiness = () => ({ fullDocumentReviewReady: true });
      ctx.extractFullDocumentReviewBodyYielding = () => new Promise(() => {});
      ctx.extractDeterministicFormatReviewSnapshotYielding = () => new Promise(() => {});
      ctx.setTimeout = () => 1;
      ctx.byId("word-result-section").hidden = !historyReport;
      ctx.byId("word-history-view").hidden = historyReport;
      ctx.setActiveResultRecord(entry.taskType, "doc-session-1", {
        result: { report: { summary: { issueCount: 9 } } }, jobId: "old-active-job"
      });
      vm.runInNewContext(functionSource(entry.name), ctx);

      ctx[entry.name]();

      assert.strictEqual(ctx.state.historyOpen, false);
      assert.strictEqual(ctx.state.viewingHistoryReport, null);
      assert.strictEqual(ctx.byId("word-result-section").hidden, false);
      assert.strictEqual(ctx.byId("word-history-view").hidden, true);
      assert.strictEqual(ctx.getActiveResultRecord(entry.taskType, "doc-session-1"), null);
      assert.strictEqual(ctx.state.historyItems[0].id, "old-history-item");
      assert.ok(ctx.state.result.includes("正在"));

      const newReport = { summary: "本次新结果" };
      if (entry.name === "runDocumentReview") {
        ctx.renderDocumentReviewResult = data => { ctx.setResult(data.summary); return true; };
        vm.runInNewContext(functionSource("completeDocumentReview"), ctx);
        ctx.completeDocumentReview(newReport, "new-job", "doc-session-1", "new-job");
      } else if (entry.name === "runFullDocumentReview") {
        ctx.DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS = 5000;
        ctx.state.fullDocumentReviewJobId = "new-job";
        ctx.setActiveReviewJobRecord("word.document_review.full", "doc-session-1", { jobId: "new-job" });
        ctx.cleanupFullDocumentReviewTerminal = () => { ctx.state.fullDocumentReviewJobId = ""; };
        ctx.renderFullDocumentReviewReport = data => { ctx.setResult(data.summary); return Promise.resolve(); };
        ctx.request = url => Promise.resolve({ data: url.endsWith("/report") ? newReport : { status: "completed" } });
        vm.runInNewContext(functionSource("pollFullDocumentReviewJob"), ctx);
        ctx.pollFullDocumentReviewJob("new-job", "doc-session-1");
        await new Promise(resolve => setImmediate(resolve));
      } else {
        ctx.state.deterministicFormatReviewPreparing = false;
        ctx.state.deterministicFormatReviewJobId = "new-job";
        ctx.setActiveReviewJobRecord("word.format_review", "doc-session-1", { jobId: "new-job" });
        ctx.request = url => Promise.resolve({ data: url.includes("/report") ? newReport : { issues: [] } });
        ctx.renderDeterministicFormatReviewIssuePage = data => ctx.setResult(data.summary);
        await ctx.loadDeterministicFormatReviewReport("new-job", "doc-session-1");
      }
      assert.strictEqual(ctx.state.result, "本次新结果");
      assert.ok(ctx.getActiveResultRecord(entry.taskType, "doc-session-1"));
    });
  }
}
