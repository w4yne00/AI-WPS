(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.19.1-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var DOCUMENT_REVIEW_POLL_INTERVAL_MS = 3000;
  var DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS = 10000;
  var WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS = 15000;
  var SETTINGS_REFRESH_REQUEST_TIMEOUT_MS = 8000;
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
  var WRITING_POLICY_SCOPE_DEFS = [
    { scope: "global", label: "全局企业规范", caption: "企业术语与通用写作规则" },
    { scope: "word.smart_write", label: "智能编写补充", caption: "仅在智能编写中使用的文体规则" },
    { scope: "word.smart_imitation", label: "智能仿写补充", caption: "仅在智能仿写中使用的文体规则" },
    { scope: "word.document_review", label: "文档审查补充", caption: "仅在文档审查中检查的文体规则" }
  ];
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
    workflowProfileRequestSequence: {},
    workflowProfileMutationBusy: false,
    settingsWorkflowTaskType: "word.smart_write",
    workflowProfileEditor: null,
    configRefreshRequestId: 0,
    configRefreshPromise: null,
    configRefreshActiveRequestId: 0,
    configRefreshActiveSilent: false,
    configRefreshQueued: false,
    configRefreshQueuedSilent: true,
    modelInterfaceDetectable: false,
    settingsRefreshController: null,
    workflowHelpPinned: false,
    providerUrlEditorOpen: false,
    writingPolicyView: "home",
    writingPolicyScope: "global",
    writingPolicyType: "term",
    writingPolicyItems: [],
    writingPolicyPresetPack: null,
    writingPolicyPresetItems: [],
    writingPolicyPresetError: "",
    writingPolicySummary: null,
    writingPolicyLoadSequence: 0,
    writingPolicyMutationBusy: false,
    writingPolicyEditor: null,
    writingPolicyEditorDirty: false,
    writingPolicySummaryState: "idle",
    writingPolicyListError: "",
    writingPolicySearch: "",
    writingPolicySearchTimer: null,
    writingPolicyImportStep: "select",
    writingPolicyImportPreview: null,
    writingPolicyImportBusy: false,
    writingPolicyImportSequence: 0,
    writingPolicyImportReader: null,
    writingPolicyImportReturnView: "scope",
    writingPolicyScene: "auto",
    writingPolicyAudit: null,
    currentMode: "smartWrite",
    lastTaskMode: "smartWrite",
    copyText: "",
    diagnosticsCopyText: "",
    scopeWatcher: null
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setNodeTextIfChanged(node, value) {
    var nextValue = value || "";
    if (node && node.textContent !== nextValue) {
      node.textContent = nextValue;
      return true;
    }
    return false;
  }

  function setNodeClassNameIfChanged(node, value) {
    var nextValue = value || "";
    if (node && node.className !== nextValue) {
      node.className = nextValue;
      return true;
    }
    return false;
  }

  function setNodeAttributeIfChanged(node, name, value) {
    var nextValue = value || "";
    if (node && node.getAttribute && node.getAttribute(name) === nextValue) {
      return false;
    }
    if (node && node.setAttribute) {
      node.setAttribute(name, nextValue);
      return true;
    }
    return false;
  }

  function setStatus(message) {
    var statusLine = byId("status-line");
    var settingsStatusLine = byId("settings-status-line");
    if (statusLine) {
      setNodeTextIfChanged(statusLine, message);
    }
    if (settingsStatusLine) {
      setNodeTextIfChanged(settingsStatusLine, message);
    }
  }

  function setSettingsStatus(message) {
    var settingsStatusLine = byId("settings-status-line");
    if (settingsStatusLine) {
      setNodeTextIfChanged(settingsStatusLine, message);
    }
  }

  function confirmWorkflowEditorDiscard() {
    if (!state.workflowProfileEditor || !state.workflowProfileEditor.dirty) {
      return true;
    }
    return !window.confirm || window.confirm("当前工作流编辑内容尚未保存，确认放弃修改？");
  }

  function confirmWritingPolicyEditorDiscard() {
    if (!state.writingPolicyEditor || !state.writingPolicyEditorDirty) {
      return true;
    }
    return !window.confirm || window.confirm("当前规范条目尚未保存，确认放弃修改？");
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

  function setProviderLine(providerName) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "模型接口",
      "enterprise-dify-workflow": "模型工作流",
      mock: "模拟接口"
    };
    var detail = providerText[providerName] || providerName || "未检测";
    state.providerName = detail;
    setNodeTextIfChanged(byId("provider-line"), "接口：" + detail);
    setNodeTextIfChanged(byId("settings-provider-line"), "接口：" + detail);
    setNodeTextIfChanged(byId("provider-summary-type"), detail);
  }

  function setProviderName(name) {
    state.providerName = name || "未检测";
  }

  function setProviderBaseUrl(baseUrl) {
    var summary = byId("provider-summary-url");
    state.providerBaseUrl = baseUrl || "";
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    if (!state.providerUrlEditorOpen && byId("provider-base-url").value !== state.providerBaseUrl) {
      byId("provider-base-url").value = state.providerBaseUrl;
    }
  }

  function setProviderAuthLine(authSource) {
    state.providerAuthSource = authSource || "none";
  }

  function applyProviderConfig(configData) {
    setProviderName(configData.providerName || "企业大模型接口");
    setProviderBaseUrl(configData.providerBaseUrl || "");
    setProviderAuthLine(configData.providerAuthSource || "none");
    state.taskApiKeys = configData.taskApiKeys || {};
    renderWorkflowProfileManager();
    renderWorkflowProfileStrip();
  }

  function renderModelInterfaceState(detectable) {
    var taskTypes = TASK_API_KEY_DEFS.map(function (item) {
      return item.taskType;
    });
    var profilesByTask = {};
    var modelState;
    var badge = byId("provider-readiness-badge");
    var summary = byId("provider-summary-url");
    taskTypes.forEach(function (taskType) {
      profilesByTask[taskType] = getWorkflowProfileData(taskType);
    });
    modelState = helpers.deriveModelInterfaceState({
      detectable: detectable,
      providerBaseUrl: state.providerBaseUrl,
      taskTypes: taskTypes,
      profilesByTask: profilesByTask
    });
    setNodeClassNameIfChanged(badge, "readiness-badge is-" + modelState.code);
    setNodeTextIfChanged(badge, modelState.label);
    setNodeTextIfChanged(summary, state.providerBaseUrl || "未配置接口地址");
    setNodeAttributeIfChanged(summary, "title", state.providerBaseUrl || "未配置接口地址");
    setNodeTextIfChanged(byId("diagnostics-summary"), modelState.label);
  }

  function setAdapterUnavailableState(error) {
    var message = error && error.message ? error.message : "端口未监听";
    setHealthBadge("badge-warn", "待启动");
    setTrace("");
    setProviderLine("mock");
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
    setNodeClassNameIfChanged(node, "badge " + mode);
    setNodeTextIfChanged(node, text);
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

  function clearWritingPolicyUsage() {
    var strip = byId("writing-policy-usage-strip");
    var summary = byId("writing-policy-usage-summary");
    var details = byId("writing-policy-usage-details");
    var list = byId("writing-policy-usage-list");
    if (summary) {
      summary.textContent = "";
    }
    if (list) {
      list.textContent = "";
    }
    if (details) {
      details.hidden = true;
      details.open = false;
    }
    if (strip) {
      strip.hidden = true;
    }
    clearWritingPolicyAudit();
  }

  function clearWritingPolicyAudit() {
    var summary = byId("writing-policy-audit-summary");
    var details = byId("writing-policy-audit-details");
    var needsReview = byId("writing-policy-needs-review");
    var suggestions = byId("writing-policy-expression-suggestions");
    var needsReviewList = byId("writing-policy-needs-review-list");
    var suggestionList = byId("writing-policy-expression-suggestions-list");
    if (summary) {
      summary.textContent = "";
    }
    if (needsReviewList) {
      needsReviewList.textContent = "";
    }
    if (suggestionList) {
      suggestionList.textContent = "";
    }
    if (needsReview) {
      needsReview.hidden = true;
    }
    if (suggestions) {
      suggestions.hidden = true;
    }
    if (details) {
      details.hidden = true;
      details.open = false;
    }
  }

  function appendWritingPolicyAuditFindings(list, findings) {
    findings.forEach(function (finding) {
      var row = document.createElement("li");
      row.textContent = helpers.writingPolicyAuditFindingText
        ? helpers.writingPolicyAuditFindingText(finding)
        : String(finding && finding.message || "");
      list.appendChild(row);
    });
  }

  function renderWritingPolicyAudit(value) {
    var strip = byId("writing-policy-usage-strip");
    var summary = byId("writing-policy-audit-summary");
    var details = byId("writing-policy-audit-details");
    var needsReview = byId("writing-policy-needs-review");
    var suggestions = byId("writing-policy-expression-suggestions");
    var needsReviewList = byId("writing-policy-needs-review-list");
    var suggestionList = byId("writing-policy-expression-suggestions-list");
    var audit = helpers.normalizeWritingPolicyAudit
      ? helpers.normalizeWritingPolicyAudit(value)
      : null;

    clearWritingPolicyAudit();
    if (!audit || !summary || !details || !needsReview || !suggestions ||
        !needsReviewList || !suggestionList) {
      return;
    }
    summary.textContent = audit.summary || (
      audit.passed ? "已完成写作规范检查" : "写作规范检查已完成"
    );
    appendWritingPolicyAuditFindings(needsReviewList, audit.needsReview);
    appendWritingPolicyAuditFindings(suggestionList, audit.expressionSuggestions);
    needsReview.hidden = audit.needsReview.length === 0;
    suggestions.hidden = audit.expressionSuggestions.length === 0;
    details.hidden = audit.needsReview.length === 0 &&
      audit.expressionSuggestions.length === 0;
    if (!needsReview.hidden) {
      needsReview.setAttribute("aria-label", "需要核对");
    }
    if (!suggestions.hidden) {
      suggestions.setAttribute("aria-label", "表达建议");
    }
    if (strip) {
      strip.hidden = false;
    }
  }

  function renderWritingPolicyUsage(value, taskType) {
    var strip = byId("writing-policy-usage-strip");
    var summary = byId("writing-policy-usage-summary");
    var details = byId("writing-policy-usage-details");
    var list = byId("writing-policy-usage-list");
    var usage = helpers.normalizeWritingPolicyUsage
      ? helpers.normalizeWritingPolicyUsage(value)
      : null;
    var summaryText;
    var detailItems;

    clearWritingPolicyUsage();
    if (!usage || !strip || !summary || !details || !list) {
      return;
    }
    summaryText = helpers.writingPolicyUsageSummary
      ? helpers.writingPolicyUsageSummary(usage, taskType)
      : "";
    detailItems = helpers.writingPolicyUsageDetails
      ? helpers.writingPolicyUsageDetails(usage)
      : [];
    summary.textContent = summaryText;
    detailItems.forEach(function (item) {
      var row = document.createElement("li");
      row.textContent = item;
      list.appendChild(row);
    });
    details.hidden = detailItems.length === 0;
    strip.hidden = false;
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
    clearWritingPolicyUsage();
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

  function setDocumentReviewJobId(jobId) {
    state.documentReviewJobId = jobId || "";
    renderWorkflowProfileStrip();
  }

  function resetDocumentReviewState() {
    state.documentReviewData = null;
    state.documentReviewIssueStatus = {};
    state.documentReviewRecordPreviewVisible = false;
    clearWritingPolicyUsage();
    setDocumentReviewJobId("");
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

  function setSmartWriteResult(result, taskType) {
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
    state.writingPolicyAudit = normalized.writingPolicyAudit || null;
    renderWritingPolicyUsage(normalized.writingPolicyUsage, taskType);
    renderWritingPolicyAudit(state.writingPolicyAudit);
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
    syncSettingsRefreshController();
  }

  function syncSettingsRefreshController() {
    var settingsView = byId("settings-view");
    var shouldRun;
    if (!state.settingsRefreshController) {
      return;
    }
    shouldRun = Boolean(
      settingsView &&
      byId("settings-view").classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      state.writingPolicyView === "home" &&
      !state.workflowProfileEditor &&
      !state.providerUrlEditorOpen &&
      !state.workflowProfileMutationBusy
    );
    if (shouldRun) {
      state.settingsRefreshController.start();
    } else if (state.settingsRefreshController.isRunning()) {
      state.settingsRefreshController.stop();
      invalidateConfigRefresh();
    }
  }

  function isSettingsRefreshEligible() {
    var settingsView = byId("settings-view");
    return Boolean(
      settingsView &&
      settingsView.classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      state.writingPolicyView === "home" &&
      !state.workflowProfileEditor &&
      !state.providerUrlEditorOpen &&
      !state.workflowProfileMutationBusy
    );
  }

  function invalidateConfigRefresh() {
    state.configRefreshRequestId += 1;
    state.configRefreshQueued = false;
    state.configRefreshQueuedSilent = true;
  }

  function toggleSettingsShortcut() {
    var settingsOpen = byId("settings-view").classList.contains("active");
    var returnMode = state.lastTaskMode || "smartWrite";
    var returnConfig;

    if (!settingsOpen) {
      if (state.currentMode !== "settings") {
        state.lastTaskMode = state.currentMode;
        returnMode = state.currentMode;
      }
      if (!state.workflowProfileEditor && MODE_WORKFLOW_TASK_TYPES[returnMode]) {
        state.settingsWorkflowTaskType = MODE_WORKFLOW_TASK_TYPES[returnMode];
        renderWorkflowProfileManager();
      }
      returnConfig = modeConfig[returnMode] || modeConfig.smartWrite;
      switchView("settings");
      document.body.setAttribute("data-task-mode", "settings");
      byId("task-title").textContent = "设置";
      byId("btn-open-settings").classList.add("is-back");
      byId("btn-open-settings").setAttribute("title", "返回" + returnConfig.title);
      byId("btn-open-settings").setAttribute("aria-label", "返回" + returnConfig.title);
      setWritingPolicyView("home");
      loadWritingPolicySummary();
      return;
    }

    if (state.writingPolicyMutationBusy) {
      setStatus("写作规范条目正在保存，请稍候。");
      return;
    }
    if (!confirmWorkflowEditorDiscard() || !confirmWritingPolicyEditorDiscard()) {
      return;
    }
    state.workflowProfileEditor = null;
    clearWritingPolicyEditorState();
    setWritingPolicyView("home", true);

    if (state.currentMode === "settings") {
      switchMode(returnMode);
      return;
    }

    returnConfig = modeConfig[state.currentMode] || modeConfig.smartWrite;
    switchView("home");
    document.body.setAttribute("data-task-mode", state.currentMode);
    byId("task-title").textContent = returnConfig.title;
    byId("btn-open-settings").classList.remove("is-back");
    byId("btn-open-settings").setAttribute("title", "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", "打开设置");
  }

  function switchMode(mode) {
    var requestedMode = modeConfig[mode] ? mode : "smartWrite";
    var config = modeConfig[requestedMode] || modeConfig.smartWrite;
    var settingsMode = requestedMode === "settings";
    var returnTitle;

    state.currentMode = requestedMode;
    if (!settingsMode) {
      state.lastTaskMode = requestedMode;
    }
    returnTitle = (modeConfig[state.lastTaskMode] || modeConfig.smartWrite).title;
    document.body.setAttribute("data-task-mode", state.currentMode);
    byId("task-title").textContent = config.title;
    byId("btn-open-settings").classList.toggle("is-back", settingsMode);
    byId("btn-open-settings").setAttribute("title", settingsMode ? "返回" + returnTitle : "打开设置");
    byId("btn-open-settings").setAttribute("aria-label", settingsMode ? "返回" + returnTitle : "打开设置");
    resetSmartWritePreviewState();
    resetDocumentReviewState();

    if (settingsMode) {
      switchView("settings");
      renderWorkflowProfileManager();
      setWritingPolicyView("home");
      loadWritingPolicySummary();
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
    byId("writing-policy-scene-block").hidden = state.currentMode !== "smartWrite";
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
            requestError.httpStatus = response.status;
            throw requestError;
          }
          requestError = new Error(adapterError.message || body.message || ("HTTP " + response.status));
          requestError.adapterCode = adapterError.code || "";
          requestError.httpStatus = response.status;
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

  function readAdapterJson(path, requestOptions) {
    return request(path, null, requestOptions).catch(function (error) {
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

  function refreshConfig(options) {
    var requestId;
    var refreshOperation;
    var refreshPromise;
    var healthConnected = false;
    var silent = Boolean(options && options.silent);

    function releaseRefresh(result) {
      var shouldRestart = false;
      var restartSilent = true;
      if (state.configRefreshPromise === refreshPromise) {
        state.configRefreshPromise = null;
        state.configRefreshActiveRequestId = 0;
        state.configRefreshActiveSilent = false;
        shouldRestart = state.configRefreshQueued;
        restartSilent = state.configRefreshQueuedSilent;
        state.configRefreshQueued = false;
        state.configRefreshQueuedSilent = true;
      }
      if (shouldRestart && isSettingsRefreshEligible()) {
        return refreshConfig({ silent: restartSilent });
      }
      return result;
    }

    if (state.configRefreshPromise) {
      if (state.configRefreshActiveRequestId !== state.configRefreshRequestId) {
        if (!state.configRefreshQueued) {
          state.configRefreshQueuedSilent = silent;
        } else {
          state.configRefreshQueuedSilent = state.configRefreshQueuedSilent && silent;
        }
        state.configRefreshQueued = true;
      } else if (!silent && state.configRefreshActiveSilent) {
        state.configRefreshActiveSilent = false;
        setSettingsStatus("正在刷新配置...");
      }
      return state.configRefreshPromise;
    }

    requestId = state.configRefreshRequestId + 1;
    state.configRefreshRequestId = requestId;
    state.configRefreshActiveRequestId = requestId;
    state.configRefreshActiveSilent = silent;
    if (!silent) {
      setSettingsStatus("正在刷新配置...");
    }
    refreshOperation = request("/health", null, {
      timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS
    }).then(function (health) {
      var healthData;
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      healthData = health.data || {};
      healthConnected = true;
      setHealthBadge("badge-ok", "已连接");
      setProviderLine(healthData.providerType || "未检测");
      return Promise.all([
        Promise.resolve(health),
        readAdapterJson("/templates", { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS }),
        readAdapterJson("/config", { timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS })
      ]);
    }).then(function (results) {
      if (!results) {
        return null;
      }
      var templates = results[1];
      var config = results[2];
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (config.success === false) {
        throw new Error(config.errors && config.errors[0] && config.errors[0].message || "配置读取失败");
      }
      applyProviderConfig(config.data || {});
      if (templates.success === false) {
        renderFallbackTemplateOptions();
      } else {
        state.templates = mergeTemplates(templates.data.templates || []);
        renderTemplateOptions();
      }
      return refreshAllWorkflowProfiles(requestId, {
        timeoutMs: SETTINGS_REFRESH_REQUEST_TIMEOUT_MS
      }).then(function (profileResults) {
        var profileIndex;
        if (state.configRefreshRequestId !== requestId) {
          return null;
        }
        if (!profileResults || profileResults.length !== TASK_API_KEY_DEFS.length) {
          throw new Error("工作流配置读取不完整");
        }
        for (profileIndex = 0; profileIndex < profileResults.length; profileIndex += 1) {
          if (!profileResults[profileIndex]) {
            throw new Error("工作流配置读取失败");
          }
        }
        state.modelInterfaceDetectable = true;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        if (!state.configRefreshActiveSilent) {
          setSettingsStatus("就绪");
        }
        return results;
      });
    }).catch(function (error) {
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (!healthConnected) {
        setHealthBadge("badge-warn", "待启动");
      }
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      setSettingsStatus("配置刷新失败：" + describeFetchError(error));
      return null;
    });

    refreshPromise = refreshOperation.then(releaseRefresh, function (error) {
      if (state.configRefreshRequestId === requestId) {
        if (!healthConnected) {
          setHealthBadge("badge-warn", "待启动");
        }
        state.modelInterfaceDetectable = false;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        setSettingsStatus("配置刷新失败：" + describeFetchError(error));
      }
      return releaseRefresh(null);
    });
    state.configRefreshPromise = refreshPromise;
    return refreshPromise;
  }

  function renderFallbackTemplateOptions() {
    state.templates = mergeTemplates([]);
    renderTemplateOptions();
  }

  function closeProviderUrlEditor(suppressRefreshSync) {
    var details = byId("provider-url-details");
    var input = byId("provider-base-url");
    state.providerUrlEditorOpen = false;
    if (details) {
      details.removeAttribute("open");
    }
    if (input) {
      input.value = state.providerBaseUrl || "";
    }
    if (suppressRefreshSync !== true) {
      syncSettingsRefreshController();
    }
  }

  function saveProviderBaseUrl() {
    var input = byId("provider-base-url");
    var baseUrl = (input.value || "").trim();
    var refreshPromise;
    setSettingsStatus("正在保存大模型 API URL...");
    request("/provider/base-url", { baseUrl: baseUrl })
      .then(function (body) {
        var savedUrl = typeof body.data.providerBaseUrl === "string" ? body.data.providerBaseUrl : baseUrl;
        setProviderBaseUrl(savedUrl);
        closeProviderUrlEditor(true);
        setSettingsStatus("大模型 API URL 已保存。");
        invalidateConfigRefresh();
        refreshPromise = refreshConfig({ silent: false });
        syncSettingsRefreshController();
        return refreshPromise;
      })
      .catch(function (error) {
        setSettingsStatus("保存大模型 API URL 失败：" + describeFetchError(error));
      });
  }

  function getCurrentWorkflowTaskType() {
    return MODE_WORKFLOW_TASK_TYPES[state.currentMode] || "";
  }

  function getSettingsWorkflowTaskType() {
    var taskType = state.settingsWorkflowTaskType;
    var exists = TASK_API_KEY_DEFS.some(function (item) {
      return item.taskType === taskType;
    });
    return exists ? taskType : TASK_API_KEY_DEFS[0].taskType;
  }

  function isWorkflowInteractionBlocked() {
    return Boolean(state.documentReviewJobId || state.workflowProfileMutationBusy);
  }

  function nextWorkflowProfileRequestId(taskType) {
    var requestId = (state.workflowProfileRequestSequence[taskType] || 0) + 1;
    state.workflowProfileRequestSequence[taskType] = requestId;
    return requestId;
  }

  function invalidateWorkflowProfileRequests(taskType) {
    return nextWorkflowProfileRequestId(taskType);
  }

  function isWorkflowProfileRequestCurrent(taskType, requestId) {
    return state.workflowProfileRequestSequence[taskType] === requestId;
  }

  function getWorkflowProfileOptionState(profile, activeProfileId, busy) {
    if (helpers.workflowProfileOptionState) {
      var sharedState = helpers.workflowProfileOptionState(profile, activeProfileId);
      return {
        id: sharedState.id,
        label: sharedState.label,
        active: Boolean(sharedState.active),
        disabled: Boolean(busy || sharedState.disabled)
      };
    }
    return {
      active: Boolean(profile && profile.id === activeProfileId),
      disabled: Boolean(busy || !profile || !profile.keyConfigured)
    };
  }

  function getWorkflowProfileDraftValidation(draft, requireApiKey) {
    if (helpers.validateWorkflowProfileDraft) {
      var sharedValidation = helpers.validateWorkflowProfileDraft(
        draft,
        requireApiKey ? "create" : "edit"
      );
      return {
        valid: Boolean(sharedValidation && sharedValidation.ok),
        message: sharedValidation && sharedValidation.message || ""
      };
    }
    if (!draft || !String(draft.name || "").trim()) {
      return { valid: false, message: "请填写工作流名称。" };
    }
    if (requireApiKey && !String(draft.apiKey || "").trim()) {
      return { valid: false, message: "请填写工作流 API Key。" };
    }
    return { valid: true, message: "" };
  }

  function getShouldActivateNewWorkflowProfile(data, requestedActivate) {
    if (helpers.shouldActivateNewWorkflowProfile) {
      var profileCount = data && Array.isArray(data.profiles) ?
        data.profiles.length : Number(data && data.profileCount || 0);
      return helpers.shouldActivateNewWorkflowProfile(profileCount, requestedActivate);
    }
    return Boolean(requestedActivate || !(data && data.activeProfileId));
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

  function loadWorkflowProfiles(taskType, configRefreshRequestId, requestOptions) {
    var requestId;
    var previousProfileData;
    if (!taskType) {
      return Promise.resolve(null);
    }
    previousProfileData = state.workflowProfiles[taskType] || null;
    requestId = nextWorkflowProfileRequestId(taskType);
    return request(
      "/provider/workflow-profiles?taskType=" + encodeURIComponent(taskType),
      null,
      requestOptions
    )
      .then(function (body) {
        if (!isWorkflowProfileRequestCurrent(taskType, requestId) ||
            (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
          return null;
        }
        state.workflowProfiles[taskType] = normalizeWorkflowProfileData(body.data || {}, taskType);
        state.workflowProfileSelections[taskType] = state.workflowProfiles[taskType].activeProfileId || "";
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        renderModelInterfaceState(state.modelInterfaceDetectable);
        return state.workflowProfiles[taskType];
      })
      .catch(function (error) {
        var loadError;
        var preservedProfileData;
        if (!isWorkflowProfileRequestCurrent(taskType, requestId) ||
            (configRefreshRequestId && state.configRefreshRequestId !== configRefreshRequestId)) {
          return null;
        }
        loadError = describeFetchError(error);
        if (previousProfileData) {
          preservedProfileData = {};
          Object.keys(previousProfileData).forEach(function (key) {
            preservedProfileData[key] = previousProfileData[key];
          });
          preservedProfileData.loadError = loadError;
          state.workflowProfiles[taskType] = preservedProfileData;
        } else {
          state.workflowProfiles[taskType] = {
            taskType: taskType,
            activeProfileId: "",
            profileCount: 0,
            profiles: [],
            loadError: loadError
          };
        }
        state.modelInterfaceDetectable = false;
        renderWorkflowProfileStrip();
        renderWorkflowProfileManager();
        renderModelInterfaceState(state.modelInterfaceDetectable);
        return null;
      });
  }

  function refreshAllWorkflowProfiles(configRefreshRequestId, requestOptions) {
    return Promise.all(TASK_API_KEY_DEFS.map(function (item) {
      return loadWorkflowProfiles(item.taskType, configRefreshRequestId, requestOptions);
    }));
  }

  function renderWorkflowProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var select = byId("workflow-profile-select");
    var current = byId("workflow-profile-current");
    var taskType = getCurrentWorkflowTaskType();
    var data;
    var selectedId;
    if (!strip || !select || !current) {
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
        var optionState = getWorkflowProfileOptionState(
          profile,
          data.activeProfileId,
          isWorkflowInteractionBlocked()
        );
        option.value = profile.id;
        option.textContent = profile.name + (profile.keyConfigured ? "" : "（密钥未配置）");
        option.selected = profile.id === selectedId;
        option.disabled = optionState.disabled;
        select.appendChild(option);
      });
    }
    select.disabled = isWorkflowInteractionBlocked() || !data.profiles.length;
    current.textContent = "当前：" + (
      helpers.getActiveWorkflowProfileName ? helpers.getActiveWorkflowProfileName(data) : "尚未配置"
    );
  }

  function getWorkflowProfileById(taskType, profileId) {
    var profiles = getWorkflowProfileData(taskType).profiles;
    var index;
    for (index = 0; index < profiles.length; index += 1) {
      if (profiles[index].id === profileId) {
        return profiles[index];
      }
    }
    return null;
  }

  function canDeleteWorkflowProfile(profile, activeProfileId) {
    if (helpers.canDeleteWorkflowProfile) {
      return helpers.canDeleteWorkflowProfile(profile, activeProfileId);
    }
    return Boolean(profile && profile.id && profile.id !== activeProfileId);
  }

  function escapeWorkflowText(value) {
    if (helpers.escapeHtml) {
      return helpers.escapeHtml(String(value || ""));
    }
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderWorkflowTaskTabs() {
    var tabs = byId("workflow-task-tabs");
    var taskType = getSettingsWorkflowTaskType();
    var buttons;
    var index;
    if (!tabs) {
      return;
    }
    buttons = tabs.querySelectorAll("[data-workflow-task-tab]");
    for (index = 0; index < buttons.length; index += 1) {
      var active = buttons[index].getAttribute("data-workflow-task-tab") === taskType;
      buttons[index].classList.toggle("active", active);
      buttons[index].setAttribute("aria-selected", active ? "true" : "false");
      buttons[index].tabIndex = active ? 0 : -1;
      buttons[index].disabled = state.workflowProfileMutationBusy;
    }
  }

  function scrollWorkflowTaskTabIntoView(button) {
    var reducedMotion = false;
    if (!button || typeof button.scrollIntoView !== "function") {
      return;
    }
    try {
      reducedMotion = Boolean(
        window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    } catch (error) {
      reducedMotion = false;
    }
    try {
      button.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "nearest",
        inline: "nearest"
      });
    } catch (error) {
      try {
        button.scrollIntoView(true);
      } catch (fallbackError) {
        // Older WPS WebViews may not expose a working scrollIntoView implementation.
      }
    }
  }

  function handleWorkflowTaskTabKeydown(event) {
    var buttons = byId("workflow-task-tabs").querySelectorAll("[data-workflow-task-tab]");
    var currentIndex = Array.prototype.indexOf.call(buttons, event.target);
    var nextIndex = currentIndex;
    var nextButton;
    if (currentIndex < 0 || state.workflowProfileMutationBusy) {
      return;
    }
    if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    } else if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % buttons.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = buttons.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    nextButton = buttons[nextIndex];
    nextButton.click();
    nextButton.focus();
    scrollWorkflowTaskTabIntoView(nextButton);
  }

  function setWorkflowHelpOpen(open, pinned) {
    var button = byId("workflow-help-button");
    var popover = byId("workflow-help-popover");
    if (typeof pinned === "boolean") {
      state.workflowHelpPinned = pinned;
    }
    popover.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function syncWorkflowProfileManagerBusyState() {
    var manager = byId("workflow-profile-manager");
    var controls;
    var index;
    if (!manager) {
      return;
    }
    controls = manager.querySelectorAll("button, input, textarea");
    for (index = 0; index < controls.length; index += 1) {
      controls[index].disabled = state.workflowProfileMutationBusy;
    }
  }

  function setWorkflowProfileMutationBusy(busy) {
    state.workflowProfileMutationBusy = Boolean(busy);
    renderWorkflowProfileStrip();
    renderWorkflowTaskTabs();
    syncWorkflowProfileManagerBusyState();
    syncSettingsRefreshController();
  }

  function markWorkflowProfileEditorDirty() {
    if (state.workflowProfileEditor) {
      state.workflowProfileEditor.dirty = true;
    }
  }

  function renderWorkflowProfileManager() {
    var manager = byId("workflow-profile-manager");
    var taskType = getSettingsWorkflowTaskType();
    var definition = TASK_API_KEY_DEFS.filter(function (item) {
      return item.taskType === taskType;
    })[0] || TASK_API_KEY_DEFS[0];
    var data = getWorkflowProfileData(taskType);
    var editor = state.workflowProfileEditor;
    var rows = [];
    var disabledAttribute = state.workflowProfileMutationBusy ? " disabled" : "";
    var createDisabledAttribute = state.workflowProfileMutationBusy || data.loadError ? " disabled" : "";
    var activationDisabledAttribute = isWorkflowInteractionBlocked() ? " disabled" : "";
    if (!manager) {
      return;
    }
    renderWorkflowTaskTabs();
    if (editor && editor.taskType === taskType) {
      var profile = editor.mode === "edit" ? getWorkflowProfileById(taskType, editor.profileId) : null;
      if (editor.mode === "edit" && !profile) {
        state.workflowProfileEditor = null;
        syncSettingsRefreshController();
        renderWorkflowProfileManager();
        return;
      }
      rows.push('<section class="workflow-settings-subpage" aria-label="' +
        (editor.mode === "create" ? "新建工作流" : "编辑工作流") + '">');
      rows.push('<div class="workflow-subpage-head"><button type="button" class="ghost-action mini-button" data-workflow-action="editor-cancel"' + disabledAttribute + '>返回</button><div><h5>' +
        (editor.mode === "create" ? "新建" + definition.label + "工作流" : "编辑" + escapeWorkflowText(profile.name)) +
        '</h5><span>' + definition.label + '</span></div></div>');
      rows.push('<div class="workflow-editor-fields">');
      rows.push('<label class="field"><span>工作流名称</span><input type="text" data-workflow-editor-name maxlength="40" value="' +
        escapeWorkflowText(profile ? profile.name : "") + '"' + disabledAttribute + ' /></label>');
      rows.push('<label class="field"><span>备注</span><textarea data-workflow-editor-note rows="3" maxlength="200" placeholder="选填"' + disabledAttribute + '>' +
        escapeWorkflowText(profile ? profile.note : "") + '</textarea></label>');
      rows.push('<label class="field"><span>' + (editor.mode === "create" ? "API Key" : "新 API Key（选填）") +
        '</span><input type="password" data-workflow-editor-key placeholder="' +
        (editor.mode === "create" ? "请输入工作流 API Key" : "留空则保持现有密钥") + '"' + disabledAttribute + ' /></label>');
      if (editor.mode === "create") {
        var shouldCheckActivate = getShouldActivateNewWorkflowProfile(data, false);
        rows.push('<label class="workflow-activate-check"><input type="checkbox" data-workflow-editor-activate' +
          (shouldCheckActivate ? " checked" : "") + disabledAttribute + ' /> 保存后设为当前</label>');
      }
      rows.push('</div><div class="button-row workflow-editor-actions">');
      rows.push('<button type="button" data-workflow-action="' + (editor.mode === "create" ? "create-save" : "edit-save") + '" data-task-type="' +
        taskType + '"' + (profile ? ' data-profile-id="' + escapeWorkflowText(profile.id) + '"' : "") + disabledAttribute + '>保存</button>');
      rows.push('<button type="button" class="ghost-action" data-workflow-action="editor-cancel"' + disabledAttribute + '>取消</button>');
      rows.push('</div></section>');
      manager.innerHTML = rows.join("");
      return;
    }

    rows.push('<div class="workflow-settings-toolbar"><div><strong>' + definition.label + '</strong><span>当前：' +
      escapeWorkflowText(helpers.getActiveWorkflowProfileName ? helpers.getActiveWorkflowProfileName(data) : "尚未配置") +
      '</span></div><button type="button" data-workflow-action="create-open" data-task-type="' + taskType + '"' + createDisabledAttribute + '>新建</button></div>');
    if (data.loadError) {
      rows.push('<div class="workflow-profile-error-actions"><p class="workflow-profile-error">无法读取工作流配置：' +
        escapeWorkflowText(data.loadError) + '</p><button type="button" class="ghost-action mini-button" data-workflow-action="reload" data-task-type="' +
        taskType + '"' + disabledAttribute + '>重新读取</button></div>');
    }
    if (!data.profiles.length && !data.loadError) {
      rows.push('<p class="workflow-profile-empty">尚未配置工作流。</p>');
    }
    if (data.profiles.length) {
      rows.push('<div class="workflow-profile-list">');
      data.profiles.forEach(function (profile) {
        var isActive = profile.id === data.activeProfileId;
        var canDelete = canDeleteWorkflowProfile(profile, data.activeProfileId);
        var statusText = helpers.workflowProfileStatusText ?
          helpers.workflowProfileStatusText(profile, data.activeProfileId) :
          (isActive ? "当前使用" : (profile.keyConfigured ? "可切换" : "密钥未配置"));
        rows.push('<div class="workflow-profile-row" data-profile-id="' + escapeWorkflowText(profile.id) + '">');
        rows.push('<div class="workflow-profile-summary"><strong>' + escapeWorkflowText(profile.name) + '</strong>');
        if (profile.note) {
          rows.push('<span class="workflow-profile-note">' + escapeWorkflowText(profile.note) + '</span>');
        }
        rows.push('</div>');
        rows.push('<span class="provider-badge">' + escapeWorkflowText(statusText) + '</span>');
        rows.push('<div class="workflow-profile-actions">');
        if (!isActive && profile.keyConfigured) {
          rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="activate" data-task-type="' + taskType +
            '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + activationDisabledAttribute + '>设为当前</button>');
        }
        rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="edit-open" data-task-type="' + taskType +
          '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + disabledAttribute + '>编辑</button>');
        if (canDelete) {
          rows.push('<button type="button" class="ghost-action mini-button danger-action" data-workflow-action="delete" data-task-type="' + taskType +
            '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + disabledAttribute + '>删除</button>');
        }
        rows.push('</div></div>');
      });
      rows.push('</div>');
    }
    manager.innerHTML = rows.join("");
  }

  function completeWorkflowMutation(taskType, message) {
    state.workflowProfileMutationBusy = false;
    state.workflowProfileEditor = null;
    renderWorkflowTaskTabs();
    return loadWorkflowProfiles(taskType).then(function () {
      syncSettingsRefreshController();
      setStatus(message);
    });
  }

  function failWorkflowMutation(taskType, prefix, error, preserveEditor) {
    setWorkflowProfileMutationBusy(false);
    state.workflowProfileSelections[taskType] = getWorkflowProfileData(taskType).activeProfileId || "";
    setStatus(prefix + "：" + describeFetchError(error));
    renderWorkflowProfileStrip();
    if (!preserveEditor) {
      renderWorkflowProfileManager();
    }
  }

  function createWorkflowProfile(taskType) {
    var nameInput = document.querySelector("[data-workflow-editor-name]");
    var keyInput = document.querySelector("[data-workflow-editor-key]");
    var noteInput = document.querySelector("[data-workflow-editor-note]");
    var activateInput = document.querySelector("[data-workflow-editor-activate]");
    var draft = {
      name: nameInput ? (nameInput.value || "").trim() : "",
      apiKey: keyInput ? (keyInput.value || "").trim() : "",
      note: noteInput ? (noteInput.value || "").trim() : ""
    };
    var validation = getWorkflowProfileDraftValidation(draft, true);
    var activate = getShouldActivateNewWorkflowProfile(
      getWorkflowProfileData(taskType),
      Boolean(activateInput && activateInput.checked)
    );
    if (!validation.valid) {
      setStatus(validation.message || "请填写工作流名称和 API Key。");
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/workflow-profiles", {
      taskType: taskType,
      name: draft.name,
      apiKey: draft.apiKey,
      note: draft.note,
      activate: activate
    }).then(function () {
      return completeWorkflowMutation(taskType, "工作流已保存。");
    }).catch(function (error) {
      failWorkflowMutation(taskType, "保存工作流失败", error, true);
    });
  }

  function saveWorkflowProfileEdit(profileId, taskType) {
    var nameInput = document.querySelector("[data-workflow-editor-name]");
    var noteInput = document.querySelector("[data-workflow-editor-note]");
    var keyInput = document.querySelector("[data-workflow-editor-key]");
    var draft = {
      name: nameInput ? (nameInput.value || "").trim() : "",
      note: noteInput ? (noteInput.value || "").trim() : "",
      apiKey: keyInput ? (keyInput.value || "").trim() : ""
    };
    var validation = getWorkflowProfileDraftValidation(draft, false);
    var apiKey = draft.apiKey;
    var metadataSaved = false;
    if (!validation.valid) {
      setStatus(validation.message || "请填写工作流名称。");
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId), {
      name: draft.name,
      note: draft.note
    }, { method: "PATCH" }).then(function () {
      metadataSaved = true;
      if (!apiKey) {
        return completeWorkflowMutation(taskType, "工作流名称和备注已保存，密钥保持不变。");
      }
      return request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/api-key", {
        apiKey: apiKey
      }).then(function () {
        return completeWorkflowMutation(taskType, "工作流名称、备注和密钥已保存。");
      });
    }).catch(function (error) {
      if (!metadataSaved) {
        failWorkflowMutation(taskType, "保存工作流名称和备注失败", error, true);
        return;
      }
      state.workflowProfileMutationBusy = false;
      state.workflowProfileEditor = null;
      renderWorkflowTaskTabs();
      return loadWorkflowProfiles(taskType).then(function () {
        syncSettingsRefreshController();
        setStatus("名称和备注已保存，但密钥更换失败：" + describeFetchError(error));
      });
    });
  }

  function activateWorkflowProfile(profileId, taskType, previousProfileId) {
    var data = getWorkflowProfileData(taskType);
    var profile = getWorkflowProfileById(taskType, profileId);
    var optionState = getWorkflowProfileOptionState(profile, data.activeProfileId, false);
    if (isWorkflowInteractionBlocked()) {
      state.workflowProfileSelections[taskType] = previousProfileId || data.activeProfileId || "";
      renderWorkflowProfileStrip();
      setStatus(state.documentReviewJobId ?
        "文档审查正在运行，暂不能切换工作流。" :
        "工作流配置正在更新，请稍后再切换。");
      return;
    }
    if (!profileId) {
      setStatus("请选择要切换的工作流。");
      return;
    }
    if (!profile || optionState.disabled) {
      state.workflowProfileSelections[taskType] = previousProfileId || data.activeProfileId || "";
      renderWorkflowProfileStrip();
      setStatus("该工作流尚未配置 API Key，无法切换。");
      return;
    }
    previousProfileId = typeof previousProfileId === "string" ? previousProfileId : (data.activeProfileId || "");
    state.workflowProfileSelections[taskType] = profileId;
    invalidateWorkflowProfileRequests(taskType);
    setWorkflowProfileMutationBusy(true);
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId) + "/activate", {})
      .then(function (body) {
        var nextData = normalizeWorkflowProfileData(body.data || {}, taskType);
        invalidateWorkflowProfileRequests(taskType);
        state.workflowProfiles[taskType] = nextData;
        state.workflowProfileSelections[taskType] = nextData.activeProfileId;
        state.workflowProfileMutationBusy = false;
        renderWorkflowProfileStrip();
        renderWorkflowTaskTabs();
        renderWorkflowProfileManager();
        renderModelInterfaceState(state.modelInterfaceDetectable);
        setStatus("工作流已切换，从下一次任务开始生效。");
      })
      .catch(function (error) {
        state.workflowProfileMutationBusy = false;
        state.workflowProfileSelections[taskType] = previousProfileId;
        renderWorkflowProfileStrip();
        renderWorkflowTaskTabs();
        renderWorkflowProfileManager();
        setStatus("切换工作流失败：" + describeFetchError(error));
      });
  }

  function deleteWorkflowProfile(profileId, taskType) {
    var data = getWorkflowProfileData(taskType);
    var profile = getWorkflowProfileById(taskType, profileId);
    if (!canDeleteWorkflowProfile(profile, data.activeProfileId)) {
      setStatus("当前工作流不可删除，请先切换到其他工作流。");
      return;
    }
    if (window.confirm && !window.confirm("确认删除工作流“" + profile.name + "”？删除后无法恢复其密钥。")) {
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/workflow-profiles/" + encodeURIComponent(profileId), null, { method: "DELETE" })
      .then(function () {
        return completeWorkflowMutation(taskType, "工作流“" + profile.name + "”已删除。");
      })
      .catch(function (error) {
        failWorkflowMutation(taskType, "删除工作流失败", error);
      });
  }

  function handleWorkflowProfileSelectionChange(event) {
    var taskType = getCurrentWorkflowTaskType();
    var data = getWorkflowProfileData(taskType);
    var previousProfileId = data.activeProfileId || state.workflowProfileSelections[taskType] || "";
    var profileId = event.target.value;
    if (!profileId || profileId === previousProfileId) {
      state.workflowProfileSelections[taskType] = previousProfileId;
      renderWorkflowProfileStrip();
      return;
    }
    activateWorkflowProfile(profileId, taskType, previousProfileId);
  }

  function handleWorkflowTaskTabClick(event) {
    var taskType = event.target.getAttribute("data-workflow-task-tab");
    if (!taskType || state.workflowProfileMutationBusy) {
      return;
    }
    if (taskType === getSettingsWorkflowTaskType()) {
      return;
    }
    if (!confirmWorkflowEditorDiscard()) {
      return;
    }
    state.settingsWorkflowTaskType = taskType;
    state.workflowProfileEditor = null;
    syncSettingsRefreshController();
    renderWorkflowTaskTabs();
    renderWorkflowProfileManager();
    if (!state.workflowProfiles[taskType]) {
      loadWorkflowProfiles(taskType);
    }
  }

  function handleWorkflowProfileManagerAction(event) {
    var target = event.target;
    var action = target.getAttribute("data-workflow-action");
    var taskType = target.getAttribute("data-task-type") || "";
    var profileId = target.getAttribute("data-profile-id") || "";
    if (!action || state.workflowProfileMutationBusy) {
      return;
    }
    taskType = taskType || getSettingsWorkflowTaskType();
    if (action === "create-open") {
      if (getWorkflowProfileData(taskType).loadError) {
        setStatus("工作流配置读取失败，请先重新读取。");
        return;
      }
      state.workflowProfileEditor = { mode: "create", taskType: taskType, profileId: "", dirty: false };
      syncSettingsRefreshController();
      renderWorkflowProfileManager();
    } else if (action === "edit-open") {
      state.workflowProfileEditor = { mode: "edit", taskType: taskType, profileId: profileId, dirty: false };
      syncSettingsRefreshController();
      renderWorkflowProfileManager();
    } else if (action === "editor-cancel") {
      if (!confirmWorkflowEditorDiscard()) {
        return;
      }
      state.workflowProfileEditor = null;
      renderWorkflowProfileManager();
      syncSettingsRefreshController();
    } else if (action === "reload") {
      setStatus("正在重新读取工作流配置...");
      loadWorkflowProfiles(taskType);
    } else if (action === "create-save") {
      createWorkflowProfile(taskType);
    } else if (action === "activate") {
      activateWorkflowProfile(profileId, taskType, getWorkflowProfileData(taskType).activeProfileId || "");
    } else if (action === "edit-save") {
      saveWorkflowProfileEdit(profileId, taskType);
    } else if (action === "delete") {
      deleteWorkflowProfile(profileId, taskType);
    }
  }

  function getWritingPolicyScopeDefinition(scope) {
    var index;
    for (index = 0; index < WRITING_POLICY_SCOPE_DEFS.length; index += 1) {
      if (WRITING_POLICY_SCOPE_DEFS[index].scope === scope) {
        return WRITING_POLICY_SCOPE_DEFS[index];
      }
    }
    return WRITING_POLICY_SCOPE_DEFS[0];
  }

  function renderWritingPolicyManagerView() {
    var view = state.writingPolicyView || "home";
    var home = view === "home";
    var diagnosticsDisclosure = byId("diagnostics-disclosure");
    byId("connection-settings-section").hidden = !home;
    if (home) {
      diagnosticsDisclosure.hidden = false;
    } else {
      diagnosticsDisclosure.open = false;
      diagnosticsDisclosure.hidden = true;
    }
    byId("writing-policy-preset-view").hidden = view !== "preset";
    byId("writing-policy-scope-view").hidden = view !== "scope";
    byId("writing-policy-list-view").hidden = view !== "list";
    byId("writing-policy-editor-view").hidden = view !== "editor";
    byId("writing-policy-import-view").hidden = view !== "import";
  }

  function focusWritingPolicyView(view) {
    var targetIds = {
      home: "btn-open-writing-policy-manager",
      preset: "writing-policy-preset-title",
      scope: "writing-policy-scope-title",
      list: "writing-policy-list-title",
      editor: "writing-policy-editor-title",
      import: "writing-policy-import-title"
    };
    var targetId = targetIds[view];
    if (!targetId) {
      return;
    }
    setTimeout(function () {
      var target;
      if (state.writingPolicyView !== view) {
        return;
      }
      target = byId(targetId);
      if (target && target.focus) {
        target.focus();
      }
    }, 0);
  }

  function setWritingPolicyView(view, suppressRefreshSync) {
    var diagnosticsDisclosure = byId("diagnostics-disclosure");
    if (view === "home" && diagnosticsDisclosure) {
      diagnosticsDisclosure.open = false;
    }
    state.writingPolicyView = view;
    renderWritingPolicyManagerView();
    focusWritingPolicyView(view);
    if (!suppressRefreshSync) {
      syncSettingsRefreshController();
    }
  }

  function formatWritingPolicyUpdatedAt(value) {
    var text;
    var date;
    if (helpers.formatWritingPolicyUpdatedAt) {
      return helpers.formatWritingPolicyUpdatedAt(value);
    }
    text = String(value || "").trim();
    if (!text) {
      return "尚无更新时间";
    }
    date = new Date(text);
    if (!isFinite(date.getTime())) {
      return "最近更新：" + text;
    }
    return "最近更新：" + new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false
    }).format(date);
  }

  function renderWritingPolicySummary() {
    var summary = state.writingPolicySummary || {};
    var statusNode = byId("writing-policy-summary-status");
    var enterButton = byId("btn-open-writing-policy-manager");
    var retryButton = byId("btn-retry-writing-policy-summary");
    byId("writing-policy-summary-total").textContent = String(Math.max(0, Number(summary.totalCount) || 0));
    byId("writing-policy-summary-enabled").textContent = String(Math.max(0, Number(summary.enabledCount) || 0));
    byId("writing-policy-summary-updated").textContent = formatWritingPolicyUpdatedAt(summary.updatedAt);
    enterButton.disabled = state.writingPolicySummaryState !== "ready";
    retryButton.hidden = state.writingPolicySummaryState !== "error";
    if (state.writingPolicySummaryState === "loading") {
      statusNode.textContent = "正在读取...";
    } else if (state.writingPolicySummaryState === "ready") {
      statusNode.textContent = "可用";
    } else if (state.writingPolicySummaryState === "unsupported") {
      statusNode.textContent = "当前 adapter 版本不支持写作规范库";
    } else if (state.writingPolicySummaryState === "error") {
      statusNode.textContent = "写作规范库暂不可用";
    } else {
      statusNode.textContent = "尚未读取";
    }
  }

  function loadWritingPolicySummary() {
    var requestId = state.writingPolicyLoadSequence + 1;
    state.writingPolicyLoadSequence = requestId;
    state.writingPolicySummaryState = "loading";
    renderWritingPolicySummary();
    return request("/writing-policies/summary").then(function (body) {
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicySummary = body.data || {};
      state.writingPolicySummaryState = "ready";
      renderWritingPolicySummary();
      return state.writingPolicySummary;
    }).catch(function (error) {
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicySummary = null;
      state.writingPolicySummaryState = error && error.httpStatus === 404 ? "unsupported" : "error";
      renderWritingPolicySummary();
      return null;
    });
  }

  function renderWritingPolicyPresetItems() {
    var pack = state.writingPolicyPresetPack || {};
    var source = pack.source || {};
    var meta = byId("writing-policy-preset-pack-meta");
    var list = byId("writing-policy-preset-item-list");
    var index;
    list.textContent = "";
    if (state.writingPolicyPresetError) {
      meta.textContent = "预置规范暂时无法读取，请稍后重试。";
      return;
    }
    if (!pack.packId) {
      meta.textContent = "正在读取规范包...";
      return;
    }
    meta.textContent = pack.name + " v" + pack.version + " ｜ 来源：" +
      source.name + " " + source.version + " ｜ 提交：" + source.commit +
      " ｜ 许可证：" + source.license;
    for (index = 0; index < state.writingPolicyPresetItems.length; index += 1) {
      var item = state.writingPolicyPresetItems[index];
      var row = document.createElement("div");
      var title = document.createElement("strong");
      var rule = document.createElement("p");
      var trace = document.createElement("small");
      row.className = "writing-policy-item-row writing-policy-preset-item";
      title.textContent = item.name || item.preferredText || "未命名规范";
      rule.textContent = item.ruleText || item.definition || "";
      trace.textContent = "ID：" + String(item.id || "") + " ｜ 来源版本：" +
        String((item.source || {}).version || source.version || "") +
        " ｜ 提交：" + String((item.source || {}).commit || source.commit || "") +
        " ｜ 许可证：" + String((item.source || {}).license || source.license || "");
      row.appendChild(title);
      row.appendChild(rule);
      row.appendChild(trace);
      list.appendChild(row);
    }
    if (!state.writingPolicyPresetItems.length) {
      list.textContent = "当前规范包暂无可显示条目。";
    }
  }

  function loadWritingPolicyPresetItems(packId) {
    return request("/writing-policies/items?layer=preset&packId=" +
      encodeURIComponent(packId)).then(function (body) {
      state.writingPolicyPresetItems = body.data && Array.isArray(body.data.items)
        ? body.data.items
        : [];
      state.writingPolicyPresetError = "";
      renderWritingPolicyPresetItems();
      return state.writingPolicyPresetItems;
    }).catch(function () {
      state.writingPolicyPresetItems = [];
      state.writingPolicyPresetError = "items_unavailable";
      renderWritingPolicyPresetItems();
      return [];
    });
  }

  function loadWritingPolicyPresetPacks() {
    state.writingPolicyPresetPack = null;
    state.writingPolicyPresetItems = [];
    state.writingPolicyPresetError = "";
    renderWritingPolicyPresetItems();
    return request("/writing-policies/packs").then(function (body) {
      var packs = body.data && Array.isArray(body.data.packs) ? body.data.packs : [];
      var index;
      for (index = 0; index < packs.length; index += 1) {
        if (packs[index].packId === "yangqi-tech-writing-base") {
          state.writingPolicyPresetPack = packs[index];
          return loadWritingPolicyPresetItems(packs[index].packId);
        }
      }
      state.writingPolicyPresetError = "base_pack_missing";
      renderWritingPolicyPresetItems();
      return [];
    }).catch(function () {
      state.writingPolicyPresetError = "packs_unavailable";
      renderWritingPolicyPresetItems();
      return [];
    });
  }

  function openWritingPolicyPresetView() {
    if (state.writingPolicySummaryState !== "ready") {
      return;
    }
    setWritingPolicyView("preset");
    loadWritingPolicyPresetPacks();
  }

  function openWritingPolicyScopeView() {
    setWritingPolicyView("scope");
  }

  function renderWritingPolicyTypeSwitch() {
    var buttons = byId("writing-policy-type-switch").querySelectorAll("[data-writing-policy-type]");
    var index;
    for (index = 0; index < buttons.length; index += 1) {
      var type = buttons[index].getAttribute("data-writing-policy-type");
      var active = type === state.writingPolicyType;
      buttons[index].classList.toggle("active", active);
      buttons[index].setAttribute("aria-selected", active ? "true" : "false");
      buttons[index].disabled = state.writingPolicyMutationBusy || (type === "term" && state.writingPolicyScope !== "global");
      buttons[index].tabIndex = active ? 0 : -1;
    }
  }

  function renderWritingPolicyList() {
    var scopeDefinition = getWritingPolicyScopeDefinition(state.writingPolicyScope);
    var list = byId("writing-policy-item-list");
    var statusNode = byId("writing-policy-list-status");
    var retryButton = byId("btn-retry-writing-policy-list");
    var addButton = byId("btn-writing-policy-add");
    list.textContent = "";
    byId("writing-policy-list-title").textContent = scopeDefinition.label;
    byId("writing-policy-list-caption").textContent = scopeDefinition.caption;
    byId("writing-policy-search-input").value = state.writingPolicySearch;
    renderWritingPolicyTypeSwitch();
    addButton.disabled = state.writingPolicyMutationBusy || Boolean(state.writingPolicyListError);
    retryButton.hidden = !state.writingPolicyListError;
    if (state.writingPolicyListError) {
      statusNode.textContent = "写作规范库暂不可用，未显示空列表。";
      return;
    }
    if (!state.writingPolicyItems.length) {
      statusNode.textContent = "当前范围暂无" + (state.writingPolicyType === "term" ? "术语。" : "文体规则。");
      return;
    }
    statusNode.textContent = "共 " + state.writingPolicyItems.length + " 条" + (state.writingPolicyType === "term" ? "术语" : "文体规则");
    state.writingPolicyItems.forEach(function (item) {
      var row = document.createElement("button");
      var text = document.createElement("span");
      var title = document.createElement("strong");
      var note = document.createElement("small");
      var status = document.createElement("span");
      row.type = "button";
      row.className = "writing-policy-item-row";
      row.setAttribute("data-writing-policy-item-id", String(item.id || ""));
      title.textContent = String(item.type === "term" ? item.preferredText || "未命名术语" : item.name || "未命名规则");
      note.textContent = String(item.note || (item.type === "term" ? item.definition || "暂无说明" : item.ruleText || "暂无说明"));
      status.className = "provider-badge";
      status.textContent = item.enabled === false ? "已停用" : "已启用";
      text.appendChild(title);
      text.appendChild(note);
      row.appendChild(text);
      row.appendChild(status);
      list.appendChild(row);
    });
  }

  function loadWritingPolicyItems() {
    var requestId = state.writingPolicyLoadSequence + 1;
    state.writingPolicyLoadSequence = requestId;
    state.writingPolicyListError = "";
    byId("writing-policy-list-status").textContent = "正在读取...";
    byId("writing-policy-item-list").textContent = "";
    return request("/writing-policies/items?scope=" + encodeURIComponent(state.writingPolicyScope) +
      "&type=" + encodeURIComponent(state.writingPolicyType) +
      "&query=" + encodeURIComponent(state.writingPolicySearch)).then(function (body) {
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyItems = body.data && Array.isArray(body.data.items) ? body.data.items : [];
      renderWritingPolicyList();
      return state.writingPolicyItems;
    }).catch(function (error) {
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyItems = [];
      state.writingPolicyListError = describeFetchError(error);
      renderWritingPolicyList();
      return null;
    });
  }

  function openWritingPolicyList(scope) {
    state.writingPolicyScope = getWritingPolicyScopeDefinition(scope).scope;
    state.writingPolicyType = state.writingPolicyScope === "global" ? state.writingPolicyType : "style";
    state.writingPolicySearch = "";
    state.writingPolicyItems = [];
    state.writingPolicyListError = "";
    setWritingPolicyView("list");
    renderWritingPolicyList();
    loadWritingPolicyItems();
  }

  function joinWritingPolicyList(values) {
    return Array.isArray(values) ? values.join(" | ") : "";
  }

  function splitWritingPolicyList(value) {
    return String(value || "").split("|").map(function (item) {
      return item.trim();
    }).filter(function (item) {
      return Boolean(item);
    });
  }

  function setWritingPolicyEditorError(message, field) {
    var errorNode = byId("writing-policy-editor-error");
    var fieldIds = {
      preferredText: "writing-policy-preferred-text",
      name: "writing-policy-style-name",
      ruleText: "writing-policy-rule-text",
      scope: "writing-policy-editor-caption"
    };
    var errorIds = {
      preferredText: "writing-policy-preferred-error",
      name: "writing-policy-style-name-error",
      ruleText: "writing-policy-rule-error"
    };
    ["preferredText", "name", "ruleText"].forEach(function (fieldName) {
      var input = byId(fieldIds[fieldName]);
      var fieldError = byId(errorIds[fieldName]);
      input.removeAttribute("aria-invalid");
      fieldError.textContent = "";
      fieldError.hidden = true;
    });
    errorNode.textContent = String(message || "");
    errorNode.hidden = !message;
    if (message && errorIds[field]) {
      byId(errorIds[field]).textContent = String(message);
      byId(errorIds[field]).hidden = false;
      byId(fieldIds[field]).setAttribute("aria-invalid", "true");
    }
    if (message && fieldIds[field] && byId(fieldIds[field]) && byId(fieldIds[field]).focus) {
      byId(fieldIds[field]).focus();
    }
  }

  function clearWritingPolicyEditorState() {
    var ids = [
      "writing-policy-preferred-text", "writing-policy-aliases", "writing-policy-forbidden-variants",
      "writing-policy-definition", "writing-policy-style-name", "writing-policy-rule-text",
      "writing-policy-positive-example", "writing-policy-negative-example", "writing-policy-note",
      "writing-policy-category", "writing-policy-context-keywords"
    ];
    ids.forEach(function (id) {
      byId(id).value = "";
    });
    state.writingPolicyEditor = null;
    state.writingPolicyEditorDirty = false;
    setWritingPolicyEditorError("", "");
  }

  function setWritingPolicyEditorControlsDisabled(disabled) {
    var controls = byId("writing-policy-editor-view").querySelectorAll("button, input, textarea, select");
    var index;
    for (index = 0; index < controls.length; index += 1) {
      controls[index].disabled = Boolean(disabled);
    }
  }

  function renderWritingPolicyEditor() {
    var editor = state.writingPolicyEditor || {};
    var item = editor.item || {};
    var type = editor.type || state.writingPolicyType;
    var scopeDefinition = getWritingPolicyScopeDefinition(editor.scope || state.writingPolicyScope);
    byId("writing-policy-editor-title").textContent = editor.mode === "edit" ? "编辑规范条目" : "新增规范条目";
    byId("writing-policy-editor-caption").textContent = scopeDefinition.label + " · " + (type === "term" ? "术语" : "文体规则");
    byId("writing-policy-term-fields").hidden = type !== "term";
    byId("writing-policy-style-fields").hidden = type !== "style";
    byId("writing-policy-category-field").hidden = type !== "term";
    byId("writing-policy-always-apply-field").hidden = type !== "style";
    byId("writing-policy-preferred-text").value = String(item.preferredText || "");
    byId("writing-policy-aliases").value = joinWritingPolicyList(item.aliases);
    byId("writing-policy-forbidden-variants").value = joinWritingPolicyList(item.forbiddenVariants);
    byId("writing-policy-definition").value = String(item.definition || "");
    byId("writing-policy-style-name").value = String(item.name || "");
    byId("writing-policy-rule-text").value = String(item.ruleText || "");
    byId("writing-policy-positive-example").value = String(item.positiveExample || "");
    byId("writing-policy-negative-example").value = String(item.negativeExample || "");
    byId("writing-policy-note").value = String(item.note || "");
    byId("writing-policy-category").value = String(item.category || "");
    byId("writing-policy-context-keywords").value = joinWritingPolicyList(item.contextKeywords);
    byId("writing-policy-priority").value = String(item.priority || "medium");
    byId("writing-policy-always-apply").checked = Boolean(item.alwaysApply);
    byId("writing-policy-enabled").checked = item.enabled !== false;
    byId("writing-policy-editor-advanced").open = false;
    byId("btn-writing-policy-delete").hidden = editor.mode !== "edit";
    setWritingPolicyEditorError("", "");
    setWritingPolicyEditorControlsDisabled(state.writingPolicyMutationBusy);
  }

  function openWritingPolicyEditor(item) {
    state.writingPolicyEditor = {
      mode: item ? "edit" : "create",
      item: item || {},
      type: item && item.type ? item.type : state.writingPolicyType,
      scope: item && item.scope ? item.scope : state.writingPolicyScope
    };
    state.writingPolicyEditorDirty = false;
    setWritingPolicyView("editor");
    renderWritingPolicyEditor();
  }

  function readWritingPolicyDraft() {
    var editor = state.writingPolicyEditor || {};
    var type = editor.type || state.writingPolicyType;
    var draft = {
      type: type,
      scope: editor.scope || state.writingPolicyScope,
      contextKeywords: splitWritingPolicyList(byId("writing-policy-context-keywords").value),
      priority: byId("writing-policy-priority").value || "medium",
      enabled: Boolean(byId("writing-policy-enabled").checked),
      note: String(byId("writing-policy-note").value || "").trim()
    };
    if (type === "term") {
      draft.category = String(byId("writing-policy-category").value || "").trim();
      draft.preferredText = String(byId("writing-policy-preferred-text").value || "").trim();
      draft.aliases = splitWritingPolicyList(byId("writing-policy-aliases").value);
      draft.forbiddenVariants = splitWritingPolicyList(byId("writing-policy-forbidden-variants").value);
      draft.definition = String(byId("writing-policy-definition").value || "").trim();
    } else {
      draft.name = String(byId("writing-policy-style-name").value || "").trim();
      draft.ruleText = String(byId("writing-policy-rule-text").value || "").trim();
      draft.positiveExample = String(byId("writing-policy-positive-example").value || "").trim();
      draft.negativeExample = String(byId("writing-policy-negative-example").value || "").trim();
      draft.alwaysApply = Boolean(byId("writing-policy-always-apply").checked);
    }
    return draft;
  }

  function setWritingPolicyMutationBusy(busy) {
    state.writingPolicyMutationBusy = Boolean(busy);
    setWritingPolicyEditorControlsDisabled(state.writingPolicyMutationBusy);
  }

  function saveWritingPolicyItem() {
    var editor = state.writingPolicyEditor;
    var draft;
    var validation;
    var path;
    var options;
    if (!editor || state.writingPolicyMutationBusy) {
      return;
    }
    draft = readWritingPolicyDraft();
    validation = helpers.validateWritingPolicyDraft ? helpers.validateWritingPolicyDraft(draft) : { ok: true, field: "", message: "" };
    if (!validation.ok) {
      setWritingPolicyEditorError(validation.message, validation.field);
      return;
    }
    path = "/writing-policies/items";
    options = { timeoutMs: WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS };
    if (editor.mode === "edit") {
      path += "/" + encodeURIComponent(String(editor.item.id || ""));
      options.method = "PATCH";
    }
    setWritingPolicyEditorError("", "");
    setWritingPolicyMutationBusy(true);
    request(path, draft, options).then(function () {
      setWritingPolicyMutationBusy(false);
      state.writingPolicyEditorDirty = false;
      clearWritingPolicyEditorState();
      setWritingPolicyView("list");
      return loadWritingPolicyItems().then(function () {
        loadWritingPolicySummary();
        setStatus("写作规范条目已保存。");
      });
    }).catch(function (error) {
      var field = helpers.writingPolicyConflictField ? helpers.writingPolicyConflictField(error) : "";
      setWritingPolicyMutationBusy(false);
      setWritingPolicyEditorError(describeFetchError(error), field);
    });
  }

  function deleteWritingPolicyItem() {
    var editor = state.writingPolicyEditor;
    var item;
    var itemName;
    if (!editor || editor.mode !== "edit" || state.writingPolicyMutationBusy) {
      return;
    }
    item = editor.item || {};
    itemName = String(item.type === "term" ? item.preferredText || "该术语" : item.name || "该规则");
    if (window.confirm && !window.confirm("确认删除“" + itemName + "”？删除后无法恢复。")) {
      return;
    }
    setWritingPolicyMutationBusy(true);
    request("/writing-policies/items/" + encodeURIComponent(String(item.id || "")), null, {
      method: "DELETE",
      timeoutMs: WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS
    })
      .then(function () {
        setWritingPolicyMutationBusy(false);
        state.writingPolicyEditorDirty = false;
        clearWritingPolicyEditorState();
        setWritingPolicyView("list");
        return loadWritingPolicyItems().then(function () {
          loadWritingPolicySummary();
          setStatus("写作规范条目已删除。");
        });
      }).catch(function (error) {
        setWritingPolicyMutationBusy(false);
        setWritingPolicyEditorError("删除失败：" + describeFetchError(error), "");
      });
  }

  function closeWritingPolicyEditor() {
    if (!confirmWritingPolicyEditorDiscard()) {
      return;
    }
    clearWritingPolicyEditorState();
    setWritingPolicyView("list");
    renderWritingPolicyList();
  }

  function handleWritingPolicyScopeClick(event) {
    var target = event.target;
    while (target && target !== byId("writing-policy-scope-list") && !target.getAttribute("data-writing-policy-scope")) {
      target = target.parentNode;
    }
    if (target && target.getAttribute("data-writing-policy-scope")) {
      openWritingPolicyList(target.getAttribute("data-writing-policy-scope"));
    }
  }

  function handleWritingPolicyTypeClick(event) {
    var type = event.target.getAttribute("data-writing-policy-type");
    selectWritingPolicyType(type);
  }

  function selectWritingPolicyType(type) {
    if (!type || state.writingPolicyMutationBusy || (type === "term" && state.writingPolicyScope !== "global")) {
      return;
    }
    state.writingPolicyType = type;
    state.writingPolicyItems = [];
    state.writingPolicyListError = "";
    renderWritingPolicyList();
    loadWritingPolicyItems();
  }

  function handleWritingPolicyTypeKeydown(event) {
    var keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    var buttons;
    var enabledButtons;
    var currentIndex;
    var nextIndex;
    var type;
    if (keys.indexOf(event.key) < 0) {
      return;
    }
    buttons = Array.prototype.slice.call(byId("writing-policy-type-switch").querySelectorAll("[data-writing-policy-type]"));
    enabledButtons = buttons.filter(function (button) {
      return !button.disabled;
    });
    if (!enabledButtons.length) {
      return;
    }
    currentIndex = enabledButtons.indexOf(event.target);
    if (currentIndex < 0) {
      currentIndex = 0;
    }
    nextIndex = helpers.nextWritingPolicyTabIndex ?
      helpers.nextWritingPolicyTabIndex(currentIndex, event.key, enabledButtons.length) : currentIndex;
    if (nextIndex < 0 || !enabledButtons[nextIndex]) {
      return;
    }
    event.preventDefault();
    enabledButtons[nextIndex].focus();
    type = enabledButtons[nextIndex].getAttribute("data-writing-policy-type");
    selectWritingPolicyType(type);
  }

  function handleWritingPolicyListClick(event) {
    var target = event.target;
    var itemId;
    var item;
    while (target && target !== byId("writing-policy-item-list") && !target.getAttribute("data-writing-policy-item-id")) {
      target = target.parentNode;
    }
    itemId = target && target.getAttribute("data-writing-policy-item-id");
    if (!itemId) {
      return;
    }
    item = state.writingPolicyItems.filter(function (candidate) {
      return String(candidate.id || "") === itemId;
    })[0];
    if (item) {
      openWritingPolicyEditor(item);
    }
  }

  function scheduleWritingPolicySearch(value) {
    state.writingPolicySearch = String(value || "");
    if (state.writingPolicySearchTimer) {
      clearTimeout(state.writingPolicySearchTimer);
    }
    state.writingPolicySearchTimer = setTimeout(function () {
      state.writingPolicySearchTimer = null;
      loadWritingPolicyItems();
    }, 250);
  }

  function setWritingPolicyImportBusy(busy) {
    var controls = byId("writing-policy-import-view").querySelectorAll("button, input, select");
    var index;
    state.writingPolicyImportBusy = Boolean(busy);
    for (index = 0; index < controls.length; index += 1) {
      controls[index].disabled = state.writingPolicyImportBusy;
    }
  }

  function releaseWritingPolicyImportReader(abortRead, expectedReader) {
    var reader = expectedReader || state.writingPolicyImportReader;
    if (!reader) {
      return;
    }
    if (!expectedReader || state.writingPolicyImportReader === expectedReader) {
      state.writingPolicyImportReader = null;
    }
    reader.onload = null;
    reader.onerror = null;
    if (abortRead && reader.readyState === 1 && reader.abort) {
      reader.abort();
    }
  }

  function renderWritingPolicyImportStep() {
    var steps = byId("writing-policy-import-steps").querySelectorAll("[data-import-step]");
    var order = { select: 0, validate: 1, conflicts: 2, apply: 3 };
    var activeIndex = order[state.writingPolicyImportStep] || 0;
    var index;
    for (index = 0; index < steps.length; index += 1) {
      steps[index].classList.toggle(
        "active",
        order[steps[index].getAttribute("data-import-step")] <= activeIndex
      );
      if (order[steps[index].getAttribute("data-import-step")] === activeIndex) {
        steps[index].setAttribute("aria-current", "step");
      } else {
        steps[index].removeAttribute("aria-current");
      }
    }
  }

  function clearWritingPolicyImportPreview(message, clearFile) {
    state.writingPolicyImportPreview = null;
    state.writingPolicyImportStep = "select";
    if (clearFile) {
      byId("writing-policy-import-file").value = "";
    }
    byId("writing-policy-import-preview-panel").hidden = true;
    byId("writing-policy-import-error-list").textContent = "";
    byId("writing-policy-import-conflict-list").textContent = "";
    byId("writing-policy-import-errors-section").hidden = true;
    byId("writing-policy-import-conflicts-section").hidden = true;
    byId("writing-policy-import-errors-title").textContent = "校验错误";
    byId("writing-policy-import-conflicts-title").textContent = "冲突处理";
    byId("writing-policy-import-status").textContent = message || "请选择文件。";
    renderWritingPolicyImportStep();
  }

  function resetWritingPolicyImport(message) {
    state.writingPolicyImportSequence += 1;
    releaseWritingPolicyImportReader(true);
    setWritingPolicyImportBusy(false);
    clearWritingPolicyImportPreview(message, true);
  }

  function openWritingPolicyImport() {
    if (state.writingPolicyImportBusy) {
      return;
    }
    state.writingPolicyImportReturnView = state.writingPolicyView === "list" ? "list" : "scope";
    resetWritingPolicyImport("");
    setWritingPolicyView("import");
  }

  function closeWritingPolicyImport() {
    if (state.writingPolicyImportBusy) {
      return;
    }
    resetWritingPolicyImport("");
    setWritingPolicyView(state.writingPolicyImportReturnView === "list" ? "list" : "scope");
  }

  function handleWritingPolicyImportFileChange(event) {
    var file = event.target.files && event.target.files[0];
    var validation;
    state.writingPolicyImportSequence += 1;
    clearWritingPolicyImportPreview(file ? "已选择文件，可开始校验。" : "请选择文件。", false);
    if (!file) {
      return;
    }
    validation = helpers.validateWritingPolicyImportFile ? helpers.validateWritingPolicyImportFile(file) : { ok: true };
    if (!validation.ok) {
      byId("writing-policy-import-status").textContent = validation.message;
    }
  }

  function arrayBufferToWritingPolicyBase64(arrayBuffer) {
    var bytes = new Uint8Array(arrayBuffer);
    var chunks = [];
    var chunkSize = 32768;
    var offset;
    for (offset = 0; offset < bytes.length; offset += chunkSize) {
      chunks.push(String.fromCharCode.apply(null, bytes.subarray(offset, offset + chunkSize)));
    }
    var encoded = window.btoa(chunks.join(""));
    bytes = null;
    chunks.length = 0;
    return encoded;
  }

  function renderWritingPolicyImportPreview() {
    var preview = state.writingPolicyImportPreview;
    var errorsSection = byId("writing-policy-import-errors-section");
    var conflictsSection = byId("writing-policy-import-conflicts-section");
    var errorList = byId("writing-policy-import-error-list");
    var conflictList = byId("writing-policy-import-conflict-list");
    var applyButton = byId("btn-apply-writing-policy-import");
    errorList.textContent = "";
    conflictList.textContent = "";
    if (!preview) {
      byId("writing-policy-import-preview-panel").hidden = true;
      return;
    }
    byId("writing-policy-import-preview-panel").hidden = false;
    byId("writing-policy-import-new-count").textContent = String(preview.stats.newCount);
    byId("writing-policy-import-update-count").textContent = String(preview.stats.updateCount);
    byId("writing-policy-import-conflict-count").textContent = String(preview.stats.conflictCount);
    byId("writing-policy-import-error-count").textContent = String(preview.stats.errorCount);
    byId("writing-policy-import-errors-title").textContent = helpers.writingPolicyImportCountLabel ?
      helpers.writingPolicyImportCountLabel("校验错误", preview.stats.errorCount, preview.errors.length) : "校验错误";
    byId("writing-policy-import-conflicts-title").textContent = helpers.writingPolicyImportCountLabel ?
      helpers.writingPolicyImportCountLabel("冲突处理", preview.stats.conflictCount, preview.conflicts.length) : "冲突处理";
    preview.errors.forEach(function (item) {
      var row = document.createElement("li");
      row.textContent = item.message;
      errorList.appendChild(row);
    });
    errorsSection.hidden = preview.errors.length === 0;
    preview.conflicts.forEach(function (item) {
      var row = document.createElement("div");
      var message = document.createElement("span");
      var select = document.createElement("select");
      var keep = document.createElement("option");
      var skip = document.createElement("option");
      row.className = "writing-policy-import-conflict-row";
      message.textContent = item.message;
      select.setAttribute("data-writing-policy-conflict-row", String(item.rowNumber));
      keep.value = "keep_existing";
      keep.textContent = "保留库内标准";
      skip.value = "skip";
      skip.textContent = "跳过该行";
      select.appendChild(keep);
      select.appendChild(skip);
      select.value = helpers.normalizeWritingPolicyConflictDecision ?
        helpers.normalizeWritingPolicyConflictDecision(item.decision) : "keep_existing";
      row.appendChild(message);
      row.appendChild(select);
      conflictList.appendChild(row);
    });
    conflictsSection.hidden = preview.conflicts.length === 0;
    applyButton.disabled = state.writingPolicyImportBusy || !preview.previewToken;
    applyButton.textContent = preview.conflicts.length ? "按当前选择应用" : "应用无冲突项";
  }

  function previewWritingPolicyImport() {
    var input = byId("writing-policy-import-file");
    var file = input.files && input.files[0];
    var validation = helpers.validateWritingPolicyImportFile ?
      helpers.validateWritingPolicyImportFile(file) : { ok: Boolean(file), message: "请选择导入文件。" };
    var reader;
    var requestId;
    if (state.writingPolicyImportBusy) {
      return;
    }
    if (!validation.ok) {
      byId("writing-policy-import-status").textContent = validation.message;
      return;
    }
    reader = new FileReader();
    requestId = state.writingPolicyImportSequence + 1;
    state.writingPolicyImportSequence = requestId;
    state.writingPolicyImportReader = reader;
    setWritingPolicyImportBusy(true);
    state.writingPolicyImportStep = "validate";
    renderWritingPolicyImportStep();
    byId("writing-policy-import-status").textContent = "正在读取并校验文件...";
    reader.onerror = function () {
      if (state.writingPolicyImportSequence !== requestId) {
        return;
      }
      releaseWritingPolicyImportReader(false, reader);
      input.value = "";
      setWritingPolicyImportBusy(false);
      state.writingPolicyImportStep = "select";
      renderWritingPolicyImportStep();
      byId("writing-policy-import-status").textContent = "无法读取所选文件，请重新选择。";
    };
    reader.onload = function (event) {
      var arrayBuffer = event && event.target ? event.target.result : reader.result;
      var contentBase64 = "";
      var payload = null;
      var previewRequest;
      function releaseLargeReferences() {
        var isCurrentRequest = state.writingPolicyImportSequence === requestId;
        arrayBuffer = null;
        contentBase64 = "";
        payload = null;
        file = null;
        if (isCurrentRequest) {
          input.value = "";
        }
        releaseWritingPolicyImportReader(false, reader);
        reader = null;
        if (isCurrentRequest) {
          setWritingPolicyImportBusy(false);
          renderWritingPolicyImportPreview();
        }
      }
      try {
        contentBase64 = arrayBufferToWritingPolicyBase64(arrayBuffer);
        payload = helpers.buildWritingPolicyImportRequest ?
          helpers.buildWritingPolicyImportRequest(file, contentBase64) : null;
        previewRequest = request("/writing-policies/imports/preview", payload);
      } catch (error) {
        if (state.writingPolicyImportSequence === requestId) {
          state.writingPolicyImportStep = "select";
          byId("writing-policy-import-status").textContent = "文件编码失败，请重新选择。";
          renderWritingPolicyImportStep();
        }
        releaseLargeReferences();
        return;
      }
      previewRequest.then(function (body) {
        if (state.writingPolicyImportSequence !== requestId) {
          return;
        }
        state.writingPolicyImportPreview = helpers.normalizeWritingPolicyImportPreview ?
          helpers.normalizeWritingPolicyImportPreview(body.data || {}) : body.data;
        if (!state.writingPolicyImportPreview || !state.writingPolicyImportPreview.previewToken) {
          throw new Error("校验结果缺少导入预览编号。");
        }
        state.writingPolicyImportStep = state.writingPolicyImportPreview.conflicts.length ? "conflicts" : "apply";
        byId("writing-policy-import-status").textContent = state.writingPolicyImportPreview.conflicts.length ?
          "校验完成，请处理冲突后应用。" : "校验完成，可应用导入。";
        renderWritingPolicyImportPreview();
      }).catch(function (error) {
        if (state.writingPolicyImportSequence !== requestId) {
          return;
        }
        state.writingPolicyImportPreview = null;
        state.writingPolicyImportStep = "select";
        byId("writing-policy-import-status").textContent = "校验失败：" + describeFetchError(error);
        renderWritingPolicyImportPreview();
        renderWritingPolicyImportStep();
      }).then(function () {
        releaseLargeReferences();
      });
    };
    reader.readAsArrayBuffer(file);
  }

  function handleWritingPolicyConflictDecision(event) {
    var rowNumber = Number(event.target.getAttribute("data-writing-policy-conflict-row"));
    var preview = state.writingPolicyImportPreview;
    if (!rowNumber || !preview) {
      return;
    }
    preview.conflicts.forEach(function (item) {
      if (item.rowNumber === rowNumber) {
        item.decision = helpers.normalizeWritingPolicyConflictDecision ?
          helpers.normalizeWritingPolicyConflictDecision(event.target.value) : "keep_existing";
        event.target.value = item.decision;
      }
    });
  }

  function applyWritingPolicyImport() {
    var preview = state.writingPolicyImportPreview;
    var acceptedConflictRows;
    if (!preview || !preview.previewToken || state.writingPolicyImportBusy) {
      return;
    }
    acceptedConflictRows = helpers.buildWritingPolicyImportApplyRequest ?
      helpers.buildWritingPolicyImportApplyRequest(preview).acceptedConflictRows : [];
    setWritingPolicyImportBusy(true);
    state.writingPolicyImportStep = "apply";
    renderWritingPolicyImportStep();
    byId("writing-policy-import-status").textContent = "正在应用导入结果...";
    request("/writing-policies/imports/apply", {
      previewToken: preview.previewToken,
      acceptedConflictRows: acceptedConflictRows
    }).then(function (body) {
      var result = body.data || {};
      state.writingPolicyImportPreview = null;
      byId("writing-policy-import-preview-panel").hidden = true;
      byId("writing-policy-import-status").textContent = "导入完成：新增 " +
        String(result.createdCount || 0) + " 条，更新 " + String(result.updatedCount || 0) + " 条。";
      setWritingPolicyImportBusy(false);
      loadWritingPolicySummary();
    }).catch(function (error) {
      setWritingPolicyImportBusy(false);
      if (helpers.isWritingPolicyPreviewExpired && helpers.isWritingPolicyPreviewExpired(error)) {
        resetWritingPolicyImport("导入预览已过期，请重新选择文件。");
        return;
      }
      byId("writing-policy-import-status").textContent = "应用失败：" + describeFetchError(error);
      renderWritingPolicyImportPreview();
    });
  }

  function downloadWritingPolicyFile(path, fileName) {
    var objectUrl = "";
    var anchor = null;
    function cleanup() {
      if (anchor) {
        anchor.href = "";
      }
      if (anchor && anchor.parentNode) {
        anchor.parentNode.removeChild(anchor);
      }
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    }
    return fetch(ADAPTER_BASE_URL + path).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return response.blob();
    }).then(function (blob) {
      objectUrl = URL.createObjectURL(blob);
      anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = fileName;
      anchor.hidden = true;
      document.body.appendChild(anchor);
      anchor.click();
      return true;
    }).then(function (result) {
      cleanup();
      return result;
    }, function (error) {
      cleanup();
      throw error;
    });
  }

  function runWritingPolicyDownload(path, fileName, successMessage) {
    var statusNode = state.writingPolicyView === "import" ? byId("writing-policy-import-status") : null;
    if (statusNode) {
      statusNode.textContent = "正在准备下载...";
    } else {
      setStatus("正在准备下载...");
    }
    downloadWritingPolicyFile(path, fileName).then(function () {
      if (statusNode) {
        statusNode.textContent = successMessage;
      } else {
        setStatus(successMessage);
      }
    }).catch(function (error) {
      if (statusNode) {
        statusNode.textContent = "下载失败：" + describeFetchError(error);
      } else {
        setStatus("下载失败：" + describeFetchError(error));
      }
    });
  }

  function handleWritingPolicyMenuAction(event) {
    var target = event.target;
    var action;
    while (target && target !== byId("writing-policy-overflow-menu") && !target.getAttribute("data-writing-policy-menu-action")) {
      target = target.parentNode;
    }
    action = target && target.getAttribute("data-writing-policy-menu-action");
    if (!action) {
      return;
    }
    byId("writing-policy-overflow-menu").open = false;
    if (action === "import") {
      openWritingPolicyImport();
    } else if (action === "export") {
      runWritingPolicyDownload(
        "/writing-policies/export.csv?scope=" + encodeURIComponent(state.writingPolicyScope),
        "writing-policies-export.csv",
        "当前范围已导出。"
      );
    } else if (action === "backup") {
      runWritingPolicyDownload(
        "/writing-policies/backup",
        "writing-policies-backup.db",
        "写作规范库备份已下载。"
      );
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
    state.writingPolicyAudit = data && data.writingPolicyAudit ? data.writingPolicyAudit : null;
    renderWritingPolicyUsage(data && data.writingPolicyUsage, "word.document_review");
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
          setDocumentReviewJobId("");
          state.documentReviewPollStartedAt = 0;
          stopWaiting();
          completeDocumentReview(job.result || {}, body.traceId || job.traceId || jobId);
          return;
        }
        if (job.status === "failed") {
          clearDocumentReviewActiveJob(jobId);
          setDocumentReviewJobId("");
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
        setDocumentReviewJobId("");
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
    setDocumentReviewJobId(active.jobId);
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
      setSettingsStatus("诊断信息已刷新。");
    });
  }

  function handleDiagnosticsDisclosureToggle(event) {
    if (event.currentTarget.open) {
      refreshDiagnostics();
    }
  }

  function copyDiagnostics() {
    var text = state.diagnosticsCopyText || byId("last-task-diagnostics-output").textContent || "";
    if (!text.trim()) {
      setSettingsStatus("暂无可复制的诊断信息。");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        setSettingsStatus("诊断信息已复制。");
      }).catch(function () {
        fallbackCopy(text, setSettingsStatus);
      });
    }
    fallbackCopy(text, setSettingsStatus);
  }

  function applyDocumentReviewPrompt(documentType) {
    var nextType = DOCUMENT_REVIEW_PROMPTS[documentType] ? documentType : "technical_solution";
    state.technicalDocumentType = nextType;
    state.technicalReviewPrompt = DOCUMENT_REVIEW_PROMPTS[nextType];
    byId("technical-review-prompt").value = state.technicalReviewPrompt;
  }

  function fallbackCopy(text, feedback) {
    var textarea = document.createElement("textarea");
    var report = typeof feedback === "function" ? feedback : setStatus;
    textarea.value = text;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      report("结果已复制。");
    } catch (error) {
      report("复制失败，请手动选择结果文本。");
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
        state.latestDocumentPayload.writingPolicyScene = "auto";
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
      setDocumentReviewJobId(clientJobId);
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
            setDocumentReviewJobId("");
            stopWaiting();
            setStatus("文档审查失败：adapter 未返回后台任务编号。");
            setResult("adapter 未返回后台任务编号，请重试或查看最近一次任务诊断。");
            return;
          }
          setDocumentReviewJobId(jobId);
          state.documentReviewPollStartedAt = startedAt;
          state.documentReviewPollErrorCount = 0;
          saveDocumentReviewActiveJob({
            jobId: jobId,
            traceId: body.traceId || job.traceId || "",
            startedAt: startedAt
          });
          if (job.status === "completed") {
            clearDocumentReviewActiveJob(jobId);
            setDocumentReviewJobId("");
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
            setDocumentReviewJobId("");
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
        state.latestDocumentPayload.writingPolicyScene = getWritingPolicyScene();
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
          state.rewriteResult = setSmartWriteResult(body.data, "word.smart_write");
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
      writingPolicyScene: "auto",
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
        state.rewriteResult = setSmartWriteResult(body.data, "word.smart_imitation");
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

  function getWritingPolicyScene() {
    var select = byId("writing-policy-scene");
    var scene = helpers.normalizeWritingPolicyScene
      ? helpers.normalizeWritingPolicyScene(select && select.value)
      : "auto";
    state.writingPolicyScene = scene;
    return scene;
  }

  function saveWritingPolicyScene(value) {
    var scene = helpers.normalizeWritingPolicyScene
      ? helpers.normalizeWritingPolicyScene(value)
      : "auto";
    var key = helpers.writingPolicySceneStorageKey
      ? helpers.writingPolicySceneStorageKey("word.smart_write")
      : "ai-wps:writing-policy-scene:word.smart_write";
    state.writingPolicyScene = scene;
    try {
      if (window.localStorage) {
        window.localStorage.setItem(key, scene);
      }
    } catch (error) {
      // Some WPS WebView modes disable localStorage; the in-memory choice still works.
    }
  }

  function restoreWritingPolicyScene() {
    var select = byId("writing-policy-scene");
    var key = helpers.writingPolicySceneStorageKey
      ? helpers.writingPolicySceneStorageKey("word.smart_write")
      : "ai-wps:writing-policy-scene:word.smart_write";
    var scene = "auto";
    try {
      scene = window.localStorage ? window.localStorage.getItem(key) : "auto";
    } catch (error) {
      scene = "auto";
    }
    scene = helpers.normalizeWritingPolicyScene
      ? helpers.normalizeWritingPolicyScene(scene)
      : "auto";
    state.writingPolicyScene = scene;
    if (select) {
      select.value = scene;
    }
  }

  function applyPreview() {
    if (state.pendingApplyAction === "rewrite") {
      applyRewrite();
    }
  }

  function runPrimaryAction() {
    if (state.workflowProfileMutationBusy) {
      setStatus("工作流配置正在更新，请稍后再提交任务。");
      return;
    }
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
    var workflowHelpButton = byId("workflow-help-button");
    var workflowHelpPopover = byId("workflow-help-popover");
    var workflowHelpHeading = document.querySelector(".workflow-settings-heading");
    byId("btn-open-settings").addEventListener("click", function () {
      toggleSettingsShortcut();
    });
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
    byId("writing-policy-scene").addEventListener("change", function (event) {
      saveWritingPolicyScene(event.target.value);
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
    byId("btn-cancel-provider-url").addEventListener("click", closeProviderUrlEditor);
    byId("btn-edit-provider-url").addEventListener("click", function () {
      state.providerUrlEditorOpen = true;
      byId("provider-url-details").open = true;
      byId("provider-base-url").focus();
      syncSettingsRefreshController();
    });
    byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
    byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
    byId("diagnostics-disclosure").addEventListener("toggle", handleDiagnosticsDisclosureToggle);
    byId("workflow-profile-select").addEventListener("change", handleWorkflowProfileSelectionChange);
    byId("workflow-task-tabs").addEventListener("click", handleWorkflowTaskTabClick);
    byId("workflow-task-tabs").addEventListener("keydown", handleWorkflowTaskTabKeydown);
    workflowHelpButton.addEventListener("click", function () {
      var pinned = !state.workflowHelpPinned;
      setWorkflowHelpOpen(pinned, pinned);
    });
    workflowHelpButton.addEventListener("mouseenter", function () {
      setWorkflowHelpOpen(true);
    });
    workflowHelpButton.addEventListener("focusin", function () {
      setWorkflowHelpOpen(true);
    });
    workflowHelpButton.addEventListener("mouseleave", function () {
      if (!state.workflowHelpPinned) {
        setWorkflowHelpOpen(false, false);
      }
    });
    workflowHelpButton.addEventListener("focusout", function (event) {
      if (!state.workflowHelpPinned && !workflowHelpButton.contains(event.relatedTarget)) {
        setWorkflowHelpOpen(false, false);
      }
    });
    document.addEventListener("click", function (event) {
      if (!workflowHelpHeading.contains(event.target) && !workflowHelpPopover.contains(event.target)) {
        setWorkflowHelpOpen(false, false);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !workflowHelpPopover.hidden) {
        setWorkflowHelpOpen(false, false);
        workflowHelpButton.focus();
      }
    });
    document.addEventListener("visibilitychange", syncSettingsRefreshController);
    byId("workflow-profile-manager").addEventListener("click", handleWorkflowProfileManagerAction);
    byId("workflow-profile-manager").addEventListener("input", markWorkflowProfileEditorDirty);
    byId("workflow-profile-manager").addEventListener("change", markWorkflowProfileEditorDirty);
    byId("btn-open-writing-policy-manager").addEventListener("click", openWritingPolicyPresetView);
    byId("btn-writing-policy-preset-back").addEventListener("click", function () {
      setWritingPolicyView("home");
    });
    byId("btn-writing-policy-open-organization").addEventListener("click", openWritingPolicyScopeView);
    byId("btn-retry-writing-policy-summary").addEventListener("click", loadWritingPolicySummary);
    byId("btn-writing-policy-scope-back").addEventListener("click", function () {
      setWritingPolicyView("home");
    });
    byId("writing-policy-scope-list").addEventListener("click", handleWritingPolicyScopeClick);
    byId("btn-writing-policy-list-back").addEventListener("click", function () {
      setWritingPolicyView("scope");
    });
    byId("writing-policy-type-switch").addEventListener("click", handleWritingPolicyTypeClick);
    byId("writing-policy-type-switch").addEventListener("keydown", handleWritingPolicyTypeKeydown);
    byId("writing-policy-search-input").addEventListener("input", function (event) {
      scheduleWritingPolicySearch(event.target.value);
    });
    byId("btn-writing-policy-add").addEventListener("click", function () {
      if (!state.writingPolicyListError && !state.writingPolicyMutationBusy) {
        openWritingPolicyEditor(null);
      }
    });
    byId("writing-policy-item-list").addEventListener("click", handleWritingPolicyListClick);
    byId("btn-retry-writing-policy-list").addEventListener("click", loadWritingPolicyItems);
    byId("btn-writing-policy-editor-back").addEventListener("click", closeWritingPolicyEditor);
    byId("btn-cancel-writing-policy-editor").addEventListener("click", closeWritingPolicyEditor);
    byId("btn-save-writing-policy-item").addEventListener("click", saveWritingPolicyItem);
    byId("btn-writing-policy-delete").addEventListener("click", deleteWritingPolicyItem);
    byId("writing-policy-editor-view").addEventListener("input", function () {
      if (state.writingPolicyEditor) {
        state.writingPolicyEditorDirty = true;
      }
    });
    byId("writing-policy-editor-view").addEventListener("change", function () {
      if (state.writingPolicyEditor) {
        state.writingPolicyEditorDirty = true;
      }
    });
    byId("btn-writing-policy-import-entry").addEventListener("click", openWritingPolicyImport);
    byId("writing-policy-overflow-menu").addEventListener("click", handleWritingPolicyMenuAction);
    byId("btn-writing-policy-import-back").addEventListener("click", closeWritingPolicyImport);
    byId("writing-policy-import-file").addEventListener("change", handleWritingPolicyImportFileChange);
    byId("btn-preview-writing-policy-import").addEventListener("click", previewWritingPolicyImport);
    byId("writing-policy-import-conflict-list").addEventListener("change", handleWritingPolicyConflictDecision);
    byId("btn-apply-writing-policy-import").addEventListener("click", applyWritingPolicyImport);
    byId("btn-writing-policy-download-csv-template").addEventListener("click", function () {
      runWritingPolicyDownload(
        "/writing-policies/import-template.csv",
        "writing-policies-import-template.csv",
        "CSV 导入模板已下载。"
      );
    });
    byId("btn-writing-policy-download-xlsx-template").addEventListener("click", function () {
      runWritingPolicyDownload(
        "/writing-policies/import-template.xlsx",
        "writing-policies-import-template.xlsx",
        "XLSX 导入模板已下载。"
      );
    });
    byId("btn-writing-policy-export-scope").addEventListener("click", function () {
      runWritingPolicyDownload(
        "/writing-policies/export.csv?scope=" + encodeURIComponent(state.writingPolicyScope),
        "writing-policies-export.csv",
        "当前范围已导出。"
      );
    });
    byId("btn-writing-policy-download-backup").addEventListener("click", function () {
      runWritingPolicyDownload(
        "/writing-policies/backup",
        "writing-policies-backup.db",
        "写作规范库备份已下载。"
      );
    });
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
  renderWritingPolicyManagerView();
  renderWritingPolicySummary();
  restoreWritingPolicyScene();
  state.settingsRefreshController = helpers.createSettingsRefreshController({
    intervalMs: 30000,
    refresh: function () {
      return refreshConfig({ silent: true });
    }
  });
  switchMode(getInitialMode());
  if (!state.settingsRefreshController.isRunning()) {
    refreshConfig({ silent: false });
  }
  startScopeWatcher();
})();
