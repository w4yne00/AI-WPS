const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { wordRoot: root } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = source.indexOf("\n  function ", start + 1);
  return source.slice(start, next >= 0 ? next : source.length);
}

function loadFunctions(names, context) {
  const declarations = names.map(functionSource).join("\n");
  const exports = names.map((name) => `${name}: ${name}`).join(",");
  return vm.runInNewContext(
    `(function () { ${declarations}; return {${exports}}; })()`,
    context
  );
}

// 静态源码包含关键指标标记
[
  "beginTaskPerformance",
  "recordTaskFirstRender",
  "clickToFeedbackMs",
  "clickToAdapterAcceptedMs",
  "completionToFirstRenderMs",
  "lastTaskPerformance"
].forEach((marker) => assert.ok(source.includes(marker), `missing ${marker}`));

async function testDocumentReviewPerformanceLifecycle() {
  let virtualTime = 1000;
  const pendingFrames = [];
  const state = {
    documentSessionId: "doc-session-1",
    documentDisplayName: "测试.docx",
    activeTaskSlots: {},
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null,
    currentMode: "documentReview"
  };

  let capturedUrl = "";
  let capturedPayload = null;

  const context = {
    state,
    Date: { now: () => virtualTime },
    performance: { now: () => virtualTime },
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot() {},
      getDocumentSessionId: () => "doc-session-1",
      getDocumentDisplayName: () => "测试.docx"
    },
    getActiveDocument: () => ({}),
    byId: () => null,
    resolveSelectionScope: () => ({ ok: true, selectionMode: "document" }),
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    resetSmartWritePreviewState() {},
    resetDocumentReviewState() {},
    clearDocumentReviewActiveJob() {},
    setActiveResultRecord() {},
    setModelTaskBusy() {},
    setStatus() {},
    setPlainResult() {},
    setApplyEnabled() {},
    setResult() {},
    setTrace(traceId) { state.traceId = traceId; },
    setDocumentReviewJobId(jobId) { state.documentReviewJobId = jobId; },
    buildDocumentReviewClientJobId: () => "doc-review-client-1",
    extractDocument: () => ({ plain_text: "测试文本", selectionMode: "document" }),
    getWritingPolicyScene: () => "auto",
    startDocumentReviewWaitFeedback: () => () => {},
    stopDocumentReviewWaitFeedback() {},
    cleanupDocumentReviewTerminal() {},
    renderDocumentReviewJobProgress() {},
    pollDocumentReviewJob() {},
    renderDocumentReviewResult: () => true,
    describeDocumentReviewError: (e) => e.message,
    isFatalDocumentReviewPollError: () => false,
    saveDocumentReviewActiveJob() {},
    setActiveReviewJobRecord() {},
    DOCUMENT_REVIEW_EXTRACTION_OPTIONS: {},
    DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS: 30000,
    setTimeout: (fn, delay) => {
      // Execute immediately or simulate next tick
      fn();
      return 1;
    },
    clearTimeout() {},
    requestAnimationFrame: (cb) => pendingFrames.push(cb),
    request: (url, payload) => {
      capturedUrl = url;
      capturedPayload = payload;
      virtualTime += 120; // 模拟网络延迟 120ms
      return Promise.resolve({
        traceId: "trace-doc-review-1",
        data: {
          jobId: "doc-review-client-1",
          status: "completed",
          result: { summary: "完成", issues: [] }
        }
      });
    }
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "selectTaskPerformance",
    "recordTaskFirstRender",
    "completeDocumentReview",
    "runDocumentReview"
  ], context);

  fns.runDocumentReview();
  await Promise.resolve();
  await Promise.resolve();

  const perf = fns.getTaskPerformance("doc-review-client-1", "trace-doc-review-1");
  assert.ok(perf, "performance record should exist for document_review");
  assert.strictEqual(perf.taskType, "word.document_review");
  assert.strictEqual(typeof perf.clickToFeedbackMs, "number");
  assert.strictEqual(typeof perf.clickToAdapterAcceptedMs, "number");
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 120);

  // 触发 requestAnimationFrame 提交首渲染耗时
  assert.strictEqual(perf.completionToFirstRenderMs, null);
  assert.strictEqual(pendingFrames.length, 1);
  virtualTime += 35;
  pendingFrames.shift()();
  assert.strictEqual(perf.completionToFirstRenderMs, 35);
  assert.strictEqual(state.lastTaskPerformance, perf);
}

