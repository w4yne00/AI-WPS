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
    currentMode: "excelSmartFill",
    busy: false,
    workflowProfileMutationBusy: false,
    modelTasksAllowed: true,
    adapterHealthStatus: "healthy",
    documentSessionId: "doc_session_1",
    activeTaskSlots: {},
    activeSmartFillResultsBySession: {},
    smartFillResult: null,
    smartFillPreview: null,
    smartFillInstruction: "",
    smartFillWorkbookId: "wb-1",
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
      }
    },
    helpers,
    requests,
    request: (url, body, options) => {
      requests.push({ url, body, options });
      return Promise.resolve({ success: true, data: { items: [] } });
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
    buildExcelSmartFillClientJobId: () => "sf_job_test_001",
    buildExcelSmartFillRequest: (clientJobId) => ({
      workbookId: "wb-1",
      clientJobId,
      documentSessionId: state.documentSessionId,
      documentDisplayName: "工作簿1.xlsx",
      host: "et",
      userInstruction: "生成岗位",
      source: { headers: ["姓名"], rows: [["张三"]] },
      items: [{ itemId: "sf_0123456789abcdef0123456789abcdef", sourceRowIndex: 1 }]
    }),
    clearExcelSmartFillActiveJob: () => {},
    saveExcelSmartFillActiveJob: () => {},
    setAnalysisBusy: (busy) => { state.busy = busy; },
    setSmartFillInterruptedRetryVisible: () => {},
    setExcelSmartFillCancelVisible: () => {},
    setScopeLine: () => {},
    summarizeSmartFillSource: () => "数据范围: A1:A2",
    startExcelSmartFillWaitFeedback: () => () => {},
    describeExcelSmartFillPollError: (err) => err.message || "error",
    isFatalExcelSmartFillPollError: () => true,
    setTrace: () => {},
    safeRead: (obj, key) => (obj ? obj[key] : undefined),
    resolveValue: (v) => v,
    defaultWorkbook: {
      Name: "工作簿1.xlsx",
      FullName: "/path/工作簿1.xlsx",
      __ai_wps_doc_session__: state.documentSessionId
    },
    getEtApplication: function() {
      return { ActiveWorkbook: this.defaultWorkbook };
    },
    getActiveWorkbook: function(app) {
      return (app && app.ActiveWorkbook) || this.defaultWorkbook;
    },
    EXCEL_SMART_FILL_REQUEST_TIMEOUT_MS: 30000,
    ...(initialOverrides.context || {})
  };

  return ctx;
}

test("Helper: getDocumentSessionId produces stable, path-sanitized session ID", () => {
  assert.strictEqual(typeof helpers.getDocumentSessionId, "function", "getDocumentSessionId must be exported");

  const wb1 = { Name: "测试表1.xlsx", FullName: "/Users/wayne/Secret/测试表1.xlsx" };
  const wb2 = { Name: "测试表2.xlsx", FullName: "/Users/wayne/Secret/测试表2.xlsx" };

  const session1_a = helpers.getDocumentSessionId(wb1);
  const session1_b = helpers.getDocumentSessionId(wb1);
  const session2 = helpers.getDocumentSessionId(wb2);

  assert.ok(session1_a, "session ID should not be empty");
  assert.strictEqual(session1_a, session1_b, "same workbook object must return identical session ID");
  assert.notStrictEqual(session1_a, session2, "different workbooks must return different session IDs");
  assert.ok(!session1_a.includes("/Users/wayne"), "session ID must not leak local filesystem path");
  assert.ok(!session1_a.includes("Secret"), "session ID must not contain directory names");
});

test("Helper: getDocumentDisplayName extracts basename without leaking path", () => {
  assert.strictEqual(typeof helpers.getDocumentDisplayName, "function", "getDocumentDisplayName must be exported");

  const wb = { Name: "员工清单.xlsx", FullName: "/Users/wayne/Confidential/员工清单.xlsx" };
  const name = helpers.getDocumentDisplayName(wb);
  assert.strictEqual(name, "员工清单.xlsx");
  assert.ok(!name.includes("/Users/wayne"), "display name must not contain path");
});

test("Helper: isTaskSlotBusy, claimTaskSlot, and releaseTaskSlot manage active slots", () => {
  assert.strictEqual(typeof helpers.isTaskSlotBusy, "function", "isTaskSlotBusy must be exported");
  assert.strictEqual(typeof helpers.claimTaskSlot, "function", "claimTaskSlot must be exported");
  assert.strictEqual(typeof helpers.releaseTaskSlot, "function", "releaseTaskSlot must be exported");

  const slots = {};
  const host = "et";
  const taskType = "excel.smart_fill";
  const session1 = "doc_session_1";
  const session2 = "doc_session_2";

  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);
  helpers.claimTaskSlot(slots, host, taskType, session1, "job-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), true);
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session2), false);

  helpers.releaseTaskSlot(slots, host, taskType, session1, "job-001");
  assert.strictEqual(helpers.isTaskSlotBusy(slots, host, taskType, session1), false);
});

