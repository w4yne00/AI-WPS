const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../..");
const kitRoot = path.join(repoRoot, "formal-plugin-kit");

test("Word taskpane does not expose legacy direct_model in workflow editor", () => {
  const wordTaskpaneJs = fs.readFileSync(
    path.join(kitRoot, "wps-ai-assistant_1.0.0", "taskpane.js"),
    "utf-8"
  );

  // Workflow editor HTML should not include direct_model option
  assert.ok(
    !wordTaskpaneJs.includes('<option value="direct_model"'),
    "Word workflow editor should not offer direct_model option"
  );

  // Workflow editor should not include direct model specific field rows
  assert.ok(
    !wordTaskpaneJs.includes('class="field model-direct-field"'),
    "Word workflow editor should not render model-direct-field rows"
  );
});

test("Excel taskpane HTML and JS do not expose legacy direct_model in workflow editor", () => {
  const excelTaskpaneHtml = fs.readFileSync(
    path.join(kitRoot, "wps-ai-assistant-et_1.0.0", "taskpane.html"),
    "utf-8"
  );
  const excelTaskpaneJs = fs.readFileSync(
    path.join(kitRoot, "wps-ai-assistant-et_1.0.0", "taskpane.js"),
    "utf-8"
  );

  // HTML should not have direct_model option
  assert.ok(
    !excelTaskpaneHtml.includes('value="direct_model"'),
    "Excel taskpane.html should not offer direct_model option"
  );

  // HTML should not have legacy direct model rows in workflow editor
  assert.ok(
    !excelTaskpaneHtml.includes('id="workflow-editor-model-row"'),
    "Excel taskpane.html should not have workflow-editor-model-row"
  );
  assert.ok(
    !excelTaskpaneHtml.includes('id="workflow-editor-direct-advanced"'),
    "Excel taskpane.html should not have workflow-editor-direct-advanced"
  );
});

test("PPT taskpane HTML and JS do not expose legacy direct_model in workflow editor", () => {
  const pptTaskpaneHtml = fs.readFileSync(
    path.join(kitRoot, "wps-ai-assistant-wpp_1.0.0", "taskpane.html"),
    "utf-8"
  );
  const pptTaskpaneJs = fs.readFileSync(
    path.join(kitRoot, "wps-ai-assistant-wpp_1.0.0", "taskpane.js"),
    "utf-8"
  );

  // HTML should not have direct_model option
  assert.ok(
    !pptTaskpaneHtml.includes('value="direct_model"'),
    "PPT taskpane.html should not offer direct_model option"
  );

  // HTML should not have legacy direct model rows in workflow editor
  assert.ok(
    !pptTaskpaneHtml.includes('id="workflow-editor-model-row"'),
    "PPT taskpane.html should not have workflow-editor-model-row"
  );
  assert.ok(
    !pptTaskpaneHtml.includes('id="workflow-editor-direct-advanced"'),
    "PPT taskpane.html should not have workflow-editor-direct-advanced"
  );
});

test("all hosts disclose pending legacy direct migrations with an admin path", () => {
  [
    "wps-ai-assistant_1.0.0",
    "wps-ai-assistant-et_1.0.0",
    "wps-ai-assistant-wpp_1.0.0"
  ].forEach((packageName) => {
    const root = path.join(kitRoot, packageName);
    const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf-8");
    const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf-8");
    assert.ok(html.includes('id="legacy-direct-pending-status"'));
    assert.ok(js.includes("data.legacyDirectPending"));
    assert.ok(js.includes("pendingConfigurationCount"));
    assert.ok(js.includes("请由管理员通过迁移管理接口处理"));
  });
});
