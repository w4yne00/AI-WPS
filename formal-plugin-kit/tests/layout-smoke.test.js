const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html",
  "utf8"
);

assert.ok(html.includes('id="home-view"'));
assert.ok(html.includes('id="settings-view"'));
assert.ok(html.includes('id="btn-save-api-key"'));
assert.ok(html.includes('id="provider-base-url"'));
assert.ok(html.includes('id="btn-save-provider-url"'));
assert.ok(html.includes('id="btn-probe"'));
assert.ok(html.includes('id="connection-settings-section"'));
assert.ok(html.includes('id="diagnostics-section"'));
assert.ok(html.includes('id="btn-copy-result"'));
assert.ok(html.includes('id="top-toolbox"'));
assert.ok(html.includes('id="scope-strip"'));
assert.ok(html.includes('id="task-title"'));
assert.ok(html.includes('识别范围'));
assert.ok(html.includes('id="rewrite-options"'));
assert.ok(html.includes('id="template-options"'));
assert.ok(html.includes('id="btn-run-primary"'));
assert.ok(html.indexOf('id="btn-copy-result"') < html.indexOf('结果预览'));
assert.ok(!html.includes('hero-copy'));
assert.ok(!html.includes('comparison-view'));
assert.ok(!html.includes('original-output'));
assert.ok(!html.includes('rewritten-output'));
assert.ok(!html.includes('id="result-mode-chip"'));
assert.ok(!html.includes('panel-eyebrow">输出'));
assert.ok(!html.includes('配置已刷新。'));
assert.ok(!html.includes('<h3>连接设置</h3>'));
assert.ok(!html.includes('<h3>诊断</h3>'));
assert.ok(!html.includes('id="btn-close-settings"'));
assert.ok(!html.includes('低频配置'));
assert.ok(!html.includes('认证</p>'));
assert.ok(!html.includes('运行时</p>'));

const js = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js",
  "utf8"
);

assert.ok(js.includes("startScopeWatcher"));
assert.ok(js.includes("setInterval(updateScopeIndicator"));
assert.ok(js.includes("switchMode"));
assert.ok(js.includes("getInitialMode"));
assert.ok(js.includes("saveProviderBaseUrl"));

const css = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css",
  "utf8"
);

assert.ok(css.includes("--surface"));
assert.ok(css.includes("--hairline"));
assert.ok(css.includes(".action-bar"));
assert.ok(css.includes(".glass-card"));
assert.ok(css.includes(".copy-button"));
assert.ok(css.includes("linear-gradient(180deg, #fafafa"));

const ribbon = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml",
  "utf8"
);

[
  "智能改写",
  "智能续写",
  "格式校对",
  "智能排版",
  "设置"
].forEach((label) => {
  assert.ok(ribbon.includes(`label="${label}"`), `missing ribbon label ${label}`);
});

const ribbonJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js",
  "utf8"
);

assert.ok(ribbonJs.includes("closeCurrentTaskPane"));
assert.ok(ribbonJs.includes("WpsAiAssistantTaskPane"));

console.log("layout smoke tests passed");