test("Helper: renderSmartFillHistoryList renders cards with read-only buttons and NO writeback capability", () => {
  assert.strictEqual(typeof helpers.renderSmartFillHistoryList, "function", "renderSmartFillHistoryList must be exported");

  const emptyHtml = helpers.renderSmartFillHistoryList([]);
  assert.ok(emptyHtml.includes("excel-history-empty"), "empty state should show empty container");

  const items = [
    {
      id: "hist_123_abc",
      taskType: "excel.smart_fill",
      documentDisplayName: "销售业绩.xlsx",
      completedAt: "2026-09-10T12:00:00Z",
      result: {
        schemaVersion: "excel.smart_fill.v2",
        processedItemCount: 3,
        items: [
          { itemId: "sf_1", value: "甲", sourceRowIndex: 1, sourceRowLabel: "张三" },
          { itemId: "sf_2", value: "乙", sourceRowIndex: 2, sourceRowLabel: "李四" }
        ]
      }
    }
  ];

  const html = helpers.renderSmartFillHistoryList(items);
  assert.ok(html.includes("销售业绩.xlsx"), "should render document display name");
  assert.ok(html.includes("智能填写成果"), "should render task title");
  assert.ok(html.includes("btn-history-view"), "should have view action button");
  assert.ok(html.includes("btn-history-copy"), "should have copy action button");
  assert.ok(html.includes("btn-history-delete"), "should have delete action button");

  // CRITICAL: History MUST NOT contain writeback or retry capabilities
  assert.ok(!html.includes("btn-write-smart-fill"), "history cards must NOT contain writeback button");
  assert.ok(!html.includes("写入内容"), "history cards must NOT contain '写入内容'");
  assert.ok(!html.includes("重新提交"), "history cards must NOT contain resubmit/retry button");
});

test("HTML Markup: taskpane.html defines history button and history view panel", () => {
  assert.ok(taskpaneHtml.includes('id="btn-view-history"'), "taskpane.html must contain #btn-view-history");
  assert.ok(taskpaneHtml.includes('id="history-unread-badge"'), "taskpane.html must contain #history-unread-badge");
  assert.ok(taskpaneHtml.includes('id="excel-history-view"'), "taskpane.html must contain #excel-history-view");
  assert.ok(taskpaneHtml.includes('id="btn-history-back"'), "taskpane.html must contain #btn-history-back");
  assert.ok(taskpaneHtml.includes('id="btn-clear-history"'), "taskpane.html must contain #btn-clear-history");
  assert.ok(taskpaneHtml.includes('id="excel-history-content"'), "taskpane.html must contain #excel-history-content");
});

test("Taskpane Source Contract: runExcelSmartFillAction checks slot busy and claims slot", () => {
  const source = taskpaneSource;
  assert.ok(
    source.includes("isTaskSlotBusy") || source.includes("isTaskSlotBusy(state.activeTaskSlots"),
    "runExcelSmartFillAction must check isTaskSlotBusy before submitting"
  );
  assert.ok(
    source.includes("当前工作簿已存在进行中的智能填写任务，请等待其完成。"),
    "busy slot message must match contract"
  );
  assert.ok(
    source.includes("claimTaskSlot") || source.includes("claimTaskSlot(state.activeTaskSlots"),
    "runExcelSmartFillAction must claimTaskSlot on successful validation"
  );
  assert.ok(
    source.includes("releaseTaskSlot") || source.includes("releaseTaskSlot(state.activeTaskSlots"),
    "task completion or error must releaseTaskSlot"
  );
});

test("Behavioral: validation failure keeps existing active result", () => {
  const ctx = createBaseTestContext();
  ctx.state.smartFillResult = { items: [{ itemId: "sf_1", value: "已生成的标签" }] };
  ctx.byId("result-output").innerHTML = "<div>当前活动预览表格</div>";

  // Override buildExcelSmartFillRequest to throw validation error
  ctx.buildExcelSmartFillRequest = () => {
    throw new Error("请先框选包含表头的有效数据范围。");
  };

  const sandbox = vm.createContext(ctx);
  const runCode = functionSource("runExcelSmartFillAction");
  vm.runInContext(runCode + "\nrunExcelSmartFillAction();", sandbox);

  // Validation failure must NOT clear smartFillResult
  assert.ok(ctx.state.smartFillResult !== null, "smartFillResult must NOT be cleared when validation fails");
  // Output content must NOT be overwritten with "智能填写未开始"
  assert.strictEqual(
    ctx.byId("result-output").innerHTML,
    "<div>当前活动预览表格</div>",
    "result-output must retain existing active result when validation fails"
  );
});

