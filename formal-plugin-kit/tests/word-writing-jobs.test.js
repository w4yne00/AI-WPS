const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { wordRoot: root } = require("./support/plugin-roots");
const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const next = source.indexOf("\n  function ", start + 1);
  return source.slice(start, next >= 0 ? next : source.length);
}

function loadFunctions(names, context) {
  const declarations = names.map(functionSource).join("\n");
  const exports = names.map((name) => `${name}: ${name}`).join(",");
  return vm.runInNewContext(
    `(function () { ${declarations}; return {${exports}}; })()`,
    context
  );
}

[
  'WRITING_ACTIVE_JOB_STORAGE_KEY = "ai-wps-writing-active-job-v1"',
  '"/word/smart-write/jobs"',
  '"/word/smart-imitation/jobs"',
  "saveWritingActiveJob",
  "resumeWritingActiveJob",
  "pollWritingJob",
  "cancelQueuedWritingJob",
  "clientJobId",
  "?resume=1",
  "clickToFeedbackMs",
  "clickToAdapterAcceptedMs",
  "completionToFirstRenderMs",
  "lastTaskPerformance"
].forEach((marker) => assert.ok(source.includes(marker), `missing ${marker}`));

assert.ok(!source.includes('request("/word/smart-write", state.latestDocumentPayload)'));
assert.ok(!source.includes('request("/word/smart-imitation", state.latestDocumentPayload)'));
assert.ok(source.includes('startWritingJob(state.latestDocumentPayload, "word.smart_write", "smartWrite")'));
assert.ok(source.includes('startWritingJob(state.latestDocumentPayload, "word.smart_imitation", "smartImitation")'));
assert.ok(source.includes("本次恢复结果仅供预览和复制"));

const performanceState = {
  taskPerformanceByJobId: {},
  taskPerformanceByTraceId: {},
  taskPerformanceOrder: [],
  lastTaskPerformance: null
};
const performanceContext = {
  state: performanceState,
  performance: { now: () => 25 },
  Date,
  requestAnimationFrame(callback) {
    performanceContext.pendingFrame = callback;
  }
};
const performanceFunctions = loadFunctions([
  "getTaskPerformance",
  "beginTaskPerformance",
  "bindTaskPerformanceTrace",
  "selectTaskPerformance",
  "recordTaskFirstRender"
], performanceContext);

const taskA = performanceFunctions.beginTaskPerformance(
  "job-a",
  "word.smart_write",
  1,
  2
);
const taskB = performanceFunctions.beginTaskPerformance(
  "job-b",
  "word.smart_imitation",
  3,
  4
);
performanceFunctions.bindTaskPerformanceTrace("job-b", "trace-b");
performanceFunctions.bindTaskPerformanceTrace("job-a", "trace-a");
taskA.clickToAdapterAcceptedMs = 11;
taskB.clickToAdapterAcceptedMs = 22;

assert.strictEqual(
  performanceFunctions.getTaskPerformance("job-a", "trace-a").clickToAdapterAcceptedMs,
  11
);
assert.strictEqual(
  performanceFunctions.getTaskPerformance("job-b", "trace-b").clickToAdapterAcceptedMs,
  22
);
performanceFunctions.selectTaskPerformance("", "trace-a");
assert.strictEqual(performanceState.lastTaskPerformance.jobId, "job-a");

performanceFunctions.recordTaskFirstRender(
  "job-a",
  "trace-a",
  "word.smart_write",
  10
);
assert.strictEqual(taskA.completionToFirstRenderMs, null);
assert.strictEqual(typeof performanceContext.pendingFrame, "function");
performanceContext.pendingFrame();
assert.strictEqual(taskA.completionToFirstRenderMs, 15);

performanceState.traceId = "trace-b";
performanceFunctions.selectTaskPerformance("", "trace-b");
performanceFunctions.recordTaskFirstRender(
  "job-b",
  "trace-b",
  "word.smart_imitation",
  10
);
performanceState.traceId = "trace-a";
performanceFunctions.selectTaskPerformance("", "trace-a");
performanceContext.pendingFrame();
assert.strictEqual(taskB.completionToFirstRenderMs, 15);
assert.strictEqual(performanceState.lastTaskPerformance.jobId, "job-a");

performanceFunctions.beginTaskPerformance("client-alias", "word.smart_write", 1, 1);
performanceFunctions.bindTaskPerformanceTrace("client-alias", "trace-alias", "server-alias");
for (let index = 0; index < 50; index += 1) {
  performanceFunctions.beginTaskPerformance(
    `job-capacity-${index}`,
    "word.smart_write",
    index,
    index
  );
}
assert.strictEqual(
  performanceFunctions.getTaskPerformance("server-alias", "trace-alias"),
  null
);

async function testConcurrentWritingPerformanceStaysIsolated() {
  const pendingRequests = [];
  const generatedJobIds = ["job-a", "job-b"];
  let now = 40;
  const concurrentState = {
    activeTaskSlots: {},
    taskPerformanceByJobId: {},
    taskPerformanceByTraceId: {},
    taskPerformanceOrder: [],
    lastTaskPerformance: null,
    documentSessionId: "",
    currentMode: "smartWrite"
  };
  const context = {
    state: concurrentState,
    Date,
    performance: { now: () => { now += 10; return now; } },
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot() {},
      getDocumentSessionId: () => "unused",
      getDocumentDisplayName: () => "unused.docx"
    },
    getActiveDocument: () => ({}),
    buildWritingClientJobId: () => generatedJobIds.shift(),
    setModelTaskBusy() {},
    setStatus() {},
    setWritingJob() {},
    setActiveWritingJobRecord() {},
    saveWritingActiveJob() {},
    setTrace() {},
    renderWritingJobProgress() {},
    pollWritingJob() {},
    completeWritingJob() {},
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    writingJobPath: () => "/jobs",
    WRITING_POLL_REQUEST_TIMEOUT_MS: 1000,
    request() {
      return new Promise((resolve, reject) => pendingRequests.push({ resolve, reject }));
    }
  };
  const functions = loadFunctions([
    "getTaskPerformance",
    "beginTaskPerformance",
    "bindTaskPerformanceTrace",
    "writingJobUsesEvents",
    "startWritingJob"
  ], context);

  functions.startWritingJob(
    { _clickTimestamp: 10, _clickToFeedbackMs: 101 },
    "word.smart_write",
    "smartWrite",
    "doc-a",
    "A.docx"
  );
  functions.startWritingJob(
    { _clickTimestamp: 20, _clickToFeedbackMs: 202 },
    "word.smart_imitation",
    "smartImitation",
    "doc-b",
    "B.docx"
  );

  pendingRequests[1].resolve({ traceId: "trace-b", data: { jobId: "job-b", status: "queued" } });
  await Promise.resolve();
  pendingRequests[0].resolve({ traceId: "trace-a", data: { jobId: "job-a", status: "queued" } });
  await Promise.resolve();

  const recordA = functions.getTaskPerformance("job-a", "trace-a");
  const recordB = functions.getTaskPerformance("job-b", "trace-b");
  assert.strictEqual(recordA.clickToFeedbackMs, 101);
  assert.strictEqual(recordB.clickToFeedbackMs, 202);
  assert.strictEqual(recordA.clickToAdapterAcceptedMs, 50);
  assert.strictEqual(recordB.clickToAdapterAcceptedMs, 30);
  assert.notStrictEqual(recordA, recordB);
}

testConcurrentWritingPerformanceStaysIsolated().then(() => {
  console.log("Word writing background job contracts passed");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
