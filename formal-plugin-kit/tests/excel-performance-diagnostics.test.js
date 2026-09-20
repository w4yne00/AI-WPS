const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { etRoot: root } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

function functionSource(name) {
  let start = source.indexOf(`  function ${name}(`);
  if (start < 0) {
    start = source.indexOf(`function ${name}(`);
  }
  assert.ok(start >= 0, `missing function ${name}`);
  const next = source.indexOf("\n  function ", start + 3);
  return source.slice(start, next === -1 ? source.length : next);
}

function loadFunctions(names, context) {
  const declarations = names.map(functionSource).join("\n");
  const exports = names.map((name) => `${name}: ${name}`).join(",");
  return vm.runInNewContext(
    `(function () { ${declarations}; return {${exports}}; })()`,
    context
  );
}

// 1. 静态源码包含关键指标标记
test("ET taskpane contains performance tracking functions and metrics", () => {
  [
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "getTaskPerformance",
    "recordTaskFirstRender",
    "clickToFeedbackMs",
    "localExtractionMs",
    "clickToAdapterAcceptedMs",
    "completionToFirstRenderMs",
    "lastTaskPerformance",
    "任务窗格本地耗时"
  ].forEach((marker) => {
    assert.ok(source.includes(marker), `missing marker: ${marker}`);
  });
});

// 2. 任务窗格性能跟踪记录基础能力与 LRU
test("task performance recording, trace binding and LRU eviction", () => {
  let virtualTime = 1000;
  const state = {
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };
  const context = {
    state,
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn()
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "selectTaskPerformance",
    "recordTaskFirstRender"
  ], context);

  // 创建性能跟踪
  const perf = fns.beginTaskPerformance("job-ana-1", "excel.analysis", 1000, 15);
  assert.strictEqual(perf.jobId, "job-ana-1");
  assert.strictEqual(perf.taskType, "excel.analysis");
  assert.strictEqual(perf.clickTimestamp, 1000);
  assert.strictEqual(perf.clickToFeedbackMs, 15);
  assert.strictEqual(state.lastTaskPerformance, perf);

  // 绑定 traceId
  fns.bindTaskPerformanceTrace("job-ana-1", "trace-ana-1", "job-ana-1-resolved");
  assert.strictEqual(perf.traceId, "trace-ana-1");
  assert.strictEqual(perf.jobId, "job-ana-1-resolved");
  assert.strictEqual(fns.getTaskPerformance(null, "trace-ana-1"), perf);
  assert.strictEqual(fns.getTaskPerformance("job-ana-1-resolved", null), perf);

  // 首渲染耗时记录
  virtualTime = 1500;
  fns.recordTaskFirstRender("job-ana-1-resolved", "trace-ana-1", "excel.analysis", 1420);
  assert.strictEqual(perf.completionToFirstRenderMs, 80); // 1500 - 1420

  // 验证超过 50 个任务触发 LRU 淘汰
  for (let i = 2; i <= 60; i++) {
    fns.beginTaskPerformance(`job-ana-${i}`, "excel.analysis", 2000 + i, 10);
  }
  assert.strictEqual(state.taskPerformanceOrder.length, 50);
  // 第 1 个任务已被淘汰
  assert.strictEqual(fns.getTaskPerformance("job-ana-1-resolved", null), null);
  // 最新的任务仍然保留
  assert.ok(fns.getTaskPerformance("job-ana-60", null) !== null);
});

