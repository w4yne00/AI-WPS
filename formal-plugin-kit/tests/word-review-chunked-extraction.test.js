const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");
const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

test("helpers: runChunkedRange yields macrotasks based on time budget and reports progress", async () => {
  assert.strictEqual(typeof helpers.runChunkedRange, "function", "helpers.runChunkedRange must be defined");

  let virtualTime = 0;
  const originalPerformance = global.performance;
  global.performance = { now: () => virtualTime };

  let macrotaskYields = 0;
  const originalSetTimeout = global.setTimeout;
  global.setTimeout = (fn, delay) => {
    macrotaskYields += 1;
    process.nextTick(fn);
    return 1;
  };

  try {
    const processed = [];
    const progressReports = [];
    // 60 items, each advances clock by 5ms => total 300ms.
    // With 50ms budget, expect ~6 slices (at least 5 yields).
    await helpers.runChunkedRange(1, 60, (idx) => {
      processed.push(idx);
      virtualTime += 5;
    }, {
      budgetMs: 50,
      onProgress: (current, total) => {
        progressReports.push({ current, total });
      }
    });

    assert.strictEqual(processed.length, 60);
    assert.strictEqual(processed[0], 1);
    assert.strictEqual(processed[59], 60);
    assert.ok(macrotaskYields >= 5, `expected at least 5 macrotask yields, got ${macrotaskYields}`);
    assert.ok(progressReports.length >= 5, `expected progress reports on yields, got ${progressReports.length}`);
    assert.strictEqual(progressReports[progressReports.length - 1].current, 60);
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

test("helpers: runChunkedRange aborts immediately when checkCancelled throws", async () => {
  assert.strictEqual(typeof helpers.runChunkedRange, "function", "helpers.runChunkedRange must be defined");

  let virtualTime = 0;
  const originalPerformance = global.performance;
  global.performance = { now: () => virtualTime };

  const originalSetTimeout = global.setTimeout;
  global.setTimeout = (fn) => {
    process.nextTick(fn);
    return 1;
  };

  try {
    let cancelTriggered = false;
    const processed = [];

    await assert.rejects(
      helpers.runChunkedRange(1, 100, (idx) => {
        processed.push(idx);
        virtualTime += 10;
        if (idx === 15) {
          cancelTriggered = true;
        }
      }, {
        budgetMs: 50,
        checkCancelled: () => {
          if (cancelTriggered) {
            throw new Error("OPERATION_CANCELLED");
          }
        }
      }),
      /OPERATION_CANCELLED/
    );

    assert.ok(processed.length < 50, `processing should have stopped early, but processed ${processed.length}`);
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

test("taskpane: full document review extraction yields event loop and matches sync baseline", async () => {
  assert.ok(taskpaneSource.includes("extractFullDocumentReviewBodyYielding"), "taskpane must have extractFullDocumentReviewBodyYielding");

  // Create fake large document
  const paragraphs = [];
  for (let i = 1; i <= 80; i += 1) {
    paragraphs.push({
      Text: `这是第 ${i} 段正文内容，用于测试 Word 全篇审查长文档提取分片。`,
      Range: {
        Tables: { Count: 0 }
      },
      ParagraphFormat: {
        OutlineLevel: i % 10 === 1 ? 1 : 10
      },
      ListFormat: {
        ListString: i % 5 === 0 ? "1." : ""
      }
    });
  }

  const fakeDocument = {
    Name: "test-large-doc.docx",
    Paragraphs: paragraphs,
    Tables: [{
      Id: "table-1",
      Rows: [{
        Index: 1,
        Cells: [{
          Id: "cell-1",
          RowIndex: 1,
          ColumnIndex: 1,
          RowSpan: 1,
          ColumnSpan: 1,
          Text: "表格内容"
        }]
      }]
    }],
    EditSequence: "seq-1"
  };

  assert.strictEqual(typeof helpers.collectFullDocumentReviewParagraphsYielding, "function",
    "helpers must provide collectFullDocumentReviewParagraphsYielding");
  assert.strictEqual(typeof helpers.collectFullDocumentReviewTablesYielding, "function",
    "helpers must provide collectFullDocumentReviewTablesYielding");

  const syncParagraphs = helpers.collectFullDocumentReviewParagraphs(fakeDocument);
  const syncTables = helpers.collectFullDocumentReviewTables(fakeDocument);

  let virtualTime = 0;
  let macrotaskCount = 0;
  const originalPerformance = global.performance;
  global.performance = { now: () => virtualTime };

  const originalSetTimeout = global.setTimeout;
  global.setTimeout = (fn) => {
    macrotaskCount += 1;
    process.nextTick(fn);
    return 1;
  };

  try {
    const chunkedParagraphs = await helpers.collectFullDocumentReviewParagraphsYielding(fakeDocument, {
      budgetMs: 25,
      itemTimeAdvanceMs: 1,
      advanceTime: (ms) => { virtualTime += ms; }
    });
    const chunkedTables = await helpers.collectFullDocumentReviewTablesYielding(fakeDocument, {
      budgetMs: 25
    });

    assert.deepStrictEqual(chunkedParagraphs, syncParagraphs, "chunked paragraphs must be identical to sync paragraphs");
    assert.deepStrictEqual(chunkedTables, syncTables, "chunked tables must be identical to sync tables");
    assert.ok(macrotaskCount > 0, "chunked extraction must yield to event loop at least once");
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

test("taskpane: format review extraction yields event loop and matches sync baseline", async () => {
  assert.strictEqual(typeof helpers.collectParagraphsYielding, "function",
    "helpers must provide collectParagraphsYielding");
  assert.strictEqual(typeof helpers.collectDeterministicFormatReviewImagesYielding, "function",
    "helpers must provide collectDeterministicFormatReviewImagesYielding");

  const paragraphs = [];
  for (let i = 1; i <= 60; i += 1) {
    paragraphs.push({
      Text: `格式审查段落 ${i} 样式测试。`,
      Range: {
        Tables: { Count: 0 },
        Characters: [{ Text: "格式" }, { Text: "审查" }]
      },
      Font: {
        NameFarEast: "宋体",
        Size: 12,
        Bold: false,
        Italic: false
      },
      ParagraphFormat: {
        OutlineLevel: 10,
        Alignment: 0
      }
    });
  }

  const fakeDocument = {
    Name: "test-format-doc.docx",
    Paragraphs: paragraphs,
    Tables: [],
    InlineShapes: [{
      Id: "inline-1",
      Type: 3,
      AlternativeText: "图 1 说明",
      ParagraphIndex: 1
    }],
    Shapes: []
  };

  const extractionOptions = {
    avoidFallbackTextRead: true,
    excludeTableParagraphs: true,
    includeCharacterFormatSegments: true,
    maxFormatSegments: 20
  };

  const syncParagraphs = helpers.collectParagraphs(fakeDocument, extractionOptions);
  const syncImages = helpers.collectDeterministicFormatReviewImages(fakeDocument, syncParagraphs);

  let virtualTime = 0;
  let macrotaskCount = 0;
  const originalPerformance = global.performance;
  global.performance = { now: () => virtualTime };

  const originalSetTimeout = global.setTimeout;
  global.setTimeout = (fn) => {
    macrotaskCount += 1;
    process.nextTick(fn);
    return 1;
  };

  try {
    const chunkedParagraphs = await helpers.collectParagraphsYielding(fakeDocument, extractionOptions, {
      budgetMs: 25,
      itemTimeAdvanceMs: 1,
      advanceTime: (ms) => { virtualTime += ms; }
    });
    const chunkedImages = await helpers.collectDeterministicFormatReviewImagesYielding(fakeDocument, chunkedParagraphs, {
      budgetMs: 25
    });

    assert.deepStrictEqual(chunkedParagraphs, syncParagraphs, "chunked format paragraphs must match sync paragraphs");
    assert.deepStrictEqual(chunkedImages.facts, syncImages.facts, "chunked image facts must match sync images");
    assert.ok(macrotaskCount > 0, "format extraction must yield to event loop");
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

test("taskpane: full document review aborts and cleans up snapshot when cancelled during preparation", async () => {
  assert.ok(taskpaneSource.includes("cancelFullDocumentReviewPreparation"),
    "taskpane must define cancelFullDocumentReviewPreparation");
  assert.ok(taskpaneSource.includes("discardFullDocumentReviewSnapshot"),
    "taskpane must define discardFullDocumentReviewSnapshot to clean up uncommitted snapshot");

  let statusText = "";
  let deletedSnapshots = [];
  let jobSubmitted = false;

  const state = {
    fullDocumentReviewEnabled: true,
    fullDocumentReviewJobId: "",
    documentReviewJobId: "",
    fullDocumentReviewPreparing: false,
    fullDocumentReviewCancelRequested: false,
    documentSessionId: "doc-sess-1",
    documentDisplayName: "test.docx",
    technicalDocumentType: "auto",
    technicalReviewPrompt: "",
    activeTaskSlots: {}
  };

  const paragraphs = [];
  for (let i = 1; i <= 60; i += 1) {
    paragraphs.push({
      Text: `全文审查测试段落 ${i}`,
      Range: { Tables: { Count: 0 } }
    });
  }

  const fakeDoc = {
    Name: "test.docx",
    Paragraphs: paragraphs,
    Tables: [],
    InlineShapes: [],
    Shapes: []
  };

  let cancelFired = false;
  const context = {
    state,
    helpers: Object.assign({}, helpers, {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      getDocumentSessionId: () => "doc-sess-1",
      getDocumentDisplayName: () => "test.docx",
      readFullDocumentReviewEditSignal: () => "sig-1"
    }),
    getActiveDocument: () => fakeDoc,
    getDocumentName: () => "test.docx",
    getFullDocumentReviewReadiness: () => ({ fullDocumentReviewReady: true }),
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    byId: () => null,
    setActiveResultRecord: () => {},
    setActiveReviewJobRecord: () => {},
    renderFullDocumentReviewEntry: () => {},
    setModelTaskBusy: () => {},
    setPlainResult: () => {},
    setStatus: (msg) => { statusText = msg; },
    setResult: () => {},
    setTrace: () => {},
    setDocumentReviewCancelVisible: () => {},
    getWritingPolicyScene: () => "general",
    describeFetchError: (e) => (e && e.message) || String(e),
    releaseTaskSlotsForJob: () => {},
    clearFullDocumentReviewActiveJob: () => {},
    stopDocumentReviewWaitFeedback: () => {},
    setTimeout: (fn) => {
      if (!cancelFired) {
        cancelFired = true;
        fns.cancelFullDocumentReviewPreparation();
      }
      return process.nextTick(fn);
    },
    request: async (url, payload, options) => {
      if (url === "/word/document-review/full/snapshots") {
        return { data: { sessionId: "snap-full-1", uploadToken: "tok-1" } };
      }
      if (url.startsWith("/word/document-review/full/snapshots/") && options && options.method === "DELETE") {
        deletedSnapshots.push(url);
        return { data: { status: "deleted" } };
      }
      if (url === "/word/document-review/full/jobs") {
        jobSubmitted = true;
        return { data: { jobId: "job-full-1" } };
      }
      return { data: {} };
    }
  };

  function functionSource(name) {
    const start = taskpaneSource.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `missing function ${name}`);
    const next = taskpaneSource.indexOf("\n  function ", start + 1);
    return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
  }

  function loadFunctions(names, ctx) {
    const declarations = names.map(functionSource).join("\n");
    const exports = names.map((name) => `${name}: ${name}`).join(",");
    return vm.runInNewContext(
      `(function () { ${declarations}; return {${exports}}; })()`,
      ctx
    );
  }

  const fns = loadFunctions([
    "ensureFullDocumentReviewPreparation",
    "extractFullDocumentReviewBodyYielding",
    "uploadFullDocumentReviewBatches",
    "discardFullDocumentReviewSnapshot",
    "cancelFullDocumentReviewPreparation",
    "cleanupFullDocumentReviewTerminal",
    "runFullDocumentReview"
  ], context);

  await fns.runFullDocumentReview();

  assert.strictEqual(state.fullDocumentReviewPreparing, false, "preparing must be false after abort");
  assert.strictEqual(jobSubmitted, false, "model job must never be submitted after cancel");
  assert.ok(statusText.includes("已取消全篇审查准备"), `statusText must reflect cancel: ${statusText}`);
});

test("taskpane: format review preparation can be cancelled, cleans up snapshot session and never calls model", async () => {
  assert.ok(taskpaneSource.includes("cancelDeterministicFormatReviewPreparation"),
    "taskpane must define cancelDeterministicFormatReviewPreparation");
  assert.ok(taskpaneSource.includes("deterministicFormatReviewPreparing"),
    "taskpane must track deterministicFormatReviewPreparing");
  assert.ok(taskpaneSource.includes("deterministicFormatReviewCancelRequested"),
    "taskpane must track deterministicFormatReviewCancelRequested");
  assert.ok(taskpaneSource.includes("extractDeterministicFormatReviewSnapshotYielding"),
    "taskpane must use extractDeterministicFormatReviewSnapshotYielding");

  let statusText = "";
  let deletedSnapshots = [];
  let jobSubmitted = false;

  const state = {
    deterministicFormatReviewEnabled: true,
    deterministicFormatReviewJobId: "",
    deterministicFormatReviewPreparing: false,
    deterministicFormatReviewCancelRequested: false,
    documentSessionId: "doc-session-fmt",
    documentDisplayName: "格式.docx",
    activeTaskSlots: {}
  };

  const paragraphs = [];
  for (let i = 1; i <= 60; i += 1) {
    paragraphs.push({
      Text: `格式审查段落 ${i} 样式测试。`,
      Range: {
        Tables: { Count: 0 },
        Characters: [{ Text: "格式" }, { Text: "审查" }]
      },
      Font: { NameFarEast: "宋体", Size: 12, Bold: false, Italic: false },
      ParagraphFormat: { OutlineLevel: 10, Alignment: 0 }
    });
  }

  const fakeDoc = {
    Name: "格式.docx",
    Paragraphs: paragraphs,
    Tables: [],
    InlineShapes: [{
      Id: "inline-1",
      Type: 3,
      AlternativeText: "图 1 说明",
      ParagraphIndex: 1
    }],
    Shapes: []
  };

  let cancelFired = false;
  const context = {
    state,
    helpers: Object.assign({}, helpers, {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      getDocumentSessionId: () => "doc-session-fmt",
      getDocumentDisplayName: () => "格式.docx",
      readFullDocumentReviewEditSignal: () => "sig-fmt-1"
    }),
    getActiveDocument: () => fakeDoc,
    getDocumentName: () => "格式.docx",
    getSelectionText: () => "",
    getSelectionSources: () => [],
    truncateText: (t) => t,
    collectHeadings: () => [],
    collectPageSetup: () => ({}),
    readValue: (target, key) => (target ? target[key] : undefined),
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    resolveSelectionScope: () => ({ ok: true, selectionMode: "document" }),
    byId: () => null,
    setActiveResultRecord: () => {},
    setActiveReviewJobRecord: () => {},
    clearDeterministicFormatReviewPresentation: () => {},
    clearDeterministicFormatReviewActiveJob: () => {},
    cleanupDeterministicFormatReviewTerminal: () => {},
    setModelTaskBusy: () => {},
    setPlainResult: () => {},
    setResult: () => {},
    setStatus: (msg) => { statusText = msg; },
    setTrace: () => {},
    setDocumentReviewCancelVisible: () => {},
    describeFetchError: (e) => (e && e.message) || String(e),
    DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS: 30000,
    DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS: {
      avoidFallbackTextRead: true,
      excludeTableParagraphs: true,
      includeCharacterFormatSegments: true,
      maxFormatSegments: 20
    },
    setTimeout: (fn) => {
      if (!cancelFired) {
        cancelFired = true;
        fns.cancelDeterministicFormatReviewPreparation();
      }
      return process.nextTick(fn);
    },
    request: async (url, payload, options) => {
      if (url === "/word/format-review/snapshots") {
        return { data: { snapshotId: "snap-fmt-1", uploadToken: "tok-fmt-1" } };
      }
      if (url.startsWith("/word/format-review/snapshots/") && options && options.method === "DELETE") {
        deletedSnapshots.push(url);
        return { data: { status: "deleted" } };
      }
      if (url === "/word/format-review/jobs") {
        jobSubmitted = true;
        return { data: { jobId: "job-fmt-1" } };
      }
      return { data: {} };
    }
  };

  function functionSource(name) {
    const start = taskpaneSource.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `missing function ${name}`);
    const next = taskpaneSource.indexOf("\n  function ", start + 1);
    return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
  }

  function loadFunctions(names, ctx) {
    const declarations = names.map(functionSource).join("\n");
    const exports = names.map((name) => `${name}: ${name}`).join(",");
    return vm.runInNewContext(
      `(function () { ${declarations}; return {${exports}}; })()`,
      ctx
    );
  }

  const fns = loadFunctions([
    "extractDocument",
    "extractDocumentYielding",
    "collectDeterministicFormatReviewImages",
    "extractDeterministicFormatReviewSnapshot",
    "extractDeterministicFormatReviewSnapshotYielding",
    "ensureDeterministicFormatReviewPreparation",
    "uploadDeterministicFormatReviewBatches",
    "exportDeterministicFormatReviewImageGroups",
    "discardDeterministicFormatReviewSnapshot",
    "cancelDeterministicFormatReviewPreparation",
    "runDeterministicFormatReview"
  ], context);

  await fns.runDeterministicFormatReview();

  assert.strictEqual(state.deterministicFormatReviewPreparing, false, "preparing must be false after abort");
  assert.strictEqual(jobSubmitted, false, "model job must never be submitted after cancel");
  assert.ok(statusText.includes("已取消格式审查准备"), `statusText must reflect cancel: ${statusText}`);
});

test("contract parity: deterministic format review 4 cross-runtime hashes match sync baseline", async () => {
  const paragraphs = [];
  for (let i = 1; i <= 40; i += 1) {
    paragraphs.push({
      Text: `格式审查段落 ${i} 内容与段落格式校验。`,
      Range: {
        Tables: { Count: 0 },
        Characters: [{ Text: "格式" }, { Text: "审查" }, { Text: "段落" }]
      },
      Font: {
        NameFarEast: i % 2 === 0 ? "宋体" : "黑体",
        Size: i === 1 ? 16 : 12,
        Bold: i === 1,
        Italic: false
      },
      ParagraphFormat: {
        OutlineLevel: i === 1 ? 1 : 10,
        Alignment: 0
      }
    });
  }

  const fakeDoc = {
    Name: "format-parity-test.docx",
    Paragraphs: paragraphs,
    Tables: [{
      Rows: [{
        Index: 1,
        Cells: [{
          Id: "fmt-cell-1",
          RowIndex: 1,
          ColumnIndex: 1,
          RowSpan: 1,
          ColumnSpan: 1,
          Text: "表格格式测试"
        }]
      }]
    }],
    InlineShapes: [{
      Id: "inline-img-1",
      Type: 3,
      AlternativeText: "图 1 架构图",
      ParagraphIndex: 2
    }],
    Shapes: []
  };

  const context = {
    getActiveDocument: () => fakeDoc,
    getDocumentName: () => "format-parity-test.docx",
    getSelectionText: () => "",
    getSelectionSources: () => [],
    truncateText: (t) => t,
    collectHeadings: () => [{ level: 1, text: "格式审查段落 1 内容与段落格式校验。" }],
    collectPageSetup: () => ({ orientation: "portrait" }),
    readValue: (target, key) => (target ? target[key] : undefined),
    helpers: helpers,
    state: {
      selectedTemplateId: "tpl-standard",
      userInstruction: "",
      rewriteStyle: "",
      focusPoint: "",
      lengthMode: "normal",
      technicalDocumentType: "auto",
      technicalReviewPrompt: "",
      deterministicFormatReviewImageObjects: {}
    },
    DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS: {
      avoidFallbackTextRead: true,
      excludeTableParagraphs: true,
      includeCharacterFormatSegments: true,
      maxFormatSegments: 20
    }
  };

  function functionSource(name) {
    const start = taskpaneSource.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `missing function ${name}`);
    const next = taskpaneSource.indexOf("\n  function ", start + 1);
    return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
  }

  function loadFunctions(names, ctx) {
    const declarations = names.map(functionSource).join("\n");
    const exports = names.map((name) => `${name}: ${name}`).join(",");
    return vm.runInNewContext(
      `(function () { ${declarations}; return {${exports}}; })()`,
      ctx
    );
  }

  const fns = loadFunctions([
    "collectParagraphs",
    "extractDocument",
    "extractDocumentYielding",
    "collectDeterministicFormatReviewImages",
    "extractDeterministicFormatReviewSnapshot",
    "extractDeterministicFormatReviewSnapshotYielding",
    "ensureDeterministicFormatReviewPreparation"
  ], context);

  const scope = { selectionMode: "document" };
  const syncSnapshot = fns.extractDeterministicFormatReviewSnapshot(scope);
  const yieldSnapshot = await fns.extractDeterministicFormatReviewSnapshotYielding(scope);

  // 验证四项核心跨运行时哈希与字符数严格一致
  assert.strictEqual(yieldSnapshot.contentSha256, syncSnapshot.contentSha256, "contentSha256 must match exactly");
  assert.strictEqual(yieldSnapshot.structureSha256, syncSnapshot.structureSha256, "structureSha256 must match exactly");
  assert.strictEqual(yieldSnapshot.formatSha256, syncSnapshot.formatSha256, "formatSha256 must match exactly");
  assert.strictEqual(yieldSnapshot.reviewCharacterCount, syncSnapshot.reviewCharacterCount, "reviewCharacterCount must match exactly");
  assert.strictEqual(yieldSnapshot.blocks.length, syncSnapshot.blocks.length, "block count must match exactly");
  assert.deepStrictEqual(yieldSnapshot.coverage, syncSnapshot.coverage, "coverage must match exactly");
});

test("taskpane: document edit during format review preparation aborts, cleans up snapshot and never calls model", async () => {
  let statusText = "";
  let deletedSnapshots = [];
  let jobSubmitted = false;
  let currentEditSignal = "sig-v1";

  const state = {
    deterministicFormatReviewEnabled: true,
    deterministicFormatReviewJobId: "",
    deterministicFormatReviewPreparing: false,
    deterministicFormatReviewCancelRequested: false,
    documentSessionId: "doc-session-fmt",
    documentDisplayName: "格式.docx",
    activeTaskSlots: {}
  };

  const paragraphs = [];
  for (let i = 1; i <= 30; i += 1) {
    paragraphs.push({
      Text: `格式审查段落 ${i}`,
      Range: { Tables: { Count: 0 } },
      Font: { NameFarEast: "宋体", Size: 12, Bold: false, Italic: false },
      ParagraphFormat: { OutlineLevel: 10, Alignment: 0 }
    });
  }

  const fakeDoc = {
    Name: "格式.docx",
    Paragraphs: paragraphs,
    Tables: [],
    InlineShapes: [],
    Shapes: []
  };

  const context = {
    state,
    helpers: Object.assign({}, helpers, {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      getDocumentSessionId: () => "doc-session-fmt",
      getDocumentDisplayName: () => "格式.docx",
      readFullDocumentReviewEditSignal: () => currentEditSignal
    }),
    getActiveDocument: () => fakeDoc,
    getDocumentName: () => "格式.docx",
    getSelectionText: () => "",
    getSelectionSources: () => [],
    truncateText: (t) => t,
    collectHeadings: () => [],
    collectPageSetup: () => ({}),
    readValue: (target, key) => (target ? target[key] : undefined),
    validateActiveDirectTaskSelection: () => ({ valid: true }),
    resolveSelectionScope: () => ({ ok: true, selectionMode: "document" }),
    byId: () => null,
    setActiveResultRecord: () => {},
    setActiveReviewJobRecord: () => {},
    clearDeterministicFormatReviewPresentation: () => {},
    clearDeterministicFormatReviewActiveJob: () => {},
    cleanupDeterministicFormatReviewTerminal: () => {},
    setModelTaskBusy: () => {},
    setPlainResult: () => {},
    setResult: () => {},
    setStatus: (msg) => { statusText = msg; },
    setTrace: () => {},
    setDocumentReviewCancelVisible: () => {},
    describeFetchError: (e) => (e && e.message) || String(e),
    DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS: 30000,
    DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS: {
      avoidFallbackTextRead: true,
      excludeTableParagraphs: true,
      includeCharacterFormatSegments: true,
      maxFormatSegments: 20
    },
    setTimeout: (fn) => process.nextTick(fn),
    request: async (url, payload, options) => {
      if (url === "/word/format-review/snapshots") {
        currentEditSignal = "sig-v2-edited";
        return { data: { snapshotId: "snap-fmt-edited", uploadToken: "tok-fmt-1" } };
      }
      if (url.startsWith("/word/format-review/snapshots/") && options && options.method === "DELETE") {
        deletedSnapshots.push(url);
        return { data: { status: "deleted" } };
      }
      if (url === "/word/format-review/jobs") {
        jobSubmitted = true;
        return { data: { jobId: "job-fmt-edited" } };
      }
      return { data: {} };
    }
  };

  function functionSource(name) {
    const start = taskpaneSource.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `missing function ${name}`);
    const next = taskpaneSource.indexOf("\n  function ", start + 1);
    return taskpaneSource.slice(start, next >= 0 ? next : taskpaneSource.length);
  }

  function loadFunctions(names, ctx) {
    const declarations = names.map(functionSource).join("\n");
    const exports = names.map((name) => `${name}: ${name}`).join(",");
    return vm.runInNewContext(
      `(function () { ${declarations}; return {${exports}}; })()`,
      ctx
    );
  }

  const fns = loadFunctions([
    "collectParagraphs",
    "extractDocument",
    "extractDocumentYielding",
    "collectDeterministicFormatReviewImages",
    "extractDeterministicFormatReviewSnapshot",
    "extractDeterministicFormatReviewSnapshotYielding",
    "ensureDeterministicFormatReviewPreparation",
    "uploadDeterministicFormatReviewBatches",
    "exportDeterministicFormatReviewImageGroups",
    "discardDeterministicFormatReviewSnapshot",
    "cancelDeterministicFormatReviewPreparation",
    "runDeterministicFormatReview"
  ], context);

  await fns.runDeterministicFormatReview();

  assert.strictEqual(state.deterministicFormatReviewPreparing, false, "preparing must be reset");
  assert.strictEqual(jobSubmitted, false, "model job must never be submitted after edit abort");
  assert.ok(deletedSnapshots.length > 0, "uncommitted snapshot must be deleted on edit abort");
  assert.ok(statusText.includes("检测到文档编辑"), `statusText must reflect edit: ${statusText}`);
});


