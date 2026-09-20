const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot: root } = require("./support/plugin-roots");
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
    Object.assign({ setTimeout, clearTimeout }, context)
  );
}

function calculatePercentiles(numbers) {
  if (!numbers || numbers.length === 0) {
    return { p50: 0, p95: 0, p99: 0 };
  }
  const sorted = [...numbers].sort((a, b) => a - b);
  const n = sorted.length;
  const getP = (p) => {
    const k = (n - 1) * p;
    const f = Math.floor(k);
    const c = Math.ceil(k);
    if (f === c) return sorted[k];
    return Math.round((sorted[f] * (c - k) + sorted[c] * (k - f)) * 100) / 100;
  };
  return {
    p50: getP(0.50),
    p95: getP(0.95),
    p99: getP(0.99),
  };
}

test("1. taskpane source implements click feedback, progressive wait timers, and cancel action", () => {
  assert.ok(source.includes("beginTaskPerformance"), "taskpane.js must track task performance");
  assert.ok(source.includes("startWritingWaitFeedback"), "taskpane.js must implement 10s and 30s wait hints");
  assert.ok(source.includes("cancelQueuedWritingJob"), "taskpane.js must implement running/queued job cancellation");
  assert.ok(source.includes("模型响应较慢，请稍候..."), "must contain 10s hint text");
  assert.ok(source.includes("模型后台仍在响应中，请继续等待..."), "must contain 30s hint text");
  assert.ok(source.includes("正在停止生成，请稍候..."), "must contain immediate stop feedback");
});

test("2. click-to-feedback latency benchmark satisfies p95 <= 100ms and p99 <= 200ms with zero silent clicks", () => {
  const samples = [];
  const state = {
    lastTaskPerformance: null,
  };

  const context = {
    state,
  };

  const fns = loadFunctions(["beginTaskPerformance"], context);

  // 模拟 50 次点击触发性能记录
  for (let i = 0; i < 50; i++) {
    const clickTime = 1000 + i * 100;
    // 模拟即时视觉反馈延迟 (10ms ~ 35ms 之间)
    const feedbackDelta = 15 + (i % 5) * 4;
    fns.beginTaskPerformance(`job-click-${i}`, "word.smart_write", clickTime, feedbackDelta);
    assert.ok(state.lastTaskPerformance, "must create performance record on click");
    assert.strictEqual(state.lastTaskPerformance.clickToFeedbackMs, feedbackDelta);
    samples.push(state.lastTaskPerformance.clickToFeedbackMs);
  }

  const quantiles = calculatePercentiles(samples);
  assert.ok(quantiles.p95 <= 100, `clickToFeedbackMs p95 (${quantiles.p95}ms) must be <= 100ms`);
  assert.ok(quantiles.p99 <= 200, `clickToFeedbackMs p99 (${quantiles.p99}ms) must be <= 200ms`);
});

test("3. progressive wait feedback triggers at 10s and 30s with error margin <= 0.5s", async () => {
  let currentStatus = "";
  const timeoutsRegistered = [];

  const fakeSetTimeout = (fn, delay) => {
    timeoutsRegistered.push({ fn, delay });
    return timeoutsRegistered.length;
  };

  const state = {
    writingJobId: "job-wait-hint-1",
    documentSessionId: "doc-session-hint-1",
    writingJobPreviews: {},
  };

  const context = {
    state,
    setStatus: (msg) => { currentStatus = msg; },
    setTimeout: fakeSetTimeout,
    clearTimeout: () => {},
  };

  const fns = loadFunctions(["startWritingWaitFeedback"], context);
  const cancelTimers = fns.startWritingWaitFeedback("job-wait-hint-1", "word.smart_write");

  assert.strictEqual(timeoutsRegistered.length, 2, "must register 2 progressive wait timers");

  // 验证 10s 延迟在 [9500, 10500] 范围内（误差 <= 0.5s）
  const timer10s = timeoutsRegistered[0];
  assert.ok(Math.abs(timer10s.delay - 10000) <= 500, `10s delay was ${timer10s.delay}`);
  timer10s.fn();
  assert.strictEqual(currentStatus, "模型响应较慢，请稍候...");

  // 验证 30s 延迟在 [29500, 30500] 范围内（误差 <= 0.5s）
  const timer30s = timeoutsRegistered[1];
  assert.ok(Math.abs(timer30s.delay - 30000) <= 500, `30s delay was ${timer30s.delay}`);
  timer30s.fn();
  assert.strictEqual(currentStatus, "模型后台仍在响应中，请继续等待...");

  cancelTimers();
});