test("Behavioral: valid submission immediately clears old result and shows progress", () => {
  const ctx = createBaseTestContext();
  ctx.state.smartFillResult = { items: [{ itemId: "sf_1", value: "旧结果" }] };
  ctx.state.smartFillPreview = { rows: [] };
  ctx.byId("result-output").innerHTML = "<div>旧预览</div>";

  const sandbox = vm.createContext(ctx);
  const runCode = functionSource("runExcelSmartFillAction");
  vm.runInContext(runCode + "\nrunExcelSmartFillAction();", sandbox);

  // Validation passed, so submission starts: old result must be cleared immediately
  assert.strictEqual(ctx.state.smartFillResult, null, "old smartFillResult must be cleared upon valid submission");
  assert.strictEqual(ctx.state.smartFillPreview, null, "old smartFillPreview must be cleared upon valid submission");
  assert.ok(
    ctx.byId("result-output").textContent.includes("正在等待模型后台生成智能填写预览"),
    "progress text must be displayed in result-output"
  );
});

test("Behavioral: slot busy prevents duplicate submission", () => {
  const ctx = createBaseTestContext();
  helpers.claimTaskSlot(ctx.state.activeTaskSlots, "et", "excel.smart_fill", ctx.state.documentSessionId, "job-busy-001");

  const sandbox = vm.createContext(ctx);
  const runCode = functionSource("runExcelSmartFillAction");
  vm.runInContext(runCode + "\nrunExcelSmartFillAction();", sandbox);

  assert.strictEqual(ctx.requests.length, 0, "no network request should be sent when slot is busy");
  assert.strictEqual(ctx.state.statusMessage, "当前工作簿已存在进行中的智能填写任务，请等待其完成。");
});

test("Behavioral: switchHistoryView toggles panels without resetting result-output or draft items", () => {
  const ctx = createBaseTestContext();
  ctx.state.smartFillResult = { items: [{ itemId: "sf_1", value: "现有结果" }] };
  ctx.state.smartFillPreview = { rows: [] };
  ctx.byId("result-output").innerHTML = '<table id="smart-fill-table"><tr><td>现有结果</td></tr></table>';
  const initialHtml = ctx.byId("result-output").innerHTML;

  const sandbox = vm.createContext(ctx);
  const switchCode = functionSource("switchHistoryView");
  const updateBadgeCode = functionSource("updateHistoryBadge");
  ctx.loadAndRenderSmartFillHistory = () => {};

  // Open history view
  vm.runInContext(updateBadgeCode + "\n" + switchCode + "\nswitchHistoryView(true);", sandbox);
  assert.strictEqual(ctx.state.historyOpen, true);
  assert.strictEqual(ctx.byId("excel-result-panel").hidden, true);
  assert.strictEqual(ctx.byId("excel-history-view").hidden, false);

  // Close history view
  vm.runInContext("switchHistoryView(false);", sandbox);
  assert.strictEqual(ctx.state.historyOpen, false);
  assert.strictEqual(ctx.byId("excel-result-panel").hidden, false);
  assert.strictEqual(ctx.byId("excel-history-view").hidden, true);

  // Result output HTML must be preserved
  assert.strictEqual(ctx.byId("result-output").innerHTML, initialHtml, "result-output HTML must be preserved when toggling history view");
  assert.ok(ctx.state.smartFillResult, "smartFillResult must remain intact");
});

test("Behavioral: valid submission clears session result cache and excelSmartFillCompletedJobId", () => {
  const ctx = createBaseTestContext();
  ctx.state.activeSmartFillResultsBySession = {
    doc_session_1: { items: [{ itemId: "sf_1", value: "旧会话结果" }] }
  };
  ctx.state.excelSmartFillCompletedJobId = "old-job-id-123";
  ctx.state.smartFillDraftItems = [{ itemId: "sf_1", value: "草稿修改" }];
  ctx.state.smartFillResult = { items: [{ itemId: "sf_1", value: "旧会话结果" }] };

  const sandbox = vm.createContext(ctx);
  const runCode = functionSource("runExcelSmartFillAction");
  vm.runInContext(runCode + "\nrunExcelSmartFillAction();", sandbox);

  assert.strictEqual(ctx.state.activeSmartFillResultsBySession["doc_session_1"], undefined, "active session result cache must be cleared");
  assert.strictEqual(ctx.state.excelSmartFillCompletedJobId, "", "completedJobId must be reset");
  assert.strictEqual(ctx.state.smartFillDraftItems.length, 0, "smartFillDraftItems must be reset");
});

