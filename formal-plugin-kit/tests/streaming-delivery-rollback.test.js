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

test("1. taskpane source contains graceful fallback and no destructive history or config resets on event failure", () => {
  assert.ok(source.includes("pollWritingJobEvents"), "taskpane.js must define pollWritingJobEvents");
  assert.ok(source.includes("pollWritingJob"), "taskpane.js must define pollWritingJob");
  assert.ok(source.includes("stopCurrentConsumer"), "taskpane.js must clean up event consumer on fallback");

  // Verify that error handling in pollWritingJobEvents does not invoke config or history erasure
  const fnBody = functionSource("pollWritingJobEvents");
  assert.ok(fnBody.includes("status === 404"), "must check for 404 status");
  assert.ok(fnBody.includes("nextErrors >= 3"), "must check for 3 consecutive errors");
  assert.ok(!fnBody.includes("clearHistory"), "must not clear history on event error");
  assert.ok(!fnBody.includes("resetConfig"), "must not reset config on event error");
  assert.ok(!fnBody.includes("delete state.activeDirectTaskSelections"), "must not erase activeDirectTaskSelections");
});

test("2. events endpoint 404 gracefully falls back to pollWritingJob preserving state, document session and history", async () => {
  let pollWritingJobCalled = false;
  let fallbackJobId = null;
  let fallbackDocSession = null;

  const initialSelections = { "word.smart_write": { serviceId: "srv-1", modelName: "gpt-4o" } };
  const initialHistory = [{ id: "hist-1", text: "以往成果" }];

  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-session-rollback-1",
    writingJobId: "job-rollback-404",
    writingJobStartedAt: Date.now(),
    writingEventConsumers: {},
    activeDirectTaskSelections: initialSelections,
    historyStore: initialHistory,
  };

  const context = {
    WRITING_EVENTS_WAIT_MS: 100,
    WRITING_EVENTS_REQUEST_TIMEOUT_MS: 500,
    state: state,
    helpers: {
      releaseTaskSlot() {},
      getDocumentSessionId: () => "doc-session-rollback-1",
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    saveWritingActiveJob() {},
    clearWritingActiveJob() {},
    failWritingJob() {
      assert.fail("failWritingJob must NOT be called when events endpoint is 404");
    },
    isFatalWritingPollError: () => false,
    pollWritingJob: (jobId, taskType, mode, resumed, targetDocSession) => {
      pollWritingJobCalled = true;
      fallbackJobId = jobId;
      fallbackDocSession = targetDocSession;
    },
    request: () => {
      const err = new Error("Not Found");
      err.httpStatus = 404;
      return Promise.reject(err);
    },
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-rollback-404", "word.smart_write", "smartWrite", false, "doc-session-rollback-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.ok(pollWritingJobCalled, "pollWritingJob must be called upon 404");
  assert.strictEqual(fallbackJobId, "job-rollback-404");
  assert.strictEqual(fallbackDocSession, "doc-session-rollback-1");

  // Verify config and history remain untouched
  assert.strictEqual(state.activeDirectTaskSelections, initialSelections, "activeDirectTaskSelections must be preserved");
  assert.strictEqual(state.historyStore, initialHistory, "historyStore must be preserved");
  assert.strictEqual(state.documentSessionId, "doc-session-rollback-1", "documentSessionId must be preserved");
});

test("3. events endpoint 3 consecutive non-fatal errors trigger graceful fallback to status polling", async () => {
  let pollWritingJobCalls = 0;
  let attempts = 0;

  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-session-rollback-2",
    writingJobId: "job-rollback-errors",
    writingJobStartedAt: Date.now(),
    writingEventConsumers: {},
  };

  const context = {
    WRITING_EVENTS_WAIT_MS: 10,
    WRITING_EVENTS_REQUEST_TIMEOUT_MS: 50,
    state: state,
    helpers: {
      releaseTaskSlot() {},
      getDocumentSessionId: () => "doc-session-rollback-2",
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    saveWritingActiveJob() {},
    clearWritingActiveJob() {},
    failWritingJob() {
      assert.fail("failWritingJob must NOT be called on transient network retry");
    },
    isFatalWritingPollError: () => false,
    pollWritingJob: () => {
      pollWritingJobCalls++;
    },
    request: () => {
      attempts++;
      const err = new Error("Network glitch");
      err.httpStatus = 500;
      return Promise.reject(err);
    },
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  // Start with 2 errors already recorded so that next error hits >= 3
  fns.pollWritingJobEvents("job-rollback-errors", "word.smart_write", "smartWrite", false, "doc-session-rollback-2", 0, 2);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.strictEqual(attempts, 1, "Should attempt 1 request");
  assert.strictEqual(pollWritingJobCalls, 1, "Should fall back to pollWritingJob on 3rd error");
});

test("4. old wps-addon prototype does not implement streaming or pollWritingJobEvents", () => {
  const repoRoot = path.resolve(__dirname, "../..");
  const addonDir = path.join(repoRoot, "wps-addon", "src");
  if (!fs.existsSync(addonDir)) {
    return;
  }
  const prohibited = ["pollWritingJobEvents", "direct_text_stream", "streamingCapability"];
  function scan(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        scan(full);
      } else if (entry.isFile() && /\.(js|ts|html|json)$/.test(entry.name)) {
        const content = fs.readFileSync(full, "utf8");
        for (const word of prohibited) {
          assert.ok(!content.includes(word), `Found forbidden '${word}' in wps-addon prototype file ${entry.name}`);
        }
      }
    }
  }
  scan(addonDir);
});

