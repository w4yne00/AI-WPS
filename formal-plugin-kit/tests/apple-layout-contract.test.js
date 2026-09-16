const assert = require("assert");
const fs = require("fs");
const path = require("path");
const test = require("node:test");

const ROOT = path.join(__dirname, "..");
const HOSTS = {
  word: "wps-ai-assistant_1.0.0",
  excel: "wps-ai-assistant-et_1.0.0",
  ppt: "wps-ai-assistant-wpp_1.0.0"
};

function source(host, file) {
  return fs.readFileSync(path.join(ROOT, HOSTS[host], file), "utf8");
}

function before(text, first, second, message) {
  const firstIndex = text.indexOf(first);
  const secondIndex = text.indexOf(second);
  assert.notStrictEqual(firstIndex, -1, `${message}: missing ${first}`);
  assert.notStrictEqual(secondIndex, -1, `${message}: missing ${second}`);
  assert.ok(firstIndex < secondIndex, message);
}

test("all settings pages order model, direct-model, then workflow configuration in the DOM", () => {
  Object.keys(HOSTS).forEach((host) => {
    const html = source(host, "taskpane.html");
    before(html, 'id="model-configuration-card"', 'id="direct-services-card"', `${host} model precedes direct model`);
    before(html, 'id="direct-services-card"', 'id="workflow-configuration-card"', `${host} direct model precedes workflow`);
  });
});

test("direct model guidance is hidden behind an accessible exclamation control", () => {
  Object.keys(HOSTS).forEach((host) => {
    const html = source(host, "taskpane.html");
    assert.match(html, /<h4>直连模型配置<\/h4>/);
    assert.match(html, /class="settings-title-actions"/);
    assert.match(html, /class="context-help settings-card-help"/);
    assert.match(html, /aria-label="查看直连模型配置说明"/);
    assert.match(html, />!<\/summary>/);
    assert.match(html, />新建<\/button>/);
    assert.doesNotMatch(html, /<p class="field-hint">同一运行环境所有宿主共享配置/);
  });
});

test("task access cards use a generic label without a visual help affordance", () => {
  Object.keys(HOSTS).forEach((host) => {
    const html = source(host, "taskpane.html");
    const js = source(host, "taskpane.js");
    assert.match(html, />接入选择<\/h4>/);
    assert.match(html, />-- 使用工作流或模型配置 --<\/option>/);
    assert.match(js, /-- 使用工作流或模型配置 --/);
    assert.doesNotMatch(js, /-- 使用工作流平台配置 --/);
    assert.doesNotMatch(html, /aria-label="查看接入选择说明"/);
    assert.doesNotMatch(html, />接入模式<\/span>/);
    assert.doesNotMatch(js, /title(?:Node)?\.textContent = "(?:智能编写|智能仿写|文档审查|格式审查|智能分析|公式助手|智能填写|智能总结|结构审查)接入选择"/);
  });
});

test("settings cards share compact create actions and omit redundant summaries", () => {
  Object.keys(HOSTS).forEach((host) => {
    const html = source(host, "taskpane.html");
    const js = source(host, "taskpane.js");
    assert.match(html, /class="settings-title-actions"[\s\S]*?id="btn-new-direct-service" class="settings-create-action"/);
    assert.match(html, /class="settings-title-actions"[\s\S]*?id="btn-new-workflow-profile" class="settings-create-action"/);
    assert.doesNotMatch(html, /id="workflow-manager-summary"|id="workflow-profile-count"/);
    assert.doesNotMatch(js, /byId\("workflow-manager-summary"\)|byId\("workflow-profile-count"\)/);
    assert.match(js, /class="direct-services-empty-state"/);
  });
});

