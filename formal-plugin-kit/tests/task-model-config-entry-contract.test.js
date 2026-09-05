const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { etRoot, wordRoot } = require("./support/plugin-roots");

const helpers = require(path.join(etRoot, "taskpane-helpers.js"));
const wordHelpers = require(path.join(wordRoot, "taskpane-helpers.js"));
const excelHtml = fs.readFileSync(path.join(etRoot, "taskpane.html"), "utf8");
const excelJs = fs.readFileSync(path.join(etRoot, "taskpane.js"), "utf8");
const excelCss = fs.readFileSync(path.join(etRoot, "taskpane.css"), "utf8");
const wordHtml = fs.readFileSync(path.join(wordRoot, "taskpane.html"), "utf8");
const wordJs = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
const wordCss = fs.readFileSync(path.join(wordRoot, "taskpane.css"), "utf8");
const sharedCssMarker = "/* Shared restrained settings and interaction treatment. */";
const excelCssHead = excelCss.slice(0, excelCss.indexOf(sharedCssMarker));
const wordCssHead = wordCss.includes(sharedCssMarker)
  ? wordCss.slice(0, wordCss.indexOf(sharedCssMarker))
  : wordCss;

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

function homeConfigStrip(html, hostName = "Excel") {
  const marker = 'id="workflow-profile-strip"';
  const index = html.indexOf(marker);
  assert.ok(index >= 0, `${hostName} task page missing workflow-profile-strip`);
  const start = html.lastIndexOf("<", index);
  const end = html.indexOf("<section class=\"controls", start);
  assert.ok(end > start, `${hostName} home strip must sit above task controls`);
  return html.slice(start, end);
}

function assertTaskPagesUseCompactEntry(html, hostName = "Excel") {
  const strip = homeConfigStrip(html, hostName);
  assert.ok(!strip.includes(">模型配置<"), `${hostName} task pages must not show the 模型配置 label`);
  assert.ok(!strip.includes("<select"), `${hostName} task pages must not use a native select`);
  assert.ok(!strip.includes("workflow-profile-select"), `${hostName} task pages must remove workflow-profile-select`);
  assert.ok(!strip.includes("当前配置"), `${hostName} task pages must not keep an independent 当前配置 status row`);
  assert.ok(strip.includes('id="task-model-config-trigger"'), `${hostName} compact entry needs a trigger`);
  assert.ok(strip.includes('aria-haspopup="menu"'), `${hostName} trigger must declare aria-haspopup="menu"`);
  assert.ok(strip.includes('id="task-model-config-menu"'), `${hostName} compact entry needs an anchored menu`);
  assert.ok(strip.includes('role="menu"'), `${hostName} anchored menu container must declare role="menu"`);
  assert.ok(strip.includes('aria-label="模型配置列表"'), `${hostName} menu container must declare accessible label`);
  assert.ok(strip.includes("›") || strip.includes("task-model-config-chevron"), `${hostName} compact entry needs a disclosure chevron`);
}

function assertExcelTaskPagesUseCompactEntry() {
  assertTaskPagesUseCompactEntry(excelHtml, "Excel");
}

function assertWordTaskPagesUseCompactEntry() {
  assertTaskPagesUseCompactEntry(wordHtml, "Word");
}

function assertWordTaskContextContract() {
  ["word.smart_write", "word.smart_imitation", "word.document_review", "word.format_review"].forEach((taskType) => {
    assert.ok(wordJs.includes(taskType), `Word compact entry must keep ${taskType} task context`);
  });
  assert.ok(wordJs.includes("getCurrentWorkflowTaskType()"), "Word task switching must keep reading the current task configuration set");
  assert.ok(wordJs.includes("state.workflowProfileSelections"), "Word per-task selections must stay isolated");
  assert.ok(
    wordJs.includes("helpers.evaluateTaskModelConfigSwitch") || wordJs.includes("evaluateTaskModelConfigSwitch("),
    "Word activation must use the shared switch contract"
  );
  assert.ok(
    wordJs.includes("helpers.reduceTaskModelConfigMenuKey") || wordJs.includes("reduceTaskModelConfigMenuKey("),
    "Word keyboard handling must use the shared menu contract"
  );
  assert.ok(wordJs.includes("taskModelConfigStatusByTask"), "Word must store switch errors per task");
  assert.ok(!/taskModelConfigStatus: \"\"/.test(wordJs), "Word must not keep a host-wide compact-entry error flag");
}

function assertWordSettingsNavigationContract() {
  assert.ok(
    wordJs.includes("helpers.buildTaskModelConfigMenuItems") || wordJs.includes("buildTaskModelConfigMenuItems("),
    "Word must render the shared menu that ends with 管理配置"
  );
  assert.ok(wordJs.includes('switchMode("settings")'), "Word 管理配置 must open the full settings page");
  assert.ok(wordHtml.includes('id="workflow-profile-manager"'), "full Word manager page must remain");
  assert.ok(wordHtml.includes('id="btn-new-workflow-profile"'), "Word new profile button must remain");
  assert.ok(wordJs.includes("deleteWorkflowProfile"), "Word delete behavior must remain");
  assert.ok(wordJs.includes("validateModelConfiguration"), "Word validate call must remain");
}

function assertLabelContract(h = helpers) {
  assert.strictEqual(h.formatTaskModelConfigAccessMethod("direct_model"), "模型直连");
  assert.strictEqual(h.formatTaskModelConfigAccessMethod("workflow_platform"), "工作流平台");

  const ready = h.formatTaskModelConfigEntry(SECRET_PROFILE, { status: "ready" });
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

  const platform = h.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "ready" });
  assert.strictEqual(platform.visibleText, "生产版 · 工作流平台");

  const busy = h.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "busy" });
  assert.strictEqual(busy.visibleText, "生产版 · 工作流平台");
  assert.strictEqual(busy.statusText, "正在切换");

  const failed = h.formatTaskModelConfigEntry(PLATFORM_PROFILE, { status: "error" });
  assert.strictEqual(failed.visibleText, "生产版 · 工作流平台");
  assert.strictEqual(failed.statusText, "切换失败");

  const empty = h.formatTaskModelConfigEntry(null, { status: "empty" });
  assert.strictEqual(empty.visibleText, "未配置");
  assert.strictEqual(empty.statusText, "未配置");

  const loading = h.formatTaskModelConfigEntry(null, { status: "loading" });
  assert.strictEqual(loading.visibleText, "正在读取");
  assert.strictEqual(loading.statusText, "正在读取");

  const readError = h.formatTaskModelConfigEntry(null, { status: "loadError" });
  assert.strictEqual(readError.visibleText, "配置读取失败");
  assert.strictEqual(readError.statusText, "配置读取失败");
}

