const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const root = "formal-plugin-kit/wps-ai-assistant-et_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const helpers = require(`../wps-ai-assistant-et_1.0.0/taskpane-helpers.js`);

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

function loadFunction(name, context = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, context);
}

function testEventFirstWatcherWithFallbackRecovery() {
  let refreshCount = 0;
  let timeoutCallback = null;
  const scheduledTimeouts = [];
  const clearedTimerIds = [];
  let registeredEventName = "";
  let registeredHandler = null;
  let removedEventName = "";
  let nextTimerId = 40;
  const apiEvent = {
    AddApiEventListener(eventName, handler) {
      registeredEventName = eventName;
      registeredHandler = handler;
    },
    RemoveApiEventListener(eventName) {
      removedEventName = eventName;
    }
  };
  const controller = helpers.createExcelSelectionWatcher({
    refresh() { refreshCount += 1; },
    getEventSource() { return apiEvent; },
    setTimeoutFn(callback, intervalMs) {
      timeoutCallback = callback;
      scheduledTimeouts.push(intervalMs);
      nextTimerId += 1;
      return nextTimerId;
    },
    clearTimeoutFn(timerId) { clearedTimerIds.push(timerId); }
  });

  controller.start();
  assert.strictEqual(refreshCount, 1, "start must read the current range immediately");
  assert.strictEqual(registeredEventName, "SheetSelectionChange");
  assert.strictEqual(typeof registeredHandler, "function");
  assert.deepStrictEqual(scheduledTimeouts, [2000]);
  assert.strictEqual(controller.isEventRegistered(), true);

  registeredHandler({ Name: "统计表" }, { Address: "$B$2:$D$8" });
  assert.strictEqual(refreshCount, 2, "host selection events must refresh immediately");

  timeoutCallback();
  assert.strictEqual(refreshCount, 3, "event silence or a missed event must recover through fallback polling");
  assert.ok(scheduledTimeouts.every((value) => value === 2000));

  controller.stop();
  assert.ok(clearedTimerIds.length >= 2);
  assert.strictEqual(removedEventName, "SheetSelectionChange");
  assert.strictEqual(controller.isRunning(), false);
}

function testUnavailableEventsAndTransientReadsRecover() {
  let refreshCount = 0;
  let timeoutCallback = null;
  const controller = helpers.createExcelSelectionWatcher({
    refresh() {
      refreshCount += 1;
      if (refreshCount === 1) throw new Error("ET 选区暂不可读");
    },
    getEventSource() { throw new Error("ET 事件对象不可用"); },
    setTimeoutFn(callback) {
      timeoutCallback = callback;
      return 51;
    },
    clearTimeoutFn() {}
  });

  assert.doesNotThrow(() => controller.start());
  assert.strictEqual(controller.isEventRegistered(), false);
  timeoutCallback();
  assert.strictEqual(refreshCount, 2, "fallback polling must retry after a transient WPS object failure");
  controller.stop();
}

function testRegistrationFallsThroughCompatibleEventSources() {
  let timeoutCallback = null;
  let registeredHandler = null;
  let removedBySuccessfulSource = false;
  const controller = helpers.createExcelSelectionWatcher({
    refresh() {},
    getEventSources() {
      return [
        { AddApiEventListener() { return false; } },
        { AddApiEventListener() { throw new Error("当前入口拒绝注册"); } },
        {
          AddApiEventListener(eventName, handler) {
            assert.strictEqual(eventName, "SheetSelectionChange");
            registeredHandler = handler;
          },
          RemoveApiEventListener(eventName) {
            assert.strictEqual(eventName, "SheetSelectionChange");
            removedBySuccessfulSource = true;
          }
        }
      ];
    },
    setTimeoutFn(callback) {
      timeoutCallback = callback;
      return 61;
    },
    clearTimeoutFn() {}
  });

  controller.start();
  assert.strictEqual(typeof registeredHandler, "function", "registration must continue to later compatible sources");
  assert.strictEqual(controller.isEventRegistered(), true);
  assert.strictEqual(typeof timeoutCallback, "function");
  controller.stop();
  assert.strictEqual(removedBySuccessfulSource, true, "cleanup must target the source that accepted registration");
}

