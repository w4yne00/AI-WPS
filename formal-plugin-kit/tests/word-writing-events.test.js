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

// 1. Static assertion that events endpoint and functions exist in source
assert.ok(source.includes("/events?afterSequence="), "taskpane.js must include /events?afterSequence=");
assert.ok(source.includes("pollWritingJobEvents"), "taskpane.js must include pollWritingJobEvents");

async function testEventConsumptionAndTerminalCompletion() {
  const renderedPhases = [];
  let completed = null;
  const requests = [];

  const context = {
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
    pollWritingJob() {
      assert.fail("should not fall back to pollWritingJob on successful event stream");
    },
    isFatalWritingPollError: () => false,
    request(url) {
      requests.push(url);
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
            result: { text: "done" },
            events: [
              { sequence: 3, type: "terminal", phase: "completed", status: "completed" }
            ]
          }
        });
      }
      return Promise.reject(new Error("unexpected request"));
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  // Wait for promise chain
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.deepStrictEqual(renderedPhases, ["preparing", "provider_processing", "completed"]);
  assert.ok(completed);
  assert.strictEqual(completed.jobId, "job-1");
  assert.strictEqual(completed.docSession, "doc-1");
  assert.strictEqual(requests.length, 2);
  assert.ok(requests[0].includes("afterSequence=0"));
  assert.ok(requests[1].includes("afterSequence=2"));
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
    isFatalWritingPollError: () => false,
    request() {
      const err = new Error("Not Found");
      err.status = 404;
      return Promise.reject(err);
    }
  };

  const fns = loadFunctions(["pollWritingJobEvents"], context);
  fns.pollWritingJobEvents("job-404", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.ok(pollCalled, "must fall back to pollWritingJob when events endpoint is 404");
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
  await testFallbackOnThreeConsecutiveErrors();
  console.log("word writing events tests passed");
}

runAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
