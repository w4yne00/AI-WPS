const assert = require("assert");
const { test } = require("node:test");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { etRoot: root } = require("./support/plugin-roots");

const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const taskpaneHtml = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const materialLedgerSource = fs.readFileSync(path.join(root, "material-ledger.js"), "utf8");

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
          add: function (c) { this.classes.add(c); this[c] = true; },
          remove: function (c) { this.classes.delete(c); delete this[c]; },
          toggle: function (c, force) {
            if (force === undefined) {
              if (this.classes.has(c)) { this.classes.delete(c); delete this[c]; }
              else { this.classes.add(c); this[c] = true; }
            } else if (force) {
              this.classes.add(c); this[c] = true;
            } else {
              this.classes.delete(c); delete this[c];
            }
          },
          contains: function (c) { return this.classes.has(c); }
        },
        hidden: false,
        disabled: false,
        setAttribute: function (attr, val) { this[attr] = val; },
        getAttribute: function (attr) { return this[attr]; },
        addEventListener: function (evt, handler) {
          this["on" + evt] = handler;
        },
        querySelector: function (sel) {
          return null;
        },
        querySelectorAll: function () { return []; }
      };
    }
    return elements[id];
  };

  const defaultTaskSessions = {
    "excel.analysis": {
      jobId: "",
      pollStartedAt: 0,
      pollErrorCount: 0,
      resumeExpected: false,
      recoveryPending: false
    },
    "excel.formula_assistant": {
      jobId: "",
      pollStartedAt: 0,
      pollErrorCount: 0,
      resumeExpected: false,
      recoveryPending: false
    },
    "excel.smart_fill": {
      jobId: "",
      pollStartedAt: 0,
      pollErrorCount: 0,
      resumeExpected: false,
      recoveryPending: false
    }
  };

  const state = {
    currentMode: "excelAnalysis",
    lastTaskMode: "excelAnalysis",
    busy: false,
    workflowProfileMutationBusy: false,
    modelTasksAllowed: true,
    adapterHealthStatus: "healthy",
    documentSessionId: "doc_session_1",
    documentDisplayName: "工作簿1.xlsx",
    activeTaskSlots: {},
    activeAnalysisResultsBySession: {},
    activeFormulaResultsBySession: {},
    activeSmartFillResultsBySession: {},
    analysisResult: null,
    formulaResult: null,
    smartFillResult: null,
    formulaMode: "generate",
    historyOpen: false,
    historyUnreadCount: 0,
    historyItems: [],
    ...(initialOverrides.state || {})
  };

  const requests = [];
  const timeouts = [];
  const ctx = {
    state,
    byId,
    document: {
      body: {
        attributes: {},
        setAttribute: function (attr, val) { this.attributes[attr] = val; },
        getAttribute: function (attr) { return this.attributes[attr]; }
      },
      querySelector: function () { return null; },
      visibilityState: "visible"
    },
    window: {
      localStorage: {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {}
      }
    },
    helpers: {
      ...helpers,
      getDocumentSessionId: (workbook) => (
        workbook && workbook.__ai_wps_doc_session__
          ? workbook.__ai_wps_doc_session__
          : helpers.getDocumentSessionId(workbook)
      )
    },
    requests,
    request: (url, body, options) => {
      requests.push({ url, body, options });
      return Promise.resolve({ success: true, data: { jobId: "job-default", status: "completed" } });
    },
    setStatus: (msg) => { state.statusMessage = msg; byId("status-line").textContent = msg; },
    setPlainResult: (text) => {
      byId("result-output").textContent = text;
    },
    setResult: (text) => {
      byId("result-output").textContent = text;
    },
    setNodeTextIfChanged: (node, text) => {
      if (node) node.textContent = text;
    },
    setNodeClassNameIfChanged: (node, cls) => {
      if (node) node.className = cls;
    },
    safeText: (v) => String(v || "").trim(),
    buildExcelAnalysisClientJobId: () => "ana_job_" + Math.random().toString(36).slice(2, 8),
    buildExcelFormulaClientJobId: () => "form_job_" + Math.random().toString(36).slice(2, 8),
    buildExcelSmartFillClientJobId: () => "fill_job_" + Math.random().toString(36).slice(2, 8),
    clearExcelAnalysisActiveJob: () => {},
    saveExcelAnalysisActiveJob: () => {},
    clearExcelFormulaActiveJob: () => {},
    saveExcelFormulaActiveJob: () => {},
    clearExcelSmartFillActiveJob: () => {},
    saveExcelSmartFillActiveJob: () => {},
    setExcelTaskBusy: (busy, docSessionId, taskType) => {
      state.busy = busy;
      byId("btn-run-primary").disabled = busy;
    },
    setInterruptedRetryVisible: (v) => { byId("btn-resubmit-interrupted-job").hidden = !v; },
    setExcelAnalysisCancelVisible: () => {},
    setFormulaInterruptedRetryVisible: (v) => { byId("btn-resubmit-interrupted-formula-job").hidden = !v; },
    setExcelFormulaCancelVisible: () => {},
    setSmartFillInterruptedRetryVisible: (v) => { byId("btn-resubmit-interrupted-smart-fill-job").hidden = !v; },
    setExcelSmartFillCancelVisible: () => {},
    setScopeLine: () => {},
    summarizeExcelPayload: () => "数据范围: A1:C10",
    summarizeExcelFormulaPayload: () => "选区范围: B2:B10",
    startExcelAnalysisWaitFeedback: () => () => {},
    startExcelFormulaWaitFeedback: () => () => {},
    startExcelSmartFillWaitFeedback: () => () => {},
    describeExcelAnalysisPollError: (err) => err.message || "error",
    describeExcelFormulaPollError: (err) => err.message || "error",
    isFatalExcelAnalysisPollError: () => true,
    isFatalExcelFormulaPollError: () => true,
    getFormulaModeUi: () => ({
      actionLabel: "生成公式",
      submitStatus: "正在提交公式请求...",
      submitResult: "正在等待推荐公式。"
    }),
    getExcelFormulaCompletionStatus: () => "公式已生成。",
    setTrace: () => {},
    refreshDiagnostics: () => Promise.resolve(),
    EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS: 30000,
    EXCEL_FORMULA_POLL_REQUEST_TIMEOUT_MS: 30000,
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 30000,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
    EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    FRONTEND_BUILD_VERSION: "1.0.0",
    getExcelTaskSession: (tt) => {
      if (!defaultTaskSessions[tt]) {
        defaultTaskSessions[tt] = { jobId: "", pollStartedAt: 0, pollErrorCount: 0, resumeExpected: false };
      }
      return defaultTaskSessions[tt];
    },
    isExcelTaskVisible: () => true,
    extractExcelRange: () => ({
      scope: { sheetName: "Sheet1", address: "A1:C10" },
      table: { headers: ["A", "B", "C"], rows: [["1", "2", "3"]], rowCount: 1, columnCount: 3 }
    }),
    extractExcelFormulaRange: () => ({
      scope: { sheetName: "Sheet1", address: "B2:B10" }
    }),
    setTimeout: (fn, ms) => {
      const handle = { fn, ms };
      timeouts.push(handle);
      return handle;
    },
    clearTimeout: () => {},
    defaultWorkbook: {
      Name: "工作簿1.xlsx",
      FullName: "/path/工作簿1.xlsx",
      __ai_wps_doc_session__: state.documentSessionId
    },
    getEtApplication: function () {
      return { ActiveWorkbook: ctx.defaultWorkbook };
    },
    getActiveWorkbook: function (app) {
      return (app && app.ActiveWorkbook) || ctx.defaultWorkbook;
    },
    timeouts,
    ...(initialOverrides.context || {})
  };

  return { ctx, state, byId, requests, timeouts, elements };
}

