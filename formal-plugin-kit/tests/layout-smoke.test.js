const assert = require("assert");
const fs = require("fs");

const html = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html",
  "utf8"
);
const manifest = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json",
  "utf8"
);
assert.ok(manifest.includes('"version": "0.12.2-alpha"'));

assert.ok(html.includes('id="home-view"'));
assert.ok(html.includes('id="settings-view"'));
assert.ok(html.includes('id="provider-base-url"'));
assert.ok(html.includes('id="btn-save-provider-url"'));
assert.ok(html.includes('id="provider-summary-card"'));
assert.ok(html.includes('id="provider-edit-view"'));
assert.ok(html.includes('id="btn-edit-provider"'));
assert.ok(html.includes('id="btn-back-provider-summary"'));
assert.ok(html.includes('id="provider-summary-url"'));
assert.ok(html.includes('id="provider-name"'));
assert.ok(html.includes('id="provider-auth-line"'));
assert.ok(!html.includes('密钥：未检测'));
assert.ok(html.indexOf('id="provider-summary-card"') < html.indexOf('id="provider-edit-view"'));
assert.ok(!html.includes('id="provider-active-select"'));
assert.ok(!html.includes('id="btn-set-active-provider"'));
assert.ok(html.includes('id="provider-api-key"'));
assert.ok(html.includes('id="btn-save-api-key"'));
assert.ok(html.includes('id="btn-clear-api-key"'));
assert.ok(!html.includes('id="task-routes-list"'));
assert.ok(!html.includes('id="btn-probe"'));
assert.ok(html.includes('id="connection-settings-section"'));
assert.ok(html.includes('id="diagnostics-section"'));
assert.ok(html.includes('id="frontend-version-line"'));
assert.ok(html.includes('./taskpane.css?v=0.12.2-alpha'));
assert.ok(html.includes('./taskpane-helpers.js?v=0.12.2-alpha'));
assert.ok(html.includes('./taskpane.js?v=0.12.2-alpha'));
assert.ok(html.includes('id="btn-copy-result"'));
assert.ok(html.includes('id="top-toolbox"'));
assert.ok(html.includes('id="scope-strip"'));
assert.ok(html.includes('id="task-title"'));
assert.ok(html.includes('识别范围'));
assert.ok(html.includes('智能编写'));
assert.ok(html.includes('id="write-action"'));
assert.ok(html.includes('id="rewrite-options"'));
assert.ok(html.includes('id="template-options"'));
assert.ok(html.includes('id="technical-review-options"'));
assert.ok(html.includes('id="technical-document-type"'));
assert.ok(html.includes('id="technical-review-prompt"'));
assert.ok(html.includes('id="btn-run-primary"'));
assert.ok(html.indexOf('id="btn-copy-result"') < html.indexOf('结果预览'));
assert.ok(html.includes('class="markdown-output"'));
assert.ok(!html.includes('<pre id="result-output"'));
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
assert.ok(!html.includes('连接设置'));

const js = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js",
  "utf8"
);

