const assert = require("assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const hosts = [
  {
    name: "Word",
    dir: "wps-ai-assistant_1.0.0",
    task: "word.smart_write",
    label: "智能编写",
    tabsLabel: "Word 任务",
    hasKnowledge: true
  },
  {
    name: "Excel",
    dir: "wps-ai-assistant-et_1.0.0",
    task: "excel.analysis",
    label: "智能分析",
    tabsLabel: "Excel 任务",
    hasKnowledge: false
  },
  {
    name: "PPT",
    dir: "wps-ai-assistant-wpp_1.0.0",
    task: "ppt.slide_assistant",
    label: "智能总结",
    tabsLabel: "PPT 任务",
    hasKnowledge: false
  }
];

const commonIds = [
  "task-title",
  "btn-open-settings",
  "health-indicator",
  "btn-run-primary",
  "result-output",
  "settings-status-line",
  "provider-readiness-badge",
  "btn-edit-provider-url",
  "workflow-help-button",
  "workflow-help-popover",
  "workflow-task-tabs",
  "diagnostics-disclosure",
  "diagnostics-section",
  "btn-refresh-diagnostics",
  "btn-copy-diagnostics"
];

function elementWithId(html, tag, id) {
  const match = html.match(new RegExp(`<${tag}\\b[^>]*\\bid="${id}"[^>]*>`, "i"));
  assert.ok(match, `missing <${tag}>#${id}`);
  return match[0];
}

hosts.forEach((host) => {
  const html = fs.readFileSync(path.join(ROOT, host.dir, "taskpane.html"), "utf8");

  commonIds.forEach((id) => {
    assert.ok(html.includes(`id="${id}"`), `${host.name} missing #${id}`);
  });
  assert.ok(
    html.includes('id="provider-summary-card" class="settings-card model-interface-card"'),
    `${host.name} missing model interface card contract`
  );
  assert.ok(html.includes('class="model-interface-heading"'), `${host.name} missing model interface heading`);
  assert.ok(html.includes('class="model-interface-row"'), `${host.name} missing model interface row`);
  assert.ok(
    html.includes('id="provider-readiness-badge" class="readiness-badge is-unavailable" aria-live="polite">无法检测'),
    `${host.name} missing initial provider readiness state`
  );
  assert.ok(
    html.includes('id="provider-summary-url" class="provider-url-summary" title="">未配置接口地址'),
    `${host.name} missing initial provider URL summary`
  );
  assert.ok(
    html.includes('id="btn-edit-provider-url" class="text-action"') &&
      html.includes('id="btn-edit-provider-url" class="text-action" type="button">修改</button>'),
    `${host.name} missing provider edit action`
  );

  const helpButton = elementWithId(html, "button", "workflow-help-button");
  assert.ok(helpButton.includes('aria-expanded="false"'), `${host.name} help button must start collapsed`);
  assert.ok(helpButton.includes('aria-controls="workflow-help-popover"'), `${host.name} help button missing controls`);
  assert.ok(
    html.includes('id="workflow-help-popover" class="workflow-help-popover" role="tooltip" hidden'),
    `${host.name} missing hidden workflow help popover`
  );
  assert.ok(
    html.includes("每项任务可保存多个工作流，可在任务页选择当前使用的工作流。"),
    `${host.name} missing workflow help copy`
  );

  const taskTabs = elementWithId(html, "div", "workflow-task-tabs");
  assert.ok(taskTabs.includes('role="tablist"'), `${host.name} task tabs missing tablist role`);
  assert.ok(taskTabs.includes(`aria-label="${host.tabsLabel}"`), `${host.name} task tabs label mismatch`);
  assert.ok(
    new RegExp(`<button\\b[^>]*role="tab"[^>]*data-workflow-task-tab="${host.task.replace(".", "\\.")}"[^>]*aria-selected="true"[^>]*>${host.label}</button>`).test(html),
    `${host.name} missing selected ${host.task} tab`
  );

  assert.ok(!html.includes('id="btn-refresh"'), `${host.name} still includes #btn-refresh`);
  assert.ok(
    !html.includes("每项任务可保存多个工作流</span>"),
    `${host.name} still renders persistent multi-workflow copy`
  );
  assert.strictEqual(
    html.includes('id="enterprise-knowledge-summary-card"'),
    host.hasKnowledge,
    `${host.name} enterprise knowledge isolation mismatch`
  );
});

const wordHtml = fs.readFileSync(path.join(ROOT, hosts[0].dir, "taskpane.html"), "utf8");
[
  "word.smart_write",
  "word.smart_imitation",
  "word.document_review",
  "word.format_review"
].forEach((task) => {
  assert.ok(wordHtml.includes(`data-workflow-task-tab="${task}"`), `Word missing ${task} tab`);
});

console.log("taskpane experience markup contract passed");