// ==========================================
// Test 1: Active Task Slot Guard per session
// ==========================================
function testActiveTaskSlotGuard() {
  assert.strictEqual(typeof helpers.isTaskSlotBusy, "function", "isTaskSlotBusy should be a function");
  assert.strictEqual(typeof helpers.claimTaskSlot, "function", "claimTaskSlot should be a function");
  assert.strictEqual(typeof helpers.releaseTaskSlot, "function", "releaseTaskSlot should be a function");

  const slots = {};
  const host = "et";
  const session1 = "doc_session_1";
  const session2 = "doc_session_2";
  const taskTypes = ["excel.analysis", "excel.formula_assistant", "excel.smart_fill", "excel.material_ledger"];

  for (const tt of taskTypes) {
    // Initially not busy
    assert.strictEqual(helpers.isTaskSlotBusy(slots, host, tt, session1), false);

    // Claim slot
    helpers.claimTaskSlot(slots, host, tt, session1, "job-1");
    assert.strictEqual(helpers.isTaskSlotBusy(slots, host, tt, session1), true);

    // Other session not busy
    assert.strictEqual(helpers.isTaskSlotBusy(slots, host, tt, session2), false);

    // Release slot
    helpers.releaseTaskSlot(slots, host, tt, session1, "job-1");
    assert.strictEqual(helpers.isTaskSlotBusy(slots, host, tt, session1), false);
  }
}

