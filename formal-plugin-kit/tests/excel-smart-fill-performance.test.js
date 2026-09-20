const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { etRoot: root } = require("./support/plugin-roots");
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

function loadFunctions(names, context) {
  const declarations = names.map(functionSource).join("\n");
  const exports = names.map((name) => `${name}: ${name}`).join(",");
  return vm.runInNewContext(
    `(function () { ${declarations}; return {${exports}}; })()`,
    context
  );
}

function buildMockRange(rowCount, columnCount, onCellAccess) {
  const cells = {};
  for (let r = 1; r <= rowCount; r++) {
    for (let c = 1; c <= columnCount; c++) {
      const isHeader = r === 1;
      const text = isHeader ? `列${c}` : `数据_${r}_${c}`;
      cells[`${r},${c}`] = {
        Row: r,
        Column: c,
        Address: `$${String.fromCharCode(64 + c)}$${r}`,
        Text: text,
        Value2: text,
        Formula: "",
        HasFormula: false,
        MergeCells: false,
        Locked: false,
        Hidden: false,
        EntireRow: { Hidden: false },
        EntireColumn: { Hidden: false }
      };
    }
  }

  return {
    Address: `$A$1:$${String.fromCharCode(64 + columnCount)}$${rowCount}`,
    Worksheet: { Name: "Sheet1" },
    Rows: { Count: rowCount },
    Columns: { Count: columnCount },
    Areas: { Count: 1 },
    Cells: {
      Item(row, col) {
        if (typeof onCellAccess === "function") {
          onCellAccess(row, col);
        }
        return cells[`${row},${col}`] || null;
      }
    }
  };
}

// 1. 静态检查：taskpane-helpers 导出 yielding 智能填写抽取函数
test("helpers: exports extractExcelSmartFillSourcePayloadYielding", () => {
  assert.strictEqual(
    typeof helpers.extractExcelSmartFillSourcePayloadYielding,
    "function",
    "helpers.extractExcelSmartFillSourcePayloadYielding must be a function"
  );
});

