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
      return Promise.resolve({ data: { jobId: "job-full-" + requests.filter((r) => r.url.endsWith("/jobs")).length } });
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
  const firstJobId = ctx.state.fullDocumentReviewJobId;
  ctx.cleanupFullDocumentReviewTerminal("doc-session-1", firstJobId);
  await ctx.runFullDocumentReview();
  assert.strictEqual(requests.filter((r) => r.url === "/word/document-review/full/snapshots").length, 2);
  assert.strictEqual(requests.filter((r) => r.url === "/word/document-review/full/jobs").length, 2);
  assert.notStrictEqual(ctx.state.fullDocumentReviewJobId, firstJobId);
  const jobs = requests.filter((r) => r.url === "/word/document-review/full/jobs");
  assert.ok(jobs[0].body.clientJobId);
  assert.notStrictEqual(jobs[0].body.clientJobId, jobs[1].body.clientJobId);
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

// Missing preparation guards allow two clicks to submit two independent jobs.
test("regular review blocks a second click before deferred extraction starts", () => {
  const pending = [];
  const ctx = createBaseTestContext({ ctx: { setTimeout: (fn) => { pending.push(fn); return pending.length; } } });
  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "document" });
  vm.runInNewContext(functionSource("runDocumentReview"), ctx);
  ctx.runDocumentReview();
  ctx.runDocumentReview();
  assert.strictEqual(pending.length, 1);
});

test("full review blocks a second click while the first extraction is pending", () => {
  const ctx = createBaseTestContext();
  let extractions = 0;
  ctx.extractFullDocumentReviewBodyYielding = () => {
    extractions += 1;
    return new Promise(() => {});
  };
  vm.runInNewContext(functionSource("runFullDocumentReview"), ctx);
  ctx.runFullDocumentReview();
  ctx.runFullDocumentReview();
  assert.strictEqual(extractions, 1);
});

test("late full review report cannot replace a newer job or its active result", async () => {
  const ctx = createBaseTestContext();
  let deliverReport;
  ctx.state.fullDocumentReviewJobId = "old-job";
  ctx.request = (url) => url.endsWith("/report")
    ? new Promise((resolve) => { deliverReport = resolve; })
    : Promise.resolve({ data: { status: "completed" } });
  ctx.pollFullDocumentReviewJob("old-job", "doc-session-1");
  await Promise.resolve();
  ctx.state.fullDocumentReviewJobId = "new-job";
  ctx.setActiveResultRecord("word.document_review", "doc-session-1", { jobId: "new-job", result: { summary: "new" } });
  deliverReport({ data: { summary: "old" } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, "new-job");
  assert.strictEqual(ctx.getActiveResultRecord("word.document_review", "doc-session-1").jobId, "new-job");
});

test("full review completion for another document does not render over the current document", async () => {
  const ctx = createBaseTestContext();
  let rendered = false;
  ctx.state.fullDocumentReviewJobId = "job-A";
  ctx.state.documentSessionId = "doc-B";
  ctx.renderFullDocumentReviewReport = () => { rendered = true; return Promise.resolve(); };
  ctx.request = (url) => Promise.resolve({ data: url.endsWith("/report") ? { summary: "A" } : { status: "completed" } });
  ctx.pollFullDocumentReviewJob("job-A", "doc-A");
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ctx.getActiveResultRecord("word.document_review", "doc-A"));
  assert.strictEqual(rendered, false);
});

test("regular review completion is saved to its document without replacing another document preview", () => {
  const ctx = createBaseTestContext();
  vm.runInNewContext(functionSource("completeDocumentReview"), ctx);
  ctx.state.documentSessionId = "doc-B";
  ctx.completeDocumentReview({ issues: [{ title: "A" }] }, "trace-A", "doc-A", "job-A");
  assert.ok(ctx.getActiveResultRecord("word.document_review", "doc-A"));
  assert.strictEqual(ctx.state.renderedReviewResult, undefined);
});

