const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { etRoot: root } = require("./support/plugin-roots");

const helpers = require(path.join(root, "taskpane-helpers.js"));
const taskpaneSource = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const taskpaneHtml = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");

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
    excelAnalysisJobId: "",
    excelFormulaJobId: "",
    excelSmartFillJobId: "",
    formulaMode: "generate",
    historyOpen: false,
    historyUnreadCount: 0,
    historyItems: [],
    ...(initialOverrides.state || {})
  };

  const requests = [];
  const ctx = {
    state,
    byId,
    document: {
      body: {
        attributes: {},
        setAttribute: function(attr, val) { this.attributes[attr] = val; },
        getAttribute: function(attr) { return this.attributes[attr]; }
      },
      querySelector: function() { return null; },
      visibilityState: "visible"
    },
    window: {
      localStorage: {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {}
      }
    },
    helpers,
    requests,
    request: (url, body, options) => {
      requests.push({ url, body, options });
      return Promise.resolve({ success: true, data: { jobId: "job-default", status: "completed" } });
    },
    setStatus: (msg) => { state.statusMessage = msg; },
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
    buildExcelAnalysisClientJobId: () => "ana_job_test_001",
    buildExcelFormulaClientJobId: () => "form_job_test_001",
    clearExcelAnalysisActiveJob: () => {},
    saveExcelAnalysisActiveJob: () => {},
    clearExcelFormulaActiveJob: () => {},
    saveExcelFormulaActiveJob: () => {},
    setAnalysisBusy: (busy) => { state.busy = busy; },
    setInterruptedRetryVisible: () => {},
    setExcelAnalysisCancelVisible: () => {},
    setFormulaInterruptedRetryVisible: () => {},
    setExcelFormulaCancelVisible: () => {},
    setScopeLine: () => {},
    summarizeExcelPayload: () => "数据范围: A1:C10",
    summarizeExcelFormulaPayload: () => "选区范围: B2:B10",
    startExcelAnalysisWaitFeedback: () => () => {},
    startExcelFormulaWaitFeedback: () => () => {},
    describeExcelAnalysisPollError: (err) => err.message || "error",
    describeExcelFormulaPollError: (err) => err.message || "error",
    isFatalExcelAnalysisPollError: () => true,
    isFatalExcelFormulaPollError: () => true,
    getFormulaModeUi: () => ({
      actionLabel: "生成公式",
      submitStatus: "正在提交公式请求...",
      submitResult: "正在生成推荐公式。"
    }),
    getExcelFormulaCompletionStatus: () => "公式已生成。",
    setTrace: () => {},
    refreshDiagnostics: () => Promise.resolve(),
    EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS: 30000,
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
    EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    FRONTEND_BUILD_VERSION: "1.0.0",
    setTimeout: global.setTimeout,
    clearTimeout: global.clearTimeout,
    defaultWorkbook: {
      Name: "工作簿1.xlsx",
      FullName: "/path/工作簿1.xlsx",
      __ai_wps_doc_session__: state.documentSessionId
    },
    getEtApplication: function() {
      return { ActiveWorkbook: ctx.defaultWorkbook };
    },
    getActiveWorkbook: function(app) {
      return (app && app.ActiveWorkbook) || ctx.defaultWorkbook;
    },
    ...(initialOverrides.context || {})
  };

  return ctx;
}

test("Helper: renderExcelAnalysisHistoryList renders analysis cards with read-only buttons", () => {
  assert.strictEqual(
    typeof helpers.renderExcelAnalysisHistoryList,
    "function",
    "renderExcelAnalysisHistoryList must be exported"
  );

  const emptyHtml = helpers.renderExcelAnalysisHistoryList([]);
  assert.ok(emptyHtml.includes("暂无成功历史记录"), "empty message must be returned");

  const items = [
    {
      id: "hist_ana_001",
      taskType: "excel.analysis",
      documentDisplayName: "财务月报.xlsx",
      completedAt: "2026-09-12T10:00:00Z",
      result: {
        structuredReport: {
          overview: "总体营收增长15%",
          findings: ["发现1", "发现2"],
          risks: ["风险1"],
          actions: ["行动1"]
        },
        plainText: "总体营收增长15%，详见各项指标分析。"
      }
    }
  ];

  const html = helpers.renderExcelAnalysisHistoryList(items);
  assert.ok(html.includes("hist_ana_001"), "card must contain history ID");
  assert.ok(html.includes("财务月报.xlsx"), "card must contain document display name");
  assert.ok(html.includes("总体营收增长15%"), "card must contain snippet of overview or text");
  assert.ok(html.includes("btn-history-view"), "card must have view button");
  assert.ok(html.includes("btn-history-copy"), "card must have copy button");
  assert.ok(html.includes("btn-history-delete"), "card must have delete button");
  assert.ok(!html.includes("写入"), "history card must NOT have writeback capability");
});

