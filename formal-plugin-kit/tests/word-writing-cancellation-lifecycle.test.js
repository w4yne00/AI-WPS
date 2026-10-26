const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));
const source = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
const names = [
  "getWritingActiveJobStorageKey", "getWritingDocTaskKey", "getActiveWritingJobRecord",
  "isCurrentWritingJob", "setActiveWritingJobRecord", "loadWritingActiveJob",
  "saveWritingActiveJob", "clearWritingActiveJob", "releaseTaskSlotsForJob",
  "writingTaskLabel", "writingJobPath", "writingJobUsesEvents", "setWritingJob",
  "setDocumentReviewCancelVisible", "renderWritingJobProgress", "pollWritingJob",
  "pollWritingJobEvents", "resumeWritingActiveJob", "cancelQueuedWritingJob", "startWritingJob"
];

function memoryStorage() {
  const records = new Map();
  return {
    get length() { return records.size; },
    key(index) { return [...records.keys()][index] || null; },
    getItem(key) { return records.get(key) || null; },
    setItem(key, value) { records.set(key, value); },
    removeItem(key) { records.delete(key); }
  };
}

function harness(taskType, storage = memoryStorage()) {
  const mode = taskType === "word.smart_imitation" ? "smartImitation" : "smartWrite";
  const state = { activeTaskSlots: {}, currentMode: mode, documentSessionId: "doc-1", directStreamingEnabled: false };
  const button = { hidden: true, disabled: false, textContent: "" };
  const output = { textContent: "", classList: { add() {}, remove() {} } };
  const pending = [];
  const scheduled = [];
  const timers = new Map();
  let generated = 0;
  const context = {
    state, Date, window: { localStorage: storage },
    WRITING_ACTIVE_JOB_STORAGE_KEY: "ai-wps-writing-active-job-v1", FRONTEND_BUILD_VERSION: "test",
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000, WRITING_POLL_INTERVAL_MS: 3000,
    DOCUMENT_REVIEW_PHASE_TEXT: {},
    helpers: { ...helpers, getDocumentSessionId: () => state.documentSessionId },
    getActiveDocument: () => ({}),
    getCurrentWorkflowTaskType: () => taskType,
    byId: (id) => id === "btn-cancel-document-review-job" ? button : id === "result-output" ? output : null,
    setModelTaskBusy(busy) { state.busy = busy; },
    setStatus(text) { state.status = text; },
    setPlainResult(text, copyText) { output.textContent = text; state.copyText = copyText || text; },
    setApplyEnabled(enabled) { state.applyEnabled = enabled; },
    setTrace() {}, renderWorkflowProfileStrip() {},
    beginTaskPerformance: () => ({}), bindTaskPerformanceTrace() {},
    buildWritingClientJobId: () => "new-" + (++generated),
    isFatalWritingPollError: () => false,
    describeFetchError: (error) => error.message,
    scheduleWritingPoll(...args) { scheduled.push(args); },
    setTimeout(callback) {
      scheduled.push(callback);
      timers.set(scheduled.length, callback);
      return scheduled.length;
    },
    clearTimeout(id) { timers.delete(id); },
    request(url, payload, options) {
      return new Promise((resolve, reject) => pending.push({ url, payload, options, resolve, reject }));
    }
  };
  const declarations = names.map((name) => {
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `missing function ${name}`);
    const end = source.indexOf("\n  function ", start + 1);
    return source.slice(start, end < 0 ? source.length : end);
  }).join("\n");
  const fns = vm.runInNewContext(`(function () { ${declarations}; return {${names.join(",")}}; })()`, context);
  function activate(jobId = "job-1", streamingEnabled = true, doc = "doc-1") {
    const record = { jobId, taskType, mode, documentSessionId: doc, streamingEnabled, startedAt: 1000 };
    fns.setActiveWritingJobRecord(taskType, doc, record);
    helpers.claimTaskSlot(state.activeTaskSlots, "wps", taskType, doc, jobId);
    fns.saveWritingActiveJob(record);
    if (doc === state.documentSessionId) fns.setWritingJob(jobId, taskType, mode);
  }
  return { fns, state, button, output, pending, scheduled, timers, setTimeout: context.setTimeout, storage, taskType, mode, activate };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));