test("late full review page failure cannot replace a newer task status", async () => {
  const ctx = createBaseTestContext();
  let rejectPage;
  ctx.state.fullDocumentReviewJobId = "old-job";
  ctx.request = (url) => Promise.resolve({ data: url.endsWith("/report") ? { summary: "old" } : { status: "completed" } });
  ctx.renderFullDocumentReviewReport = () => new Promise((resolve, reject) => { rejectPage = reject; });
  ctx.pollFullDocumentReviewJob("old-job", "doc-session-1");
  await new Promise((resolve) => setImmediate(resolve));
  ctx.state.fullDocumentReviewJobId = "new-job";
  ctx.state.status = "new task running";
  rejectPage(new Error("old page failed"));
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(ctx.state.status, "new task running");
});

test("regular review submits identical text again with a fresh client job ID after completion", async () => {
  const ctx = createBaseTestContext();
  const submitted = [];
  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "document" });
  ctx.extractDocument = () => ({ text: "相同正文", selectionMode: "document" });
  ctx.pollDocumentReviewJob = () => {};
  ctx.request = (url, body) => {
    submitted.push({ url, body: { ...body } });
    return Promise.resolve({ data: { jobId: body.clientJobId } });
  };
  vm.runInNewContext(functionSource("buildDocumentReviewClientJobId") + functionSource("runDocumentReview"), ctx);
  ctx.runDocumentReview();
  await new Promise((resolve) => setTimeout(resolve, 50));
  ctx.cleanupDocumentReviewTerminal("doc-session-1", ctx.state.documentReviewJobId);
  ctx.runDocumentReview();
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.strictEqual(submitted.length, 2);
  assert.ok(submitted.every((entry) => entry.url === "/word/document-review/jobs" && entry.body.text === "相同正文"));
  assert.notStrictEqual(submitted[0].body.clientJobId, submitted[1].body.clientJobId);
});

test("full review recovers a lost submission response by GET using the same client job ID", async () => {
  const ctx = createBaseTestContext();
  const requests = [];
  let discarded = false;
  ctx.extractFullDocumentReviewBodyYielding = () => Promise.resolve({ documentId: "doc", contentSha256: "same", structureSha256: "same", reviewCharacterCount: 10, blocks: [{}], batches: [], editSignal: "1" });
  ctx.ensureFullDocumentReviewPreparation = () => {};
  ctx.uploadFullDocumentReviewBatches = () => Promise.resolve();
  ctx.discardFullDocumentReviewSnapshot = () => { discarded = true; return Promise.resolve(); };
  ctx.request = (url, body) => {
    requests.push({ url, body });
    if (url === "/word/document-review/full/jobs") return Promise.reject(new Error("connection lost"));
    if (url.includes("/jobs/")) return Promise.resolve({ data: { status: "cancelled" } });
    if (url.endsWith("/commit")) return Promise.resolve({ data: { snapshotId: "snapshot", snapshotToken: "token" } });
    return Promise.resolve({ data: { sessionId: "session", uploadToken: "upload-token" } });
  };
  vm.runInNewContext(functionSource("runFullDocumentReview"), ctx);
  await ctx.runFullDocumentReview();
  await new Promise((resolve) => setImmediate(resolve));
  const posts = requests.filter((entry) => entry.url === "/word/document-review/full/jobs");
  assert.strictEqual(posts.length, 1);
  assert.ok(requests.some((entry) => entry.url === "/word/document-review/full/jobs/" + posts[0].body.clientJobId && entry.body === null));
  assert.strictEqual(discarded, false);
});

test("late full review issue page cannot render after a new result or history view is selected", async () => {
  for (const change of ["new-result", "history", "document"]) {
    const ctx = createBaseTestContext();
    let deliver;
    let rendered = false;
    ctx.request = () => new Promise((resolve) => { deliver = resolve; });
    ctx.renderFullDocumentReviewIssuePage = () => { rendered = true; };
    vm.runInNewContext(functionSource("loadFullDocumentReviewIssuePage"), ctx);
    const pending = ctx.loadFullDocumentReviewIssuePage("old-job", {}, "");
    if (change === "new-result") ctx.setActiveResultRecord("word.document_review", "doc-session-1", { jobId: "new-job" });
    if (change === "history") ctx.state.viewingHistoryReport = { jobId: "history-job" };
    if (change === "document") ctx.state.documentSessionId = "doc-B";
    deliver({ data: { issues: [] } });
    await pending;
    assert.strictEqual(rendered, false, change);
  }
});

