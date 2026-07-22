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

const commonCssMarkers = [
  ".model-interface-card",
  ".readiness-badge",
  ".workflow-settings-heading",
  ".workflow-help-popover",
  ".workflow-task-tabs",
  ".advanced-diagnostics",
  "@keyframes disclosure-in",
  ".advanced-diagnostics[open]",
  ":focus-visible",
  ":active",
  "@media (prefers-reduced-motion: reduce)"
];
const sharedCssMarker = "/* Shared restrained settings and interaction treatment. */";
const sharedCssTails = [];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getTag(html, id) {
  const match = html.match(new RegExp(`<[a-z][^>]*\\bid="${escapeRegExp(id)}"[^>]*>`, "i"));
  assert.ok(match, `missing element #${id}`);
  return match[0];
}

function getTagWithAttribute(html, tagName, attribute, value) {
  const match = html.match(
    new RegExp(`<${tagName}\\b[^>]*\\b${attribute}="${escapeRegExp(value)}"[^>]*>`, "i")
  );
  assert.ok(match, `missing <${tagName}> with ${attribute}="${value}"`);
  return match[0];
}

function collectHtmlIds(html) {
  return new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), (match) => match[1]));
}

function collectLiteralByIds(js) {
  return new Set(Array.from(js.matchAll(/\bbyId\("([^"]+)"\)/g), (match) => match[1]));
}

function cssRuleBodies(css, selector) {
  const pattern = new RegExp(`(?:^|\\n)[ \\t]*${escapeRegExp(selector)}[ \\t]*\\{([^}]*)\\}`, "g");
  return Array.from(css.matchAll(pattern), (match) => match[1]);
}

function extractCssRules(css, selector) {
  const rules = [];
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1]
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split(",")
      .map((value) => value.trim());
    if (selectors.includes(selector)) {
      rules.push(match[2]);
    }
  }
  return rules;
}

function extractCssRule(css, selector, requiredDeclaration) {
  const rules = extractCssRules(css, selector);
  const rule = requiredDeclaration
    ? rules.find((body) => body.includes(requiredDeclaration))
    : rules[rules.length - 1];
  assert.notStrictEqual(rule, undefined, `missing CSS rule ${selector}`);
  return rule;
}

function extractCssBlock(css, header) {
  const start = css.indexOf(header);
  assert.notStrictEqual(start, -1, `missing CSS block ${header}`);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let index = open; index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    if (css[index] === "}") depth -= 1;
    if (depth === 0) return css.slice(open + 1, index);
  }
  assert.fail(`unclosed CSS block ${header}`);
}

function hasClass(tag, className) {
  const match = tag.match(/\bclass="([^"]*)"/i);
  return Boolean(match && match[1].split(/\s+/).includes(className));
}

function assertElementTextStartsWith(html, tag, text, message) {
  const start = html.indexOf(tag);
  assert.ok(start >= 0 && html.slice(start + tag.length).startsWith(text), message);
}