test("Behavioral: active job localStorage keys and resume are isolated per documentSessionId", () => {
  const mockStorage = {};
  const ctx = createBaseTestContext({
    context: {
      window: {
        localStorage: {
          getItem: (k) => mockStorage[k] || null,
          setItem: (k, v) => { mockStorage[k] = String(v); },
          removeItem: (k) => { delete mockStorage[k]; }
        }
      },
      EXCEL_SMART_FILL_ACTIVE_JOB_STORAGE_KEY: "wps_ai_excel_smart_fill_active_job",
      FRONTEND_BUILD_VERSION: "1.0.0"
    }
  });

  const sandbox = vm.createContext(ctx);
  const getStorageKeyCode = functionSource("getExcelSmartFillActiveJobStorageKey");
  const saveCode = functionSource("saveExcelSmartFillActiveJob");
  const loadCode = functionSource("loadExcelSmartFillActiveJob");
  const clearCode = functionSource("clearExcelSmartFillActiveJob");

  const combined = [getStorageKeyCode, saveCode, loadCode, clearCode].join("\n");
  vm.runInContext(combined, sandbox);

  // Save job for session-A
  vm.runInContext(`
    saveExcelSmartFillActiveJob({
      jobId: "job-A",
      documentSessionId: "session-A",
      startedAt: 1000
    });
  `, sandbox);

  // Save job for session-B
  vm.runInContext(`
    saveExcelSmartFillActiveJob({
      jobId: "job-B",
      documentSessionId: "session-B",
      startedAt: 2000
    });
  `, sandbox);

  // Verify separate keys in localStorage
  assert.ok(mockStorage["wps_ai_excel_smart_fill_active_job_session-A"], "session-A key must exist");
  assert.ok(mockStorage["wps_ai_excel_smart_fill_active_job_session-B"], "session-B key must exist");

  // Load session A
  const loadedA = vm.runInContext(`loadExcelSmartFillActiveJob("session-A");`, sandbox);
  assert.strictEqual(loadedA.jobId, "job-A");
  assert.strictEqual(loadedA.documentSessionId, "session-A");

  // Load session B
  const loadedB = vm.runInContext(`loadExcelSmartFillActiveJob("session-B");`, sandbox);
  assert.strictEqual(loadedB.jobId, "job-B");
  assert.strictEqual(loadedB.documentSessionId, "session-B");

  // Clear session A does not affect session B
  vm.runInContext(`clearExcelSmartFillActiveJob("job-A", "session-A");`, sandbox);
  assert.strictEqual(mockStorage["wps_ai_excel_smart_fill_active_job_session-A"], undefined);
  assert.ok(mockStorage["wps_ai_excel_smart_fill_active_job_session-B"] !== undefined);
});

test("Behavioral: recordFinalizedSmartFillResult suppresses badge on failure or historyNotice", () => {
  const ctx = createBaseTestContext();
  ctx.state.historyUnreadCount = 0;
  ctx.updateHistoryBadge = () => {};

  const sandbox = vm.createContext(ctx);
  const recordCode = functionSource("recordFinalizedSmartFillResult");
  vm.runInContext(recordCode, sandbox);

  // 1. Successful normal result -> increments unread
  vm.runInContext(`recordFinalizedSmartFillResult("job-1", { items: [] }, true);`, sandbox);
  assert.strictEqual(ctx.state.historyUnreadCount, 1, "success should increment unread count");

  // 2. Failed / cancelled / partial preview (isSuccess = false) -> does NOT increment
  vm.runInContext(`recordFinalizedSmartFillResult("job-2", { items: [], partial: true }, false);`, sandbox);
  assert.strictEqual(ctx.state.historyUnreadCount, 1, "failed/cancelled result must NOT increment unread count");

  // 3. Oversized payload (> 5 MiB) with historyNotice -> does NOT increment
  vm.runInContext(`recordFinalizedSmartFillResult("job-3", { items: [], historyNotice: "结果过大未归档" }, true);`, sandbox);
  assert.strictEqual(ctx.state.historyUnreadCount, 1, "oversized payload with historyNotice must NOT increment unread count");
});

test("Helper: renderSmartFillHistoryList falls back gracefully when sourceRowIndex is missing", () => {
  const items = [
    {
      id: "hist_missing_idx",
      taskType: "excel.smart_fill",
      documentDisplayName: "无行号历史.xlsx",
      completedAt: "2026-09-10T12:00:00Z",
      result: {
        schemaVersion: "excel.smart_fill.v2",
        processedItemCount: 2,
        items: [
          { itemId: "sf_1", value: "填入值A" },
          { itemId: "sf_2", value: "填入值B", sourceRowIndex: null }
        ]
      }
    }
  ];

  const html = helpers.renderSmartFillHistoryList(items);
  assert.ok(!html.includes("undefined"), "rendered history HTML must never include 'undefined'");
  assert.ok(html.includes("第1行"), "should fall back to 1-based index (第1行)");
  assert.ok(html.includes("第2行"), "should fall back to 1-based index (第2行)");
});