test("full review report completes its originating document after switching to another active job", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  ctx.state.fullDocumentReviewJobId = "job-A";
  ctx.setActiveReviewJobRecord("word.document_review.full", "doc-A", { jobId: "job-A" });
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-A", "job-A");
  ctx.request = (url) => url.endsWith("/report") ? new Promise(resolve => { deliver = resolve; }) : Promise.resolve({ data: { status: "completed" } });
  ctx.pollFullDocumentReviewJob("job-A", "doc-A");
  await Promise.resolve();
  ctx.state.documentSessionId = "doc-B";
  ctx.state.fullDocumentReviewJobId = "job-B";
  ctx.state.modelTaskBusy = true;
  deliver({ data: { summary: "A complete" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(ctx.getActiveReviewJobRecord("word.document_review.full", "doc-A"), null);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "wps", "word.document_review.full", "doc-A"), false);
  assert.strictEqual(ctx.getActiveResultRecord("word.document_review", "doc-A").jobId, "job-A");
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, "job-B");
  assert.strictEqual(ctx.state.modelTaskBusy, true);
});

test("old full submission rejection does not clear another document's active task", async () => {
  const ctx = createBaseTestContext();
  let rejectPost;
  ctx.extractFullDocumentReviewBodyYielding = () => Promise.resolve({ documentId: "doc", contentSha256: "same", structureSha256: "same", reviewCharacterCount: 10, blocks: [{}], batches: [], editSignal: "1" });
  ctx.ensureFullDocumentReviewPreparation = () => {};
  ctx.uploadFullDocumentReviewBatches = () => Promise.resolve();
  ctx.discardFullDocumentReviewSnapshot = () => Promise.resolve();
  ctx.request = (url) => {
    if (url.endsWith("/jobs")) return new Promise((resolve, reject) => { rejectPost = reject; });
    if (url.endsWith("/commit")) return Promise.resolve({ data: { snapshotId: "snapshot", snapshotToken: "token" } });
    return Promise.resolve({ data: { sessionId: "session", uploadToken: "token" } });
  };
  vm.runInNewContext(functionSource("runFullDocumentReview"), ctx);
  const pending = ctx.runFullDocumentReview();
  await new Promise(resolve => setImmediate(resolve));
  ctx.state.documentSessionId = "doc-B";
  ctx.state.fullDocumentReviewJobId = "job-B";
  ctx.state.fullDocumentReviewPreparing = true;
  ctx.state.modelTaskBusy = true;
  ctx.state.status = "B running";
  rejectPost(Object.assign(new Error("A rejected"), { httpStatus: 400 }));
  await pending;
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, "job-B");
  assert.strictEqual(ctx.state.fullDocumentReviewPreparing, true);
  assert.strictEqual(ctx.state.modelTaskBusy, true);
  assert.strictEqual(ctx.state.status, "B running");
});

test("full history page remains valid when a background active result arrives", async () => {
  const ctx = createBaseTestContext();
  let deliver;
  let rendered = false;
  ctx.state.viewingHistoryReport = { jobId: "history-job" };
  ctx.request = () => new Promise(resolve => { deliver = resolve; });
  ctx.renderFullDocumentReviewIssuePage = () => { rendered = true; };
  vm.runInNewContext(functionSource("loadFullDocumentReviewIssuePage"), ctx);
  const pending = ctx.loadFullDocumentReviewIssuePage("history-job", {}, "");
  ctx.setActiveResultRecord("word.document_review", "doc-session-1", { jobId: "background-job" });
  deliver({ data: { issues: [] } });
  await pending;
  assert.strictEqual(rendered, true);
});