// ==========================================
// Test 2: Synchronous Slot Claiming Blocks Rapid Consecutive Clicks
// ==========================================
function testConsecutiveClickGuarding() {
  // Test runExcelAnalysisAction
  const h1 = createBaseTestContext();
  const runAnalysis = vm.runInNewContext(
    `(${functionSource("runExcelAnalysisAction")})`,
    h1.ctx
  );

  // First click: synchronous check and immediate slot claim
  runAnalysis();
  assert.strictEqual(
    helpers.isTaskSlotBusy(h1.state.activeTaskSlots, "et", "excel.analysis", "doc_session_1"),
    true,
    "runExcelAnalysisAction must synchronously claim task slot before deferred extraction"
  );
  assert.strictEqual(h1.state.busy, true, "runExcelAnalysisAction must synchronously set busy to true");

  // Second immediate click (before setTimeout fires) must be blocked
  runAnalysis();
  assert.strictEqual(
    h1.state.statusMessage,
    "当前工作簿已存在进行中的智能分析任务，请等待其完成。",
    "Second consecutive click must be blocked by synchronous slot claiming"
  );
  assert.strictEqual(h1.timeouts.length, 1, "Only one asynchronous task should have been scheduled");

  // Test runExcelFormulaAction
  const h2 = createBaseTestContext();
  h2.byId("excel-formula-requirement").value = "计算总销售额";
  const runFormula = vm.runInNewContext(
    `(${functionSource("runExcelFormulaAction")})`,
    h2.ctx
  );

  runFormula();
  assert.strictEqual(
    helpers.isTaskSlotBusy(h2.state.activeTaskSlots, "et", "excel.formula_assistant", "doc_session_1"),
    true,
    "runExcelFormulaAction must synchronously claim task slot before deferred extraction"
  );
  assert.strictEqual(h2.state.busy, true, "runExcelFormulaAction must synchronously set busy to true");

  runFormula();
  assert.strictEqual(
    h2.state.statusMessage,
    "当前工作簿已存在进行中的公式助手任务，请等待其完成。",
    "Second consecutive click must be blocked by synchronous slot claiming"
  );
  assert.strictEqual(h2.timeouts.length, 1, "Only one asynchronous task should have been scheduled");
}