test("Helper: renderExcelFormulaHistoryList renders formula cards with read-only buttons", () => {
  assert.strictEqual(
    typeof helpers.renderExcelFormulaHistoryList,
    "function",
    "renderExcelFormulaHistoryList must be exported"
  );

  const emptyHtml = helpers.renderExcelFormulaHistoryList([]);
  assert.ok(emptyHtml.includes("暂无成功历史记录"), "empty message must be returned");

  const items = [
    {
      id: "hist_form_001",
      taskType: "excel.formula_assistant",
      documentDisplayName: "销售统计.xlsx",
      completedAt: "2026-09-12T10:05:00Z",
      result: {
        mode: "generate",
        primaryFormula: "=SUM(C2:C20)",
        explanation: "计算C2到C20总和"
      }
    }
  ];

  const html = helpers.renderExcelFormulaHistoryList(items);
  assert.ok(html.includes("hist_form_001"), "card must contain history ID");
  assert.ok(html.includes("销售统计.xlsx"), "card must contain document display name");
  assert.ok(html.includes("=SUM(C2:C20)"), "card must contain formula");
  assert.ok(html.includes("btn-history-view"), "card must have view button");
  assert.ok(html.includes("btn-history-copy"), "card must have copy button");
  assert.ok(html.includes("btn-history-delete"), "card must have delete button");
  assert.ok(!html.includes("写入"), "formula history must NOT have writeback capability");
});

test("Behavioral: Analysis validation failure preserves active result", (t, done) => {
  const ctx = createBaseTestContext();
  ctx.state.analysisResult = {
    structuredReport: { overview: "保留的旧分析结果" },
    plainText: "旧分析结果文本"
  };
  ctx.byId("excel-analysis-requirement").value = "分析趋势";
  ctx.extractExcelRange = () => {
    throw new Error("选区为空，请选择包含数据的单元格区域");
  };

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelAnalysisAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelAnalysisAction();", sandbox);

  setTimeout(() => {
    assert.ok(ctx.state.analysisResult !== null, "analysisResult must NOT be wiped on validation failure");
    assert.strictEqual(
      ctx.state.analysisResult.structuredReport.overview,
      "保留的旧分析结果",
      "old analysisResult must be preserved on validation error"
    );
    assert.ok(ctx.state.statusMessage.includes("选区为空"), "status must reflect validation error");
    done();
  }, 10);
});

test("Behavioral: Analysis valid submission immediately clears old result and claims slot", (t, done) => {
  const ctx = createBaseTestContext();
  ctx.state.analysisResult = {
    structuredReport: { overview: "旧分析结果" }
  };
  ctx.byId("excel-analysis-requirement").value = "分析利润";
  ctx.extractExcelRange = () => ({
    scope: { sheetName: "Sheet1" },
    table: { headers: ["A"], rows: [["1"]] }
  });

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelAnalysisAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelAnalysisAction();", sandbox);

  setTimeout(() => {
    assert.strictEqual(ctx.state.analysisResult, null, "analysisResult must be cleared on valid submission");
    assert.strictEqual(
      helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", ctx.state.documentSessionId),
      true,
      "active task slot must be claimed"
    );
    done();
  }, 10);
});

test("Behavioral: Analysis slot busy blocks duplicate submission", () => {
  const ctx = createBaseTestContext();
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.analysis", ctx.state.documentSessionId, "job_running_01");

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelAnalysisAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelAnalysisAction();", sandbox);

  assert.ok(ctx.state.statusMessage.includes("已存在进行中的智能分析任务"), "must block duplicate submission");
});

test("Behavioral: Formula validation failure preserves active result", (t, done) => {
  const ctx = createBaseTestContext({
    state: { currentMode: "excelFormulaAssistant", formulaMode: "generate" }
  });
  ctx.state.formulaResult = {
    primaryFormula: "=AVERAGE(A1:A10)",
    explanation: "旧公式结果"
  };
  ctx.byId("excel-formula-requirement").value = ""; // Empty requirement in generate mode -> validation error

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelFormulaAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelFormulaAction();", sandbox);

  setTimeout(() => {
    assert.ok(ctx.state.formulaResult !== null, "formulaResult must NOT be wiped on validation failure");
    assert.strictEqual(ctx.state.formulaResult.primaryFormula, "=AVERAGE(A1:A10)");
    assert.ok(ctx.state.statusMessage.includes("请填写计算需求"), "status must reflect requirement error");
    done();
  }, 10);
});