function eventPayload(overrides = {}) {
  return { data: {
    jobId: "job-1", status: "running", phase: "streaming", streamingEnabled: true,
    canCancel: true, cancelRequested: false, terminal: false, latestSequence: 2,
    previewSnapshot: { text: "", status: "running", phase: "provider_processing", latestSequence: 0 },
    events: [{ sequence: 1, type: "phase", status: "running", phase: "provider_processing", canCancel: false }],
    ...overrides
  } };
}

for (const taskType of ["word.smart_write", "word.smart_imitation"]) {
  test(`${taskType}: latest event authority keeps stop visible despite old phases and snapshots`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    h.pending[0].resolve(eventPayload());
    await settle();
    assert.equal(h.button.hidden, false);
    assert.equal(h.button.disabled, false);
    assert.equal(h.button.textContent, "停止生成");
    h.pending[1].resolve(eventPayload({ cancelRequested: true, phase: "stopping", canCancel: false }));
    await settle();
    assert.equal(h.button.hidden, false);
    assert.equal(h.button.disabled, true);
    assert.equal(h.button.textContent, "正在停止");
    h.pending[2].resolve(eventPayload({ canCancel: false, previewSnapshot: null, events: [] }));
    await settle();
    assert.equal(h.button.hidden, true, "empty event batches still carry authoritative capabilities");
  });

  test(`${taskType}: events preserve streaming on reopen even after the global switch changes`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    h.pending[0].resolve(eventPayload());
    await settle();
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-1").streamingEnabled, true);
    const reopened = harness(taskType, h.storage);
    reopened.fns.resumeWritingActiveJob();
    assert.ok(reopened.pending[0].url.includes("/events?"));
    assert.equal(reopened.fns.getActiveWritingJobRecord(taskType, "doc-1").streamingEnabled, true);
    reopened.pending[0].resolve(eventPayload());
    await settle();
    assert.equal(reopened.button.hidden, false);
  });

  test(`${taskType}: status fallback preserves streaming, including legacy responses without the flag`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJob("job-1", taskType, h.mode, false, "doc-1");
    h.pending[0].resolve({ data: { status: "running", streamingEnabled: true } });
    await settle();
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-1").streamingEnabled, true);
    h.fns.pollWritingJob("job-1", taskType, h.mode, false, "doc-1");
    h.pending[1].resolve({ data: { status: "running" } });
    await settle();
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-1").streamingEnabled, true);
  });

  test(`${taskType}: non-streaming task stays non-cancellable and resumes status polling`, async () => {
    const h = harness(taskType);
    h.state.directStreamingEnabled = true;
    h.activate("job-1", false);
    h.fns.pollWritingJob("job-1", taskType, h.mode, false, "doc-1");
    h.pending[0].resolve({ data: { status: "running", streamingEnabled: false, canCancel: false } });
    await settle();
    assert.equal(h.button.hidden, true);
    const reopened = harness(taskType, h.storage);
    reopened.state.directStreamingEnabled = true;
    reopened.fns.resumeWritingActiveJob();
    assert.ok(reopened.pending[0].url.endsWith("?resume=1"));
    assert.equal(reopened.fns.getActiveWritingJobRecord(taskType, "doc-1").streamingEnabled, false);
    h.fns.renderWritingJobProgress({ status: "running", streamingEnabled: true }, taskType, "job-1");
    assert.equal(h.button.hidden, true, "missing cancellation capability must not be guessed");
  });

  test(`${taskType}: submitting a new task replaces malformed saved storage`, () => {
    const h = harness(taskType);
    h.storage.setItem(h.fns.getWritingActiveJobStorageKey(taskType, "doc-1"), "malformed");
    h.activate();
    const stored = h.fns.loadWritingActiveJob(taskType, "doc-1");
    assert.ok(stored, "new submission must replace unreadable storage");
    assert.equal(stored.jobId, "job-1");
  });

  test(`${taskType}: confirmed cancel rejects both in-flight event and status responses`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    h.fns.pollWritingJob("job-1", taskType, h.mode, false, "doc-1");
    h.fns.cancelQueuedWritingJob();
    h.pending[2].resolve({ data: { status: "cancelled" } });
    await settle();
    const stoppedText = h.output.textContent;
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-1"), null);
    assert.equal(h.state.busy, false);
    h.pending[0].resolve(eventPayload());
    h.pending[1].resolve({ data: { status: "running", streamingEnabled: true, canCancel: true } });
    await settle();
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-1"), null, "old response must not resurrect storage");
    assert.equal(h.pending.length, 3, "old events must not restart polling");
    assert.equal(h.scheduled.length, 0, "old status must not schedule polling");
    assert.equal(h.output.textContent, stoppedText);
    assert.equal(h.button.hidden, true);
    h.fns.startWritingJob({}, taskType, h.mode, "doc-1");
    assert.equal(h.pending.length, 4, "confirmed terminal state releases the task slot");
    assert.equal(h.state.writingJobId, "new-1");
  });

  test(`${taskType}: DELETE confirmation clears the consumer and preview timer while retaining read-only text`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    const consumerKey = `${taskType}::doc-1::job-1`;
    const otherKey = `${taskType}::doc-2::job-2`;
    const timer = h.setTimeout(() => { h.output.textContent = "迟到的预览"; });
    const otherPreview = { text: "其他文档预览", renderTimer: h.setTimeout(() => {}) };
    h.state.writingJobPreviews = {
      [consumerKey]: { text: "取消前的正文", renderTimer: timer },
      [otherKey]: otherPreview
    };
    h.state.writingEventConsumers[otherKey] = 1;
    h.fns.cancelQueuedWritingJob();
    h.pending[1].resolve({ data: { status: "cancelled" } });
    await settle();
    assert.equal(h.state.writingEventConsumers[consumerKey], undefined, "stopped consumer must be removed");
    assert.equal(h.state.writingJobPreviews[consumerKey], undefined, "stopped preview must be released");
    assert.equal(h.timers.has(timer), false, "pending preview render must be cancelled");
    assert.equal(h.state.writingEventConsumers[otherKey], 1);
    assert.equal(h.state.writingJobPreviews[otherKey], otherPreview);
    assert.equal(h.output.textContent, "取消前的正文");
    assert.equal(h.state.copyText, "取消前的正文");
    assert.equal(h.state.applyEnabled, false);
    for (const callback of h.timers.values()) callback();
    h.pending[0].resolve(eventPayload());
    await settle();
    assert.equal(h.output.textContent, "取消前的正文", "late timers and events must not overwrite stopped text");
    assert.equal(h.pending.length, 2);
    assert.deepEqual(Object.keys(h.state.activeTaskSlots), []);
  });

  test(`${taskType}: cancellation acknowledgement keeps the slot until terminal confirmation`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    h.fns.cancelQueuedWritingJob();
    assert.equal(h.button.disabled, true);
    h.fns.startWritingJob({}, taskType, h.mode, "doc-1");
    assert.equal(h.pending.length, 2);
    assert.equal(h.state.busy, true, "a rejected duplicate must retain the running task's busy state");
    h.pending[1].resolve({ data: { status: "running", phase: "stopping", cancelRequested: true, canCancel: false } });
    await settle();
    h.fns.startWritingJob({}, taskType, h.mode, "doc-1");
    assert.equal(h.pending.length, 2);
    assert.equal(h.state.writingJobId, "job-1");
    h.pending[0].resolve(eventPayload({ terminal: true, status: "cancelled", phase: "cancelled", canCancel: false, events: [] }));
    await settle();
    h.fns.startWritingJob({}, taskType, h.mode, "doc-1");
    assert.equal(h.pending.length, 3);
    assert.equal(h.state.writingJobId, "new-1");
  });

  test(`${taskType}: old document responses cannot alter the current document or newer task`, async () => {
    const h = harness(taskType);
    h.activate();
    h.fns.pollWritingJobEvents("job-1", taskType, h.mode, false, "doc-1", 0, 0);
    h.fns.cancelQueuedWritingJob();
    h.state.documentSessionId = "doc-2";
    h.activate("job-2", false, "doc-2");
    h.pending[1].resolve({ data: { status: "cancelled" } });
    h.pending[0].resolve(eventPayload());
    await settle();
    assert.equal(h.state.writingJobId, "job-2");
    assert.equal(h.state.busy, true);
    assert.equal(h.output.textContent, "");
    h.fns.pollWritingJob("job-2", taskType, h.mode, false, "doc-2");
    h.activate("job-3", true, "doc-2");
    h.pending.at(-1).resolve({ data: { status: "cancelled" } });
    await settle();
    assert.equal(h.state.writingJobId, "job-3");
    assert.equal(h.fns.loadWritingActiveJob(taskType, "doc-2").jobId, "job-3");
  });
}
