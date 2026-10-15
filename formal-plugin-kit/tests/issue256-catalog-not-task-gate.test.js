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