function functionSource(js, name) {
  const start = js.indexOf(`  function ${name}(`);
  assert.notStrictEqual(start, -1, `missing function ${name}`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

hosts.forEach((host) => {
  const html = fs.readFileSync(path.join(ROOT, host.dir, "taskpane.html"), "utf8");
  const js = fs.readFileSync(path.join(ROOT, host.dir, "taskpane.js"), "utf8");
  const css = fs.readFileSync(path.join(ROOT, host.dir, "taskpane.css"), "utf8");
  const htmlIds = collectHtmlIds(html);

  commonCssMarkers.forEach((marker) => {
    assert.ok(css.includes(marker), `${host.name} CSS missing ${marker}`);
  });
  const diagnosticsRules = cssRuleBodies(css, ".advanced-diagnostics");
  assert.ok(diagnosticsRules.length > 0, `${host.name} CSS missing .advanced-diagnostics rule`);
  diagnosticsRules.forEach((body) => {
    assert.ok(!/overflow\s*:\s*hidden/.test(body), `${host.name} diagnostics must not clip focus outline`);
  });
  const textActionHover = extractCssRule(css, ".text-action:hover");
  const infoButtonHover = extractCssRule(css, ".info-button:hover");
  [textActionHover, infoButtonHover].forEach((body) => {
    assert.ok(body.includes("border-color: var(--border-color);"), `${host.name} utility hover border mismatch`);
    assert.ok(body.includes("background: var(--host-accent-soft);"), `${host.name} utility hover background mismatch`);
    assert.ok(body.includes("color: var(--host-accent);"), `${host.name} utility hover color mismatch`);
  });
  const popoverRule = extractCssRule(css, ".workflow-help-popover", "width: 260px;");
  const fallbackMaxWidth = popoverRule.indexOf("max-width: calc(100vw - 40px);");
  const modernMaxWidth = popoverRule.indexOf("max-width: min(260px, calc(100vw - 40px));");
  assert.ok(fallbackMaxWidth >= 0, `${host.name} popover missing calc fallback`);
  assert.ok(modernMaxWidth > fallbackMaxWidth, `${host.name} popover fallback order mismatch`);
  assert.ok(
    popoverRule.indexOf("width: max-content;") > popoverRule.indexOf("width: 260px;"),
    `${host.name} popover width fallback order mismatch`
  );
  const tabsRule = extractCssRule(css, ".workflow-task-tabs", "padding:");
  assert.ok(tabsRule.includes("padding: 4px 10px 5px 4px;"), `${host.name} tabs must preserve focus outline space`);
  const disclosureOpenRule = extractCssRule(css, ".advanced-diagnostics[open] > .advanced-diagnostics-content");
  assert.ok(
    disclosureOpenRule.includes("animation: disclosure-in 160ms ease-out;"),
    `${host.name} disclosure animation mismatch`
  );
  assert.ok(css.includes("button:active:not(:disabled),"), `${host.name} active selector must exclude disabled buttons`);
  assert.ok(!/(?:^|\n)button:active\s*,/.test(css), `${host.name} CSS includes bare grouped button:active`);
  assert.ok(!/(?:^|\n)button:active\s*\{/.test(css), `${host.name} CSS includes bare button:active rule`);
  const reducedMotion = extractCssBlock(css, "@media (prefers-reduced-motion: reduce)");
  assert.ok(reducedMotion.includes("transition-duration: 0.01ms !important;"), `${host.name} reduced transition mismatch`);
  assert.ok(reducedMotion.includes("animation-duration: 0.01ms !important;"), `${host.name} reduced animation mismatch`);
  const sharedStart = css.indexOf(sharedCssMarker);
  assert.notStrictEqual(sharedStart, -1, `${host.name} CSS missing shared interaction tail`);
  sharedCssTails.push(css.slice(sharedStart).replace(/\r\n/g, "\n").trim());
  assert.ok(css.includes("--host-accent: var(--color-primary);"), `${host.name} host accent mapping mismatch`);
  assert.ok(
    css.includes("--host-accent-soft: var(--color-surface-muted);"),
    `${host.name} soft host accent mapping mismatch`
  );
  assert.ok(css.includes("--border-color: var(--color-border);"), `${host.name} border mapping mismatch`);
  assert.ok(
    css.includes('font-family: system-ui, -apple-system, BlinkMacSystemFont, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;'),
    `${host.name} body font stack mismatch`
  );
  assert.ok(!css.includes("backdrop-filter"), `${host.name} CSS must not use backdrop-filter`);
  assert.ok(!/letter-spacing\s*:\s*-/.test(css), `${host.name} CSS must not use negative letter spacing`);

  commonIds.forEach((id) => {
    assert.ok(htmlIds.has(id), `${host.name} missing #${id}`);
  });
  collectLiteralByIds(js).forEach((id) => {
    assert.ok(htmlIds.has(id), `${host.name} JS references missing #${id}`);
  });

  const providerCard = getTag(html, "provider-summary-card");
  assert.ok(providerCard.startsWith("<section"), `${host.name} provider summary must be a section`);
  assert.ok(hasClass(providerCard, "settings-card"), `${host.name} provider summary missing settings-card`);
  assert.ok(hasClass(providerCard, "model-interface-card"), `${host.name} provider summary missing model-interface-card`);
  assert.ok(html.includes('class="model-interface-heading"'), `${host.name} missing model interface heading`);
  assert.ok(html.includes('class="model-interface-row"'), `${host.name} missing model interface row`);

  const readinessBadge = getTag(html, "provider-readiness-badge");
  assert.ok(hasClass(readinessBadge, "readiness-badge"), `${host.name} readiness badge class mismatch`);
  assert.ok(hasClass(readinessBadge, "is-unavailable"), `${host.name} readiness state class mismatch`);
  assert.ok(readinessBadge.includes('aria-live="polite"'), `${host.name} readiness badge must be live`);
  assertElementTextStartsWith(html, readinessBadge, "无法检测", `${host.name} readiness initial text mismatch`);

  const providerSummary = getTag(html, "provider-summary-url");
  assert.ok(hasClass(providerSummary, "provider-url-summary"), `${host.name} provider URL class mismatch`);
  assert.ok(providerSummary.includes('title=""'), `${host.name} provider URL title mismatch`);
  assertElementTextStartsWith(html, providerSummary, "未配置接口地址", `${host.name} provider URL initial text mismatch`);

  const editProviderButton = getTag(html, "btn-edit-provider-url");
  assert.ok(editProviderButton.startsWith("<button"), `${host.name} provider edit action must be a button`);
  assert.ok(hasClass(editProviderButton, "text-action"), `${host.name} provider edit action class mismatch`);
  assert.ok(editProviderButton.includes('type="button"'), `${host.name} provider edit action type mismatch`);
  assertElementTextStartsWith(html, editProviderButton, "修改", `${host.name} provider edit action text mismatch`);

  const helpButton = getTag(html, "workflow-help-button");
  assert.ok(helpButton.includes('aria-expanded="false"'), `${host.name} help button must start collapsed`);
  assert.ok(helpButton.includes('aria-controls="workflow-help-popover"'), `${host.name} help button missing controls`);

  const helpPopover = getTag(html, "workflow-help-popover");
  assert.ok(hasClass(helpPopover, "workflow-help-popover"), `${host.name} help popover class mismatch`);
  assert.ok(helpPopover.includes('role="tooltip"'), `${host.name} help popover role mismatch`);
  assert.ok(/\shidden(?:\s|>)/.test(helpPopover), `${host.name} help popover must start hidden`);
  assert.ok(
    html.includes("每项任务可保存多个工作流，可在任务页选择当前使用的工作流。"),
    `${host.name} missing workflow help copy`
  );

  const taskTabs = getTag(html, "workflow-task-tabs");
  assert.ok(taskTabs.includes('role="tablist"'), `${host.name} task tabs missing tablist role`);
  assert.ok(taskTabs.includes(`aria-label="${host.tabsLabel}"`), `${host.name} task tabs label mismatch`);
  const selectedTaskTab = getTagWithAttribute(html, "button", "data-workflow-task-tab", host.task);
  assert.ok(selectedTaskTab.includes('role="tab"'), `${host.name} task button missing tab role`);
  assert.ok(selectedTaskTab.includes('aria-selected="true"'), `${host.name} current task tab is not selected`);
  assertElementTextStartsWith(html, selectedTaskTab, host.label, `${host.name} task tab label mismatch`);

  assert.ok(!htmlIds.has("btn-refresh"), `${host.name} still includes #btn-refresh`);
  assert.ok(
    !html.includes("每项任务可保存多个工作流</span>"),
    `${host.name} still renders persistent multi-workflow copy`
  );
  assert.strictEqual(
    htmlIds.has("enterprise-knowledge-summary-card"),
    host.hasKnowledge,
    `${host.name} enterprise knowledge isolation mismatch`
  );
  assert.ok(!js.includes('byId("btn-refresh")'), `${host.name} JS still references removed #btn-refresh`);
});

sharedCssTails.slice(1).forEach((tail, index) => {
  assert.strictEqual(tail, sharedCssTails[0], `${hosts[index + 1].name} shared interaction CSS drifted`);
});

const wordHtml = fs.readFileSync(path.join(ROOT, hosts[0].dir, "taskpane.html"), "utf8");
const wordJs = fs.readFileSync(path.join(ROOT, hosts[0].dir, "taskpane.js"), "utf8");
const excelJs = fs.readFileSync(path.join(ROOT, hosts[1].dir, "taskpane.js"), "utf8");
const pptJs = fs.readFileSync(path.join(ROOT, hosts[2].dir, "taskpane.js"), "utf8");
[
  "word.smart_write",
  "word.smart_imitation",
  "word.document_review",
  "word.format_review"
].forEach((task) => {
  assert.ok(wordHtml.includes(`data-workflow-task-tab="${task}"`), `Word missing ${task} tab`);
});
assert.ok(wordJs.includes('byId("btn-edit-provider-url")'), "Word JS missing provider edit binding");
assert.ok(excelJs.includes('byId("btn-edit-provider-url")'), "Excel JS missing provider edit binding");
assert.ok(pptJs.includes('byId("provider-summary-url")'), "PPT JS missing provider summary reference");
assert.ok(!pptJs.includes('byId("provider-url-summary")'), "PPT JS still references old provider summary ID");

const renderKnowledgeManagerView = functionSource(wordJs, "renderKnowledgeManagerView");
assert.ok(
  renderKnowledgeManagerView.includes('byId("diagnostics-disclosure")'),
  "Word knowledge subviews must control the diagnostics disclosure"
);
assert.ok(
  renderKnowledgeManagerView.includes("diagnosticsDisclosure.hidden = false"),
  "Word settings home must show the diagnostics disclosure"
);
assert.ok(
  renderKnowledgeManagerView.indexOf("diagnosticsDisclosure.open = false") <
    renderKnowledgeManagerView.indexOf("diagnosticsDisclosure.hidden = true"),
  "Word knowledge subviews must collapse diagnostics before hiding it"
);
assert.ok(
  !renderKnowledgeManagerView.includes('byId("diagnostics-section").hidden'),
  "Word knowledge subviews must not hide the diagnostics content directly"
);

console.log("taskpane experience markup contract passed");
