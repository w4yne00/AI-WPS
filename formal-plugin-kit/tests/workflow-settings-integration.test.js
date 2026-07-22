const assert = require("assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const hosts = [
  {
    name: "Word",
    dir: "wps-ai-assistant_1.0.0",
    tasks: ["word.smart_write", "word.smart_imitation", "word.document_review", "word.format_review"]
  },
  { name: "Excel", dir: "wps-ai-assistant-et_1.0.0", tasks: ["excel.analysis"] },
  { name: "PPT", dir: "wps-ai-assistant-wpp_1.0.0", tasks: ["ppt.slide_assistant"] }
];

const allTasks = hosts.flatMap((host) => host.tasks);

const commonMarkup = [
  'id="workflow-settings-home"',
  'id="workflow-profile-manager"',
  'id="workflow-profile-select"'
];

const removedMarkup = [
  'id="provider-name"',
  'id="provider-api-key"',
  'id="btn-save-api-key"',
  'id="btn-clear-api-key"',
  'id="btn-activate-workflow-profile"'
];

const commonCss = [
  ".workflow-profile-list",
  ".workflow-editor-actions"
];

hosts.forEach((host) => {
  const hostRoot = path.join(ROOT, host.dir);
  const html = fs.readFileSync(path.join(hostRoot, "taskpane.html"), "utf8");
  const css = fs.readFileSync(path.join(hostRoot, "taskpane.css"), "utf8");
  const js = fs.readFileSync(path.join(hostRoot, "taskpane.js"), "utf8");

  commonMarkup.forEach((marker) => {
    assert.ok(html.includes(marker), `${host.name} missing ${marker}`);
  });
  removedMarkup.forEach((marker) => {
    assert.ok(!html.includes(marker), `${host.name} still exposes ${marker}`);
  });
  commonCss.forEach((selector) => {
    assert.ok(css.includes(selector), `${host.name} missing ${selector}`);
  });

  assert.ok(html.includes('id="workflow-task-tabs"'), `${host.name} missing task tabs`);
  host.tasks.forEach((task) => {
    assert.ok(html.includes(`data-workflow-task-tab="${task}"`), `${host.name} missing ${task} tab`);
  });
  allTasks.filter((task) => !host.tasks.includes(task)).forEach((task) => {
    assert.ok(!html.includes(`data-workflow-task-tab="${task}"`), `${host.name} exposes foreign ${task} tab`);
  });
  assert.ok(js.includes("validateWorkflowProfileDraft"), `${host.name} must validate editor drafts`);
  assert.ok(js.includes("shouldActivateNewWorkflowProfile"), `${host.name} must default first-profile activation`);
  assert.ok(js.includes("activateWorkflowProfile"), `${host.name} must support immediate profile activation`);
  assert.ok(!js.includes("function saveProviderApiKey()"), `${host.name} still binds unified-key save`);
  assert.ok(!js.includes("function clearProviderApiKey()"), `${host.name} still binds unified-key clear`);
  assert.ok(!js.includes('request("/provider/api-key"'), `${host.name} still calls unified-key API`);
});

const wordRoot = path.join(ROOT, hosts[0].dir);
const wordHtml = fs.readFileSync(path.join(wordRoot, "taskpane.html"), "utf8");
const wordCss = fs.readFileSync(path.join(wordRoot, "taskpane.css"), "utf8");
const wordJs = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
[
  'id="workflow-task-tabs"',
  'id="workflow-profile-current"'
].forEach((marker) => assert.ok(wordHtml.includes(marker), `Word missing ${marker}`));
[
  'data-workflow-action="create-open"',
  'class="workflow-settings-subpage"',
  "data-workflow-editor-name",
  "data-workflow-editor-note",
  "data-workflow-editor-key",
  "data-workflow-editor-activate",
  '? "create-save" : "edit-save"',
  'data-workflow-action="editor-cancel"'
].forEach((marker) => assert.ok(wordJs.includes(marker), `Word missing dynamic editor marker ${marker}`));
assert.ok(wordJs.includes('window.confirm("确认删除工作流'), "Word must confirm profile deletion");
assert.ok(wordCss.includes(".workflow-settings-subpage"), "Word missing dynamic editor layout");
assert.ok(wordCss.includes(".workflow-profile-empty"), "Word missing empty profile state");

hosts.slice(1).forEach((host) => {
  const hostRoot = path.join(ROOT, host.dir);
  const html = fs.readFileSync(path.join(hostRoot, "taskpane.html"), "utf8");
  const css = fs.readFileSync(path.join(hostRoot, "taskpane.css"), "utf8");
  [
    'id="btn-new-workflow-profile"',
    'id="workflow-editor-view"',
    'id="workflow-editor-name"',
    'id="workflow-editor-note"',
    'id="workflow-editor-key"',
    'id="workflow-editor-activate"',
    'id="btn-save-workflow-editor"',
    'id="btn-cancel-workflow-editor"',
    'id="workflow-switch-feedback"'
  ].forEach((marker) => assert.ok(html.includes(marker), `${host.name} missing ${marker}`));
  [
    ".workflow-profile-list-row",
    ".workflow-profile-note",
    ".workflow-editor-view",
    ".workflow-empty-state"
  ].forEach((selector) => assert.ok(css.includes(selector), `${host.name} missing ${selector}`));
});

const excelHtml = fs.readFileSync(
  path.join(ROOT, "wps-ai-assistant-et_1.0.0", "taskpane.html"),
  "utf8"
);
assert.ok(excelHtml.includes('id="workflow-delete-dialog"'), "Excel must use an explicit delete dialog");

console.log("workflow settings integration tests passed");