function testTaskpaneLifecycleAndChangedOnlyRendering() {
  assert.ok(html.includes('id="scope-strip" class="scope-strip" role="status" aria-live="polite" aria-atomic="true"'));
  assert.ok(js.includes("helpers.createExcelSelectionWatcher"));
  assert.ok(js.includes("intervalMs: 2000"));
  assert.ok(js.includes('document.addEventListener("visibilitychange", syncScopeWatcher)'));
  assert.ok(functionSource("getExcelSelectionEventSources").includes("window.wps && window.wps.ApiEvent"));
  assert.ok(functionSource("getExcelSelectionEventSources").includes("window.et && window.et.ApiEvent"));
  assert.ok(functionSource("switchView").includes("syncScopeWatcher()"));
  assert.ok(functionSource("setAnalysisBusy").includes("syncScopeWatcher()"));

  const scopeNodes = {
    "scope-line": { textContent: "未检测" },
    "settings-scope-line": { textContent: "未检测" }
  };
  let scopeWriteCount = 0;
  const setScopeLine = loadFunction("setScopeLine", {
    byId(id) { return scopeNodes[id]; },
    setNodeTextIfChanged(node, value) {
      if (node.textContent === value) return false;
      node.textContent = value;
      scopeWriteCount += 1;
      return true;
    }
  });
  setScopeLine("选区 / 统计表 / $B$2:$D$8 / 7 行 / 3 列");
  assert.strictEqual(scopeWriteCount, 2);
  setScopeLine("选区 / 统计表 / $B$2:$D$8 / 7 行 / 3 列");
  assert.strictEqual(scopeWriteCount, 2, "unchanged type, sheet, address and dimensions must not rewrite live text");

  const lifecycleState = {
    busy: false,
    scopeWatcher: {
      running: false,
      startCount: 0,
      stopCount: 0,
      start() { this.running = true; this.startCount += 1; },
      stop() { this.running = false; this.stopCount += 1; },
      isRunning() { return this.running; }
    }
  };
  let homeViewActive = true;
  const lifecycleDocument = { visibilityState: "visible" };
  const isScopeWatcherEligible = loadFunction("isScopeWatcherEligible", {
    state: lifecycleState,
    document: lifecycleDocument,
    byId() { return { classList: { contains() { return homeViewActive; } } }; }
  });
  const syncScopeWatcher = loadFunction("syncScopeWatcher", {
    state: lifecycleState,
    isScopeWatcherEligible
  });

  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.startCount, 1);
  lifecycleDocument.visibilityState = "hidden";
  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.stopCount, 1, "hidden pages must pause WPS object reads");
  lifecycleDocument.visibilityState = "visible";
  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.startCount, 2, "visibility restore must refresh immediately");
  homeViewActive = false;
  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.stopCount, 2, "settings view must pause range reads");
  homeViewActive = true;
  lifecycleState.busy = true;
  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.startCount, 2, "running analysis must keep range reads paused");
  lifecycleState.busy = false;
  syncScopeWatcher();
  assert.strictEqual(lifecycleState.scopeWatcher.startCount, 3, "returning to an idle task view must refresh immediately");
}

function testSubmissionStillReadsTheLiveWorkbook() {
  const runAnalysis = functionSource("runExcelAnalysisAction");
  const extraction = functionSource("extractExcelRange");
  assert.ok(runAnalysis.includes("state.latestExcelPayload = extractExcelRange()"));
  assert.ok(runAnalysis.indexOf("setAnalysisBusy(true)") < runAnalysis.indexOf("extractExcelRange()"));
  assert.ok(extraction.includes("getSelectionRange(app)"), "submission must continue to prefer the live selection");
  assert.ok(extraction.includes("getUsedRange(sheet)"), "submission must keep the UsedRange fallback");
  assert.ok(extraction.includes("readRangeMatrix(range)"), "submission must keep the budgeted matrix reader");
  assert.ok(js.includes("maxRows: 120") && js.includes("maxColumns: 30") && js.includes("maxTotalTextLength: 20000"),
    "the existing analysis data budget must remain unchanged");
}

testEventFirstWatcherWithFallbackRecovery();
testUnavailableEventsAndTransientReadsRecover();
testRegistrationFallsThroughCompatibleEventSources();
testTaskpaneLifecycleAndChangedOnlyRendering();
testSubmissionStillReadsTheLiveWorkbook();

console.log("Excel selection watcher tests passed");