test("Behavioral: Formula valid submission immediately clears old result and claims slot", (t, done) => {
  const ctx = createBaseTestContext({
    state: { currentMode: "excelFormulaAssistant", formulaMode: "generate" }
  });
  ctx.state.formulaResult = {
    primaryFormula: "=AVERAGE(A1:A10)"
  };
  ctx.byId("excel-formula-requirement").value = "计算合计";
  ctx.extractExcelFormulaRange = () => ({
    selection: { address: "B2:B10" }
  });

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelFormulaAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelFormulaAction();", sandbox);

  setTimeout(() => {
    assert.strictEqual(ctx.state.formulaResult, null, "formulaResult must be cleared on valid submission");
    assert.strictEqual(
      helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.formula_assistant", ctx.state.documentSessionId),
      true,
      "formula assistant task slot must be claimed"
    );
    done();
  }, 10);
});

test("Behavioral: Formula slot busy blocks duplicate submission", () => {
  const ctx = createBaseTestContext({
    state: { currentMode: "excelFormulaAssistant" }
  });
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.formula_assistant", ctx.state.documentSessionId, "job_running_02");

  const sandbox = vm.createContext(ctx);
  const actionCode = functionSource("runExcelFormulaAction");
  vm.runInContext(actionCode, sandbox);

  vm.runInContext("runExcelFormulaAction();", sandbox);

  assert.ok(ctx.state.statusMessage.includes("已存在进行中的公式助手任务"), "must block duplicate formula submission");
});

test("Behavioral: switchMode isolates active results across task modes", () => {
  const ctx = createBaseTestContext();
  ctx.state.activeAnalysisResultsBySession = {
    doc_session_1: { structuredReport: { overview: "分析成果1" } }
  };
  ctx.state.activeFormulaResultsBySession = {
    doc_session_1: { primaryFormula: "=SUM(A1:A5)" }
  };
  ctx.state.activeSmartFillResultsBySession = {
    doc_session_1: { items: [{ itemId: "1", value: "填项1" }] }
  };

  const sandbox = vm.createContext(ctx);
  const switchModeCode = functionSource("switchMode");
  const switchViewCode = functionSource("switchView");
  const syncSettingsRefreshControllerCode = functionSource("syncSettingsRefreshController");
  const isSettingsRefreshEligibleCode = functionSource("isSettingsRefreshEligible");
  const invalidateConfigRefreshCode = functionSource("invalidateConfigRefresh");

  vm.runInContext([
    syncSettingsRefreshControllerCode,
    isSettingsRefreshEligibleCode,
    invalidateConfigRefreshCode,
    switchViewCode,
    "function closeTaskModelConfigMenu() {}",
    "function setExcelResultViewSwitchForMode() {}",
    "function renderWorkflowProfileStrip() {}",
    "function renderWorkflowProfileManager() {}",
    "function renderWorkflowTaskTabs() {}",
    "function renderSmartFillCaptureState() {}",
    "function setSmartFillWriteButtonState() {}",
    "function resumeExcelFormulaActiveJob() {}",
    "function resumeExcelSmartFillActiveJob() {}",
    "function resumeExcelAnalysisActiveJob() {}",
    "function renderExcelAnalysisResult(res) { state.analysisResult = res; }",
    "function renderExcelFormulaResult(res) { state.formulaResult = res; }",
    "function renderExcelSmartFillResult(res) { state.smartFillResult = res; }",
    "function loadAndRenderSmartFillHistory() {}",
    "function loadWorkflowProfiles() {}",
    "function syncScopeWatcher() {}",
    "function updateHistoryBadge() {}",
    "function switchHistoryView() {}",
    "function setFormulaAssistantMode() {}",
    "function refreshConfig() {}",
    "function syncActiveTaskBusyUi() {}",
    "function rerenderExcelSmartFillPreview() {}",
    "function tryRebindSmartFillTarget() {}",
    functionSource("syncActiveSessionView"),
    switchModeCode
  ].join("\n"), sandbox);

  // 1. Switch to excelAnalysis: btn-view-history must be visible, mode is excelAnalysis, analysisResult restored
  vm.runInContext("switchMode('excelAnalysis');", sandbox);
  assert.strictEqual(ctx.state.currentMode, "excelAnalysis");
  assert.strictEqual(ctx.byId("btn-view-history").hidden, false, "history button must be visible in analysis mode");
  assert.ok(ctx.state.analysisResult !== null, "analysisResult must be restored from session");
  assert.strictEqual(ctx.state.analysisResult.structuredReport.overview, "分析成果1");

  // 2. Switch to excelFormulaAssistant: btn-view-history must be visible, formulaResult restored
  vm.runInContext("switchMode('excelFormulaAssistant');", sandbox);
  assert.strictEqual(ctx.state.currentMode, "excelFormulaAssistant");
  assert.strictEqual(ctx.byId("btn-view-history").hidden, false, "history button must be visible in formula mode");
  assert.ok(ctx.state.formulaResult !== null, "formulaResult must be restored from session");
  assert.strictEqual(ctx.state.formulaResult.primaryFormula, "=SUM(A1:A5)");

  // 3. Switch to excelSmartFill: btn-view-history must be visible, smartFillResult restored
  vm.runInContext("switchMode('excelSmartFill');", sandbox);
  assert.strictEqual(ctx.state.currentMode, "excelSmartFill");
  assert.strictEqual(ctx.byId("btn-view-history").hidden, false, "history button must be visible in smart fill mode");
  assert.ok(ctx.state.smartFillResult !== null, "smartFillResult must be restored from session");
  assert.strictEqual(ctx.state.smartFillResult.items[0].value, "填项1");

  // 4. Switch to settings: btn-view-history must be hidden
  vm.runInContext("switchMode('settings');", sandbox);
  assert.strictEqual(ctx.state.currentMode, "settings");
  assert.strictEqual(ctx.byId("btn-view-history").hidden, true, "history button must be hidden in settings");
});

