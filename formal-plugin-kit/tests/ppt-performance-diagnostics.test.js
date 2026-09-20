const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { pptRoot: root } = require("./support/plugin-roots");
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

// 1. 静态源码包含关键指标与方法标记
test("PPT taskpane contains performance tracking functions and metrics", () => {
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
    "任务窗格本地耗时",
    "validateSlideAssistantResult",
    "validateStructureReviewResult"
  ].forEach((marker) => {
    assert.ok(source.includes(marker), `missing marker: ${marker}`);
  });
});

// 2. 任务窗格性能跟踪记录基础能力与 50 条 LRU 淘汰
test("PPT task performance recording, trace binding and LRU eviction", () => {
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
  const perf = fns.beginTaskPerformance("job-ppt-1", "ppt.slide_assistant", 1000, 18);
  assert.strictEqual(perf.jobId, "job-ppt-1");
  assert.strictEqual(perf.taskType, "ppt.slide_assistant");
  assert.strictEqual(perf.clickTimestamp, 1000);
  assert.strictEqual(perf.clickToFeedbackMs, 18);
  assert.strictEqual(state.lastTaskPerformance, perf);

  // 绑定 traceId
  fns.bindTaskPerformanceTrace("job-ppt-1", "trace-ppt-1", "job-ppt-1-resolved");
  assert.strictEqual(perf.traceId, "trace-ppt-1");
  assert.strictEqual(perf.jobId, "job-ppt-1-resolved");
  assert.strictEqual(fns.getTaskPerformance(null, "trace-ppt-1"), perf);
  assert.strictEqual(fns.getTaskPerformance("job-ppt-1-resolved", null), perf);

  // 首渲染耗时记录
  virtualTime = 1450;
  fns.recordTaskFirstRender("job-ppt-1-resolved", "trace-ppt-1", "ppt.slide_assistant", 1400);
  assert.strictEqual(perf.completionToFirstRenderMs, 50);

  // 验证超过 50 个任务触发 LRU 淘汰
  for (let i = 2; i <= 60; i++) {
    fns.beginTaskPerformance(`job-ppt-${i}`, "ppt.slide_assistant", 2000 + i, 12);
  }
  assert.strictEqual(state.taskPerformanceOrder.length, 50);
  // 第 1 个任务已被淘汰
  assert.strictEqual(fns.getTaskPerformance("job-ppt-1-resolved", null), null);
  // 最新的任务仍然保留
  assert.ok(fns.getTaskPerformance("job-ppt-60", null) !== null);
});

// 3. 高级诊断呈现“任务窗格本地耗时”
test("PPT renderProviderDiagnostics presents local taskpane metrics section", () => {
  const state = {
    lastTaskPerformance: {
      jobId: "job-ppt-1",
      taskType: "ppt.slide_assistant",
      clickToFeedbackMs: 14,
      localExtractionMs: 38,
      clickToAdapterAcceptedMs: 165,
      completionToFirstRenderMs: 42
    }
  };

  const context = {
    state,
    FRONTEND_BUILD_VERSION: "0.26.0-test"
  };

  const fns = loadFunctions(["renderProviderDiagnostics"], context);

  const markdown = fns.renderProviderDiagnostics([
    { data: { taskType: "ppt.slide_assistant", traceId: "trace-1", performance: { providerOutcome: "success" } } },
    { data: { configured: true } },
    { data: {} },
    { data: {} }
  ]);

  assert.ok(markdown.includes("## 任务窗格本地耗时"), "diagnostics should contain local latency section");
  assert.ok(markdown.includes("- 点击到反馈耗时：14 ms"), "contains clickToFeedbackMs");
  assert.ok(markdown.includes("- 本地抽取耗时：38 ms"), "contains localExtractionMs");
  assert.ok(markdown.includes("- 点击到后台接收耗时：165 ms"), "contains clickToAdapterAcceptedMs");
  assert.ok(markdown.includes("- 完成到首渲染耗时：42 ms"), "contains completionToFirstRenderMs");
});

// 4. setRunDisabled 阻断写操作但保留只读操作
test("setRunDisabled disables mutation controls while keeping readonly actions enabled", () => {
  const elements = {};
  const byId = (id) => {
    if (!elements[id]) {
      elements[id] = { id, disabled: false };
    }
    return elements[id];
  };

  const state = {
    busy: false,
    workflowProfileMutationBusy: false
  };

  const context = {
    state,
    byId,
    renderProfileStrip: () => {}
  };

  const fns = loadFunctions(["setRunDisabled"], context);

  // 触发 busy = true
  fns.setRunDisabled(true);
  assert.strictEqual(state.busy, true);

  // 写操作被禁用
  assert.strictEqual(byId("btn-run-primary").disabled, true);
  assert.strictEqual(byId("btn-run-structure-review").disabled, true);
  assert.strictEqual(byId("ppt-source-slide").disabled, true);
  assert.strictEqual(byId("ppt-source-document").disabled, true);
  assert.strictEqual(byId("ppt-document-file").disabled, true);
  assert.strictEqual(byId("ppt-slide-count").disabled, true);
  assert.strictEqual(byId("ppt-slide-instruction").disabled, true);
  assert.strictEqual(byId("ppt-structure-start-slide").disabled, true);
  assert.strictEqual(byId("ppt-structure-end-slide").disabled, true);

  // 只读入口必须保持可用（未被 setRunDisabled 禁用）
  assert.strictEqual(byId("btn-open-settings").disabled, false, "btn-open-settings should NOT be disabled");
  assert.strictEqual(byId("btn-view-history").disabled, false, "btn-view-history should NOT be disabled");
  assert.strictEqual(byId("btn-view-structure-history").disabled, false, "btn-view-structure-history should NOT be disabled");
  assert.strictEqual(byId("btn-copy-result").disabled, false, "btn-copy-result should NOT be disabled");
});