// 3. 高级诊断呈现“任务窗格本地耗时”
test("renderProviderDiagnostics presents local taskpane metrics section", () => {
  const state = {
    lastTaskPerformance: {
      jobId: "job-ana-1",
      taskType: "excel.analysis",
      clickToFeedbackMs: 12,
      localExtractionMs: 34,
      clickToAdapterAcceptedMs: 156,
      completionToFirstRenderMs: 45
    }
  };

  const context = {
    state,
    firstErrorMessage: () => "",
    yesNo: (v) => (v ? "是" : "否"),
    describeAuthSource: () => "mock",
    normalizeReportList: (l) => l || []
  };

  const fns = loadFunctions(["renderProviderDiagnostics"], context);

  const markdown = fns.renderProviderDiagnostics(
    { data: { taskType: "excel.analysis", traceId: "trace-1", performance: { providerOutcome: "success" } } },
    { data: { configured: true, providerType: "mock" } },
    { data: {} },
    { data: {} }
  );

  assert.ok(markdown.includes("## 任务窗格本地耗时"), "diagnostics should contain local latency section");
  assert.ok(markdown.includes("- 点击到反馈耗时：12 ms"), "contains clickToFeedbackMs");
  assert.ok(markdown.includes("- 本地抽取耗时：34 ms"), "contains localExtractionMs");
  assert.ok(markdown.includes("- 点击到后台接收耗时：156 ms"), "contains clickToAdapterAcceptedMs");
  assert.ok(markdown.includes("- 完成到首渲染耗时：45 ms"), "contains completionToFirstRenderMs");
});

// 4. runExcelAnalysisAction 完整记录四项本地耗时
test("runExcelAnalysisAction tracks clickToFeedbackMs, localExtractionMs, clickToAdapterAcceptedMs and completionToFirstRenderMs", async () => {
  let virtualTime = 1000;
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: "",
        hidden: false,
        disabled: false,
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        setAttribute() {},
        getAttribute() { return ""; },
        addEventListener() {}
      };
    }
    return elements[id];
  };

  const state = {
    currentMode: "excelAnalysis",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    activeTaskSlots: {},
    excelTaskSessions: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

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
    buildExcelAnalysisClientJobId: () => "analysis-client-job-1",
    isExcelTaskVisible: () => true,
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      releaseTaskSlot: () => {},
      getDocumentSessionId: () => "doc-1",
      getDocumentDisplayName: () => "工作簿1.xlsx"
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setStatus: () => {
      if (virtualTime === 1000) {
        virtualTime += 15; // 点击到反馈耗时 15ms
      }
    },
    setPlainResult: () => {},
    setExcelTaskBusy: () => {},
    extractExcelRange: () => {
      virtualTime += 40; // 本地抽取耗时 40ms
      return { scope: { address: "A1:B10" }, table: { headers: ["A"], rows: [["1"]] } };
    },
    summarizeExcelPayload: () => "A1:B10",
    setScopeLine: () => {},
    setInterruptedRetryVisible: () => {},
    setExcelAnalysisCancelVisible: () => {},
    safeText: (t) => t || "",
    clearExcelAnalysisActiveJob: () => {},
    startExcelAnalysisWaitFeedback: () => () => {},
    saveExcelAnalysisActiveJob: () => {},
    request: (url, payload) => {
      virtualTime += 120; // 从点击到受理共 175ms (15 + 40 + 120)
      return Promise.resolve({
        data: {
          jobId: "analysis-client-job-1",
          traceId: "trace-analysis-1",
          status: "completed",
          result: { plainText: "分析完成" }
        }
      });
    },
    setTrace: () => {},
    recordFinalizedAnalysisResult: () => {},
    renderExcelAnalysisResult: (result, jobId, traceId, completionTimestamp) => {
      virtualTime += 30; // 完成到首渲染耗时 30ms
      context.recordTaskFirstRender(jobId, traceId, "excel.analysis", completionTimestamp);
    },
    pollExcelAnalysisJob: () => {},
    describeExcelAnalysisPollError: (e) => e.message,
    isFatalExcelAnalysisPollError: () => false,
    EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS: 10000
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "recordTaskFirstRender",
    "runExcelAnalysisAction"
  ], context);

  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelAnalysisAction();

  // 等待 Promise.resolve
  await new Promise((resolve) => setImmediate(resolve));

  const perf = state.lastTaskPerformance;
  assert.ok(perf !== null, "lastTaskPerformance must be recorded");
  assert.strictEqual(perf.jobId, "analysis-client-job-1");
  assert.strictEqual(perf.taskType, "excel.analysis");
  assert.strictEqual(perf.clickToFeedbackMs, 15);
  assert.strictEqual(perf.localExtractionMs, 40);
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 175);
  assert.strictEqual(perf.completionToFirstRenderMs, 30);
});