async function testFullDocumentReviewPerformanceLifecycle() {
  let virtualTime = 2000;
  const pendingFrames = [];
  const state = {
    documentSessionId: "doc-session-full",
    documentDisplayName: "全篇.docx",
    fullDocumentReviewEnabled: true,
    technicalDocumentType: "technical_solution",
    technicalReviewPrompt: "",
    activeTaskSlots: {},
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null,
    currentMode: "documentReview"
  };

  const context = {
    state,
    Date: { now: () => virtualTime },
    performance: { now: () => virtualTime },
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot() {},
      getDocumentSessionId: () => "doc-session-full",
      getDocumentDisplayName: () => "全篇.docx"
    },
    getActiveDocument: () => ({}),
    byId: () => null,
    getFullDocumentReviewReadiness: () => ({ fullDocumentReviewReady: true }),
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    setActiveResultRecord() {},
    setModelTaskBusy() {},
    setDocumentReviewCancelVisible() {},
    renderFullDocumentReviewEntry() {},
    setPlainResult() {},
    setStatus() {},
    setResult() {},
    setTrace(traceId) { state.traceId = traceId; },
    getWritingPolicyScene: () => "auto",
    extractFullDocumentReviewBodyYielding: () => Promise.resolve({
      documentId: "doc-1",
      editSignal: 1,
      reviewCharacterCount: 100,
      contentSha256: "hash1",
      structureSha256: "struct1",
      blocks: [{}],
      tableCount: 0,
      cellCount: 0,
      batches: [{}]
    }),
    ensureFullDocumentReviewPreparation() {},
    uploadFullDocumentReviewBatches: () => Promise.resolve(),
    saveFullDocumentReviewActiveJob() {},
    setActiveReviewJobRecord() {},
    cleanupFullDocumentReviewTerminal() {},
    renderFullDocumentReviewReport: () => Promise.resolve(),
    describeFetchError: (e) => e.message,
    DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS: 30000,
    DOCUMENT_REVIEW_POLL_INTERVAL_MS: 1000,
    DOCUMENT_REVIEW_PHASE_TEXT: {},
    isFullDocumentReviewPermanentPollError: () => false,
    setTimeout: (fn) => { fn(); return 1; },
    clearTimeout() {},
    requestAnimationFrame: (cb) => pendingFrames.push(cb),
    request: (url, payload) => {
      if (url.includes("/snapshots") && !url.includes("/commit")) {
        return Promise.resolve({ data: { sessionId: "sess-1", uploadToken: "tok-1" } });
      }
      if (url.includes("/commit")) {
        return Promise.resolve({ data: { snapshotId: "snap-1", snapshotToken: "stok-1", capacity: {} } });
      }
      if (url === "/word/document-review/full/jobs") {
        virtualTime += 150; // accepted 耗时 150ms
        return Promise.resolve({
          traceId: "trace-full-1",
          data: { jobId: "job-full-1", status: "running" }
        });
      }
      if (url === "/word/document-review/full/jobs/job-full-1") {
        return Promise.resolve({
          traceId: "trace-full-1",
          data: { jobId: "job-full-1", status: "completed" }
        });
      }
      if (url.includes("/report")) {
        return Promise.resolve({
          data: { snapshot: {}, coverage: {}, enumerationStatus: "complete" }
        });
      }
      return Promise.resolve({ data: {} });
    }
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "selectTaskPerformance",
    "recordTaskFirstRender",
    "pollFullDocumentReviewJob",
    "runFullDocumentReview"
  ], context);

  await fns.runFullDocumentReview();
  for (let i = 0; i < 20; i++) {
    await Promise.resolve();
  }

  const perf = fns.getTaskPerformance("job-full-1", "trace-full-1");
  assert.ok(perf, "performance record should exist for full_document_review");
  assert.strictEqual(perf.taskType, "word.document_review.full");
  assert.strictEqual(typeof perf.clickToFeedbackMs, "number");
  assert.strictEqual(typeof perf.clickToAdapterAcceptedMs, "number");
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 150);

  // 首渲染耗时
  assert.strictEqual(perf.completionToFirstRenderMs, null);
  assert.strictEqual(pendingFrames.length, 1);
  virtualTime += 40;
  pendingFrames.shift()();
  assert.strictEqual(perf.completionToFirstRenderMs, 40);
  assert.strictEqual(state.lastTaskPerformance, perf);
}

