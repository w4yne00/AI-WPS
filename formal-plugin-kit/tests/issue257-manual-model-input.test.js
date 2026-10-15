const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { wordRoot, etRoot, pptRoot } = require("./support/plugin-roots");

const hosts = [
  { name: "Word", root: wordRoot, prefix: "word-task" },
  { name: "Excel", root: etRoot, prefix: "excel-task" },
  { name: "PPT", root: pptRoot, prefix: "ppt-task" }
];

for (const host of hosts) {
  const html = fs.readFileSync(path.join(host.root, "taskpane.html"), "utf8");
  const css = fs.readFileSync(path.join(host.root, "taskpane.css"), "utf8");
  const js = fs.readFileSync(path.join(host.root, "taskpane.js"), "utf8");
  const helpers = require(path.join(host.root, "taskpane-helpers.js"));

  test(`${host.name} taskpane markup contains custom models panel containers for default and task models`, () => {
    assert.ok(html.includes('id="direct-service-custom-models-panel"'), `missing #direct-service-custom-models-panel in ${host.name}`);
    assert.ok(html.includes(`id="${host.prefix}-custom-models-panel"`), `missing #${host.prefix}-custom-models-panel in ${host.name}`);
    assert.ok(html.includes('class="custom-models-panel"'), `missing .custom-models-panel class in ${host.name}`);
    assert.ok(html.includes('id="direct-service-custom-model-input"'), `missing #direct-service-custom-model-input in ${host.name}`);
    assert.ok(html.includes('id="btn-add-direct-service-custom-model"'), `missing #btn-add-direct-service-custom-model in ${host.name}`);
    assert.ok(html.includes(`id="${host.prefix}-manual-model-input"`), `missing #${host.prefix}-manual-model-input in ${host.name}`);
    assert.ok(html.includes(`id="btn-add-${host.prefix}-manual-model"`), `missing #btn-add-${host.prefix}-manual-model in ${host.name}`);
  });

  test(`${host.name} Apple Design styles for custom models panel and chips`, () => {
    // Inset Grouped card container
    assert.match(css, /\.custom-models-panel[\s\S]*?border-radius:\s*(?:8px|10px|12px)/, `${host.name} custom-models-panel must have rounded corners (8-12px)`);
    assert.match(css, /\.custom-models-panel[\s\S]*?background:/, `${host.name} custom-models-panel must have inset background`);

    // Capsule pill chip styling
    assert.match(css, /\.custom-model-chip[\s\S]*?border-radius:\s*(?:999em|9999px|20px|16px)/, `${host.name} custom-model-chip must have capsule border-radius`);

    // Delete button micro-interaction active scale
    assert.match(css, /\.btn-delete-custom-model:active[\s\S]*?transform:\s*scale\(0\.96\)/, `${host.name} btn-delete-custom-model must have :active { transform: scale(0.96); }`);
  });

  test(`${host.name} renderModelOptionsWithCustom generates catalog, custom, and manual options`, () => {
    assert.strictEqual(typeof helpers.renderModelOptionsWithCustom, "function", `renderModelOptionsWithCustom must be exported in ${host.name}`);

    const mockSelect = { innerHTML: "", value: "" };
    const catalog = ["gpt-4o", "gpt-4o-mini"];
    const custom = ["deepseek-v3", "qwen-max"];

    // 1. Task model dropdown
    helpers.renderModelOptionsWithCustom(mockSelect, catalog, custom, "deepseek-v3", false, "默认: gpt-4o");
    assert.ok(mockSelect.innerHTML.includes('<option value="">继承服务默认模型 (默认: gpt-4o)</option>'));
    assert.ok(mockSelect.innerHTML.includes('<optgroup label="目录模型">'));
    assert.ok(mockSelect.innerHTML.includes('<option value="gpt-4o">gpt-4o</option>'));
    assert.ok(mockSelect.innerHTML.includes('<optgroup label="手填模型">'));
    assert.ok(mockSelect.innerHTML.includes('<option value="deepseek-v3">deepseek-v3</option>'));
    assert.ok(mockSelect.innerHTML.includes('<option value="__manual__">输入 / 管理手填模型...</option>'));
    assert.strictEqual(mockSelect.value, "deepseek-v3");

    // 2. Default model dropdown
    helpers.renderModelOptionsWithCustom(mockSelect, catalog, custom, "", true);
    assert.ok(mockSelect.innerHTML.includes('<option value="">不设置默认模型</option>'));
    assert.ok(mockSelect.innerHTML.includes('<option value="__manual__">输入 / 管理手填模型...</option>'));
    assert.strictEqual(mockSelect.value, "");
  });

  test(`${host.name} helpers validation does NOT block unverified manual models or catalog usable state`, () => {
    const service = {
      id: "svc_test",
      serviceBaseUrl: "https://api.example.com/v1",
      keyConfigured: true,
      modelList: ["catalog-model-1", "catalog-model-2"],
    };

    // Draft validation with custom model when catalog is usable
    const draftResult = helpers.validateTaskModelSelectionDraft(
      {
        serviceId: "svc_test",
        modelName: "custom-unlisted",
        customModel: true,
      },
      { service: service, customModelValidated: false }
    );
    assert.strictEqual(draftResult.ok, true, `${host.name} validateTaskModelSelectionDraft must allow custom model even if catalog is usable`);

    // Readiness validation with unverified custom model
    const readyResult = helpers.validateDirectTaskSelectionReadiness(
      {
        serviceId: "svc_test",
        modelName: "custom-unlisted",
        customModel: true,
        customModelValidated: false,
        modelAvailable: true,
        modelAvailability: "available",
      },
      service,
      { accessMethod: "direct_model" }
    );
    assert.strictEqual(readyResult.ok, true, `${host.name} validateDirectTaskSelectionReadiness must allow unverified custom model`);
  });

  test(`${host.name} taskpane.js includes panel expand and instant API sync logic`, () => {
    assert.match(js, /custom-models/, `${host.name} taskpane.js must reference custom-models endpoint or custom models`);
    assert.match(js, /__manual__/, `${host.name} taskpane.js must handle __manual__ dropdown selection`);
    assert.match(js, /add_custom_model|addCustomModel|\/custom-models/, `${host.name} taskpane.js must handle adding custom model`);
    assert.match(js, /delete_custom_model|deleteCustomModel|\/custom-models\//, `${host.name} taskpane.js must handle deleting custom model`);
  });
}
