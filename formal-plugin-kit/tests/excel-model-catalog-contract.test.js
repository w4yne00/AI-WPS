const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

test("Excel exposes separate service validation and task cost-risk disclosure", () => {
  assert.ok(html.includes('id="btn-validate-direct-service"'));
  assert.ok(html.includes('id="direct-service-validation-status"'));
  assert.ok(html.includes('id="excel-task-model-cost-warning"'));
  assert.ok(js.includes("function validateDirectService("));
  assert.ok(js.includes("mayIncurModelCost"));
});

test("Direct service catalog state is normalized and controls manual model entry", () => {
  assert.strictEqual(typeof helpers.getDirectServiceCatalogState, "function");
  assert.strictEqual(typeof helpers.isDirectServiceManualModelAllowed, "function");

  const available = helpers.getDirectServiceCatalogState({
    modelList: ["gpt-4o"],
    modelListStatus: "available",
    modelListCacheStatus: "valid",
    modelListFetchStatus: "success",
    modelListFetchedAt: "2026-09-12T00:00:00Z",
    modelListError: null
  });
  assert.strictEqual(available.status, "available");
  assert.strictEqual(available.cacheStatus, "valid");
  assert.strictEqual(available.manualModelAllowed, false);
  assert.strictEqual(helpers.isDirectServiceManualModelAllowed({ modelCatalog: available }), false);

  const unavailable = helpers.getDirectServiceCatalogState({
    modelList: [],
    modelListStatus: "unavailable",
    modelListCacheStatus: "empty",
    modelListFetchStatus: "error",
    modelListError: { code: "DIRECT_SERVICE_MODELS_UNAVAILABLE", message: "无目录" }
  });
  assert.strictEqual(unavailable.manualModelAllowed, true);
  assert.strictEqual(helpers.isDirectServiceManualModelAllowed({ modelCatalog: unavailable }), true);
});

test("Task selection draft rejects manual model while catalog is usable", () => {
  const blocked = helpers.validateTaskModelSelectionDraft(
    { serviceId: "direct_svc_1", modelName: "manual-model", customModel: true },
    { service: { modelCatalog: { status: "available", cacheStatus: "valid", usableForSelection: true } } }
  );
  assert.strictEqual(blocked.valid, false);
  assert.ok(blocked.error.includes("目录"));

  const allowed = helpers.validateTaskModelSelectionDraft(
    { serviceId: "direct_svc_1", modelName: "manual-model", customModel: true },
    { service: { modelCatalog: { status: "expired", cacheStatus: "expired", manualModelAllowed: true } } }
  );
  assert.strictEqual(allowed.valid, true);

  const invalidated = helpers.validateTaskModelSelectionDraft(
    { serviceId: "direct_svc_1", modelName: "gpt-4o", customModel: false },
    { service: { modelCatalog: { status: "unavailable", cacheStatus: "invalidated", fetchStatus: "not_attempted" } } }
  );
  assert.strictEqual(invalidated.valid, false);
  assert.ok(invalidated.error.includes("失效"));
});

test("Direct task readiness blocks unavailable catalog before task submission", () => {
  assert.strictEqual(typeof helpers.validateDirectTaskSelectionReadiness, "function");

  const blocked = helpers.validateDirectTaskSelectionReadiness(
    {
      serviceId: "direct_svc_1",
      modelName: "gpt-4o",
      customModel: false,
      modelAvailable: false,
      modelUnavailableReason: "cache_expired"
    },
    {
      modelCatalog: {
        status: "expired",
        cacheStatus: "expired",
        manualModelAllowed: true
      }
    },
    { accessMethod: "direct_model" }
  );
  assert.strictEqual(blocked.ok, false);
  assert.ok(blocked.error.includes("过期"));

  const workflow = helpers.validateDirectTaskSelectionReadiness(
    {},
    null,
    { accessMethod: "workflow_platform" }
  );
  assert.strictEqual(workflow.ok, true);
  assert.strictEqual(workflow.applicable, false);
});

test("Taskpane task submitters include direct-model readiness preflight", () => {
  assert.ok(js.includes("function validateActiveDirectTaskSelection("));
  assert.ok(js.includes("validateActiveDirectTaskSelection(\"excel.analysis\")"));
  assert.ok(js.includes("validateActiveDirectTaskSelection(\"excel.formula_assistant\")"));
  assert.ok(js.includes("validateActiveDirectTaskSelection(\"excel.smart_fill\")"));
});

test("Direct service validation stays separate from task validation", async () => {
  const vm = require("node:vm");
  const start = js.indexOf("function validateDirectService(");
  const end = js.indexOf("\n  function openDirectServiceDeleteDialog(", start);
  assert.ok(start >= 0 && end > start);
  const validationState = {
    directServiceEditor: { serviceId: "direct_svc_1", revision: 4 },
    workflowProfileMutationBusy: false
  };
  let requestSeen = null;
  const vmContext = {
    state: validationState,
    byId(id) {
      return {
        "direct-service-validation-status": { textContent: "" },
        "direct-service-models-status": { textContent: "" }
      }[id] || null;
    },
    setWorkflowMutationBusy(value) {
      validationState.workflowProfileMutationBusy = value;
    },
    request(url, payload) {
      requestSeen = { url, payload };
      return Promise.resolve({
        data: {
          validationScope: "service",
          modelCatalogAvailable: false,
          directService: {
            id: "direct_svc_1",
            revision: 5,
            modelCatalog: {
              status: "unavailable",
              cacheStatus: "empty",
              manualModelAllowed: true
            }
          }
        }
      });
    },
    loadDirectServices() {
      return Promise.resolve({ success: true });
    },
    getDirectServiceCatalogState: helpers.getDirectServiceCatalogState,
    formatDirectServiceCatalogStatus() {
      return "目录不可用；可使用高级手填";
    },
    describeFetchError(error) {
      return String(error);
    }
  };
  const validateDirectService = vm.runInNewContext(
    `(${js.slice(start, end)})`,
    vmContext
  );
  await validateDirectService();
  assert.ok(requestSeen.url.endsWith("/direct_svc_1/validate"));
  assert.strictEqual(requestSeen.url.includes("task-model"), false);
  assert.strictEqual(validationState.directServiceEditor.revision, 5);
});
