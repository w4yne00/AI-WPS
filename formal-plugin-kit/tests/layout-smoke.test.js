const assert = require("assert");
const fs = require("fs");

function relativeLuminance(hex) {
  const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((value) => (
    value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
  ));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(first, second) {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

const html = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html",
  "utf8"
);
const manifest = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json",
  "utf8"
);
const helperJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js",
  "utf8"
);
const excelHtml = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html",
  "utf8"
);
const excelJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js",
  "utf8"
);
const excelCss = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css",
  "utf8"
);
const excelRibbon = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml",
  "utf8"
);
const excelRibbonJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js",
  "utf8"
);
const excelManifest = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json",
  "utf8"
);
const excelManifestXml = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.xml",
  "utf8"
);
const pptRoot = "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0";
const pptHtml = fs.readFileSync(`${pptRoot}/taskpane.html`, "utf8");
const pptJs = fs.readFileSync(`${pptRoot}/taskpane.js`, "utf8");
const pptCss = fs.readFileSync(`${pptRoot}/taskpane.css`, "utf8");
const pptRibbon = fs.readFileSync(`${pptRoot}/ribbon.xml`, "utf8");
const pptRibbonJs = fs.readFileSync(`${pptRoot}/ribbon.js`, "utf8");
const pptManifest = fs.readFileSync(`${pptRoot}/manifest.json`, "utf8");
const pptManifestXml = fs.readFileSync(`${pptRoot}/manifest.xml`, "utf8");
assert.ok(manifest.includes('"version": "0.19.0-alpha"'));
assert.ok(excelManifest.includes('"name": "wps-ai-assistant-et"'));
assert.ok(excelManifest.includes('"version": "0.19.0-alpha"'));
assert.ok(excelManifestXml.includes("<wps:AppId>wps-ai-assistant-et</wps:AppId>"));
assert.ok(excelManifestXml.includes("<wps:Ribbon>ribbon.xml</wps:Ribbon>"));
assert.ok(excelRibbon.includes('label="WPS AI 助理"'));
assert.ok(excelRibbon.includes('label="表格分析"'));
assert.ok(excelRibbon.includes('id="btnAiExcelAnalysis"'));
assert.ok(excelRibbon.includes('label="智能分析"'));
assert.ok(!excelRibbon.includes('label="Excel 智能分析"'));
assert.ok(excelRibbon.includes('id="btnAiSettings"'));
assert.ok(excelRibbon.includes('label="设置"'));
assert.ok(!excelRibbon.includes('label="智能编写"'));
assert.ok(!excelRibbon.includes('label="智能仿写"'));
assert.ok(!excelRibbon.includes('label="文档审查"'));
assert.ok(!excelRibbon.includes('label="格式审查"'));
assert.ok(excelRibbonJs.includes('btnAiExcelAnalysis: "excelAnalysis"'));
assert.ok(excelRibbonJs.includes('btnAiSettings: "settings"'));
assert.ok(excelRibbonJs.includes('btnAiExcelAnalysis: "assets/icon-excel-analysis.png"'));
assert.ok(excelRibbonJs.includes('build=0.19.0-alpha'));
assert.ok(fs.existsSync("formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png"));
assert.ok(pptManifest.includes('"name": "wps-ai-assistant-wpp"'));
assert.ok(pptManifest.includes('"version": "0.19.0-alpha"'));
assert.ok(pptManifestXml.includes("<wps:AppId>wps-ai-assistant-wpp</wps:AppId>"));
assert.ok(pptManifestXml.includes("<wps:Ribbon>ribbon.xml</wps:Ribbon>"));
assert.ok(pptRibbon.includes('label="WPS AI 助理"'));
assert.ok(pptRibbon.includes('label="演示内容"'));
assert.ok(pptRibbon.includes('label="智能总结"'));
assert.ok(!pptRibbon.includes('label="PPT 单页助手"'));
assert.ok(pptRibbon.includes('label="设置"'));
assert.ok(!pptRibbon.includes("智能编写"));
assert.ok(!pptRibbon.includes("智能仿写"));
assert.ok(!pptRibbon.includes("文档审查"));
assert.ok(!pptRibbon.includes("格式审查"));
assert.ok(!pptRibbon.includes("Excel 智能分析"));
assert.ok(pptRibbonJs.includes('btnAiPptSlideAssistant: "pptSlideAssistant"'));
assert.ok(pptRibbonJs.includes('btnAiSettings: "settings"'));
assert.ok(pptRibbonJs.includes('btnAiPptSlideAssistant: "assets/icon-ppt-slide-assistant.png"'));
assert.ok(pptRibbonJs.includes("build=0.19.0-alpha"));
assert.ok(fs.existsSync(`${pptRoot}/assets/icon-ppt-slide-assistant.png`));
[
  'id="task-title">智能总结',
  'id="health-indicator"',
  'id="btn-open-settings"',
  'id="workflow-profile-select"',
  'id="ppt-source-slide"',
  'id="ppt-source-document"',
  'id="slide-summary-controls"',
  'id="document-summary-controls"',
  'id="ppt-document-file"',
  'accept=".md,.docx"',
  'id="ppt-slide-count"',
  'id="ppt-slide-summary"',
  'id="ppt-slide-instruction"',
  'id="btn-run-primary"',
  'id="btn-result-preview"',
  'id="btn-result-plain"',
  'id="btn-copy-title"',
  'id="btn-copy-bullets"',
  'id="btn-copy-conclusion"',
  'id="btn-copy-result"',
  'id="workflow-switch-feedback"',
  'id="workflow-settings-home"',
  'id="workflow-editor-view"',
  'id="workflow-profile-manager"'
].forEach(token => assert.ok(pptHtml.includes(token), token));
assert.ok(!pptHtml.includes('id="btn-activate-workflow-profile"'));
assert.ok(!pptHtml.includes('id="provider-name"'));
assert.ok(!pptHtml.includes('id="provider-api-key"'));
assert.ok(!pptHtml.includes('id="btn-save-api-key"'));
assert.ok(!pptHtml.includes('id="btn-clear-api-key"'));
assert.ok(pptHtml.includes("WPS AI 助理 - 智能总结"));
assert.ok(!pptHtml.includes("PPT 单页助手"));
assert.ok(!pptHtml.includes("build-badge"));
[5, 8, 10, 12, 15].forEach(count => {
  assert.ok(pptHtml.includes(`<option value="${count}"`), `PPT page count ${count}`);
});
assert.ok(pptHtml.includes('<option value="10" selected>10</option>'));
assert.ok(pptHtml.includes('title="打开设置"'));
assert.ok(pptHtml.includes('aria-label="打开设置"'));
assert.ok(pptHtml.includes('title="复制完整方案"'));
assert.ok(pptHtml.includes('aria-label="复制完整方案"'));
assert.ok(pptJs.includes("/ppt/document-files"));
assert.ok(pptJs.includes("/ppt/slide-assistant/jobs"));
assert.ok(pptJs.includes("ppt.slide_assistant"));
assert.ok(pptJs.includes('{ taskType: "ppt.slide_assistant", label: "智能总结" }'));
assert.ok(!pptJs.includes("PPT 单页助手"));
assert.ok(pptJs.includes("FileReader"));
assert.ok(pptJs.includes("readAsDataURL"));
assert.ok(pptJs.includes("sourceMode"));
assert.ok(pptJs.includes("fileToken"));
assert.ok(pptJs.includes("requestedSlideCount"));
assert.ok(pptJs.includes("userInstruction"));
assert.ok(pptJs.includes("clientJobId"));
assert.ok(pptJs.includes("PPT_SLIDE_POLL_REQUEST_TIMEOUT_MS = 10000"));
assert.ok(pptJs.includes("PPT_SLIDE_POLL_MAX_ERRORS = 240"));
assert.ok(pptJs.includes("PPT_SLIDE_POLL_MAX_WAIT_MS = 60 * 60 * 1000"));
assert.ok(pptJs.includes("ai-wps-ppt-slide-assistant-active-job-v1"));
assert.ok(pptJs.includes('stage: "uploaded"'));
assert.ok(pptJs.includes('active.stage === "uploaded"'));
assert.ok(pptJs.includes("state.jobSourceMode"));
assert.ok(pptJs.includes('state.busy = isDisabled'));
assert.ok(pptJs.includes('"ppt-source-slide"'));
assert.ok(pptJs.includes('"ppt-document-file"'));
assert.ok(pptJs.includes('(statusMessage || "总结失败") + "：" + failureMessage'));
assert.ok(pptJs.includes('"btn-open-settings"'));
assert.ok(!pptJs.includes("button.disabled = false"));
[
  "Slides.Add",
  "Shapes.Add",
  ".Shapes.Add",
  ".Slides.Add",
  ".Text =",
  ".TextRange.Text",
  ".Delete()",
  ".Apply",
  "TextRange.Text =",
  "writeSlide",
  "applySlide",
  "insertSlide"
].forEach(token => assert.ok(!pptJs.includes(token), token));
assert.ok(!/id="[^"]*apply[^"]*"/i.test(pptHtml));
assert.ok(pptJs.includes("extractPresentationSlide"));
assert.ok(!pptJs.includes("Slides.Add"));
assert.ok(!pptJs.includes("Shapes.Add"));
assert.ok(!pptJs.includes("TextRange.Text ="));