// 2. 分片抽取在时间预算耗尽后真正让出宏任务并递增上报进度
test("helpers: extractExcelSmartFillSourcePayloadYielding yields macrotasks and reports progress", async () => {
  let virtualTime = 0;
  const originalPerformance = global.performance;
  const originalSetTimeout = global.setTimeout;

  global.performance = { now: () => virtualTime };
  let macrotaskYields = 0;
  global.setTimeout = (fn, delay) => {
    macrotaskYields += 1;
    process.nextTick(fn);
    return 1;
  };

  try {
    const rowCount = 30;
    const colCount = 4;
    // 每次读取单元格时 advance 2ms => 每行 4 单元格 = 8ms
    // budgetMs 为 20ms => 预计每 3 行让出一次，30 行产生约 9-10 次让出
    const range = buildMockRange(rowCount, colCount, () => {
      virtualTime += 2;
    });

    const progressReports = [];
    const payload = await helpers.extractExcelSmartFillSourcePayloadYielding(range, {
      workbookId: "wb-test",
      budgetMs: 20,
      onProgress: (progress) => {
        progressReports.push({ ...progress });
      }
    });

    assert.ok(macrotaskYields >= 5, `expected at least 5 macrotask yields, got ${macrotaskYields}`);
    assert.strictEqual(payload.workbookId, "wb-test");
    assert.strictEqual(payload.scene, "excel");
    assert.strictEqual(payload.source.rows.length, 29); // 30 行扣除 1 行表头
    assert.strictEqual(payload.items.length, 29);
    assert.strictEqual(payload.source.headers.length, 4);

    // 进度单调递增验证
    assert.ok(progressReports.length >= 5, `expected progress reports on yields, got ${progressReports.length}`);
    for (let i = 1; i < progressReports.length; i++) {
      assert.ok(
        progressReports[i].processedRows >= progressReports[i - 1].processedRows,
        "processedRows must be monotonic"
      );
    }
    const lastProgress = progressReports[progressReports.length - 1];
    assert.strictEqual(lastProgress.processedRows, rowCount);
    assert.strictEqual(lastProgress.totalRows, rowCount);

    // 与同步提取严格等价
    const syncPayload = helpers.extractExcelSmartFillSourcePayload(range, { workbookId: "wb-test" });
    assert.strictEqual(payload.source.snapshotHash, syncPayload.source.snapshotHash);
    assert.deepStrictEqual(payload.source.headers, syncPayload.source.headers);
    assert.deepStrictEqual(payload.source.rows, syncPayload.source.rows);
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

test("helpers: wide smart-fill rows stay within the 50ms synchronous slice target", async () => {
  let virtualTime = 0;
  let sliceStartedAt = 0;
  const sliceDurations = [];
  const originalPerformance = global.performance;
  const originalSetTimeout = global.setTimeout;

  global.performance = { now: () => virtualTime };
  global.setTimeout = (fn) => {
    sliceDurations.push(virtualTime - sliceStartedAt);
    sliceStartedAt = virtualTime;
    process.nextTick(fn);
    return 1;
  };

  try {
    const range = buildMockRange(2, 50, () => {
      virtualTime += 2;
    });

    await helpers.extractExcelSmartFillSourcePayloadYielding(range, {
      workbookId: "wb-wide-row",
      budgetMs: 32
    });
    sliceDurations.push(virtualTime - sliceStartedAt);

    assert.ok(sliceDurations.length > 1, "wide rows must yield before the row is complete");
    assert.ok(
      Math.max(...sliceDurations) < 50,
      `maximum synchronous slice must stay below 50ms, got ${Math.max(...sliceDurations)}ms`
    );
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

// 3. 分片抽取安全检查：公式遮蔽、隐藏/合并单元格校验保持一致
test("helpers: extractExcelSmartFillSourcePayloadYielding masks formulas and validates merged/hidden", async () => {
  // 公式单元格遮蔽测试
  const formulaRange = buildMockRange(3, 2);
  const formulaCell = formulaRange.Cells.Item(2, 2);
  formulaCell.HasFormula = true;
  formulaCell.Formula = "=SUM(A1:A2)";
  formulaCell.Text = "100";

  const payload = await helpers.extractExcelSmartFillSourcePayloadYielding(formulaRange);
  assert.strictEqual(payload.source.rows[0][1], "", "Formula cell text must be masked to empty string");

  // 合并单元格测试
  const mergedRange = buildMockRange(3, 2);
  mergedRange.Cells.Item(2, 1).MergeCells = true;
  await assert.rejects(
    async () => helpers.extractExcelSmartFillSourcePayloadYielding(mergedRange),
    /来源不能包含合并单元格/
  );

  // 隐藏单元格测试
  const hiddenRange = buildMockRange(3, 2);
  hiddenRange.Cells.Item(2, 1).Hidden = true;
  await assert.rejects(
    async () => helpers.extractExcelSmartFillSourcePayloadYielding(hiddenRange),
    /来源不能包含隐藏行、列或单元格/
  );
});

// 4. 分片抽取支持检查取消标志并在中途抛出中止异常
test("helpers: extractExcelSmartFillSourcePayloadYielding aborts promptly when cancelled", async () => {
  let virtualTime = 0;
  const originalPerformance = global.performance;
  const originalSetTimeout = global.setTimeout;
  global.performance = { now: () => virtualTime };
  global.setTimeout = (fn) => {
    process.nextTick(fn);
    return 1;
  };

  try {
    let cancelRequested = false;
    let readCellCount = 0;
    const range = buildMockRange(50, 4, (row) => {
      virtualTime += 5;
      readCellCount += 1;
      if (row >= 10) {
        cancelRequested = true;
      }
    });

    await assert.rejects(
      async () => helpers.extractExcelSmartFillSourcePayloadYielding(range, {
        budgetMs: 20,
        checkCancelled: () => {
          if (cancelRequested) {
            const err = new Error("智能填写已取消。");
            err.name = "AbortError";
            throw err;
          }
        }
      }),
      (err) => err.name === "AbortError" || /智能填写已取消/.test(err.message)
    );

    // 证实未继续读取完所有 200 单元格
    assert.ok(readCellCount < 200, `expected aborted read count < 200, got ${readCellCount}`);
  } finally {
    global.performance = originalPerformance;
    global.setTimeout = originalSetTimeout;
  }
});

// 5. runExcelSmartFillAction 即时 UI 反馈：点击后先更新 busy、状态栏和结果卡，再读取 WPS 单元格
test("taskpane: runExcelSmartFillAction provides immediate UI feedback (<100ms) before reading cells", async () => {
  let virtualTime = 1000;
  const events = [];
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: id === "excel-smart-fill-instruction" ? "生成部门统计" : "",
        hidden: false,
        disabled: false,
        addEventListener: () => {}
      };
    }
    return elements[id];
  };

  const state = {
    currentMode: "excelSmartFill",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    excelTaskSessions: {},
    activeTaskSlots: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    smartFillInstruction: "",
    smartFillResult: null,
    smartFillCancelRequested: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

  const mockRange = buildMockRange(10, 3, () => {
    events.push({ type: "readCell", time: virtualTime });
  });

  const context = {
    state,
    byId,
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => { fn(); },
    getExcelTaskSession: (type) => {
      if (!state.excelTaskSessions[type]) {
        state.excelTaskSessions[type] = { jobId: "", pollStartedAt: 0, resumeExpected: false };
      }
      return state.excelTaskSessions[type];
    },
    buildExcelSmartFillClientJobId: () => "sf-client-job-1",
    isExcelTaskVisible: () => true,
    getEtApplication: () => ({}),
    getActiveWorkbook: () => ({}),
    getActiveSheet: () => ({ Name: "Sheet1" }),
    getSelectionRange: () => mockRange,
    readSmartFillWorkbookId: () => "wb-doc-1",
    readSmartFillSheetName: () => "Sheet1",
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      releaseTaskSlot: () => {},
      getDocumentSessionId: () => "doc-1",
      getDocumentDisplayName: () => "工作簿1.xlsx",
      extractExcelSmartFillSourcePayloadYielding: helpers.extractExcelSmartFillSourcePayloadYielding,
      requireExcelSmartFillInstruction: (t) => t
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setExcelTaskBusy: (busy) => {
      events.push({ type: "setExcelTaskBusy", busy, time: virtualTime });
    },
    setStatus: (msg) => {
      events.push({ type: "setStatus", msg, time: virtualTime });
    },
    setPlainResult: (msg) => {
      events.push({ type: "setPlainResult", msg, time: virtualTime });
    },
    setNodeTextIfChanged: () => {},
    setSmartFillInterruptedRetryVisible: () => {},
    setExcelSmartFillCancelVisible: (vis) => {
      events.push({ type: "setCancelVisible", vis, time: virtualTime });
    },
    saveCurrentSmartFillSessionState: () => {},
    saveExcelSmartFillActiveJob: () => {},
    clearExcelSmartFillActiveJob: () => {},
    summarizeSmartFillSource: () => "A1:C10",
    setScopeLine: () => {},
    startExcelSmartFillWaitFeedback: () => () => {},
    request: () => Promise.resolve({
      data: {
        jobId: "sf-client-job-1",
        traceId: "trace-sf-1",
        status: "completed",
        result: { schemaVersion: "excel.smart_fill.v2", items: [] }
      }
    }),
    setTrace: () => {},
    finalizeExcelSmartFillResult: () => {},
    safeText: (t) => t || "",
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 10000,
    EXCEL_SMART_FILL_EXTRACTION_OPTIONS: {
      maxItems: 500,
      maxSourceRows: 500,
      maxSourceColumns: 50,
      maxCellTextLength: 2000,
      maxTotalTextLength: 200000
    },
    pollExcelSmartFillJob: () => {},
    describeExcelSmartFillPollError: (e) => e.message,
    isFatalExcelSmartFillPollError: () => false
  };

  const fns = loadFunctions([
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "getTaskPerformance",
    "recordTaskFirstRender",
    "runExcelSmartFillAction"
  ], context);

  context.beginTaskPerformance = fns.beginTaskPerformance;
  context.bindTaskPerformanceTrace = fns.bindTaskPerformanceTrace;
  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelSmartFillAction();

  await new Promise((resolve) => setImmediate(resolve));

  // 验证在任何 cell 读取前，必须先产生 setStatus / setPlainResult / setExcelTaskBusy
  const firstReadIndex = events.findIndex((e) => e.type === "readCell");
  const firstFeedbackIndex = events.findIndex((e) => e.type === "setStatus" || e.type === "setPlainResult");
  const firstBusyIndex = events.findIndex((e) => e.type === "setExcelTaskBusy");

  assert.ok(firstFeedbackIndex >= 0, "must provide status/result feedback");
  assert.ok(firstBusyIndex >= 0, "must set busy state");
  if (firstReadIndex >= 0) {
    assert.ok(firstFeedbackIndex < firstReadIndex, "Feedback must occur BEFORE first cell read");
    assert.ok(firstBusyIndex < firstReadIndex, "Busy state must occur BEFORE first cell read");
  }
});

// 6. 准备与抽取期间取消：严禁向 Adapter 发起长任务，不产生新结果或历史，并保留既有预览
test("taskpane: runExcelSmartFillAction cancels during extraction without creating an active adapter job", async () => {
  let virtualTime = 1000;
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: id === "excel-smart-fill-instruction" ? "分析数据" : "",
        hidden: false,
        disabled: false,
        addEventListener: () => {}
      };
    }
    return elements[id];
  };

  let slotClaimed = false;
  let slotReleased = false;
  let adapterRequested = false;
  let activeJobSaved = false;
  const previousResult = {
    schemaVersion: "excel.smart_fill.v2",
    items: [{ itemId: "sf_previous", status: "completed", value: "既有预览" }]
  };

  const state = {
    currentMode: "excelSmartFill",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    excelTaskSessions: {},
    activeTaskSlots: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    smartFillInstruction: "",
    smartFillResult: previousResult,
    smartFillCancelRequested: false,
    smartFillExtractionInFlight: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

  // 模拟一个大选区，在抽取中途触发取消
  let currentStep = 0;
  const mockRange = buildMockRange(20, 3, () => {
    currentStep += 1;
    if (currentStep === 15) {
      state.smartFillCancelRequested = true;
    }
  });

  const context = {
    state,
    byId,
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => { fn(); },
    getExcelTaskSession: (type) => {
      if (!state.excelTaskSessions[type]) {
        state.excelTaskSessions[type] = { jobId: "", pollStartedAt: 0, resumeExpected: false };
      }
      return state.excelTaskSessions[type];
    },
    buildExcelSmartFillClientJobId: () => "sf-client-job-cancel",
    isExcelTaskVisible: () => true,
    getEtApplication: () => ({}),
    getActiveWorkbook: () => ({}),
    getActiveSheet: () => ({ Name: "Sheet1" }),
    getSelectionRange: () => mockRange,
    readSmartFillWorkbookId: () => "wb-doc-1",
    readSmartFillSheetName: () => "Sheet1",
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => { slotClaimed = true; },
      releaseTaskSlot: () => { slotReleased = true; },
      getDocumentSessionId: () => "doc-1",
      getDocumentDisplayName: () => "工作簿1.xlsx",
      extractExcelSmartFillSourcePayloadYielding: helpers.extractExcelSmartFillSourcePayloadYielding,
      requireExcelSmartFillInstruction: (t) => t
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setExcelTaskBusy: () => {},
    setStatus: () => {},
    setPlainResult: () => {},
    setNodeTextIfChanged: () => {},
    setSmartFillInterruptedRetryVisible: () => {},
    setExcelSmartFillCancelVisible: () => {},
    saveCurrentSmartFillSessionState: () => {},
    saveExcelSmartFillActiveJob: () => { activeJobSaved = true; },
    clearExcelSmartFillActiveJob: () => {},
    summarizeSmartFillSource: () => "A1:C20",
    setScopeLine: () => {},
    startExcelSmartFillWaitFeedback: () => () => {},
    request: () => {
      adapterRequested = true;
      return Promise.resolve({ data: {} });
    },
    setTrace: () => {},
    finalizeExcelSmartFillResult: () => {},
    safeText: (t) => t || "",
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 10000,
    EXCEL_SMART_FILL_EXTRACTION_OPTIONS: {
      maxItems: 500,
      maxSourceRows: 500,
      maxSourceColumns: 50,
      maxCellTextLength: 2000,
      maxTotalTextLength: 200000
    },
    pollExcelSmartFillJob: () => {},
    describeExcelSmartFillPollError: (e) => e.message,
    isFatalExcelSmartFillPollError: () => false
  };

  const fns = loadFunctions([
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "getTaskPerformance",
    "recordTaskFirstRender",
    "runExcelSmartFillAction"
  ], context);

  context.beginTaskPerformance = fns.beginTaskPerformance;
  context.bindTaskPerformanceTrace = fns.bindTaskPerformanceTrace;
  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelSmartFillAction();

  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(slotClaimed, "task slot must have been claimed");
  assert.ok(slotReleased, "task slot must be released upon cancellation");
  assert.strictEqual(adapterRequested, false, "Adapter request MUST NOT be called when cancelled during extraction");
  assert.strictEqual(activeJobSaved, false, "preparation must not persist a recoverable adapter job");
  assert.strictEqual(
    state.smartFillResult,
    previousResult,
    "cancelling a new extraction must preserve the existing read-only preview"
  );
});

// 7. 抽取中途切换工作簿：严禁提交旧来源至新会话
test("taskpane: runExcelSmartFillAction aborts if workbook session changes during extraction", async () => {
  let virtualTime = 1000;
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: id === "excel-smart-fill-instruction" ? "分析数据" : "",
        hidden: false,
        disabled: false,
        addEventListener: () => {}
      };
    }
    return elements[id];
  };

  let activeSessionId = "doc-1";
  let adapterRequested = false;
  let slotReleased = false;

  const state = {
    currentMode: "excelSmartFill",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    excelTaskSessions: {},
    activeTaskSlots: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    smartFillInstruction: "",
    smartFillResult: null,
    smartFillCancelRequested: false,
    smartFillExtractionInFlight: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

  let currentStep = 0;
  const mockRange = buildMockRange(20, 3, () => {
    currentStep += 1;
    if (currentStep === 10) {
      activeSessionId = "doc-2"; // 模拟中途切换了工作簿
    }
  });

  const context = {
    state,
    byId,
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => { fn(); },
    getExcelTaskSession: (type) => {
      if (!state.excelTaskSessions[type]) {
        state.excelTaskSessions[type] = { jobId: "", pollStartedAt: 0, resumeExpected: false };
      }
      return state.excelTaskSessions[type];
    },
    buildExcelSmartFillClientJobId: () => "sf-client-job-switch",
    isExcelTaskVisible: () => true,
    getEtApplication: () => ({}),
    getActiveWorkbook: () => ({}),
    getActiveSheet: () => ({ Name: "Sheet1" }),
    getSelectionRange: () => mockRange,
    readSmartFillWorkbookId: () => "wb-doc-1",
    readSmartFillSheetName: () => "Sheet1",
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      releaseTaskSlot: () => { slotReleased = true; },
      getDocumentSessionId: () => activeSessionId,
      getDocumentDisplayName: () => (activeSessionId === "doc-1" ? "工作簿1.xlsx" : "工作簿2.xlsx"),
      extractExcelSmartFillSourcePayloadYielding: helpers.extractExcelSmartFillSourcePayloadYielding,
      requireExcelSmartFillInstruction: (t) => t
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setExcelTaskBusy: () => {},
    setStatus: () => {},
    setPlainResult: () => {},
    setNodeTextIfChanged: () => {},
    setSmartFillInterruptedRetryVisible: () => {},
    setExcelSmartFillCancelVisible: () => {},
    saveCurrentSmartFillSessionState: () => {},
    saveExcelSmartFillActiveJob: () => {},
    clearExcelSmartFillActiveJob: () => {},
    summarizeSmartFillSource: () => "A1:C20",
    setScopeLine: () => {},
    startExcelSmartFillWaitFeedback: () => () => {},
    request: () => {
      adapterRequested = true;
      return Promise.resolve({ data: {} });
    },
    setTrace: () => {},
    finalizeExcelSmartFillResult: () => {},
    safeText: (t) => t || "",
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 10000,
    EXCEL_SMART_FILL_EXTRACTION_OPTIONS: {
      maxItems: 500,
      maxSourceRows: 500,
      maxSourceColumns: 50,
      maxCellTextLength: 2000,
      maxTotalTextLength: 200000
    },
    pollExcelSmartFillJob: () => {},
    describeExcelSmartFillPollError: (e) => e.message,
    isFatalExcelSmartFillPollError: () => false
  };

  const fns = loadFunctions([
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "getTaskPerformance",
    "recordTaskFirstRender",
    "runExcelSmartFillAction"
  ], context);

  context.beginTaskPerformance = fns.beginTaskPerformance;
  context.bindTaskPerformanceTrace = fns.bindTaskPerformanceTrace;
  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelSmartFillAction();

  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(slotReleased, "task slot must be released when session changed");
  assert.strictEqual(adapterRequested, false, "Adapter request MUST NOT be called when session changed during extraction");
});