// ==========================================
// Test 3: Regenerate Creates New Job Even With Identical Inputs
// ==========================================
async function testRegenerateCreatesNewJobEvenWithIdenticalInput() {
  // 1. excel.analysis
  {
    const h = createBaseTestContext();
    const runAnalysis = vm.runInNewContext(
      `(${functionSource("runExcelAnalysisAction")})`,
      h.ctx
    );

    // First run
    runAnalysis();
    assert.strictEqual(h.timeouts.length, 1);
    await h.timeouts[0].fn();
    assert.strictEqual(h.requests.length, 1);
    const job1Id = h.requests[0].body.clientJobId;
    assert.ok(job1Id, "First run should produce clientJobId");

    // Complete job 1
    helpers.releaseTaskSlot(h.state.activeTaskSlots, "et", "excel.analysis", "doc_session_1", job1Id);
    h.state.analysisResult = { plainText: "第一轮分析结果" };
    h.state.busy = false;

    // Second run with identical input
    runAnalysis();
    assert.strictEqual(h.timeouts.length, 2);
    await h.timeouts[1].fn();
    assert.strictEqual(h.requests.length, 2);
    const job2Id = h.requests[1].body.clientJobId;
    assert.ok(job2Id, "Second run should produce clientJobId");
    assert.notStrictEqual(job1Id, job2Id, "Second run must have a distinct clientJobId even with identical input");
  }

  // 2. excel.formula_assistant
  {
    const h = createBaseTestContext();
    h.byId("excel-formula-requirement").value = "计算总额";
    const runFormula = vm.runInNewContext(
      `(${functionSource("runExcelFormulaAction")})`,
      h.ctx
    );

    // First run
    runFormula();
    assert.strictEqual(h.timeouts.length, 1);
    await h.timeouts[0].fn();
    assert.strictEqual(h.requests.length, 1);
    const job1Id = h.requests[0].body.clientJobId;

    // Complete job 1
    helpers.releaseTaskSlot(h.state.activeTaskSlots, "et", "excel.formula_assistant", "doc_session_1", job1Id);
    h.state.formulaResult = { primaryFormula: "=SUM(B2:B10)" };
    h.state.busy = false;

    // Second run with identical requirement
    runFormula();
    assert.strictEqual(h.timeouts.length, 2);
    await h.timeouts[1].fn();
    assert.strictEqual(h.requests.length, 2);
    const job2Id = h.requests[1].body.clientJobId;
    assert.notStrictEqual(job1Id, job2Id, "Formula second run must have a distinct clientJobId");
  }

  // 3. excel.material_ledger
  {
    const context = {
      window: {},
      console,
      Promise,
      Date,
      Math,
      Array,
      Object,
      setTimeout,
      clearTimeout
    };
    vm.runInNewContext(materialLedgerSource, context);
    const storageMap = new Map();
    const storage = {
      getItem: (k) => storageMap.get(k) || null,
      setItem: (k, v) => storageMap.set(k, String(v)),
      removeItem: (k) => storageMap.delete(k)
    };
    const ledgerRequests = [];
    const ledger = context.createMaterialLedger({
      storage,
      getSessionId: () => "sess-1",
      request: (url, body, options) => {
        ledgerRequests.push({ url, body, options });
        return Promise.resolve({
          data: {
            jobId: (body && body.clientJobId) || "job-ret-1",
            status: "completed",
            rows: [{ values: { "工作事项": "事项1" } }]
          }
        });
      }
    });

    // Run 1
    await ledger.generate();
    const jobPosts1 = ledgerRequests.filter(r => r.url === "/excel/material-ledger/jobs");
    assert.strictEqual(jobPosts1.length, 1);
    const job1Id = jobPosts1[0].body.clientJobId;
    assert.ok(job1Id, "First ledger run must have clientJobId");

    // Run 2 with identical data after completion
    await ledger.generate();
    const jobPosts2 = ledgerRequests.filter(r => r.url === "/excel/material-ledger/jobs");
    assert.strictEqual(jobPosts2.length, 2);
    const job2Id = jobPosts2[1].body.clientJobId;
    assert.notStrictEqual(job1Id, job2Id, "Second ledger run must generate a new clientJobId even with identical inputs");
  }
}

