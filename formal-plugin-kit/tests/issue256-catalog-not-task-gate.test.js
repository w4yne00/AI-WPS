const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { wordRoot, etRoot, pptRoot } = require("./support/plugin-roots");

const hosts = [
  ["word", wordRoot],
  ["excel", etRoot],
  ["ppt", pptRoot]
];

function catalogStatus(root, service) {
  const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  const start = js.indexOf("  function formatDirectServiceCatalogStatus(");
  const end = js.indexOf("\n  function ", start + 1);
  const helpers = require(path.join(root, "taskpane-helpers.js"));
  return vm.runInNewContext(
    `${js.slice(start, end)}\nformatDirectServiceCatalogStatus(${JSON.stringify(service)});`,
    {
      helpers,
      getDirectServiceCatalogState: helpers.getDirectServiceCatalogState
    }
  );
}

for (const [host, root] of hosts) {
  const helpers = require(path.join(root, "taskpane-helpers.js"));
  const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");

  test(`${host} saved model stays usable when the catalog is expired or missing`, () => {
    const service = {
      id: "direct_svc_1",
      keyConfigured: true,
      defaultModel: "gpt-4o",
      modelCatalog: {
        status: "expired",
        cacheStatus: "expired",
        fetchedAt: "2026-09-01T00:00:00Z",
        models: ["gpt-4o"]
      }
    };
    const selection = {
      serviceId: "direct_svc_1",
      modelName: "glm-kept",
      customModel: false,
      modelAvailable: false,
      modelUnavailableReason: "cache_expired"
    };
    const ready = helpers.validateDirectTaskSelectionReadiness(
      selection,
      service,
      { accessMethod: "direct_model" }
    );
    assert.strictEqual(ready.ok, true, ready.error);

    const missing = helpers.validateDirectTaskSelectionReadiness(
      { ...selection, modelUnavailableReason: "disappeared" },
      {
        ...service,
        modelCatalog: {
          status: "available",
          cacheStatus: "valid",
          usableForSelection: true,
          models: ["other-model"]
        }
      },
      { accessMethod: "direct_model" }
    );
    assert.strictEqual(missing.ok, true, missing.error);

    if (host !== "excel") {
      const noKey = helpers.validateDirectTaskSelectionReadiness(
        selection,
        { ...service, keyConfigured: false },
        { accessMethod: "direct_model" }
      );
      assert.strictEqual(noKey.ok, false);
    }
  });

  test(`${host} settings show a manual refresh control and the last fetch time`, () => {
    assert.ok(html.includes('id="btn-refresh-direct-service-models"'));
    const text = catalogStatus(root, {
      modelCatalog: {
        status: "expired",
        cacheStatus: "expired",
        fetchedAt: "2026-09-01T00:00:00Z",
        models: ["gpt-4o"]
      }
    });
    assert.match(text, /2026-09-01T00:00:00Z/);
    assert.doesNotMatch(text, /不能发起新任务/);
    assert.doesNotMatch(js, /不能发起新任务/);
  });
}

for (const [host, root] of hosts) {
  for (const sameService of [false, true]) {
    test(`${host} legacy custom model ${sameService ? "cannot be cleared accidentally" : "can switch service and inherit its default"}`, async () => {
      const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
      const start = js.indexOf("  function saveTaskModelSelection(");
      const end = js.indexOf("\n  function ", start + 1);
      const taskType = { word: "word.smart_write", excel: "excel.analysis", ppt: "ppt.slide_assistant" }[host];
      const saved = { serviceId: "direct_svc_old", modelName: "legacy-custom", customModel: true, customModelValidated: true };
      const draft = { serviceId: sameService ? "direct_svc_old" : "direct_svc_new", modelName: "", customModel: false };
      const state = { taskModelSelections: { [taskType]: saved }, taskApiKeys: {}, workflowProfileSelections: {} };
      const status = { textContent: "" };
      const requests = [];
      const context = {
        state, helpers: require(path.join(root, "taskpane-helpers.js")),
        getTaskModelSelectionDraft: () => draft,
        getSettingsWorkflowTaskType: () => taskType,
        findDirectService: () => ({ id: draft.serviceId, defaultModel: "new-default", keyConfigured: true }),
        byId: () => status,
        setStatus() {}, setWorkflowMutationBusy() {}, setWorkflowProfileMutationBusy() {},
        loadWorkflowProfiles: async () => {}, loadWorkflowProfileForTask: async () => {},
        loadProfiles: async () => {}, loadDirectServices: async () => {},
        describeFetchError: error => error.message,
        TASK_API_KEY_DEFS: [], EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant", EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
        request: async (url, body) => {
          requests.push({ url, body });
          return { data: { taskModelSelection: { ...body.taskModelSelection } } };
        }
      };
      const save = vm.runInNewContext(`(${js.slice(start, end)})`, context);
      let error;
      try { await save(); } catch (caught) { error = caught; }
      if (sameService) {
        assert.strictEqual(requests.length, 0);
        assert.strictEqual(state.taskModelSelections[taskType], saved);
        assert.match(status.textContent, /不能用空模型覆盖/);
      } else {
        assert.ifError(error);
        assert.strictEqual(requests.length, 1, status.textContent);
        assert.strictEqual(requests[0].url, "/provider/direct-services/direct_svc_new/activate");
        assert.strictEqual(requests[0].body.taskModelSelection.modelName, "");
        assert.strictEqual(state.taskModelSelections[taskType].serviceId, "direct_svc_new");
        assert.strictEqual(state.taskModelSelections[taskType].modelName, "");
      }
    });
  }
}

for (const [host, root] of hosts) {
  test(`${host} validated legacy custom model remains ready after catalog refresh`, () => {
    const helpers = require(path.join(root, "taskpane-helpers.js"));
    for (const models of [["legacy-custom"], ["other-model"]]) {
      const service = {
        id: "direct_svc_1", keyConfigured: true, defaultModel: "default-model",
        modelCatalog: { status: "available", cacheStatus: "valid", usableForSelection: true, manualModelAllowed: false, models }
      };
      const selection = {
        serviceId: service.id, modelName: "legacy-custom", customModel: true,
        customModelValidated: true, modelAvailable: true, modelAvailability: "available"
      };
      const ready = helpers.validateDirectTaskSelectionReadiness(selection, service, { accessMethod: "direct_model" });
      assert.strictEqual(ready.ok, true, ready.error);
      const unverified = helpers.validateDirectTaskSelectionReadiness(
        { ...selection, customModelValidated: false, modelAvailable: false, modelAvailability: "unverified", modelUnavailableReason: "validation_required" },
        service, { accessMethod: "direct_model" }
      );
      assert.strictEqual(unverified.ok, false);
    }
  });
}