test("Behavioral: resume completed analysis job clears storage and leaves UI clean", async () => {
  let clearedJob = null;
  const mockStorage = {};
  const currentSession = "doc_session_1";

  const ctx = createBaseTestContext({
    context: {
      window: {
        localStorage: {
          getItem: (k) => mockStorage[k] || null,
          setItem: (k, v) => { mockStorage[k] = String(v); },
          removeItem: (k) => { delete mockStorage[k]; }
        }
      },
      EXCEL_ANALYSIS_ACTIVE_JOB_STORAGE_KEY: "wps_ai_excel_analysis_active_job",
      request: () => Promise.resolve({
        success: true,
        data: {
          jobId: "job-completed-ana-01",
          status: "completed",
          result: { structuredReport: { overview: "已完成的历史分析结果" } }
        }
      }),
      pollExcelAnalysisJob: () => {
        assert.fail("Must not poll completed job");
      }
    }
  });

  const sandbox = vm.createContext(ctx);
  const getStorageKeyCode = functionSource("getExcelAnalysisActiveJobStorageKey");
  const saveCode = functionSource("saveExcelAnalysisActiveJob");
  const loadCode = functionSource("loadExcelAnalysisActiveJob");
  const clearCode = functionSource("clearExcelAnalysisActiveJob");
  const resumeCode = functionSource("resumeExcelAnalysisActiveJob");

  vm.runInContext([getStorageKeyCode, saveCode, loadCode, clearCode, resumeCode].join("\n"), sandbox);

  // Store a completed job in storage
  mockStorage["wps_ai_excel_analysis_active_job_" + encodeURIComponent(currentSession)] = JSON.stringify({
    jobId: "job-completed-ana-01",
    documentSessionId: currentSession,
    host: "et",
    taskType: "excel.analysis"
  });

  await vm.runInContext("resumeExcelAnalysisActiveJob();", sandbox);

  // Must clear active storage
  assert.strictEqual(
    mockStorage["wps_ai_excel_analysis_active_job_" + encodeURIComponent(currentSession)],
    undefined,
    "completed job must be cleared from storage"
  );
  // Must NOT set active analysis result in state
  assert.strictEqual(ctx.state.analysisResult, null, "analysisResult must remain null");
  assert.strictEqual(ctx.state.excelAnalysisJobId, "", "excelAnalysisJobId must remain empty");
});