// 5. runExcelFormulaAction 完整记录四项本地耗时
test("runExcelFormulaAction tracks clickToFeedbackMs, localExtractionMs, clickToAdapterAcceptedMs and completionToFirstRenderMs", async () => {
  let virtualTime = 2000;
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        value: "计算平均值",
        hidden: false,
        disabled: false,
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        setAttribute() {},
        getAttribute() { return ""; },
        addEventListener() {}
      };
    }
    return elements[id];
  };

  const state = {
    currentMode: "excelFormulaAssistant",
    formulaMode: "generate",
    documentSessionId: "doc-1",
    documentDisplayName: "工作簿1.xlsx",
    activeTaskSlots: {},
    excelTaskSessions: {},
    adapterHealthStatus: "healthy",
    modelTasksAllowed: true,
    workflowProfileMutationBusy: false,
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null
  };

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
    buildExcelFormulaClientJobId: () => "formula-client-job-1",
    isExcelTaskVisible: () => true,
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot: () => {},
      releaseTaskSlot: () => {},
      getDocumentSessionId: () => "doc-1",
      getDocumentDisplayName: () => "工作簿1.xlsx"
    },
    validateActiveDirectTaskSelection: () => ({ ok: true }),
    setStatus: () => {
      if (virtualTime === 2000) {
        virtualTime += 10; // 点击到反馈耗时 10ms
      }
    },
    setPlainResult: () => {},
    setExcelTaskBusy: () => {},
    extractExcelFormulaRange: () => {
      virtualTime += 25; // 本地抽取耗时 25ms
      return { selection: { address: "B2:B10" }, cells: [] };
    },
    summarizeExcelFormulaPayload: () => "B2:B10",
    setScopeLine: () => {},
    setFormulaInterruptedRetryVisible: () => {},
    setExcelFormulaCancelVisible: () => {},
    safeText: (t) => t || "",
    clearExcelFormulaActiveJob: () => {},
    getFormulaModeUi: () => ({ submitStatus: "提交中", submitResult: "等待中" }),
    startExcelFormulaWaitFeedback: () => () => {},
    saveExcelFormulaActiveJob: () => {},
    request: (url, payload) => {
      virtualTime += 100; // 点击到受理共 135ms (10 + 25 + 100)
      return Promise.resolve({
        data: {
          jobId: "formula-client-job-1",
          traceId: "trace-formula-1",
          status: "completed",
          result: { primaryFormula: "=AVERAGE(B2:B10)" }
        }
      });
    },
    setTrace: () => {},
    recordFinalizedFormulaResult: () => {},
    renderExcelFormulaResult: (result, jobId, traceId, completionTimestamp) => {
      virtualTime += 20; // 完成到首渲染耗时 20ms
      context.recordTaskFirstRender(jobId, traceId, "excel.formula_assistant", completionTimestamp);
    },
    getExcelFormulaCompletionStatus: () => "推荐公式已生成。",
    pollExcelFormulaJob: () => {},
    describeExcelFormulaPollError: (e) => e.message,
    isFatalExcelFormulaPollError: () => false,
    EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS: 10000
  };

  const fns = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "recordTaskFirstRender",
    "runExcelFormulaAction"
  ], context);

  context.recordTaskFirstRender = fns.recordTaskFirstRender;

  fns.runExcelFormulaAction();

  await new Promise((resolve) => setImmediate(resolve));

  const perf = state.lastTaskPerformance;
  assert.ok(perf !== null, "lastTaskPerformance must be recorded");
  assert.strictEqual(perf.jobId, "formula-client-job-1");
  assert.strictEqual(perf.taskType, "excel.formula_assistant");
  assert.strictEqual(perf.clickToFeedbackMs, 10);
  assert.strictEqual(perf.localExtractionMs, 25);
  assert.strictEqual(perf.clickToAdapterAcceptedMs, 135);
  assert.strictEqual(perf.completionToFirstRenderMs, 20);
});

