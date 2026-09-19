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

// Ensure the required functions exist in source
assert.ok(source.includes("pollWritingJobEvents"), "taskpane.js must include pollWritingJobEvents");

function createMockElement(id) {
  const el = {
    id,
    hidden: false,
    classList: {
      _classes: new Set(),
      add(cls) { this._classes.add(cls); },
      remove(cls) { this._classes.delete(cls); },
      contains(cls) { return this._classes.has(cls); },
      toggle(cls, force) {
        if (force === undefined) {
          if (this.contains(cls)) { this.remove(cls); return false; }
          this.add(cls); return true;
        }
        if (force) { this.add(cls); return true; }
        this.remove(cls); return false;
      }
    },
    _text: "",
    scrollHeight: 100,
    scrollTop: 0,
    clientHeight: 100
  };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(val) {
      this._text = typeof val === "string" ? val : "";
      this.scrollHeight = 100 + (this._text.length * 50);
    }
  });
  return el;
}

async function testIncrementalPreviewRenderingAndCopySync() {
  const resultOutput = createMockElement("result-output");
  const viewSwitch = createMockElement("result-view-switch");
  const elements = {
    "result-output": resultOutput,
    "result-view-switch": viewSwitch
  };

  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-stream-1",
    writingJobStartedAt: 1000,
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    helpers: {
      getDocumentSessionId: () => "doc-1",
      releaseTaskSlot() {}
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    saveWritingActiveJob() {},
    renderWritingJobProgress() {},
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {},
    completeWritingJob() {},
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    request(url) {
      if (url.includes("afterSequence=0")) {
        return Promise.resolve({
          traceId: "trace-1",
          data: {
            jobId: "job-stream-1",
            latestSequence: 2,
            events: [
              { sequence: 1, type: "delta", delta: "你好，" },
              { sequence: 2, type: "delta", delta: "世界！" }
            ]
          }
        });
      }
      return new Promise(() => {}); // hang
    }
  };

  const fns = loadFunctions([
    "pollWritingJobEvents",
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender"
  ], context);

  fns.pollWritingJobEvents("job-stream-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  // Wait for 50ms render throttle
  await new Promise((resolve) => setTimeout(resolve, 80));

  assert.strictEqual(resultOutput.textContent, "你好，世界！");
  assert.strictEqual(state.copyText, "你好，世界！");
  assert.ok(resultOutput.classList.contains("plain-output"));
  assert.strictEqual(resultOutput.classList.contains("markdown-body"), false);
}

async function testSnapshotRecoveryUsesAuthoritativeText() {
  async function runCase(jobId, payload, expectedText) {
    const resultOutput = createMockElement("result-output");
    const elements = {
      "result-output": resultOutput,
      "result-view-switch": createMockElement("result-view-switch")
    };
    const state = {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-1",
      writingJobId: jobId,
      writingJobStartedAt: 1000,
      writingJobPreviews: {},
      copyText: ""
    };
    let requestCount = 0;
    const context = {
      state,
      WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
      byId(id) { return elements[id] || null; },
      helpers: {
        getDocumentSessionId: () => "doc-1",
        releaseTaskSlot() {}
      },
      getActiveDocument: () => ({}),
      writingJobPath: () => "/word/smart-write/jobs",
      releaseTaskSlotsForJob() {},
      clearWritingActiveJob() {},
      saveWritingActiveJob() {},
      renderWritingJobProgress() {},
      clearWritingPolicyUsage() {},
      hideCompareForSmartImitation() {},
      completeWritingJob() {},
      failWritingJob() {},
      isFatalWritingPollError: () => false,
      request() {
        requestCount += 1;
        if (requestCount === 1) {
          return Promise.resolve({ traceId: "trace-snapshot", data: payload });
        }
        return new Promise(() => {});
      }
    };
    const fns = loadFunctions([
      "pollWritingJobEvents",
      "renderWritingJobPreview",
      "appendWritingJobPreviewDelta",
      "setWritingJobPreviewSnapshot",
      "scheduleWritingJobPreviewRender",
      "flushWritingJobPreviewRender"
    ], context);

    fns.pollWritingJobEvents(jobId, "word.smart_write", "smartWrite", false, "doc-1", 0, 0);
    await new Promise((resolve) => setTimeout(resolve, 80));

    assert.strictEqual(resultOutput.textContent, expectedText);
    assert.strictEqual(state.copyText, expectedText);
  }

  await runCase(
    "job-first-snapshot",
    {
      jobId: "job-first-snapshot",
      latestSequence: 5,
      resetRequired: false,
      previewSnapshot: { text: "已淘汰的前文 + 尾文", latestSequence: 5 },
      events: [
        { sequence: 4, type: "delta", delta: " + " },
        { sequence: 5, type: "delta", delta: "尾文" }
      ]
    },
    "已淘汰的前文 + 尾文"
  );

  await runCase(
    "job-gap-snapshot",
    {
      jobId: "job-gap-snapshot",
      latestSequence: 8,
      resetRequired: true,
      previewSnapshot: { text: "缺口后的完整正文", latestSequence: 8 },
      events: [
        { sequence: 7, type: "delta", delta: "完整" },
        { sequence: 8, type: "delta", delta: "正文" }
      ]
    },
    "缺口后的完整正文"
  );
}

async function testScrollFollowingLogic() {
  const resultOutput = createMockElement("result-output");
  // Set up scrolled to bottom initially: scrollHeight 200, scrollTop 100, clientHeight 100 => remaining 0 <= 30
  resultOutput.scrollHeight = 200;
  resultOutput.scrollTop = 100;
  resultOutput.clientHeight = 100;

  const elements = {
    "result-output": resultOutput,
    "result-view-switch": createMockElement("result-view-switch")
  };

  const state = {
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-scroll-1",
    writingJobPreviews: {}
  };

  const context = {
    state,
    byId(id) { return elements[id] || null; },
    helpers: { getDocumentSessionId: () => "doc-1" },
    getActiveDocument: () => ({}),
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {}
  };

  const fns = loadFunctions([
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender"
  ], context);

  const consumerKey = "word.smart_write::doc-1::job-scroll-1";

  // Delta 1 when at bottom (initial text empty, remaining = 0 <= 30)
  fns.appendWritingJobPreviewDelta(consumerKey, "段落1\n", "word.smart_write", "job-scroll-1", "doc-1", "smartWrite");
  fns.flushWritingJobPreviewRender(consumerKey);

  // Should have scrolled to bottom (scrollTop == scrollHeight)
  assert.strictEqual(resultOutput.scrollTop, resultOutput.scrollHeight);

  // Now user scrolls up: scrollTop set to 20
  resultOutput.scrollTop = 20;
  fns.appendWritingJobPreviewDelta(consumerKey, "段落2\n", "word.smart_write", "job-scroll-1", "doc-1", "smartWrite");
  fns.flushWritingJobPreviewRender(consumerKey);

  // Must preserve scroll position at 20, NOT auto-scroll
  assert.strictEqual(resultOutput.scrollTop, 20);

  // User scrolls back down near bottom: remaining <= 30
  resultOutput.scrollTop = resultOutput.scrollHeight - resultOutput.clientHeight - 10;
  fns.appendWritingJobPreviewDelta(consumerKey, "段落3\n", "word.smart_write", "job-scroll-1", "doc-1", "smartWrite");
  fns.flushWritingJobPreviewRender(consumerKey);

  // Auto-scroll resumes: scrollTop set to scrollHeight
  assert.strictEqual(resultOutput.scrollTop, resultOutput.scrollHeight);
}

async function testPreviewIsolationBetweenDocuments() {
  const resultOutput = createMockElement("result-output");
  const elements = {
    "result-output": resultOutput,
    "result-view-switch": createMockElement("result-view-switch")
  };

  const state = {
    currentMode: "smartWrite",
    documentSessionId: "doc-active",
    writingJobId: "job-doc-active",
    writingJobPreviews: {}
  };

  const context = {
    state,
    byId(id) { return elements[id] || null; },
    helpers: { getDocumentSessionId: () => "doc-active" },
    getActiveDocument: () => ({}),
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {}
  };

  const fns = loadFunctions([
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender"
  ], context);

  // Append delta for another document: doc-other
  const otherKey = "word.smart_write::doc-other::job-doc-other";
  fns.appendWritingJobPreviewDelta(otherKey, "其他文档内容", "word.smart_write", "job-doc-other", "doc-other", "smartWrite");
  fns.flushWritingJobPreviewRender(otherKey);

  // Output must NOT have been updated with other document's content
  assert.strictEqual(resultOutput.textContent, "");

  // Now append for active document
  const activeKey = "word.smart_write::doc-active::job-doc-active";
  fns.appendWritingJobPreviewDelta(activeKey, "当前文档内容", "word.smart_write", "job-doc-active", "doc-active", "smartWrite");
  fns.flushWritingJobPreviewRender(activeKey);

  assert.strictEqual(resultOutput.textContent, "当前文档内容");
}

async function testModeSwitchRestoresPreview() {
  const resultOutput = createMockElement("result-output");
  const elements = {
    "result-output": resultOutput,
    "result-view-switch": createMockElement("result-view-switch")
  };

  const state = {
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-restore-1",
    writingJobPreviews: {
      "word.smart_write::doc-1::job-restore-1": {
        jobId: "job-restore-1",
        taskType: "word.smart_write",
        documentSessionId: "doc-1",
        mode: "smartWrite",
        text: "流式恢复的草稿",
        lastRenderAt: 0,
        renderTimer: null
      }
    }
  };

  const context = {
    state,
    byId(id) { return elements[id] || null; },
    helpers: { getDocumentSessionId: () => "doc-1" },
    getActiveDocument: () => ({}),
    writingTaskLabel: () => "智能编写",
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {}
  };

  const fns = loadFunctions(["renderWritingJobPreview"], context);
  fns.renderWritingJobPreview("word.smart_write::doc-1::job-restore-1");

  assert.strictEqual(resultOutput.textContent, "流式恢复的草稿");
  assert.strictEqual(state.copyText, "流式恢复的草稿");
  assert.ok(resultOutput.classList.contains("plain-output"));
}

async function testTerminalCompletionHandoff() {
  const resultOutput = createMockElement("result-output");
  const viewSwitch = createMockElement("result-view-switch");
  const elements = {
    "result-output": resultOutput,
    "result-view-switch": viewSwitch
  };

  let completedArgs = null;
  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-term-1",
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    helpers: {
      getDocumentSessionId: () => "doc-1",
      releaseTaskSlot() {}
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-write/jobs",
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    saveWritingActiveJob() {},
    renderWritingJobProgress() {},
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {},
    completeWritingJob(result, traceId, taskType, resumed, mode, jobId, docSession) {
      completedArgs = { result, jobId };
    },
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    pollWritingJob(jobId, taskType, mode, resumed, targetDocSession) {
      // Simulate pollWritingJob calling completeWritingJob
      context.completeWritingJob({ rewrittenText: "终态正式文本" }, "trace-term-1", taskType, resumed, mode, jobId, targetDocSession);
    },
    request(url) {
      if (url.includes("afterSequence=0")) {
        return Promise.resolve({
          traceId: "trace-term-1",
          data: {
            jobId: "job-term-1",
            latestSequence: 2,
            terminal: true,
            status: "completed",
            events: [
              { sequence: 1, type: "delta", delta: "正在流式..." },
              { sequence: 2, type: "terminal", phase: "completed", status: "completed" }
            ]
          }
        });
      }
      return Promise.reject(new Error("unexpected url"));
    }
  };

  const fns = loadFunctions([
    "pollWritingJobEvents",
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender"
  ], context);

  fns.pollWritingJobEvents("job-term-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.ok(completedArgs);
  assert.strictEqual(completedArgs.jobId, "job-term-1");
  assert.strictEqual(completedArgs.result.rewrittenText, "终态正式文本");
}

async function main() {
  await testIncrementalPreviewRenderingAndCopySync();
  await testSnapshotRecoveryUsesAuthoritativeText();
  await testScrollFollowingLogic();
  await testPreviewIsolationBetweenDocuments();
  await testModeSwitchRestoresPreview();
  await testTerminalCompletionHandoff();
  console.log("word-writing-streaming tests passed!");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