async function testFormatReviewPerformanceLifecycle() {
  let virtualTime = 3000;
  const pendingFrames = [];
  const state = {
    documentSessionId: "doc-session-fmt",
    documentDisplayName: "格式.docx",
    deterministicFormatReviewEnabled: true,
    activeTaskSlots: {},
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null,
    currentMode: "formatReview"
  };

  const context = {
    state,
    Date: { now: () => virtualTime },
    performance: { now: () => virtualTime },
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot() {},
      getDocumentSessionId: () => "doc-session-fmt",
      getDocumentDisplayName: () => "格式.docx",
      buildDeterministicFormatReviewBatches: () => [{}]
    },
    getActiveDocument: () => ({}),
    byId: () => null,
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    resolveSelectionScope: () => ({ ok: true, selectionMode: "document" }),
    setActiveResultRecord() {},
    clearDeterministicFormatReviewPresentation() {},
    clearDeterministicFormatReviewActiveJob() {},
    setModelTaskBusy() {},
    setStatus() {},
    setPlainResult() {},
    setResult() {},
    setTrace(traceId) { state.traceId = traceId; },
    extractDeterministicFormatReviewSnapshot: () => ({
      documentId: "doc-fmt-1",
      selectionMode: "document",
      documentIdentity: { hostDocumentId: "host-1" },
      editSequence: "1",
      templateId: "tpl-1",
      formatSnapshotSchemaVersion: "word.format_review.snapshot.v2",
      formatFactSchemaVersion: "format_snapshot.v2",
      pageSetup: {},
      pageSetupFacts: {},
      scope: {},
      coverage: {},
      contentSha256: "h1",
      structureSha256: "s1",
      formatSha256: "f1",
      reviewCharacterCount: 50,
      blocks: [{}]
    }),
    ensureDeterministicFormatReviewPreparation() {},
    uploadDeterministicFormatReviewBatches: () => Promise.resolve(),
    exportDeterministicFormatReviewImageGroups: () => Promise.resolve(),
    saveDeterministicFormatReviewActiveJob() {},
    setActiveReviewJobRecord() {},
    setDocumentReviewCancelVisible() {},
    cleanupDeterministicFormatReviewTerminal() {},
    loadDeterministicFormatReviewReport: () => Promise.resolve(),
    describeFetchError: (e) => e.message,
    DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS: 30000,
    DETERMINISTIC_FORMAT_REVIEW_POLL_INTERVAL_MS: 1000,
    setTimeout: (fn) => { fn(); return 1; },
    clearTimeout() {},
    requestAnimationFrame: (cb) => pendingFrames.push(cb),
    request: (url, payload) => {
      if (url.includes("/snapshots") && !url.includes("/commit")) {
        return Promise.resolve({ data: { snapshotId: "snap-fmt-1", uploadToken: "tok-f1" } });
      }
      if (url.includes("/commit")) {
        return Promise.resolve({ data: { snapshotId: "snap-fmt-1", snapshotToken: "stok-f1" } });
      }
      if (url === "/word/format-review/jobs") {
        virtualTime += 90; // accepted 耗时 90ms
        return Promise.resolve({
          traceId: "trace-fmt-1",
          data: { jobId: "job-fmt-1", status: "running" }
        });
      }
      if (url === "/word/format-review/jobs/job-fmt-1") {
        return Promise.resolve({
          traceId: "trace-fmt-1",
          data: { jobId: "job-fmt-1", status: "completed" }
        });
      }
      return Promise.resolve({ data: {} });
    }
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "selectTaskPerformance",
    "recordTaskFirstRender",
    "pollDeterministicFormatReviewJob",
    "runDeterministicFormatReview"
  ], context);

  fns.runDeterministicFormatReview();
  for (let i = 0; i < 20; i++) {
    await Promise.resolve();
  }

  const perf = fns.getTaskPerformance("job-fmt-1", "trace-fmt-1");
  assert.ok(perf, "performance record should exist for format_review");
  assert.strictEqual(perf.taskType, "word.format_review.deterministic");
  assert.strictEqual(typeof perf.clickToFeedbackMs, "number");
  assert.strictEqual(typeof perf.clickToAdapterAcceptedMs, "number");
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 90);

  // 首渲染耗时
  assert.strictEqual(perf.completionToFirstRenderMs, null);
  assert.strictEqual(pendingFrames.length, 1);
  virtualTime += 25;
  pendingFrames.shift()();
  assert.strictEqual(perf.completionToFirstRenderMs, 25);
  assert.strictEqual(state.lastTaskPerformance, perf);
}

Promise.all([
  testDocumentReviewPerformanceLifecycle(),
  testFullDocumentReviewPerformanceLifecycle(),
  testFormatReviewPerformanceLifecycle()
]).then(() => {
  console.log("All Word review performance lifecycle tests passed");
}).catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