// 5. 设置页在 state.busy 时阻断模型配置修改
test("settings mutations are blocked when state.busy is true", () => {
  const state = {
    busy: true,
    workflowProfileMutationBusy: false,
    directServices: [{ id: "direct_svc_1", name: "服务1" }],
    taskModelSelections: {},
    profiles: { activeProfileId: "prof_1", profiles: [{ id: "prof_1", name: "配置1", complete: true }] }
  };

  let statusMsg = "";
  const context = {
    state,
    setStatus: (msg) => { statusMsg = msg; },
    findDirectService: (id) => state.directServices.find(s => s.id === id),
    getTaskModelSelectionDraft: () => ({ serviceId: "direct_svc_1", modelName: "gpt-4o" }),
    getSettingsWorkflowTaskType: () => "ppt.slide_assistant",
    helpers: {
      validateTaskModelSelectionDraft: () => ({ ok: true })
    },
    byId: () => ({ textContent: "", hidden: false, disabled: false, value: "" })
  };

  const fns = loadFunctions([
    "openDirectServiceEditor",
    "handleDirectServiceAction",
    "saveTaskModelSelection",
    "handleTaskDirectServiceSelectChange"
  ], context);

  // 打开 direct service 编辑器被阻断
  fns.openDirectServiceEditor("edit", "direct_svc_1");
  // 动作分发被阻断
  fns.handleDirectServiceAction({ target: { getAttribute: (k) => k === "data-direct-action" ? "delete" : "direct_svc_1" } });
  // 保存任务模型配置被阻断
  const saveResult = fns.saveTaskModelSelection();
  assert.strictEqual(saveResult, undefined, "saveTaskModelSelection should return without saving when state.busy is true");
});

// 6. 结果完整结构化校验通过后才展示正式结果
test("structured validation ensures formal results are valid before display", () => {
  const context = {};
  const fns = loadFunctions([
    "validateSlideAssistantResult",
    "validateStructureReviewResult"
  ], context);

  // 单页总结验证
  assert.strictEqual(fns.validateSlideAssistantResult(null).valid, false);
  assert.strictEqual(fns.validateSlideAssistantResult({}).valid, false);
  assert.strictEqual(fns.validateSlideAssistantResult({ resultType: "slide", plainText: "总结内容" }).valid, true);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "slide",
    suggestedTitle: "标题",
    bullets: ["点1"],
    conclusion: "结论"
  }).valid, true);

  // 文档总结验证
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "document",
    deckTitle: "总方案",
    documentSummary: "摘要",
    slides: [{ index: 1, title: "页1" }]
  }).valid, true);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "document",
    slides: []
  }).valid, false);

  // 结构审查验证
  assert.strictEqual(fns.validateStructureReviewResult(null).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({}).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({
    reviewedRange: { startSlide: 1, endSlide: 5, totalSlides: 5 },
    highPriorityIssues: [],
    generalSuggestions: []
  }).valid, true);
});

// 7. finishJob 支持 targetDocSession 隔离及查看历史时不强制切回
test("finishJob isolates by document session and respects historyOpen", () => {
  let rendered = false;
  let statusText = "";
  const state = {
    documentSessionId: "doc-session-A",
    jobId: "job-ppt-1",
    busy: true,
    historyOpen: true,
    historyUnreadCount: 0,
    result: null,
    slideAssistantResultsBySession: {}
  };

  const context = {
    state,
    clearActiveJob: () => {},
    releaseTaskSlotsForJob: () => {},
    setPptJobActionVisibility: () => {},
    setRunDisabled: (val) => { state.busy = val; },
    updateHistoryBadge: () => {},
    setStatus: (txt) => { statusText = txt; },
    renderResult: () => { rendered = true; },
    validateSlideAssistantResult: () => ({ valid: true }),
    helpers: { getDocumentSessionId: () => state.documentSessionId }
  };

  const fns = loadFunctions(["finishJob"], context);

  const resultDocB = { resultType: "slide", plainText: "文稿B总结" };
  // 后台任务为 doc-session-B 完成，当前处于 doc-session-A
  fns.finishJob("job-doc-b", resultDocB, "doc-session-B");
  assert.strictEqual(state.slideAssistantResultsBySession["doc-session-B"], resultDocB);
  assert.strictEqual(rendered, false, "Must not render result for background document session");
  assert.strictEqual(state.result, null, "Must not overwrite current active result");

  // 当前 session 完成，但在查看历史 (historyOpen === true)
  const resultDocA = { resultType: "slide", plainText: "文稿A总结" };
  fns.finishJob("job-ppt-1", resultDocA, "doc-session-A");
  assert.strictEqual(state.historyUnreadCount, 1, "Should increment historyUnreadCount");
  assert.strictEqual(rendered, false, "Must not force switch back or render when viewing history");
  assert.strictEqual(state.result, resultDocA, "Active result recorded");
});