assert.ok(html.includes('id="home-view"'));
assert.ok(html.includes('id="settings-view"'));
assert.ok(html.includes('id="provider-base-url"'));
assert.ok(html.includes('id="btn-save-provider-url"'));
assert.ok(html.includes('id="provider-summary-url"'));
assert.ok(!html.includes('id="provider-name"'));
assert.ok(!html.includes('id="provider-auth-line"'));
assert.ok(!html.includes('id="provider-active-select"'));
assert.ok(!html.includes('id="btn-set-active-provider"'));
assert.ok(!html.includes('id="provider-api-key"'));
assert.ok(!html.includes('id="btn-save-api-key"'));
assert.ok(!html.includes('id="btn-clear-api-key"'));
assert.ok(!html.includes('id="task-routes-list"'));
assert.ok(!html.includes('id="btn-probe"'));
assert.ok(html.includes('id="connection-settings-section"'));
assert.ok(html.includes('id="diagnostics-section"'));
assert.ok(html.includes('id="last-task-diagnostics-card"'));
assert.ok(html.includes('id="btn-refresh-diagnostics"'));
assert.ok(html.includes('id="btn-copy-diagnostics"'));
assert.ok(html.includes('id="last-task-diagnostics-output"'));
assert.ok(html.includes('最近一次任务诊断'));
assert.ok(html.includes('id="frontend-version-line"'));
assert.ok(html.includes('./taskpane.css?v=0.19.0-alpha'));
assert.ok(html.includes('./taskpane-helpers.js?v=0.19.0-alpha'));
assert.ok(html.includes('./taskpane.js?v=0.19.0-alpha'));
assert.ok(html.includes('id="btn-copy-result"'));
assert.ok(html.includes('id="result-view-switch"'));
assert.ok(html.includes('id="btn-result-preview"'));
assert.ok(html.includes('id="btn-result-compare"'));
assert.ok(html.includes('id="btn-result-plain"'));
assert.ok(html.includes('id="review-record-actions"'));
assert.ok(html.includes('id="btn-copy-review-record"'));
assert.ok(html.includes('id="btn-preview-review-record"'));
assert.ok(html.includes('id="top-toolbox"'));
assert.ok(html.includes('id="btn-open-settings"'));
assert.ok(html.includes('class="icon-button"'));
assert.ok(html.includes('class="settings-icon"'));
assert.ok(html.includes('class="back-icon"'));
assert.ok(html.includes('title="打开设置"'));
assert.ok(html.includes('aria-label="打开设置"'));
assert.ok(html.includes('id="scope-strip"'));
assert.ok(html.includes('id="workflow-profile-strip"'));
assert.ok(html.includes('id="workflow-profile-select"'));
assert.ok(!html.includes('id="btn-activate-workflow-profile"'));
assert.ok(html.includes('id="workflow-profile-current"'));
assert.ok(html.includes('id="workflow-task-tabs"'));
assert.ok(html.includes('id="workflow-settings-home"'));
assert.ok(html.includes('id="workflow-profile-manager"'));
assert.ok(html.includes('id="task-title"'));
assert.ok(html.includes('识别范围'));
assert.ok(html.includes('智能编写'));
assert.ok(html.includes('id="write-action"'));
assert.ok(html.includes('id="rewrite-options"'));
assert.ok(html.includes('<option value="standard">技术方案正式</option>'));
assert.ok(html.includes('<option value="structured">条理化说明</option>'));
assert.ok(html.includes('<option value="reporting">汇报材料风格</option>'));
assert.ok(html.includes('<option value="complete">保持信息完整</option>'));
assert.ok(html.includes('<option value="conclusion_risk">结论与风险</option>'));
assert.ok(html.includes('<option value="plan_next">措施与计划</option>'));
assert.ok(html.includes('<option value="acceptance">验收与闭环</option>'));
assert.ok(html.includes('<option value="same">保持篇幅</option>'));
assert.ok(html.indexOf('<option value="same">保持篇幅</option>') < html.indexOf('<option value="concise">精简</option>'));
assert.ok(!html.includes("默认正式"));
assert.ok(!html.includes("更正式"));
assert.ok(!html.includes("更有条理"));
assert.ok(!html.includes("更像汇报材料"));
assert.ok(!html.includes("突出下一步"));
assert.ok(!html.includes("突出实施路径"));
assert.ok(!html.includes('<option value="default">默认</option>'));
assert.ok(html.includes('id="rewrite-summary-card"'));
assert.ok(html.includes('id="rewrite-summary-text"'));
assert.ok(html.includes('id="rewrite-style-detail"'));
assert.ok(html.includes('id="rewrite-focus-detail"'));
assert.ok(html.includes('id="rewrite-length-detail"'));
assert.ok(html.includes('id="rewrite-output-detail"'));
assert.ok(html.includes('id="template-options"'));
assert.ok(html.includes('id="document-review-options"'));
assert.ok(html.includes('id="fixed-template-options"'));
assert.ok(html.includes('id="smart-imitation-options"'));
assert.ok(html.includes('id="imitation-template-text"'));
assert.ok(html.includes('id="imitation-requirement"'));
assert.ok(html.includes('id="imitation-reference-material"'));
assert.ok(html.includes("仿写模板"));
assert.ok(html.includes("仿写需求"));
assert.ok(html.includes("参考素材"));
assert.ok(html.includes('id="technical-document-type"'));
assert.ok(html.includes('id="technical-review-prompt"'));
assert.ok(html.includes('技术文件格式及书写要求'));
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
assert.ok(js.includes('lastTaskMode: "smartWrite"'));
assert.ok(js.includes('byId("btn-open-settings").addEventListener("click"'));
assert.ok(js.includes("function toggleSettingsShortcut()"));
assert.ok(js.includes("toggleSettingsShortcut();"));
assert.ok(js.includes('setHealthBadge("badge-ok", "已连接")'));
assert.ok(js.includes('classList.toggle("is-back", settingsMode)'));
assert.ok(js.includes('settingsMode ? "返回" + returnTitle : "打开设置"'));
assert.ok(!js.includes('setHealthBadge("badge-ok", health.data.status)'));
const settingsShortcutStart = js.indexOf("function toggleSettingsShortcut()");
const settingsShortcutEnd = js.indexOf("\n  function ", settingsShortcutStart + 1);
const settingsShortcutSource = js.slice(settingsShortcutStart, settingsShortcutEnd);
assert.ok(settingsShortcutStart >= 0);
assert.ok(settingsShortcutSource.includes('switchView("settings")'));
assert.ok(settingsShortcutSource.includes('switchView("home")'));
assert.ok(!settingsShortcutSource.includes("resetSmartWritePreviewState"));
assert.ok(!settingsShortcutSource.includes("resetDocumentReviewState"));
assert.ok(!settingsShortcutSource.includes("setApplyEnabled"));
assert.ok(js.includes("documentReview"));
assert.ok(js.includes("formatReview"));
assert.ok(js.includes("/word/document-review"));
assert.ok(js.includes("/word/document-review/jobs"));
assert.ok(js.includes("pollDocumentReviewJob"));
assert.ok(js.includes("DOCUMENT_REVIEW_POLL_MAX_ERRORS = 240"));
assert.ok(js.includes("DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS = 15000"));
assert.ok(js.includes("DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS = 30000"));
assert.ok(js.includes("DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS = 10000"));
assert.ok(js.includes("DOCUMENT_REVIEW_POLL_MAX_WAIT_MS = 60 * 60 * 1000"));
assert.ok(js.includes("DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY"));
assert.ok(js.includes("buildDocumentReviewClientJobId"));
assert.ok(js.includes("saveDocumentReviewActiveJob"));
assert.ok(js.includes("loadDocumentReviewActiveJob"));
assert.ok(js.includes("resumeDocumentReviewActiveJob"));
assert.ok(js.includes("clearDocumentReviewActiveJob"));
assert.ok(js.includes("clientJobId"));
assert.ok(js.includes("documentReviewPollErrorCount"));
assert.ok(js.includes("文档审查状态查询暂时失败"));
assert.ok(js.includes("状态查询暂时未连上本地 adapter"));
assert.ok(js.includes("这不代表模型后台任务失败"));
assert.ok(js.includes("文档审查任务连接中断，正在尝试恢复状态查询"));
assert.ok(js.includes("DOCUMENT_REVIEW_EXTRACTION_OPTIONS"));
assert.ok(js.includes('setPlainResult("正在读取文档审查范围，请稍候。")'));
assert.ok(js.includes("startDocumentReviewWaitFeedback"));
assert.ok(js.includes("extractDocument(scope.selectionMode, null, DOCUMENT_REVIEW_EXTRACTION_OPTIONS)"));
assert.ok(js.includes("/word/format-review"));
assert.ok(js.includes("renderGroupedDocumentReview"));
assert.ok(js.includes("renderGroupedFormatReview"));
assert.ok(js.includes("renderProviderDiagnostics"));
assert.ok(js.includes("refreshDiagnostics"));
assert.ok(js.includes("copyDiagnostics"));
assert.ok(js.includes("/provider/debug-last"));
assert.ok(js.includes("/provider/route-diagnostics"));
assert.ok(js.includes("/provider/task-api-keys"));
assert.ok(js.includes('diagnosticsCopyText: ""'));
assert.ok(js.includes("错别字"));
assert.ok(js.includes("页面设置"));
assert.ok(js.includes("其他格式项"));
assert.ok(js.includes("DEFAULT_DOCUMENT_REVIEW_PROMPT"));
assert.ok(js.includes("saveProviderBaseUrl"));
assert.ok(js.includes("/word/smart-write"));
assert.ok(js.includes("smartImitation"));
assert.ok(js.includes("/word/smart-imitation"));
assert.ok(js.includes("runSmartImitationAction"));
assert.ok(js.includes("imitationTemplateText"));
assert.ok(js.includes("imitationRequirement"));
assert.ok(js.includes("imitationReferenceMaterial"));
assert.ok(js.includes("请先提供仿写模板。"));
assert.ok(js.includes("请填写仿写需求。"));
assert.ok(js.includes('setSmartWriteResult(body.data, "word.smart_write")'));
assert.ok(js.includes('setSmartWriteResult(body.data, "word.smart_imitation")'));
assert.ok(js.includes('state.currentMode !== "smartImitation"'));
assert.ok(js.includes("hideCompareForSmartImitation"));
assert.ok(js.includes('rewriteStyle: "standard"'));
assert.ok(js.includes('focusPoint: "complete"'));
assert.ok(js.includes('lengthMode: "same"'));
assert.ok(js.includes("技术方案常用的正式、准确、克制表达"));
assert.ok(js.includes("验收标准、问题闭环"));
assert.ok(js.includes("showPromptFragments: false"));
assert.ok(js.includes('document.body.setAttribute("data-task-mode", state.currentMode)'));
assert.ok(js.includes("setAdapterUnavailableState"));
assert.ok(js.includes("describeFetchError"));
assert.ok(js.includes("readAdapterJson"));
assert.ok(js.includes("renderMarkdown"));
assert.ok(js.includes("setPlainResult"));
assert.ok(js.includes("setSmartWriteResult"));
assert.ok(js.includes("SMART_WRITE_EXTRACTION_OPTIONS"));
assert.ok(js.includes("正在读取选中文本"));
assert.ok(js.includes("preferPlainText"));
assert.ok(js.includes("shouldUseStructuredSmartWriteResult"));
assert.ok(js.includes("buildMarkdownWritebackBlocks"));
assert.ok(js.includes("tryApplyFormattedRewrite"));
assert.ok(js.includes("结果已按原文段落形态应用。"));
assert.ok(js.includes("结果已尽量按结构化格式应用。"));
assert.ok(js.includes("插件无法访问 http://127.0.0.1:18100"));
assert.ok(js.includes("当前适配服务版本较旧"));
assert.ok(js.includes("closeProviderUrlEditor"));
assert.ok(js.includes("renderFallbackTemplateOptions"));
assert.ok(js.includes("setProviderAuthLine"));
assert.ok(js.includes("providerAuthSource"));
assert.ok(js.includes('FRONTEND_BUILD_VERSION = "0.19.0-alpha"'));
assert.ok(js.includes('byId("frontend-version-line").textContent = FRONTEND_BUILD_VERSION'));
assert.ok(!js.includes("renderTaskRoutes"));
assert.ok(js.includes("/provider/task-api-key"));
assert.ok(js.includes("/provider/workflow-profiles"));
assert.ok(js.includes('method: "PATCH"'));
assert.ok(js.includes('method: "DELETE"'));
assert.ok(js.includes("/activate"));
assert.ok(js.includes("word.document_review"));
assert.ok(js.includes("renderDocumentReviewResult"));
assert.ok(js.includes("documentReviewRecordPreviewVisible"));
assert.ok(js.includes("toggleDocumentReviewRecordPreview"));
assert.ok(js.includes("返回审查结果"));
assert.ok(js.includes("renderDocumentReviewResult(state.documentReviewData)"));
assert.ok(js.includes("provider_timeout"));
assert.ok(js.includes("word.format_review"));
assert.ok(js.includes("FORMAT_REVIEW_EXTRACTION_OPTIONS"));
assert.ok(js.includes("maxPlainTextLength: 12000"));
assert.ok(js.includes("maxParagraphs: 80"));
assert.ok(js.includes("preferSelectionTextParagraphs: true"));
assert.ok(js.includes("collectParagraphsFromSelectionSources"));
assert.ok(js.includes("avoidFullTextRead: true"));
assert.ok(js.includes("avoidFallbackTextRead: true"));
assert.ok(js.includes("正在读取格式审查范围"));
assert.ok(js.includes("扫描段落"));
assert.ok(js.includes("AI 识别段落"));
assert.ok(helperJs.includes("buildHighlightedSmartWriteResult"));
assert.ok(helperJs.includes("smart-diff-highlight"));
assert.ok(helperJs.includes("collectParagraphsFromSelectionSources"));
assert.ok(helperJs.includes("normalizeAlignmentValue"));
assert.ok(js.includes("本地兜底段落"));
assert.ok(js.includes("以下仅显示需要调整的格式项"));
assert.ok(js.includes("未读取到正文段落，未调用模型后台"));
const taskpaneFrontendText = html + js + helperJs;
assert.ok(taskpaneFrontendText.includes("模型后台"));
[
  "Dify 后台",
  "Dify 正在",
  "等待 Dify",
  "未调用 Dify",
  "Dify 未返回",
  "Dify 请求失败",
  "Dify 原始回复",
  "Dify 已返回",
  "Dify 文档审查",
  "统一 Dify Chat API Key"
].forEach(function (phrase) {
  assert.ok(!taskpaneFrontendText.includes(phrase), phrase);
});
assert.ok(js.includes("resolveSelectionScope(false)"));
assert.ok(!js.includes("请输入大模型 API URL 后再保存"));
assert.ok(!js.includes("renderProviderOptions"));
assert.ok(!js.includes("setActiveProvider"));
assert.ok(js.includes("本地适配服务暂不可用"));
assert.ok(js.includes("fluency: \"通畅性\""));
assert.ok(!js.includes('setHealthBadge("badge-error", "不可达")'));
assert.ok(!js.includes("无法连接本地适配层"));
assert.ok(!js.includes("runProbe"));