// ==========================================
// Test 4: Network Retry vs Regenerate ID Reuse
// ==========================================
async function testNetworkRetryVsRegenerate() {
  const context = {
    window: {},
    console,
    Promise,
    Date,
    Math,
    Array,
    Object,
    setTimeout,
    clearTimeout
  };
  vm.runInNewContext(materialLedgerSource, context);
  const storageMap = new Map();
  const storage = {
    getItem: (k) => storageMap.get(k) || null,
    setItem: (k, v) => storageMap.set(k, String(v)),
    removeItem: (k) => storageMap.delete(k)
  };

  let failOnce = true;
  const ledgerRequests = [];
  const ledger = context.createMaterialLedger({
    storage,
    getSessionId: () => "sess-retry",
    request: (url, body) => {
      ledgerRequests.push({ url, body });
      if (url === "/excel/material-ledger/jobs" && failOnce) {
        failOnce = false;
        const err = new Error("网络超时");
        err.status = 504;
        return Promise.reject(err);
      }
      return Promise.resolve({
        data: {
          jobId: (body && body.clientJobId) || "id-1",
          status: "completed",
          rows: []
        }
      });
    }
  });

  // First attempt fails with network error
  await ledger.generate();
  const jobPosts1 = ledgerRequests.filter(r => r.url === "/excel/material-ledger/jobs");
  assert.strictEqual(jobPosts1.length, 1);
  const unconfirmedId = jobPosts1[0].body.clientJobId;

  // Unconfirmed retry reuses the original clientJobId for backend idempotency
  await ledger.generate();
  const jobPosts2 = ledgerRequests.filter(r => r.url === "/excel/material-ledger/jobs");
  assert.strictEqual(jobPosts2.length, 2);
  assert.strictEqual(
    jobPosts2[1].body.clientJobId,
    unconfirmedId,
    "Unconfirmed submission retry must reuse original clientJobId"
  );

  // Now job has completed. Next generate must produce a new clientJobId
  await ledger.generate();
  const jobPosts3 = ledgerRequests.filter(r => r.url === "/excel/material-ledger/jobs");
  assert.strictEqual(jobPosts3.length, 3);
  assert.notStrictEqual(
    jobPosts3[2].body.clientJobId,
    unconfirmedId,
    "New generation after completed task must produce a new clientJobId"
  );
}

// ==========================================
// Test 5: Validation Failure Preserves Active Result
// ==========================================
async function testValidationFailurePreservesActiveResult() {
  const h = createBaseTestContext();
  const runFormula = vm.runInNewContext(
    `(${functionSource("runExcelFormulaAction")})`,
    h.ctx
  );

  // Set existing active formula result in DOM and state
  h.state.formulaResult = { primaryFormula: "=SUM(A1:A10)", explanation: "原求和公式" };
  h.byId("result-output").textContent = "=SUM(A1:A10) 原求和公式";

  // Requirement is empty -> validation fails
  h.byId("excel-formula-requirement").value = "";
  h.state.formulaMode = "generate";

  runFormula();

  // Status must show error
  assert.strictEqual(h.state.statusMessage, "请填写计算需求。");
  // Active result must NOT be cleared or replaced with placeholder
  assert.strictEqual(
    h.byId("result-output").textContent,
    "=SUM(A1:A10) 原求和公式",
    "Validation failure must preserve existing active result in DOM"
  );
  assert.strictEqual(
    helpers.isTaskSlotBusy(h.state.activeTaskSlots, "et", "excel.formula_assistant", "doc_session_1"),
    false,
    "Slot must not remain busy after validation failure"
  );

  // Now fill requirement and run valid submission
  h.byId("excel-formula-requirement").value = "求平均值";
  runFormula();

  // On valid submission, progress is displayed and old result exits
  assert.strictEqual(
    h.byId("result-output").textContent,
    "公式助手正在读取明确选区，不会读取工作表已用范围。",
    "Valid submission must immediately clear old result and show extraction progress"
  );

  // Execute extraction callback
  await h.timeouts[h.timeouts.length - 1].fn();
  assert.strictEqual(
    h.byId("result-output").textContent,
    "正在等待推荐公式。",
    "After extraction, active output must show submit waiting progress"
  );
}

