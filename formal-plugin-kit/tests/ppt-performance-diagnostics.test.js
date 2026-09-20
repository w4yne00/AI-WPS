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
    "getTerminalCompletionTimestamp",
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

// 2. 任务窗格性能跟踪记录基础能力与 50 条按创建顺序淘汰
test("PPT task performance recording, trace binding and bounded FIFO eviction", () => {
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

  // 验证超过 50 个任务按创建顺序淘汰
  for (let i = 2; i <= 60; i++) {
    fns.beginTaskPerformance(`job-ppt-${i}`, "ppt.slide_assistant", 2000 + i, 12);
  }
  assert.strictEqual(state.taskPerformanceOrder.length, 50);
  // 第 1 个任务已被淘汰
  assert.strictEqual(fns.getTaskPerformance("job-ppt-1-resolved", null), null);
  // 最新的任务仍然保留
  assert.ok(fns.getTaskPerformance("job-ppt-60", null) !== null);
});

test("PPT terminal completion timestamp includes monotonic terminal age", () => {
  let virtualTime = 5000;
  const context = {
    performance: { now: () => virtualTime },
    Date: { now: () => virtualTime }
  };
  const fns = loadFunctions(["getTerminalCompletionTimestamp"], context);

  assert.strictEqual(
    fns.getTerminalCompletionTimestamp({ terminalAgeMs: 2750 }),
    2250,
    "completion timestamp must include time spent waiting for the next poll"
  );
  assert.strictEqual(
    fns.getTerminalCompletionTimestamp({}),
    5000,
    "older adapters without terminalAgeMs fall back to response observation time"
  );
});

// 3. 高级诊断呈现“任务窗格本地耗时”
test("PPT renderProviderDiagnostics presents local taskpane metrics section", () => {
  const currentPerformance = {
    jobId: "job-ppt-1",
    traceId: "trace-1",
    taskType: "ppt.slide_assistant",
    clickToFeedbackMs: 14,
    localExtractionMs: 38,
    clickToAdapterAcceptedMs: 165,
    completionToFirstRenderMs: 42
  };
  const state = {
    taskPerformanceByJobId: { "job-ppt-1": currentPerformance },
    taskPerformanceByTraceId: { "trace-1": currentPerformance },
    lastTaskPerformance: {
      jobId: "job-other",
      traceId: "trace-other",
      taskType: "ppt.slide_assistant",
      clickToFeedbackMs: 999,
      localExtractionMs: 999,
      clickToAdapterAcceptedMs: 999,
      completionToFirstRenderMs: 999
    }
  };

  const context = {
    state,
    FRONTEND_BUILD_VERSION: "0.26.0-test"
  };

  const fns = loadFunctions(["getTaskPerformance", "renderProviderDiagnostics"], context);

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
  assert.ok(!markdown.includes("999 ms"), "must not mix metrics from another trace");
});

// 4. setRunDisabled 阻断写操作但保留只读操作
test("setRunDisabled disables mutation controls while keeping readonly actions enabled", () => {
  const elements = {};
  const refreshed = [];
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
    renderProfileStrip: () => { refreshed.push("strip"); },
    renderProfileManager: () => { refreshed.push("profiles"); },
    renderDirectServicesList: () => { refreshed.push("services"); },
    renderTaskModelSelectionSection: () => { refreshed.push("task-selection"); },
    updateWorkflowEditorControls: () => { refreshed.push("workflow-editor"); }
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
  assert.deepStrictEqual(
    refreshed,
    ["strip", "profiles", "services", "task-selection", "workflow-editor"],
    "busy transition should refresh every settings mutation surface"
  );
});