test("full snapshot cleanup cannot clear a newer task started while discard is pending", async () => {
  const ctx = createBaseTestContext();
  let finishDiscard;
  ctx.extractFullDocumentReviewBodyYielding = () => Promise.reject(new Error("old extraction failed"));
  ctx.discardFullDocumentReviewSnapshot = () => new Promise(resolve => { finishDiscard = resolve; });
  vm.runInNewContext(functionSource("runFullDocumentReview"), ctx);
  const pending = ctx.runFullDocumentReview();
  await new Promise(resolve => setImmediate(resolve));
  ctx.setActiveReviewJobRecord("word.document_review.full", "doc-session-1", { jobId: "new-job" });
  ctx.state.fullDocumentReviewJobId = "new-job";
  ctx.state.modelTaskBusy = true;
  ctx.state.status = "new task running";
  finishDiscard();
  await pending;
  assert.strictEqual(ctx.getActiveReviewJobRecord("word.document_review.full", "doc-session-1").jobId, "new-job");
  assert.strictEqual(ctx.state.status, "new task running");
  assert.strictEqual(ctx.state.modelTaskBusy, true);
});

for (const change of ["switch", "close"]) {
  test(`full review preparation releases its busy state after document ${change}`, async () => {
    const ctx = createBaseTestContext();
    let finishExtraction;
    let extractionCount = 0;
    ctx.helpers.getDocumentSessionId = document => document ? document.__sessionId : "";
    ctx.extractFullDocumentReviewBodyYielding = () => {
      extractionCount += 1;
      return extractionCount === 1
        ? new Promise(resolve => { finishExtraction = resolve; })
        : Promise.reject(new Error("next extraction failed"));
    };
    vm.runInNewContext([
      "ensureFullDocumentReviewPreparation", "discardFullDocumentReviewSnapshot", "runFullDocumentReview"
    ].map(functionSource).join("\n"), ctx);
    const pending = ctx.runFullDocumentReview();
    if (change === "switch") {
      ctx.state.documentSessionId = "doc-B";
    } else {
      ctx.getActiveDocument = () => null;
    }
    ctx.state.status = "current document status";
    finishExtraction({ editSignal: "1" });
    await pending;
    assert.strictEqual(ctx.state.fullDocumentReviewPreparing, false);
    assert.strictEqual(ctx.state.modelTaskBusy, false);
    assert.strictEqual(ctx.getActiveReviewJobRecord("word.document_review.full", "doc-session-1"), null);
    assert.strictEqual(ctx.state.status, "current document status");

    ctx.getActiveDocument = () => ({ __sessionId: "doc-B", Name: "B.docx" });
    await ctx.runFullDocumentReview();
    assert.strictEqual(extractionCount, 2, "a new document can start another review");
  });
}

for (const mode of ["smartWrite", "smartImitation"]) {
  for (const submitted of [false, true]) {
    test(`old full preparation failure preserves a new ${mode} task (${submitted ? "submitted" : "preparing"})`, async () => {
      const ctx = createBaseTestContext();
      let rejectExtraction;
      let cancelVisible = true;
      ctx.extractFullDocumentReviewBodyYielding = () => new Promise((resolve, reject) => { rejectExtraction = reject; });
      ctx.getActiveWritingJobRecord = () => null;
      ctx.resumeWritingActiveJob = () => false;
      ctx.fillSmartImitationTemplateFromSelection = () => {};
      ctx.setDocumentReviewCancelVisible = visible => { cancelVisible = visible; };
      vm.runInNewContext([
        "discardFullDocumentReviewSnapshot", "runFullDocumentReview"
      ].map(functionSource).join("\n"), ctx);
      const pending = ctx.runFullDocumentReview();
      ctx.state.documentSessionId = "doc-B";
      ctx.switchMode(mode);
      ctx.state.writingJobId = submitted ? "new-writing-job" : "";
      ctx.setModelTaskBusy(true);
      ctx.state.status = "new task running";
      rejectExtraction(new Error("old extraction failed"));
      await pending;
      assert.strictEqual(ctx.state.fullDocumentReviewPreparing, false);
      assert.strictEqual(ctx.state.modelTaskBusy, true);
      assert.strictEqual(cancelVisible, true);
      assert.strictEqual(ctx.state.status, "new task running");
    });
  }
}