// ==========================================
// Test 6: Material Ledger Result Display, Failure Isolation & Late Response Dropping
// ==========================================
async function testMaterialLedgerIsolationAndLateResponse() {
  const h = createBaseTestContext();
  h.state.currentMode = "excelLedger";

  const renderView = vm.runInNewContext(
    `(${functionSource("renderMaterialLedgerView")})`,
    h.ctx
  );

  // 1. Initial successful result renders table and hides markdownOutput
  renderView({
    busy: false,
    status: "idle",
    result: { rows: [{ values: { "工作事项": "完成" } }] }
  });
  assert.strictEqual(h.byId("excel-ledger-result").hidden, false);
  assert.strictEqual(h.byId("result-output").hidden, true);

  // 2. Starting new task: result becomes null, busy becomes true
  renderView({
    busy: true,
    status: "running",
    phaseLabel: "正在分析资料并建立索引...",
    result: null,
    error: ""
  });
  assert.strictEqual(
    h.byId("excel-ledger-result").hidden,
    true,
    "excel-ledger-result must be hidden when result is null during new task execution"
  );
  assert.strictEqual(
    h.byId("result-output").hidden,
    false,
    "result-output must be shown when result is null during new task execution"
  );
  assert.strictEqual(
    h.byId("result-output").textContent,
    "正在分析资料并建立索引...",
    "result-output must display current progress when running"
  );

  // 3. Task failure: result is null, error is present
  renderView({
    busy: false,
    status: "failed",
    phaseLabel: "",
    result: null,
    error: "提取资料超时"
  });
  assert.strictEqual(h.byId("excel-ledger-result").hidden, true);
  assert.strictEqual(h.byId("result-output").hidden, false);
  assert.strictEqual(
    h.byId("result-output").textContent,
    "提取资料超时",
    "result-output must display error message on failure"
  );

}

// ==========================================
// Test 7: Source Contract Invariants
// ==========================================
function testSourceContractInvariants() {
  // 1. runExcelAnalysisAction must call claimTaskSlot before setTimeout
  const analysisFn = functionSource("runExcelAnalysisAction");
  const setTimeoutIdx = analysisFn.indexOf("setTimeout(");
  const claimIdx = analysisFn.indexOf("claimTaskSlot");
  assert.ok(setTimeoutIdx > 0, "runExcelAnalysisAction must contain setTimeout");
  assert.ok(claimIdx > 0, "runExcelAnalysisAction must contain claimTaskSlot");
  assert.ok(
    claimIdx < setTimeoutIdx,
    "runExcelAnalysisAction must claim task slot synchronously BEFORE setTimeout"
  );

  // 2. runExcelFormulaAction must call claimTaskSlot before setTimeout
  const formulaFn = functionSource("runExcelFormulaAction");
  const formulaSetTimeoutIdx = formulaFn.indexOf("setTimeout(");
  const formulaClaimIdx = formulaFn.indexOf("claimTaskSlot");
  assert.ok(formulaSetTimeoutIdx > 0, "runExcelFormulaAction must contain setTimeout");
  assert.ok(formulaClaimIdx > 0, "runExcelFormulaAction must contain claimTaskSlot");
  assert.ok(
    formulaClaimIdx < formulaSetTimeoutIdx,
    "runExcelFormulaAction must claim task slot synchronously BEFORE setTimeout"
  );

  // 3. runExcelFormulaAction must NOT call setPlainResult on missing requirement validation failure
  const missingReqSection = formulaFn.slice(
    formulaFn.indexOf('if (state.formulaMode === "generate" && !state.formulaRequirement)'),
    formulaFn.indexOf('setStatus("正在校验公式上下文...')
  );
  assert.ok(
    !missingReqSection.includes("setPlainResult("),
    "Missing requirement validation failure must NOT call setPlainResult to overwrite active result"
  );

  // 4. renderMaterialLedgerView must update result-output when result is null
  const renderLedgerFn = functionSource("renderMaterialLedgerView");
  assert.ok(
    renderLedgerFn.includes("markdownOutput.textContent = view.error") ||
    renderLedgerFn.includes("markdownOutput.textContent ="),
    "renderMaterialLedgerView must populate markdownOutput with progress or error when result is empty"
  );

  // 5. material-ledger.js must guard POST response against mismatched clientJobId
  assert.ok(
    materialLedgerSource.includes("s.clientJobId !== payload.clientJobId"),
    "material-ledger.js must guard POST response with clientJobId check"
  );
}

test("active task slots are isolated by task and session", testActiveTaskSlotGuard);
test("rapid consecutive clicks submit only once", testConsecutiveClickGuarding);
test("identical input generates a new task after completion", testRegenerateCreatesNewJobEvenWithIdenticalInput);
test("an unconfirmed submission retry reuses the original task", testNetworkRetryVsRegenerate);
test("local validation failure preserves the active result", testValidationFailurePreservesActiveResult);
test("ledger progress and errors replace the old result", testMaterialLedgerIsolationAndLateResponse);
test("existing source contract invariants", testSourceContractInvariants);