assert.ok(excelHtml.includes("智能分析"));
assert.ok(!excelHtml.includes("Excel 智能分析"));
assert.ok(excelHtml.includes('id="btn-open-settings"'));
assert.ok(excelHtml.includes('class="icon-button"'));
assert.ok(excelHtml.includes('class="settings-icon"'));
assert.ok(excelHtml.includes('class="back-icon"'));
assert.ok(excelHtml.includes('title="打开设置"'));
assert.ok(excelHtml.includes('id="excel-analysis-options"'));
assert.ok(excelHtml.includes('id="workflow-profile-strip"'));
assert.ok(excelHtml.includes('id="workflow-profile-select"'));
assert.ok(!excelHtml.includes('id="btn-activate-workflow-profile"'));
assert.ok(excelHtml.includes('id="workflow-switch-feedback"'));
assert.ok(excelHtml.includes('id="workflow-settings-home"'));
assert.ok(excelHtml.includes('id="workflow-editor-view"'));
assert.ok(!excelHtml.includes('id="provider-api-key"'));
assert.ok(!excelHtml.includes('id="provider-name"'));
assert.ok(excelHtml.includes('id="workflow-profile-manager"'));
assert.ok(excelHtml.includes('id="excel-analysis-requirement"'));
assert.ok(excelHtml.includes('id="excel-range-summary"'));
assert.ok(excelHtml.includes('id="btn-run-primary"'));
assert.ok(excelHtml.includes('id="btn-copy-result"'));
assert.ok(!excelHtml.includes('id="write-action"'));
assert.ok(!excelHtml.includes('id="btn-apply"'));
assert.ok(!excelHtml.includes("文档审查"));
assert.ok(!excelHtml.includes("格式审查"));

