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
    disabled: false,
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

async function testPreviewTruncationShowsStableNotice() {
  let statusMsg = "";
  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-preview-limit",
    writingJobStartedAt: 1000,
    writingJobPreviews: {}
  };
  let requestCount = 0;
  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId: () => null,
    setStatus(message) { statusMsg = message; },
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
        return Promise.resolve({
          data: {
            jobId: "job-preview-limit",
            status: "running",
            latestSequence: 8,
            previewTruncated: true,
            previewSnapshot: {
              text: "已保留的预览正文",
              latestSequence: 8,
              previewTruncated: true
            },
            events: []
          }
        });
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

  fns.pollWritingJobEvents("job-preview-limit", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.ok(statusMsg.includes("512 KiB"));
  assert.ok(statusMsg.includes("后台仍在生成完整结果"));
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

async function testRunningCancelButtonVisibilityAnd100msTransition() {
  const cancelButton = createMockElement("btn-cancel-document-review-job");
  cancelButton.textContent = "取消排队任务";
  const elements = {
    "btn-cancel-document-review-job": cancelButton,
    "result-output": createMockElement("result-output"),
    "status-line": createMockElement("status-line")
  };

  let statusMsg = "";
  const state = {
    writingJobId: "job-cancel-test",
    writingJobTaskType: "word.smart_write",
    writingJobMode: "smartWrite",
    writingJobPreviews: {},
    documentSessionId: "doc-1",
    currentMode: "smartWrite"
  };

  const context = {
    state,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult() {},
    writingTaskLabel: () => "智能编写",
    DOCUMENT_REVIEW_PHASE_TEXT: {},
    helpers: { getDocumentSessionId: () => "doc-1", releaseTaskSlot() {} },
    getActiveDocument: () => ({}),
    request() { return Promise.resolve({ data: { status: "running", phase: "stopping" } }); },
    writingJobPath: () => "/word/smart-write/jobs",
    WRITING_POLL_REQUEST_TIMEOUT_MS: 5000,
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    setActiveWritingJobRecord() {},
    setWritingJob() {},
    setModelTaskBusy() {}
  };

  const fns = loadFunctions([
    "setDocumentReviewCancelVisible",
    "writingJobUsesEvents",
    "renderWritingJobProgress",
    "cancelQueuedWritingJob"
  ], context);

  // 1. Queued with canCancel -> visible, not disabled, text "取消排队任务"
  fns.renderWritingJobProgress({ status: "queued", canCancel: true, queuePosition: 1 }, "word.smart_write", "job-cancel-test");
  assert.strictEqual(cancelButton.hidden, false);
  assert.strictEqual(cancelButton.disabled, false);
  assert.strictEqual(cancelButton.textContent, "取消排队任务");

  // 2. Running blocking task (canCancel: false) -> button hidden
  fns.renderWritingJobProgress({ status: "running", canCancel: false, phase: "provider_processing" }, "word.smart_write", "job-cancel-test");
  assert.strictEqual(cancelButton.hidden, true);

  // 3. Running streaming task (canCancel: true) -> button visible, not disabled, text "停止生成"
  fns.renderWritingJobProgress({ status: "running", canCancel: true, phase: "streaming" }, "word.smart_write", "job-cancel-test");
  assert.strictEqual(cancelButton.hidden, false);
  assert.strictEqual(cancelButton.disabled, false);
  assert.strictEqual(cancelButton.textContent, "停止生成");

  // 4. Click "停止生成" -> immediately (< 100ms) shows "正在停止" and disabled
  const clickStart = Date.now();
  fns.cancelQueuedWritingJob();
  const clickElapsed = Date.now() - clickStart;

  assert.ok(clickElapsed < 100, "UI update on cancel must occur in < 100ms");
  assert.strictEqual(cancelButton.textContent, "正在停止");
  assert.strictEqual(cancelButton.disabled, true);
}

async function testCancelledStreamingJobPreservesPartialPreviewAndDisablesWriteback() {
  const resultOutput = createMockElement("result-output");
  const applyButton = createMockElement("btn-apply");
  applyButton.disabled = false;
  const statusLine = createMockElement("status-line");
  const elements = {
    "result-output": resultOutput,
    "btn-apply": applyButton,
    "status-line": statusLine,
    "result-view-switch": createMockElement("result-view-switch"),
    "btn-cancel-document-review-job": createMockElement("btn-cancel-document-review-job")
  };

  let statusMsg = "";
  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-cancel-preview-1",
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult(text, copyText) {
      resultOutput.textContent = text;
      state.copyText = copyText || text;
    },
    setApplyEnabled(enabled) { applyButton.disabled = !enabled; },
    writingTaskLabel: () => "智能编写",
    helpers: { getDocumentSessionId: () => "doc-1", releaseTaskSlot() {} },
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
      return Promise.resolve({
        data: {
          jobId: "job-cancel-preview-1",
          status: "cancelled",
          terminal: true,
          previewSnapshot: {
            text: "取消前已接收到的正文部分",
            latestSequence: 2
          },
          events: [
            { sequence: 1, type: "delta", delta: "取消前已接收到的正文部分" },
            { sequence: 2, type: "terminal", phase: "cancelled", status: "cancelled" }
          ]
        }
      });
    }
  };

  const fns = loadFunctions([
    "pollWritingJobEvents",
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender",
    "setWritingJobPreviewSnapshot"
  ], context);

  fns.pollWritingJobEvents("job-cancel-preview-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  // Partial preview must be preserved in output and copyText
  assert.strictEqual(resultOutput.textContent, "取消前已接收到的正文部分");
  assert.strictEqual(state.copyText, "取消前已接收到的正文部分");
  // Apply/Writeback button must be disabled
  assert.strictEqual(applyButton.disabled, true);
  // Status must communicate stopped generation
  assert.ok(statusMsg.includes("已停止生成"));
}