test("old full preparation failure preserves a newer regular review before extraction", async () => {
  const ctx = createBaseTestContext();
  const timers = [];
  let rejectExtraction;
  ctx.extractFullDocumentReviewBodyYielding = () => new Promise((resolve, reject) => { rejectExtraction = reject; });
  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "selection" });
  ctx.extractDocument = () => { throw new Error("new extraction failed"); };
  ctx.setTimeout = callback => { timers.push(callback); };
  vm.runInNewContext([
    "discardFullDocumentReviewSnapshot", "runFullDocumentReview", "runDocumentReview"
  ].map(functionSource).join("\n"), ctx);
  const pending = ctx.runFullDocumentReview();
  ctx.state.documentSessionId = "doc-B";
  ctx.switchMode("documentReview");
  ctx.runDocumentReview();
  assert.strictEqual(timers.length, 1);
  const status = ctx.state.status;
  rejectExtraction(new Error("old extraction failed"));
  await pending;
  assert.strictEqual(ctx.state.fullDocumentReviewPreparing, false);
  assert.strictEqual(ctx.state.modelTaskBusy, true);
  assert.strictEqual(ctx.state.status, status);
  ctx.runDocumentReview();
  assert.strictEqual(timers.length, 1, "rapid clicks cannot schedule duplicate extractions");
  timers[0]();
  assert.strictEqual(ctx.state.documentReviewPreparing, false);
  assert.strictEqual(ctx.state.modelTaskBusy, false);
});

test("snapshot discard cannot clear a regular review started while cleanup was pending", async () => {
  const ctx = createBaseTestContext();
  const timers = [];
  let finishDiscard;
  ctx.extractFullDocumentReviewBodyYielding = () => Promise.reject(new Error("old extraction failed"));
  ctx.discardFullDocumentReviewSnapshot = () => new Promise(resolve => { finishDiscard = resolve; });
  ctx.resolveSelectionScope = () => ({ ok: true, selectionMode: "selection" });
  ctx.setTimeout = callback => { timers.push(callback); };
  vm.runInNewContext([
    "runFullDocumentReview", "runDocumentReview"
  ].map(functionSource).join("\n"), ctx);
  const pending = ctx.runFullDocumentReview();
  await new Promise(resolve => setImmediate(resolve));
  ctx.runDocumentReview();
  const status = ctx.state.status;
  finishDiscard();
  await pending;
  assert.strictEqual(ctx.state.modelTaskBusy, true);
  assert.strictEqual(ctx.state.status, status);
  ctx.runDocumentReview();
  assert.strictEqual(timers.length, 1);
});

test('running document review keeps a stop action available', () => {
  const ctx = createBaseTestContext();
  vm.runInNewContext(['setDocumentReviewCancelVisible','renderDocumentReviewJobProgress'].map(functionSource).join('\n'), ctx);
  ctx.renderDocumentReviewJobProgress({status:'running',canCancel:true}, 'review-running');
  assert.strictEqual(ctx.byId('btn-cancel-document-review-job').hidden, false);
  assert.strictEqual(ctx.byId('btn-cancel-document-review-job').disabled, false);
});

test('document review cancellation waits for the backend terminal acknowledgment', async () => {
  const ctx = createBaseTestContext();
  ctx.state.documentReviewJobId = 'review-cancelling';
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, 'wps', 'word.document_review', ctx.state.documentSessionId, 'review-cancelling');
  ctx.request = () => Promise.resolve({data:{jobId:'review-cancelling',status:'running',cancelRequested:true}});
  vm.runInNewContext(functionSource('cancelQueuedDocumentReviewJob'), ctx);
  ctx.cancelQueuedDocumentReviewJob();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(ctx.state.documentReviewJobId, 'review-cancelling');
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, 'wps', 'word.document_review', ctx.state.documentSessionId), true);
  assert.ok(!String(ctx.state.status).includes('已取消'));
});