function assertMenuContract(h = helpers) {
  const items = h.buildTaskModelConfigMenuItems(
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

function assertTaskStatusIsolationContract(h = helpers) {
  assert.strictEqual(
    h.resolveTaskModelConfigViewStatus({
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
    h.resolveTaskModelConfigViewStatus({
      taskType: "excel.analysis",
      mutationBusy: false,
      statusByTask: { "excel.analysis": "error" },
      hasLoaded: true,
      hasProfile: true
    }),
    "error"
  );
  assert.strictEqual(
    h.resolveTaskModelConfigViewStatus({
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

function assertActivationContract(h = helpers) {
  assert.deepStrictEqual(
    h.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: true,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: false, reason: "busy", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    h.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: true,
      profileComplete: true
    }),
    { allowed: false, reason: "busy", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    h.evaluateTaskModelConfigSwitch({
      requestedId: "broken",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: false
    }),
    { allowed: false, reason: "incomplete", nextSelectionId: "flow-1", restoreFocus: true }
  );
  assert.deepStrictEqual(
    h.evaluateTaskModelConfigSwitch({
      requestedId: "flow-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: false, reason: "unchanged", nextSelectionId: "flow-1", restoreFocus: false }
  );
  assert.deepStrictEqual(
    h.evaluateTaskModelConfigSwitch({
      requestedId: "direct-1",
      previousId: "flow-1",
      busy: false,
      mutationBusy: false,
      profileComplete: true
    }),
    { allowed: true, reason: "activate", nextSelectionId: "direct-1", restoreFocus: false }
  );
  assert.deepStrictEqual(
    h.rollbackTaskModelConfigSwitch({
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

function assertKeyboardContract(h = helpers) {
  const items = [
    { action: "select", selected: false },
    { action: "select", selected: true },
    { action: "manage", selected: false }
  ];
  const closed = { open: false, itemCount: 3, highlightedIndex: -1, items: items };
  const opened = h.reduceTaskModelConfigMenuKey(closed, "Open");
  assert.deepStrictEqual(opened, { open: true, itemCount: 3, highlightedIndex: 0, action: "open", restoreFocus: false });

  const openedOnCurrent = h.reduceTaskModelConfigMenuKey({
    open: false,
    itemCount: 3,
    highlightedIndex: 1,
    items: items
  }, "Open");
  assert.strictEqual(openedOnCurrent.highlightedIndex, 1, "opening must keep the current configuration highlighted");

  const down = h.reduceTaskModelConfigMenuKey(opened, "ArrowDown");
  assert.strictEqual(down.highlightedIndex, 1);
  assert.strictEqual(down.open, true);
  const wrap = h.reduceTaskModelConfigMenuKey(
    h.reduceTaskModelConfigMenuKey(down, "ArrowDown"),
    "ArrowDown"
  );
  assert.strictEqual(wrap.highlightedIndex, 2, "highlight must clamp at the last item including 管理配置");

  const up = h.reduceTaskModelConfigMenuKey({ open: true, itemCount: 3, highlightedIndex: 0, items: items }, "ArrowUp");
  assert.strictEqual(up.highlightedIndex, 0);

  const select = h.reduceTaskModelConfigMenuKey({
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

  const manage = h.reduceTaskModelConfigMenuKey({
    open: true,
    itemCount: 3,
    highlightedIndex: 1,
    items: [{ action: "select" }, { action: "manage" }, { action: "select" }]
  }, "Enter");
  assert.strictEqual(manage.action, "manage", "Enter must follow item.action, not the last index");
  assert.strictEqual(manage.open, false);
  assert.strictEqual(manage.restoreFocus, false);

  const escape = h.reduceTaskModelConfigMenuKey({
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

function assertLayoutContract(cssHead = excelCssHead, hostName = "Excel") {
  const fullCss = hostName === "Excel" ? excelCss : wordCss;
  const targetJs = hostName === "Excel" ? excelJs : wordJs;
  const triggerRule = cssRuleBody(cssHead, ".task-model-config-trigger");
  const labelRule = cssRuleBody(cssHead, ".task-model-config-label");
  const menuRule = cssRuleBody(cssHead, ".task-model-config-menu");
  assert.ok(labelRule.includes("text-overflow: ellipsis"), `${hostName}: narrow panes must ellipsize the entry, not wrap mid-glyph`);
  assert.ok(labelRule.includes("white-space: nowrap"), `${hostName}: entry label must not break onto a second line`);
  assert.ok(labelRule.includes("overflow: hidden"), `${hostName}: entry must clip instead of overflowing 320px`);
  assert.ok(triggerRule.includes("min-width: 0"), `${hostName}: trigger must shrink inside 320px panes`);
  assert.ok(/max-height\s*:/.test(menuRule), `${hostName}: menu must cap height inside 320×700`);
  assert.ok(menuRule.includes("overflow-y: auto"), `${hostName}: tall config lists must scroll inside the menu`);
  assert.ok(cssHead.includes(".task-model-config-menu.is-above"), `${hostName}: menu must flip above the trigger near the pane bottom`);
  assert.ok(cssHead.includes("transform: scale(0.98)") || fullCss.includes("transform: scale(0.98)"), `${hostName}: pointer-down must give immediate press feedback`);
  assert.ok(fullCss.includes("@media (prefers-reduced-motion: reduce)"), `${hostName}: reduced motion support must remain`);
  assert.ok(!cssHead.includes("backdrop-filter"), `${hostName}: compact entry must not add decorative blur`);
  assert.ok(targetJs.includes('tabindex="-1"') || targetJs.includes("tabindex=\\\"-1\\\""), `${hostName}: menu options must stay out of tab order`);
  assert.ok(targetJs.includes("aria-activedescendant"), `${hostName}: trigger must expose the highlighted option via aria-activedescendant without moving focus`);
  assert.ok(targetJs.includes("role=\"menuitemradio\"") || targetJs.includes("isManage ? \"menuitem\" : \"menuitemradio\""), `${hostName}: options must use menuitemradio and menuitem`);
  assert.ok(targetJs.includes("aria-checked="), `${hostName}: options must expose real selection state via aria-checked`);
  assert.ok(targetJs.includes("updateTaskModelConfigMenuHighlight"), `${hostName}: arrow keys must update highlight without replacing the menu`);
}

function assertUnactivatedProfileContract(h = helpers, taskType = "excel.analysis") {
  const unresolved = h.resolveCurrentTaskModelConfigProfile(
    { activeProfileId: "", profiles: [PLATFORM_PROFILE, SECRET_PROFILE] },
    ""
  );
  assert.strictEqual(unresolved, null, "unactivated profile set must resolve to null");

  const nonExistent = h.resolveCurrentTaskModelConfigProfile(
    { activeProfileId: "ghost", profiles: [PLATFORM_PROFILE] },
    "ghost"
  );
  assert.strictEqual(nonExistent, null, "unknown profile id must resolve to null");

  const resolvedActive = h.resolveCurrentTaskModelConfigProfile(
    { activeProfileId: "flow-1", profiles: [PLATFORM_PROFILE, SECRET_PROFILE] },
    "flow-1"
  );
  assert.strictEqual(resolvedActive.id, "flow-1");

  const status = h.resolveTaskModelConfigViewStatus({
    taskType: taskType,
    mutationBusy: false,
    statusByTask: {},
    hasLoaded: true,
    loadError: false,
    hasProfile: Boolean(unresolved)
  });
  assert.strictEqual(status, "empty", "status must be empty when no profile is active");

  const formatted = h.formatTaskModelConfigEntry(unresolved, { status: status });
  assert.strictEqual(formatted.visibleText, "未配置");
  assert.strictEqual(formatted.statusText, "未配置");
  assert.strictEqual(formatted.ariaLabel, "未配置");

  const menuItems = h.buildTaskModelConfigMenuItems(
    [PLATFORM_PROFILE, SECRET_PROFILE],
    { activeProfileId: "" }
  );
  menuItems.forEach((item) => {
    if (item.action === "select") {
      assert.strictEqual(item.selected, false, "no option should be selected when activeProfileId is empty");
    }
  });
}

async function assertBehavioralDomContracts() {
  function functionSource(name) {
    const start = excelJs.indexOf(`  function ${name}(`);
    assert.notStrictEqual(start, -1, `missing function ${name}`);
    const next = excelJs.indexOf("\n  function ", start + 3);
    return excelJs.slice(start, next === -1 ? excelJs.length : next);
  }
  function loadFunction(name, context = {}) {
    return vm.runInNewContext(`(${functionSource(name)})`, context);
  }

  function createClassList(initial = []) {
    const classes = new Set(initial);
    return {
      add(...names) { names.forEach((n) => classes.add(n)); },
      remove(...names) { names.forEach((n) => classes.delete(n)); },
      toggle(name, force) {
        if (force === undefined) {
          if (classes.has(name)) classes.delete(name); else classes.add(name);
        } else if (force) {
          classes.add(name);
        } else {
          classes.delete(name);
        }
      },
      contains(name) { return classes.has(name); }
    };
  }

  function createMockElement(id = "", tagName = "div") {
    const attributes = {};
    const classList = createClassList();
    const children = [];
    let currentInnerHtml = "";
    const el = {
      id: id,
      tagName: tagName.toUpperCase(),
      attributes: attributes,
      classList: classList,
      children: children,
      hidden: false,
      disabled: false,
      textContent: "",
      setAttribute(name, value) { attributes[name] = String(value); },
      getAttribute(name) { return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null; },
      removeAttribute(name) { delete attributes[name]; },
      hasAttribute(name) { return Object.prototype.hasOwnProperty.call(attributes, name); },
      getBoundingClientRect() { return { top: 100, bottom: 200, height: 100, width: 200 }; },
      focus() {
        mockDocument.activeElement = el;
      },
      querySelectorAll(selector) {
        if (selector === "[data-config-action]") {
          return children.filter((c) => c.hasAttribute("data-config-action"));
        }
        return [];
      },
      get innerHTML() { return currentInnerHtml; },
      set innerHTML(val) {
        currentInnerHtml = val;
        children.length = 0;
        if (!val) return;
        const regex = /<button\s+([^>]+)>([^<]*)<\/button>/g;
        let match;
        while ((match = regex.exec(val)) !== null) {
          const attrsStr = match[1];
          const text = match[2];
          const btn = createMockElement("", "button");
          btn.textContent = text;
          const attrRegex = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
          let attrMatch;
          while ((attrMatch = attrRegex.exec(attrsStr)) !== null) {
            btn.setAttribute(attrMatch[1], attrMatch[2]);
            if (attrMatch[1] === "id") btn.id = attrMatch[2];
            if (attrMatch[1] === "class") {
              attrMatch[2].split(/\s+/).forEach((c) => { if (c) btn.classList.add(c); });
            }
          }
          if (attrsStr.includes("disabled")) btn.disabled = true;
          children.push(btn);
        }
      }
    };
    return el;
  }

  const mockTabs = {
    "excel.analysis": createMockElement("tab-excel-analysis", "button"),
    "excel.formula_assistant": createMockElement("tab-excel-formula", "button"),
    "excel.smart_fill": createMockElement("tab-excel-smart-fill", "button")
  };
  mockTabs["excel.analysis"].setAttribute("data-workflow-task-tab", "excel.analysis");
  mockTabs["excel.formula_assistant"].setAttribute("data-workflow-task-tab", "excel.formula_assistant");
  mockTabs["excel.smart_fill"].setAttribute("data-workflow-task-tab", "excel.smart_fill");

  const mockNodes = {
    "workflow-profile-strip": createMockElement("workflow-profile-strip"),
    "task-model-config-trigger": createMockElement("task-model-config-trigger", "button"),
    "task-model-config-menu": createMockElement("task-model-config-menu"),
    "task-model-config-label": createMockElement("task-model-config-label", "span"),
    "task-model-config-status": createMockElement("task-model-config-status", "span"),
    "workflow-switch-feedback": createMockElement("workflow-switch-feedback", "span"),
    "home-view": createMockElement("home-view", "section"),
    "settings-view": createMockElement("settings-view", "section"),
    "task-title": createMockElement("task-title", "h2"),
    "btn-open-settings": createMockElement("btn-open-settings", "button"),
    "excel-analysis-options": createMockElement("excel-analysis-options"),
    "excel-formula-options": createMockElement("excel-formula-options"),
    "excel-smart-fill-options": createMockElement("excel-smart-fill-options"),
    "btn-run-primary": createMockElement("btn-run-primary", "button"),
    "btn-copy-formula": createMockElement("btn-copy-formula", "button"),
    "diagnostics-disclosure": createMockElement("diagnostics-disclosure"),
    "btn-confirm-workflow-delete": createMockElement("btn-confirm-workflow-delete", "button"),
    "btn-cancel-workflow-delete": createMockElement("btn-cancel-workflow-delete", "button"),
    "btn-save-workflow-editor": createMockElement("btn-save-workflow-editor", "button"),
    "btn-cancel-workflow-editor": createMockElement("btn-cancel-workflow-editor", "button"),
    "btn-workflow-editor-back": createMockElement("btn-workflow-editor-back", "button")
  };
  mockNodes["home-view"].classList.add("active");

  const mockDocument = {
    activeElement: mockNodes["task-model-config-trigger"],
    body: createMockElement("body", "body"),
    querySelector(sel) {
      const tabMatch = sel && sel.match(/\[data-workflow-task-tab="([^"]+)"\]/);
      if (tabMatch && mockTabs[tabMatch[1]]) {
        return mockTabs[tabMatch[1]];
      }
      return null;
    }
  };

  const byId = (id) => mockNodes[id] || null;
  const setNodeTextIfChanged = (node, text) => { if (node) node.textContent = text; };
  const escaped = (v) => helpers.escapeHtml ? helpers.escapeHtml(v) : String(v || "");

  const testState = {
    currentMode: "excelAnalysis",
    lastTaskMode: "excelAnalysis",
    workflowTaskType: "excel.analysis",
    busy: false,
    workflowProfileMutationBusy: false,
    taskModelConfigStatusByTask: {},
    taskModelConfigMenu: { open: false, highlightedIndex: -1, itemCount: 0, items: [] },
    workflowProfileSelections: { "excel.analysis": "" },
    workflowProfileLoadSequences: {},
    workflowProfilesByTask: {},
    modelInterfaceDetectable: true,
    workflowEditor: { open: false },
    providerUrlEditorOpen: false
  };

  const baseContext = {
    state: testState,
    helpers: helpers,
    byId: byId,
    setNodeTextIfChanged: setNodeTextIfChanged,
    escaped: escaped,
    document: mockDocument,
    window: { innerHeight: 700 },
    EXCEL_WORKFLOW_TASK_TYPE: "excel.analysis",
    EXCEL_FORMULA_WORKFLOW_TASK_TYPE: "excel.formula_assistant",
    EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE: "excel.smart_fill",
    getTaskPageWorkflowType() { return testState.workflowTaskType; },
    getWorkflowProfileData(task) {
      return testState.workflowProfilesByTask[task] || { taskType: task, activeProfileId: "", profiles: [] };
    },
    normalizeWorkflowProfileData(data, task) {
      return {
        taskType: task,
        activeProfileId: (data && data.activeConfigurationId) || (data && data.activeProfileId) || "",
        profiles: (data && data.configurations) || (data && data.profiles) || []
      };
    },
    getActiveWorkflowProfileName(data) {
      const p = (data && data.profiles || []).find((x) => x.id === (data && data.activeProfileId));
      return p ? p.name : "尚未配置";
    },
    findWorkflowProfile(id, task) {
      const d = testState.workflowProfilesByTask[task];
      return d && d.profiles ? d.profiles.find((x) => x.id === id) : null;
    },
    focusTaskModelConfigTrigger() { mockNodes["task-model-config-trigger"].focus(); },
    describeFetchError(err) { return err && err.message || String(err); },
    renderModelInterfaceState() {},
    renderWorkflowProfileManager() {},
    renderWorkflowTaskTabs() {},
    renderSmartFillCaptureState() {},
    setSmartFillWriteButtonState() {},
    setExcelResultViewSwitchForMode() {},
    refreshConfig() {},
    syncSettingsRefreshController() {},
    syncScopeWatcher() {},
    setFormulaAssistantMode() {},
    resumeExcelAnalysisActiveJob() {},
    resumeExcelFormulaActiveJob() {},
    resumeExcelSmartFillActiveJob() {},
    loadWorkflowProfiles() {},
    getFormulaModeUi() { return { actionLabel: "生成" }; }
  };

  baseContext.taskModelConfigOptionId = loadFunction("taskModelConfigOptionId", baseContext);
  baseContext.positionTaskModelConfigMenu = loadFunction("positionTaskModelConfigMenu", baseContext);
  baseContext.updateTaskModelConfigMenuHighlight = loadFunction("updateTaskModelConfigMenuHighlight", baseContext);
  baseContext.closeTaskModelConfigMenu = loadFunction("closeTaskModelConfigMenu", baseContext);
  baseContext.renderTaskModelConfigMenu = loadFunction("renderTaskModelConfigMenu", baseContext);
  baseContext.currentTaskModelConfigProfile = loadFunction("currentTaskModelConfigProfile", baseContext);
  baseContext.resolveTaskModelConfigStatus = loadFunction("resolveTaskModelConfigStatus", baseContext);
  baseContext.openTaskModelConfigMenu = loadFunction("openTaskModelConfigMenu", baseContext);
  baseContext.switchView = loadFunction("switchView", baseContext);
  baseContext.switchMode = loadFunction("switchMode", baseContext);
  baseContext.renderWorkflowProfileStrip = loadFunction("renderWorkflowProfileStrip", baseContext);
  baseContext.setWorkflowMutationBusy = loadFunction("setWorkflowMutationBusy", baseContext);

  let statusMessage = "";
  baseContext.setStatus = (msg) => { statusMessage = msg; };

  // --- Test 1: Unactivated profile rendering (complete profile exists, but activeConfigurationId is empty) ---
  testState.workflowProfilesByTask["excel.analysis"] = {
    taskType: "excel.analysis",
    activeProfileId: "",
    profiles: [PLATFORM_PROFILE, SECRET_PROFILE]
  };
  testState.workflowProfileSelections["excel.analysis"] = "";
  const resolvedUnactivated = baseContext.currentTaskModelConfigProfile(testState.workflowProfilesByTask["excel.analysis"]);
  assert.strictEqual(resolvedUnactivated, null, "currentTaskModelConfigProfile must return null when activeProfileId is empty");

  baseContext.renderWorkflowProfileStrip();
  assert.strictEqual(mockNodes["task-model-config-label"].textContent, "未配置");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-label"), "选择智能分析模型配置，未配置");
  assert.ok(!mockNodes["task-model-config-trigger"].getAttribute("aria-label").includes("生产版"));
  assert.ok(!mockNodes["task-model-config-trigger"].getAttribute("aria-label").includes("直连生产"));
  assert.ok(mockNodes["task-model-config-status"].className.includes("empty"), "status indicator must reflect empty state");

  // --- Test 2: Menu ARIA roles, aria-checked, and aria-activedescendant on trigger ---
  testState.workflowProfilesByTask["excel.analysis"].activeProfileId = "flow-1";
  testState.workflowProfileSelections["excel.analysis"] = "flow-1";
  baseContext.renderWorkflowProfileStrip();
  assert.strictEqual(mockNodes["task-model-config-label"].textContent, "生产版 · 工作流平台");

  baseContext.openTaskModelConfigMenu();
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-expanded"), "true");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), "task-model-config-option-0");
  assert.strictEqual(mockNodes["task-model-config-menu"].getAttribute("aria-activedescendant"), null, "aria-activedescendant must not sit on menu");

  const menuButtons = mockNodes["task-model-config-menu"].querySelectorAll("[data-config-action]");
  assert.strictEqual(menuButtons.length, 3);
  assert.strictEqual(menuButtons[0].getAttribute("role"), "menuitemradio");
  assert.strictEqual(menuButtons[0].getAttribute("aria-checked"), "true", "active profile must have aria-checked=true");
  assert.strictEqual(menuButtons[1].getAttribute("role"), "menuitemradio");
  assert.strictEqual(menuButtons[1].getAttribute("aria-checked"), "false", "inactive profile must have aria-checked=false");
  assert.strictEqual(menuButtons[2].getAttribute("role"), "menuitem");
  assert.strictEqual(menuButtons[2].getAttribute("aria-checked"), null, "manage action must not have aria-checked");

  // Keyboard navigation moves highlight
  baseContext.updateTaskModelConfigMenuHighlight(1);
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), "task-model-config-option-1");
  assert.ok(menuButtons[1].classList.contains("is-active"));
  assert.ok(!menuButtons[0].classList.contains("is-active"));
  assert.strictEqual(menuButtons[0].getAttribute("aria-checked"), "true", "highlight movement must not corrupt aria-checked selection state");

  // Close menu removes aria-activedescendant from trigger
  baseContext.closeTaskModelConfigMenu(false);
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-expanded"), "false");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), null);

  // --- Test 3: Settings navigation and document.activeElement ---
  baseContext.applyTaskModelConfigMenuItem = loadFunction("applyTaskModelConfigMenuItem", baseContext);
  mockDocument.activeElement = mockNodes["task-model-config-trigger"];
  baseContext.applyTaskModelConfigMenuItem({ action: "manage" }, false);
  assert.strictEqual(testState.currentMode, "settings");
  assert.ok(mockNodes["settings-view"].classList.contains("active"));
  assert.ok(!mockNodes["home-view"].classList.contains("active"));
  assert.strictEqual(
    mockDocument.activeElement,
    mockTabs["excel.analysis"],
    "navigating via 管理配置 must move document.activeElement to the task tab in settings view"
  );
  assert.notStrictEqual(mockDocument.activeElement, mockNodes["task-model-config-trigger"]);

  // --- Test 4: Activation vs refresh failure behavior ---
  baseContext.switchMode("excelAnalysis");
  testState.workflowProfileSelections["excel.analysis"] = "flow-1";
  testState.workflowProfilesByTask["excel.analysis"].activeProfileId = "flow-1";

  baseContext.request = (url) => {
    if (url.includes("/activate")) {
      return Promise.resolve({
        data: {
          taskType: "excel.analysis",
          activeConfigurationId: "direct-1",
          configurations: [PLATFORM_PROFILE, SECRET_PROFILE]
        }
      });
    }
    return Promise.reject(new Error("unexpected url"));
  };
  baseContext.loadWorkflowProfileForTask = () => {
    return Promise.resolve({ failed: true });
  };
  baseContext.activateWorkflowProfile = loadFunction("activateWorkflowProfile", baseContext);

  await baseContext.activateWorkflowProfile("direct-1", "flow-1", "excel.analysis");
  assert.strictEqual(testState.workflowProfileSelections["excel.analysis"], "direct-1", "selection must remain direct-1 even if list refresh failed");
  assert.ok(statusMessage.includes("刷新最新列表失败"), `expected refresh failure message, got: ${statusMessage}`);
  assert.notStrictEqual(testState.taskModelConfigStatusByTask["excel.analysis"], "error", "refresh failure must not flag switch error");

  baseContext.request = () => Promise.reject(new Error("网络异常 503"));
  await baseContext.activateWorkflowProfile("flow-1", "direct-1", "excel.analysis");
  assert.strictEqual(testState.workflowProfileSelections["excel.analysis"], "direct-1", "activation failure must roll back selection");
  assert.ok(statusMessage.includes("切换模型配置失败"), `expected activation failure message, got: ${statusMessage}`);
  assert.strictEqual(testState.taskModelConfigStatusByTask["excel.analysis"], "error");
}

async function assertWordBehavioralDomContracts() {
  function functionSource(name) {
    const start = wordJs.indexOf(`  function ${name}(`);
    assert.notStrictEqual(start, -1, `missing function ${name} in Word JS`);
    const next = wordJs.indexOf("\n  function ", start + 3);
    return wordJs.slice(start, next === -1 ? wordJs.length : next);
  }
  function loadFunction(name, context = {}) {
    return vm.runInNewContext(`(${functionSource(name)})`, context);
  }

  function createClassList(initial = []) {
    const classes = new Set(initial);
    return {
      add(...names) { names.forEach((n) => classes.add(n)); },
      remove(...names) { names.forEach((n) => classes.delete(n)); },
      toggle(name, force) {
        if (force === undefined) {
          if (classes.has(name)) classes.delete(name); else classes.add(name);
        } else if (force) {
          classes.add(name);
        } else {
          classes.delete(name);
        }
      },
      contains(name) { return classes.has(name); }
    };
  }

  function createMockElement(id = "", tagName = "div") {
    const attributes = {};
    const classList = createClassList();
    const children = [];
    let currentInnerHtml = "";
    const el = {
      id: id,
      tagName: tagName.toUpperCase(),
      attributes: attributes,
      classList: classList,
      children: children,
      hidden: false,
      disabled: false,
      textContent: "",
      setAttribute(name, value) { attributes[name] = String(value); },
      getAttribute(name) { return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null; },
      removeAttribute(name) { delete attributes[name]; },
      hasAttribute(name) { return Object.prototype.hasOwnProperty.call(attributes, name); },
      getBoundingClientRect() { return { top: 100, bottom: 200, height: 100, width: 200 }; },
      focus() {
        mockDocument.activeElement = el;
      },
      querySelectorAll(selector) {
        if (selector === "[data-config-action]") {
          return children.filter((c) => c.hasAttribute("data-config-action"));
        }
        return [];
      },
      get innerHTML() { return currentInnerHtml; },
      set innerHTML(val) {
        currentInnerHtml = val;
        children.length = 0;
        if (!val) return;
        const regex = /<button\s+([^>]+)>([^<]*)<\/button>/g;
        let match;
        while ((match = regex.exec(val)) !== null) {
          const attrsStr = match[1];
          const text = match[2];
          const btn = createMockElement("", "button");
          btn.textContent = text;
          const attrRegex = /([a-zA-Z0-9_-]+)="([^"]*)"/g;
          let attrMatch;
          while ((attrMatch = attrRegex.exec(attrsStr)) !== null) {
            btn.setAttribute(attrMatch[1], attrMatch[2]);
            if (attrMatch[1] === "id") btn.id = attrMatch[2];
            if (attrMatch[1] === "class") {
              attrMatch[2].split(/\s+/).forEach((c) => { if (c) btn.classList.add(c); });
            }
          }
          if (attrsStr.includes("disabled")) btn.disabled = true;
          children.push(btn);
        }
      }
    };
    return el;
  }

  const mockTabs = {
    "word.smart_write": createMockElement("tab-word-smart-write", "button"),
    "word.smart_imitation": createMockElement("tab-word-smart-imitation", "button"),
    "word.document_review": createMockElement("tab-word-document-review", "button"),
    "word.format_review": createMockElement("tab-word-format-review", "button")
  };
  mockTabs["word.smart_write"].setAttribute("data-workflow-task-tab", "word.smart_write");
  mockTabs["word.smart_imitation"].setAttribute("data-workflow-task-tab", "word.smart_imitation");
  mockTabs["word.document_review"].setAttribute("data-workflow-task-tab", "word.document_review");
  mockTabs["word.format_review"].setAttribute("data-workflow-task-tab", "word.format_review");

  const mockNodes = {
    "workflow-profile-strip": createMockElement("workflow-profile-strip"),
    "task-model-config-trigger": createMockElement("task-model-config-trigger", "button"),
    "task-model-config-menu": createMockElement("task-model-config-menu"),
    "task-model-config-label": createMockElement("task-model-config-label", "span"),
    "task-model-config-status": createMockElement("task-model-config-status", "span"),
    "workflow-switch-feedback": createMockElement("workflow-switch-feedback", "span"),
    "home-view": createMockElement("home-view", "section"),
    "settings-view": createMockElement("settings-view", "section"),
    "task-title": createMockElement("task-title", "h2"),
    "btn-open-settings": createMockElement("btn-open-settings", "button"),
    "workflow-profile-manager": createMockElement("workflow-profile-manager"),
    "btn-new-workflow-profile": createMockElement("btn-new-workflow-profile", "button"),
    "diagnostics-disclosure": createMockElement("diagnostics-disclosure")
  };
  mockNodes["home-view"].classList.add("active");

  const mockDocument = {
    activeElement: mockNodes["task-model-config-trigger"],
    body: createMockElement("body", "body"),
    querySelector(sel) {
      const tabMatch = sel && sel.match(/\[data-workflow-task-tab="([^"]+)"\]/);
      if (tabMatch && mockTabs[tabMatch[1]]) {
        return mockTabs[tabMatch[1]];
      }
      return null;
    }
  };

  const byId = (id) => mockNodes[id] || null;
  const setNodeTextIfChanged = (node, text) => { if (node) node.textContent = text; };
  const escaped = (v) => wordHelpers.escapeHtml ? wordHelpers.escapeHtml(v) : String(v || "");

  const testState = {
    currentMode: "smartWrite",
    lastTaskMode: "smartWrite",
    busy: false,
    workflowProfileMutationBusy: false,
    taskModelConfigStatusByTask: {},
    taskModelConfigMenu: { open: false, highlightedIndex: -1, itemCount: 0, items: [] },
    workflowProfileSelections: { "word.smart_write": "" },
    workflowProfiles: {},
    modelInterfaceDetectable: true,
    workflowProfileEditor: null,
    providerUrlEditorOpen: false
  };

  const baseContext = {
    state: testState,
    helpers: wordHelpers,
    byId: byId,
    setNodeTextIfChanged: setNodeTextIfChanged,
    escaped: escaped,
    document: mockDocument,
    window: { innerHeight: 700 },
    MODE_WORKFLOW_TASK_TYPES: {
      smartWrite: "word.smart_write",
      smartImitation: "word.smart_imitation",
      documentReview: "word.document_review",
      formatReview: "word.format_review"
    },
    TASK_API_KEY_DEFS: [
      { taskType: "word.smart_write", label: "智能编写" },
      { taskType: "word.smart_imitation", label: "智能仿写" },
      { taskType: "word.document_review", label: "文档审查" },
      { taskType: "word.format_review", label: "格式审查" }
    ],
    getCurrentWorkflowTaskType() {
      return baseContext.MODE_WORKFLOW_TASK_TYPES[testState.currentMode] || "";
    },
    getWorkflowProfileData(task) {
      return testState.workflowProfiles[task] || { taskType: task, activeProfileId: "", profiles: [] };
    },
    getWorkflowProfileById(task, id) {
      const d = testState.workflowProfiles[task];
      return d && d.profiles ? d.profiles.find((x) => x.id === id) : null;
    },
    focusTaskModelConfigTrigger() { mockNodes["task-model-config-trigger"].focus(); },
    describeFetchError(err) { return err && err.message || String(err); },
    renderModelInterfaceState() {},
    renderWorkflowProfileManager() {},
    renderWorkflowTaskTabs() {},
    switchView() {},
    switchMode(mode) {
      testState.currentMode = mode;
      if (mode === "settings") {
        mockNodes["settings-view"].classList.add("active");
        mockNodes["home-view"].classList.remove("active");
      } else {
        mockNodes["home-view"].classList.add("active");
        mockNodes["settings-view"].classList.remove("active");
      }
    },
    normalizeWorkflowProfileData(data, task) {
      return {
        taskType: task,
        activeProfileId: data.activeConfigurationId || "",
        profiles: data.configurations || []
      };
    },
    syncWorkflowProfileManagerBusyState() {},
    syncSettingsRefreshController() {},
    invalidateWorkflowProfileRequests() {},
    loadWorkflowProfiles() { return Promise.resolve(); }
  };

  baseContext.isWorkflowInteractionBlocked = loadFunction("isWorkflowInteractionBlocked", baseContext);
  baseContext.escapeWorkflowText = loadFunction("escapeWorkflowText", baseContext);
  baseContext.taskModelConfigOptionId = loadFunction("taskModelConfigOptionId", baseContext);
  baseContext.positionTaskModelConfigMenu = loadFunction("positionTaskModelConfigMenu", baseContext);
  baseContext.updateTaskModelConfigMenuHighlight = loadFunction("updateTaskModelConfigMenuHighlight", baseContext);
  baseContext.closeTaskModelConfigMenu = loadFunction("closeTaskModelConfigMenu", baseContext);
  baseContext.renderTaskModelConfigMenu = loadFunction("renderTaskModelConfigMenu", baseContext);
  baseContext.currentTaskModelConfigProfile = loadFunction("currentTaskModelConfigProfile", baseContext);
  baseContext.resolveTaskModelConfigStatus = loadFunction("resolveTaskModelConfigStatus", baseContext);
  baseContext.openTaskModelConfigMenu = loadFunction("openTaskModelConfigMenu", baseContext);
  baseContext.renderWorkflowProfileStrip = loadFunction("renderWorkflowProfileStrip", baseContext);
  baseContext.setWorkflowProfileMutationBusy = loadFunction("setWorkflowProfileMutationBusy", baseContext);

  let statusMessage = "";
  baseContext.setStatus = (msg) => { statusMessage = msg; };

  // Test 1: Unactivated profile rendering on Word task page
  testState.workflowProfiles["word.smart_write"] = {
    taskType: "word.smart_write",
    activeProfileId: "",
    profiles: [PLATFORM_PROFILE, SECRET_PROFILE]
  };
  testState.workflowProfileSelections["word.smart_write"] = "";
  const resolvedUnactivated = baseContext.currentTaskModelConfigProfile(testState.workflowProfiles["word.smart_write"]);
  assert.strictEqual(resolvedUnactivated, null, "Word currentTaskModelConfigProfile must return null when activeProfileId is empty");

  baseContext.renderWorkflowProfileStrip();
  assert.strictEqual(mockNodes["task-model-config-label"].textContent, "未配置");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-label"), "选择智能编写模型配置，未配置");
  assert.ok(mockNodes["task-model-config-status"].className.includes("empty"), "status indicator must reflect empty state");

  // Test 2: Active profile & menu ARIA
  testState.workflowProfiles["word.smart_write"].activeProfileId = "flow-1";
  testState.workflowProfileSelections["word.smart_write"] = "flow-1";
  baseContext.renderWorkflowProfileStrip();
  assert.strictEqual(mockNodes["task-model-config-label"].textContent, "生产版 · 工作流平台");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-label"), "选择智能编写模型配置，已就绪 生产版 · 工作流平台");

  baseContext.openTaskModelConfigMenu();
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-expanded"), "true");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), "task-model-config-option-0");

  const menuButtons = mockNodes["task-model-config-menu"].querySelectorAll("[data-config-action]");
  assert.strictEqual(menuButtons.length, 3);
  assert.strictEqual(menuButtons[0].getAttribute("role"), "menuitemradio");
  assert.strictEqual(menuButtons[0].getAttribute("aria-checked"), "true");
  assert.strictEqual(menuButtons[1].getAttribute("role"), "menuitemradio");
  assert.strictEqual(menuButtons[1].getAttribute("aria-checked"), "false");
  assert.strictEqual(menuButtons[2].getAttribute("role"), "menuitem");

  baseContext.updateTaskModelConfigMenuHighlight(1);
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), "task-model-config-option-1");
  assert.ok(menuButtons[1].classList.contains("is-active"));

  baseContext.closeTaskModelConfigMenu(false);
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-expanded"), "false");
  assert.strictEqual(mockNodes["task-model-config-trigger"].getAttribute("aria-activedescendant"), null);

  // Test 3: Settings navigation moves activeElement to Word task tab
  baseContext.applyTaskModelConfigMenuItem = loadFunction("applyTaskModelConfigMenuItem", baseContext);
  mockDocument.activeElement = mockNodes["task-model-config-trigger"];
  baseContext.applyTaskModelConfigMenuItem({ action: "manage" }, false);
  assert.strictEqual(testState.currentMode, "settings");
  assert.strictEqual(
    mockDocument.activeElement,
    mockTabs["word.smart_write"],
    "Word 管理配置 must move activeElement to the active Word task tab in settings"
  );

  // Test 4: Activation vs refresh failure and task isolation across Word tasks
  testState.currentMode = "smartWrite";
  testState.workflowProfileSelections["word.smart_write"] = "flow-1";
  testState.workflowProfiles["word.smart_write"].activeProfileId = "flow-1";

  baseContext.request = (url) => {
    if (url.includes("/activate")) {
      return Promise.resolve({
        data: {
          taskType: "word.smart_write",
          activeConfigurationId: "direct-1",
          configurations: [PLATFORM_PROFILE, SECRET_PROFILE]
        }
      });
    }
    return Promise.reject(new Error("unexpected url"));
  };
  baseContext.loadWorkflowProfiles = () => Promise.resolve();
  baseContext.activateWorkflowProfile = loadFunction("activateWorkflowProfile", baseContext);

  await baseContext.activateWorkflowProfile("direct-1", "word.smart_write", "flow-1");
  assert.strictEqual(testState.workflowProfileSelections["word.smart_write"], "direct-1");
  assert.notStrictEqual(testState.taskModelConfigStatusByTask["word.smart_write"], "error");

  baseContext.request = () => Promise.reject(new Error("网络异常 503"));
  await baseContext.activateWorkflowProfile("flow-1", "word.smart_write", "direct-1");
  assert.strictEqual(testState.workflowProfileSelections["word.smart_write"], "direct-1", "Word activation failure must roll back selection");
  assert.strictEqual(testState.taskModelConfigStatusByTask["word.smart_write"], "error");

  // Document review must be isolated and have no error
  assert.strictEqual(testState.taskModelConfigStatusByTask["word.document_review"], undefined);
}

// Excel tests
assertLabelContract(helpers);
assertMenuContract(helpers);
assertTaskStatusIsolationContract(helpers);
assertActivationContract(helpers);
assertKeyboardContract(helpers);
assertExcelTaskPagesUseCompactEntry();
assertSettingsNavigationContract();
assertExcelTaskContextContract();
assertLayoutContract(excelCssHead, "Excel");
assertUnactivatedProfileContract(helpers, "excel.analysis");

// Word tests
assertLabelContract(wordHelpers);
assertMenuContract(wordHelpers);
assertActivationContract(wordHelpers);
assertKeyboardContract(wordHelpers);
assertWordTaskPagesUseCompactEntry();
assertWordSettingsNavigationContract();
assertWordTaskContextContract();
assertLayoutContract(wordCssHead, "Word");
assertUnactivatedProfileContract(wordHelpers, "word.smart_write");

Promise.all([
  assertBehavioralDomContracts(),
  assertWordBehavioralDomContracts()
]).then(() => {
  console.log("task model config entry contract tests passed");
}).catch((err) => {
  console.error(err);
  process.exit(1);
});