for (const task of [
  { name: "analysis", type: "excel.analysis", action: "runExcelAnalysisAction", mode: "excelAnalysis" },
  { name: "formula", type: "excel.formula_assistant", action: "runExcelFormulaAction", mode: "excelFormulaAssistant" }
]) {
  for (const change of ["mode", "workbook"]) {
    test(`${task.name} releases its slot when ${change} changes before extraction`, () => {
      const h = createBaseTestContext({ state: { currentMode: task.mode } });
      h.ctx.getCurrentExcelDocumentSession = () => h.ctx.defaultWorkbook.__ai_wps_doc_session__;
      h.ctx.isExcelTaskVisible = vm.runInNewContext(`(${functionSource("isExcelTaskVisible")})`, h.ctx);
      h.byId("excel-formula-requirement").value = "计算总额";
      const run = vm.runInNewContext(`(${functionSource(task.action)})`, h.ctx);
      run();
      assert.strictEqual(helpers.isTaskSlotBusy(h.state.activeTaskSlots, "et", task.type, "doc_session_1"), true);
      if (change === "mode") h.state.currentMode = "settings";
      else h.ctx.defaultWorkbook.__ai_wps_doc_session__ = "doc_session_2";
      helpers.claimTaskSlot(h.state.activeTaskSlots, "et", task.type, "doc_session_2", "other-job");
      h.timeouts[0].fn();
      assert.strictEqual(h.requests.length, 0, "an abandoned extraction must not submit");
      assert.strictEqual(helpers.isTaskSlotBusy(h.state.activeTaskSlots, "et", task.type, "doc_session_1"), false);
      assert.strictEqual(helpers.isTaskSlotBusy(h.state.activeTaskSlots, "et", task.type, "doc_session_2"), true);
      h.state.currentMode = task.mode;
      h.ctx.defaultWorkbook.__ai_wps_doc_session__ = "doc_session_1";
      run();
      assert.strictEqual(h.timeouts.length, 2, "returning to the task must allow another generation");
    });
  }
}

for (const response of ["running", "completed", "error"]) {
  test(`a late ledger POST ${response} cannot replace confirmed cancellation`, { timeout: 2000 }, async () => {
    const context = { window: {}, console, setTimeout, clearTimeout };
    vm.runInNewContext(materialLedgerSource, context);
    let settlePost;
    let markPostStarted;
    const postStarted = new Promise(resolve => { markPostStarted = resolve; });
    const scheduled = [];
    const ledger = context.createMaterialLedger({
      getSessionId: () => "sess-late",
      schedule: fn => { scheduled.push(fn); },
      request: (url, body) => {
        if (url === "/excel/material-ledger/jobs") {
          return new Promise((resolve, reject) => {
            settlePost = () => {
              if (response === "error") reject(new Error("迟到的网络错误"));
              else resolve({ data: { jobId: body.clientJobId, status: response,
                result: { rows: [{ values: { "工作事项": "旧任务结果" } }] } } });
            };
            markPostStarted();
          });
        }
        if (url.endsWith("/cancel")) return Promise.resolve({ data: { status: "cancelled" } });
        return Promise.resolve({ data: { conflicts: [] } });
      }
    });
    const pending = ledger.generate();
    await postStarted;
    await ledger.cancel();
    assert.strictEqual(ledger.getState().status, "cancelled");
    settlePost();
    await pending;
    assert.strictEqual(ledger.getState().status, "cancelled");
    assert.strictEqual(ledger.getState().busy, false);
    assert.strictEqual(ledger.getState().result, null);
    assert.strictEqual(ledger.getState().error, "");
    assert.strictEqual(scheduled.length, 0, "late submission must not restart polling");
  });
}

function createExcelResultRenderContext(mode) {
  const h = createBaseTestContext({ state: { currentMode: mode, resultViewMode: "preview" } });
  h.ctx.saveCurrentSmartFillSessionState = () => {};
  for (const name of [
    "setResult", "setPlainResult", "normalizeReportList", "buildExcelAnalysisMarkdown",
    "updateResultViewButtons", "setExcelResultViewSwitchForMode", "setResultViewMode",
    "renderExcelAnalysisResult", "buildExcelFormulaMarkdown", "renderExcelFormulaResult",
    "smartFillResultAddress", "buildExcelSmartFillMarkdown", "buildExcelSmartFillCopyText",
    "renderExcelSmartFillResult", "renderMaterialLedgerView"
  ]) {
    vm.runInNewContext(functionSource(name), h.ctx);
  }
  return h;
}

