const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { etRoot } = require("./support/plugin-roots");

const helpers = require(path.join(etRoot, "taskpane-helpers.js"));
const excelHtml = fs.readFileSync(path.join(etRoot, "taskpane.html"), "utf8");
const excelJs = fs.readFileSync(path.join(etRoot, "taskpane.js"), "utf8");
const excelCss = fs.readFileSync(path.join(etRoot, "taskpane.css"), "utf8");
const sharedCssMarker = "/* Shared restrained settings and interaction treatment. */";
const excelCssHead = excelCss.slice(0, excelCss.indexOf(sharedCssMarker));

const SECRET_PROFILE = {
  id: "direct-1",
  name: "直连生产",
  accessMethod: "direct_model",
  complete: true,
  modelName: "secret-model",
  serviceBaseUrl: "https://secret.example.test/v1",
  note: "secret note",
  keyConfigured: true
};
const PLATFORM_PROFILE = {
  id: "flow-1",
  name: "生产版",
  accessMethod: "workflow_platform",
  complete: true,
  modelName: "hidden-model",
  serviceBaseUrl: "https://hidden.example.test/v1",
  note: "hidden note",
  keyConfigured: true
};
const FORBIDDEN_LABEL_TOKENS = [
  "secret-model",
  "hidden-model",
  "secret.example.test",
  "hidden.example.test",
  "secret note",
  "hidden note",
  "Key",
  "配置完整",
  "配置不完整",
  "✓"
];

function assertNoLeak(text, label) {
  const value = String(text || "");
  FORBIDDEN_LABEL_TOKENS.forEach((token) => {
    assert.ok(!value.includes(token), `${label} leaks ${token}: ${value}`);
  });
}

function homeConfigStrip(html) {
  const marker = 'id="workflow-profile-strip"';
  const index = html.indexOf(marker);
  assert.ok(index >= 0, "Excel task page missing workflow-profile-strip");
  const start = html.lastIndexOf("<", index);
  const end = html.indexOf("<section class=\"controls", start);
  assert.ok(end > start, "Excel home strip must sit above task controls");
  return html.slice(start, end);
}

function assertExcelTaskPagesUseCompactEntry() {
  const strip = homeConfigStrip(excelHtml);
  assert.ok(!strip.includes(">模型配置<"), "Excel task pages must not show the 模型配置 label");
  assert.ok(!strip.includes("<select"), "Excel task pages must not use a native select");
  assert.ok(!strip.includes("workflow-profile-select"), "Excel task pages must remove workflow-profile-select");
  assert.ok(!strip.includes("当前配置"), "Excel task pages must not keep an independent 当前配置 status row");
  assert.ok(strip.includes('id="task-model-config-trigger"'), "Excel compact entry needs a trigger");
  assert.ok(strip.includes('id="task-model-config-menu"'), "Excel compact entry needs an anchored menu");
  assert.ok(strip.includes("›") || strip.includes("task-model-config-chevron"), "Excel compact entry needs a disclosure chevron");
}

function assertLabelContract() {
  assert.strictEqual(helpers.formatTaskModelConfigAccessMethod("direct_model"), "模型直连");
  assert.strictEqual(helpers.formatTaskModelConfigAccessMethod("workflow_platform"), "工作流平台");

  const ready = helpers.formatTaskModelConfigEntry(SECRET_PROFILE, { status: "ready" });
  assert.strictEqual(ready.visibleText, "直连生产 · 模型直连");
  assert.strictEqual(ready.chevron, "›");
  assert.strictEqual(ready.statusText, "已就绪");
  assert.ok(!ready.visibleText.includes("›"), "chevron must stay out of the visible name/method text");
  assertNoLeak(ready.visibleText, "ready visibleText");
  assertNoLeak(ready.statusText, "ready statusText");
  assertNoLeak(ready.ariaLabel, "ready ariaLabel");
  assert.ok(ready.ariaLabel.includes("直连生产"));
  assert.ok(ready.ariaLabel.includes("模型直连"));
  assert.ok(ready.ariaLabel.includes("已就绪"));

  const platform = helpers.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "ready" });
  assert.strictEqual(platform.visibleText, "生产版 · 工作流平台");

  const busy = helpers.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "busy" });
  assert.strictEqual(busy.visibleText, "生产版 · 工作流平台");
  assert.strictEqual(busy.statusText, "正在切换");

  const failed = helpers.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "error" });
  assert.strictEqual(failed.visibleText, "生产版 · 工作流平台");
  assert.strictEqual(failed.statusText, "切换失败");

  const empty = helpers.formatTaskModelConfigEntry(null, { status: "empty" });
  assert.strictEqual(empty.visibleText, "未配置");
  assert.strictEqual(empty.statusText, "未配置");

  const loading = helpers.formatTaskModelConfigEntry(null, { status: "loading" });
  assert.strictEqual(loading.visibleText, "正在读取");
  assert.strictEqual(loading.statusText, "正在读取");

  const readError = helpers.formatTaskModelConfigEntry(null, { status: "loadError" });
  assert.strictEqual(readError.visibleText, "配置读取失败");
  assert.strictEqual(readError.statusText, "配置读取失败");
}