// 5. 设置页在 state.busy 时阻断模型配置修改
test("settings mutations are blocked when state.busy is true", () => {
  const state = {
    busy: true,
    workflowProfileMutationBusy: false,
    directServices: [{ id: "direct_svc_1", name: "服务1" }],
    taskModelSelections: {},
    profiles: { activeProfileId: "prof_1", profiles: [{ id: "prof_1", name: "配置1", complete: true }] },
    directServiceEditor: { open: true, serviceId: "direct_svc_1", revision: 2 }
  };

  let statusMsg = "";
  let mutationAttempts = 0;
  const context = {
    state,
    setStatus: (msg) => { statusMsg = msg; },
    request: () => {
      mutationAttempts += 1;
      return new Promise(() => {});
    },
    setWorkflowProfileMutationBusy: () => {},
    copyModelConfiguration: () => { mutationAttempts += 1; },
    activateWorkflowProfile: () => { mutationAttempts += 1; },
    deleteWorkflowProfile: () => { mutationAttempts += 1; },
    openWorkflowEditor: () => { mutationAttempts += 1; },
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
    "handleWorkflowProfileAction",
    "clearDirectServiceApiKey",
    "refreshDirectServiceModelsInEditor",
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
  // 工作流复制、清除 Key、刷新模型目录也不得穿透 busy 门禁
  fns.handleWorkflowProfileAction({
    target: {
      getAttribute: (key) => key === "data-profile-action" ? "copy" : "prof_1"
    }
  });
  fns.clearDirectServiceApiKey();
  fns.refreshDirectServiceModelsInEditor();
  assert.strictEqual(mutationAttempts, 0, "no settings mutation may start while a task is running");
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
  assert.strictEqual(fns.validateSlideAssistantResult({ resultType: "bogus", rawAnswer: "错误类型" }).valid, false);
  assert.strictEqual(fns.validateSlideAssistantResult({ resultType: "slide", plainText: "缺少完整结果信封" }).valid, false);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "slide",
    suggestedTitle: "标题",
    bullets: ["点1"],
    conclusion: "结论",
    plainText: "标题\n点1\n结论",
    rawAnswer: null,
    parseFallbackReason: null
  }).valid, true);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "slide",
    suggestedTitle: "",
    bullets: [],
    conclusion: "",
    plainText: "模型返回的纯文本降级结果",
    rawAnswer: "模型返回的纯文本降级结果",
    parseFallbackReason: "ppt_output_not_structured"
  }).valid, true);

  // 文档总结验证
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "document",
    deckTitle: "总方案",
    documentSummary: "摘要",
    recommendedSlideCount: 5,
    slides: [{ index: 1, title: "页1" }],
    globalStyleAdvice: "统一样式",
    plainText: "总方案\n摘要",
    rawAnswer: null,
    parseFallbackReason: null
  }).valid, true);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "document",
    deckTitle: "只有标题"
  }).valid, false);
  assert.strictEqual(fns.validateSlideAssistantResult({
    resultType: "document",
    deckTitle: "",
    documentSummary: "模型后台已返回结果，但未按结构化 JSON 输出。",
    recommendedSlideCount: 5,
    slides: [],
    globalStyleAdvice: "",
    plainText: "模型返回的纯文本降级结果",
    rawAnswer: "模型返回的纯文本降级结果",
    parseFallbackReason: "模型后台未返回可解析的 PPT 文档总结 JSON。"
  }).valid, true);

  // 结构审查验证
  assert.strictEqual(fns.validateStructureReviewResult(null).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({}).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({ highPriorityIssues: [] }).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({
    reviewedRange: { startSlide: 5, endSlide: 1, totalSlides: 5 },
    inferredChapters: [],
    highPriorityIssues: [],
    generalSuggestions: [],
    slideRecommendations: [],
    recommendedOutline: [],
    pageRoles: [],
    reviewConclusion: "无效范围",
    plainText: "无效范围"
  }).valid, false);
  assert.strictEqual(fns.validateStructureReviewResult({
    reviewedRange: { startSlide: 1, endSlide: 5, totalSlides: 5 },
    inferredChapters: [],
    highPriorityIssues: [],
    generalSuggestions: [],
    slideRecommendations: [],
    recommendedOutline: [],
    pageRoles: [],
    reviewConclusion: "审查完成",
    plainText: "审查完成"
  }).valid, true);
});

// 7. finishJob 支持 targetDocSession 隔离及查看历史时不强制切回
test("finishJob isolates by document session and respects historyOpen", () => {
  let rendered = false;
  let statusText = "";
  const firstRenderCalls = [];
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
    recordTaskFirstRender: (...args) => { firstRenderCalls.push(args); },
    validateSlideAssistantResult: () => ({ valid: true }),
    helpers: { getDocumentSessionId: () => state.documentSessionId }
  };

  const fns = loadFunctions(["finishJob"], context);

  const resultDocB = { resultType: "slide", plainText: "文稿B总结" };
  // 后台任务为 doc-session-B 完成，当前处于 doc-session-A
  fns.finishJob("job-doc-b", resultDocB, "doc-session-B", "trace-doc-b", 1200);
  assert.strictEqual(state.slideAssistantResultsBySession["doc-session-B"], resultDocB);
  assert.strictEqual(rendered, false, "Must not render result for background document session");
  assert.strictEqual(state.result, null, "Must not overwrite current active result");
  assert.strictEqual(firstRenderCalls.length, 0, "background session did not render");

  // 当前 session 完成，但在查看历史 (historyOpen === true)
  const resultDocA = { resultType: "slide", plainText: "文稿A总结" };
  fns.finishJob("job-ppt-1", resultDocA, "doc-session-A", "trace-doc-a", 1300);
  assert.strictEqual(state.historyUnreadCount, 1, "Should increment historyUnreadCount");
  assert.strictEqual(rendered, false, "Must not force switch back or render when viewing history");
  assert.strictEqual(state.result, resultDocA, "Active result recorded");
  assert.strictEqual(firstRenderCalls.length, 0, "history view did not render");

  state.historyOpen = false;
  state.jobId = "job-ppt-2";
  const renderedResult = {
    resultType: "slide",
    suggestedTitle: "标题",
    bullets: ["要点"],
    conclusion: "结论",
    plainText: "标题\n要点\n结论",
    rawAnswer: null,
    parseFallbackReason: null
  };
  fns.finishJob("job-ppt-2", renderedResult, "doc-session-A", "trace-doc-rendered", 1400);
  assert.strictEqual(rendered, true, "active session should render");
  assert.deepStrictEqual(
    firstRenderCalls[0],
    ["job-ppt-2", "trace-doc-rendered", "ppt.slide_assistant", 1400],
    "first-render timing must start only after the result is accepted for rendering"
  );
});