test("Behavioral: resume completed formula job clears storage and leaves UI clean", async () => {
  const mockStorage = {};
  const currentSession = "doc_session_1";

  const ctx = createBaseTestContext({
    state: { currentMode: "excelFormulaAssistant" },
    context: {
      window: {
        localStorage: {
          getItem: (k) => mockStorage[k] || null,
          setItem: (k, v) => { mockStorage[k] = String(v); },
          removeItem: (k) => { delete mockStorage[k]; }
        }
      },
      EXCEL_FORMULA_ACTIVE_JOB_STORAGE_KEY: "wps_ai_excel_formula_active_job",
      request: () => Promise.resolve({
        success: true,
        data: {
          jobId: "job-completed-form-01",
          status: "completed",
          result: { primaryFormula: "=SUM(A1:A10)", mode: "generate" }
        }
      }),
      pollExcelFormulaJob: () => {
        assert.fail("Must not poll completed job");
      }
    }
  });

  const sandbox = vm.createContext(ctx);
  const getStorageKeyCode = functionSource("getExcelFormulaActiveJobStorageKey");
  const saveCode = functionSource("saveExcelFormulaActiveJob");
  const loadCode = functionSource("loadExcelFormulaActiveJob");
  const clearCode = functionSource("clearExcelFormulaActiveJob");
  const resumeCode = functionSource("resumeExcelFormulaActiveJob");

  vm.runInContext([getStorageKeyCode, saveCode, loadCode, clearCode, resumeCode].join("\n"), sandbox);

  mockStorage["wps_ai_excel_formula_active_job_" + encodeURIComponent(currentSession)] = JSON.stringify({
    jobId: "job-completed-form-01",
    documentSessionId: currentSession,
    host: "et",
    taskType: "excel.formula_assistant"
  });

  await vm.runInContext("resumeExcelFormulaActiveJob();", sandbox);

  assert.strictEqual(
    mockStorage["wps_ai_excel_formula_active_job_" + encodeURIComponent(currentSession)],
    undefined,
    "completed job must be cleared from storage"
  );
  assert.strictEqual(ctx.state.formulaResult, null, "formulaResult must remain null");
  assert.strictEqual(ctx.state.excelFormulaJobId, "", "excelFormulaJobId must remain empty");
});

test("Behavioral: History copy copies formula / analysis content", () => {
  let copiedText = "";
  const ctx = createBaseTestContext({
    state: {
      historyItems: [
        {
          id: "h_ana_1",
          taskType: "excel.analysis",
          result: {
            structuredReport: { overview: "分析总体稳步增长" },
            plainText: "分析总体稳步增长，详见各项报表。"
          }
        },
        {
          id: "h_form_1",
          taskType: "excel.formula_assistant",
          result: {
            primaryFormula: "=AVERAGE(B2:B20)",
            copyText: "=AVERAGE(B2:B20)"
          }
        }
      ]
    },
    context: {
      navigator: {
        clipboard: {
          writeText: (t) => { copiedText = t; return Promise.resolve(); }
        }
      },
      getCurrentWorkflowTaskType: () => "excel.analysis"
    }
  });

  const sandbox = vm.createContext(ctx);
  const getCurrentWorkflowTaskTypeCode = functionSource("getCurrentWorkflowTaskType");
  const copyItemCode = functionSource("handleSmartFillHistoryCopyItem");
  vm.runInContext([getCurrentWorkflowTaskTypeCode, copyItemCode].join("\n"), sandbox);

  // 1. Copy analysis item
  vm.runInContext("handleSmartFillHistoryCopyItem('h_ana_1');", sandbox);
  assert.ok(copiedText.includes("分析总体稳步增长"), "must copy analysis report text");

  // 2. Copy formula item
  vm.runInContext("handleSmartFillHistoryCopyItem('h_form_1');", sandbox);
  assert.strictEqual(copiedText, "=AVERAGE(B2:B20)", "must copy primary formula");
});

test("Behavioral: Clear history sends DELETE request for current task type", (t, done) => {
  const ctx = createBaseTestContext({
    state: { currentMode: "excelAnalysis" }
  });

  const sandbox = vm.createContext(ctx);
  const getCurrentWorkflowTaskTypeCode = functionSource("getCurrentWorkflowTaskType");
  const renderCurrentTaskHistoryListCode = functionSource("renderCurrentTaskHistoryList");
  const clearHistoryCode = functionSource("handleClearSmartFillHistory");

  vm.runInContext([getCurrentWorkflowTaskTypeCode, renderCurrentTaskHistoryListCode, clearHistoryCode].join("\n"), sandbox);

  vm.runInContext("handleClearSmartFillHistory();", sandbox);

  setTimeout(() => {
    assert.strictEqual(ctx.requests.length, 1);
    assert.strictEqual(ctx.requests[0].url, "/history?taskType=excel.analysis");
    assert.strictEqual(ctx.requests[0].options.method, "DELETE");
    done();
  }, 10);
});