test("5. blocking job snapshot bypasses an available events endpoint and persists the protocol", async () => {
  let eventPollCalls = 0;
  let statusPollCalls = 0;
  const savedJobs = [];
  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    directStreamingEnabled: false,
  };
  const context = {
    Date,
    performance: { now: () => 10 },
    WRITING_POLL_REQUEST_TIMEOUT_MS: 35000,
    state,
    helpers: {
      isTaskSlotBusy: () => false,
      claimTaskSlot() {},
      getDocumentSessionId: () => "doc-blocking",
      getDocumentDisplayName: () => "阻塞任务.docx",
    },
    getActiveDocument: () => ({}),
    setModelTaskBusy() {},
    setStatus() {},
    writingTaskLabel: () => "智能编写",
    buildWritingClientJobId: () => "job-blocking",
    setWritingJob() {},
    beginTaskPerformance: () => ({ clickTimestamp: 0, clickToAdapterAcceptedMs: null }),
    setActiveWritingJobRecord() {},
    saveWritingActiveJob: (job) => savedJobs.push(job),
    writingJobPath: () => "/word/smart-write/jobs",
    request: () => Promise.resolve({
      traceId: "trace-blocking",
      data: {
        jobId: "job-blocking",
        status: "running",
        streamingEnabled: false,
      },
    }),
    bindTaskPerformanceTrace() {},
    setTrace() {},
    renderWritingJobProgress() {},
    stopWritingWaitFeedback() {},
    startWritingWaitFeedback() {},
    pollWritingJobEvents() {
      eventPollCalls += 1;
    },
    pollWritingJob() {
      statusPollCalls += 1;
    },
    isFatalWritingPollError: () => false,
    failWritingJob() {
      assert.fail("blocking job must not fail");
    },
  };

  const fns = loadFunctions(["writingJobUsesEvents", "startWritingJob"], context);
  fns.startWritingJob({}, "word.smart_write", "smartWrite", "doc-blocking", "阻塞任务.docx");
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.strictEqual(eventPollCalls, 0);
  assert.strictEqual(statusPollCalls, 1);
  assert.strictEqual(savedJobs[savedJobs.length - 1].streamingEnabled, false);
});