test('document review handles a plain missing-task response as terminal and permits resubmission', async () => {
  const ctx = createBaseTestContext();
  Object.assign(ctx, {DOCUMENT_REVIEW_POLL_MAX_ERRORS:240,DOCUMENT_REVIEW_POLL_MAX_WAIT_MS:3600000,
    DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS:15000,DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS:30000,
    scheduleDocumentReviewPoll:()=>{}});
  ctx.state.documentReviewJobId = 'missing-review';
  ctx.state.modelTaskBusy = true;
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, 'wps', 'word.document_review', ctx.state.documentSessionId, 'missing-review');
  ctx.request = () => Promise.reject(Object.assign(Error('HTTP 404'), {httpStatus:404}));
  vm.runInNewContext(functionSource('isFatalDocumentReviewPollError'), ctx);
  ctx.pollDocumentReviewJob('missing-review', () => {}, true, ctx.state.documentSessionId);
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(ctx.state.documentReviewJobId, '');
  assert.strictEqual(ctx.state.modelTaskBusy, false);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, 'wps', 'word.document_review', ctx.state.documentSessionId), false);
});

for (const full of [false,true]) {
  test((full ? 'full' : 'regular') + ' document review pauses repeated disconnections without losing the original job', async () => {
    const ctx = createBaseTestContext();
    const scheduled=[];
    const jobField=full ? 'fullDocumentReviewJobId' : 'documentReviewJobId';
    ctx.state[jobField]='offline-review';
    ctx.state.documentReviewPollErrorCount=0;
    ctx.state.fullDocumentReviewPollErrorCount=0;
    Object.assign(ctx, {DOCUMENT_REVIEW_POLL_MAX_ERRORS:240,DOCUMENT_REVIEW_POLL_MAX_WAIT_MS:3600000,
      DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS:15000,DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS:30000,
      isFatalDocumentReviewPollError:()=>false,isFullDocumentReviewPermanentPollError:()=>false,
      scheduleDocumentReviewPoll:()=>scheduled.push('poll'),setTimeout:()=>scheduled.push('poll'),
      setInterruptedRetryVisible:(visible,label)=>{ctx.retryVisible=visible;ctx.retryLabel=label;},
      request:()=>Promise.reject(Error('Adapter无法连接'))});
    for(let i=0;i<3;i+=1) {
      if(full) ctx.pollFullDocumentReviewJob('offline-review',ctx.state.documentSessionId);
      else ctx.pollDocumentReviewJob('offline-review',()=>{},true,ctx.state.documentSessionId);
      await new Promise(resolve=>setImmediate(resolve));
    }
    assert.strictEqual(scheduled.length,2);
    assert.strictEqual(ctx.state[jobField],'offline-review');
    assert.strictEqual(ctx.retryVisible,true);
    assert.strictEqual(ctx.retryLabel,'继续查询');
  });
}