test("Behavioral: Smart Fill draft, exclusions, and locked status preserved across mode switches", () => {
  const ctx = createBaseTestContext();
  const session = "doc_session_smart_fill";
  ctx.state.documentSessionId = session;
  ctx.state.smartFillResult = {
    items: [
      { itemId: "item-1", status: "completed", value: "值1" },
      { itemId: "item-2", status: "completed", value: "值2" }
    ]
  };
  ctx.state.smartFillPreview = {
    consumed: false,
    status: "ready"
  };
  ctx.state.smartFillDraftItems = [
    { itemId: "item-1", status: "completed", value: "用户修改的值1", selected: true },
    { itemId: "item-2", status: "completed", value: "值2", selected: false }
  ];
  ctx.state.smartFillItems = [{ itemId: "item-1" }, { itemId: "item-2" }];

  const sandbox = vm.createContext(ctx);
  const saveStateCode = functionSource("saveCurrentSmartFillSessionState");
  const syncActiveSessionViewCode = functionSource("syncActiveSessionView");

  vm.runInContext([
    saveStateCode,
    syncActiveSessionViewCode,
    "function rerenderExcelSmartFillPreview() {}",
    "function setExcelResultViewSwitchForMode() {}",
    "function tryRebindSmartFillTarget() {}",
    "function setSmartFillWriteButtonState() {}",
    "function resumeExcelSmartFillActiveJob() {}",
    "function syncActiveTaskBusyUi() {}"
  ].join("\n"), sandbox);

  // 1. Save state
  vm.runInContext("saveCurrentSmartFillSessionState('doc_session_smart_fill');", sandbox);
  assert.ok(ctx.state.activeSmartFillStatesBySession["doc_session_smart_fill"]);
  assert.strictEqual(ctx.state.activeSmartFillStatesBySession["doc_session_smart_fill"].draftItems[0].value, "用户修改的值1");
  assert.strictEqual(ctx.state.activeSmartFillStatesBySession["doc_session_smart_fill"].draftItems[1].selected, false);

  // 2. User switches to excelAnalysis, changing state.smartFillDraftItems
  ctx.state.currentMode = "excelAnalysis";
  ctx.state.smartFillDraftItems = [];

  // 3. User switches back to excelSmartFill
  ctx.state.currentMode = "excelSmartFill";
  vm.runInContext("syncActiveSessionView('doc_session_smart_fill');", sandbox);

  // Drafts, exclusions, and preview must be restored without reset!
  assert.strictEqual(ctx.state.smartFillDraftItems.length, 2);
  assert.strictEqual(ctx.state.smartFillDraftItems[0].value, "用户修改的值1");
  assert.strictEqual(ctx.state.smartFillDraftItems[1].selected, false);
});

test("Behavioral: finishCancelledExcelAnalysis and finishCancelledExcelFormula release targetDocSession slot", () => {
  const ctx = createBaseTestContext();
  const session = "doc_session_cancel";
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.analysis", session, "job-cancel-ana");
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.formula_assistant", session, "job-cancel-form");
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", session), true);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.formula_assistant", session), true);

  const sandbox = vm.createContext(ctx);
  const finishCancelAnaCode = functionSource("finishCancelledExcelAnalysis");
  const finishCancelFormCode = functionSource("finishCancelledExcelFormula");

  vm.runInContext([
    finishCancelAnaCode,
    finishCancelFormCode,
    "function clearExcelAnalysisActiveJob() {}",
    "function clearExcelFormulaActiveJob() {}",
    "function setExcelAnalysisCancelVisible() {}",
    "function setExcelFormulaCancelVisible() {}"
  ].join("\n"), sandbox);

  // Finish cancel with targetDocSession
  vm.runInContext(`finishCancelledExcelAnalysis("job-cancel-ana", () => {}, "${session}");`, sandbox);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", session), false);

  vm.runInContext(`finishCancelledExcelFormula("job-cancel-form", () => {}, "${session}");`, sandbox);
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.formula_assistant", session), false);
});