test("settings styles separate headings from their dependent status and controls", () => {
  Object.keys(HOSTS).forEach((host) => {
    const css = source(host, "taskpane.css");
    assert.match(css, /\.task-selection-heading\s*\{[\s\S]*?margin-bottom:\s*8px/);
    assert.match(css, /\.settings-create-action\s*\{[\s\S]*?min-height:\s*32px[\s\S]*?padding:\s*5px 12px/);
    assert.match(css, /\.direct-services-empty-state\s*\{[\s\S]*?align-items:\s*center[\s\S]*?justify-content:\s*center[\s\S]*?text-align:\s*center/);
  });
  const wordCss = source("word", "taskpane.css");
  assert.match(wordCss, /\.writing-policy-summary-title\s*\{[\s\S]*?gap:\s*6px/);
  const excelCss = source("excel", "taskpane.css");
  assert.match(
    excelCss,
    /@media \(max-width:\s*420px\)[\s\S]*?\.workflow-manager-head \.settings-create-action\s*\{[\s\S]*?width:\s*auto/,
    "Excel compact create action must not stretch across the narrow settings card"
  );
});

test("workflow-only configuration uses workflow terminology", () => {
  Object.keys(HOSTS).forEach((host) => {
    const html = source(host, "taskpane.html");
    const js = source(host, "taskpane.js");
    assert.match(html, /id="workflow-configuration-card"/);
    assert.match(html, />工作流配置<\/h[234]>/);
    assert.match(html, /id="btn-new-workflow-profile"[^>]*>新建<\/button>/);
    assert.match(js, /尚未建立工作流配置/);
    assert.doesNotMatch(js, /尚未建立模型配置/);
  });
});

test("Word and Excel place history in the heading and copy actions below output", () => {
  ["word", "excel"].forEach((host) => {
    const html = source(host, "taskpane.html");
    before(html, "结果预览", 'id="btn-view-history"', `${host} result title precedes history`);
    before(html, 'id="result-output"', 'class="copy-toolbar', `${host} copy toolbar follows output`);
    before(html, 'class="copy-toolbar', 'id="btn-copy-result"', `${host} copy button lives in toolbar`);
  });
});

test("PPT structure review uses contextual help and the shared result title", () => {
  const html = source("ppt", "taskpane.html");
  assert.match(html, /aria-label="查看结构审查说明"/);
  assert.match(html, /class="context-help-popover"[^>]*>结构审查只读取页码/);
  assert.doesNotMatch(html, /<p class="task-guidance">结构审查只读取页码/);
  assert.match(html, /id="structure-result-title">结果预览<\/h2>/);
});

test("Excel moves persistent task guidance out of the primary form", () => {
  const html = source("excel", "taskpane.html");
  assert.doesNotMatch(html, /<p class="field-note">公式助手只读取明确选区/);
  assert.doesNotMatch(html, /<p class="field-note">选择包含表头的数据范围/);
  assert.match(html, /aria-label="查看公式助手说明"/);
  assert.match(html, /aria-label="查看智能填写说明"/);
});

test("all hosts share compact action and contextual-help control dimensions", () => {
  Object.keys(HOSTS).forEach((host) => {
    const css = source(host, "taskpane.css");
    assert.match(css, /\.result-actions\s+\.ghost-action[\s\S]*?min-height:\s*32px/);
    assert.match(css, /\.copy-toolbar\s+\.ghost-action[\s\S]*?min-height:\s*32px/);
    assert.match(css, /\.context-help\s*>\s*summary[\s\S]*?width:\s*28px/);
    assert.match(css, /\.settings-card-help\s*\{[\s\S]*?position:\s*absolute[\s\S]*?top:\s*16px[\s\S]*?right:\s*16px/);
    assert.match(css, /\.inline-status:empty\s*\{[\s\S]*?display:\s*none/);
  });
});

test("all hosts use a restrained system typography scale", () => {
  Object.keys(HOSTS).forEach((host) => {
    const css = source(host, "taskpane.css");
    assert.match(css, /--font-size-body:\s*13px/);
    assert.match(css, /--font-size-caption:\s*12px/);
    assert.match(css, /--font-size-section:\s*16px/);
    assert.match(css, /font-optical-sizing:\s*auto/);
  });
});

test("all host stylesheets keep every rule block closed", () => {
  Object.keys(HOSTS).forEach((host) => {
    const css = source(host, "taskpane.css");
    const openings = (css.match(/\{/g) || []).length;
    const closings = (css.match(/\}/g) || []).length;
    assert.strictEqual(closings, openings, `${host} stylesheet has an unclosed rule block`);
  });
});