assert.ok(js.includes("startScopeWatcher"));
assert.ok(js.includes("setInterval(updateScopeIndicator"));
assert.ok(js.includes("switchMode"));
assert.ok(js.includes("getInitialMode"));
assert.ok(js.includes("technicalReview"));
assert.ok(js.includes("/word/technical-review"));
assert.ok(js.includes("DEFAULT_TECHNICAL_REVIEW_PROMPT"));
assert.ok(js.includes("saveProviderBaseUrl"));
assert.ok(js.includes("/word/smart-write"));
assert.ok(js.includes("setAdapterUnavailableState"));
assert.ok(js.includes("describeFetchError"));
assert.ok(js.includes("readAdapterJson"));
assert.ok(js.includes("renderMarkdown"));
assert.ok(js.includes("插件无法访问 http://127.0.0.1:18100"));
assert.ok(js.includes("当前适配服务版本较旧"));
assert.ok(js.includes("showProviderEditor"));
assert.ok(js.includes("renderFallbackTemplateOptions"));
assert.ok(js.includes("setProviderAuthLine"));
assert.ok(js.includes("providerAuthSource"));
assert.ok(js.includes('FRONTEND_BUILD_VERSION = "0.12.2-alpha"'));
assert.ok(js.includes('byId("frontend-version-line").textContent = FRONTEND_BUILD_VERSION'));
assert.ok(!js.includes("renderTaskRoutes"));
assert.ok(js.includes("/provider/task-api-key"));
assert.ok(js.includes("word.smart_format"));
assert.ok(js.includes("全文扫描段落"));
assert.ok(js.includes("AI 识别段落"));
assert.ok(js.includes("本地兜底段落"));
assert.ok(js.includes("以下仅显示需要调整的格式项"));
assert.ok(!js.includes("请输入大模型 API URL 后再保存"));
assert.ok(!js.includes("renderProviderOptions"));
assert.ok(!js.includes("setActiveProvider"));
assert.ok(js.includes("本地适配服务暂不可用"));
assert.ok(!js.includes('setHealthBadge("badge-error", "不可达")'));
assert.ok(!js.includes("无法连接本地适配层"));
assert.ok(!js.includes("runProbe"));
assert.ok(!js.includes("/word/rewrite"));

const css = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css",
  "utf8"
);

assert.ok(css.includes("--surface"));
assert.ok(css.includes("--hairline"));
assert.ok(css.includes(".action-bar"));
assert.ok(css.includes(".glass-card"));
assert.ok(css.includes(".copy-button"));
assert.ok(css.includes(".markdown-output"));
assert.ok(css.includes(".markdown-table-wrap"));
assert.ok(css.includes("linear-gradient(180deg, #fafafa"));
assert.ok(css.includes("--accent: #386ea8;"));
assert.ok(css.includes("--accent-press: #2c5a8b;"));
assert.ok(css.includes("rgba(56, 110, 168"));
assert.ok(!css.includes("#174f43"));
assert.ok(!css.includes("#1e6a59"));
assert.ok(!css.includes("#0f3b32"));
assert.ok(!css.includes("rgba(23, 79, 67"));

const ribbon = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml",
  "utf8"
);

[
  "智能编写",
  "格式校对",
  "智能排版",
  "技术文档审查",
  "设置"
].forEach((label) => {
  assert.ok(ribbon.includes(`label="${label}"`), `missing ribbon label ${label}`);
});

assert.ok(ribbon.includes('getImage="GetImage"'));
assert.ok(!ribbon.includes('image="assets/'));

const ribbonJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js",
  "utf8"
);

assert.ok(ribbonJs.includes("closeCurrentTaskPane"));
assert.ok(ribbonJs.includes("WpsAiAssistantTaskPane"));
assert.ok(ribbonJs.includes("function GetImage"));
assert.ok(ribbonJs.includes("ribbonIconMap"));
assert.ok(ribbonJs.includes("return ribbonIconMap[controlId]"));
assert.ok(ribbonJs.includes("icon-smart-write.png"));
assert.ok(ribbonJs.includes("icon-review.png"));
assert.ok(ribbonJs.includes('build=0.12.2-alpha'));
assert.ok(!ribbonJs.includes("baseUrl + iconPath"));

const uvicornStart = fs.readFileSync(
  "adapter-start-kit/scripts/start_uvicorn_adapter.sh",
  "utf8"
);

assert.ok(uvicornStart.includes("existing_adapter_detected"));
assert.ok(uvicornStart.includes("replace_existing_adapter"));
assert.ok(uvicornStart.includes("mode=uvicorn"));

const healthCheck = fs.readFileSync(
  "adapter-start-kit/scripts/check_health.sh",
  "utf8"
);

assert.ok(healthCheck.includes("adapter_mode=uvicorn"));
assert.ok(healthCheck.includes("adapter_mode=standalone"));

const fastapiHealth = fs.readFileSync("adapter_service/app/api/health.py", "utf8");
assert.ok(fastapiHealth.includes('"mode": "uvicorn"'));

console.log("layout smoke tests passed");
