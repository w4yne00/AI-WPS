const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadFunction(source, name, context) {
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf("\n  function ", start + 1);
  assert.ok(start >= 0 && end > start);
  return vm.runInNewContext(`(${source.slice(start, end)})`, context);
}

for (const [host, directory, task] of [
  ["Word", "wps-ai-assistant_1.0.0", "word.smart_write"],
  ["Word", "wps-ai-assistant_1.0.0", "word.format_review"],
  ["Excel", "wps-ai-assistant-et_1.0.0", "excel.analysis"],
  ["PPT", "wps-ai-assistant-wpp_1.0.0", "ppt.slide_assistant"]
]) {
  const root = path.join(__dirname, "..", directory);
  const source = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  for (const controller of [undefined, AbortController]) {
    for (const phase of ["headers", "body"]) {
      test(`${task} validation releases the UI when ${phase} stall, AbortController=${Boolean(controller)}`, async () => {
        const status = { textContent: "" };
        const timers = new Map();
        const draft = { serviceId: "direct_svc_1", modelName: "model", customModel: false };
        const state = { configurationMutationsAllowed: true, modelTasksAllowed: true,
          taskModelSelections: {}, taskApiKeys: {}, workflowProfileSelections: {} };
        let serial = 0;
        let finished = false;
        let resume;
        let fetchCount = 0;
        const stalled = new Promise(resolve => { resume = resolve; });
        const context = {
          state, ADAPTER_BASE_URL: "http://adapter.test", AbortController: controller,
          helpers: require(path.join(root, "taskpane-helpers.js")), TASK_API_KEY_DEFS: [],
          getTaskModelSelectionDraft: () => draft,
          getSettingsWorkflowTaskType: () => task,
          findDirectService: () => ({ id: draft.serviceId, modelList: ["model"], defaultModel: "model", keyConfigured: true }),
          byId: id => id.endsWith("-model-select") ? { value: "model" } : status,
          setWorkflowProfileMutationBusy: busy => { state.workflowProfileMutationBusy = busy; },
          setWorkflowMutationBusy: busy => { state.workflowProfileMutationBusy = busy; },
          setStatus: message => { status.textContent = message; },
          describeFetchError: error => error.message,
          fetch: () => {
            fetchCount += 1;
            return phase === "headers" ? stalled : Promise.resolve({ ok: true, json: () => stalled });
          },
          setTimeout: (fn, delay) => { timers.set(++serial, { fn, delay }); return serial; },
          clearTimeout: id => timers.delete(id)
        };
        context.request = loadFunction(source, "request", context);
        if (host === "Word") context.formatReviewUsesCatalogConfirm = loadFunction(source, "formatReviewUsesCatalogConfirm", context);
        const action = loadFunction(source, host === "Word" ? "saveTaskModelSelection" : "validateTaskModelSelection", context);
        const pending = Promise.resolve(action()).catch(() => {}).then(() => { finished = true; });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(state.workflowProfileMutationBusy, true);
        for (const timer of [...timers.values()]) timer.fn();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(finished, true, "validation must settle at its deadline even if fetch ignores abort");
        await pending;
        assert.equal(state.workflowProfileMutationBusy, false);
        assert.match(status.textContent, /超时|超过.*等待/);
        assert.equal(timers.size, 0);
        assert.equal(Object.keys(state.taskModelSelections).length, 0);
        const failureNotice = status.textContent;
        const body = { success: true, data: { success: true, streamingCapability: "validated" } };
        resume(phase === "headers" ? { ok: true, json: async () => body } : body);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(status.textContent, failureNotice, "a late success must not replace the timeout notice");
        assert.equal(fetchCount, 1, "a late success must not activate the expired draft");
      });
    }
  }
  test(`${task} successful validation clears its deadline after parsing the response`, async () => {
    const timers = new Map();
    const context = { state: { configurationMutationsAllowed: true }, ADAPTER_BASE_URL: "http://adapter.test",
      AbortController, setTimeout: fn => { timers.set(1, fn); return 1; }, clearTimeout: id => timers.delete(id),
      fetch: async () => ({ ok: true, json: async () => ({ success: true, data: { success: true } }) }) };
    const request = loadFunction(source, "request", context);
    const result = await request(`/provider/task-model-selections/${task}/validate`, {});
    assert.equal(result.success, true);
    assert.equal(timers.size, 0);
  });
}