test("Behavioral: Async job completion does not overwrite DOM when mode or session changed during run", (t, done) => {
  const ctx = createBaseTestContext();
  const sessionA = "session_A";
  const sessionB = "session_B";

  ctx.state.currentMode = "excelAnalysis";
  ctx.state.documentSessionId = sessionA;
  ctx.state.excelAnalysisJobId = "job_bg_1";

  // Simulate network response resolving with completed result
  ctx.request = (url) => {
    return Promise.resolve({
      traceId: "tr-1",
      data: {
        jobId: "job_bg_1",
        status: "completed",
        result: { plainText: "任务A完成分析" }
      }
    });
  };

  let renderCalled = false;
  ctx.renderExcelAnalysisResult = () => { renderCalled = true; };

  const sandbox = vm.createContext(ctx);
  const pollCode = functionSource("pollExcelAnalysisJob");
  const recordCode = functionSource("recordFinalizedAnalysisResult");
  const updateBadgeCode = functionSource("updateHistoryBadge");

  vm.runInContext([
    updateBadgeCode,
    recordCode,
    pollCode,
    "function clearExcelAnalysisActiveJob() {}",
    "function saveExcelAnalysisActiveJob() {}",
    "function setExcelAnalysisCancelVisible() {}",
    "function setTrace() {}",
    "function setStatus() {}",
    "function refreshDiagnostics() { return Promise.resolve(); }"
  ].join("\n"), sandbox);

  // Before response arrives, user switched to session B and mode excelFormulaAssistant
  ctx.state.documentSessionId = sessionB;
  ctx.state.currentMode = "excelFormulaAssistant";

  // Polling completes for session A
  vm.runInContext(`pollExcelAnalysisJob("job_bg_1", () => {}, "${sessionA}");`, sandbox);

  setTimeout(() => {
    // 1. Result should be stored in session A cache
    assert.ok(ctx.state.activeAnalysisResultsBySession[sessionA]);
    assert.strictEqual(ctx.state.activeAnalysisResultsBySession[sessionA].plainText, "任务A完成分析");

    // 2. DOM rendering MUST NOT have occurred because user switched away!
    assert.strictEqual(renderCalled, false, "renderExcelAnalysisResult must not be called when user switched mode/session");
    done();
  }, 20);
});

test("Behavioral: Out-of-order history responses with mismatched taskType are discarded", (t, done) => {
  const ctx = createBaseTestContext();
  ctx.state.currentMode = "excelAnalysis";
  ctx.state.historyItems = [];

  let resolveAnalysis;
  let resolveFormula;

  ctx.request = (url) => {
    if (url.includes("excel.analysis")) {
      return new Promise((resolve) => { resolveAnalysis = resolve; });
    }
    if (url.includes("excel.formula_assistant")) {
      return new Promise((resolve) => { resolveFormula = resolve; });
    }
    return Promise.resolve({ data: [] });
  };

  const sandbox = vm.createContext(ctx);
  const loadHistoryCode = functionSource("loadAndRenderSmartFillHistory");
  const getCurrentWorkflowTaskTypeCode = functionSource("getCurrentWorkflowTaskType");
  const renderCurrentTaskHistoryListCode = functionSource("renderCurrentTaskHistoryList");

  vm.runInContext([
    getCurrentWorkflowTaskTypeCode,
    renderCurrentTaskHistoryListCode,
    loadHistoryCode
  ].join("\n"), sandbox);

  // 1. User starts on excelAnalysis, request 1 fires
  vm.runInContext("loadAndRenderSmartFillHistory();", sandbox);

  // 2. User quickly switches to excelFormulaAssistant, request 2 fires
  ctx.state.currentMode = "excelFormulaAssistant";
  vm.runInContext("loadAndRenderSmartFillHistory();", sandbox);

  // 3. Request 1 (analysis) resolves late (out-of-order!)
  resolveAnalysis({
    data: [{ id: "h_ana_old", taskType: "excel.analysis" }]
  });

  // 4. Request 2 (formula) resolves
  resolveFormula({
    data: [{ id: "h_form_new", taskType: "excel.formula_assistant" }]
  });

  setTimeout(() => {
    // State historyItems must only contain the latest formula history, not the out-of-order analysis response
    assert.strictEqual(ctx.state.historyItems.length, 1);
    assert.strictEqual(ctx.state.historyItems[0].id, "h_form_new");
    assert.strictEqual(ctx.state.historyItems[0].taskType, "excel.formula_assistant");
    done();
  }, 20);
});