assert.ok(excelJs.includes("excelAnalysis"));
assert.ok(excelJs.includes('byId("btn-open-settings").addEventListener("click"'));
assert.ok(excelJs.includes('state.currentMode === "settings" ? "excelAnalysis" : "settings"'));
assert.ok(excelJs.includes('setHealthBadge("badge-ok", "已连接")'));
assert.ok(excelJs.includes('classList.toggle("is-back", settingsMode)'));
assert.ok(!excelJs.includes('setHealthBadge("badge-ok", healthData.status || "就绪")'));
assert.ok(excelJs.includes("/provider/workflow-profiles"));
assert.ok(excelJs.includes('taskType: "excel.analysis"'));
assert.ok(excelJs.includes("/excel/analysis"));
assert.ok(excelJs.includes("/excel/analysis/jobs"));
assert.ok(excelJs.includes("pollExcelAnalysisJob"));
assert.ok(excelJs.includes("EXCEL_ANALYSIS_POLL_MAX_ERRORS = 240"));
assert.ok(excelJs.includes("EXCEL_ANALYSIS_POLL_ERROR_RETRY_DELAY_MS = 15000"));
assert.ok(excelJs.includes("EXCEL_ANALYSIS_POLL_SLOW_RETRY_DELAY_MS = 30000"));
assert.ok(excelJs.includes("EXCEL_ANALYSIS_POLL_REQUEST_TIMEOUT_MS = 10000"));
assert.ok(excelJs.includes("EXCEL_ANALYSIS_POLL_MAX_WAIT_MS = 60 * 60 * 1000"));
assert.ok(excelJs.includes("clientJobId"));
assert.ok(excelJs.includes("智能分析状态查询暂时失败"));
assert.ok(excelJs.includes("这不代表模型后台任务失败"));
assert.ok(excelJs.includes("runExcelAnalysisAction"));
assert.ok(excelJs.includes("extractExcelRange"));
assert.ok(excelJs.includes("analysisRequirement"));
assert.ok(excelJs.includes("structuredReport"));
assert.ok(excelJs.includes("plainText"));
assert.ok(excelJs.includes('{ taskType: "excel.analysis", label: "智能分析" }'));
assert.ok(!excelJs.includes("Excel 智能分析"));
assert.ok(!excelJs.includes("applyRewrite"));
assert.ok(!excelJs.includes("tryApplyFormattedRewrite"));
assert.ok(!excelJs.includes("/word/document-review"));

