const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { wordRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

function loadFunction(name, context = {}) {
  return vm.runInNewContext(`(${functionSource(name)})`, context);
}

assert.ok(html.includes('id="scope-strip" class="scope-strip" role="status" aria-live="polite" aria-atomic="true"'));
assert.ok(js.includes("scopeWatcher: null"));
assert.ok(js.includes("modelTaskBusy: false"));
assert.ok(js.includes("helpers.createWordSelectionWatcher"));
assert.ok(js.includes("intervalMs: 2000"));
assert.ok(js.includes('document.addEventListener("visibilitychange", syncScopeWatcher)'));
assert.ok(functionSource("getWordSelectionEventSource").includes("window.wps && window.wps.ApiEvent"));
assert.ok(functionSource("switchView").includes("syncScopeWatcher()"));

["runSmartWriteAction", "runSmartImitationAction", "runDeterministicFormatReview"].forEach((name) => {
  const source = functionSource(name);
  assert.ok(source.includes("setModelTaskBusy(true)"), `${name} must pause scope reads while running`);
});
assert.ok(functionSource("setWritingJob").includes("setModelTaskBusy(Boolean(jobId))"));
assert.ok(functionSource("completeWritingJob").includes('setWritingJob("", "", "")'));
assert.ok(functionSource("runDeterministicFormatReview").includes("setModelTaskBusy(false)"));
assert.ok(functionSource("runDocumentReview").includes("setModelTaskBusy(true)"));
assert.ok(functionSource("setDocumentReviewJobId").includes("setModelTaskBusy(Boolean(state.documentReviewJobId))"));

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
setScopeLine("识别范围：选中文本");
assert.strictEqual(scopeWriteCount, 2);
setScopeLine("识别范围：选中文本");
assert.strictEqual(scopeWriteCount, 2, "unchanged scope summaries must not rewrite accessible text");

const lifecycleState = {
  currentMode: "smartWrite",
  modelTaskBusy: false,
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
assert.strictEqual(lifecycleState.scopeWatcher.stopCount, 1);
lifecycleDocument.visibilityState = "visible";
syncScopeWatcher();
assert.strictEqual(lifecycleState.scopeWatcher.startCount, 2, "visibility restore should restart with an immediate refresh");
homeViewActive = false;
syncScopeWatcher();
assert.strictEqual(lifecycleState.scopeWatcher.stopCount, 2, "settings view should pause selection reads");
homeViewActive = true;
lifecycleState.modelTaskBusy = true;
syncScopeWatcher();
assert.strictEqual(lifecycleState.scopeWatcher.startCount, 2, "busy tasks should keep selection reads paused");
lifecycleState.modelTaskBusy = false;
syncScopeWatcher();
assert.strictEqual(lifecycleState.scopeWatcher.startCount, 3, "returning idle task view should refresh immediately");

console.log("Word selection watcher tests passed");