async function testFailedStreamingJobPreservesPartialPreviewAndDisablesWriteback() {
  const resultOutput = createMockElement("result-output");
  const applyButton = createMockElement("btn-apply");
  applyButton.disabled = false;
  const elements = {
    "result-output": resultOutput,
    "btn-apply": applyButton,
    "status-line": createMockElement("status-line"),
    "result-view-switch": createMockElement("result-view-switch"),
    "btn-cancel-document-review-job": createMockElement("btn-cancel-document-review-job")
  };

  let statusMsg = "";
  const state = {
    activeTaskSlots: {},
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-fail-preview-1",
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult(text, copyText) {
      resultOutput.textContent = text;
      state.copyText = copyText || text;
    },
    setApplyEnabled(enabled) { applyButton.disabled = !enabled; },
    writingTaskLabel: () => "智能编写",
    helpers: { getDocumentSessionId: () => "doc-1", releaseTaskSlot() {} },
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
      return Promise.resolve({
        data: {
          jobId: "job-fail-preview-1",
          status: "failed",
          terminal: true,
          error: { code: "PROVIDER_MID_STREAM_DISCONNECT", message: "连接断开" },
          previewSnapshot: {
            text: "网络断开前收到的文本",
            latestSequence: 1
          },
          events: [
            { sequence: 1, type: "delta", delta: "网络断开前收到的文本" }
          ]
        }
      });
    }
  };

  const fns = loadFunctions([
    "pollWritingJobEvents",
    "renderWritingJobPreview",
    "appendWritingJobPreviewDelta",
    "scheduleWritingJobPreviewRender",
    "flushWritingJobPreviewRender",
    "setWritingJobPreviewSnapshot"
  ], context);

  fns.pollWritingJobEvents("job-fail-preview-1", "word.smart_write", "smartWrite", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  // Partial preview must be preserved
  assert.strictEqual(resultOutput.textContent, "网络断开前收到的文本");
  assert.strictEqual(state.copyText, "网络断开前收到的文本");
  // Writeback disabled
  assert.strictEqual(applyButton.disabled, true);
  // Status mentions failure and partial preview
  assert.ok(statusMsg.includes("失败") && statusMsg.includes("部分预览"));
}