// 8. 端到端性能跟踪：成功完成时记录 4 项指标并绑定 trace
test("taskpane: runExcelSmartFillAction tracks clickToFeedbackMs, localExtractionMs, clickToAdapterAcceptedMs and completionToFirstRenderMs", async () => {
  let virtualTime = 3000;
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: id === "excel-smart-fill-instruction" ? "统计数据" : "",
        hidden: false,
        disabled: false,
        addEventListener: () => {}
      };
    }
    return elements[id];
  };

  const state = {
    currentMode: "excelSmartFill",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    excelTaskSessions: {},
    activeTaskSlots: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    smartFillInstruction: "",
    smartFillResult: null,
    smartFillCancelRequested: false,
    smartFillExtractionInFlight: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

  const mockRange = buildMockRange(5, 2);

  const context = {
    state,
    byId,
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => { fn(); },
    getExcelTaskSession: (type) => {
      if (!state.excelTaskSessions[type]) {
        state.excelTaskSessions[type] = { jobId: "", pollStartedAt: 0, resumeExpected: false };
      }
      return state.excelTaskSessions[type];
    },
    buildExcelSmartFillClientJobId: () => "sf-client-job-perf",
    isExcelTaskVisible: () => true,
    getEtApplication: () => ({}),
    getActiveWorkbook: () => ({}),
    getActiveSheet: () => ({ Name: "Sheet1" }),
    getSelectionRange: () => mockRange,
    readSmartFillWorkbookId: () => "wb-doc-1",
    readSmartFillSheetName: () => "Sheet1",
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      releaseTaskSlot: () => {},
      getDocumentSessionId: () => "doc-1",
      getDocumentDisplayName: () => "工作簿1.xlsx",
      extractExcelSmartFillSourcePayloadYielding: (range, opts) => {
        virtualTime += 35; // 本地抽取耗时 35ms
        return helpers.extractExcelSmartFillSourcePayloadYielding(range, opts);
      },
      requireExcelSmartFillInstruction: (t) => t
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setExcelTaskBusy: () => {},
    setStatus: () => {
      if (virtualTime === 3000) {
        virtualTime += 12; // 点击到反馈耗时 12ms
      }
    },
    setPlainResult: () => {},
    setNodeTextIfChanged: () => {},
    setSmartFillInterruptedRetryVisible: () => {},
    setExcelSmartFillCancelVisible: () => {},
    saveCurrentSmartFillSessionState: () => {},
    saveExcelSmartFillActiveJob: () => {},
    clearExcelSmartFillActiveJob: () => {},
    summarizeSmartFillSource: () => "A1:B5",
    setScopeLine: () => {},
    startExcelSmartFillWaitFeedback: () => () => {},
    request: () => {
      virtualTime += 110; // 点击到受理共 12 + 35 + 110 = 157ms
      return Promise.resolve({
        data: {
          jobId: "sf-client-job-perf",
          traceId: "trace-sf-perf",
          status: "completed",
          result: { schemaVersion: "excel.smart_fill.v2", items: [] }
        }
      });
    },
    setTrace: () => {},
    finalizeExcelSmartFillResult: (result, jobId) => {
      virtualTime += 25; // 完成到首渲染耗时 25ms
      context.recordTaskFirstRender(jobId, "trace-sf-perf", "excel.smart_fill", virtualTime - 25);
    },
    safeText: (t) => t || "",
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 10000,
    EXCEL_SMART_FILL_EXTRACTION_OPTIONS: {
      maxItems: 500,
      maxSourceRows: 500,
      maxSourceColumns: 50,
      maxCellTextLength: 2000,
      maxTotalTextLength: 200000
    },
    pollExcelSmartFillJob: () => {},
    describeExcelSmartFillPollError: (e) => e.message,
    isFatalExcelSmartFillPollError: () => false
  };

  const fns = loadFunctions([
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "getTaskPerformance",
    "recordTaskFirstRender",
    "runExcelSmartFillAction"
  ], context);

  context.beginTaskPerformance = fns.beginTaskPerformance;
  context.bindTaskPerformanceTrace = fns.bindTaskPerformanceTrace;
  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelSmartFillAction();

  await new Promise((resolve) => setImmediate(resolve));

  const perf = state.lastTaskPerformance;
  assert.ok(perf !== null, "lastTaskPerformance must be recorded");
  assert.strictEqual(perf.jobId, "sf-client-job-perf");
  assert.strictEqual(perf.taskType, "excel.smart_fill");
  assert.strictEqual(perf.clickToFeedbackMs, 12);
  assert.strictEqual(perf.localExtractionMs, 35);
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 157);
  assert.strictEqual(perf.completionToFirstRenderMs, 25);
});