assert.ok(excelCss.includes("excel-range-summary"));
assert.ok(!js.includes("/word/rewrite"));
assert.ok(!js.includes("/word/proofread"));
assert.ok(!js.includes("/word/technical-review"));
assert.ok(!js.includes("/word/format-preview"));
assert.ok(!js.includes('state.pendingApplyAction = "imitation"'));
assert.ok(!js.includes("applySmartImitation"));

const css = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css",
  "utf8"
);

for (const hostCss of [css, excelCss, pptCss]) {
  assert.ok(hostCss.includes("--color-surface: #ffffff"));
  assert.ok(hostCss.includes("--color-success: #2f7d5c"));
  assert.ok(hostCss.includes("--color-warning: #a56a13"));
  assert.ok(hostCss.includes("--color-danger: #a44242"));
  assert.ok(hostCss.includes("--radius-control: 6px"));
  assert.ok(hostCss.includes("--radius-panel: 8px"));
  assert.ok(hostCss.includes("--control-height: 36px"));
  assert.ok(!/radial-gradient|linear-gradient/.test(hostCss));
  assert.ok(hostCss.includes("overflow-x: hidden"));
  assert.ok(hostCss.includes("overflow-wrap: anywhere"));
  assert.ok(hostCss.includes("min-width: 0"));
  assert.ok(hostCss.includes("@media (max-width: 720px)"));
  assert.ok(hostCss.includes(".settings-shell {\n  border: 0;\n  background: transparent;"));
  assert.ok(hostCss.includes("button.ghost-action:hover"));
  const radii = Array.from(hostCss.matchAll(/border-radius:\s*(\d+)px/g), (match) => Number(match[1]));
  assert.ok(radii.length > 0);
  assert.ok(radii.every((radius) => radius <= 8));
}
assert.ok(css.includes("--color-primary: #2f6db3"));
assert.ok(css.includes("--color-primary-hover: #265c98"));
assert.ok(css.includes("--color-bg: #f4f7fb"));
assert.ok(css.includes("--color-surface-muted: #eaf2fb"));
assert.ok(css.includes("rgba(47, 109, 179"));
assert.ok(!css.includes("rgba(57, 120, 148"));
assert.ok(css.includes("border-top: 3px solid var(--color-primary)"));
assert.ok(css.includes(".icon-button"));
assert.ok(css.includes(".icon-button.is-back .settings-icon"));
assert.ok(css.includes(".icon-button.is-back .back-icon"));
assert.ok(!css.includes("#btn-run-primary::before"));
assert.ok(excelCss.includes("--color-primary: #237a4b"));
assert.ok(excelCss.includes("--color-primary-hover: #1b643d"));
assert.ok(excelCss.includes("--color-bg: #f4f8f5"));
assert.ok(excelCss.includes("--color-surface-muted: #eaf6ef"));
assert.ok(excelCss.includes("rgba(35, 122, 75"));
assert.ok(!excelCss.includes("rgba(57, 120, 148"));
assert.ok(excelCss.includes("border-top: 3px solid var(--color-primary)"));
assert.ok(excelCss.includes(".icon-button.is-back .settings-icon"));
assert.ok(excelCss.includes(".icon-button.is-back .back-icon"));
assert.ok(!excelCss.includes("#btn-run-primary::before"));
assert.ok(!excelCss.includes("rgba(0, 122, 255"));
assert.ok(!excelCss.includes("#0066cc"));
assert.ok(!excelCss.includes("rgba(42, 111, 151"));
assert.ok(!excelCss.includes("#24556f"));
assert.ok(!excelCss.includes("#e3ebef"));
assert.ok(!excelCss.includes("rgba(238, 244, 251"));
assert.ok(!excelCss.includes("#2f4660"));
assert.ok(pptCss.includes("--color-host: #d36b2c"));
assert.ok(pptCss.includes("--color-primary: #b95720"));
assert.ok(pptCss.includes("--color-primary-hover: #99461a"));
assert.ok(pptCss.includes("--color-action: #b95720"));
assert.ok(pptCss.includes("--color-action-hover: #99461a"));
assert.ok(pptCss.includes("--color-bg: #fbf6f3"));
assert.ok(pptCss.includes("--color-surface-muted: #fff1e7"));
assert.ok(pptCss.includes("rgba(211, 107, 44, 0.42)"));
assert.ok(!pptCss.includes("rgba(57, 120, 148"));
assert.ok(pptCss.includes("border-top: 3px solid var(--color-host)"));
assert.ok(!pptCss.includes("#btn-run-primary::before"));
assert.ok(!pptCss.includes('background: url("./assets/icon-ppt-slide-assistant.png")'));
assert.ok(!pptCss.includes("#f4f9fb"));
assert.ok(!pptCss.includes("#eaf3f7"));
assert.ok(!pptCss.includes("#bdccd3"));
assert.ok(contrastRatio("#2f6db3", "#ffffff") >= 4.5);
assert.ok(contrastRatio("#237a4b", "#ffffff") >= 4.5);
assert.ok(contrastRatio("#b95720", "#ffffff") >= 4.5);
assert.ok(css.includes("--surface"));
assert.ok(css.includes("--hairline"));
assert.ok(css.includes(".action-bar"));
assert.ok(css.includes(".glass-card"));
assert.ok(css.includes(".copy-button"));
assert.ok(css.includes(".markdown-output"));
assert.ok(css.includes(".smart-diff-highlight"));
assert.ok(css.includes("#result-output.plain-output"));
assert.ok(css.includes(".markdown-table-wrap"));
assert.ok(css.includes("[hidden]"));
assert.ok(css.includes("body[data-task-mode=\"smartWrite\"] #result-output"));
assert.ok(css.includes("#rewrite-summary-card"));
assert.ok(css.includes("#rewrite-summary-card p"));
assert.ok(css.includes("repeat(4, minmax(0, 1fr))"));
assert.ok(css.includes("--accent: var(--color-primary);"));
assert.ok(css.includes("--accent-press: var(--color-primary-hover);"));
assert.ok(css.includes("rgba(47, 109, 179"));
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
  "智能仿写",
  "文档审查",
  "格式审查",
  "设置"
].forEach((label) => {
  assert.ok(ribbon.includes(`label="${label}"`), `missing ribbon label ${label}`);
});
assert.ok(ribbon.includes('id="btnAiSmartImitation"'));
assert.ok(ribbon.includes('label="智能仿写"'));
assert.ok(!ribbon.includes('label="格式校对"'));
assert.ok(!ribbon.includes('label="智能排版"'));
assert.ok(!ribbon.includes('label="技术文档审查"'));
assert.ok(!ribbon.includes('label="Excel 智能分析"'));
assert.ok(!ribbon.includes('id="btnAiExcelAnalysis"'));

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
assert.ok(ribbonJs.includes('btnAiSmartImitation: "smartImitation"'));
assert.ok(ribbonJs.includes('btnAiSmartImitation: "assets/icon-smart-imitation.png"'));
assert.ok(ribbonJs.includes("icon-smart-write.png"));
assert.ok(ribbonJs.includes("icon-smart-imitation.png"));
assert.ok(ribbonJs.includes("icon-review.png"));
assert.ok(ribbonJs.includes('build=0.19.0-alpha'));
assert.ok(!ribbonJs.includes("baseUrl + iconPath"));
assert.ok(fs.existsSync("formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png"));
assert.ok(js.includes('{ taskType: "word.smart_imitation", label: "智能仿写" }'));

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