test("Behavioral: Transient network error on resume pre-query does not purge storage", (t, done) => {
  const ctx = createBaseTestContext();
  const session = "doc_session_resume_transient";
  ctx.state.documentSessionId = session;
  ctx.defaultWorkbook.__ai_wps_doc_session__ = session;
  ctx.state.currentMode = "excelAnalysis";

  // Seed storage with active job
  let storageCleared = false;
  ctx.loadExcelAnalysisActiveJob = () => ({
    jobId: "job_resume_active",
    startedAt: Date.now(),
    documentSessionId: session,
    host: "et",
    taskType: "excel.analysis"
  });
  ctx.clearExcelAnalysisActiveJob = () => {
    storageCleared = true;
  };

  // Simulate transient network timeout error (not 404)
  ctx.request = () => {
    const error = new Error("Network timeout");
    error.status = 504;
    error.adapterCode = "TIMEOUT";
    return Promise.reject(error);
  };

  const sandbox = vm.createContext(ctx);
  const resumeCode = functionSource("resumeExcelAnalysisActiveJob");

  vm.runInContext([
    resumeCode
  ].join("\n"), sandbox);

  vm.runInContext("resumeExcelAnalysisActiveJob();", sandbox);

  setTimeout(() => {
    // Storage MUST NOT have been purged!
    assert.strictEqual(storageCleared, false, "transient error must not purge active job from storage");
    done();
  }, 20);
});

test("Behavioral: Different workbooks submit concurrently without being blocked by another session slot", (t, done) => {
  const ctx = createBaseTestContext();
  const sessionA = "session_wb_A";
  const sessionB = "session_wb_B";

  // Session A has an active analysis job running
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.analysis", sessionA, "job_A_active");
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", sessionA), true);

  // User is now on Session B
  ctx.defaultWorkbook = {
    Name: "工作簿B.xlsx",
    FullName: "/path/工作簿B.xlsx",
    __ai_wps_doc_session__: sessionB
  };
  ctx.state.documentSessionId = sessionB;
  ctx.state.currentMode = "excelAnalysis";

  // Session B should NOT be busy
  assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", sessionB), false);

  const sandbox = vm.createContext(ctx);
  const runAnalysisCode = functionSource("runExcelAnalysisAction");

  vm.runInContext([
    runAnalysisCode,
    "function buildExcelAnalysisClientJobId() { return 'job_B_client'; }",
    "function extractExcelRange() { return { rows: 2, columns: 2 }; }",
    "function summarizeExcelPayload() { return '2行 x 2列'; }",
    "function setScopeLine() {}",
    "function setInterruptedRetryVisible() {}",
    "function setExcelAnalysisCancelVisible() {}",
    "function setAnalysisBusy() {}",
    "function clearExcelAnalysisActiveJob() {}",
    "function startExcelAnalysisWaitFeedback() { return () => {}; }",
    "function saveExcelAnalysisActiveJob() {}"
  ].join("\n"), sandbox);

  // Submission in Session B should succeed in claiming slot and submitting
  vm.runInContext("runExcelAnalysisAction();", sandbox);

  setTimeout(() => {
    // Check that slot was claimed for session B
    assert.strictEqual(helpers.isTaskSlotBusy(ctx.state.activeTaskSlots, "et", "excel.analysis", sessionB), true);
    done();
  }, 20);
});

test("Behavioral: Analysis result with historyNotice suppresses unread count increment", () => {
  const ctx = createBaseTestContext();
  ctx.state.historyUnreadCount = 0;
  ctx.updateHistoryBadge = () => {};

  const sandbox = vm.createContext(ctx);
  const recordAnalysisCode = functionSource("recordFinalizedAnalysisResult");
  vm.runInContext(recordAnalysisCode, sandbox);

  // 1. Success without historyNotice -> increments unread
  vm.runInContext(`recordFinalizedAnalysisResult("job-a1", { structuredReport: {} }, true, "s1");`, sandbox);
  assert.strictEqual(ctx.state.historyUnreadCount, 1, "success without notice must increment unread");

  // 2. Success with historyNotice (e.g. diagnostic degradation) -> does NOT increment unread
  vm.runInContext(`recordFinalizedAnalysisResult("job-a2", { structuredReport: {}, historyNotice: "未保存历史" }, true, "s1");`, sandbox);
  assert.strictEqual(ctx.state.historyUnreadCount, 1, "historyNotice must suppress unread count increment");
});
