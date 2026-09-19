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
    Object.assign({ setTimeout, clearTimeout }, context)
  );
}

// 1. Static assertion that events endpoint and functions exist in source
assert.ok(source.includes("/events?afterSequence="), "taskpane.js must include /events?afterSequence=");
assert.ok(source.includes("pollWritingJobEvents"), "taskpane.js must include pollWritingJobEvents");

async function testEventConsumptionAndTerminalCompletion() {
  const renderedPhases = [];
  let completed = null;
  const requests = [];

  const context = {
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    state: {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-1",
      writingJobId: "job-1",
      writingJobStartedAt: 1000
    },
    helpers: {
      releaseTaskSlot() {}
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    saveWritingActiveJob() {},
    renderWritingJobProgress(evt) {
      renderedPhases.push(evt.phase);
    },
    completeWritingJob(result, traceId, taskType, resumed, mode, jobId, docSession) {
      completed = { result, jobId, docSession };
    },
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    request(url) {
      requests.push(url);
      if (url.endsWith("/job-1?resume=1")) {
        return Promise.resolve({
          traceId: "trace-1",
          data: {
            jobId: "job-1",
            traceId: "trace-1",
            status: "completed",
            result: { rewrittenText: "done" }
          }
        });
      }
      if (url.includes("afterSequence=0")) {
        return Promise.resolve({
          traceId: "trace-1",
          data: {
            jobId: "job-1",
            latestSequence: 2,
            resetRequired: false,
            terminal: false,
            events: [
              { sequence: 1, type: "phase", phase: "preparing", status: "running" },
              { sequence: 2, type: "phase", phase: "provider_processing", status: "running" }
            ]
          }
        });
      }
      if (url.includes("afterSequence=2")) {
        return Promise.resolve({
          traceId: "trace-1",
          data: {
            jobId: "job-1",
            latestSequence: 3,
            resetRequired: false,
            terminal: true,
            status: "completed",
            events: [
              { sequence: 3, type: "terminal", phase: "completed", status: "completed" }
            ]
          }
        });
      }
      return Promise.reject(new Error("unexpected request"));
    }
  };

  const fns = loadFunctions(["pollWritingJob", "pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  // Wait for promise chain
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.deepStrictEqual(renderedPhases, ["preparing", "provider_processing", "completed"]);
  assert.ok(completed);
  assert.strictEqual(completed.result.rewrittenText, "done");
  assert.strictEqual(completed.jobId, "job-1");
  assert.strictEqual(completed.docSession, "doc-1");
  assert.strictEqual(requests.length, 3);
  assert.ok(requests[0].includes("afterSequence=0"));
  assert.ok(requests[1].includes("afterSequence=2"));
  assert.ok(requests[2].endsWith("/job-1?resume=1"));
}

async function testFallbackOn404() {
  let pollCalled = false;
  const context = {
    state: { currentMode: "smartWrite", documentSessionId: "doc-1" },
    helpers: {},
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    pollWritingJob(jobId, taskType, mode, resumed, docSession) {
      pollCalled = true;
      assert.strictEqual(jobId, "job-404");
    },
    failWritingJob() {
      assert.fail("events 404 must degrade instead of failing the task");
    },
    isFatalWritingPollError: (error) => error.adapterCode === "SMART_WRITE_JOB_NOT_FOUND",
    request() {
      const err = new Error("Not Found");
      err.httpStatus = 404;
      err.adapterCode = "SMART_WRITE_JOB_NOT_FOUND";
      return Promise.reject(err);
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-404", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.ok(pollCalled, "must fall back to pollWritingJob when events endpoint is 404");
}

async function testEventsDoNotRenderIntoAnotherDocument() {
  const rendered = [];
  const context = {
    state: {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-b",
      writingJobId: "job-b"
    },
    helpers: {
      getDocumentSessionId: () => "doc-b",
      releaseTaskSlot() {}
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    saveWritingActiveJob() {},
    renderWritingJobProgress(evt) {
      rendered.push(evt.phase);
    },
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    getActiveWritingJobRecord() { return null; },
    setActiveWritingJobRecord() {},
    setWritingJob() {
      assert.fail("another document's task must not clear the current job");
    },
    setModelTaskBusy() {
      assert.fail("another document's task must not clear the current busy state");
    },
    setStatus() {},
    setPlainResult() {},
    writingTaskLabel: () => "智能编写",
    failWritingJob() {},
    pollWritingJob() {},
    isFatalWritingPollError: () => false,
    request() {
      return Promise.resolve({
        traceId: "trace-a",
        data: {
          jobId: "job-a",
          latestSequence: 1,
          terminal: true,
          status: "cancelled",
          events: [
            { sequence: 1, type: "terminal", phase: "cancelled", status: "cancelled" }
          ]
        }
      });
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-a", "word.smart_write", "smartWrite", false, "doc-a", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.deepStrictEqual(rendered, []);
}

async function testOnlyLatestConsumerHandlesSameJob() {
  const pending = [];
  let rendered = 0;
  let cleared = 0;
  const context = {
    state: {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-1",
      writingJobId: "job-1"
    },
    helpers: {
      getDocumentSessionId: () => "doc-1",
      releaseTaskSlot() {}
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    saveWritingActiveJob() {},
    renderWritingJobProgress() {
      rendered += 1;
    },
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {
      cleared += 1;
    },
    setActiveWritingJobRecord() {},
    setWritingJob() {},
    setModelTaskBusy() {},
    setStatus() {},
    setPlainResult() {},
    writingTaskLabel: () => "智能编写",
    failWritingJob() {},
    pollWritingJob() {},
    isFatalWritingPollError: () => false,
    request() {
      return new Promise((resolve) => pending.push(resolve));
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);
  fns.pollWritingJobEvents("job-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  const terminal = {
    traceId: "trace-1",
    data: {
      jobId: "job-1",
      latestSequence: 1,
      terminal: true,
      status: "cancelled",
      events: [
        { sequence: 1, type: "terminal", phase: "cancelled", status: "cancelled" }
      ]
    }
  };
  pending[0](terminal);
  pending[1](terminal);

  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.strictEqual(rendered, 1, "superseded event consumers must ignore late responses");
  assert.strictEqual(cleared, 1, "terminal state must be handled once");
}

function testBackgroundCompletionDoesNotClearAnotherCurrentJob() {
  let globalClears = 0;
  const context = {
    state: {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-b",
      writingJobId: "job-b",
      writingJobTaskType: "word.smart_write",
      historyOpen: true,
      historyUnreadCount: 0,
      latestDocumentPayload: null
    },
    helpers: { releaseTaskSlot() {} },
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    getActiveWritingJobRecord() { return null; },
    setActiveWritingJobRecord() {},
    setWritingJob() {
      globalClears += 1;
    },
    setModelTaskBusy() {},
    setActiveResultRecord() {},
    updateHistoryBadge() {},
    setStatus() {},
    writingTaskLabel: () => "智能编写"
  };

  const fns = loadFunctions(["completeWritingJob"], context);
  fns.completeWritingJob({}, "trace-a", "word.smart_write", false, "smartWrite", "job-a", "doc-a");

  assert.strictEqual(globalClears, 0, "a background job must not clear another document's current job");
}

async function testFallbackOnThreeConsecutiveErrors() {
  let pollCalled = false;
  let attempts = 0;
  const context = {
    state: { currentMode: "smartWrite", documentSessionId: "doc-1" },
    helpers: {},
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    pollWritingJob(jobId) {
      pollCalled = true;
      assert.strictEqual(jobId, "job-err");
    },
    isFatalWritingPollError: () => false,
    request() {
      attempts += 1;
      return Promise.reject(new Error("Network connection lost"));
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  // Start with 2 prior consecutive errors
  fns.pollWritingJobEvents("job-err", "word.smart_write", "smartWrite", false, "doc-1", 0, 2);

  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.strictEqual(attempts, 1);
  assert.ok(pollCalled, "must fall back to pollWritingJob after 3 consecutive errors");
}

async function runAll() {
  await testEventConsumptionAndTerminalCompletion();
  await testFallbackOn404();
  await testEventsDoNotRenderIntoAnotherDocument();
  await testOnlyLatestConsumerHandlesSameJob();
  testBackgroundCompletionDoesNotClearAnotherCurrentJob();
  await testFallbackOnThreeConsecutiveErrors();
  console.log("word writing events tests passed");
}

runAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
