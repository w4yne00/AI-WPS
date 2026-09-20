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

test("progressive wait feedback registers the 10s and 30s callbacks", () => {
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

test("stop action synchronously disarms writeback and retains the partial preview", async () => {
  let cancelVisible = false;
  let cancelDisabled = false;
  let cancelText = "";
  let statusText = "";
  let applyEnabled = true;
  let requestCalled = false;
  let requestedMethod = "";

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

  fns.cancelQueuedWritingJob();

  // 同步更新表示用户点击后不会等待 DELETE 请求返回才获得反馈。
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
});