for (const task of [
  { mode: "excelAnalysis", render: "renderExcelAnalysisResult", result: text => ({ structuredReport: { overview: text }, plainText: text }) },
  { mode: "excelFormulaAssistant", render: "renderExcelFormulaResult", result: text => ({ primaryFormula: "=SUM(A1:A2)", explanation: text }) },
  { mode: "excelSmartFill", render: "renderExcelSmartFillResult", result: text => ({ items: [{ itemId: "row-1", value: text, status: "completed" }] }) }
]) {
  test(`${task.mode} renders the next result and copy text without switching tabs`, () => {
    const h = createExcelResultRenderContext(task.mode);
    const output = h.byId("result-output");
    h.ctx[task.render](task.result("旧任务甲"));
    assert.match(output.innerHTML, /旧任务甲/);
    h.ctx.setPlainResult("正在等待新任务");
    h.ctx[task.render](task.result("新任务乙"));
    assert.match(output.innerHTML, /新任务乙/);
    assert.doesNotMatch(output.innerHTML, /旧任务甲/);
    assert.match(h.state.copyText, /新任务乙/);
    assert.doesNotMatch(h.state.copyText, /旧任务甲/);
    assert.strictEqual(output.hidden, false);
    assert.strictEqual(output.classList.contains("plain-output"), false);
  });
}

test("ledger replaces the previous table and copied text after the next task", { timeout: 2000 }, async () => {
  const h = createExcelResultRenderContext("excelLedger");
  const makeNode = () => ({
    children: [],
    appendChild(child) { this.children.push(child); },
    addEventListener() {},
    set innerHTML(value) { this.html = value; this.children = []; },
    get innerHTML() { return this.html || ""; }
  });
  const originalById = h.ctx.byId;
  h.ctx.byId = id => {
    const element = originalById(id);
    element.appendChild = element.appendChild || (() => {});
    return element;
  };
  h.ctx.document.createElement = makeNode;
  h.ctx.document.createTextNode = text => ({ textContent: text });
  const head = makeNode();
  const body = makeNode();
  h.byId("ledger-preview-table").querySelector = selector => selector === "tbody" ? body : head;
  const ledgerContext = { window: {} };
  vm.runInNewContext(materialLedgerSource, ledgerContext);
  let resolveJob;
  let copied = "";
  let markSubmitted;
  const submitted = new Promise(resolve => { markSubmitted = resolve; });
  const result = text => ({ headers: ["工作事项"], rows: [{ values: { "工作事项": text } }] });
  const ledger = ledgerContext.createMaterialLedger({
    render: h.ctx.renderMaterialLedgerView,
    copyText: text => { copied = text; },
    request: (url, payload) => {
      if (url !== "/excel/material-ledger/jobs") return Promise.resolve({ data: { conflicts: [] } });
      markSubmitted();
      return new Promise(resolve => { resolveJob = () => resolve({ data: {
        jobId: payload.clientJobId, status: "completed", result: result("新任务乙")
      } }); });
    }
  });
  ledger.setResult(result("旧任务甲"));
  assert.match(body.children[0].innerHTML, /旧任务甲/);
  ledger.copyTsv();
  assert.match(copied, /旧任务甲/);
  const pending = ledger.generate();
  await submitted;
  assert.strictEqual(h.byId("excel-ledger-result").hidden, true);
  resolveJob();
  await pending;
  assert.strictEqual(body.children.length, 1);
  assert.match(body.children[0].innerHTML, /新任务乙/);
  assert.doesNotMatch(body.children[0].innerHTML, /旧任务甲/);
  assert.strictEqual(h.byId("excel-ledger-result").hidden, false);
  assert.strictEqual(ledger.copyTsv(), true);
  assert.match(copied, /新任务乙/);
  assert.doesNotMatch(copied, /旧任务甲/);
});
