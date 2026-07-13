(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.17.0-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var DOCUMENT_REVIEW_POLL_INTERVAL_MS = 3000;
  var DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS = 10000;
  var DOCUMENT_REVIEW_POLL_MAX_ERRORS = 240;
  var DOCUMENT_REVIEW_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY = "ai-wps-document-review-active-job-v1";
  var FORMAT_REVIEW_EXTRACTION_OPTIONS = {
    maxParagraphs: 80,
    maxParagraphTextLength: 800,
    maxPlainTextLength: 12000,
    preferSelectionTextParagraphs: true,
    avoidFullTextRead: true,
    avoidFallbackTextRead: true
  };
  var DOCUMENT_REVIEW_EXTRACTION_OPTIONS = {
    maxParagraphs: 80,
    maxParagraphTextLength: 800,
    maxPlainTextLength: 12000,
    preferSelectionTextParagraphs: true,
    avoidFullTextRead: true,
    avoidFallbackTextRead: true
  };
  var SMART_WRITE_EXTRACTION_OPTIONS = {
    maxParagraphs: 20,
    maxParagraphTextLength: 2000,
    maxPlainTextLength: 12000,
    preferSelectionTextParagraphs: true,
    avoidFullTextRead: true,
    avoidFallbackTextRead: true
  };
  var DOCUMENT_REVIEW_PROMPTS = {
    technical_solution: [
      "请从以下维度审查技术方案内容：",
      "1. 功能描述准确性：检查功能边界、输入输出、前置条件、异常流程、权限和依赖是否描述清楚，避免夸大或遗漏关键约束。",
      "2. 术语专业性：检查技术术语、产品名称、接口名称、模块名称是否准确、一致，避免口语化和同一概念多种叫法。",
      "3. 设计合理性：检查方案是否说明架构边界、模块职责、数据流、容错机制、安全性、可扩展性和部署约束。",
      "4. 要求明确性：检查需求、验收标准和测试要求是否可执行、可验证、无歧义，避免“尽快、友好、高效、支持多种”等不可验收表述。",
      "请优先指出影响理解、实现、验收或交付风险的问题，并给出可直接落地的修改建议。"
    ].join("\n"),
    contract_acceptance: [
      "请从以下维度审查合同验收文档内容：",
      "1. 验收范围：检查验收对象、交付边界、版本范围、排除项和依赖条件是否明确。",
      "2. 验收证据：检查是否明确交付物清单、测试记录、签署材料、问题闭环记录和可追溯证明。",
      "3. 判定标准：检查通过/不通过标准、缺陷等级、整改时限、复验方式和例外处理是否可执行。",
      "4. 合同一致性：检查文档表述是否与合同条款、技术协议、变更单和项目范围保持一致。",
      "5. 风险闭环：检查遗留问题、限制条件、责任归属和后续计划是否清楚，避免留下验收争议。",
      "请优先指出可能影响验收签署、责任划分或后续交付的风险，并给出可落地修改建议。"
    ].join("\n"),
    test_outline: [
      "请从以下维度审查测试大纲和细则内容：",
      "1. 测试范围：检查测试对象、版本、环境、接口、模块边界和不测范围是否明确。",
      "2. 测试目标：检查测试目标是否与需求、设计、验收标准对应，是否覆盖关键业务路径和异常场景。",
      "3. 用例完整性：检查前置条件、输入数据、操作步骤、预期结果、判定准则和清理步骤是否可复现。",
      "4. 覆盖充分性：检查功能、性能、安全、兼容、异常、边界值和回归测试是否按风险分层覆盖。",
      "5. 缺陷闭环：检查缺陷记录、等级划分、复测策略、通过条件和测试报告输出是否明确。",
      "请优先指出会导致测试不可执行、不可复现、不可验收或覆盖不足的问题，并给出可落地修改建议。"
    ].join("\n")
  };
  var DEFAULT_DOCUMENT_REVIEW_PROMPT = DOCUMENT_REVIEW_PROMPTS.technical_solution;
  var REWRITE_STYLE_PROMPTS = {
    standard: "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述。",
    default: "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述。",
    formal: "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述。",
    structured: "按“背景、问题、措施、结论”组织内容，强化层级、逻辑连接和可执行表述。",
    reporting: "采用汇报材料表达，先给结论，再说明进展、问题、风险和下一步安排，语言稳健。"
  };
  var REWRITE_FOCUS_PROMPTS = {
    complete: "保留原文关键信息、事实、条件和约束，不遗漏责任、时间、对象和结论。",
    default: "保留原文关键信息、事实、条件和约束，不遗漏责任、时间、对象和结论。",
    conclusion: "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题。",
    risk: "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题。",
    conclusion_risk: "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题。",
    next_step: "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排。",
    implementation: "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排。",
    plan_next: "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排。",
    acceptance: "优先突出交付物、验收标准、问题闭环、证据材料和后续跟踪要求。"
  };
  var REWRITE_LENGTH_PROMPTS = {
    same: "保持与原文相近的篇幅，只优化措辞、结构和信息组织。",
    default: "保持与原文相近的篇幅，只优化措辞、结构和信息组织。",
    concise: "压缩冗余表达，保留关键信息和必要限定，输出更短更直接的版本。",
    expanded: "在不编造事实的前提下补足必要背景、逻辑衔接、措施说明和结论表达。"
  };
  var REWRITE_OUTPUT_PROMPT = "不要原样返回待处理内容；只输出最终正文。";
  var fallbackTemplates = [
    { id: "technical-file-format-requirements", name: "技术文件格式及书写要求" },
    { id: "general-office", name: "通用办公模板" }
  ];
  var TASK_API_KEY_DEFS = [
    { taskType: "word.smart_write", label: "智能编写" },
    { taskType: "word.smart_imitation", label: "智能仿写" },
    { taskType: "word.document_review", label: "文档审查" },
    { taskType: "word.format_review", label: "格式审查" }
  ];
  var MODE_WORKFLOW_TASK_TYPES = {
    smartWrite: "word.smart_write",
    smartImitation: "word.smart_imitation",
    documentReview: "word.document_review",
    formatReview: "word.format_review"
  };
  var modeConfig = {
    smartWrite: {
      title: "智能编写",
      styleLabel: "表达风格",
      primaryText: "生成内容",
      runningText: "正在执行智能编写...",
      doneText: "智能编写结果已生成。",
      showRewriteOptions: true,
      showInstruction: true,
      showPromptFragments: false,
      showTemplate: false
    },
    smartImitation: {
      title: "智能仿写",
      primaryText: "生成仿写内容",
      runningText: "正在执行智能仿写...",
      doneText: "智能仿写结果已生成。",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: false,
      showDocumentReviewOptions: false,
      showFixedTemplate: false,
      showSmartImitationOptions: true
    },
    documentReview: {
      title: "文档审查",
      primaryText: "开始文档审查",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: false,
      showDocumentReviewOptions: true,
      showFixedTemplate: false
    },
    formatReview: {
      title: "格式审查",
      primaryText: "开始格式审查",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: false,
      showDocumentReviewOptions: false,
      showFixedTemplate: true
    },
    settings: {
      title: "设置"
    }
  };
  var state = {
    templates: [],
    selectedTemplateId: "technical-file-format-requirements",
    writeAction: "rewrite",
    rewriteStyle: "standard",
    focusPoint: "complete",
    lengthMode: "same",
    userInstruction: "",
    technicalDocumentType: "technical_solution",
    technicalReviewPrompt: DEFAULT_DOCUMENT_REVIEW_PROMPT,
    imitationTemplateText: "",
    imitationRequirement: "",
    imitationReferenceMaterial: "",
    traceId: "",
    pendingApplyAction: "",
    rewriteResult: null,
    smartWritePreviewModel: null,
    resultViewMode: "preview",
    documentReviewData: null,
    documentReviewIssueStatus: {},
    documentReviewRecordPreviewVisible: false,
    documentReviewJobId: "",
    documentReviewPollStartedAt: 0,
    documentReviewPollErrorCount: 0,
    latestDocumentPayload: null,
    latestSelectionMode: "document",
    providerName: "未检测",
    providerBaseUrl: "",
    providerAuthSource: "none",
    taskApiKeys: {},
    workflowProfiles: {},
    workflowProfileSelections: {},
    workflowProfileMutationBusy: false,
    currentMode: "smartWrite",
    copyText: "",
    diagnosticsCopyText: "",
    scopeWatcher: null
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setStatus(message) {
    byId("status-line").textContent = message;
  }

  function isTaskpanePage() {
    return Boolean(byId(TASKPANE_ROOT_ID));
  }

  function getInitialMode() {
    var match = /[?&]mode=([^&]+)/.exec(window.location.search || "");
    var mode = match ? decodeURIComponent(match[1]) : "smartWrite";
    if (mode === "rewrite" || mode === "continue") {
      return "smartWrite";
    }
    return modeConfig[mode] ? mode : "smartWrite";
  }

  function setTrace(traceId) {
    state.traceId = traceId || "";
    byId("trace-line").textContent = traceId || "未检测";
  }

  function buildDocumentReviewClientJobId() {
    return [
      "client-doc-review",
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 10)
    ].join("-");
  }

  function loadDocumentReviewActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveDocumentReviewActiveJob(job) {
    if (!job || !job.jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY, JSON.stringify({
          jobId: job.jobId,
          traceId: job.traceId || "",
          startedAt: job.startedAt || Date.now(),
          frontendVersion: FRONTEND_BUILD_VERSION
        }));
      }
    } catch (error) {
      // localStorage may be unavailable in some WPS WebView modes; polling still works in memory.
    }
  }

  function clearDocumentReviewActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      if (jobId) {
        active = loadDocumentReviewActiveJob();
        if (active && active.jobId && active.jobId !== jobId) {
          return;
        }
      }
      window.localStorage.removeItem(DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Ignore storage cleanup failures; they should not block task-pane rendering.
    }
  }

  function setProviderLine(providerName, configured) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "模型接口",
      "enterprise-dify-workflow": "模型工作流",
      mock: "模拟接口"
    };
    var detail = providerText[providerName] || providerName || "未检测";
    if (typeof configured === "boolean") {
      detail += configured ? " / 已配置" : " / 未配置";
    }
    state.providerName = detail;
    byId("provider-line").textContent = "接口：" + detail;
    byId("settings-provider-line").textContent = "接口：" + detail;
    byId("provider-summary-type").textContent = detail;
  }

  function setProviderName(name) {
    state.providerName = name || "未检测";
    byId("provider-summary-name").textContent = state.providerName;
    byId("provider-name").value = state.providerName === "未检测" ? "" : state.providerName;
  }

  function setProviderBaseUrl(baseUrl) {
    state.providerBaseUrl = baseUrl || "";
    byId("provider-summary-url").textContent = state.providerBaseUrl || "未配置大模型 API URL";
    byId("provider-base-url").value = state.providerBaseUrl;
  }

  function setProviderAuthLine(authSource) {
    state.providerAuthSource = authSource || "none";
    var text = state.providerAuthSource === "none" ? "统一密钥：未配置" : "统一密钥：已配置";
    byId("provider-auth-line").textContent = text;
  }

  function applyProviderConfig(configData) {
    setProviderName(configData.providerName || "企业大模型接口");
    setProviderBaseUrl(configData.providerBaseUrl || "");
    setProviderAuthLine(configData.providerAuthSource || "none");
    state.taskApiKeys = configData.taskApiKeys || {};
    renderWorkflowProfileManager();
    renderWorkflowProfileStrip();
  }

  function showProviderEditor(show) {
    byId("provider-edit-view").hidden = !show;
    byId("provider-summary-card").classList.toggle("editing", !!show);
  }

  function setAdapterUnavailableState(error) {
    var message = error && error.message ? error.message : "端口未监听";
    setHealthBadge("badge-warn", "待启动");
    setTrace("");
    setProviderLine("mock", false);
    setProviderName("本地 mock");
    setStatus("本地适配服务暂不可用。");
    setResult([
      "本地适配服务暂不可用，插件无法访问 http://127.0.0.1:18100。",
      "请确认已执行 adapter 一键启动脚本，并用健康检查确认 /health 可访问。",
      "这不是大模型接口故障；adapter 启动后，未配置企业密钥时会继续使用 mock 模型。",
      "后台返回：" + message
    ].join("\n"));
  }

  function setScopeLine(label) {
    var text = label || "识别范围：未检测";
    text = text.replace(/^当前范围：/, "").replace(/^识别范围：/, "");
    byId("scope-line").textContent = text;
    byId("settings-scope-line").textContent = text;
  }

  function setHealthBadge(mode, text) {
    var node = byId("health-indicator");
    node.className = "badge " + mode;
    node.textContent = text;
  }

  function setResult(text, copyText) {
    var output = byId("result-output");
    output.hidden = false;
    output.classList.remove("plain-output");
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(text);
    } else {
      output.textContent = text;
    }
    state.copyText = typeof copyText === "string" ? copyText : (text || "");
  }

  function setPlainResult(text, copyText) {
    var output = byId("result-output");
    output.hidden = false;
    output.classList.add("plain-output");
    output.textContent = text || "";
    state.copyText = typeof copyText === "string" ? copyText : (text || "");
  }

  function setRewriteResult(result) {
    setPlainResult(result.rewrittenText || "");
  }

  function setResultViewSwitchVisible(visible) {
    var node = byId("result-view-switch");
    if (node) {
      node.hidden = !visible;
    }
  }

  function updateResultViewButtons() {
    [
      { id: "btn-result-preview", mode: "preview" },
      { id: "btn-result-compare", mode: "compare" },
      { id: "btn-result-plain", mode: "plain" }
    ].forEach(function (item) {
      var button = byId(item.id);
      var active = state.resultViewMode === item.mode;
      if (button) {
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      }
    });
  }

  function resetSmartWritePreviewState() {
    state.smartWritePreviewModel = null;
    state.resultViewMode = "preview";
    setResultViewSwitchVisible(false);
    updateResultViewButtons();
  }

  function hideCompareForSmartImitation() {
    var compareButton = byId("btn-result-compare");
    if (!compareButton) {
      return;
    }
    if (state.currentMode !== "smartImitation") {
      compareButton.hidden = false;
      return;
    }
    compareButton.hidden = true;
    if (state.resultViewMode === "compare") {
      setResultViewMode("preview");
    }
  }

  function setReviewRecordActionsVisible(visible) {
    var node = byId("review-record-actions");
    var previewButton = byId("btn-preview-review-record");
    if (node) {
      node.hidden = !visible;
    }
    if (previewButton) {
      previewButton.textContent = state.documentReviewRecordPreviewVisible ? "返回审查结果" : "预览审查记录";
    }
  }

  function resetDocumentReviewState() {
    state.documentReviewData = null;
    state.documentReviewIssueStatus = {};
    state.documentReviewRecordPreviewVisible = false;
    state.documentReviewJobId = "";
    state.documentReviewPollStartedAt = 0;
    state.documentReviewPollErrorCount = 0;
    setReviewRecordActionsVisible(false);
  }

  function renderSmartWritePreviewMode() {
    var model = state.smartWritePreviewModel || {};
    var copyText = state.rewriteResult && state.rewriteResult.rewrittenText
      ? state.rewriteResult.rewrittenText
      : (model.plainText || "");

    updateResultViewButtons();
    if (state.resultViewMode === "plain") {
      setPlainResult(model.plainText || "", copyText);
      return;
    }
    if (state.resultViewMode === "compare") {
      setResult(model.comparisonMarkdown || model.previewMarkdown || "", copyText);
      return;
    }
    if (model.hasStructuredResult) {
      setResult(model.previewMarkdown || "", copyText);
      return;
    }
    setPlainResult(model.previewMarkdown || "", copyText);
  }

  function setResultViewMode(mode) {
    if (!state.smartWritePreviewModel) {
      return;
    }
    state.resultViewMode = state.currentMode === "smartImitation" && mode === "compare" ? "preview" : mode;
    renderSmartWritePreviewMode();
  }

  function getLatestOriginalText() {
    return state.latestDocumentPayload &&
      state.latestDocumentPayload.content &&
      state.latestDocumentPayload.content.plainText
      ? state.latestDocumentPayload.content.plainText
      : "";
  }

  function shouldUseStructuredSmartWriteResult(text) {
    if (helpers.shouldUseStructuredSmartWriteResult) {
      return helpers.shouldUseStructuredSmartWriteResult(getLatestOriginalText(), text);
    }
    if (helpers.hasStructuredSmartWriteContent) {
      return helpers.hasStructuredSmartWriteContent(getLatestOriginalText()) ||
        helpers.hasStructuredSmartWriteContent(text);
    }
    return false;
  }

  function normalizeSmartWriteResult(result) {
    var source = result || {};
    var normalized = {};
    var key;
    var text = source && source.rewrittenText ? source.rewrittenText : "";
    var formattedText = helpers.formatSmartWriteResult
      ? helpers.formatSmartWriteResult(getLatestOriginalText(), text)
      : text;

    for (key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) {
        normalized[key] = source[key];
      }
    }
    normalized.rewrittenText = formattedText;
    return normalized;
  }

  function setSmartWriteResult(result) {
    var normalized = normalizeSmartWriteResult(result);
    var text = normalized.rewrittenText || "";
    var previewSource = {};
    var key;
    for (key in normalized) {
      if (Object.prototype.hasOwnProperty.call(normalized, key)) {
        previewSource[key] = normalized[key];
      }
    }
    previewSource.originalText = previewSource.originalText || getLatestOriginalText();
    state.smartWritePreviewModel = helpers.buildSmartWritePreviewModel
      ? helpers.buildSmartWritePreviewModel(previewSource)
      : {
        previewMarkdown: text,
        plainText: text,
        comparisonMarkdown: text,
        hasOriginal: Boolean(previewSource.originalText),
        hasStructuredResult: shouldUseStructuredSmartWriteResult(text)
      };
    state.resultViewMode = "preview";
    setResultViewSwitchVisible(Boolean(text));
    renderSmartWritePreviewMode();
    return normalized;
  }

  function setApplyEnabled(enabled) {
    byId("btn-apply").disabled = !enabled;
  }

  function getRewritePromptFragments() {
    return {
      style: REWRITE_STYLE_PROMPTS[state.rewriteStyle] || REWRITE_STYLE_PROMPTS.standard,
      focus: REWRITE_FOCUS_PROMPTS[state.focusPoint] || REWRITE_FOCUS_PROMPTS.complete,
      length: REWRITE_LENGTH_PROMPTS[state.lengthMode] || REWRITE_LENGTH_PROMPTS.same
    };
  }

  function getSelectedOptionText(selectId) {
    var select = byId(selectId);
    if (!select || !select.options || select.selectedIndex < 0) {
      return "";
    }
    return select.options[select.selectedIndex].text || "";
  }

  function updateRewritePromptPreview() {
    var fragments = getRewritePromptFragments();
    var config = modeConfig[state.currentMode] || modeConfig.smartWrite;
    var shouldShowPromptFragments = state.currentMode === "smartWrite" && config.showPromptFragments;
    byId("rewrite-prompt-label").textContent = "编写要求";
    byId("prompt-fragment-card").hidden = !shouldShowPromptFragments;
    byId("rewrite-summary-text").textContent = [
      getSelectedOptionText("rewrite-style") || "技术方案正式",
      getSelectedOptionText("focus-point") || "保持信息完整",
      getSelectedOptionText("length-mode") || "保持篇幅"
    ].join(" / ");
    byId("rewrite-style-detail").textContent = fragments.style;
    byId("rewrite-focus-detail").textContent = fragments.focus;
    byId("rewrite-length-detail").textContent = fragments.length;
    byId("rewrite-output-detail").textContent = REWRITE_OUTPUT_PROMPT;
    byId("selected-style-prompt").textContent = fragments.style;
    byId("selected-focus-prompt").textContent = fragments.focus;
    byId("selected-length-prompt").textContent = fragments.length;
    byId("selected-output-prompt").textContent = REWRITE_OUTPUT_PROMPT;
  }

  function switchView(viewName) {
    byId("home-view").classList.toggle("active", viewName === "home");
    byId("settings-view").classList.toggle("active", viewName === "settings");
  }

  function switchMode(mode) {
    var config = modeConfig[mode] || modeConfig.smartWrite;
    state.currentMode = modeConfig[mode] ? mode : "smartWrite";
    document.body.setAttribute("data-task-mode", state.currentMode);
    byId("task-title").textContent = config.title;
    resetSmartWritePreviewState();
    resetDocumentReviewState();

    if (state.currentMode === "settings") {
      switchView("settings");
      renderWorkflowProfileManager();
      return;
    }

    switchView("home");
    renderWorkflowProfileStrip();
    loadWorkflowProfiles(getCurrentWorkflowTaskType());
    byId("rewrite-options").hidden = !config.showRewriteOptions;
    byId("instruction-block").hidden = !config.showInstruction;
    byId("template-options").hidden = !config.showTemplate;
    byId("document-review-options").hidden = !config.showDocumentReviewOptions;
    byId("fixed-template-options").hidden = !config.showFixedTemplate;
    byId("smart-imitation-options").hidden = !config.showSmartImitationOptions;
    byId("style-field-label").textContent = config.styleLabel || "表达风格";
    byId("btn-run-primary").textContent = config.primaryText;
    byId("btn-apply").hidden = state.currentMode !== "smartWrite";
    hideCompareForSmartImitation();
    updateRewritePromptPreview();
    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("等待操作。");
    if (state.currentMode === "smartImitation") {
      fillSmartImitationTemplateFromSelection();
    }
    if (state.currentMode === "documentReview") {
      resumeDocumentReviewActiveJob();
    }
  }

  function getHostApplication() {
    return window.Application || window.wps || {};
  }

  function callNoArgs(fn, thisArg) {
    if (typeof fn !== "function") {
      return null;
    }
    try {
      return fn.call(thisArg);
    } catch (error) {
      return null;
    }
  }

  function getActiveDocument() {
    var app = getHostApplication();
    var document = app.ActiveDocument || app.activeDocument || null;
    if (typeof document === "function") {
      document = callNoArgs(document, app);
    }
    return document || null;
  }

  function getDocumentName(document) {
    if (helpers.toSafeString) {
      return helpers.toSafeString(document && (document.Name || document.name), "unnamed.docx") || "unnamed.docx";
    }
    return (document && (document.Name || document.name)) || "unnamed.docx";
  }

  function getSelectionSources(document) {
    var app = getHostApplication();
    return [
      document && document.Selection,
      app && app.Selection,
      app && app.ActiveWindow && app.ActiveWindow.Selection,
      app && app.ActiveDocument && app.ActiveDocument.Selection
    ];
  }

  function getParagraphs(document) {
    if (helpers.getParagraphCollection) {
      return helpers.getParagraphCollection(document);
    }
    return (document && (document.Paragraphs || document.paragraphs)) || [];
  }

  function getSelectionText(document) {
    return helpers.getEffectiveSelectionText
      ? helpers.getEffectiveSelectionText(getSelectionSources(document))
      : "";
  }

  function fillSmartImitationTemplateFromSelection() {
    var document = getActiveDocument();
    var selectedText = "";
    if (!document || state.imitationTemplateText) {
      return;
    }
    try {
      selectedText = getSelectionText(document);
    } catch (error) {
      selectedText = "";
    }
    selectedText = String(selectedText || "").trim();
    if (selectedText) {
      state.imitationTemplateText = selectedText;
      byId("imitation-template-text").value = selectedText;
    }
  }

  function truncateText(text, maxLength) {
    var value = String(text || "");
    if (maxLength && value.length > maxLength) {
      return value.slice(0, maxLength);
    }
    return value;
  }

  function getWritableSelection(document) {
    return helpers.getWritableSelection
      ? helpers.getWritableSelection(getSelectionSources(document))
      : (document && document.Selection) || null;
  }

  function collectParagraphs(document, options) {
    if (helpers.collectParagraphs) {
      return helpers.collectParagraphs(document, options);
    }
    var paragraphs = getParagraphs(document);
    var items = [];
    var maxParagraphs = options && options.maxParagraphs ? Math.min(paragraphs.length, options.maxParagraphs) : paragraphs.length;
    for (var i = 0; i < maxParagraphs; i += 1) {
      var paragraph = paragraphs[i];
      var font = paragraph.Font || {};
      var paragraphFormat = paragraph.ParagraphFormat || {};
      items.push({
        index: i + 1,
        text: truncateText(paragraph.Text || paragraph.text || "", options && options.maxParagraphTextLength),
        styleName: paragraph.StyleNameLocal || paragraph.styleName || "Body",
        fontName: font.NameFarEast || font.Name || "",
        fontSize: font.Size || null,
        bold: Boolean(font.Bold),
        italic: Boolean(font.Italic),
        underline: font.Underline || null,
        alignment: String(paragraphFormat.Alignment || ""),
        outlineLevel: paragraphFormat.OutlineLevel || 0,
        lineSpacing: paragraphFormat.LineSpacing || paragraphFormat.lineSpacing || null,
        firstLineIndent: paragraphFormat.FirstLineIndent || paragraphFormat.firstLineIndent || null,
        spaceBefore: paragraphFormat.SpaceBefore || paragraphFormat.spaceBefore || null,
        spaceAfter: paragraphFormat.SpaceAfter || paragraphFormat.spaceAfter || null,
        leftIndent: paragraphFormat.LeftIndent || paragraphFormat.leftIndent || null,
        rightIndent: paragraphFormat.RightIndent || paragraphFormat.rightIndent || null
      });
    }
    return items;
  }

  function collectHeadings(paragraphs) {
    return paragraphs.filter(function (item) {
      return (item.outlineLevel || 0) > 0;
    }).map(function (item) {
      return {
        level: item.outlineLevel || 0,
        text: item.text || "",
        paragraphIndex: item.index
      };
    });
  }

  function collectPageSetup(document) {
    var setup = document && (document.PageSetup || document.pageSetup);
    if (!setup) {
      return {};
    }
    return {
      paperSize: setup.PaperSize || setup.paperSize || "",
      marginTop: setup.TopMargin || setup.marginTop || null,
      marginBottom: setup.BottomMargin || setup.marginBottom || null,
      marginLeft: setup.LeftMargin || setup.marginLeft || null,
      marginRight: setup.RightMargin || setup.marginRight || null
    };
  }

  function extractDocument(selectionMode, rewriteAction, extractionOptions) {
    var options = extractionOptions || {};
    var document = getActiveDocument();
    var selectionSources = [];
    if (!document) {
      throw new Error("未检测到活动文档。");
    }

    var selectedText = selectionMode === "selection" ? getSelectionText(document) : "";
    var paragraphs = [];
    var plainText = "";
    if (selectionMode === "selection") {
      selectionSources = getSelectionSources(document);
    }
    if (options.preferSelectionTextParagraphs && selectedText && helpers.collectParagraphsFromText) {
      plainText = selectedText;
      paragraphs = helpers.collectParagraphsFromSelectionSources
        ? helpers.collectParagraphsFromSelectionSources(selectionSources, selectedText, options)
        : helpers.collectParagraphsFromText(selectedText, options);
    } else {
      paragraphs = collectParagraphs(document, options);
      if (!options.avoidFullTextRead && helpers.readDocumentText) {
        plainText = helpers.readDocumentText(document);
      }
      if (!plainText) {
        plainText = paragraphs.map(function (item) { return item.text; }).join("\n");
      }
    }
    if (selectionMode === "selection") {
      plainText = selectedText || plainText;
    }
    plainText = truncateText(plainText, options.maxPlainTextLength);

    var documentName = getDocumentName(document);
    var headings = collectHeadings(paragraphs);
    var documentStructure = helpers.buildDocumentStructure
      ? helpers.buildDocumentStructure({
        documentId: documentName,
        templateId: state.selectedTemplateId,
        selectionMode: selectionMode,
        plainText: plainText,
        pageSetup: collectPageSetup(document),
        paragraphs: paragraphs,
        headings: headings
      })
      : {};

    return {
      documentId: documentName,
      scene: "word",
      selectionMode: selectionMode,
      content: {
        plainText: plainText,
        paragraphs: paragraphs,
        headings: headings,
        documentStructure: documentStructure
      },
      options: {
        templateId: state.selectedTemplateId,
        trackChanges: true,
        userInstruction: state.userInstruction,
        rewriteStyle: state.rewriteStyle,
        focusPoint: state.focusPoint,
        lengthMode: state.lengthMode,
        rewriteAction: rewriteAction || "rewrite",
        technicalDocumentType: state.technicalDocumentType,
        technicalReviewPrompt: state.technicalReviewPrompt
      }
    };
  }

  function resolveSelectionScope(requireSelection) {
    var document = getActiveDocument();
    var selectionText = getSelectionText(document);
    var resolved = helpers.resolveRewriteScope
      ? helpers.resolveRewriteScope({
        selectionText: selectionText,
        requireSelection: requireSelection
      })
      : {
        ok: !!selectionText || !requireSelection,
        selectionMode: selectionText ? "selection" : "document",
        scopeLabel: selectionText ? "识别范围：选中文本" : "识别范围：全文",
        selectedText: selectionText,
        message: "请先用鼠标选中一段文字，再执行改写或续写。"
      };

    setScopeLine(resolved.scopeLabel);
    return resolved;
  }

  function updateScopeIndicator() {
    var document = getActiveDocument();
    if (!document) {
      setScopeLine("识别范围：未检测");
      return;
    }
    resolveSelectionScope(false);
  }

  function startScopeWatcher() {
    if (state.scopeWatcher) {
      return;
    }
    updateScopeIndicator();
    state.scopeWatcher = setInterval(updateScopeIndicator, 800);
  }

  function request(path, payload, requestOptions) {
    var timeoutMs = requestOptions && requestOptions.timeoutMs;
    var requestMethod = requestOptions && requestOptions.method;
    var controller = null;
    var timeoutId = null;
    var options = {
      method: requestMethod || (payload ? "POST" : "GET")
    };

    if (payload) {
      options.headers = {
        "Content-Type": "application/json"
      };
      options.body = JSON.stringify(payload);
    }

    if (timeoutMs && typeof AbortController !== "undefined") {
      controller = new AbortController();
      options.signal = controller.signal;
      timeoutId = setTimeout(function () {
        controller.abort();
      }, timeoutMs);
    }

    return fetch(ADAPTER_BASE_URL + path, {
      method: options.method,
      headers: options.headers,
      body: options.body,
      signal: options.signal
    }).then(function (response) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      return response.json().then(function (body) {
        if (!response.ok) {
          var validation = body.data && body.data.validation;
          var adapterError = (body.errors && body.errors[0]) || {};
          var requestError;
          if (validation && validation.errors && validation.errors.length) {
            var details = validation.errors.map(function (item) {
              return [item.loc, item.type, item.message].filter(Boolean).join(" | ");
            }).join("\n");
            requestError = new Error("HTTP " + response.status + " 请求数据校验失败：\n" + details);
            requestError.adapterCode = "REQUEST_VALIDATION_FAILED";
            throw requestError;
          }
          requestError = new Error(adapterError.message || body.message || ("HTTP " + response.status));
          requestError.adapterCode = adapterError.code || "";
          throw requestError;
        }
        return body;
      });
    }, function (error) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      throw error;
    });
  }

  function describeFetchError(error) {
    var message = error && error.message ? error.message : String(error || "");
    if (message === "Failed to fetch" || message.indexOf("NetworkError") >= 0) {
      return "插件无法访问 http://127.0.0.1:18100。请确认 adapter 正在运行、端口为 18100，并重新打开任务窗格。";
    }
    return message;
  }

  function describeDocumentReviewError(error) {
    var message = describeFetchError(error);
    if (error && error.name === "AbortError") {
      return "文档审查任务提交请求超过 10 秒未返回，任务窗格将尝试按本地任务编号恢复查询。";
    }
    if (error && error.adapterCode === "PROVIDER_TIMEOUT") {
      return "模型后台文档审查未按时返回，adapter 已停止等待。请缩小审查范围后重试，或到“设置-最近一次任务诊断”查看 trace 和 provider 状态。";
    }
    if (message.indexOf("插件无法访问 http://127.0.0.1:18100") === 0) {
      return message + "\n\n如果模型后台已经收到文档审查请求，通常说明 adapter 正在等待模型后台返回或模型后台返回过慢；请稍后在“设置-最近一次任务诊断”查看 trace 和 provider 状态。";
    }
    return message;
  }

  function describeDocumentReviewPollError(error) {
    var message = describeFetchError(error);
    if (error && error.name === "AbortError") {
      return "状态查询请求超过 10 秒未返回，将继续自动刷新。";
    }
    if (error && error.adapterCode === "PROVIDER_TIMEOUT") {
      return "模型后台文档审查仍未按时返回，adapter 可能仍在等待或已返回超时诊断。";
    }
    if (message.indexOf("插件无法访问 http://127.0.0.1:18100") === 0) {
      return "状态查询暂时未连上本地 adapter；这不代表模型后台任务失败，将继续自动刷新。";
    }
    return message;
  }

  function readAdapterJson(path) {
    return request(path).catch(function (error) {
      return {
        success: false,
        data: {},
        errors: [{ message: describeFetchError(error) }]
      };
    });
  }

  function yesNo(value) {
    return value ? "是" : "否";
  }

  function describeAuthSource(value) {
    return {
      env: "环境变量",
      file: "统一密钥文件",
      "task-file": "任务级密钥文件",
      "route-file": "任务级密钥文件",
      none: "未配置"
    }[value] || value || "未检测";
  }

  function firstErrorMessage(result) {
    if (!result || result.success !== false) {
      return "";
    }
    return result.errors && result.errors[0] && result.errors[0].message
      ? result.errors[0].message
      : "请求失败";
  }

  function renderProviderDiagnostics(debugResult, statusResult, routesResult, taskKeysResult) {
    var debug = (debugResult && debugResult.data) || {};
    var status = (statusResult && statusResult.data) || {};
    var routes = (routesResult && routesResult.data) || {};
    var taskKeys = (taskKeysResult && taskKeysResult.data) || {};
    var lines = ["最近一次任务诊断", ""];

    if (firstErrorMessage(debugResult)) {
      lines.push("- debug-last：" + firstErrorMessage(debugResult));
    }
    if (firstErrorMessage(statusResult)) {
      lines.push("- provider/status：" + firstErrorMessage(statusResult));
    }
    if (firstErrorMessage(routesResult)) {
      lines.push("- route-diagnostics：" + firstErrorMessage(routesResult));
    }
    if (firstErrorMessage(taskKeysResult)) {
      lines.push("- task-api-keys：" + firstErrorMessage(taskKeysResult));
    }

    lines.push("- 任务类型：" + (debug.taskType || "未记录"));
    lines.push("- traceId：" + (debug.traceId || "未记录"));
    lines.push("- adapter 状态：" + (status.configured ? "provider 已配置" : "provider 未配置"));
    lines.push("- provider 类型：" + (status.providerType || routes.providerType || "未检测"));
    lines.push("- provider 名称：" + (status.providerName || "未检测"));
    lines.push("- 统一 API URL 已配置：" + yesNo(routes.providerBaseUrlConfigured || debug.providerBaseUrlConfigured));
    lines.push("- 认证来源：" + describeAuthSource(debug.taskAuthSource || debug.authSource || status.authSource || routes.authSource));
    lines.push("- 请求路径：" + (debug.url || routes.url || "未进入模型后台请求"));
    lines.push("- fallback 原因：" + (debug.skipReason || "无"));

    if (debug.request) {
      lines.push("");
      lines.push("## 请求摘要");
      lines.push("- body 字段：" + (debug.request.bodyKeys || []).join(", "));
      lines.push("- inputs 字段：" + (debug.request.inputsKeys || []).join(", "));
      lines.push("- query 长度：" + (debug.request.queryLength || 0));
      lines.push("- query 预览：" + (debug.request.queryPreview || "空"));
      lines.push("- response_mode：" + (debug.request.responseMode || "未记录"));
    }

    if (debug.response) {
      lines.push("");
      lines.push("## 响应摘要");
      lines.push("- HTTP 状态：" + (debug.response.status || "未记录"));
      lines.push("- body 字段：" + (debug.response.bodyKeys || []).join(", "));
      lines.push("- answer 长度：" + (debug.response.answerLength || 0));
      if (debug.response.answerFormat) {
        lines.push("- Markdown 特征：" + yesNo(debug.response.answerFormat.containsMarkdown));
      }
    }

    if (debug.error) {
      lines.push("");
      lines.push("## 错误摘要");
      lines.push("- 类型：" + (debug.error.type || "未记录"));
      lines.push("- 状态：" + (debug.error.status || "未记录"));
      lines.push("- 信息：" + (debug.error.message || "未记录"));
    }

    lines.push("");
    lines.push("## 任务密钥状态");
    Object.keys(taskKeys).forEach(function (taskType) {
      var item = taskKeys[taskType] || {};
      lines.push("- " + taskType + "：" + describeAuthSource(item.authSource) + "，已配置：" + yesNo(item.configured));
    });

    return lines.join("\n");
  }

  function mergeTemplates(serverTemplates) {
    var merged = [];
    var seen = {};

    function add(template) {
      if (!template || !template.id || seen[template.id]) {
        return;
      }
      seen[template.id] = true;
      merged.push(template);
    }

    fallbackTemplates.forEach(add);
    (serverTemplates || []).forEach(add);
    return merged;
  }

  function refreshConfig() {
    setStatus("正在刷新配置...");
    return request("/health").then(function (health) {
      return Promise.all([
        Promise.resolve(health),
        readAdapterJson("/templates"),
        readAdapterJson("/config")
      ]);
    }).then(function (results) {
      var health = results[0];
      var templates = results[1];
      var config = results[2];
      setHealthBadge("badge-ok", health.data.status);
      setTrace(health.traceId || "");
      setProviderLine(health.data.providerType || "未检测", health.data.providerConfigured);
      if (config.success === false) {
        applyProviderConfig({
          providerName: health.data.providerName || "企业大模型接口",
          providerBaseUrl: state.providerBaseUrl
        });
        setResult("当前适配服务版本较旧或缺少 /config 接口，请使用新版 adapter-start-kit 后再保存模型配置。\n后台返回：" + config.errors[0].message);
      } else {
        applyProviderConfig(config.data || {});
      }
      resolveSelectionScope(false);
      if (templates.success === false) {
        renderFallbackTemplateOptions();
      } else {
        state.templates = mergeTemplates(templates.data.templates || []);
        renderTemplateOptions();
      }
      return refreshAllWorkflowProfiles().then(function () {
        setStatus("就绪");
        refreshDiagnostics();
      });
    }).catch(function (error) {
      setAdapterUnavailableState(error);
    });
  }

  function renderFallbackTemplateOptions() {
    state.templates = mergeTemplates([]);
    renderTemplateOptions();
  }

  function saveProviderBaseUrl() {
    var input = byId("provider-base-url");
    var baseUrl = (input.value || "").trim();
    var providerName = (byId("provider-name").value || "").trim();
    setStatus("正在保存大模型 API URL...");
    request("/provider/base-url", { baseUrl: baseUrl, providerName: providerName })
      .then(function (body) {
        var savedName = body.data.providerName || providerName || "企业大模型接口";
        var savedUrl = typeof body.data.providerBaseUrl === "string" ? body.data.providerBaseUrl : baseUrl;
        setProviderName(savedName);
        setProviderBaseUrl(savedUrl);
        setStatus("大模型 API URL 已保存。");
        setResult([
          "模型提供商配置已保存。",
          "名称：" + savedName,
          "URL：" + (savedUrl || "未配置")
        ].join("\n"));
        return refreshConfig();
      })
      .catch(function (error) {
        setStatus("保存大模型 API URL 失败：" + describeFetchError(error));
        setResult(describeFetchError(error));
      });
  }

  function saveProviderApiKey() {
    var input = byId("provider-api-key");
    var apiKey = (input.value || "").trim();
    if (!apiKey) {
      setStatus("请输入统一模型 API Key。");
      return;
    }
    request("/provider/api-key", { apiKey: apiKey })
      .then(function () {
        input.value = "";
        setProviderAuthLine("file");
        setStatus("统一密钥已保存。");
        return refreshConfig();
      })
      .catch(function (error) {
        setStatus("保存统一密钥失败：" + describeFetchError(error));
      });
  }

  function clearProviderApiKey() {
    fetch(ADAPTER_BASE_URL + "/provider/api-key", {
      method: "DELETE"
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) || body.message || ("HTTP " + response.status));
        }
        return body;
      });
    }).then(function () {
      byId("provider-api-key").value = "";
      setProviderAuthLine("none");
      setStatus("统一密钥已清除。");
      return refreshConfig();
    }).catch(function (error) {
      setStatus("清除统一密钥失败：" + describeFetchError(error));
    });
  }

  function getCurrentWorkflowTaskType() {
    return MODE_WORKFLOW_TASK_TYPES[state.currentMode] || "";
  }

  function getWorkflowProfileData(taskType) {
    return state.workflowProfiles[taskType] || {
      taskType: taskType,
      activeProfileId: "",
      profileCount: 0,
      profiles: []
    };
  }

  function normalizeWorkflowProfileData(data, taskType) {
    if (helpers.normalizeWorkflowProfileData) {
      return helpers.normalizeWorkflowProfileData(data, taskType);
    }
    return {
      taskType: taskType,
      activeProfileId: data && data.activeProfileId || "",
      profileCount: data && data.profileCount || 0,
      profiles: data && Array.isArray(data.profiles) ? data.profiles : []
    };
  }

  function loadWorkflowProfiles(taskType) {
    if (!taskType) {
      return Promise.resolve(null);
    }
    return request("/provider/workflow-profiles?taskType=" + encodeURIComponent(taskType))
      .then(function (body) {
        state.workflowProfiles[taskType] = normalizeWorkflowProfileData(body.data || {}, taskType);
        state.workflowProfileSelections[taskType] = state.workflowProfiles[taskType].activeProfileId || "";
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        return state.workflowProfiles[taskType];
      })
      .catch(function (error) {
        state.workflowProfiles[taskType] = {
          taskType: taskType,
          activeProfileId: "",
          profileCount: 0,
          profiles: [],
          loadError: describeFetchError(error)
        };
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        return null;
      });
  }

  function refreshAllWorkflowProfiles() {
    return Promise.all(TASK_API_KEY_DEFS.map(function (item) {
      return loadWorkflowProfiles(item.taskType);
    }));
  }

  function renderWorkflowProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var select = byId("workflow-profile-select");
    var button = byId("btn-activate-workflow-profile");
    var current = byId("workflow-profile-current");
    var taskType = getCurrentWorkflowTaskType();
    var data;
    var selectedId;
    if (!strip || !select || !button || !current) {
      return;
    }
    strip.hidden = !taskType;
    if (!taskType) {
      return;
    }
    data = getWorkflowProfileData(taskType);
    selectedId = state.workflowProfileSelections[taskType] || data.activeProfileId || "";
    select.innerHTML = "";
    if (!data.profiles.length) {
      var emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = data.loadError ? "档案读取失败" : "尚未配置工作流";
      select.appendChild(emptyOption);
    } else {
      data.profiles.forEach(function (profile) {
        var option = document.createElement("option");
        option.value = profile.id;
        option.textContent = profile.name + (profile.keyConfigured ? "" : "（密钥未配置）");
        option.selected = profile.id === selectedId;
        select.appendChild(option);
      });
    }
    current.textContent = "当前：" + (
      helpers.getActiveWorkflowProfileName ? helpers.getActiveWorkflowProfileName(data) : "尚未配置"
    );
    button.disabled = state.workflowProfileMutationBusy || !selectedId || selectedId === data.activeProfileId;
  }

  function profileFieldSelector(field, id) {
    return '[data-profile-' + field + '="' + id + '"]';
  }

  function renderWorkflowProfileManager() {
    var manager = byId("workflow-profile-manager");
    if (!manager) {
      return;
    }
    manager.innerHTML = "";
    TASK_API_KEY_DEFS.forEach(function (definition) {
      var data = getWorkflowProfileData(definition.taskType);
      var section = document.createElement("section");
      var rows = [];
      section.className = "workflow-task-section";
      section.setAttribute("data-workflow-task", definition.taskType);
      rows.push('<div class="workflow-task-head"><div><strong>' + definition.label + '</strong><span>当前：' +
        (helpers.escapeHtml ? helpers.escapeHtml(helpers.getActiveWorkflowProfileName(data)) : "尚未配置") +
        '</span></div><span class="provider-badge">' + data.profileCount + ' 个</span></div>');
      rows.push('<div class="workflow-profile-create">');
      rows.push('<input type="text" data-create-profile-name="' + definition.taskType + '" maxlength="40" placeholder="自定义工作流名称" />');
      rows.push('<input type="password" data-create-profile-key="' + definition.taskType + '" placeholder="API Key" />');
      rows.push('<input type="text" data-create-profile-note="' + definition.taskType + '" maxlength="200" placeholder="备注（选填）" />');
      rows.push('<label class="workflow-activate-check"><input type="checkbox" data-create-profile-activate="' + definition.taskType + '" /> 保存后设为当前</label>');
      rows.push('<button type="button" data-workflow-action="create" data-task-type="' + definition.taskType + '">保存工作流</button>');
      rows.push('</div>');
      if (data.loadError) {
        rows.push('<p class="workflow-profile-error">无法读取工作流配置：' +
          (helpers.escapeHtml ? helpers.escapeHtml(data.loadError) : data.loadError) + '</p>');
      }
      data.profiles.forEach(function (profile) {
        var escapedId = helpers.escapeHtml ? helpers.escapeHtml(profile.id) : profile.id;
        var escapedName = helpers.escapeHtml ? helpers.escapeHtml(profile.name) : profile.name;
        var escapedNote = helpers.escapeHtml ? helpers.escapeHtml(profile.note) : profile.note;
        var isActive = profile.id === data.activeProfileId;
        rows.push('<div class="workflow-profile-row" data-profile-id="' + escapedId + '">');
        rows.push('<div class="workflow-profile-row-head"><strong>' + escapedName + '</strong><span class="provider-badge">' +
          (isActive ? "当前使用" : (profile.keyConfigured ? "可切换" : "密钥未配置")) + '</span></div>');
        rows.push('<input type="text" data-profile-name="' + escapedId + '" maxlength="40" value="' + escapedName + '" aria-label="工作流名称" />');
        rows.push('<input type="text" data-profile-note="' + escapedId + '" maxlength="200" value="' + escapedNote + '" placeholder="备注（选填）" aria-label="工作流备注" />');
        rows.push('<input type="password" data-profile-key="' + escapedId + '" placeholder="输入新 API Key 可单独替换" aria-label="新 API Key" />');
        rows.push('<div class="button-row workflow-profile-actions">');
        if (!isActive) {
          rows.push('<button type="button" data-workflow-action="activate" data-profile-id="' + escapedId + '">设为当前</button>');
        }
        rows.push('<button type="button" class="ghost-action" data-workflow-action="update" data-profile-id="' + escapedId + '">保存名称</button>');
        rows.push('<button type="button" class="ghost-action" data-workflow-action="replace-key" data-profile-id="' + escapedId + '">更换密钥</button>');
        if (!isActive) {
          rows.push('<button type="button" class="ghost-action danger-action" data-workflow-action="delete" data-profile-id="' + escapedId + '">删除</button>');
        }
        rows.push('</div></div>');
      });
      section.innerHTML = rows.join("");
      manager.appendChild(section);
    });
  }

  function completeWorkflowMutation(taskType, message) {
    state.workflowProfileMutationBusy = false;
    setStatus(message);
    return loadWorkflowProfiles(taskType);
  }

  function failWorkflowMutation(taskType, prefix, error) {
    state.workflowProfileMutationBusy = false;
    setStatus(prefix + "：" + describeFetchError(error));
    renderWorkflowProfileStrip();
    renderWorkflowProfileManager();
  }

  function createWorkflowProfile(taskType) {
    var nameInput = document.querySelector('[data-create-profile-name="' + taskType + '"]');
    var keyInput = document.querySelector('[data-create-profile-key="' + taskType + '"]');
    var noteInput = document.querySelector('[data-create-profile-note="' + taskType + '"]');
    var activateInput = document.querySelector('[data-create-profile-activate="' + taskType + '"]');
    var name = nameInput ? (nameInput.value || "").trim() : "";
    var apiKey = keyInput ? (keyInput.value || "").trim() : "";
    if (!name || !apiKey) {
      setStatus("请填写工作流名称和 API Key。");
      return;
    }
    state.workflowProfileMutationBusy = true;
    request("/provider/workflow-profiles", {
      taskType: taskType,
      name: name,
      apiKey: apiKey,
      note: noteInput ? (noteInput.value || "").trim() : "",
      activate: Boolean(activateInput && activateInput.checked)
    }).then(function () {
      if (keyInput) {
        keyInput.value = "";
      }
      return completeWorkflowMutation(taskType, "工作流配置已保存。");
    }).catch(function (error) {
      failWorkflowMutation(taskType, "保存工作流失败", error);
    });
  }

  function updateWorkflowProfile(profileId) {
    var nameInput = document.querySelector(profileFieldSelector("name", profileId));
    var noteInput = document.querySelector(profileFieldSelector("note", profileId));
    state.workflowProfileMutationBusy = true;
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId), {
      name: nameInput ? (nameInput.value || "").trim() : "",
      note: noteInput ? (noteInput.value || "").trim() : ""
    }, { method: "PATCH" }).then(function (body) {
      return completeWorkflowMutation(body.data.profile.taskType, "工作流名称和备注已保存。");
    }).catch(function (error) {
      failWorkflowMutation(getCurrentWorkflowTaskType(), "保存工作流信息失败", error);
    });
  }

  function replaceWorkflowProfileKey(profileId) {
    var keyInput = document.querySelector(profileFieldSelector("key", profileId));
    var apiKey = keyInput ? (keyInput.value || "").trim() : "";
    if (!apiKey) {
      setStatus("请输入新的 API Key。");
      return;
    }
    state.workflowProfileMutationBusy = true;
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/api-key", {
      apiKey: apiKey
    }).then(function (body) {
      if (keyInput) {
        keyInput.value = "";
      }
      return completeWorkflowMutation(body.data.profile.taskType, "工作流密钥已更新。");
    }).catch(function (error) {
      failWorkflowMutation(getCurrentWorkflowTaskType(), "更换工作流密钥失败", error);
    });
  }

  function activateWorkflowProfile(profileId, taskType) {
    if (!profileId) {
      setStatus("请选择要切换的工作流。");
      return;
    }
    state.workflowProfileMutationBusy = true;
    renderWorkflowProfileStrip();
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/activate", {})
      .then(function (body) {
        var data = normalizeWorkflowProfileData(body.data || {}, taskType || getCurrentWorkflowTaskType());
        state.workflowProfiles[data.taskType] = data;
        state.workflowProfileSelections[data.taskType] = data.activeProfileId;
        state.workflowProfileMutationBusy = false;
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        setStatus("工作流已切换，从下一次任务开始生效。");
      })
      .catch(function (error) {
        failWorkflowMutation(taskType || getCurrentWorkflowTaskType(), "切换工作流失败", error);
      });
  }

  function deleteWorkflowProfile(profileId, taskType) {
    if (window.confirm && !window.confirm("确认删除这个备用工作流配置？删除后无法恢复其密钥。")) {
      return;
    }
    state.workflowProfileMutationBusy = true;
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId), null, { method: "DELETE" })
      .then(function () {
        return completeWorkflowMutation(taskType, "备用工作流已删除。");
      })
      .catch(function (error) {
        failWorkflowMutation(taskType, "删除工作流失败", error);
      });
  }

  function handleWorkflowProfileManagerAction(event) {
    var target = event.target;
    var action = target.getAttribute("data-workflow-action");
    var taskType = target.getAttribute("data-task-type") || "";
    var profileId = target.getAttribute("data-profile-id") || "";
    var definition;
    if (!action || state.workflowProfileMutationBusy) {
      return;
    }
    if (profileId && !taskType) {
      definition = TASK_API_KEY_DEFS.filter(function (item) {
        return getWorkflowProfileData(item.taskType).profiles.some(function (profile) {
          return profile.id === profileId;
        });
      })[0];
      taskType = definition ? definition.taskType : "";
    }
    if (action === "create") {
      createWorkflowProfile(taskType);
    } else if (action === "activate") {
      activateWorkflowProfile(profileId, taskType);
    } else if (action === "update") {
      updateWorkflowProfile(profileId);
    } else if (action === "replace-key") {
      replaceWorkflowProfileKey(profileId);
    } else if (action === "delete") {
      deleteWorkflowProfile(profileId, taskType);
    }
  }

  function renderTemplateOptions() {
    var select = byId("template-select");
    select.innerHTML = "";

    if (!state.templates.length) {
      var fallback = document.createElement("option");
      fallback.value = "general-office";
      fallback.textContent = "通用办公模板";
      select.appendChild(fallback);
      state.selectedTemplateId = "general-office";
      return;
    }

    state.templates.forEach(function (template) {
      var option = document.createElement("option");
      option.value = template.id;
      option.textContent = template.name;
      if (template.id === state.selectedTemplateId) {
        option.selected = true;
      }
      select.appendChild(option);
    });
  }

  var DOCUMENT_REVIEW_CATEGORY_ORDER = ["typo", "expression", "logic", "fluency", "professional", "other"];
  var DOCUMENT_REVIEW_CATEGORY_TEXT = {
    typo: "错别字",
    expression: "语言表达",
    logic: "逻辑表达",
    fluency: "通畅性",
    professional: "专业性",
    other: "其他问题"
  };
  var REVIEW_SEVERITY_TEXT = {
    high: "高",
    medium: "中",
    low: "低"
  };
  var FORMAT_REVIEW_GROUP_ORDER = [
    "page_setup",
    "heading",
    "body_text",
    "paragraph",
    "caption_note",
    "other"
  ];
  var FORMAT_REVIEW_GROUP_TEXT = {
    page_setup: "页面设置",
    heading: "标题层级",
    body_text: "正文格式",
    paragraph: "段落格式",
    caption_note: "图表题/注释",
    other: "其他格式项"
  };

  function groupItems(items, getKey) {
    var grouped = {};
    (items || []).forEach(function (item) {
      var key = getKey(item) || "other";
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    });
    return grouped;
  }

  function getDocumentReviewCategory(issue) {
    var category = issue && issue.category ? String(issue.category) : "";
    return DOCUMENT_REVIEW_CATEGORY_TEXT[category] ? category : "other";
  }

  function getFormatReviewGroup(issue) {
    var ruleId = String((issue && issue.ruleId) || "");
    var role = String((issue && issue.role) || "");
    if (ruleId === "page_setup") {
      return "page_setup";
    }
    if (role.indexOf("heading") >= 0 || role.indexOf("title") >= 0) {
      return "heading";
    }
    if (ruleId === "style_name") {
      return "body_text";
    }
    if (ruleId === "font_name" || ruleId === "font_size") {
      return "body_text";
    }
    if (ruleId === "line_spacing" || ruleId === "alignment" || ruleId === "first_line_indent") {
      return "paragraph";
    }
    if (role.indexOf("caption") >= 0 || role.indexOf("note") >= 0 || ruleId.indexOf("caption") >= 0 || ruleId.indexOf("note") >= 0) {
      return "caption_note";
    }
    return "other";
  }

  function formatAiFallbackReason(reason) {
    var reasonText = {
      no_paragraphs: "未读取到正文段落，未调用模型后台；请确认当前文档对象能暴露正文段落或全文文本。",
      provider_not_configured: "统一 API URL 或格式审查任务 API Key 未形成可用配置，已使用本地模板规则。",
      dify_response_not_role_json: "模型后台未返回段落角色 JSON，已使用本地模板规则。",
      provider_request_failed: "模型后台请求失败，已使用本地模板规则。",
      dify_response_no_valid_roles: "模型后台返回的角色无效，已使用本地模板规则。",
      dify_returned_no_roles: "模型后台未返回有效段落角色，已使用本地模板规则。"
    };
    return reasonText[reason] || reason || "";
  }

  function renderGroupedFormatReview(data) {
    if (helpers.renderReadableFormatReview) {
      return helpers.renderReadableFormatReview(data);
    }

    var summary = data.summary || {};
    var issues = data.issues || [];
    var lines = [
      "格式审查结果",
      "",
      "模板：" + (summary.templateId || "technical-file-format-requirements"),
      "检查范围：" + (summary.scope === "selection" ? "选中内容" : "全文"),
      "发现问题：" + (summary.issueCount || issues.length || 0)
    ];
    var hasCoverageStats = typeof summary.paragraphCount !== "undefined";

    if (hasCoverageStats) {
      lines.push("扫描段落：" + summary.paragraphCount);
      lines.push(
        "AI 识别段落：" + (summary.aiClassifiedParagraphCount || 0) +
        " | 本地兜底段落：" + (summary.localFallbackParagraphCount || 0)
      );
    }
    lines.push("识别来源：" + (summary.provider || "local"));
    var aiFallbackText = formatAiFallbackReason(summary.aiFallbackReason);
    if (aiFallbackText) {
      lines.push("fallback 原因：" + aiFallbackText);
    }
    if (summary.aiInvalidRoleCount || summary.aiOutOfBatchCount) {
      lines.push(
        "AI 无效角色：" + (summary.aiInvalidRoleCount || 0) +
        " | 越界段落：" + (summary.aiOutOfBatchCount || 0)
      );
    }
    lines.push("");
    lines.push("以下仅显示需要调整的格式项，正文内容不会在检查中改写。");
    lines.push("");

    if (!issues.length) {
      lines.push("当前范围未发现明显格式问题。");
      return lines.join("\n");
    }

    var grouped = groupItems(issues, getFormatReviewGroup);
    FORMAT_REVIEW_GROUP_ORDER.forEach(function (group) {
      var groupIssues = grouped[group] || [];
      if (!groupIssues.length) {
        return;
      }
      lines.push("## " + FORMAT_REVIEW_GROUP_TEXT[group] + "（" + groupIssues.length + "）");
      lines.push("");
      groupIssues.forEach(function (issue, index) {
        lines.push("### " + FORMAT_REVIEW_GROUP_TEXT[group] + " #" + (index + 1));
        lines.push("- 段落号：" + (issue.paragraphIndex || 0));
        lines.push("- 段落角色：" + (issue.role || "未识别"));
        lines.push("- 问题说明：" + (issue.message || "格式问题"));
        lines.push("- 当前值：" + (issue.currentValue || "未读取"));
        lines.push("- 模板要求：" + (issue.expectedValue || "未给出"));
        lines.push("- 建议操作：" + (issue.suggestion || "按模板调整。"));
        lines.push("");
      });
    });

    return lines.join("\n").trim();
  }

  function renderGroupedDocumentReview(data) {
    var documentTypeText = {
      technical_solution: "技术方案",
      contract_acceptance: "合同验收文档",
      test_outline: "测试大纲和细则"
    };
    var issues = data.issues || [];
    var rawAnswer = data.rawAnswer || data.raw_answer || "";
    var parseFallbackReason = data.parseFallbackReason || data.parse_fallback_reason || "";
    var lines = [
      "文档审查结果",
      "",
      "文档类型：" + (documentTypeText[data.documentType] || data.documentType || "技术方案"),
      "检查范围：" + (data.scope === "selection" ? "选中内容" : "全文"),
      "总体结论：" + (data.summary || "审查完成。"),
      "问题数量：" + issues.length,
      ""
    ];

    if (parseFallbackReason) {
      lines.push("解析状态：" + formatDocumentReviewFallbackReason(parseFallbackReason));
      lines.push("");
    }

    if (!issues.length) {
      if (rawAnswer) {
        lines.push("未解析到结构化问题列表，以下展示模型后台原始回复。");
        lines.push("");
        lines.push("## 原始模型回复");
        lines.push("");
        lines.push(rawAnswer);
        return lines.join("\n").trim();
      }
      lines.push("未发现明显文档质量问题。");
      return lines.join("\n");
    }

    var grouped = groupItems(issues, getDocumentReviewCategory);
    DOCUMENT_REVIEW_CATEGORY_ORDER.forEach(function (category) {
      var categoryIssues = grouped[category] || [];
      if (!categoryIssues.length) {
        return;
      }
      lines.push("## " + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + "（" + categoryIssues.length + "）");
      lines.push("");
      categoryIssues.forEach(function (issue, index) {
        lines.push("### " + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + " #" + (index + 1));
        lines.push("- 严重程度：" + (REVIEW_SEVERITY_TEXT[issue.severity] || issue.severity || "中"));
        lines.push("- 位置：" + (issue.location || "未定位"));
        if (issue.originalText) {
          lines.push("- 原文片段：" + issue.originalText);
        }
        lines.push("- 问题说明：" + (issue.problem || "未说明"));
        lines.push("- 修改建议：" + (issue.suggestion || "无"));
        if (issue.suggestedRewrite) {
          lines.push("- 建议改写：" + issue.suggestedRewrite);
        }
        lines.push("");
      });
    });

    return lines.join("\n").trim();
  }

  function formatDocumentReviewFallbackReason(reason) {
    var reasonText = {
      provider_timeout: "模型后台未按时返回，adapter 已停止等待。",
      provider_unreachable: "模型后台或企业大模型接口暂不可达。",
      provider_auth_failed: "模型后台或企业大模型接口认证失败。",
      non_json_answer: "模型后台已返回内容，但不是标准 JSON 问题列表。",
      unsupported_json_shape: "模型后台已返回 JSON，但未包含标准 issues 问题列表。"
    };
    return reasonText[reason] || "模型后台已返回内容，但未解析为标准问题列表。";
  }

  function escapeHtmlText(value) {
    return helpers.escapeHtml ? helpers.escapeHtml(value) : String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function getDocumentReviewRecordText() {
    if (helpers.buildDocumentReviewRecord) {
      return helpers.buildDocumentReviewRecord(state.documentReviewData || {}, state.documentReviewIssueStatus || {});
    }
    return renderGroupedDocumentReview(state.documentReviewData || {});
  }

  function getDocumentReviewStatus(index) {
    return state.documentReviewIssueStatus[String(index)] || "pending";
  }

  function getDocumentReviewStatusText(status) {
    return {
      pending: "待处理",
      done: "已处理",
      ignored: "已忽略"
    }[status] || "待处理";
  }

  function renderDocumentReviewInteractive(data) {
    var output = byId("result-output");
    var issues = data.issues || [];
    var documentTypeText = {
      technical_solution: "技术方案",
      contract_acceptance: "合同验收文档",
      test_outline: "测试大纲和细则"
    };
    var grouped = {};
    var html = [];
    var markdown = renderGroupedDocumentReview(data);

    state.copyText = markdown;
    output.hidden = false;
    output.classList.remove("plain-output");

    if (!issues.length) {
      setResult(markdown, markdown);
      setReviewRecordActionsVisible(Boolean(state.documentReviewData));
      return;
    }

    issues.forEach(function (issue, index) {
      var category = getDocumentReviewCategory(issue);
      if (!grouped[category]) {
        grouped[category] = [];
      }
      grouped[category].push({ issue: issue, index: index });
    });

    html.push('<div class="document-review-result">');
    html.push('<section class="review-summary-box">');
    html.push("<h3>文档审查结果</h3>");
    html.push("<p>文档类型：" + escapeHtmlText(documentTypeText[data.documentType] || data.documentType || "技术方案") + "</p>");
    html.push("<p>检查范围：" + (data.scope === "selection" ? "选中内容" : "全文") + "</p>");
    html.push("<p>总体结论：" + escapeHtmlText(data.summary || "审查完成。") + "</p>");
    html.push("<p>问题数量：" + issues.length + "</p>");
    html.push("</section>");

    DOCUMENT_REVIEW_CATEGORY_ORDER.forEach(function (category) {
      var items = grouped[category] || [];
      if (!items.length) {
        return;
      }
      html.push('<section class="review-category-section">');
      html.push("<h3>" + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + "（" + items.length + "）</h3>");
      items.forEach(function (entry, localIndex) {
        var issue = entry.issue;
        var index = entry.index;
        var status = getDocumentReviewStatus(index);
        html.push('<article class="review-issue-card" data-review-issue-index="' + index + '">');
        html.push("<h4>" + DOCUMENT_REVIEW_CATEGORY_TEXT[category] + " #" + (localIndex + 1) + "</h4>");
        html.push('<div class="review-issue-meta">');
        html.push("<span>严重程度：" + escapeHtmlText(REVIEW_SEVERITY_TEXT[issue.severity] || issue.severity || "中") + "</span>");
        html.push("<span>位置：" + escapeHtmlText(issue.location || "未定位") + "</span>");
        html.push("</div>");
        if (issue.originalText) {
          html.push("<p><strong>原文片段：</strong>" + escapeHtmlText(issue.originalText) + "</p>");
        }
        html.push("<p><strong>问题说明：</strong>" + escapeHtmlText(issue.problem || "未说明") + "</p>");
        html.push("<p><strong>修改建议：</strong>" + escapeHtmlText(issue.suggestion || "无") + "</p>");
        if (issue.suggestedRewrite) {
          html.push("<p><strong>建议改写：</strong>" + escapeHtmlText(issue.suggestedRewrite) + "</p>");
        }
        html.push('<div class="review-status-row">');
        html.push('<span class="review-status-pill ' + status + '">' + getDocumentReviewStatusText(status) + "</span>");
        html.push("</div>");
        html.push('<div class="review-action-row">');
        html.push('<button type="button" class="ghost-action" data-review-action="mark-done" data-issue-index="' + index + '">标记已处理</button>');
        html.push('<button type="button" class="ghost-action" data-review-action="mark-ignored" data-issue-index="' + index + '">忽略</button>');
        html.push('<button type="button" class="ghost-action" data-review-action="copy-suggestion" data-issue-index="' + index + '">复制建议</button>');
        if (issue.suggestedRewrite) {
          html.push('<button type="button" class="ghost-action" data-review-action="copy-rewrite" data-issue-index="' + index + '">复制改写</button>');
        }
        html.push("</div>");
        html.push("</article>");
      });
      html.push("</section>");
    });

    html.push("</div>");
    output.innerHTML = html.join("");
    setReviewRecordActionsVisible(true);
  }

  function renderDocumentReviewResult(data) {
    var markdown = renderGroupedDocumentReview(data || {});
    state.documentReviewRecordPreviewVisible = false;
    try {
      renderDocumentReviewInteractive(data || {});
      return true;
    } catch (error) {
      setResult(markdown, markdown);
      setReviewRecordActionsVisible(Boolean(data));
      return false;
    }
  }

  function completeDocumentReview(data, traceId) {
    state.pendingApplyAction = "";
    setApplyEnabled(false);
    if (traceId) {
      setTrace(traceId);
    }
    state.documentReviewData = data || {};
    state.documentReviewIssueStatus = {};
    if (renderDocumentReviewResult(state.documentReviewData)) {
      setStatus("文档审查完成。");
    } else {
      setStatus("文档审查完成，已使用简洁结果视图显示。");
    }
  }

  function scheduleDocumentReviewPoll(jobId, stopWaiting, delayMs) {
    setTimeout(function () {
      pollDocumentReviewJob(jobId, stopWaiting);
    }, delayMs);
  }

  function isFatalDocumentReviewPollError(error) {
    return error && (
      error.adapterCode === "DOCUMENT_REVIEW_JOB_NOT_FOUND" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function pollDocumentReviewJob(jobId, stopWaiting) {
    if (!jobId || state.documentReviewJobId !== jobId) {
      return;
    }
    request("/word/document-review/jobs/" + encodeURIComponent(jobId), null, {
      timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
    })
      .then(function (body) {
        var job = body.data || {};
        if (state.documentReviewJobId !== jobId) {
          return;
        }
        state.documentReviewPollErrorCount = 0;
        setTrace(body.traceId || job.traceId || jobId);
        saveDocumentReviewActiveJob({
          jobId: jobId,
          traceId: body.traceId || job.traceId || "",
          startedAt: state.documentReviewPollStartedAt || Date.now()
        });
        if (job.status === "completed") {
          clearDocumentReviewActiveJob(jobId);
          state.documentReviewJobId = "";
          state.documentReviewPollStartedAt = 0;
          stopWaiting();
          completeDocumentReview(job.result || {}, body.traceId || job.traceId || jobId);
          return;
        }
        if (job.status === "failed") {
          clearDocumentReviewActiveJob(jobId);
          state.documentReviewJobId = "";
          state.documentReviewPollStartedAt = 0;
          stopWaiting();
          setStatus("文档审查失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
          setResult((job.error && job.error.message) || "后台任务执行失败。");
          return;
        }
        setStatus("文档审查仍在模型后台处理中...");
        if (job.elapsedSeconds || job.runningMessage) {
          setPlainResult([
            job.runningMessage || "模型后台正在处理文档审查。",
            "已等待：" + (job.elapsedSeconds || 0) + " 秒",
            "adapter 等待预算：" + (job.providerTimeoutSeconds || 1800) + " 秒",
            "任务编号：" + jobId
          ].join("\n"));
        }
        scheduleDocumentReviewPoll(jobId, stopWaiting, DOCUMENT_REVIEW_POLL_INTERVAL_MS);
      })
      .catch(function (error) {
        var elapsed;
        var message;
        var withinRetryBudget;
        var retryDelay;
        if (state.documentReviewJobId !== jobId) {
          return;
        }
        message = describeDocumentReviewPollError(error);
        state.documentReviewPollErrorCount = (state.documentReviewPollErrorCount || 0) + 1;
        elapsed = Date.now() - (state.documentReviewPollStartedAt || Date.now());
        if (!isFatalDocumentReviewPollError(error)) {
          withinRetryBudget = (
            state.documentReviewPollErrorCount <= DOCUMENT_REVIEW_POLL_MAX_ERRORS &&
            elapsed <= DOCUMENT_REVIEW_POLL_MAX_WAIT_MS
          );
          retryDelay = withinRetryBudget
            ? DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS
            : DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS;
          saveDocumentReviewActiveJob({
            jobId: jobId,
            traceId: state.traceId || "",
            startedAt: state.documentReviewPollStartedAt || Date.now()
          });
          setStatus(withinRetryBudget
            ? "文档审查状态查询暂时失败，正在继续等待模型后台返回..."
            : "文档审查任务连接中断，正在尝试恢复状态查询...");
          setPlainResult([
            withinRetryBudget
              ? "文档审查状态查询暂时失败，adapter 后台任务可能仍在执行，将继续自动刷新。"
              : "文档审查任务连接中断，前台不会丢弃任务编号，将继续低频自动刷新。",
            "这不代表模型后台任务失败；如果模型后台已收到请求，请保持 WPS 和 adapter 打开。",
            "已重试：" + state.documentReviewPollErrorCount + "/" + DOCUMENT_REVIEW_POLL_MAX_ERRORS,
            "任务编号：" + jobId,
            "最近错误：" + message
          ].join("\n"));
          scheduleDocumentReviewPoll(jobId, stopWaiting, retryDelay);
          return;
        }
        clearDocumentReviewActiveJob(jobId);
        state.documentReviewJobId = "";
        state.documentReviewPollStartedAt = 0;
        state.documentReviewPollErrorCount = 0;
        setStatus("文档审查状态查询持续失败，请查看最近一次任务诊断。");
        setResult([
          "文档审查状态查询持续失败，前台已暂停自动刷新。",
          "这不代表模型后台任务失败；如果模型后台已收到请求，adapter 可能仍在等待模型后台返回，或目标机网络/任务窗格连接不稳定。",
          "请到“设置-最近一次任务诊断”查看 trace、provider 状态和模型后台返回情况。",
          "最近错误：" + message
        ].join("\n"));
        stopWaiting();
      });
  }

  function resumeDocumentReviewActiveJob() {
    var active = loadDocumentReviewActiveJob();
    if (!active || !active.jobId || state.currentMode !== "documentReview") {
      return;
    }
    state.documentReviewJobId = active.jobId;
    state.documentReviewPollStartedAt = active.startedAt || Date.now();
    state.documentReviewPollErrorCount = 0;
    setApplyEnabled(false);
    setReviewRecordActionsVisible(false);
    setTrace(active.traceId || active.jobId);
    setStatus("已恢复未完成的文档审查任务，正在查询模型后台结果...");
    setPlainResult([
      "检测到未完成的文档审查任务，将继续查询 adapter 后台状态。",
      "如果模型后台仍在处理，请保持 WPS 和 adapter 打开。",
      "任务编号：" + active.jobId
    ].join("\n"));
    pollDocumentReviewJob(active.jobId, function () {});
  }

  function writeClipboardText(text, successMessage) {
    if (!String(text || "").trim()) {
      setStatus("暂无可复制的内容。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus(successMessage);
      }).catch(function () {
        setStatus("复制失败，请手动选择文本复制。");
      });
      return;
    }
    setStatus("当前环境不支持自动复制，请手动选择文本复制。");
  }

  function handleDocumentReviewAction(event) {
    var action = event.target.getAttribute("data-review-action");
    var indexText = event.target.getAttribute("data-issue-index");
    var index;
    var issue;
    if (!action) {
      return;
    }
    index = Number(indexText);
    issue = state.documentReviewData &&
      state.documentReviewData.issues &&
      state.documentReviewData.issues[index];
    if (!issue) {
      return;
    }
    if (action === "mark-done") {
      state.documentReviewIssueStatus[String(index)] = "done";
      renderDocumentReviewResult(state.documentReviewData);
      setStatus("已标记为已处理。");
      return;
    }
    if (action === "mark-ignored") {
      state.documentReviewIssueStatus[String(index)] = "ignored";
      renderDocumentReviewResult(state.documentReviewData);
      setStatus("已标记为忽略。");
      return;
    }
    if (action === "copy-suggestion") {
      writeClipboardText(issue.suggestion || "", "修改建议已复制。");
      return;
    }
    if (action === "copy-rewrite") {
      writeClipboardText(issue.suggestedRewrite || "", "建议改写已复制。");
    }
  }

  function copyDocumentReviewRecord() {
    writeClipboardText(getDocumentReviewRecordText(), "审查记录已复制。");
  }

  function toggleDocumentReviewRecordPreview() {
    var record;
    if (!state.documentReviewData) {
      setStatus("暂无可预览的审查记录。");
      return;
    }
    if (state.documentReviewRecordPreviewVisible) {
      renderDocumentReviewResult(state.documentReviewData);
      setStatus("已返回文档审查结果。");
      return;
    }
    record = getDocumentReviewRecordText();
    state.documentReviewRecordPreviewVisible = true;
    setResult(record, record);
    setReviewRecordActionsVisible(true);
    setStatus("正在预览审查记录。");
  }

  function copyResult() {
    var text = state.copyText || byId("result-output").textContent || "";
    if (!text.trim()) {
      setStatus("暂无可复制的结果。");
      return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("结果已复制。");
      }).catch(function () {
        fallbackCopy(text);
      });
      return;
    }

    fallbackCopy(text);
  }

  function setDiagnosticsResult(text) {
    var output = byId("last-task-diagnostics-output");
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(text);
    } else {
      output.textContent = text;
    }
    state.diagnosticsCopyText = text || "";
  }

  function refreshDiagnostics() {
    setDiagnosticsResult("正在刷新最近一次任务诊断...");
    return Promise.all([
      readAdapterJson("/provider/debug-last"),
      readAdapterJson("/provider/status"),
      readAdapterJson("/provider/route-diagnostics"),
      readAdapterJson("/provider/task-api-keys")
    ]).then(function (results) {
      var markdown = renderProviderDiagnostics(results[0], results[1], results[2], results[3]);
      setDiagnosticsResult(markdown);
      setStatus("诊断信息已刷新。");
    });
  }

  function copyDiagnostics() {
    var text = state.diagnosticsCopyText || byId("last-task-diagnostics-output").textContent || "";
    if (!text.trim()) {
      setStatus("暂无可复制的诊断信息。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("诊断信息已复制。");
      }).catch(function () {
        fallbackCopy(text);
      });
      return;
    }
    fallbackCopy(text);
  }

  function applyDocumentReviewPrompt(documentType) {
    var nextType = DOCUMENT_REVIEW_PROMPTS[documentType] ? documentType : "technical_solution";
    state.technicalDocumentType = nextType;
    state.technicalReviewPrompt = DOCUMENT_REVIEW_PROMPTS[nextType];
    byId("technical-review-prompt").value = state.technicalReviewPrompt;
  }

  function fallbackCopy(text) {
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      setStatus("结果已复制。");
    } catch (error) {
      setStatus("复制失败，请手动选择结果文本。");
    }
    document.body.removeChild(textarea);
  }

  function blockToWritebackLine(block) {
    if (!block) {
      return "";
    }
    if (block.type === "unorderedListItem") {
      return "• " + (block.text || "");
    }
    if (block.type === "orderedListItem") {
      return String(block.ordinal || 1) + ". " + (block.text || "");
    }
    return block.text || "";
  }

  function blockWritebackPrefixLength(block) {
    if (!block) {
      return 0;
    }
    if (block.type === "unorderedListItem") {
      return 2;
    }
    if (block.type === "orderedListItem") {
      return String(block.ordinal || 1).length + 2;
    }
    return 0;
  }

  function buildWritebackPlainText(blocks) {
    return blocks.map(blockToWritebackLine).filter(Boolean).join("\r");
  }

  function readValue(target, key) {
    try {
      return target ? target[key] : undefined;
    } catch (error) {
      return undefined;
    }
  }

  function setValue(target, key, value) {
    try {
      if (target && typeof target[key] !== "undefined") {
        target[key] = value;
        return true;
      }
    } catch (error) {
      return false;
    }
    return false;
  }

  function writeTextToTarget(target, text) {
    if (!target) {
      return false;
    }
    try {
      if (target.Range && typeof target.Range.Text !== "undefined") {
        target.Range.Text = text;
        return true;
      }
      if (typeof target.Text !== "undefined") {
        target.Text = text;
        return true;
      }
    } catch (error) {
      return false;
    }
    return false;
  }

  function getRangeFromTarget(target) {
    if (!target) {
      return null;
    }
    return readValue(target, "Range") || target;
  }

  function getRangeParagraph(range, index) {
    var paragraphs = readValue(range, "Paragraphs");
    if (!paragraphs) {
      return null;
    }
    if (helpers.getCollectionItem) {
      return helpers.getCollectionItem(paragraphs, index);
    }
    if (typeof paragraphs.Item === "function") {
      try {
        return paragraphs.Item(index);
      } catch (error) {
        return null;
      }
    }
    return paragraphs[index] || paragraphs[index - 1] || null;
  }

  function applyParagraphWritebackFormatting(range, blocks) {
    var formatted = false;
    blocks.forEach(function (block, index) {
      var paragraph = getRangeParagraph(range, index + 1);
      var paragraphRange = getRangeFromTarget(paragraph);
      var font = readValue(paragraphRange, "Font") || readValue(paragraph, "Font");
      var headingLevel = Math.min(block.level || 1, 3);
      var styleSet;

      if (block.type === "heading") {
        styleSet = setValue(paragraphRange, "Style", "标题 " + headingLevel);
        if (!styleSet) {
          styleSet = setValue(paragraphRange, "Style", "Heading " + headingLevel);
        }
        formatted = styleSet || formatted;
        formatted = setValue(font, "Bold", true) || formatted;
        formatted = setValue(font, "Size", headingLevel === 1 ? 16 : headingLevel === 2 ? 15 : 14) || formatted;
      }
    });
    return formatted;
  }

  function duplicateRange(range) {
    var duplicate = readValue(range, "Duplicate");
    if (typeof duplicate === "function") {
      return callNoArgs(duplicate, range);
    }
    return duplicate || null;
  }

  function applyBoldWritebackRuns(range, blocks) {
    var start = Number(readValue(range, "Start"));
    if (isNaN(start)) {
      return false;
    }

    var formatted = false;
    var offset = 0;
    blocks.forEach(function (block) {
      var line = blockToWritebackLine(block);
      var prefixLength = blockWritebackPrefixLength(block);
      var runOffset = prefixLength;

      (block.runs || []).forEach(function (run) {
        var runText = run.text || "";
        var runRange;
        if (run.bold && runText) {
          runRange = duplicateRange(range);
          if (runRange && typeof runRange.SetRange === "function") {
            try {
              runRange.SetRange(start + offset + runOffset, start + offset + runOffset + runText.length);
              formatted = setValue(readValue(runRange, "Font"), "Bold", true) || formatted;
            } catch (error) {
              return;
            }
          }
        }
        runOffset += runText.length;
      });

      offset += line.length + 1;
    });
    return formatted;
  }

  function tryApplyFormattedRewrite(target, text) {
    var blocks;
    var plainText;
    var range;
    if (!helpers.buildMarkdownWritebackBlocks) {
      return { ok: false, formatted: false, reason: "parser_unavailable" };
    }

    blocks = helpers.buildMarkdownWritebackBlocks(text);
    plainText = buildWritebackPlainText(blocks);
    if (!plainText) {
      return { ok: false, formatted: false, reason: "empty" };
    }
    if (!writeTextToTarget(target, plainText)) {
      return { ok: false, formatted: false, reason: "write_unavailable" };
    }

    range = getRangeFromTarget(target);
    var paragraphFormatted = applyParagraphWritebackFormatting(range, blocks);
    var boldFormatted = applyBoldWritebackRuns(range, blocks);
    return {
      ok: true,
      formatted: paragraphFormatted || boldFormatted,
      reason: "applied"
    };
  }

  function applyRewriteText(target, text, options) {
    var writeOptions = options || {};
    var formattedResult;
    var plainText;
    if (writeOptions.preferPlainText) {
      plainText = helpers.buildMarkdownWritebackBlocks
        ? buildWritebackPlainText(helpers.buildMarkdownWritebackBlocks(text))
        : text;
      if (writeTextToTarget(target, plainText || text)) {
        return { ok: true, formatted: false, reason: "plain_text_preferred" };
      }
      return { ok: false, formatted: false, reason: "plain_text_unavailable" };
    }

    formattedResult = tryApplyFormattedRewrite(target, text);
    if (formattedResult.ok) {
      return formattedResult;
    }
    if (writeTextToTarget(target, text)) {
      return { ok: true, formatted: false, reason: "plain_text_fallback" };
    }
    return formattedResult;
  }

  function applyRewrite() {
    var document = getActiveDocument();
    var applyResult = null;
    var rewrittenText;
    var preferPlainText;
    if (!document || !state.rewriteResult) {
      return;
    }
    rewrittenText = state.rewriteResult.rewrittenText || "";
    preferPlainText = !shouldUseStructuredSmartWriteResult(rewrittenText);

    if (state.latestSelectionMode === "selection") {
      var writableSelection = getWritableSelection(document);
      var selectionCheck = helpers.canApplyRewriteToSelection
        ? helpers.canApplyRewriteToSelection(state.latestDocumentPayload.content.plainText, getSelectionText(document))
        : { ok: true };
      if (!selectionCheck.ok) {
        setStatus(selectionCheck.message);
        setResult(selectionCheck.message);
        return;
      }
      if (!writableSelection) {
        setStatus("未找到可写回的选区对象。");
        setResult("当前宿主未暴露可写回的选区对象，请反馈当前 WPS 版本、操作路径和选区截图。");
        return;
      }
      applyResult = applyRewriteText(writableSelection, rewrittenText, {
        preferPlainText: preferPlainText
      });
      if (!applyResult.ok) {
        setStatus("结果写回失败，请复制结果后手动粘贴。");
        setResult("当前宿主未开放可写回的正文对象，请复制结果后手动粘贴。");
        return;
      }
    } else if (document.Content) {
      applyResult = applyRewriteText(document.Content, rewrittenText, {
        preferPlainText: preferPlainText
      });
      if (!applyResult.ok) {
        setStatus("结果写回失败，请复制结果后手动粘贴。");
        setResult("当前宿主未开放可写回的正文对象，请复制结果后手动粘贴。");
        return;
      }
    }

    if (!applyResult) {
      setStatus("结果写回失败，请复制结果后手动粘贴。");
      setResult("当前宿主未开放可写回的正文对象，请复制结果后手动粘贴。");
      return;
    }

    state.pendingApplyAction = "";
    setApplyEnabled(false);
    if (!preferPlainText) {
      setStatus(applyResult.formatted ? "结果已尽量按结构化格式应用。" : "结果已按结构化文本应用。");
    } else {
      setStatus("结果已按原文段落形态应用。");
    }
  }

  function startDocumentReviewWaitFeedback() {
    var timers = [];
    timers.push(setTimeout(function () {
      setStatus("模型后台正在处理文档审查，请继续等待...");
      setPlainResult("文档审查请求已提交，模型后台正在处理。较长文本或繁忙时可能需要更久，请保持 WPS 和 adapter 打开。");
    }, 8000));
    timers.push(setTimeout(function () {
      setStatus("文档审查仍在等待模型后台返回...");
      setPlainResult("文档审查仍在等待模型后台返回。若模型后台已完成但此处长时间未更新，请到“设置-最近一次任务诊断”查看 trace 和 provider 状态。");
    }, 30000));
    return function () {
      timers.forEach(function (timer) {
        clearTimeout(timer);
      });
    };
  }

  function runDocumentReview() {
    var scope = resolveSelectionScope(false);
    resetSmartWritePreviewState();
    resetDocumentReviewState();
    clearDocumentReviewActiveJob();
    if (!scope.ok) {
      setStatus(scope.message);
      setResult(scope.message);
      return;
    }

    setStatus("正在读取文档审查范围...");
    setPlainResult("正在读取文档审查范围，请稍候。");
    setApplyEnabled(false);

    setTimeout(function () {
      var stopWaiting;
      var clientJobId;
      var startedAt;
      try {
        state.latestDocumentPayload = extractDocument(scope.selectionMode, null, DOCUMENT_REVIEW_EXTRACTION_OPTIONS);
        state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
      } catch (error) {
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus("正在提交文档审查请求...");
      setPlainResult("文档审查请求已提交，正在等待模型后台返回。");
      stopWaiting = startDocumentReviewWaitFeedback();
      clientJobId = buildDocumentReviewClientJobId();
      startedAt = Date.now();
      state.latestDocumentPayload.clientJobId = clientJobId;
      state.documentReviewJobId = clientJobId;
      state.documentReviewPollStartedAt = startedAt;
      state.documentReviewPollErrorCount = 0;
      saveDocumentReviewActiveJob({
        jobId: clientJobId,
        traceId: "",
        startedAt: startedAt
      });
      request("/word/document-review/jobs", state.latestDocumentPayload, {
        timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
      })
        .then(function (body) {
          var job = body.data || {};
          var jobId = job.jobId || clientJobId || body.traceId;
          if (state.documentReviewJobId !== clientJobId) {
            return;
          }
          setTrace(body.traceId || job.traceId || jobId);
          if (!jobId) {
            clearDocumentReviewActiveJob(clientJobId);
            stopWaiting();
            setStatus("文档审查失败：adapter 未返回后台任务编号。");
            setResult("adapter 未返回后台任务编号，请重试或查看最近一次任务诊断。");
            return;
          }
          state.documentReviewJobId = jobId || "";
          state.documentReviewPollStartedAt = startedAt;
          state.documentReviewPollErrorCount = 0;
          saveDocumentReviewActiveJob({
            jobId: jobId,
            traceId: body.traceId || job.traceId || "",
            startedAt: startedAt
          });
          if (job.status === "completed") {
            clearDocumentReviewActiveJob(jobId);
            state.documentReviewJobId = "";
            state.documentReviewPollStartedAt = 0;
            stopWaiting();
            completeDocumentReview(job.result || {}, body.traceId || job.traceId || jobId);
            return;
          }
          setStatus("文档审查任务已提交，模型后台处理中...");
          setPlainResult("文档审查任务已提交。adapter 会在后台等待模型后台返回，此处将自动刷新结果。");
          pollDocumentReviewJob(state.documentReviewJobId, stopWaiting);
        })
        .catch(function (error) {
          var message;
          message = describeDocumentReviewError(error);
          if (state.documentReviewJobId !== clientJobId) {
            return;
          }
          if (isFatalDocumentReviewPollError(error)) {
            clearDocumentReviewActiveJob(clientJobId);
            state.documentReviewJobId = "";
            state.documentReviewPollStartedAt = 0;
            state.documentReviewPollErrorCount = 0;
            stopWaiting();
            setStatus("文档审查失败：" + message);
            setResult(message);
            return;
          }
          setStatus("文档审查提交响应未确认，正在按任务编号恢复状态查询...");
          setPlainResult([
            "文档审查任务可能已经提交到 adapter，但任务窗格没有收到确认响应。",
            "将按本地任务编号继续查询；如果 adapter 未收到请求，会返回任务不存在。",
            "任务编号：" + clientJobId,
            "最近错误：" + message
          ].join("\n"));
          pollDocumentReviewJob(clientJobId, stopWaiting);
        });
    }, 0);
  }

  function runFormatReview() {
    var scope = resolveSelectionScope(false);
    resetSmartWritePreviewState();
    if (!scope.ok) {
      setStatus(scope.message);
      setResult(scope.message);
      return;
    }

    setStatus("正在读取格式审查范围...");
    setResult("正在读取格式审查范围，请稍候。");
    setApplyEnabled(false);

    setTimeout(function () {
      try {
        state.latestDocumentPayload = extractDocument(scope.selectionMode, null, FORMAT_REVIEW_EXTRACTION_OPTIONS);
        state.latestDocumentPayload.options.templateId = "technical-file-format-requirements";
        state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
      } catch (error) {
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus("正在执行格式审查...");
      request("/word/format-review", state.latestDocumentPayload)
        .then(function (body) {
          state.pendingApplyAction = "";
          setApplyEnabled(false);
          setTrace(body.traceId);
          setResult(renderGroupedFormatReview(body.data || {}));
          setStatus("格式审查完成。");
        })
        .catch(function (error) {
          var message = describeFetchError(error);
          setStatus("格式审查失败：" + message);
          setResult(message);
        });
    }, 0);
  }

  function runSmartWriteAction() {
    var selectionScope = resolveSelectionScope(true);
    resetSmartWritePreviewState();
    if (!selectionScope.ok) {
      setStatus(selectionScope.message);
      setResult(selectionScope.message);
      return;
    }

    var config = modeConfig[state.currentMode] || modeConfig.smartWrite;
    setStatus("正在读取选中文本...");
    setPlainResult("正在读取选中文本，请稍候。");
    setApplyEnabled(false);

    setTimeout(function () {
      try {
        state.latestDocumentPayload = extractDocument(
          "selection",
          state.writeAction || "rewrite",
          SMART_WRITE_EXTRACTION_OPTIONS
        );
        state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
      } catch (error) {
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus(config.runningText);
      request("/word/smart-write", state.latestDocumentPayload)
        .then(function (body) {
          state.pendingApplyAction = "rewrite";
          state.rewriteResult = setSmartWriteResult(body.data);
          setApplyEnabled(true);
          setTrace(body.traceId);
          setStatus(config.doneText);
        })
        .catch(function (error) {
          var message = describeFetchError(error);
          setStatus("生成失败：" + message);
          setResult(message);
        });
    }, 0);
  }

  function runSmartImitationAction() {
    var templateText = String(byId("imitation-template-text").value || "").trim();
    var requirement = String(byId("imitation-requirement").value || "").trim();
    var referenceMaterial = String(byId("imitation-reference-material").value || "").trim();
    var paragraphs;
    var config = modeConfig[state.currentMode] || modeConfig.smartImitation;

    resetSmartWritePreviewState();
    state.pendingApplyAction = "";
    setApplyEnabled(false);

    if (!templateText) {
      setStatus("请先提供仿写模板。");
      setResult("请先提供仿写模板。");
      return;
    }
    if (!requirement) {
      setStatus("请填写仿写需求。");
      setResult("请填写仿写需求。");
      return;
    }

    paragraphs = helpers.collectParagraphsFromText
      ? helpers.collectParagraphsFromText(templateText, SMART_WRITE_EXTRACTION_OPTIONS)
      : [];

    state.latestDocumentPayload = {
      documentId: "smart-imitation",
      scene: "word",
      selectionMode: "selection",
      content: {
        plainText: templateText,
        paragraphs: paragraphs,
        headings: []
      },
      options: {
        imitationRequirement: requirement,
        imitationReferenceMaterial: referenceMaterial
      }
    };
    state.latestSelectionMode = "selection";

    setStatus(config.runningText);
    setPlainResult("正在生成仿写内容，请稍候。");
    request("/word/smart-imitation", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "";
        state.rewriteResult = setSmartWriteResult(body.data);
        setApplyEnabled(false);
        setTrace(body.traceId);
        hideCompareForSmartImitation();
        setStatus(config.doneText);
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("生成失败：" + message);
        setResult(message);
      });
  }

  function applyPreview() {
    if (state.pendingApplyAction === "rewrite") {
      applyRewrite();
    }
  }

  function runPrimaryAction() {
    if (state.currentMode === "smartImitation") {
      runSmartImitationAction();
      return;
    }
    if (state.currentMode === "smartWrite") {
      runSmartWriteAction();
      return;
    }
    if (state.currentMode === "documentReview") {
      runDocumentReview();
      return;
    }
    if (state.currentMode === "formatReview") {
      runFormatReview();
    }
  }

  function bindEvents() {
    byId("template-select").addEventListener("change", function (event) {
      state.selectedTemplateId = event.target.value;
    });
    byId("write-action").addEventListener("change", function (event) {
      state.writeAction = event.target.value;
    });
    byId("rewrite-style").addEventListener("change", function (event) {
      state.rewriteStyle = event.target.value;
      updateRewritePromptPreview();
    });
    byId("focus-point").addEventListener("change", function (event) {
      state.focusPoint = event.target.value;
      updateRewritePromptPreview();
    });
    byId("length-mode").addEventListener("change", function (event) {
      state.lengthMode = event.target.value;
      updateRewritePromptPreview();
    });
    byId("user-instruction").addEventListener("input", function (event) {
      state.userInstruction = event.target.value;
    });
    byId("technical-document-type").addEventListener("change", function (event) {
      applyDocumentReviewPrompt(event.target.value);
    });
    byId("technical-review-prompt").addEventListener("input", function (event) {
      state.technicalReviewPrompt = event.target.value;
    });
    byId("imitation-template-text").addEventListener("input", function (event) {
      state.imitationTemplateText = event.target.value;
    });
    byId("imitation-requirement").addEventListener("input", function (event) {
      state.imitationRequirement = event.target.value;
    });
    byId("imitation-reference-material").addEventListener("input", function (event) {
      state.imitationReferenceMaterial = event.target.value;
    });
    byId("btn-save-provider-url").addEventListener("click", saveProviderBaseUrl);
    byId("btn-save-api-key").addEventListener("click", saveProviderApiKey);
    byId("btn-clear-api-key").addEventListener("click", clearProviderApiKey);
    byId("btn-refresh").addEventListener("click", refreshConfig);
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
    byId("btn-edit-provider").addEventListener("click", function () {
      showProviderEditor(true);
    });
    byId("btn-back-provider-summary").addEventListener("click", function () {
      showProviderEditor(false);
    });
    byId("workflow-profile-select").addEventListener("change", function (event) {
      var taskType = getCurrentWorkflowTaskType();
      state.workflowProfileSelections[taskType] = event.target.value;
      renderWorkflowProfileStrip();
    });
    byId("btn-activate-workflow-profile").addEventListener("click", function () {
      var taskType = getCurrentWorkflowTaskType();
      activateWorkflowProfile(state.workflowProfileSelections[taskType], taskType);
    });
    byId("workflow-profile-manager").addEventListener("click", handleWorkflowProfileManagerAction);
    byId("btn-apply").addEventListener("click", applyPreview);
    byId("btn-copy-result").addEventListener("click", copyResult);
    byId("btn-run-primary").addEventListener("click", runPrimaryAction);
    byId("result-output").addEventListener("click", handleDocumentReviewAction);
    byId("btn-copy-review-record").addEventListener("click", copyDocumentReviewRecord);
    byId("btn-preview-review-record").addEventListener("click", toggleDocumentReviewRecordPreview);
    byId("btn-result-preview").addEventListener("click", function () {
      setResultViewMode("preview");
    });
    byId("btn-result-compare").addEventListener("click", function () {
      setResultViewMode("compare");
    });
    byId("btn-result-plain").addEventListener("click", function () {
      setResultViewMode("plain");
    });
  }

  if (!isTaskpanePage()) {
    window.openTaskpane = function (mode) {
      return switchMode(mode || "smartWrite");
    };
    return;
  }

  bindEvents();
  byId("frontend-version-line").textContent = FRONTEND_BUILD_VERSION;
  byId("technical-review-prompt").value = state.technicalReviewPrompt;
  renderFallbackTemplateOptions();
  switchMode(getInitialMode());
  refreshConfig();
  startScopeWatcher();
})();