function assertMenuContract() {
  const items = helpers.buildTaskModelConfigMenuItems(
    [PLATFORM_PROFILE, SECRET_PROFILE, { id: "broken", name: "草稿", accessMethod: "direct_model", complete: false, modelName: "secret-model" }],
    { activeProfileId: "flow-1" }
  );
  assert.strictEqual(items[items.length - 1].action, "manage");
  assert.strictEqual(items[items.length - 1].label, "管理配置");
  assert.strictEqual(items[0].label, "生产版 · 工作流平台");
  assert.strictEqual(items[0].selected, true);
  assert.strictEqual(items[1].label, "直连生产 · 模型直连");
  assert.strictEqual(items[1].selected, false);
  assert.strictEqual(items[2].disabled, true);
  items.forEach((item) => assertNoLeak(item.label, item.action + " menu label"));
}

function assertTaskStatusIsolationContract() {
  assert.strictEqual(
    helpers.resolveTaskModelConfigViewStatus({
      taskType: "excel.formula_assistant",
      mutationBusy: false,
      statusByTask: { "excel.analysis": "error" },
      hasLoaded: true,
      hasProfile: true
    }),
    "ready",
    "formula assistant must not inherit analysis switch failure"
  );
  assert.strictEqual(
    helpers.resolveTaskModelConfigViewStatus({
      taskType: "excel.analysis",
      mutationBusy: false,
      statusByTask: { "excel.analysis": "error" },
      hasLoaded: true,
      hasProfile: true
    }),
    "error"
  );
  assert.strictEqual(
    helpers.resolveTaskModelConfigViewStatus({
      taskType: "excel.smart_fill",
      mutationBusy: true,
      statusByTask: { "excel.smart_fill": "error" },
      hasLoaded: true,
      hasProfile: true
    }),
    "busy"
  );
  assert.ok(excelJs.includes("taskModelConfigStatusByTask"), "Excel must store switch errors per task");
  assert.ok(!/taskModelConfigStatus: \"\"/.test(excelJs), "Excel must not keep a host-wide compact-entry error flag");
}

function assertActivationContract() {
  assert.deepStrictEqual(
    helpers.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: true,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: false, reason: "busy", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    helpers.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: true,
      profileComplete: true
    }),
    { allowed: false, reason: "busy", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    helpers.evaluateTaskModelConfigSwitch({
      requestedId: "broken",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: false
    }),
    { allowed: false, reason: "incomplete", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    helpers.evaluateTaskModelConfigSwitch({
      requestedId: "flow-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: false, reason: "unchanged", nextSelectionId: "flow-1", restoreFocus: false }
  );
  assert.deepStrictEqual(
    helpers.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: true, reason: "activate", nextSelectionId: "direct-1", restoreFocus: false }
  );
  assert.deepStrictEqual(
    helpers.rollbackTaskModelConfigSwitch({
      previousId: "flow-1",
      previousLabel: "生产版 · 工作流平台"
    }),
    {
      selectionId: "flow-1",
      visibleText: "生产版 · 工作流平台",
      restoreFocus: true,
      statusText: "切换失败"
    }
  );
}

function assertKeyboardContract() {
  const items = [
    { action: "select", selected: false },
    { action: "select", selected: true },
    { action: "manage", selected: false }
  ];
  const closed = { open: false, itemCount: 3, highlightedIndex: -1, items: items };
  const opened = helpers.reduceTaskModelConfigMenuKey(closed, "Open");
  assert.deepStrictEqual(opened, { open: true, itemCount: 3, highlightedIndex: 0, action: "open", restoreFocus: false });

  const openedOnCurrent = helpers.reduceTaskModelConfigMenuKey({
    open: false,
    itemCount: 3,
    highlightedIndex: 1,
    items: items
  }, "Open");
  assert.strictEqual(openedOnCurrent.highlightedIndex, 1, "opening must keep the current configuration highlighted");

  const down = helpers.reduceTaskModelConfigMenuKey(opened, "ArrowDown");
  assert.strictEqual(down.highlightedIndex, 1);
  assert.strictEqual(down.open, true);
  const wrap = helpers.reduceTaskModelConfigMenuKey(
    helpers.reduceTaskModelConfigMenuKey(down, "ArrowDown"),
    "ArrowDown"
  );
  assert.strictEqual(wrap.highlightedIndex, 2, "highlight must clamp at the last item including 管理配置");

  const up = helpers.reduceTaskModelConfigMenuKey({ open: true, itemCount: 3, highlightedIndex: 0, items: items }, "ArrowUp");
  assert.strictEqual(up.highlightedIndex, 0);

  const select = helpers.reduceTaskModelConfigMenuKey({
    open: true,
    itemCount: 3,
    highlightedIndex: 1,
    items: items
  }, "Enter");
  assert.deepStrictEqual(select, {
    open: false,
    itemCount: 3,
    highlightedIndex: 1,
    action: "select",
    selectedIndex: 1,
    restoreFocus: true
  });

  const manage = helpers.reduceTaskModelConfigMenuKey({
    open: true,
    itemCount: 3,
    highlightedIndex: 1,
    items: [{ action: "select" }, { action: "manage" }, { action: "select" }]
  }, "Enter");
  assert.strictEqual(manage.action, "manage", "Enter must follow item.action, not the last index");
  assert.strictEqual(manage.open, false);
  assert.strictEqual(manage.restoreFocus, false);

  const escape = helpers.reduceTaskModelConfigMenuKey({
    open: true,
    itemCount: 3,
    highlightedIndex: 1,
    items: items
  }, "Escape");
  assert.deepStrictEqual(escape, {
    open: false,
    itemCount: 3,
    highlightedIndex: -1,
    action: "close",
    restoreFocus: true
  });
}

function assertSettingsNavigationContract() {
  assert.ok(
    excelJs.includes("helpers.buildTaskModelConfigMenuItems"),
    "Excel must render the shared menu that ends with 管理配置"
  );
  assert.ok(excelJs.includes('switchMode("settings")'), "管理配置 must open the full settings page");
  assert.ok(excelHtml.includes('id="workflow-profile-manager"'), "full Excel manager page must remain");
  assert.ok(excelHtml.includes('id="btn-validate-model-configuration"'), "validate action must remain");
  assert.ok(excelHtml.includes('id="workflow-delete-dialog"'), "delete dialog must remain");
  assert.ok(excelHtml.includes('id="workflow-editor-name"'), "editor fields must remain");
  assert.ok(excelJs.includes("confirmWorkflowProfileDelete"), "delete behavior must remain");
  assert.ok(excelJs.includes("validateCurrentModelConfiguration"), "validate call must remain");
}

function assertExcelTaskContextContract() {
  ["excel.analysis", "excel.formula_assistant", "excel.smart_fill"].forEach((taskType) => {
    assert.ok(excelJs.includes(taskType), `Excel compact entry must keep ${taskType} task context`);
  });
  assert.ok(excelJs.includes("getTaskPageWorkflowType()"), "task switching must keep reading the current task configuration set");
  assert.ok(excelJs.includes("state.workflowProfileSelections"), "per-task selections must stay isolated");
  assert.ok(
    excelJs.includes("helpers.evaluateTaskModelConfigSwitch") || excelJs.includes("evaluateTaskModelConfigSwitch("),
    "Excel activation must use the shared switch contract"
  );
  assert.ok(
    excelJs.includes("helpers.reduceTaskModelConfigMenuKey") || excelJs.includes("reduceTaskModelConfigMenuKey("),
    "Excel keyboard handling must use the shared menu contract"
  );
}

function cssRuleBody(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)[ \\t]*${escaped}[ \\t]*\\{([^}]*)\\}`));
  assert.ok(match, `missing CSS rule ${selector}`);
  return match[1];
}

function assertLayoutContract() {
  const triggerRule = cssRuleBody(excelCssHead, ".task-model-config-trigger");
  const labelRule = cssRuleBody(excelCssHead, ".task-model-config-label");
  const menuRule = cssRuleBody(excelCssHead, ".task-model-config-menu");
  assert.ok(labelRule.includes("text-overflow: ellipsis"), "narrow panes must ellipsize the entry, not wrap mid-glyph");
  assert.ok(labelRule.includes("white-space: nowrap"), "entry label must not break onto a second line");
  assert.ok(labelRule.includes("overflow: hidden"), "entry must clip instead of overflowing 320px");
  assert.ok(triggerRule.includes("min-width: 0"), "trigger must shrink inside 320px panes");
  assert.ok(/max-height\s*:/.test(menuRule), "menu must cap height inside 320×700");
  assert.ok(menuRule.includes("overflow-y: auto"), "tall config lists must scroll inside the menu");
  assert.ok(excelCssHead.includes(".task-model-config-menu.is-above"), "menu must flip above the trigger near the pane bottom");
  assert.ok(excelCssHead.includes("transform: scale(0.98)") || excelCss.includes("transform: scale(0.98)"), "pointer-down must give immediate press feedback");
  assert.ok(excelCss.includes("@media (prefers-reduced-motion: reduce)"), "reduced motion support must remain");
  assert.ok(!excelCssHead.includes("backdrop-filter"), "compact entry must not add decorative blur");
  assert.ok(excelJs.includes('tabindex="-1"') || excelJs.includes("tabindex=\\\"-1\\\""), "listbox options must stay out of tab order");
  assert.ok(excelJs.includes("aria-activedescendant"), "listbox must expose the highlighted option without moving focus");
  assert.ok(excelJs.includes("updateTaskModelConfigMenuHighlight"), "arrow keys must update highlight without replacing the menu");
}

assertLabelContract();
assertMenuContract();
assertTaskStatusIsolationContract();
assertActivationContract();
assertKeyboardContract();
assertExcelTaskPagesUseCompactEntry();
assertSettingsNavigationContract();
assertExcelTaskContextContract();
assertLayoutContract();

console.log("task model config entry contract tests passed");