async function testStatusPollingFallbackPreservesPartialPreview() {
  async function runCase(status) {
    const resultOutput = createMockElement("result-output");
    const applyButton = createMockElement("btn-apply");
    applyButton.disabled = false;
    const jobId = `job-poll-${status}`;
    const previewKey = `word.smart_write::doc-1::${jobId}`;
    let statusMsg = "";
    const state = {
      activeTaskSlots: {},
      currentMode: "smartWrite",
      documentSessionId: "doc-1",
      writingJobId: jobId,
      writingJobPollErrorCount: 0,
      writingJobPreviews: {
        [previewKey]: {
          text: "事件接口降级前收到的正文",
          renderTimer: null
        }
      }
    };
    const context = {
      state,
      WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
      WRITING_POLL_INTERVAL_MS: 3000,
      WRITING_POLL_RETRY_DELAY_MS: 3000,
      request() {
        return Promise.resolve({
          data: {
            status,
            error: status === "failed" ? { message: "连接断开" } : null
          }
        });
      },
      writingJobPath: () => "/word/smart-write/jobs",
      writingTaskLabel: () => "智能编写",
      helpers: {
        getDocumentSessionId: () => "doc-1",
        releaseTaskSlot() {}
      },
      getActiveDocument: () => ({}),
      releaseTaskSlotsForJob() {},
      clearWritingActiveJob() {},
      saveWritingActiveJob() {},
      setActiveWritingJobRecord() {},
      setActiveResultRecord() {},
      setWritingJob() { state.writingJobId = ""; },
      setModelTaskBusy() {},
      setApplyEnabled(enabled) { applyButton.disabled = !enabled; },
      setStatus(message) { statusMsg = message; },
      setPlainResult(text) { resultOutput.textContent = text; },
      setResult(text) { resultOutput.textContent = text; },
      renderWritingJobProgress() {},
      completeWritingJob() {},
      isFatalWritingPollError: () => false,
      describeFetchError: () => "连接断开"
    };
    const fns = loadFunctions(["pollWritingJob", "failWritingJob"], context);

    fns.pollWritingJob(jobId, "word.smart_write", "smartWrite", false, "doc-1");
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.strictEqual(resultOutput.textContent, "事件接口降级前收到的正文");
    assert.strictEqual(applyButton.disabled, true);
    assert.ok(status === "cancelled" ? statusMsg.includes("已停止生成") : statusMsg.includes("部分预览"));
  }

  await runCase("cancelled");
  await runCase("failed");
}

async function testWaitFeedbackTimersDoNotOverrideCancelCapability() {
  const resultOutput = createMockElement("result-output");
  const cancelButton = createMockElement("btn-cancel-document-review-job");
  cancelButton.hidden = true;
  const elements = {
    "result-output": resultOutput,
    "btn-cancel-document-review-job": cancelButton,
    "status-line": createMockElement("status-line")
  };

  let statusMsg = "";
  const state = {
    writingJobId: "job-wait-1",
    documentSessionId: "doc-1",
    writingJobPreviews: {}
  };

  const context = {
    state,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult(text) { resultOutput.textContent = text; },
    writingTaskLabel: () => "智能编写",
    setDocumentReviewCancelVisible(visible, disabled, text) {
      cancelButton.hidden = !visible;
      cancelButton.disabled = Boolean(disabled);
      if (text) cancelButton.textContent = text;
    }
  };

  const fns = loadFunctions([
    "startWritingWaitFeedback"
  ], context);

  let capturedTimers = [];
  const origSetTimeout = setTimeout;

  const fakeContext = Object.assign({}, context, {
    setTimeout(cb, ms) {
      capturedTimers.push({ cb, ms });
      return capturedTimers.length;
    },
    clearTimeout(id) {}
  });

  const customFns = loadFunctions(["startWritingWaitFeedback"], fakeContext);
  const stopWait = customFns.startWritingWaitFeedback("job-wait-1", "word.smart_write");

  // Should register 10000ms and 30000ms timers
  assert.strictEqual(capturedTimers.length, 2);
  const timer10s = capturedTimers.find(t => t.ms === 10000);
  const timer30s = capturedTimers.find(t => t.ms === 30000);
  assert.ok(timer10s, "10s timer must be registered");
  assert.ok(timer30s, "30s timer must be registered");

  // Trigger 10s timer
  timer10s.cb();
  assert.ok(statusMsg.includes("模型响应较慢"));
  assert.ok(!statusMsg.includes("%"), "Must not display fake percentage");

  // Trigger 30s timer
  timer30s.cb();
  assert.ok(statusMsg.includes("继续等待"));
  assert.strictEqual(cancelButton.hidden, true, "blocking task must not gain a stop button at 30s");
  assert.ok(!statusMsg.includes("%"), "Must not display fake percentage");

  // An authoritative streaming status may already expose the button; the timer must preserve it.
  cancelButton.hidden = false;
  cancelButton.textContent = "停止生成";
  timer30s.cb();
  assert.strictEqual(cancelButton.hidden, false);
  assert.strictEqual(cancelButton.textContent, "停止生成");
}