for (const full of [false, true]) {
  const taskType = full ? 'word.document_review.full' : 'word.document_review';
  const jobField = full ? 'fullDocumentReviewJobId' : 'documentReviewJobId';
  const poll = full ? 'pollFullDocumentReviewJob' : 'pollDocumentReviewJob';
  const cancel = full ? 'cancelFullDocumentReviewJob' : 'cancelQueuedDocumentReviewJob';
  const resume = full ? 'resumeFullDocumentReviewActiveJob' : 'resumeDocumentReviewActiveJob';

  test(taskType + ' stopping a paused running job queries its original ID through cancellation', async () => {
    const ctx = createBaseTestContext();
    const calls = [];
    const timers = [];
    ctx.state[jobField] = 'paused-review';
    ctx.state.modelTaskBusy = true;
    ctx.retryVisible = true;
    ctx.setInterruptedRetryVisible = visible => { ctx.retryVisible = visible; };
    ctx.setActiveReviewJobRecord(taskType, 'doc-session-1', { jobId: 'paused-review', pollPaused: true });
    helpers.claimTaskSlot(ctx.state.activeTaskSlots, 'wps', taskType, 'doc-session-1', 'paused-review');
    ctx.request = (url, body, options = {}) => {
      calls.push([url, options.method || 'GET']);
      return Promise.resolve({ data: { jobId: 'paused-review', status: calls.length < 3 ? 'running' : 'cancelled', cancelRequested: true } });
    };
    ctx.setTimeout = callback => { timers.push(callback); };
    vm.runInNewContext([cancel, 'finishCancelledDocumentReview', 'scheduleDocumentReviewPoll'].map(functionSource).join('\n'), ctx);
    ctx[cancel]();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepStrictEqual(calls.map(call => call[1]), ['DELETE', 'GET']);
    assert.strictEqual(ctx.state[jobField], 'paused-review');
    assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, 'wps', taskType, 'doc-session-1'), true);
    assert.strictEqual(timers.length, 1);
    timers.shift()();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepStrictEqual(calls.map(call => call[1]), ['DELETE', 'GET', 'GET']);
    assert.ok(calls.every(call => call[0].includes('/paused-review')));
    assert.strictEqual(ctx.state[jobField], '');
    assert.strictEqual(ctx.retryVisible, false);
    assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, 'wps', taskType, 'doc-session-1'), false);
  });

  test(taskType + ' returning to a paused task restores explicit query without submitting or polling', () => {
    const ctx = createBaseTestContext();
    const record = { jobId: 'paused-review', taskType, documentSessionId: 'doc-session-1', pollPaused: true };
    ctx.setActiveReviewJobRecord(taskType, 'doc-session-1', record);
    if (full) ctx.saveFullDocumentReviewActiveJob('paused-review', 'doc-session-1');
    else ctx.saveDocumentReviewActiveJob(record);
    ctx.state[jobField] = '';
    const calls = [];
    ctx.request = (...args) => { calls.push(args); return new Promise(() => {}); };
    ctx.setInterruptedRetryVisible = (visible, label) => { ctx.retry = [visible, label]; };
    assert.strictEqual(ctx[resume](), true);
    assert.strictEqual(ctx.state[jobField], 'paused-review');
    assert.deepStrictEqual(ctx.retry, [true, '继续查询']);
    assert.strictEqual(calls.length, 0);
  });

  for (const otherView of ['document', 'mode']) {
    test(taskType + ' background pause preserves another ' + otherView + ' view', async () => {
      const ctx = createBaseTestContext();
      ctx.state[jobField] = 'background-review';
      ctx.state[full ? 'fullDocumentReviewPollErrorCount' : 'documentReviewPollErrorCount'] = 2;
      ctx.setActiveReviewJobRecord(taskType, 'doc-session-1', { jobId: 'background-review' });
      if (otherView === 'document') ctx.state.documentSessionId = 'doc-session-2';
      else ctx.state.currentMode = 'smartWrite';
      const changes = [];
      ctx.request = () => Promise.reject(Error('offline'));
      ctx.isFatalDocumentReviewPollError = () => false;
      ctx.isFullDocumentReviewPermanentPollError = () => false;
      ctx.setInterruptedRetryVisible = () => changes.push('retry');
      ctx.setDocumentReviewCancelVisible = () => changes.push('cancel');
      ctx.setStatus = () => changes.push('status');
      if (full) ctx[poll]('background-review', 'doc-session-1');
      else ctx[poll]('background-review', () => {}, true, 'doc-session-1');
      await new Promise(resolve => setImmediate(resolve));
      assert.deepStrictEqual(changes, []);
      assert.strictEqual(ctx.getActiveReviewJobRecord(taskType, 'doc-session-1').pollPaused, true);
    });
  }
}

test('full review cancellation 404 releases the original slot for resubmission', async () => {
  const ctx = createBaseTestContext();
  ctx.state.fullDocumentReviewJobId = 'missing-full';
  ctx.state.modelTaskBusy = true;
  ctx.setActiveReviewJobRecord('word.document_review.full', 'doc-session-1', { jobId: 'missing-full', pollPaused: true });
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, 'wps', 'word.document_review.full', 'doc-session-1', 'missing-full');
  ctx.request = () => Promise.reject(Object.assign(Error('missing'), { httpStatus: 404 }));
  vm.runInNewContext(functionSource('cancelFullDocumentReviewJob'), ctx);
  ctx.cancelFullDocumentReviewJob();
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(ctx.state.fullDocumentReviewJobId, '');
  assert.strictEqual(ctx.state.modelTaskBusy, false);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, 'wps', 'word.document_review.full', 'doc-session-1'), false);
});