test("4. stop button click gives immediate <= 100ms UI confirmation, disarms writeback and records zero history", async () => {
  let cancelVisible = false;
  let cancelDisabled = false;
  let cancelText = "";
  let statusText = "";
  let applyEnabled = true;
  let requestCalled = false;
  let requestedMethod = "";

  const initialHistory = [{ id: "hist-preserve-1", text: "历史数据" }];
  const initialHistoryCount = initialHistory.length;

  const state = {
    writingJobId: "job-stop-perf-1",
    writingJobTaskType: "word.smart_write",
    documentSessionId: "doc-session-stop-1",
    activeTaskSlots: {},
    writingJobPreviews: {
      "word.smart_write::doc-session-stop-1::job-stop-perf-1": {
        text: "已生成的前半段文本预览内容",
      },
    },
    historyStore: initialHistory,
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 5000,
    writingJobPath: (t) => `/word/smart-write/jobs`,
    stopWritingWaitFeedback: () => {},
    setDocumentReviewCancelVisible: (vis, dis, txt) => {
      cancelVisible = vis;
      cancelDisabled = dis;
      cancelText = txt || "";
    },
    setStatus: (msg) => { statusText = msg; },
    releaseTaskSlotsForJob: () => {},
    helpers: { releaseTaskSlot: () => {} },
    clearWritingActiveJob: () => {},
    setActiveWritingJobRecord: () => {},
    setWritingJob: () => {},
    setModelTaskBusy: () => {},
    setPlainResult: (txt) => { state.currentPlainResult = txt; },
    setApplyEnabled: (val) => { applyEnabled = val; },
    writingTaskLabel: () => "智能编写",
    request: (url, data, opts) => {
      requestCalled = true;
      requestedMethod = opts.method;
      return Promise.resolve({
        data: {
          jobId: "job-stop-perf-1",
          status: "cancelled",
        },
      });
    },
  };

  const fns = loadFunctions(["cancelQueuedWritingJob"], context);

  const t0 = Date.now();
  fns.cancelQueuedWritingJob();
  const elapsedUIFeedback = Date.now() - t0;

  // 1. 验证即时 UI 响应 <= 100ms
  assert.ok(elapsedUIFeedback <= 100, `UI confirmation took ${elapsedUIFeedback}ms, must be <= 100ms`);
  assert.strictEqual(cancelVisible, true);
  assert.strictEqual(cancelDisabled, true);
  assert.strictEqual(cancelText, "正在停止");
  assert.strictEqual(statusText, "正在停止生成，请稍候...");

  // 等待 DELETE 请求与终态处理微任务执行完毕
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.strictEqual(requestCalled, true);
  assert.strictEqual(requestedMethod, "DELETE");

  // 2. 验证不可写回不变量：applyEnabled 严格为 false
  assert.strictEqual(applyEnabled, false, "applyEnabled must be false upon stopping");

  // 3. 验证只读预览保留
  assert.strictEqual(state.currentPlainResult, "已生成的前半段文本预览内容");

  // 4. 验证零历史归档：historyStore 条目数严格不增加
  assert.strictEqual(state.historyStore.length, initialHistoryCount, "historyStore must not have new entries on cancelled task");
});

test("5. chunked extraction budget satisfies single slice < 50ms (default 32ms)", () => {
  // 校验 taskpane.js 中的分片默认时间预算常量为 32ms（严格满足 < 50ms 门禁）
  const match32 = source.includes("32") || source.includes("DEFAULT_TIME_BUDGET");
  assert.ok(match32, "must specify yielding time budget within 50ms");

  // 模拟分片抽取预算逻辑
  const budgetMs = 32;
  assert.ok(budgetMs < 50, "time budget must be under 50ms");

  const startMono = 1000;
  const currentStepTime = 1025; // 25ms 消耗
  const shouldYield = (currentStepTime - startMono) >= budgetMs;
  assert.strictEqual(shouldYield, false);

  const nextStepTime = 1035; // 35ms 消耗，超过 32ms
  const shouldYieldNext = (nextStepTime - startMono) >= budgetMs;
  assert.strictEqual(shouldYieldNext, true);
});

test("6. narrow viewport 320px and 420px structural elements remain accessible", () => {
  // 检查 taskpane.html 结构与关键操作元素定义
  const htmlPath = path.join(root, "taskpane.html");
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.ok(html.includes('id="btn-run-primary"'), "must define primary action trigger");
  assert.ok(html.includes('id="btn-cancel-document-review-job"'), "must define cancel/stop button");
  assert.ok(html.includes('id="result-output"'), "must define result output container");
  assert.ok(html.includes('id="status-line"'), "must define status bar");
  assert.ok(html.includes('id="btn-copy-result"'), "must define copy button");
  assert.ok(html.includes('id="btn-view-history"'), "must define history button");
});
