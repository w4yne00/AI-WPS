const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

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

  function pane() {
    const taskType = { Word: "word.smart_write", Excel: "excel.analysis", PPT: "ppt.slide_assistant" }[host.name];
    const service = { id: "direct_svc_test", name: "测试服务", serviceBaseUrl: "https://api.example.com/v1", keyConfigured: true,
      defaultModel: "catalog-model", modelList: ["catalog-model"], customModels: ["org/model"], revision: 1 };
    const state = { directServices: [service], directServiceOperationId: 0, workflowProfileMutationBusy: false,
      workflowTaskType: taskType, taskModelSelections: {}, taskApiKeys: {}, workflowProfileSelections: {},
      directServiceEditor: { open: true, mode: "edit", serviceId: service.id, revision: 1 } };
    const nodes = new Map();
    const node = id => {
      if (!nodes.has(id)) nodes.set(id, { value: "", innerHTML: "", textContent: "", hidden: false,
        querySelectorAll() { return []; }, focus() {} });
      return nodes.get(id);
    };
    node(host.prefix + "-direct-service-select").value = service.id;
    node(host.prefix + "-model-select").value = "org/model";
    node("direct-service-name").value = service.name;
    node("direct-service-url").value = service.serviceBaseUrl;
    node("direct-service-default-model").value = service.defaultModel;
    const calls = [];
    const context = { state, helpers, byId: node, TASK_API_KEY_DEFS: [], EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
      EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill", getSettingsWorkflowTaskType: () => taskType,
      findDirectService: id => state.directServices.find(svc => svc.id === id),
      escapeWorkflowText: helpers.escapeHtml, escaped: helpers.escapeHtml,
      setWorkflowProfileMutationBusy: value => { state.workflowProfileMutationBusy = value; },
      setWorkflowMutationBusy: value => { state.workflowProfileMutationBusy = value; },
      setStatus() {}, describeFetchError: error => error.message, closeDirectServiceEditor() {},
      loadWorkflowProfiles: async () => {}, loadWorkflowProfileForTask: async () => {}, loadProfiles: async () => {},
      loadDirectServices: async () => {},
      request: async (url, payload, options) => {
        calls.push({ url, payload, options });
        if (url.endsWith("/validate")) return { data: { streamingCapability: "validated" } };
        return { data: { taskModelSelection: payload && payload.taskModelSelection,
          directService: Object.assign({}, service, { defaultModel: "", customModels: [], revision: 2 }) } };
      } };
    for (const name of ["getTaskModelSelectionDraft", "saveTaskModelSelection", "handleTaskDirectServiceSelectChange",
      "saveDirectServiceEditor", "renderCustomModelsList", "renderDirectServiceDefaultModelOptions", "syncDirectServiceInMemory", "deleteCustomModel"]) {
      const start = js.indexOf("  function " + name + "(");
      assert.notStrictEqual(start, -1, name);
      const end = js.indexOf("\n  function ", start + 3);
      context[name] = vm.runInNewContext("(" + js.slice(start, end < 0 ? js.length : end) + ")", context);
    }
    return { ...context, node, service, taskType, calls };
  }

  test(`${host.name} saves an untested manual task model without a validation request`, async () => {
    const p = pane();
    await p.saveTaskModelSelection();
    const expectedCalls = host.name === "Word" ? 2 : 1;
    assert.strictEqual(p.calls.length, expectedCalls, p.node(host.prefix + "-model-validation-status").textContent);
    assert.strictEqual(p.calls[0].url, "/provider/direct-services/direct_svc_test/activate");
    assert.strictEqual(p.calls[0].payload.taskModelSelection.modelName, "org/model");
    assert.strictEqual(p.calls[0].payload.taskModelSelection.customModel, true);
    assert.notStrictEqual(p.calls[0].payload.taskModelSelection.customModelValidated, true);
  });

  test(`${host.name} can switch a saved manual task model back to default inheritance`, async () => {
    const p = pane();
    p.state.taskModelSelections[p.taskType] = { serviceId: p.service.id, modelName: "org/model", customModel: true };
    p.node(host.prefix + "-model-select").value = "";
    await p.saveTaskModelSelection();
    const expectedCalls = host.name === "Word" ? 2 : 1;
    assert.strictEqual(p.calls.length, expectedCalls, p.node(host.prefix + "-model-validation-status").textContent);
    const activateCall = p.calls[p.calls.length - 1];
    assert.strictEqual(activateCall.payload.taskModelSelection.modelName, "");
    assert.strictEqual(activateCall.payload.taskModelSelection.customModel, false);
  });

  test(`${host.name} service switch keeps manual entry and the chosen service's saved models`, () => {
    const p = pane();
    p.service.modelList = [];
    p.handleTaskDirectServiceSelectChange();
    assert.ok(p.node(host.prefix + "-model-select").innerHTML.includes('value="__manual__"'));
    assert.ok(p.node(host.prefix + "-model-select").innerHTML.includes('value="org/model"'));
    assert.ok(p.node(host.prefix + "-custom-models-list").innerHTML.includes("org/model"));
  });

  test(`${host.name} cannot save the management entry as a default model`, async () => {
    const p = pane();
    p.node("direct-service-default-model").value = "__manual__";
    await p.saveDirectServiceEditor();
    assert.strictEqual(p.calls.length, 0);
    assert.ok(p.node("direct-service-editor-error").textContent.includes("默认模型"));
    assert.strictEqual(p.state.directServiceEditor.open, true);
  });

  test(`${host.name} opening task model management does not clear a saved override`, async () => {
    const p = pane();
    p.state.taskModelSelections[p.taskType] = { serviceId: p.service.id, modelName: "org/model", customModel: true };
    p.node(host.prefix + "-model-select").value = "__manual__";
    await p.saveTaskModelSelection();
    assert.strictEqual(p.calls.length, 0);
    assert.strictEqual(p.state.taskModelSelections[p.taskType].modelName, "org/model");
    assert.ok(p.node(host.prefix + "-model-validation-status").textContent.includes("模型"));
  });

  test(`${host.name} deletion uses the returned revision for the next editor save`, async () => {
    const p = pane();
    p.service.defaultModel = "org/model";
    p.node("direct-service-default-model").value = "org/model";
    p.deleteCustomModel(p.service.id, "org/model", "direct-service");
    for (let i = 0; i < 8; i++) await Promise.resolve();
    assert.strictEqual(p.calls[0].url, "/provider/direct-services/direct_svc_test/custom-models/org%2Fmodel?expectedRevision=1");
    await p.saveDirectServiceEditor();
    assert.strictEqual(p.calls[1].payload.expectedRevision, 2);
    assert.strictEqual(p.calls[1].payload.defaultModel, "");
  });

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