async function testSmartImitationStreamingPreviewAndReadOnlyNoApply() {
  const resultOutput = createMockElement("result-output");
  const viewSwitch = createMockElement("result-view-switch");
  const applyButton = createMockElement("btn-apply");
  applyButton.hidden = true;
  applyButton.disabled = true;
  const compareButton = createMockElement("btn-result-compare");
  compareButton.hidden = true;

  const elements = {
    "result-output": resultOutput,
    "result-view-switch": viewSwitch,
    "btn-apply": applyButton,
    "btn-result-compare": compareButton
  };

  const state = {
    activeTaskSlots: {},
    currentMode: "smartImitation",
    documentSessionId: "doc-1",
    writingJobId: "job-im-stream-1",
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
    writingJobPath: () => "/word/smart-imitation/jobs",
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() {},
    saveWritingActiveJob() {},
    renderWritingJobProgress() {},
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {
      compareButton.hidden = true;
    },
    completeWritingJob() {},
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    request(url) {
      if (url.includes("afterSequence=0")) {
        return Promise.resolve({
          data: {
            jobId: "job-im-stream-1",
            latestSequence: 2,
            previewSnapshot: {
              text: "仿写增量第一段。",
              latestSequence: 1
            },
            events: [
              {
                sequence: 2,
                type: "delta",
                delta: "仿写增量第二段。"
              }
            ]
          }
        });
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

  fns.pollWritingJobEvents("job-im-stream-1", "word.smart_imitation", "smartImitation", false, "doc-1", 0, 0);

  // Allow timers / RAF to flush
  await new Promise((resolve) => setTimeout(resolve, 60));

  assert.strictEqual(
    resultOutput.textContent,
    "仿写增量第一段。仿写增量第二段。",
    "Streaming text must be rendered incrementally for smart imitation"
  );
  assert.strictEqual(
    state.copyText,
    "仿写增量第一段。仿写增量第二段。",
    "Copy text must be in sync with incremental preview text"
  );
  assert.ok(resultOutput.classList.contains("plain-output"), "Must use plain-output style");
  assert.strictEqual(viewSwitch.hidden, true, "Result view switch must remain hidden during generation");
  assert.strictEqual(compareButton.hidden, true, "Compare button must remain hidden for smart imitation");
  assert.strictEqual(applyButton.hidden, true, "Apply button must remain hidden for smart imitation");
  assert.strictEqual(applyButton.disabled, true, "Apply button must remain disabled for smart imitation");
}

async function testSmartImitationCancellationPreservesPartialPreviewAndZeroApply() {
  const resultOutput = createMockElement("result-output");
  const applyButton = createMockElement("btn-apply");
  applyButton.hidden = true;
  applyButton.disabled = true;
  const statusLine = createMockElement("status-line");
  const elements = {
    "result-output": resultOutput,
    "btn-apply": applyButton,
    "status-line": statusLine,
    "result-view-switch": createMockElement("result-view-switch"),
    "btn-cancel-document-review-job": createMockElement("btn-cancel-document-review-job")
  };

  let statusMsg = "";
  let slotReleased = false;
  let activeJobCleared = false;

  const state = {
    activeTaskSlots: {},
    currentMode: "smartImitation",
    documentSessionId: "doc-1",
    writingJobId: "job-im-cancel-1",
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult(text, copyText) {
      resultOutput.textContent = text;
      state.copyText = copyText || text;
    },
    setApplyEnabled(enabled) { applyButton.disabled = !enabled; },
    writingTaskLabel: (tt) => tt === "word.smart_imitation" ? "智能仿写" : "智能编写",
    helpers: {
      getDocumentSessionId: () => "doc-1",
      releaseTaskSlot() { slotReleased = true; }
    },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-imitation/jobs",
    releaseTaskSlotsForJob() {},
    clearWritingActiveJob() { activeJobCleared = true; },
    saveWritingActiveJob() {},
    renderWritingJobProgress() {},
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {},
    completeWritingJob() {},
    failWritingJob() {},
    isFatalWritingPollError: () => false,
    request(url) {
      return Promise.resolve({
        data: {
          jobId: "job-im-cancel-1",
          status: "cancelled",
          terminal: true,
          previewSnapshot: {
            text: "仿写取消前已接收部分",
            latestSequence: 2
          },
          events: [
            {
              sequence: 3,
              type: "status",
              status: "cancelled",
              phase: "stopping"
            }
          ]
        }
      });
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

  fns.pollWritingJobEvents("job-im-cancel-1", "word.smart_imitation", "smartImitation", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.ok(
    statusMsg.includes("智能仿写已停止生成，保留已生成部分预览（只读，不可写回）。"),
    `Unexpected status message: ${statusMsg}`
  );
  assert.strictEqual(
    resultOutput.textContent,
    "仿写取消前已接收部分",
    "Cancelled job must preserve partial text"
  );
  assert.strictEqual(applyButton.disabled, true, "Apply button must remain disabled on cancellation");
  assert.strictEqual(slotReleased, true, "Task slot must be released");
  assert.strictEqual(activeJobCleared, true, "Active writing job must be cleared");
}

async function testSmartImitationFailurePreservesPartialPreviewAndZeroApply() {
  const resultOutput = createMockElement("result-output");
  const applyButton = createMockElement("btn-apply");
  applyButton.hidden = true;
  applyButton.disabled = true;
  const elements = {
    "result-output": resultOutput,
    "btn-apply": applyButton,
    "result-view-switch": createMockElement("result-view-switch"),
    "btn-cancel-document-review-job": createMockElement("btn-cancel-document-review-job")
  };

  let statusMsg = "";
  const state = {
    activeTaskSlots: {},
    currentMode: "smartImitation",
    documentSessionId: "doc-1",
    writingJobId: "job-im-fail-1",
    writingJobPreviews: {},
    copyText: ""
  };

  const context = {
    state,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    byId(id) { return elements[id] || null; },
    setStatus(msg) { statusMsg = msg; },
    setPlainResult(text, copyText) {
      resultOutput.textContent = text;
      state.copyText = copyText || text;
    },
    setApplyEnabled(enabled) { applyButton.disabled = !enabled; },
    writingTaskLabel: (tt) => tt === "word.smart_imitation" ? "智能仿写" : "智能编写",
    helpers: { getDocumentSessionId: () => "doc-1", releaseTaskSlot() {} },
    getActiveDocument: () => ({}),
    writingJobPath: () => "/word/smart-imitation/jobs",
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
      return Promise.resolve({
        data: {
          jobId: "job-im-fail-1",
          status: "failed",
          terminal: true,
          error: { code: "PROVIDER_DISCONNECT", message: "上游连接中断" },
          previewSnapshot: {
            text: "仿写中断前收到的文字",
            latestSequence: 1
          },
          events: [
            { sequence: 2, type: "status", status: "failed" }
          ]
        }
      });
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

  fns.pollWritingJobEvents("job-im-fail-1", "word.smart_imitation", "smartImitation", false, "doc-1", 0, 0);

  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.ok(
    statusMsg.includes("智能仿写失败：上游连接中断，已保留已接收内容部分预览（只读，不可写回）。"),
    `Unexpected failure status message: ${statusMsg}`
  );
  assert.strictEqual(resultOutput.textContent, "仿写中断前收到的文字");
  assert.strictEqual(applyButton.disabled, true);
}

async function testSmartWriteAndSmartImitationIsolation() {
  const resultOutput = createMockElement("result-output");
  const elements = {
    "result-output": resultOutput,
    "result-view-switch": createMockElement("result-view-switch")
  };

  const state = {
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-write-1",
    writingJobPreviews: {
      "word.smart_write::doc-1::job-write-1": {
        jobId: "job-write-1",
        taskType: "word.smart_write",
        documentSessionId: "doc-1",
        mode: "smartWrite",
        text: "智能编写独立文本",
        lastRenderAt: 0,
        renderTimer: null
      },
      "word.smart_imitation::doc-1::job-im-1": {
        jobId: "job-im-1",
        taskType: "word.smart_imitation",
        documentSessionId: "doc-1",
        mode: "smartImitation",
        text: "智能仿写独立文本",
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
    writingTaskLabel: (tt) => tt === "word.smart_imitation" ? "智能仿写" : "智能编写",
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {}
  };

  const fns = loadFunctions(["renderWritingJobPreview"], context);

  // 1. When currentMode is smartWrite, job-write-1 renders
  fns.renderWritingJobPreview("word.smart_write::doc-1::job-write-1");
  assert.strictEqual(resultOutput.textContent, "智能编写独立文本");

  // If wrong consumerKey is called (imitation consumer key while in smartWrite), preview must NOT render
  resultOutput.textContent = "";
  fns.renderWritingJobPreview("word.smart_imitation::doc-1::job-im-1");
  assert.strictEqual(resultOutput.textContent, "", "Cross-mode preview must not render into wrong view");

  // 2. Switch mode to smartImitation
  state.currentMode = "smartImitation";
  state.writingJobId = "job-im-1";
  fns.renderWritingJobPreview("word.smart_imitation::doc-1::job-im-1");
  assert.strictEqual(resultOutput.textContent, "智能仿写独立文本");
}

function assertNoCountdown(text) {
  assert.ok(!text.includes("总耗时"), `streaming preview must not show elapsed countdown: ${text}`);
  assert.ok(!/\d+\s*秒/.test(text), `streaming preview must not count seconds: ${text}`);
}

function loadWritingProgress(resultOutput, state) {
  const elements = {
    "result-output": resultOutput,
    "btn-cancel-document-review-job": createMockElement("btn-cancel-document-review-job"),
    "status-line": createMockElement("status-line")
  };
  const context = {
    state,
    byId(id) { return elements[id] || null; },
    setStatus() {},
    setPlainResult(text) {
      resultOutput.hidden = false;
      resultOutput.classList.add("plain-output");
      resultOutput.textContent = text || "";
    },
    setDocumentReviewCancelVisible() {},
    writingTaskLabel(taskType) {
      return taskType === "word.smart_imitation" ? "智能仿写" : "智能编写";
    },
    DOCUMENT_REVIEW_PHASE_TEXT: {
      streaming: "正在生成内容",
      provider_processing: "模型后台处理",
      stopping: "正在停止任务"
    },
    helpers: { getDocumentSessionId: () => state.documentSessionId },
    getActiveDocument: () => ({})
  };
  return loadFunctions(["writingJobUsesEvents", "renderWritingJobProgress"], context);
}

async function testStreamingResultPreviewUsesInteractivePromptInsteadOfCountdown() {
  const streamingOutput = createMockElement("result-output");
  const streamingState = {
    directStreamingEnabled: true,
    documentSessionId: "doc-1",
    writingJobId: "job-stream-wait",
    writingJobPreviews: {}
  };
  const streamingFns = loadWritingProgress(streamingOutput, streamingState);
  streamingFns.renderWritingJobProgress({
    status: "running",
    phase: "streaming",
    streamingEnabled: true,
    canCancel: true,
    elapsedSeconds: 18
  }, "word.smart_write", "job-stream-wait");

  assert.ok(
    streamingOutput.textContent.includes("正在生成增量文本预览"),
    `expected interactive streaming prompt, got: ${streamingOutput.textContent}`
  );
  assert.ok(streamingOutput.textContent.includes("逐步出现"), streamingOutput.textContent);
  assert.ok(streamingOutput.textContent.includes("停止生成"), streamingOutput.textContent);
  assert.ok(streamingOutput.textContent.includes("还不是最终结果"), streamingOutput.textContent);
  assertNoCountdown(streamingOutput.textContent);
  assert.ok(
    streamingOutput.classList.contains("streaming-preview-wait"),
    "streaming wait must mark the preview as live"
  );

  streamingState.currentMode = "smartWrite";
  streamingState.writingJobPreviews["word.smart_write::doc-1::job-stream-wait"] = {
    jobId: "job-stream-wait",
    taskType: "word.smart_write",
    documentSessionId: "doc-1",
    mode: "smartWrite",
    text: "逐步出现的正文"
  };
  const previewFns = loadFunctions(["renderWritingJobPreview"], {
    state: streamingState,
    byId(id) { return id === "result-output" ? streamingOutput : createMockElement(id); },
    helpers: { getDocumentSessionId: () => "doc-1" },
    getActiveDocument: () => ({}),
    clearWritingPolicyUsage() {},
    hideCompareForSmartImitation() {}
  });
  previewFns.renderWritingJobPreview("word.smart_write::doc-1::job-stream-wait");
  assert.strictEqual(streamingOutput.textContent, "逐步出现的正文");
  assert.ok(!streamingOutput.classList.contains("streaming-preview-wait"));

  const imitationOutput = createMockElement("result-output");
  const imitationFns = loadWritingProgress(imitationOutput, {
    directStreamingEnabled: true,
    documentSessionId: "doc-1",
    writingJobId: "job-im-wait",
    writingJobPreviews: {}
  });
  imitationFns.renderWritingJobProgress({
    status: "running",
    phase: "provider_waiting",
    streamingEnabled: true,
    elapsedSeconds: 9
  }, "word.smart_imitation", "job-im-wait");
  assert.ok(imitationOutput.textContent.includes("正在生成增量文本预览"), imitationOutput.textContent);
  assertNoCountdown(imitationOutput.textContent);

  const flaggedOutput = createMockElement("result-output");
  const flaggedFns = loadWritingProgress(flaggedOutput, {
    directStreamingEnabled: true,
    documentSessionId: "doc-1",
    writingJobId: "job-flag-wait",
    writingJobPreviews: {}
  });
  flaggedFns.renderWritingJobProgress({
    status: "running",
    phase: "provider_connecting",
    elapsedSeconds: 4
  }, "word.smart_write", "job-flag-wait");
  assert.ok(flaggedOutput.textContent.includes("正在生成增量文本预览"), flaggedOutput.textContent);
  assertNoCountdown(flaggedOutput.textContent);

  const queuedOutput = createMockElement("result-output");
  const queuedFns = loadWritingProgress(queuedOutput, {
    directStreamingEnabled: true,
    documentSessionId: "doc-1",
    writingJobId: "job-queue-wait",
    writingJobPreviews: {}
  });
  queuedFns.renderWritingJobProgress({
    status: "queued",
    streamingEnabled: true,
    queuePosition: 2,
    elapsedSeconds: 6,
    canCancel: true
  }, "word.smart_write", "job-queue-wait");
  assert.ok(queuedOutput.textContent.includes("逐步出现"), queuedOutput.textContent);
  assert.ok(queuedOutput.textContent.includes("2"), queuedOutput.textContent);
  assertNoCountdown(queuedOutput.textContent);

  const blockingOutput = createMockElement("result-output");
  const blockingFns = loadWritingProgress(blockingOutput, {
    directStreamingEnabled: false,
    documentSessionId: "doc-1",
    writingJobId: "job-block-wait",
    writingJobPreviews: {}
  });
  blockingFns.renderWritingJobProgress({
    status: "running",
    phase: "provider_processing",
    streamingEnabled: false,
    elapsedSeconds: 12
  }, "word.smart_write", "job-block-wait");
  assert.ok(blockingOutput.textContent.includes("总耗时：12 秒"), blockingOutput.textContent);
  assert.ok(!blockingOutput.textContent.includes("增量文本预览"), blockingOutput.textContent);
  assert.ok(!blockingOutput.classList.contains("streaming-preview-wait"));

  const keptOutput = createMockElement("result-output");
  keptOutput.textContent = "已经出现的正文";
  const keptState = {
    directStreamingEnabled: true,
    documentSessionId: "doc-1",
    writingJobId: "job-live",
    writingJobPreviews: {
      "word.smart_write::doc-1::job-live": { text: "已经出现的正文" }
    }
  };
  const keptFns = loadWritingProgress(keptOutput, keptState);
  keptFns.renderWritingJobProgress({
    status: "running",
    phase: "streaming",
    streamingEnabled: true,
    elapsedSeconds: 21
  }, "word.smart_write", "job-live");
  assert.strictEqual(keptOutput.textContent, "已经出现的正文");
  assert.ok(!keptOutput.classList.contains("streaming-preview-wait"));

  const fallbackOutput = createMockElement("result-output");
  const fallbackState = {
    directStreamingEnabled: true,
    currentMode: "smartWrite",
    documentSessionId: "doc-1",
    writingJobId: "job-fallback",
    writingJobPollErrorCount: 0,
    writingJobPreviews: {}
  };
  const fallbackFns = loadFunctions(["writingJobUsesEvents", "renderWritingJobProgress", "pollWritingJob"], {
    state: fallbackState,
    WRITING_POLL_REQUEST_TIMEOUT_MS: 10000,
    WRITING_POLL_INTERVAL_MS: 3000,
    byId(id) { return id === "result-output" ? fallbackOutput : createMockElement(id); },
    setStatus() {},
    setPlainResult(text) {
      fallbackOutput.classList.add("plain-output");
      fallbackOutput.textContent = text || "";
    },
    setDocumentReviewCancelVisible() {},
    writingTaskLabel() { return "智能编写"; },
    DOCUMENT_REVIEW_PHASE_TEXT: { provider_processing: "模型后台处理" },
    helpers: { getDocumentSessionId: () => "doc-1" },
    getActiveDocument: () => ({}),
    request() {
      return Promise.resolve({
        data: {
          status: "running",
          phase: "provider_processing",
          streamingEnabled: true,
          elapsedSeconds: 15
        }
      });
    },
    writingJobPath: () => "/word/smart-write/jobs",
    saveWritingActiveJob() {},
    scheduleWritingPoll() {}
  });
  fallbackFns.pollWritingJob("job-fallback", "word.smart_write", "smartWrite", false, "doc-1");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(fallbackOutput.textContent.includes("总耗时：15 秒"), fallbackOutput.textContent);
  assert.ok(!fallbackOutput.textContent.includes("增量文本预览"), fallbackOutput.textContent);

  const clearedOutput = createMockElement("result-output");
  clearedOutput.classList.add("streaming-preview-wait");
  const clearFns = loadFunctions(["setPlainResult"], {
    state: { copyText: "" },
    byId(id) { return id === "result-output" ? clearedOutput : null; }
  });
  clearFns.setPlainResult("排队任务已取消，未调用模型后台。");
  assert.strictEqual(clearedOutput.textContent, "排队任务已取消，未调用模型后台。");
  assert.ok(!clearedOutput.classList.contains("streaming-preview-wait"));
}

async function main() {
  await testIncrementalPreviewRenderingAndCopySync();
  await testSnapshotRecoveryUsesAuthoritativeText();
  await testPreviewTruncationShowsStableNotice();
  await testScrollFollowingLogic();
  await testPreviewIsolationBetweenDocuments();
  await testModeSwitchRestoresPreview();
  await testTerminalCompletionHandoff();
  await testRunningCancelButtonVisibilityAnd100msTransition();
  await testCancelledStreamingJobPreservesPartialPreviewAndDisablesWriteback();
  await testFailedStreamingJobPreservesPartialPreviewAndDisablesWriteback();
  await testStatusPollingFallbackPreservesPartialPreview();
  await testWaitFeedbackTimersDoNotOverrideCancelCapability();
  await testSmartImitationStreamingPreviewAndReadOnlyNoApply();
  await testSmartImitationCancellationPreservesPartialPreviewAndZeroApply();
  await testSmartImitationFailurePreservesPartialPreviewAndZeroApply();
  await testSmartWriteAndSmartImitationIsolation();
  await testStreamingResultPreviewUsesInteractivePromptInsteadOfCountdown();
  console.log("word-writing-streaming tests passed!");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
