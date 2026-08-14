(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.23.1-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var DOCUMENT_REVIEW_POLL_INTERVAL_MS = 3000;
  var DOCUMENT_REVIEW_POLL_ERROR_RETRY_DELAY_MS = 15000;
  var DOCUMENT_REVIEW_POLL_SLOW_RETRY_DELAY_MS = 30000;
  var DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS = 10000;
  var WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS = 15000;
  var WRITING_POLICY_LIST_PAGE_SIZE = 50;
  var SETTINGS_REFRESH_REQUEST_TIMEOUT_MS = 8000;
  var DOCUMENT_REVIEW_POLL_MAX_ERRORS = 240;
  var DOCUMENT_REVIEW_POLL_MAX_WAIT_MS = 60 * 60 * 1000;
  var DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY = "ai-wps-document-review-active-job-v1";
  var FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY = "ai-wps-full-document-review-active-job-v1";
  var DETERMINISTIC_FORMAT_REVIEW_POLL_INTERVAL_MS = 1000;
  var DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS = 10000;
  var WRITING_ACTIVE_JOB_STORAGE_KEY = "ai-wps-writing-active-job-v1";
  var WRITING_POLL_INTERVAL_MS = 3000;
  var WRITING_POLL_RETRY_DELAY_MS = 15000;
  var WRITING_POLL_REQUEST_TIMEOUT_MS = 10000;
  var DOCUMENT_REVIEW_PHASE_TEXT = {
    queued: "排队等待",
    preparing: "准备审查内容",
    extracting: "抽取审查内容",
    confirming: "等待大型文档确认",
    chunking: "处理审查分片",
    provider_processing: "模型后台处理",
    retrying: "受控重试中",
    splitting: "拆分饱和分片",
    parsing: "解析并整理审查结果",
    aggregating: "汇总分片结果",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消"
  };
  var FORMAT_REVIEW_EXTRACTION_OPTIONS = {
    maxParagraphs: 80,
    maxParagraphTextLength: 800,
    maxPlainTextLength: 12000,
    preferSelectionTextParagraphs: true,
    avoidFullTextRead: true,
    avoidFallbackTextRead: true
  };
  var DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS = {
    maxPlainTextLength: 130000,
    preferSelectionTextParagraphs: false,
    preferSelectionRangeParagraphs: true,
    avoidFullTextRead: true,
    avoidFallbackTextRead: true,
    includeCharacterFormatSegments: true,
    maxFormatSegments: 2048
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
    { scope: "global", label: "组织规范", caption: "管理组织术语、文体规则和去模板化规则" },
    { scope: "word.smart_write", label: "智能编写补充", caption: "仅在智能编写中使用的文体规则" },
    { scope: "word.smart_imitation", label: "智能仿写补充", caption: "仅在智能仿写中使用的文体规则" },
    { scope: "word.document_review", label: "文档审查补充", caption: "仅在文档审查中检查的文体规则" }
  ];
  var WRITING_POLICY_RULE_TASK_TYPES = [
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review"
  ];
  var WRITING_POLICY_ITEM_TYPES = ["term", "style", "anti_template"];
  var WRITING_POLICY_RULE_SCENE_IDS = [
    "yangqi",
    "cybersecurity",
    "official"
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
    documentReviewStopWaiting: null,
    fullDocumentReviewEnabled: false,
    deterministicFormatReviewEnabled: false,
    deterministicFormatReviewJobId: "",
    deterministicFormatReviewSnapshot: null,
    deterministicFormatReviewReport: null,
    deterministicFormatReviewIssueJobId: "",
    deterministicFormatReviewIssueCursorHistory: [],
    deterministicFormatReviewIssueFilters: {
      rule: "",
      severity: "",
      dataStatus: "",
      sort: "source"
    },
    deterministicFormatReviewDocumentIdentity: null,
    fullDocumentReviewJobId: "",
    fullDocumentReviewPollErrorCount: 0,
    fullDocumentReviewPreparing: false,
    fullDocumentReviewCancelRequested: false,
    fullDocumentReviewIssueJobId: "",
    fullDocumentReviewIssueReport: null,
    fullDocumentReviewIssueCursorHistory: [],
    fullDocumentReviewIssueFilters: {
      severity: "",
      category: "",
      location: "",
      status: "",
      sort: "source"
    },
    writingJobId: "",
    writingJobTaskType: "",
    writingJobMode: "",
    writingJobStartedAt: 0,
    writingJobPollErrorCount: 0,
    latestDocumentPayload: null,
    latestSelectionMode: "document",
    providerName: "未检测",
    providerBaseUrl: "",
    providerAuthSource: "none",
    adapterHealthStatus: "unknown",
    configurationMutationsAllowed: true,
    modelTasksAllowed: true,
    writingPolicyMutationsAllowed: true,
    taskApiKeys: {},
    workflowProfiles: {},
    workflowProfileSelections: {},
    workflowProfileRequestSequence: {},
    workflowProfileMutationBusy: false,
    workflowProfileActivationTimer: null,
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
    writingPolicyItemTotal: 0,
    writingPolicyItemOffset: 0,
    writingPolicyPresetPacks: [],
    writingPolicyPresetPack: null,
    writingPolicyPresetItems: [],
    writingPolicyPresetItemTotal: 0,
    writingPolicyPresetItemOffset: 0,
    writingPolicyPresetError: "",
    writingPolicyPresetLoadSequence: 0,
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
    writingPolicyScene: "auto",
    writingPolicyAudit: null,
    currentMode: "smartWrite",
    lastTaskMode: "smartWrite",
    modelTaskBusy: false,
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
    return !window.confirm || window.confirm("当前模型配置尚未保存，确认放弃修改？");
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

  function buildWritingClientJobId(taskType) {
    return [
      taskType === "word.smart_imitation" ? "client-imitation" : "client-smart-write",
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 10)
    ].join("-");
  }

  function loadWritingActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(WRITING_ACTIVE_JOB_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveWritingActiveJob(job) {
    if (!job || !job.jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(WRITING_ACTIVE_JOB_STORAGE_KEY, JSON.stringify({
          jobId: job.jobId,
          taskType: job.taskType,
          mode: job.mode,
          traceId: job.traceId || "",
          startedAt: job.startedAt || Date.now(),
          frontendVersion: FRONTEND_BUILD_VERSION
        }));
      }
    } catch (error) {
      // Storage may be unavailable in some WPS WebView modes.
    }
  }

  function clearWritingActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      active = loadWritingActiveJob();
      if (jobId && active && active.jobId && active.jobId !== jobId) {
        return;
      }
      window.localStorage.removeItem(WRITING_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Storage cleanup must not block result rendering.
    }
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

  function loadFullDocumentReviewActiveJob() {
    var raw;
    try {
      raw = window.localStorage && window.localStorage.getItem(
        FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY
      );
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function saveFullDocumentReviewActiveJob(jobId) {
    if (!jobId) {
      return;
    }
    try {
      if (window.localStorage) {
        window.localStorage.setItem(
          FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY,
          JSON.stringify({
            jobId: jobId,
            startedAt: Date.now(),
            frontendVersion: FRONTEND_BUILD_VERSION
          })
        );
      }
    } catch (error) {
      // Storage may be unavailable; in-memory polling remains active.
    }
  }

  function clearFullDocumentReviewActiveJob(jobId) {
    var active;
    try {
      if (!window.localStorage) {
        return;
      }
      active = loadFullDocumentReviewActiveJob();
      if (jobId && active && active.jobId && active.jobId !== jobId) {
        return;
      }
      window.localStorage.removeItem(FULL_DOCUMENT_REVIEW_ACTIVE_JOB_STORAGE_KEY);
    } catch (error) {
      // Storage cleanup must not block report rendering.
    }
  }

  function setProviderLine(providerName) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "模型接口",
      "enterprise-dify-workflow": "工作流平台",
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
    state.fullDocumentReviewEnabled = Boolean(
      configData.features && configData.features.fullDocumentReviewEnabled
    );
    state.deterministicFormatReviewEnabled = Boolean(
      configData.features && configData.features.deterministicFormatReviewEnabled
    );
    renderWorkflowProfileManager();
    renderWorkflowProfileStrip();
    renderFullDocumentReviewEntry();
    renderDeterministicFormatReviewEntry();
    if (
      state.fullDocumentReviewEnabled &&
      state.currentMode === "documentReview" &&
      !state.fullDocumentReviewJobId
    ) {
      resumeFullDocumentReviewActiveJob();
    }
  }

  function getFullDocumentReviewReadiness() {
    var data = getWorkflowProfileData("word.document_review");
    var active = data.profiles.filter(function (profile) {
      return profile.id === data.activeProfileId;
    })[0];
    if (!active) {
      return { fullDocumentReviewReady: false, label: "请先启用文档审查模型配置。" };
    }
    return {
      fullDocumentReviewReady: Boolean(active.fullDocumentReviewReady),
      label: active.fullDocumentReviewReadiness && active.fullDocumentReviewReadiness.label ||
        "当前配置尚未满足全篇审查要求。"
    };
  }

  function renderFullDocumentReviewEntry() {
    var entry = byId("full-document-review-entry");
    var button = byId("btn-run-full-document-review");
    var readinessNode = byId("full-document-review-readiness");
    var readiness;
    if (!entry || !button || !readinessNode) {
      return;
    }
    entry.hidden = !state.fullDocumentReviewEnabled;
    if (!state.fullDocumentReviewEnabled) {
      return;
    }
    readiness = getFullDocumentReviewReadiness();
    readinessNode.textContent = readiness.label;
    button.disabled = !readiness.fullDocumentReviewReady ||
      Boolean(state.fullDocumentReviewJobId || state.documentReviewJobId);
  }

  function renderDeterministicFormatReviewEntry() {
    var entry = byId("deterministic-format-review-entry");
    var button = byId("btn-run-deterministic-format-review");
    var readinessNode = byId("deterministic-format-review-readiness");
    if (!entry || !button || !readinessNode) {
      return;
    }
    entry.hidden = !state.deterministicFormatReviewEnabled;
    button.disabled = !state.deterministicFormatReviewEnabled ||
      Boolean(state.deterministicFormatReviewJobId) || state.modelTaskBusy;
    readinessNode.textContent = state.deterministicFormatReviewEnabled
      ? "功能开关已开启，可提交只读格式审查任务。"
      : "当前功能尚未启用。";
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
    setNodeTextIfChanged(byId("scope-line"), text);
    setNodeTextIfChanged(byId("settings-scope-line"), text);
  }

  function setHealthBadge(mode, text) {
    var node = byId("health-indicator");
    setNodeClassNameIfChanged(node, "badge " + mode);
    setNodeTextIfChanged(node, text);
  }

  function applyAdapterHealthState(data, connected) {
    var healthState = helpers.normalizeAdapterHealth(data, connected);
    state.adapterHealthStatus = healthState.status;
    state.configurationMutationsAllowed = healthState.configurationMutationsAllowed;
    state.modelTasksAllowed = healthState.modelTasksAllowed;
    state.writingPolicyMutationsAllowed = healthState.writingPolicyMutationsAllowed;
    setHealthBadge(healthState.badgeClass, healthState.badgeLabel);
    if (typeof renderRecoveryActions === "function") {
      renderRecoveryActions(data || {}, healthState.status === "recovery");
    }
    if (healthState.status === "recovery") {
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(false);
      setSettingsStatus(healthState.summary);
    }
    return healthState;
  }

  function renderRecoveryActions(data, visible) {
    var card = byId("recovery-actions-card");
    var subsystemLine = byId("recovery-subsystem-status");
    var backupLine = byId("recovery-backup-status");
    var subsystems = data && data.subsystems || {};
    var labels = {
      modelConfigurations: "模型配置",
      taskRoutes: "任务路由",
      writingPolicies: "写作规范"
    };
    var failures = Object.keys(labels).filter(function (name) {
      return subsystems[name] && subsystems[name].status !== "ready";
    }).map(function (name) {
      var item = subsystems[name];
      return labels[name] + "（" + (item.stage || item.errorCode || "状态异常") + "）";
    });
    var backup = data && data.backupStatus || {};
    if (!card) {
      return;
    }
    card.hidden = !visible;
    if (!visible) {
      return;
    }
    setNodeTextIfChanged(
      subsystemLine,
      failures.length ? "故障子系统：" + failures.join("、") : "核心运行数据需要恢复。"
    );
    setNodeTextIfChanged(
      backupLine,
      backup.latestValid && backup.latestValid.snapshotId
        ? "最近有效备份：" + backup.latestValid.snapshotId
        : (backup.latestVerified && backup.latestVerified.snapshotId
          ? "无有效备份；最近只读备份不可恢复：" + backup.latestVerified.snapshotId
          : "尚无有效备份")
    );
  }

  function createRecoveryBackup() {
    var button = byId("btn-recovery-backup");
    button.disabled = true;
    setSettingsStatus("正在创建只读整体备份...");
    return request("/recovery/backups", {}).then(function (response) {
      var data = response.data || {};
      renderRecoveryActions({
        status: "recovery",
        subsystems: {},
        backupStatus: data.backupStatus || {}
      }, true);
      setSettingsStatus("只读备份已创建：" + (data.snapshotId || "已完成"));
    }).catch(function (error) {
      setSettingsStatus(error && error.message || "只读备份创建失败，请重试。");
    }).then(function () {
      button.removeAttribute("disabled");
    });
  }

  function exportRecoveryDiagnostics() {
    setSettingsStatus("正在生成脱敏诊断...");
    return request("/recovery/diagnostics", null).then(function (response) {
      var text = JSON.stringify(response.data || {}, null, 2);
      var blob = new Blob([text], { type: "application/json;charset=utf-8" });
      var objectUrl = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = objectUrl;
      link.download = "ai-wps-recovery-diagnostics.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
      setSettingsStatus("脱敏诊断已导出。");
    }).catch(function (error) {
      setSettingsStatus(error && error.message || "脱敏诊断导出失败，请重试。");
    });
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
    setModelTaskBusy(Boolean(state.documentReviewJobId));
    if (!state.documentReviewJobId) {
      setDocumentReviewCancelVisible(false);
    }
    renderWorkflowProfileStrip();
  }

  function setDocumentReviewCancelVisible(visible, disabled) {
    var button = byId("btn-cancel-document-review-job");
    if (!button) {
      return;
    }
    button.hidden = !visible;
    button.disabled = Boolean(disabled);
  }

  function setInterruptedRetryVisible(visible) {
    var button = byId("btn-resubmit-interrupted-job");
    if (button) {
      button.hidden = !visible;
    }
  }

  function resetDocumentReviewState() {
    stopDocumentReviewWaitFeedback();
    state.documentReviewData = null;
    state.documentReviewIssueStatus = {};
    state.documentReviewRecordPreviewVisible = false;
    clearWritingPolicyUsage();
    setDocumentReviewJobId("");
    state.documentReviewPollStartedAt = 0;
    state.documentReviewPollErrorCount = 0;
    setReviewRecordActionsVisible(false);
  }

  function stopDocumentReviewWaitFeedback(fallback) {
    var stopWaiting = state.documentReviewStopWaiting || fallback;
    state.documentReviewStopWaiting = null;
    if (typeof stopWaiting === "function") {
      stopWaiting();
    }
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
    syncScopeWatcher();
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
    var writingPolicyMode;
    var returnTitle;

    setInterruptedRetryVisible(false);
    if (state.writingJobId && state.writingJobMode !== requestedMode) {
      setWritingJob("", "", "");
    }
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
    renderFullDocumentReviewEntry();
    renderDeterministicFormatReviewEntry();
    writingPolicyMode = ["smartWrite", "smartImitation", "documentReview"].indexOf(state.currentMode) >= 0;
    byId("writing-policy-scene-block").hidden = !writingPolicyMode;
    if (writingPolicyMode) {
      restoreWritingPolicyScene();
    }
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
      if (!resumeFullDocumentReviewActiveJob()) {
        resumeDocumentReviewActiveJob();
      }
    } else if (state.currentMode === "smartWrite" || state.currentMode === "smartImitation") {
      resumeWritingActiveJob();
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
    } else if (selectionMode === "selection" && options.preferSelectionRangeParagraphs &&
        helpers.collectParagraphsFromSelectionSources) {
      paragraphs = helpers.collectParagraphsFromSelectionSources(selectionSources, selectedText, options);
      plainText = selectedText || paragraphs.map(function (item) { return item.text; }).join("\n");
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

  function getWordSelectionEventSource() {
    var sources = [
      window.wps && window.wps.ApiEvent,
      window.Application && window.Application.ApiEvent
    ];
    var index;
    for (index = 0; index < sources.length; index += 1) {
      if (sources[index] && typeof sources[index].AddApiEventListener === "function") {
        return sources[index];
      }
    }
    return null;
  }

  function isScopeWatcherEligible() {
    var homeView = byId("home-view");
    return Boolean(
      homeView &&
      homeView.classList.contains("active") &&
      document.visibilityState !== "hidden" &&
      !state.modelTaskBusy
    );
  }

  function syncScopeWatcher() {
    if (!state.scopeWatcher) {
      return;
    }
    if (isScopeWatcherEligible()) {
      state.scopeWatcher.start();
    } else if (state.scopeWatcher.isRunning()) {
      state.scopeWatcher.stop();
    }
  }

  function setModelTaskBusy(busy) {
    var button = byId("btn-run-primary");
    state.modelTaskBusy = Boolean(busy);
    if (button) {
      button.disabled = state.modelTaskBusy;
      button.setAttribute("aria-busy", state.modelTaskBusy ? "true" : "false");
    }
    renderDeterministicFormatReviewEntry();
    syncScopeWatcher();
  }

  function request(path, payload, requestOptions) {
    var timeoutMs = requestOptions && requestOptions.timeoutMs;
    var requestMethod = requestOptions && requestOptions.method;
    var controller = null;
    var timeoutId = null;
    var options = {
      method: requestMethod || (payload ? "POST" : "GET")
    };
    var normalizedMethod = String(options.method || "GET").toUpperCase();
    var mutating = ["POST", "PUT", "PATCH", "DELETE"].indexOf(normalizedMethod) >= 0;
    var blockedCode = "";

    if (mutating && path.indexOf("/provider/") === 0 && !state.configurationMutationsAllowed) {
      blockedCode = "ADAPTER_RECOVERY_MODE";
    } else if (
      mutating &&
      path.indexOf("/writing-policies/") === 0 &&
      !state.writingPolicyMutationsAllowed
    ) {
      blockedCode = state.adapterHealthStatus === "recovery"
        ? "ADAPTER_RECOVERY_MODE"
        : "WRITING_POLICY_READ_ONLY";
    } else if (
      normalizedMethod === "POST" &&
      ["/word/", "/excel/", "/ppt/"].some(function (prefix) {
        return path.indexOf(prefix) === 0;
      }) &&
      !state.modelTasksAllowed
    ) {
      blockedCode = "ADAPTER_RECOVERY_MODE";
    }
    if (blockedCode) {
      var blockedError = new Error(
        blockedCode === "WRITING_POLICY_READ_ONLY"
          ? "写作规范增强能力当前处于降级状态，仅允许只读查看。"
          : "Adapter 当前处于恢复模式，配置变更和模型任务已被安全阻止。"
      );
      blockedError.adapterCode = blockedCode;
      return Promise.reject(blockedError);
    }

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

  function isFullDocumentReviewPermanentPollError(error) {
    var status = Number(error && error.httpStatus);
    return Boolean(error) && (
      (status >= 400 && status < 500) ||
      error.adapterCode === "FULL_DOCUMENT_REVIEW_JOB_NOT_FOUND"
    );
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
    var longTasks = routes.longTaskCoordinator || {};
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

    if (typeof longTasks.maxRunning === "number") {
      lines.push("");
      lines.push("## 共享长任务协调器");
      lines.push("- 运行中：" + (longTasks.runningCount || 0) + "/" + longTasks.maxRunning);
      lines.push("- 排队中：" + (longTasks.queuedCount || 0) + "/" + longTasks.maxQueued);
      lines.push("- 终态保留：" + (longTasks.terminalCount || 0) + "/" + longTasks.maxTerminalJobs);
      lines.push("- 终态保留时长：" + (longTasks.terminalTtlSeconds || 0) + " 秒");
      lines.push("- 取消数：" + (longTasks.cancelledCount || 0));
      lines.push("- 拒绝数：" + (longTasks.rejectedCount || 0));
      lines.push("- 超时数：" + (longTasks.timedOutCount || 0));
      (longTasks.recentTerminalJobs || []).forEach(function (job) {
        lines.push(
          "- 最近任务 " + (job.jobId || "未记录") +
          "：" + (job.status || "未记录") +
          "，耗时 " + (job.elapsedSeconds || 0) + " 秒" +
          (job.errorCode ? "，错误码 " + job.errorCode : "")
        );
      });
    }

    if (debug.request) {
      lines.push("");
      lines.push("## 请求摘要");
      lines.push("- body 字段：" + (debug.request.bodyKeys || []).join(", "));
      lines.push("- inputs 字段：" + (debug.request.inputsKeys || []).join(", "));
      lines.push("- query 长度：" + (debug.request.queryLength || 0));
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
      var healthState;
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      healthData = health.data || {};
      healthConnected = true;
      healthState = applyAdapterHealthState(healthData, true);
      setProviderLine(healthData.providerType || "未检测");
      if (healthState.status === "recovery") {
        return null;
      }
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
          throw new Error("模型配置读取不完整");
        }
        for (profileIndex = 0; profileIndex < profileResults.length; profileIndex += 1) {
          if (!profileResults[profileIndex]) {
            throw new Error("模型配置读取失败");
          }
        }
        state.modelInterfaceDetectable = true;
        renderModelInterfaceState(state.modelInterfaceDetectable);
        if (!state.configRefreshActiveSilent) {
          setSettingsStatus(state.adapterHealthStatus === "degraded"
            ? "增强能力降级，核心功能可用。"
            : "就绪");
        }
        return results;
      });
    }).catch(function (error) {
      if (state.configRefreshRequestId !== requestId) {
        return null;
      }
      if (!healthConnected) {
        applyAdapterHealthState(null, false);
      }
      state.modelInterfaceDetectable = false;
      renderModelInterfaceState(state.modelInterfaceDetectable);
      setSettingsStatus("配置刷新失败：" + describeFetchError(error));
      return null;
    });

    refreshPromise = refreshOperation.then(releaseRefresh, function (error) {
      if (state.configRefreshRequestId === requestId) {
        if (!healthConnected) {
          applyAdapterHealthState(null, false);
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
    return Boolean(state.documentReviewJobId || state.fullDocumentReviewJobId || state.workflowProfileMutationBusy);
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
      return { valid: false, message: "请填写模型配置名称。" };
    }
    if (requireApiKey && !String(draft.apiKey || "").trim()) {
      return { valid: false, message: "请填写模型配置 API Key。" };
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
      "/provider/model-configurations?taskType=" + encodeURIComponent(taskType),
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
        renderFullDocumentReviewEntry();
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

  function syncWorkflowProfileSelectOptions(select, optionModels) {
    var options = select.options || select.children || [];
    var canReuseOptions = options.length === optionModels.length;
    var index;
    var option;
    var model;
    if (canReuseOptions) {
      for (index = 0; index < optionModels.length; index += 1) {
        if (!options[index] || String(options[index].value || "") !== optionModels[index].value) {
          canReuseOptions = false;
          break;
        }
      }
    }
    if (!canReuseOptions) {
      select.innerHTML = "";
      for (index = 0; index < optionModels.length; index += 1) {
        option = document.createElement("option");
        option.value = optionModels[index].value;
        select.appendChild(option);
      }
      options = select.options || select.children || [];
    }
    for (index = 0; index < optionModels.length; index += 1) {
      option = options[index];
      model = optionModels[index];
      if (option.textContent !== model.text) {
        option.textContent = model.text;
      }
      if (option.selected !== model.selected) {
        option.selected = model.selected;
      }
      if (option.disabled !== model.disabled) {
        option.disabled = model.disabled;
      }
    }
  }

  function renderWorkflowProfileStrip() {
    var strip = byId("workflow-profile-strip");
    var select = byId("workflow-profile-select");
    var current = byId("workflow-profile-current");
    var taskType = getCurrentWorkflowTaskType();
    var data;
    var selectedId;
    var availableProfiles;
    var optionModels = [];
    var interactionBlocked;
    if (!strip || !select || !current) {
      return;
    }
    strip.hidden = !taskType;
    if (!taskType) {
      return;
    }
    data = getWorkflowProfileData(taskType);
    availableProfiles = data.profiles.filter(function (profile) { return profile.complete; });
    selectedId = state.workflowProfileSelections[taskType] || data.activeProfileId || "";
    interactionBlocked = isWorkflowInteractionBlocked();
    if (!availableProfiles.length) {
      optionModels.push({
        value: "",
        text: data.loadError ? "配置读取失败" : "未配置",
        selected: true,
        disabled: false
      });
    } else {
      availableProfiles.forEach(function (profile) {
        var optionState = getWorkflowProfileOptionState(
          profile,
          data.activeProfileId,
          interactionBlocked
        );
        optionModels.push({
          value: profile.id,
          text: (profile.id === data.activeProfileId ? "✓ " : "") + profile.name + " · " +
            (profile.accessMethod === "direct_model" ? "模型直连" + (profile.modelName ? " · " + profile.modelName : "") : "工作流平台"),
          selected: profile.id === selectedId,
          disabled: optionState.disabled
        });
      });
    }
    syncWorkflowProfileSelectOptions(select, optionModels);
    if (select.disabled !== (interactionBlocked || !availableProfiles.length)) {
      select.disabled = interactionBlocked || !availableProfiles.length;
    }
    setNodeTextIfChanged(current, "当前配置：" + (
      helpers.getActiveWorkflowProfileName ? helpers.getActiveWorkflowProfileName(data) : "尚未配置"
    ));
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
    controls = manager.querySelectorAll("button, input, textarea, select");
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
      var validateButton = document.querySelector('[data-workflow-action="validate"]');
      if (validateButton) {
        validateButton.disabled = true;
      }
    }
  }

  function handleModelConfigurationEditorChange(event) {
    var editor = state.workflowProfileEditor;
    var methodInput;
    var nextMethod;
    var directFields;
    var index;
    markWorkflowProfileEditorDirty();
    if (!editor || !event.target || !event.target.hasAttribute("data-workflow-editor-method")) {
      return;
    }
    methodInput = event.target;
    nextMethod = methodInput.value;
    if (editor.currentAccessMethod && editor.currentAccessMethod !== nextMethod && window.confirm &&
        !window.confirm("切换接入方式会清空原方式的专属参数和 API Key，是否继续？")) {
      methodInput.value = editor.currentAccessMethod;
      return;
    }
    editor.currentAccessMethod = nextMethod;
    directFields = document.querySelectorAll(".model-direct-field");
    for (index = 0; index < directFields.length; index += 1) {
      directFields[index].hidden = nextMethod !== "direct_model";
    }
    if (editor.originalAccessMethod && editor.originalAccessMethod !== nextMethod) {
      ["[data-workflow-editor-key]", "[data-workflow-editor-key-confirm]",
        "[data-workflow-editor-model]", "[data-workflow-editor-temperature]",
        "[data-workflow-editor-max-output]"].forEach(function (selector) {
        var input = document.querySelector(selector);
        if (input) {
          input.value = "";
        }
      });
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
      var accessMethod = profile ? profile.accessMethod : "workflow_platform";
      var directHidden = accessMethod === "direct_model" ? "" : " hidden";
      rows.push('<section class="workflow-settings-subpage" aria-label="' +
        (editor.mode === "create" ? "新建模型配置" : "编辑模型配置") + '">');
      rows.push('<div class="workflow-subpage-head"><button type="button" class="ghost-action mini-button" data-workflow-action="editor-cancel"' + disabledAttribute + '>返回</button><div><h5>' +
        (editor.mode === "create" ? "新建" + definition.label + "模型配置" : "编辑" + escapeWorkflowText(profile.name)) +
        '</h5><span>' + definition.label + '</span></div></div>');
      rows.push('<div class="workflow-editor-fields">');
      rows.push('<label class="field"><span>配置名称</span><input type="text" data-workflow-editor-name maxlength="40" value="' +
        escapeWorkflowText(profile ? profile.name : "") + '"' + disabledAttribute + ' /></label>');
      rows.push('<label class="field"><span>接入方式</span><select data-workflow-editor-method' + disabledAttribute + '>' +
        '<option value="workflow_platform"' + (accessMethod === "workflow_platform" ? " selected" : "") + '>工作流平台</option>' +
        '<option value="direct_model"' + (accessMethod === "direct_model" ? " selected" : "") + '>模型直连</option></select></label>');
      rows.push('<label class="field"><span>服务地址</span><input type="text" data-workflow-editor-url placeholder="例如：http://1.1.1.1:1111/one-api/v1" value="' +
        escapeWorkflowText(profile ? profile.serviceBaseUrl : "") + '"' + disabledAttribute + ' /></label>');
      rows.push('<label class="field model-direct-field"' + directHidden + '><span>模型标识</span><input type="text" data-workflow-editor-model placeholder="例如：glm-5.2" value="' +
        escapeWorkflowText(profile ? profile.modelName : "") + '"' + disabledAttribute + ' /></label>');
      rows.push('<label class="field"><span>备注</span><textarea data-workflow-editor-note rows="3" maxlength="200" placeholder="选填"' + disabledAttribute + '>' +
        escapeWorkflowText(profile ? profile.note : "") + '</textarea></label>');
      rows.push('<section class="model-key-editor"><div class="model-key-status">API Key：' +
        (profile && profile.keyConfigured ? "已配置" : "未配置") + '</div>' +
        '<label class="field"><span>' + (profile && profile.keyConfigured ? "新 API Key（选填）" : "API Key（可稍后配置）") +
        '</span><input type="password" data-workflow-editor-key autocomplete="new-password"' + disabledAttribute + ' /></label>' +
        '<label class="field"><span>再次输入 API Key</span><input type="password" data-workflow-editor-key-confirm autocomplete="new-password"' + disabledAttribute + ' /></label></section>');
      rows.push('<details class="model-advanced-settings"><summary>高级配置</summary><div class="workflow-editor-fields">' +
        '<label class="field model-direct-field"' + directHidden + '><span>温度（选填）</span><input type="number" min="0" max="2" step="0.1" data-workflow-editor-temperature value="' +
        escapeWorkflowText(profile && profile.temperature !== null && typeof profile.temperature !== "undefined" ? profile.temperature : "") + '"' + disabledAttribute + ' /></label>' +
        '<label class="field model-direct-field"' + directHidden + '><span>最大输出 Token（选填）</span><input type="number" min="1" data-workflow-editor-max-output value="' +
        escapeWorkflowText(profile && profile.maxOutputTokens ? profile.maxOutputTokens : "") + '"' + disabledAttribute + ' /></label>' +
        '<label class="field model-direct-field"' + directHidden + '><span>上下文容量</span><input type="number" min="1000" data-workflow-editor-context value="' +
        escapeWorkflowText(profile ? profile.contextWindowTokens : 40000) + '"' + disabledAttribute + ' /></label>' +
        (profile ? '<button type="button" class="ghost-action" data-workflow-action="validate" data-task-type="' + taskType + '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' +
          (!profile.complete || editor.dirty ? " disabled" : "") + '>验证调用</button><p class="inline-status" data-model-validation-summary>' +
          escapeWorkflowText(profile.lastValidation && profile.lastValidation.message || "尚未验证") + '</p>' : '') +
        '</div></details>');
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

    rows.push('<div class="workflow-settings-toolbar"><div><strong>' + definition.label + '</strong><span>当前配置：' +
      escapeWorkflowText(helpers.getActiveWorkflowProfileName ? helpers.getActiveWorkflowProfileName(data) : "尚未配置") +
      '</span></div><button type="button" data-workflow-action="create-open" data-task-type="' + taskType + '"' + createDisabledAttribute + '>新建模型配置</button></div>');
    if (data.loadError) {
      rows.push('<div class="workflow-profile-error-actions"><p class="workflow-profile-error">无法读取工作流配置：' +
        escapeWorkflowText(data.loadError) + '</p><button type="button" class="ghost-action mini-button" data-workflow-action="reload" data-task-type="' +
        taskType + '"' + disabledAttribute + '>重新读取</button></div>');
    }
    if (!data.profiles.length && !data.loadError) {
      rows.push('<p class="workflow-profile-empty">尚未建立模型配置。</p>');
    }
    if (data.profiles.length) {
      rows.push('<div class="workflow-profile-list">');
      data.profiles.forEach(function (profile) {
        var isActive = profile.id === data.activeProfileId;
        var canDelete = canDeleteWorkflowProfile(profile, data.activeProfileId);
        var statusText = helpers.workflowProfileStatusText ?
          helpers.workflowProfileStatusText(profile, data.activeProfileId) :
          (isActive ? "当前使用" : (profile.complete ? "配置完整" : "配置不完整"));
        rows.push('<div class="workflow-profile-row" data-profile-id="' + escapeWorkflowText(profile.id) + '">');
        rows.push('<div class="workflow-profile-summary"><strong>' + escapeWorkflowText(profile.name) + '</strong>');
        rows.push('<span class="workflow-profile-note">' +
          (profile.accessMethod === "direct_model" ? "模型直连" + (profile.modelName ? " · " + escapeWorkflowText(profile.modelName) : "") : "工作流平台") + '</span>');
        if (profile.note) {
          rows.push('<span class="workflow-profile-note">' + escapeWorkflowText(profile.note) + '</span>');
        }
        if (taskType === "word.document_review") {
          rows.push('<span class="workflow-profile-note">限量审查：' +
            (profile.limitedReviewReady ? "可用" : "不可用") + '</span>');
          rows.push('<span class="workflow-profile-note">全篇审查：' +
            escapeWorkflowText(profile.fullDocumentReviewReadiness &&
              profile.fullDocumentReviewReadiness.label || "尚未就绪") + '</span>');
        }
        rows.push('</div>');
        rows.push('<span class="provider-badge">' + escapeWorkflowText(statusText) + '</span>');
        rows.push('<div class="workflow-profile-actions">');
        if (!isActive && profile.complete) {
          rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="activate" data-task-type="' + taskType +
            '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + activationDisabledAttribute + '>设为当前</button>');
        }
        rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="edit-open" data-task-type="' + taskType +
          '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + disabledAttribute + '>编辑</button>');
        rows.push('<button type="button" class="ghost-action mini-button" data-workflow-action="copy" data-task-type="' + taskType +
          '" data-profile-id="' + escapeWorkflowText(profile.id) + '"' + disabledAttribute + '>复制</button>');
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

  function readModelConfigurationDraft() {
    function value(selector) {
      var input = document.querySelector(selector);
      return input ? String(input.value || "").trim() : "";
    }
    return {
      name: value("[data-workflow-editor-name]"),
      note: value("[data-workflow-editor-note]"),
      accessMethod: value("[data-workflow-editor-method]") || "workflow_platform",
      serviceBaseUrl: value("[data-workflow-editor-url]"),
      modelName: value("[data-workflow-editor-model]"),
      temperature: value("[data-workflow-editor-temperature]"),
      maxOutputTokens: value("[data-workflow-editor-max-output]"),
      contextWindowTokens: value("[data-workflow-editor-context]") || "40000",
      apiKey: value("[data-workflow-editor-key]"),
      apiKeyConfirm: value("[data-workflow-editor-key-confirm]")
    };
  }

  function modelConfigurationPayload(taskType, draft) {
    return {
      taskType: taskType,
      name: draft.name,
      note: draft.note,
      accessMethod: draft.accessMethod,
      serviceBaseUrl: draft.serviceBaseUrl,
      modelName: draft.accessMethod === "direct_model" ? draft.modelName : "",
      temperature: draft.accessMethod === "direct_model" && draft.temperature !== "" ? Number(draft.temperature) : null,
      maxOutputTokens: draft.accessMethod === "direct_model" && draft.maxOutputTokens !== "" ? Number(draft.maxOutputTokens) : null,
      contextWindowTokens: draft.accessMethod === "direct_model" ? Number(draft.contextWindowTokens || 40000) : 40000
    };
  }

  function validateModelConfigurationDraft(draft) {
    var base = getWorkflowProfileDraftValidation(draft, false);
    if (!base.valid) {
      return base;
    }
    if (draft.apiKey !== draft.apiKeyConfirm) {
      return { valid: false, message: "两次输入的 API Key 不一致。" };
    }
    if (draft.accessMethod === "direct_model" && draft.maxOutputTokens &&
        Number(draft.maxOutputTokens) >= Number(draft.contextWindowTokens || 40000)) {
      return { valid: false, message: "最大输出 Token 必须小于上下文容量。" };
    }
    return { valid: true, message: "" };
  }

  function saveModelConfigurationKey(configurationId, draft) {
    if (!draft.apiKey) {
      return Promise.resolve();
    }
    return request("/provider/model-configurations/" + encodeURIComponent(configurationId) + "/api-key", {
      apiKey: draft.apiKey
    });
  }

  function validateSavedFormatSemanticConfiguration(taskType, configurationId, draft) {
    if (taskType !== "word.format_review" || draft.accessMethod !== "workflow_platform") {
      return Promise.resolve({ validated: false, skipped: true });
    }
    return request("/provider/model-configurations/" + encodeURIComponent(configurationId) + "/validate", {})
      .then(function () {
        return { validated: true, skipped: false };
      })
      .catch(function (error) {
        return { validated: false, skipped: false, error: error };
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
    var activateInput = document.querySelector("[data-workflow-editor-activate]");
    var draft = readModelConfigurationDraft();
    var validation = validateModelConfigurationDraft(draft);
    var activate = getShouldActivateNewWorkflowProfile(
      getWorkflowProfileData(taskType),
      Boolean(activateInput && activateInput.checked)
    );
    if (!validation.valid) {
      setStatus(validation.message || "请检查模型配置。");
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations", modelConfigurationPayload(taskType, draft))
      .then(function (body) {
        var configuration = body && body.data && body.data.configuration || {};
        return saveModelConfigurationKey(configuration.id, draft).then(function () {
          return validateSavedFormatSemanticConfiguration(taskType, configuration.id, draft).then(function (validation) {
          var complete = Boolean(draft.serviceBaseUrl && draft.apiKey &&
            (draft.accessMethod !== "direct_model" || draft.modelName));
          if (activate && complete) {
            return request("/provider/model-configurations/" + encodeURIComponent(configuration.id) + "/activate", {})
              .then(function () { return validation; });
          }
          return validation;
          });
        });
      }).then(function (validation) {
      var message = "模型配置已保存。";
      if (validation && validation.skipped === false && !validation.validated) {
        message += "格式语义协议验证未通过，格式审查将仅运行确定性规则。";
      }
      return completeWorkflowMutation(taskType, message);
    }).catch(function (error) {
      failWorkflowMutation(taskType, "保存模型配置失败", error, true);
    });
  }

  function saveWorkflowProfileEdit(profileId, taskType) {
    var draft = readModelConfigurationDraft();
    var validation = validateModelConfigurationDraft(draft);
    var metadataSaved = false;
    if (!validation.valid) {
      setStatus(validation.message || "请检查模型配置。");
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId),
      modelConfigurationPayload(taskType, draft), { method: "PATCH" }).then(function () {
      metadataSaved = true;
      return saveModelConfigurationKey(profileId, draft).then(function () {
        return validateSavedFormatSemanticConfiguration(taskType, profileId, draft).then(function (validation) {
          var message = "模型配置已保存。";
          if (validation && validation.skipped === false && !validation.validated) {
            message += "格式语义协议验证未通过，格式审查将仅运行确定性规则。";
          }
          return completeWorkflowMutation(taskType, message);
        });
      });
    }).catch(function (error) {
      if (!metadataSaved) {
        failWorkflowMutation(taskType, "保存模型配置失败", error, true);
        return;
      }
      state.workflowProfileMutationBusy = false;
      state.workflowProfileEditor = null;
      renderWorkflowTaskTabs();
      return loadWorkflowProfiles(taskType).then(function () {
        syncSettingsRefreshController();
        setStatus("模型配置已保存，但 API Key 更换失败：" + describeFetchError(error));
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
        "文档审查正在运行，暂不能切换模型配置。" :
        "模型配置正在更新，请稍后再切换。");
      return;
    }
    if (!profileId) {
      setStatus("请选择要切换的模型配置。");
      return;
    }
    if (!profile || optionState.disabled) {
      state.workflowProfileSelections[taskType] = previousProfileId || data.activeProfileId || "";
      renderWorkflowProfileStrip();
      setStatus("该模型配置不完整，无法切换。");
      return;
    }
    previousProfileId = typeof previousProfileId === "string" ? previousProfileId : (data.activeProfileId || "");
    state.workflowProfileSelections[taskType] = profileId;
    invalidateWorkflowProfileRequests(taskType);
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/activate", {})
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
        setStatus("模型配置已切换，从下一次任务开始生效。");
      })
      .catch(function (error) {
        state.workflowProfileMutationBusy = false;
        state.workflowProfileSelections[taskType] = previousProfileId;
        renderWorkflowProfileStrip();
        renderWorkflowTaskTabs();
        renderWorkflowProfileManager();
        setStatus("切换模型配置失败：" + describeFetchError(error));
      });
  }

  function deleteWorkflowProfile(profileId, taskType) {
    var data = getWorkflowProfileData(taskType);
    var profile = getWorkflowProfileById(taskType, profileId);
    if (!canDeleteWorkflowProfile(profile, data.activeProfileId)) {
      setStatus("当前模型配置不可删除，请先切换到其他配置。");
      return;
    }
    if (window.confirm && !window.confirm("确认删除模型配置“" + profile.name + "”？删除后无法恢复其 API Key。")) {
      return;
    }
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId), null, { method: "DELETE" })
      .then(function () {
        return completeWorkflowMutation(taskType, "模型配置“" + profile.name + "”已删除。");
      })
      .catch(function (error) {
        failWorkflowMutation(taskType, "删除模型配置失败", error);
      });
  }

  function copyModelConfiguration(profileId, taskType) {
    setWorkflowProfileMutationBusy(true);
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/copy", {
      targetTaskType: taskType
    }).then(function () {
      return completeWorkflowMutation(taskType, "模型配置副本已创建，请检查后再启用。");
    }).catch(function (error) {
      failWorkflowMutation(taskType, "复制模型配置失败", error);
    });
  }

  function validateModelConfiguration(profileId, taskType) {
    if (state.workflowProfileEditor && state.workflowProfileEditor.dirty) {
      setStatus("请先保存模型配置，再执行验证调用。");
      return;
    }
    if (window.confirm && !window.confirm("验证调用会向模型后台发送一条内置测试请求，是否继续？")) {
      return;
    }
    setWorkflowProfileMutationBusy(true);
    setStatus("正在验证模型配置，模型响应较慢时请耐心等待...");
    request("/provider/model-configurations/" + encodeURIComponent(profileId) + "/validate", {})
      .then(function (body) {
        var duration = body && body.data ? Number(body.data.durationMs || 0) : 0;
        state.workflowProfileMutationBusy = false;
        state.workflowProfileEditor.dirty = false;
        return loadWorkflowProfiles(taskType).then(function () {
          var refreshedProfile = getWorkflowProfileById(taskType, profileId);
          if (!refreshedProfile) {
            state.workflowProfileEditor = null;
            renderWorkflowProfileManager();
            setStatus("模型配置已验证，但刷新后未找到该配置，请重新进入设置。");
            return;
          }
          state.workflowProfileEditor = {
            mode: "edit",
            taskType: taskType,
            profileId: profileId,
            dirty: false,
            originalAccessMethod: refreshedProfile.accessMethod,
            currentAccessMethod: refreshedProfile.accessMethod
          };
          renderWorkflowProfileManager();
          setStatus("验证成功，用时 " + (duration / 1000).toFixed(1) + " 秒。");
        });
      }).catch(function (error) {
        setWorkflowProfileMutationBusy(false);
        setStatus("验证失败：" + describeFetchError(error));
        renderWorkflowProfileManager();
      });
  }

  function scheduleWorkflowProfileActivation(profileId, taskType, previousProfileId) {
    cancelWorkflowProfileActivation();
    state.workflowProfileActivationTimer = window.setTimeout(function () {
      state.workflowProfileActivationTimer = null;
      activateWorkflowProfile(profileId, taskType, previousProfileId);
    }, 0);
  }

  function cancelWorkflowProfileActivation() {
    if (state.workflowProfileActivationTimer !== null) {
      window.clearTimeout(state.workflowProfileActivationTimer);
      state.workflowProfileActivationTimer = null;
    }
  }

  function handleWorkflowProfileSelectionChange(event) {
    var taskType = getCurrentWorkflowTaskType();
    var data = getWorkflowProfileData(taskType);
    var previousProfileId = data.activeProfileId || state.workflowProfileSelections[taskType] || "";
    var profileId = event.target.value;
    if (!profileId || profileId === previousProfileId) {
      cancelWorkflowProfileActivation();
      state.workflowProfileSelections[taskType] = previousProfileId;
      renderWorkflowProfileStrip();
      return;
    }
    scheduleWorkflowProfileActivation(profileId, taskType, previousProfileId);
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
        setStatus("模型配置读取失败，请先重新读取。");
        return;
      }
      state.workflowProfileEditor = {
        mode: "create", taskType: taskType, profileId: "", dirty: false,
        originalAccessMethod: "workflow_platform", currentAccessMethod: "workflow_platform"
      };
      syncSettingsRefreshController();
      renderWorkflowProfileManager();
    } else if (action === "edit-open") {
      var editingProfile = getWorkflowProfileById(taskType, profileId);
      state.workflowProfileEditor = {
        mode: "edit", taskType: taskType, profileId: profileId, dirty: false,
        originalAccessMethod: editingProfile ? editingProfile.accessMethod : "workflow_platform",
        currentAccessMethod: editingProfile ? editingProfile.accessMethod : "workflow_platform"
      };
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
      setStatus("正在重新读取模型配置...");
      loadWorkflowProfiles(taskType);
    } else if (action === "create-save") {
      createWorkflowProfile(taskType);
    } else if (action === "activate") {
      activateWorkflowProfile(profileId, taskType, getWorkflowProfileData(taskType).activeProfileId || "");
    } else if (action === "edit-save") {
      saveWorkflowProfileEdit(profileId, taskType);
    } else if (action === "delete") {
      deleteWorkflowProfile(profileId, taskType);
    } else if (action === "copy") {
      copyModelConfiguration(profileId, taskType);
    } else if (action === "validate") {
      validateModelConfiguration(profileId, taskType);
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
    byId("writing-policy-more-view").hidden = view !== "more";
    byId("writing-policy-editor-view").hidden = view !== "editor";
    byId("writing-policy-import-view").hidden = view !== "import";
  }

  function focusWritingPolicyView(view) {
    var targetIds = {
      home: "btn-open-writing-policy-manager",
      preset: "writing-policy-preset-title",
      scope: "writing-policy-scope-title",
      list: "writing-policy-list-title",
      more: "writing-policy-more-title",
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
    renderWritingPolicyPagination(
      "preset",
      state.writingPolicyPresetItemOffset,
      state.writingPolicyPresetItemTotal,
      state.writingPolicyPresetItems.length,
      Boolean(state.writingPolicyPresetError)
    );
    if (state.writingPolicyPresetError) {
      meta.textContent = "预置规范暂时无法读取，请稍后重试。";
      return;
    }
    if (!pack.packId) {
      meta.textContent = "正在读取规范包...";
      return;
    }
    byId("writing-policy-preset-title").textContent = String(pack.name || "预置规范");
    meta.textContent = pack.name + " v" + pack.version + " ｜ 来源：" +
      source.name + " " + source.version + " ｜ 提交：" + source.commit +
      " ｜ 许可证：" + source.license;
    for (index = 0; index < state.writingPolicyPresetItems.length; index += 1) {
      var item = state.writingPolicyPresetItems[index];
      var row = document.createElement("div");
      var title = document.createElement("strong");
      var rule = document.createElement("p");
      var trace = document.createElement("small");
      var status = document.createElement("span");
      var actions = document.createElement("div");
      row.className = "writing-policy-item-row writing-policy-preset-item";
      title.textContent = item.name || item.preferredText || "未命名规范";
      rule.textContent = item.ruleText || item.definition || "";
      trace.textContent = "ID：" + String(item.id || "") + " ｜ 来源版本：" +
        String((item.source || {}).version || source.version || "") +
        " ｜ 提交：" + String((item.source || {}).commit || source.commit || "") +
        " ｜ 许可证：" + String((item.source || {}).license || source.license || "");
      status.className = "provider-badge";
      status.textContent = helpers.writingPolicyItemStateLabel
        ? helpers.writingPolicyItemStateLabel(item, "preset")
        : (item.effective === false ? "预置停用 · 未生效" : "预置基线 · 已生效");
      actions.className = "writing-policy-preset-actions";
      if (WRITING_POLICY_ITEM_TYPES.indexOf(item.type) >= 0 && item.organizationState !== "disabled") {
        var editButton = document.createElement("button");
        var disableButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "ghost-action mini-button";
        editButton.textContent = "编辑覆盖";
        editButton.setAttribute("data-writing-policy-preset-action", "edit");
        editButton.setAttribute("data-writing-policy-preset-id", String(item.id || ""));
        editButton.disabled = state.writingPolicyMutationBusy;
        disableButton.type = "button";
        disableButton.className = "ghost-action mini-button danger-action";
        disableButton.textContent = "停用预置";
        disableButton.setAttribute("data-writing-policy-preset-action", "disable");
        disableButton.setAttribute("data-writing-policy-preset-id", String(item.id || ""));
        disableButton.disabled = state.writingPolicyMutationBusy;
        actions.appendChild(editButton);
        actions.appendChild(disableButton);
      }
      if (WRITING_POLICY_ITEM_TYPES.indexOf(item.type) >= 0 &&
          (item.organizationState === "overridden" || item.organizationState === "disabled")) {
        var restoreButton = document.createElement("button");
        restoreButton.type = "button";
        restoreButton.className = "ghost-action mini-button";
        restoreButton.textContent = "恢复预置";
        restoreButton.setAttribute("data-writing-policy-preset-action", "restore");
        restoreButton.setAttribute("data-writing-policy-preset-id", String(item.id || ""));
        restoreButton.disabled = state.writingPolicyMutationBusy;
        actions.appendChild(restoreButton);
      }
      row.appendChild(title);
      row.appendChild(rule);
      row.appendChild(trace);
      row.appendChild(status);
      row.appendChild(actions);
      list.appendChild(row);
    }
    if (!state.writingPolicyPresetItems.length) {
      list.textContent = "当前规范包暂无可显示条目。";
    }
  }

  function renderWritingPolicyPresetPackSelect() {
    var select = byId("writing-policy-preset-pack-select");
    var selectedId = String(state.writingPolicyPresetPack && state.writingPolicyPresetPack.packId || "");
    select.textContent = "";
    state.writingPolicyPresetPacks.forEach(function (pack) {
      var option = document.createElement("option");
      option.value = String(pack.packId || "");
      option.textContent = String(pack.name || pack.packId || "未命名规范包");
      option.selected = option.value === selectedId;
      select.appendChild(option);
    });
    select.disabled = state.writingPolicyMutationBusy || !state.writingPolicyPresetPacks.length;
  }

  function loadWritingPolicyPresetItems(packId) {
    var requestId = state.writingPolicyPresetLoadSequence + 1;
    var requestOffset = state.writingPolicyPresetItemOffset;
    state.writingPolicyPresetLoadSequence = requestId;
    return request("/writing-policies/items?layer=preset&packId=" +
      encodeURIComponent(packId) + "&limit=" + WRITING_POLICY_LIST_PAGE_SIZE +
      "&offset=" + requestOffset).then(function (body) {
      var data = body.data || {};
      if (state.writingPolicyPresetLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyPresetItems = Array.isArray(data.items)
        ? data.items.slice(0, WRITING_POLICY_LIST_PAGE_SIZE)
        : [];
      state.writingPolicyPresetItemTotal = Math.max(
        state.writingPolicyPresetItems.length,
        Number(data.count) || 0
      );
      var normalizedOffset = normalizeWritingPolicyPageOffset(
        state.writingPolicyPresetItemOffset,
        state.writingPolicyPresetItemTotal
      );
      if (normalizedOffset !== state.writingPolicyPresetItemOffset) {
        state.writingPolicyPresetItemOffset = normalizedOffset;
        return loadWritingPolicyPresetItems(packId);
      }
      state.writingPolicyPresetError = "";
      renderWritingPolicyPresetItems();
      return state.writingPolicyPresetItems;
    }).catch(function () {
      if (state.writingPolicyPresetLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyPresetItems = [];
      state.writingPolicyPresetItemTotal = 0;
      state.writingPolicyPresetError = "items_unavailable";
      renderWritingPolicyPresetItems();
      return [];
    });
  }

  function loadWritingPolicyPresetPacks() {
    state.writingPolicyPresetPacks = [];
    state.writingPolicyPresetPack = null;
    state.writingPolicyPresetItems = [];
    state.writingPolicyPresetItemTotal = 0;
    state.writingPolicyPresetItemOffset = 0;
    state.writingPolicyPresetError = "";
    renderWritingPolicyPresetItems();
    return request("/writing-policies/packs").then(function (body) {
      var packs = body.data && Array.isArray(body.data.packs) ? body.data.packs : [];
      var index;
      state.writingPolicyPresetPacks = packs;
      for (index = 0; index < packs.length; index += 1) {
        if (packs[index].packId === "yangqi-tech-writing-base") {
          state.writingPolicyPresetPack = packs[index];
          renderWritingPolicyPresetPackSelect();
          return loadWritingPolicyPresetItems(packs[index].packId);
        }
      }
      state.writingPolicyPresetError = "base_pack_missing";
      renderWritingPolicyPresetPackSelect();
      renderWritingPolicyPresetItems();
      return [];
    }).catch(function () {
      state.writingPolicyPresetError = "packs_unavailable";
      renderWritingPolicyPresetPackSelect();
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

  function selectWritingPolicyPresetPack(packId) {
    var selected = null;
    state.writingPolicyPresetPacks.forEach(function (pack) {
      if (String(pack.packId || "") === String(packId || "")) {
        selected = pack;
      }
    });
    if (!selected || state.writingPolicyMutationBusy) {
      return;
    }
    state.writingPolicyPresetPack = selected;
    state.writingPolicyPresetItems = [];
    state.writingPolicyPresetItemTotal = 0;
    state.writingPolicyPresetItemOffset = 0;
    state.writingPolicyPresetError = "";
    renderWritingPolicyPresetPackSelect();
    renderWritingPolicyPresetItems();
    loadWritingPolicyPresetItems(selected.packId);
  }

  function openWritingPolicyScopeView() {
    setWritingPolicyView("scope");
  }

  function writingPolicyTypeLabel(type) {
    if (type === "term") {
      return "术语";
    }
    return type === "anti_template" ? "去模板化规则" : "文体规则";
  }

  function normalizeWritingPolicyPageOffset(offset, total) {
    return helpers.writingPolicyPageState(
      offset,
      total,
      0,
      WRITING_POLICY_LIST_PAGE_SIZE
    ).offset;
  }

  function renderWritingPolicyPagination(kind, offset, total, pageCount, error) {
    var preset = kind === "preset";
    var container = byId(preset ? "writing-policy-preset-pagination" : "writing-policy-pagination");
    var previous = byId(preset ? "btn-writing-policy-preset-previous" : "btn-writing-policy-previous");
    var next = byId(preset ? "btn-writing-policy-preset-next" : "btn-writing-policy-next");
    var status = byId(preset ? "writing-policy-preset-page-status" : "writing-policy-page-status");
    var page = helpers.writingPolicyPageState(
      offset,
      total,
      pageCount,
      WRITING_POLICY_LIST_PAGE_SIZE
    );
    var disabled = Boolean(error) || state.writingPolicyMutationBusy;
    container.hidden = Boolean(error) || (!page.hasPrevious && !page.hasNext);
    previous.disabled = disabled || !page.hasPrevious;
    next.disabled = disabled || !page.hasNext;
    status.textContent = page.label;
  }

  function changeWritingPolicyPresetPage(direction) {
    var nextOffset = normalizeWritingPolicyPageOffset(
      state.writingPolicyPresetItemOffset +
        direction * WRITING_POLICY_LIST_PAGE_SIZE,
      state.writingPolicyPresetItemTotal
    );
    if (nextOffset === state.writingPolicyPresetItemOffset ||
        !state.writingPolicyPresetPack ||
        state.writingPolicyMutationBusy) {
      return;
    }
    state.writingPolicyPresetItemOffset = nextOffset;
    loadWritingPolicyPresetItems(state.writingPolicyPresetPack.packId);
  }

  function changeWritingPolicyPage(direction) {
    var nextOffset = normalizeWritingPolicyPageOffset(
      state.writingPolicyItemOffset + direction * WRITING_POLICY_LIST_PAGE_SIZE,
      state.writingPolicyItemTotal
    );
    if (nextOffset === state.writingPolicyItemOffset ||
        state.writingPolicyMutationBusy) {
      return;
    }
    state.writingPolicyItemOffset = nextOffset;
    loadWritingPolicyItems();
  }

  function handleWritingPolicyLayerClick(event) {
    var layer = event.target.getAttribute("data-writing-policy-layer");
    if (layer === "preset") {
      openWritingPolicyPresetView();
    } else if (layer === "organization") {
      openWritingPolicyScopeView();
    }
  }

  function renderWritingPolicyTypeSwitch() {
    var buttons = byId("writing-policy-type-switch").querySelectorAll("[data-writing-policy-type]");
    var index;
    for (index = 0; index < buttons.length; index += 1) {
      var type = buttons[index].getAttribute("data-writing-policy-type");
      var active = type === state.writingPolicyType;
      buttons[index].classList.toggle("active", active);
      buttons[index].setAttribute("aria-selected", active ? "true" : "false");
      buttons[index].disabled = state.writingPolicyMutationBusy;
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
    renderWritingPolicyPagination(
      "organization",
      state.writingPolicyItemOffset,
      state.writingPolicyItemTotal,
      state.writingPolicyItems.length,
      Boolean(state.writingPolicyListError)
    );
    byId("writing-policy-list-title").textContent = state.writingPolicyType === "term"
      ? scopeDefinition.label
      : "组织" + writingPolicyTypeLabel(state.writingPolicyType);
    byId("writing-policy-list-caption").textContent = state.writingPolicyType === "term"
      ? scopeDefinition.caption
      : "统一管理规则的任务与场景范围。";
    byId("writing-policy-search-input").value = state.writingPolicySearch;
    renderWritingPolicyTypeSwitch();
    addButton.disabled = state.writingPolicyMutationBusy || Boolean(state.writingPolicyListError);
    retryButton.hidden = !state.writingPolicyListError;
    if (state.writingPolicyListError) {
      statusNode.textContent = "写作规范库暂不可用，未显示空列表。";
      return;
    }
    if (!state.writingPolicyItems.length) {
      statusNode.textContent = "当前范围暂无" + writingPolicyTypeLabel(state.writingPolicyType) + "。";
      return;
    }
    statusNode.textContent = (
      state.writingPolicyItemTotal > state.writingPolicyItems.length
        ? "共 " + state.writingPolicyItemTotal + " 条，当前显示第 " +
          (state.writingPolicyItemOffset + 1) + "–" +
          (state.writingPolicyItemOffset + state.writingPolicyItems.length) + " 条"
        : "共 " + state.writingPolicyItems.length + " 条"
    ) + writingPolicyTypeLabel(state.writingPolicyType);
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
      status.textContent = helpers.writingPolicyItemStateLabel
        ? helpers.writingPolicyItemStateLabel(item, "organization")
        : (item.enabled === false ? "组织自定义 · 未生效" : "组织自定义 · 已生效");
      text.appendChild(title);
      text.appendChild(note);
      row.appendChild(text);
      row.appendChild(status);
      list.appendChild(row);
    });
  }

  function loadWritingPolicyItems() {
    var requestId = state.writingPolicyLoadSequence + 1;
    var requestType = state.writingPolicyType;
    var requestSearch = state.writingPolicySearch;
    var requestOffset = state.writingPolicyItemOffset;
    var listScope = requestType === "term"
      ? state.writingPolicyScope
      : "organization";
    state.writingPolicyLoadSequence = requestId;
    state.writingPolicyListError = "";
    byId("writing-policy-list-status").textContent = "正在读取...";
    byId("writing-policy-item-list").textContent = "";
    return request("/writing-policies/items?scope=" + encodeURIComponent(listScope) +
      "&type=" + encodeURIComponent(requestType) +
      "&query=" + encodeURIComponent(requestSearch) +
      "&limit=" + WRITING_POLICY_LIST_PAGE_SIZE +
      "&offset=" + requestOffset).then(function (body) {
      var data = body.data || {};
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyItems = Array.isArray(data.items)
        ? data.items.slice(0, WRITING_POLICY_LIST_PAGE_SIZE)
        : [];
      state.writingPolicyItemTotal = Math.max(
        state.writingPolicyItems.length,
        Number(data.count) || 0
      );
      var normalizedOffset = normalizeWritingPolicyPageOffset(
        state.writingPolicyItemOffset,
        state.writingPolicyItemTotal
      );
      if (normalizedOffset !== state.writingPolicyItemOffset) {
        state.writingPolicyItemOffset = normalizedOffset;
        return loadWritingPolicyItems();
      }
      renderWritingPolicyList();
      return state.writingPolicyItems;
    }).catch(function (error) {
      if (state.writingPolicyLoadSequence !== requestId) {
        return null;
      }
      state.writingPolicyItems = [];
      state.writingPolicyItemTotal = 0;
      state.writingPolicyItemOffset = 0;
      state.writingPolicyListError = describeFetchError(error);
      renderWritingPolicyList();
      return null;
    });
  }

  function openWritingPolicyList(scope, type) {
    state.writingPolicyScope = getWritingPolicyScopeDefinition(scope).scope;
    state.writingPolicyType = type || state.writingPolicyType;
    state.writingPolicySearch = "";
    state.writingPolicyItems = [];
    state.writingPolicyItemTotal = 0;
    state.writingPolicyItemOffset = 0;
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

  function normalizeWritingPolicyRuleTasks(item) {
    var aliases = {
      smart_write: "word.smart_write",
      smart_imitate: "word.smart_imitation",
      document_review: "word.document_review"
    };
    var values = Array.isArray(item && item.taskTypes) ? item.taskTypes : [];
    values = values.map(function (value) {
      return aliases[value] || value;
    }).filter(function (value) {
      return WRITING_POLICY_RULE_TASK_TYPES.indexOf(value) >= 0;
    });
    if (!values.length && item && item.scope && item.scope !== "global") {
      values = [item.scope];
    }
    return values.length ? values : WRITING_POLICY_RULE_TASK_TYPES.slice();
  }

  function normalizeWritingPolicyRuleScenes(item) {
    var values = Array.isArray(item && item.sceneIds) ? item.sceneIds : [];
    values = values.filter(function (value) {
      return WRITING_POLICY_RULE_SCENE_IDS.indexOf(value) >= 0;
    });
    return values.length ? values : WRITING_POLICY_RULE_SCENE_IDS.slice();
  }

  function setWritingPolicyCheckedValues(containerId, values) {
    var controls = byId(containerId).querySelectorAll('input[type="checkbox"]');
    var index;
    for (index = 0; index < controls.length; index += 1) {
      controls[index].checked = values.indexOf(controls[index].value) >= 0;
    }
  }

  function readWritingPolicyCheckedValues(containerId) {
    var controls = byId(containerId).querySelectorAll('input[type="checkbox"]');
    var values = [];
    var index;
    for (index = 0; index < controls.length; index += 1) {
      if (controls[index].checked) {
        values.push(controls[index].value);
      }
    }
    return values;
  }

  function setWritingPolicyEditorError(message, field) {
    var errorNode = byId("writing-policy-editor-error");
    var fieldIds = {
      preferredText: "writing-policy-preferred-text",
      name: "writing-policy-style-name",
      ruleText: "writing-policy-rule-text",
      taskTypes: "writing-policy-task-types",
      sceneIds: "writing-policy-scene-ids",
      scope: "writing-policy-editor-caption"
    };
    var errorIds = {
      preferredText: "writing-policy-preferred-error",
      name: "writing-policy-style-name-error",
      ruleText: "writing-policy-rule-error"
    };
    Object.keys(fieldIds).forEach(function (fieldName) {
      var input = byId(fieldIds[fieldName]);
      if (input) {
        input.removeAttribute("aria-invalid");
      }
    });
    ["preferredText", "name", "ruleText"].forEach(function (fieldName) {
      var fieldError = byId(errorIds[fieldName]);
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
    setWritingPolicyCheckedValues("writing-policy-task-types", []);
    setWritingPolicyCheckedValues("writing-policy-scene-ids", []);
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
    byId("writing-policy-editor-title").textContent = editor.mode === "preset-override"
      ? "编辑预置规范覆盖"
      : editor.mode === "edit"
        ? "编辑规范条目"
        : "新增规范条目";
    byId("writing-policy-editor-caption").textContent = editor.mode === "preset-override"
      ? "组织覆盖 · 保存后优先于预置基线"
      : scopeDefinition.label + " · " + writingPolicyTypeLabel(type);
    byId("writing-policy-term-fields").hidden = type !== "term";
    byId("writing-policy-style-fields").hidden = type === "term";
    byId("writing-policy-category-field").hidden = type !== "term";
    byId("writing-policy-always-apply-field").hidden = type === "term";
    byId("writing-policy-enabled-field").hidden = editor.mode === "preset-override";
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
    byId("writing-policy-priority").value = helpers.normalizeWritingPolicyPriority
      ? helpers.normalizeWritingPolicyPriority(item.priority)
      : String(item.priority || "medium");
    byId("writing-policy-always-apply").checked = editor.mode === "preset-override"
      ? item.alwaysApply !== false
      : Boolean(item.alwaysApply);
    byId("writing-policy-enabled").checked = item.enabled !== false;
    setWritingPolicyCheckedValues(
      "writing-policy-task-types",
      normalizeWritingPolicyRuleTasks(item)
    );
    setWritingPolicyCheckedValues(
      "writing-policy-scene-ids",
      normalizeWritingPolicyRuleScenes(item)
    );
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

  function openWritingPolicyPresetEditor(item) {
    if (!item || WRITING_POLICY_ITEM_TYPES.indexOf(item.type) < 0 ||
        state.writingPolicyMutationBusy) {
      return;
    }
    state.writingPolicyEditor = {
      mode: "preset-override",
      item: item,
      type: item.type,
      scope: item.scope || "global",
      returnView: "preset"
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
      draft.taskTypes = readWritingPolicyCheckedValues("writing-policy-task-types");
      draft.sceneIds = readWritingPolicyCheckedValues("writing-policy-scene-ids");
      if (type === "anti_template") {
        draft.type = "anti_template";
      }
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
    if (editor.mode === "preset-override") {
      path = "/writing-policies/preset-overrides/" +
        encodeURIComponent(String(editor.item.id || ""));
      options.method = "PUT";
      draft.operation = "override";
    } else if (editor.mode === "edit") {
      path += "/" + encodeURIComponent(String(editor.item.id || ""));
      options.method = "PATCH";
    }
    setWritingPolicyEditorError("", "");
    setWritingPolicyMutationBusy(true);
    request(path, draft, options).then(function () {
      setWritingPolicyMutationBusy(false);
      state.writingPolicyEditorDirty = false;
      clearWritingPolicyEditorState();
      if (editor.mode === "preset-override") {
        setWritingPolicyView("preset");
        return loadWritingPolicyPresetItems(state.writingPolicyPresetPack.packId).then(function () {
          loadWritingPolicySummary();
          setStatus("预置规范的组织覆盖已保存。");
        });
      }
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
    var returnView = state.writingPolicyEditor && state.writingPolicyEditor.returnView;
    if (!confirmWritingPolicyEditorDiscard()) {
      return;
    }
    clearWritingPolicyEditorState();
    if (returnView === "preset") {
      setWritingPolicyView("preset");
      renderWritingPolicyPresetItems();
    } else {
      setWritingPolicyView("list");
      renderWritingPolicyList();
    }
  }

  function findWritingPolicyPresetItem(itemId) {
    var found = null;
    state.writingPolicyPresetItems.forEach(function (item) {
      if (String(item.id || "") === String(itemId || "")) {
        found = item;
      }
    });
    return found;
  }

  function disableWritingPolicyPresetItem(itemId) {
    var item = findWritingPolicyPresetItem(itemId);
    if (!item || WRITING_POLICY_ITEM_TYPES.indexOf(item.type) < 0 ||
        state.writingPolicyMutationBusy) {
      return;
    }
    if (window.confirm && !window.confirm("确认停用预置规范“" + String(item.preferredText || item.name || "") + "”？")) {
      return;
    }
    state.writingPolicyMutationBusy = true;
    renderWritingPolicyPresetPackSelect();
    renderWritingPolicyPresetItems();
    request("/writing-policies/preset-overrides/" + encodeURIComponent(String(item.id || "")), {
      operation: "disabled"
    }, {
      method: "PUT",
      timeoutMs: WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS
    }).then(function () {
      state.writingPolicyMutationBusy = false;
      renderWritingPolicyPresetPackSelect();
      return loadWritingPolicyPresetItems(state.writingPolicyPresetPack.packId).then(function () {
        loadWritingPolicySummary();
        setStatus("预置规范已停用。");
      });
    }).catch(function (error) {
      state.writingPolicyMutationBusy = false;
      renderWritingPolicyPresetPackSelect();
      renderWritingPolicyPresetItems();
      setStatus("停用失败：" + describeFetchError(error));
    });
  }

  function restoreWritingPolicyPresetItem(itemId) {
    var item = findWritingPolicyPresetItem(itemId);
    if (!item || WRITING_POLICY_ITEM_TYPES.indexOf(item.type) < 0 ||
        state.writingPolicyMutationBusy) {
      return;
    }
    if (window.confirm && !window.confirm("确认恢复预置规范“" +
        String((item.baseline || {}).preferredText || (item.baseline || {}).name ||
          item.preferredText || item.name || "") + "”？")) {
      return;
    }
    state.writingPolicyMutationBusy = true;
    renderWritingPolicyPresetPackSelect();
    renderWritingPolicyPresetItems();
    request("/writing-policies/preset-overrides/" + encodeURIComponent(String(item.id || "")), null, {
      method: "DELETE",
      timeoutMs: WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS
    }).then(function () {
      state.writingPolicyMutationBusy = false;
      renderWritingPolicyPresetPackSelect();
      return loadWritingPolicyPresetItems(state.writingPolicyPresetPack.packId).then(function () {
        loadWritingPolicySummary();
        setStatus("预置规范已恢复。");
      });
    }).catch(function (error) {
      state.writingPolicyMutationBusy = false;
      renderWritingPolicyPresetPackSelect();
      renderWritingPolicyPresetItems();
      setStatus("恢复失败：" + describeFetchError(error));
    });
  }

  function handleWritingPolicyPresetAction(event) {
    var target = event.target;
    var action;
    var itemId;
    while (target && target !== byId("writing-policy-preset-item-list") && !target.getAttribute("data-writing-policy-preset-action")) {
      target = target.parentNode;
    }
    if (!target || target === byId("writing-policy-preset-item-list")) {
      return;
    }
    action = target.getAttribute("data-writing-policy-preset-action");
    itemId = target.getAttribute("data-writing-policy-preset-id");
    if (action === "edit") {
      openWritingPolicyPresetEditor(findWritingPolicyPresetItem(itemId));
    } else if (action === "disable") {
      disableWritingPolicyPresetItem(itemId);
    } else if (action === "restore") {
      restoreWritingPolicyPresetItem(itemId);
    }
  }

  function handleWritingPolicyScopeClick(event) {
    var target = event.target;
    while (target && target !== byId("writing-policy-scope-list") && !target.getAttribute("data-writing-policy-scope")) {
      target = target.parentNode;
    }
    if (target && target.getAttribute("data-writing-policy-scope")) {
      openWritingPolicyList(
        target.getAttribute("data-writing-policy-scope"),
        target.getAttribute("data-writing-policy-entry-type") || ""
      );
    }
  }

  function handleWritingPolicyTypeClick(event) {
    var type = event.target.getAttribute("data-writing-policy-type");
    selectWritingPolicyType(type);
  }

  function selectWritingPolicyType(type) {
    if (WRITING_POLICY_ITEM_TYPES.indexOf(type) < 0 || state.writingPolicyMutationBusy) {
      return;
    }
    state.writingPolicyType = type;
    state.writingPolicyItems = [];
    state.writingPolicyItemTotal = 0;
    state.writingPolicyItemOffset = 0;
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
    state.writingPolicyItemOffset = 0;
    state.writingPolicyLoadSequence += 1;
    state.writingPolicyItems = [];
    state.writingPolicyItemTotal = 0;
    state.writingPolicyListError = "";
    renderWritingPolicyList();
    byId("writing-policy-list-status").textContent = "正在筛选...";
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
    byId("writing-policy-import-change-list").textContent = "";
    byId("writing-policy-import-changes-section").hidden = true;
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
    resetWritingPolicyImport("");
    setWritingPolicyView("import");
  }

  function closeWritingPolicyImport() {
    if (state.writingPolicyImportBusy) {
      return;
    }
    resetWritingPolicyImport("");
    setWritingPolicyView("more");
  }

  function openWritingPolicyMore() {
    if (state.writingPolicyMutationBusy || state.writingPolicyImportBusy) {
      return;
    }
    byId("writing-policy-more-status").textContent = "按需执行操作。";
    setWritingPolicyView("more");
  }

  function closeWritingPolicyMore() {
    setWritingPolicyView("preset");
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
    var changeList = byId("writing-policy-import-change-list");
    var applyButton = byId("btn-apply-writing-policy-import");
    errorList.textContent = "";
    conflictList.textContent = "";
    changeList.textContent = "";
    if (!preview) {
      byId("writing-policy-import-preview-panel").hidden = true;
      return;
    }
    byId("writing-policy-import-preview-panel").hidden = false;
    byId("writing-policy-import-new-count").textContent = String(preview.stats.newCount);
    byId("writing-policy-import-modify-count").textContent = String(preview.stats.modifyCount);
    byId("writing-policy-import-disable-count").textContent = String(preview.stats.disableCount);
    byId("writing-policy-import-restore-count").textContent = String(preview.stats.restoreCount);
    byId("writing-policy-import-delete-count").textContent = String(preview.stats.deleteCount);
    byId("writing-policy-import-conflict-count").textContent = String(preview.stats.conflictCount);
    byId("writing-policy-import-error-count").textContent = String(preview.stats.errorCount);
    byId("writing-policy-import-errors-title").textContent = helpers.writingPolicyImportCountLabel ?
      helpers.writingPolicyImportCountLabel("校验错误", preview.stats.errorCount, preview.errors.length) : "校验错误";
    byId("writing-policy-import-conflicts-title").textContent = helpers.writingPolicyImportCountLabel ?
      helpers.writingPolicyImportCountLabel("冲突处理", preview.stats.conflictCount, preview.conflicts.length) : "冲突处理";
    preview.changes.forEach(function (item) {
      var row = document.createElement("li");
      var labels = {
        "new": "新增",
        "modify": "修改",
        "disable": "停用",
        "restore": "恢复",
        "delete": "删除"
      };
      row.textContent = "第 " + String(item.rowNumber) + " 行 · " +
        (labels[item.action] || item.action || "变更") + " · " + item.name;
      changeList.appendChild(row);
    });
    byId("writing-policy-import-changes-title").textContent = helpers.writingPolicyImportCountLabel ?
      helpers.writingPolicyImportCountLabel("变更预览", preview.changes.length, preview.changes.length) : "变更预览";
    byId("writing-policy-import-changes-section").hidden = preview.changes.length === 0;
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
    applyButton.disabled = state.writingPolicyImportBusy || !preview.previewToken ||
      preview.stats.errorCount > 0;
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
        if (state.writingPolicyImportPreview.stats.errorCount > 0) {
          state.writingPolicyImportStep = "validate";
          byId("writing-policy-import-status").textContent = "校验发现错误，请修正文件后重新预览。";
        } else {
          byId("writing-policy-import-status").textContent = state.writingPolicyImportPreview.conflicts.length ?
            "校验完成，请处理冲突后应用。" : "校验完成，可应用导入。";
        }
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
    var applyPayload;
    if (!preview || !preview.previewToken || state.writingPolicyImportBusy) {
      return;
    }
    if (preview.stats.errorCount > 0) {
      byId("writing-policy-import-status").textContent = "预览仍有错误，不能应用。";
      return;
    }
    applyPayload = helpers.buildWritingPolicyImportApplyRequest ?
      helpers.buildWritingPolicyImportApplyRequest(preview) : {
        previewToken: preview.previewToken,
        fileDigest: preview.fileDigest,
        acceptedConflictRows: []
      };
    setWritingPolicyImportBusy(true);
    state.writingPolicyImportStep = "apply";
    renderWritingPolicyImportStep();
    byId("writing-policy-import-status").textContent = "正在应用导入结果...";
    request("/writing-policies/imports/apply", applyPayload).then(function (body) {
      var result = body.data || {};
      state.writingPolicyImportPreview = null;
      byId("writing-policy-import-preview-panel").hidden = true;
      byId("writing-policy-import-status").textContent = "导入完成：新增 " +
        String(result.createdCount || 0) + "，修改 " + String(result.modifiedCount || result.updatedCount || 0) +
        "，停用 " + String(result.disabledCount || 0) + "，恢复 " +
        String(result.restoredCount || 0) + "，删除 " + String(result.deletedCount || 0) + "。";
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
    var statusNode = state.writingPolicyView === "import" ?
      byId("writing-policy-import-status") :
      state.writingPolicyView === "more" ? byId("writing-policy-more-status") : null;
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

  function exportWritingPolicies(format) {
    var scope = byId("writing-policy-export-scope").value === "organization" ?
      "organization" : "effective";
    var suffix = format === "xlsx" ? "xlsx" : "csv";
    runWritingPolicyDownload(
      "/writing-policies/export." + suffix + "?scope=" + encodeURIComponent(scope),
      "writing-policies-" + scope + "." + suffix,
      (scope === "organization" ? "组织规范" : "当前生效规范") +
        "已导出为 " + suffix.toUpperCase() + "。"
    );
  }

  function refreshWritingPolicyDiagnostics() {
    var status = byId("writing-policy-more-status");
    var output = byId("writing-policy-diagnostics-output");
    status.textContent = "正在读取写作规范库诊断...";
    request("/writing-policies/diagnostics", null, {
      method: "GET",
      timeoutMs: WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      output.textContent = JSON.stringify(body.data || {}, null, 2);
      output.hidden = false;
      status.textContent = "写作规范库诊断已刷新。";
    }).catch(function (error) {
      output.hidden = true;
      output.textContent = "";
      status.textContent = "诊断读取失败：" + describeFetchError(error);
    });
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

  function scheduleDocumentReviewPoll(jobId, stopWaiting, delayMs, resumeExpected) {
    setTimeout(function () {
      pollDocumentReviewJob(jobId, stopWaiting, resumeExpected);
    }, delayMs);
  }

  function isFatalDocumentReviewPollError(error) {
    return error && (
      error.adapterCode === "DOCUMENT_REVIEW_JOB_NOT_FOUND" ||
      error.adapterCode === "DOCUMENT_REVIEW_JOB_INTERRUPTED" ||
      error.adapterCode === "LONG_TASK_QUEUE_FULL" ||
      error.adapterCode === "DOCUMENT_REVIEW_AUTH_SNAPSHOT_FAILED" ||
      error.adapterCode === "REQUEST_VALIDATION_FAILED"
    );
  }

  function renderDocumentReviewJobProgress(job, jobId) {
    var phaseText = DOCUMENT_REVIEW_PHASE_TEXT[job.phase] || job.phase || "等待状态更新";
    var elapsedSeconds = Number(job.elapsedSeconds || 0);
    var phaseElapsedSeconds = Number(job.phaseElapsedSeconds || 0);
    var lines = [];
    if (job.status === "queued") {
      setStatus("文档审查正在排队，当前位置：" + (job.queuePosition || 1) + "。");
      lines.push("文档审查已进入共享任务队列。", "排队位置：" + (job.queuePosition || 1));
    } else {
      setStatus("文档审查正在处理，当前阶段：" + phaseText + "。");
      lines.push(job.runningMessage || "adapter 正在执行文档审查。", "当前阶段：" + phaseText);
    }
    lines.push(
      "总耗时：" + elapsedSeconds + " 秒",
      "本阶段耗时：" + phaseElapsedSeconds + " 秒",
      "任务编号：" + jobId
    );
    setDocumentReviewCancelVisible(job.status === "queued" && job.canCancel, false);
    setPlainResult(lines.join("\n"));
  }

  function finishCancelledDocumentReview(jobId, stopWaiting) {
    clearDocumentReviewActiveJob(jobId);
    setDocumentReviewJobId("");
    state.documentReviewPollStartedAt = 0;
    state.documentReviewPollErrorCount = 0;
    stopDocumentReviewWaitFeedback(stopWaiting);
    setStatus("排队中的文档审查任务已取消。");
    setPlainResult("排队中的文档审查任务已取消，未调用模型后台。\n任务编号：" + jobId);
  }

  function pollDocumentReviewJob(jobId, stopWaiting, resumeExpected) {
    var query = resumeExpected ? "?resume=1" : "";
    if (!jobId || state.documentReviewJobId !== jobId) {
      return;
    }
    request("/word/document-review/jobs/" + encodeURIComponent(jobId) + query, null, {
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
          stopDocumentReviewWaitFeedback(stopWaiting);
          completeDocumentReview(job.result || {}, body.traceId || job.traceId || jobId);
          return;
        }
        if (job.status === "cancelled") {
          finishCancelledDocumentReview(jobId, stopWaiting);
          return;
        }
        if (job.status === "failed") {
          clearDocumentReviewActiveJob(jobId);
          setDocumentReviewJobId("");
          state.documentReviewPollStartedAt = 0;
          stopDocumentReviewWaitFeedback(stopWaiting);
          setStatus("文档审查失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
          setResult((job.error && job.error.message) || "后台任务执行失败。");
          return;
        }
        renderDocumentReviewJobProgress(job, jobId);
        scheduleDocumentReviewPoll(jobId, stopWaiting, DOCUMENT_REVIEW_POLL_INTERVAL_MS, true);
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
        if (error && error.adapterCode === "DOCUMENT_REVIEW_JOB_INTERRUPTED") {
          clearDocumentReviewActiveJob(jobId);
          setDocumentReviewJobId("");
          state.documentReviewPollStartedAt = 0;
          state.documentReviewPollErrorCount = 0;
          setStatus("adapter 已重启，原文档审查任务已中断，请重新提交。");
          setResult("adapter 已重启，原文档审查任务无法恢复。阻塞式模型请求不会伪装为可恢复，请重新提交文档审查。\n任务编号：" + jobId);
          setInterruptedRetryVisible(true);
          stopDocumentReviewWaitFeedback(stopWaiting);
          return;
        }
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
          scheduleDocumentReviewPoll(jobId, stopWaiting, retryDelay, resumeExpected);
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
        stopDocumentReviewWaitFeedback(stopWaiting);
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
    pollDocumentReviewJob(active.jobId, function () {}, true);
  }

  function cancelQueuedDocumentReviewJob() {
    var jobId = state.documentReviewJobId;
    if (!jobId) {
      return;
    }
    setDocumentReviewCancelVisible(true, true);
    setStatus("正在取消排队中的文档审查任务...");
    request("/word/document-review/jobs/" + encodeURIComponent(jobId) + "?resume=1", null, {
      method: "DELETE",
      timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (state.documentReviewJobId !== jobId) {
        return;
      }
      if (job.status === "cancelled") {
        finishCancelledDocumentReview(jobId);
        return;
      }
      renderDocumentReviewJobProgress(job, jobId);
    }).catch(function (error) {
      if (state.documentReviewJobId !== jobId) {
        return;
      }
      if (error && error.adapterCode === "LONG_TASK_NOT_CANCELLABLE") {
        setDocumentReviewCancelVisible(false);
        setStatus("文档审查已经开始运行，模型后台无法可靠取消。");
        return;
      }
      setDocumentReviewCancelVisible(true, false);
      setStatus("取消排队任务失败：" + describeDocumentReviewPollError(error));
    });
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

  function writingTaskLabel(taskType) {
    return taskType === "word.smart_imitation" ? "智能仿写" : "智能编写";
  }

  function writingJobPath(taskType) {
    return taskType === "word.smart_imitation"
      ? "/word/smart-imitation/jobs"
      : "/word/smart-write/jobs";
  }

  function setWritingJob(jobId, taskType, mode) {
    state.writingJobId = jobId || "";
    state.writingJobTaskType = jobId ? taskType : "";
    state.writingJobMode = jobId ? mode : "";
    setModelTaskBusy(Boolean(jobId));
    if (!jobId) {
      setDocumentReviewCancelVisible(false);
    }
    renderWorkflowProfileStrip();
  }

  function renderWritingJobProgress(job, taskType, jobId) {
    var label = writingTaskLabel(taskType);
    var phaseText = DOCUMENT_REVIEW_PHASE_TEXT[job.phase] || job.phase || "等待状态更新";
    var lines = [];
    if (job.status === "queued") {
      setStatus(label + "正在排队，当前位置：" + (job.queuePosition || 1) + "。");
      lines.push(label + "已进入共享任务队列。", "排队位置：" + (job.queuePosition || 1));
    } else {
      setStatus(label + "正在处理，当前阶段：" + phaseText + "。");
      lines.push(job.runningMessage || ("模型后台正在处理" + label + "。"), "当前阶段：" + phaseText);
    }
    lines.push("总耗时：" + Number(job.elapsedSeconds || 0) + " 秒", "任务编号：" + jobId);
    setDocumentReviewCancelVisible(job.status === "queued" && job.canCancel, false);
    setPlainResult(lines.join("\n"));
  }

  function completeWritingJob(result, traceId, taskType, resumed) {
    var label = writingTaskLabel(taskType);
    setWritingJob("", "", "");
    state.writingJobStartedAt = 0;
    state.writingJobPollErrorCount = 0;
    state.pendingApplyAction = taskType === "word.smart_write" && !resumed && state.latestDocumentPayload
      ? "rewrite"
      : "";
    state.rewriteResult = setSmartWriteResult(result || {}, taskType);
    setApplyEnabled(state.pendingApplyAction === "rewrite");
    setTrace(traceId || "");
    if (taskType === "word.smart_imitation") {
      hideCompareForSmartImitation();
    }
    setStatus(label + "结果已生成。" + (resumed && taskType === "word.smart_write" ? "为保护原选区，本次恢复结果仅供预览和复制。" : ""));
  }

  function isFatalWritingPollError(error) {
    var code = error && error.adapterCode || "";
    return code.indexOf("SMART_WRITE_JOB_") === 0 ||
      code.indexOf("SMART_IMITATION_JOB_") === 0 ||
      code === "LONG_TASK_QUEUE_FULL" ||
      code === "REQUEST_VALIDATION_FAILED";
  }

  function scheduleWritingPoll(jobId, taskType, mode, resumed, delayMs) {
    setTimeout(function () {
      pollWritingJob(jobId, taskType, mode, resumed);
    }, delayMs);
  }

  function pollWritingJob(jobId, taskType, mode, resumed) {
    if (!jobId || state.writingJobId !== jobId) {
      return;
    }
    request(writingJobPath(taskType) + "/" + encodeURIComponent(jobId) + "?resume=1", null, {
      timeoutMs: WRITING_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (state.writingJobId !== jobId) {
        return;
      }
      state.writingJobPollErrorCount = 0;
      saveWritingActiveJob({
        jobId: jobId,
        taskType: taskType,
        mode: mode,
        traceId: body.traceId || job.traceId || "",
        startedAt: state.writingJobStartedAt || Date.now()
      });
      if (job.status === "completed") {
        clearWritingActiveJob(jobId);
        completeWritingJob(job.result || {}, body.traceId || job.traceId || jobId, taskType, resumed);
        return;
      }
      if (job.status === "cancelled") {
        clearWritingActiveJob(jobId);
        setWritingJob("", "", "");
        setStatus("排队中的" + writingTaskLabel(taskType) + "任务已取消。");
        setPlainResult("排队任务已取消，未调用模型后台。\n任务编号：" + jobId);
        return;
      }
      if (job.status === "failed") {
        clearWritingActiveJob(jobId);
        setWritingJob("", "", "");
        setStatus(writingTaskLabel(taskType) + "失败：" + ((job.error && job.error.message) || "后台任务执行失败。"));
        setResult((job.error && job.error.message) || "后台任务执行失败。");
        return;
      }
      renderWritingJobProgress(job, taskType, jobId);
      scheduleWritingPoll(jobId, taskType, mode, resumed, WRITING_POLL_INTERVAL_MS);
    }).catch(function (error) {
      if (state.writingJobId !== jobId) {
        return;
      }
      state.writingJobPollErrorCount += 1;
      if (isFatalWritingPollError(error)) {
        clearWritingActiveJob(jobId);
        setWritingJob("", "", "");
        setStatus(writingTaskLabel(taskType) + "任务无法恢复：" + describeFetchError(error));
        setResult(describeFetchError(error));
        return;
      }
      setStatus(writingTaskLabel(taskType) + "状态查询暂时失败，将继续自动刷新。");
      setPlainResult([
        "状态查询暂时未连上本地 adapter；这不代表模型后台任务失败。",
        "已重试：" + state.writingJobPollErrorCount,
        "任务编号：" + jobId,
        "最近错误：" + describeFetchError(error)
      ].join("\n"));
      scheduleWritingPoll(jobId, taskType, mode, resumed, WRITING_POLL_RETRY_DELAY_MS);
    });
  }

  function startWritingJob(payload, taskType, mode) {
    var active = loadWritingActiveJob();
    var jobId;
    var startedAt;
    if (state.writingJobId || (active && active.jobId)) {
      setModelTaskBusy(false);
      setStatus("已有写作任务尚未结束，请等待当前任务完成。");
      return;
    }
    jobId = buildWritingClientJobId(taskType);
    startedAt = Date.now();
    payload.clientJobId = jobId;
    setWritingJob(jobId, taskType, mode);
    state.writingJobStartedAt = startedAt;
    state.writingJobPollErrorCount = 0;
    saveWritingActiveJob({ jobId: jobId, taskType: taskType, mode: mode, startedAt: startedAt });
    request(writingJobPath(taskType), payload, { timeoutMs: WRITING_POLL_REQUEST_TIMEOUT_MS })
      .then(function (body) {
        var job = body.data || {};
        var returnedJobId = job.jobId || jobId;
        if (state.writingJobId !== jobId) {
          return;
        }
        setWritingJob(returnedJobId, taskType, mode);
        setTrace(body.traceId || job.traceId || returnedJobId);
        saveWritingActiveJob({
          jobId: returnedJobId,
          taskType: taskType,
          mode: mode,
          traceId: body.traceId || job.traceId || "",
          startedAt: startedAt
        });
        if (job.status === "completed") {
          clearWritingActiveJob(returnedJobId);
          completeWritingJob(job.result || {}, body.traceId || job.traceId || returnedJobId, taskType, false);
          return;
        }
        renderWritingJobProgress(job, taskType, returnedJobId);
        pollWritingJob(returnedJobId, taskType, mode, false);
      }).catch(function (error) {
        if (state.writingJobId !== jobId) {
          return;
        }
        if (isFatalWritingPollError(error)) {
          clearWritingActiveJob(jobId);
          setWritingJob("", "", "");
          setStatus(writingTaskLabel(taskType) + "提交失败：" + describeFetchError(error));
          setResult(describeFetchError(error));
          return;
        }
        setStatus(writingTaskLabel(taskType) + "提交响应未确认，正在按任务编号恢复查询...");
        pollWritingJob(jobId, taskType, mode, false);
      });
  }

  function resumeWritingActiveJob() {
    var active = loadWritingActiveJob();
    if (!active || !active.jobId || active.mode !== state.currentMode) {
      return;
    }
    setWritingJob(active.jobId, active.taskType, active.mode);
    state.writingJobStartedAt = active.startedAt || Date.now();
    state.writingJobPollErrorCount = 0;
    setTrace(active.traceId || active.jobId);
    setApplyEnabled(false);
    setStatus("已恢复未完成的" + writingTaskLabel(active.taskType) + "任务，正在查询结果...");
    setPlainResult("检测到未完成的写作任务，将继续查询 adapter 后台状态。\n任务编号：" + active.jobId);
    pollWritingJob(active.jobId, active.taskType, active.mode, true);
  }

  function cancelQueuedWritingJob() {
    var jobId = state.writingJobId;
    var taskType = state.writingJobTaskType;
    if (!jobId || !taskType) {
      return;
    }
    setDocumentReviewCancelVisible(true, true);
    request(writingJobPath(taskType) + "/" + encodeURIComponent(jobId) + "?resume=1", null, {
      method: "DELETE",
      timeoutMs: WRITING_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (job.status === "cancelled") {
        clearWritingActiveJob(jobId);
        setWritingJob("", "", "");
        setStatus("排队中的" + writingTaskLabel(taskType) + "任务已取消。");
        setPlainResult("排队任务已取消，未调用模型后台。\n任务编号：" + jobId);
        return;
      }
      renderWritingJobProgress(job, taskType, jobId);
    }).catch(function (error) {
      setDocumentReviewCancelVisible(true, false);
      setStatus("取消排队任务失败：" + describeFetchError(error));
    });
  }

  function extractFullDocumentReviewBody() {
    var document = getActiveDocument();
    var paragraphs;
    var tables;
    var body;
    if (!document) {
      throw new Error("未检测到活动文档。");
    }
    paragraphs = helpers.collectFullDocumentReviewParagraphs
      ? helpers.collectFullDocumentReviewParagraphs(document)
      : collectParagraphs(document, {
        avoidFallbackTextRead: true,
        excludeTableParagraphs: true
      });
    tables = helpers.collectFullDocumentReviewTables
      ? helpers.collectFullDocumentReviewTables(document)
      : [];
    body = helpers.buildFullDocumentReviewBody({
      paragraphs: paragraphs,
      tables: tables
    }, 120000);
    body.documentId = "wps-document-" + helpers.sha256Text(getDocumentName(document)).slice(0, 24);
    body.editSignal = helpers.readFullDocumentReviewEditSignal
      ? helpers.readFullDocumentReviewEditSignal(document)
      : "";
    body.batches = helpers.buildFullDocumentReviewBatches
      ? helpers.buildFullDocumentReviewBatches(body, 3500)
      : [{
        sequence: 0,
        batchId: "batch-0",
        blocks: body.blocks,
        characterCount: body.reviewCharacterCount,
        contentSha256: body.contentSha256
      }];
    return body;
  }

  function markFullDocumentReviewAnchorVerification(jobId, issueId, verification) {
    if (!jobId || !issueId || (verification !== "verified" && verification !== "unverified")) {
      return Promise.resolve();
    }
    return request(
      "/word/document-review/full/jobs/" + encodeURIComponent(jobId) +
        "/issues/" + encodeURIComponent(issueId),
      { anchorVerification: verification },
      { method: "PATCH", timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS }
    );
  }

  function locateFullDocumentReviewIssue(issue, jobId) {
    var document = getActiveDocument();
    var anchor = issue && issue.sourceAnchor || {};
    var originalText;
    var location = String(anchor.location || issue && issue.location || "body");
    var target;
    var range;
    var text;
    var occurrences = [];
    var index;
    var start;
    var end;
    var expectedOffset;
    var nearbyOccurrences;
    var paragraphs;
    var tables;
    var table;
    var rows;
    var row;
    var cells;
    function failLocation(message) {
      if (issue) {
        issue.anchorVerification = "unverified";
      }
      setStatus(message);
      markFullDocumentReviewAnchorVerification(jobId, issue && issue.issueId, "unverified")
        .catch(function () {
          setStatus(message + "（定位状态未能写回服务器。）");
        });
      return false;
    }
    if (!document || String(issue && issue.anchorVerification || "") !== "verified") {
      return failLocation("该问题的原文锚点未通过快照校验，未自动跳转。");
    }
    originalText = String(issue && issue.originalText || "");
    if (!document || !originalText) {
      return failLocation("缺少可验证的原文锚点，未自动定位。");
    }
    if (location === "table") {
      tables = readValue(document, "Tables") || readValue(document, "tables") || [];
      var tablePath = Array.isArray(anchor.tablePath) && anchor.tablePath.length
        ? anchor.tablePath : [{ tableIndex: Number(anchor.tableIndex || 0) }];
      table = helpers.getCollectionItem
        ? helpers.getCollectionItem(tables, Number(tablePath[0].tableIndex || 0))
        : null;
      for (var pathIndex = 1; table && pathIndex < tablePath.length; pathIndex += 1) {
        var parentPath = tablePath[pathIndex];
        var parentRows = readValue(table, "Rows") || readValue(table, "rows") || [];
        var parentRow = helpers.getCollectionItem
          ? helpers.getCollectionItem(parentRows, Number(parentPath.rowIndex || 0))
          : null;
        var parentCells = parentRow && (readValue(parentRow, "Cells") || readValue(parentRow, "cells") || []);
        var parentCell = helpers.getCollectionItem
          ? helpers.getCollectionItem(parentCells, Number(parentPath.columnIndex || 0))
          : null;
        var nestedTables = parentCell && (readValue(parentCell, "Tables") || readValue(parentCell, "tables") || []);
        table = helpers.getCollectionItem
          ? helpers.getCollectionItem(nestedTables, Number(parentPath.tableIndex || 0))
          : null;
      }
      rows = table && (readValue(table, "Rows") || readValue(table, "rows") || []);
      row = helpers.getCollectionItem
        ? helpers.getCollectionItem(rows, Number(anchor.rowIndex || 0))
        : null;
      cells = row && (readValue(row, "Cells") || readValue(row, "cells") || []);
      target = helpers.getCollectionItem
        ? helpers.getCollectionItem(cells, Number(anchor.columnIndex || 0))
        : null;
      range = getRangeFromTarget(target);
    } else {
      paragraphs = getParagraphs(document);
      target = helpers.getCollectionItem
        ? helpers.getCollectionItem(paragraphs, Number(anchor.paragraphIndex || 0))
        : null;
      range = getRangeFromTarget(target);
    }
    text = String(readValue(range, "Text") || readValue(range, "text") || "")
      .replace(/[\r\u0007]+$/g, "");
    if (!range) {
      return failLocation("原文结构单元已不存在，未自动跳转。");
    }
    index = text.indexOf(originalText);
    while (index >= 0) {
      occurrences.push(index);
      index = text.indexOf(originalText, index + Math.max(originalText.length, 1));
    }
    expectedOffset = Number(issue && issue.anchorStart);
    if (isFinite(expectedOffset) && expectedOffset >= 0 &&
        text.slice(expectedOffset, expectedOffset + originalText.length) === originalText) {
      occurrences = [expectedOffset];
    } else {
      nearbyOccurrences = occurrences.filter(function (candidate) {
        return isFinite(expectedOffset) && Math.abs(candidate - expectedOffset) <= 512;
      });
      occurrences = nearbyOccurrences;
    }
    if (occurrences.length !== 1) {
      return failLocation("原文无法在预期" + (location === "table" ? "表格单元格" : "段落") + "内唯一匹配，未自动跳转。");
    }
    index = occurrences[0];
    start = Number(readValue(range, "Start"));
    if (isNaN(start)) {
      return failLocation("当前 WPS 未提供可验证的原文范围，未自动跳转。");
    }
    end = start + index + originalText.length;
    try {
      if (typeof range.SetRange === "function") {
        range.SetRange(start + index, end);
      } else if (typeof range.setRange === "function") {
        range.setRange(start + index, end);
      } else {
        return failLocation("当前 WPS 不支持保守范围定位。");
      }
      if (typeof range.Select === "function") {
        range.Select();
      } else if (typeof range.select === "function") {
        range.select();
      }
      issue.anchorVerification = "verified";
      setStatus("已按原始范围或预期附近的唯一原文匹配定位；文档变化后仍以人工复核为准。");
      return true;
    } catch (error) {
      return failLocation("原文定位失败，未修改文档正文。");
    }
  }

  function renderFullDocumentReviewIssuePage(report, pageData, jobId) {
    var snapshot = report && report.snapshot || {};
    var coverage = report && report.coverage || {};
    var capacity = report && report.capacity || {};
    var issues = pageData && Array.isArray(pageData.items) ? pageData.items : [];
    var excludedRegions = Array.isArray(coverage.excludedRegions) ? coverage.excludedRegions : [];
    var lines = [
      "# 全篇审查报告",
      "",
      report && report.summary || "审查已完成。",
      report && report.globalSummary ? "\n## 跨片全局结论\n" + report.globalSummary : "",
      report && Array.isArray(report.globalFindings) && report.globalFindings.length
        ? "\n## 跨片发现\n" + report.globalFindings.map(function (finding) {
          return "- [" + (finding.severity || "未标注") + "] " +
            (finding.summary || "") + "（" + (finding.findingId || "未标识") + "）";
        }).join("\n") : "",
      "",
      "## 快照与覆盖",
      "- 快照编号：" + (snapshot.snapshotId || "未记录"),
      "- 快照哈希：" + String(snapshot.contentSha256 || "").slice(0, 16),
      "- 已审查字符：" + Number(coverage.reviewedCharacterCount || 0),
      "- 已审查段落：" + Number(coverage.reviewedParagraphCount || 0),
      "- 已审查表格：" + Number(coverage.reviewedTableCount || 0),
      "- 已审查单元格：" + Number(coverage.reviewedCellCount || 0),
      "- 容量等级：" + (capacity.label || capacity.tier || "未记录"),
      "- 初始分片估算：" + Number(capacity.initialChunkCount || 0),
      "- 调用上限：" + Number(capacity.callLimit || 0),
      "- 覆盖状态：" + (coverage.status === "complete" ? "声明范围覆盖完整" : "覆盖未完成"),
      "- 问题枚举：" + (report && report.enumerationStatus === "complete" ? "完整" : "受限"),
      "- 未审查区域：" + (excludedRegions.length ? excludedRegions.join("、") : "未披露"),
      "",
      "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部问题。",
      "",
      "## 问题清单（第 " + Number(pageData && pageData.page || 1) + " 页，共 " +
        Number(pageData && pageData.total || 0) + " 项）"
    ];
    if (!issues.length) {
      lines.push("未返回结构化问题；这不表示文档不存在其他问题。");
    }
    issues.forEach(function (issue) {
      lines.push("");
      lines.push("### " + (issue.issueId || "未标识问题") + " · " + (issue.problem || "审查问题"));
      lines.push("- 严重程度：" + (issue.severity || "未标注"));
      lines.push("- 处理状态：" + (issue.status || "open"));
      lines.push("- 问题类别：" + (issue.category || "未标注"));
      lines.push("- 原文锚点：" + (issue.anchorId || "未标注"));
      lines.push("- 原文：" + (issue.originalText || "未提供"));
      lines.push("- 建议：" + (issue.suggestion || "请人工复核。"));
      if (issue.suggestedRewrite) {
        lines.push("- 建议改写：" + issue.suggestedRewrite);
      }
    });
    if (pageData && pageData.nextCursor) {
      lines.push("");
      lines.push("下一页游标：" + pageData.nextCursor);
    }
    setResult(lines.join("\n"), lines.join("\n"));
    setStatus("全篇审查只读报告已生成。");
    var controls = byId("full-document-review-issue-controls");
    var previous = byId("btn-full-review-previous-page");
    var next = byId("btn-full-review-next-page");
    var exportJson = byId("btn-full-review-export-json");
    var exportMarkdown = byId("btn-full-review-export-markdown");
    var pageStatus = byId("full-review-page-status");
    var actions = byId("full-review-issue-actions");
    var filterNames = ["severity", "category", "location", "status", "sort"];
    if (!controls || !previous || !next || !exportJson || !exportMarkdown ||
        !pageStatus || !actions) {
      return;
    }
    controls.hidden = false;
    filterNames.forEach(function (name) {
      var select = byId("full-review-filter-" + name);
      var value = state.fullDocumentReviewIssueFilters[name] || "";
      if (select && select.value !== value) {
        select.value = value;
      }
    });
    pageStatus.textContent = "第 " + Number(pageData && pageData.page || 1) + " 页，共 " +
      Number(pageData && pageData.total || 0) + " 项";
    previous.disabled = state.fullDocumentReviewIssueCursorHistory.length <= 1;
    next.disabled = !pageData.nextCursor;
    exportJson.onclick = function () {
      downloadFullDocumentReviewExport(jobId, "json");
    };
    exportMarkdown.onclick = function () {
      downloadFullDocumentReviewExport(jobId, "markdown");
    };
    previous.onclick = function () {
      var history = state.fullDocumentReviewIssueCursorHistory;
      if (history.length <= 1) {
        return;
      }
      history.pop();
      loadFullDocumentReviewIssuePage(jobId, report, history[history.length - 1]);
    };
    next.onclick = function () {
      if (!pageData.nextCursor) {
        return;
      }
      state.fullDocumentReviewIssueCursorHistory.push(pageData.nextCursor);
      loadFullDocumentReviewIssuePage(jobId, report, pageData.nextCursor);
    };
    actions.textContent = "";
    issues.forEach(function (issue) {
      var row = document.createElement("div");
      var locate = document.createElement("button");
      var copyOriginal = document.createElement("button");
      var copySuggestion = document.createElement("button");
      var processed = document.createElement("button");
      var ignored = document.createElement("button");
      row.className = "full-review-issue-row";
      row.textContent = (issue.issueId || "问题") + "［" +
        (issue.category || "未分类") + "／" + (issue.severity || "未标注") + "］：" +
        (issue.problem || "审查问题") +
        (issue.duplicateGroupSize > 1 ? "（重复组 " + issue.duplicateGroupSize + " 处）" : "") +
        (issue.anchorVerification !== "verified" ? "（锚点未验证）" : "");
      locate.type = "button";
      locate.textContent = "定位原文";
      copyOriginal.type = "button";
      copyOriginal.textContent = "复制原文";
      copySuggestion.type = "button";
      copySuggestion.textContent = "复制建议";
      processed.type = "button";
      processed.textContent = "标记已处理";
      ignored.type = "button";
      ignored.textContent = "标记已忽略";
      processed.disabled = issue.status === "processed";
      ignored.disabled = issue.status === "ignored";
      locate.addEventListener("click", function () {
        locateFullDocumentReviewIssue(issue, jobId);
      });
      copyOriginal.addEventListener("click", function () {
        writeClipboardText(issue.originalText || "", "原文已复制。");
      });
      copySuggestion.addEventListener("click", function () {
        writeClipboardText(issue.suggestion || "", "修改建议已复制。");
      });
      processed.addEventListener("click", function () {
        updateFullDocumentReviewIssueStatus(jobId, issue.issueId, "processed")
          .then(function () {
            loadFullDocumentReviewIssuePage(jobId, report, pageData._cursor || "");
          });
      });
      ignored.addEventListener("click", function () {
        updateFullDocumentReviewIssueStatus(jobId, issue.issueId, "ignored")
          .then(function () {
            loadFullDocumentReviewIssuePage(jobId, report, pageData._cursor || "");
          });
      });
      row.appendChild(locate);
      row.appendChild(copyOriginal);
      row.appendChild(copySuggestion);
      if (issue.suggestedRewrite) {
        var copyRewrite = document.createElement("button");
        copyRewrite.type = "button";
        copyRewrite.textContent = "复制改写";
        copyRewrite.addEventListener("click", function () {
          writeClipboardText(issue.suggestedRewrite, "建议改写已复制。");
        });
        row.appendChild(copyRewrite);
      }
      row.appendChild(processed);
      row.appendChild(ignored);
      actions.appendChild(row);
    });
  }

  function loadFullDocumentReviewIssuePage(jobId, report, cursor) {
    var filters = state.fullDocumentReviewIssueFilters || {};
    var path = "/word/document-review/full/jobs/" + encodeURIComponent(jobId) +
      "/issues?pageSize=20&sort=" + encodeURIComponent(filters.sort || "source");
    ["severity", "category", "location", "status"].forEach(function (name) {
      if (filters[name]) {
        path += "&" + name + "=" + encodeURIComponent(filters[name]);
      }
    });
    if (cursor) {
      path += "&cursor=" + encodeURIComponent(cursor);
    }
    return request(path, null, {
      timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var pageData = body.data || {};
      pageData._cursor = cursor || "";
      state.fullDocumentReviewIssueJobId = jobId;
      state.fullDocumentReviewIssueReport = report;
      renderFullDocumentReviewIssuePage(report, pageData, jobId);
    });
  }

  function updateFullDocumentReviewIssueStatus(jobId, issueId, status) {
    if (!jobId || !issueId || (status !== "processed" && status !== "ignored" && status !== "open")) {
      return Promise.reject(new Error("全篇审查问题状态参数无效。"));
    }
    return request(
      "/word/document-review/full/jobs/" + encodeURIComponent(jobId) +
        "/issues/" + encodeURIComponent(issueId),
      { status: status },
      { method: "PATCH", timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS }
    );
  }

  function changeFullDocumentReviewIssueFilter(name, value) {
    if (!state.fullDocumentReviewIssueFilters ||
        ["severity", "category", "location", "status", "sort"].indexOf(name) < 0) {
      return;
    }
    state.fullDocumentReviewIssueFilters[name] = String(value || "");
    state.fullDocumentReviewIssueCursorHistory = [""];
    if (state.fullDocumentReviewIssueJobId && state.fullDocumentReviewIssueReport) {
      loadFullDocumentReviewIssuePage(
        state.fullDocumentReviewIssueJobId,
        state.fullDocumentReviewIssueReport,
        ""
      ).catch(function (error) {
        setStatus("问题筛选读取失败：" + describeFetchError(error));
      });
    }
  }

  function downloadFullDocumentReviewExport(jobId, format) {
    var path = "/word/document-review/full/jobs/" + encodeURIComponent(jobId) +
      "/report?format=" + encodeURIComponent(format);
    return fetch(ADAPTER_BASE_URL + path).then(function (response) {
      if (!response.ok) {
        return response.json().then(function (body) {
          throw new Error(body.message || "全篇审查报告导出失败。");
        });
      }
      return format === "markdown" ? response.text() : response.json();
    }).then(function (body) {
      var extension = format === "markdown" ? "md" : "json";
      var text = format === "markdown" ? body : JSON.stringify(body.data || body, null, 2);
      var blob = new Blob([text], { type: format === "markdown" ? "text/markdown" : "application/json" });
      var objectUrl = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = objectUrl;
      link.download = "word-full-review." + extension;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    }).catch(function (error) {
      setStatus("全篇审查报告导出失败：" + describeFetchError(error));
    });
  }

  function markDeterministicFormatReviewAnchorVerification(jobId, issueId, verification) {
    if (!jobId || !issueId || ["verified", "unverified"].indexOf(verification) < 0) {
      return Promise.resolve();
    }
    return request(
      "/word/format-review/jobs/" + encodeURIComponent(jobId) +
        "/issues/" + encodeURIComponent(issueId),
      { anchorVerification: verification },
      { method: "PATCH", timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS }
    );
  }

  function locateDeterministicFormatReviewIssue(issue, jobId) {
    var document = getActiveDocument();
    var anchor = issue && issue.sourceAnchor || {};
    var identity = state.deterministicFormatReviewDocumentIdentity || {};
    var currentName = getDocumentName(document);
    var currentHostId = String(readValue(document, "Id") || readValue(document, "ID") || currentName);
    var target;
    var range;
    var paragraphs;
    var text;
    var expectedText = String(anchor.text || "");
    var paragraphIndex = Number(anchor.paragraphIndex);
    var start;
    var occurrences = [];
    var index;
    var adjacentIds;
    var currentAdjacentIds;
    function failLocation(message) {
      if (issue) {
        issue.anchorVerification = "unverified";
      }
      setStatus(message);
      markDeterministicFormatReviewAnchorVerification(jobId, issue && issue.issueId, "unverified")
        .catch(function () {});
      return false;
    }
    if (!document || String(issue && issue.anchorVerification || "") !== "verified" ||
        !expectedText || !anchor.textSha256 || !anchor.adjacentStructureSha256) {
      return failLocation("该格式问题缺少可验证锚点，未自动跳转。");
    }
    if ((identity.hostDocumentId && String(identity.hostDocumentId) !== currentHostId) ||
        (identity.documentIdSha256 && helpers.sha256Text(currentName) !== identity.documentIdSha256)) {
      return failLocation("当前文档身份与格式审查快照不一致，未自动跳转。");
    }
    paragraphs = getParagraphs(document);
    target = helpers.getCollectionItem
      ? helpers.getCollectionItem(paragraphs, paragraphIndex)
      : null;
    range = getRangeFromTarget(target);
    if (!range) {
      return failLocation("格式审查锚点对应的段落已不存在，未自动跳转。");
    }
    text = String(readValue(range, "Text") || readValue(range, "text") || "")
      .replace(/[\r\u0007]+$/g, "");
    if (helpers.sha256Text(text) !== String(anchor.textSha256)) {
      return failLocation("格式审查锚点文本已变化，未自动跳转。");
    }
    adjacentIds = Array.isArray(anchor.adjacentBlockIds) ? anchor.adjacentBlockIds : [];
    currentAdjacentIds = [];
    [-1, 0, 1].forEach(function (offset) {
      var neighbor = helpers.getCollectionItem
        ? helpers.getCollectionItem(paragraphs, paragraphIndex + offset)
        : null;
      var neighborId = neighbor && (readValue(neighbor, "BlockId") || readValue(neighbor, "blockId") ||
        readValue(neighbor, "Id") || readValue(neighbor, "ID"));
      if (neighborId) {
        currentAdjacentIds.push(String(neighborId));
      }
    });
    if (adjacentIds.length && (currentAdjacentIds.length !== adjacentIds.length ||
        helpers.sha256Text(JSON.stringify(currentAdjacentIds)) !== String(anchor.adjacentStructureSha256))) {
      return failLocation("格式审查锚点相邻结构无法唯一验证，未自动跳转。");
    }
    index = text.indexOf(expectedText);
    while (index >= 0) {
      occurrences.push(index);
      index = text.indexOf(expectedText, index + Math.max(expectedText.length, 1));
    }
    if (occurrences.length !== 1) {
      return failLocation("格式审查锚点文本无法唯一匹配，未自动跳转。");
    }
    start = Number(readValue(range, "Start"));
    if (isNaN(start)) {
      return failLocation("当前 WPS 未提供可验证的格式范围，未自动跳转。");
    }
    try {
      if (typeof range.SetRange === "function") {
        range.SetRange(start + occurrences[0], start + occurrences[0] + expectedText.length);
      } else if (typeof range.setRange === "function") {
        range.setRange(start + occurrences[0], start + occurrences[0] + expectedText.length);
      } else {
        return failLocation("当前 WPS 不支持保守范围定位。");
      }
      if (typeof range.Select === "function") {
        range.Select();
      } else if (typeof range.select === "function") {
        range.select();
      }
      setStatus("已通过文档身份、文本和相邻结构验证，定位到格式问题原文。");
      return true;
    } catch (error) {
      return failLocation("格式问题定位失败，未修改文档正文。");
    }
  }

  function renderDeterministicFormatReviewIssuePage(report, pageData, jobId) {
    var summary = report && report.summary || {};
    var coverage = report && report.coverage || {};
    var issues = pageData && Array.isArray(pageData.items) ? pageData.items : [];
    var lines = [
      "# 格式审查报告",
      "",
      "执行状态：" + (summary.executionStatus || "未记录"),
      "合规状态：" + (summary.complianceStatus || "未评估"),
      "覆盖状态：" + (summary.coverageStatus || coverage.status || "未评估"),
      "语义增强状态：" + (summary.semanticStatus || "未运行"),
      "问题数量：" + Number(report && report.issueCount || 0) +
        "｜重复问题组：" + Number(report && report.duplicateGroupCount || 0),
      "覆盖说明：" + (report && report.disclaimer || "覆盖完整不承诺检出全部问题。"),
      "",
      "## 问题清单（第 " + Number(pageData && pageData.page || 1) + " 页，共 " +
        Number(pageData && pageData.total || 0) + " 项）"
    ];
    if (!issues.length) {
      lines.push("当前筛选条件下没有问题实例；零问题不单独形成通过结论。");
    }
    issues.forEach(function (issue) {
      lines.push("");
      lines.push("### " + (issue.issueId || "未标识问题") + " · " + (issue.ruleId || "未标识规则"));
      lines.push("- 锚点：" + (issue.anchorId || "未标注") + "／" + (issue.propertyPath || "未标注"));
      lines.push("- 当前值：" + (issue.currentValue === undefined ? "未读取" : String(issue.currentValue)));
      lines.push("- 期望值：" + (issue.expectedValue === undefined ? "未给出" : String(issue.expectedValue)));
      lines.push("- 证据：" + (issue.evidence || "未提供"));
      lines.push("- 规则版本：" + (issue.ruleVersion || "未记录"));
      lines.push("- 数据状态／处理状态：" + (issue.dataStatus || "未标注") + "／" + (issue.status || "open"));
      lines.push("- 锚点验证：" + (issue.anchorVerification || "unverified"));
      if (Number(issue.duplicateGroupSize || 0) > 1) {
        lines.push("- 重复问题组：" + issue.duplicateGroupSize + " 个实例");
      }
    });
    setResult(lines.join("\n"), lines.join("\n"));
    setStatus("确定性格式审查只读报告已生成。");
    var controls = byId("deterministic-format-review-issue-controls");
    var previous = byId("btn-format-review-previous-page");
    var next = byId("btn-format-review-next-page");
    var pageStatus = byId("format-review-page-status");
    var exportJson = byId("btn-format-review-export-json");
    var exportMarkdown = byId("btn-format-review-export-markdown");
    var actions = byId("format-review-issue-actions");
    if (!controls || !previous || !next || !pageStatus || !exportJson || !exportMarkdown || !actions) {
      return;
    }
    controls.hidden = false;
    ["rule", "severity", "dataStatus", "sort"].forEach(function (name) {
      var field = byId("format-review-filter-" + name.replace("dataStatus", "data-status"));
      if (field && field.value !== String(state.deterministicFormatReviewIssueFilters[name] || "")) {
        field.value = state.deterministicFormatReviewIssueFilters[name] || "";
      }
    });
    pageStatus.textContent = "第 " + Number(pageData && pageData.page || 1) + " 页，共 " +
      Number(pageData && pageData.total || 0) + " 项";
    previous.disabled = state.deterministicFormatReviewIssueCursorHistory.length <= 1;
    next.disabled = !pageData.nextCursor;
    exportJson.onclick = function () { downloadDeterministicFormatReviewExport(jobId, "json"); };
    exportMarkdown.onclick = function () { downloadDeterministicFormatReviewExport(jobId, "markdown"); };
    previous.onclick = function () {
      var history = state.deterministicFormatReviewIssueCursorHistory;
      if (history.length <= 1) { return; }
      history.pop();
      loadDeterministicFormatReviewIssuePage(jobId, report, history[history.length - 1]);
    };
    next.onclick = function () {
      if (!pageData.nextCursor) { return; }
      state.deterministicFormatReviewIssueCursorHistory.push(pageData.nextCursor);
      loadDeterministicFormatReviewIssuePage(jobId, report, pageData.nextCursor);
    };
    actions.textContent = "";
    issues.forEach(function (issue) {
      var row = document.createElement("div");
      var locate = document.createElement("button");
      var processed = document.createElement("button");
      var ignored = document.createElement("button");
      row.className = "full-review-issue-row";
      row.textContent = (issue.issueId || "问题") + "［" + (issue.ruleId || "未分类") + "／" +
        (issue.propertyPath || "未标注") + "］" + (issue.anchorVerification === "verified" ? "" : "（锚点未验证）");
      locate.type = "button";
      locate.textContent = "定位原文";
      processed.type = "button";
      processed.textContent = "标记已处理";
      ignored.type = "button";
      ignored.textContent = "标记已忽略";
      locate.addEventListener("click", function () { locateDeterministicFormatReviewIssue(issue, jobId); });
      processed.disabled = issue.status === "processed";
      ignored.disabled = issue.status === "ignored";
      processed.addEventListener("click", function () {
        updateDeterministicFormatReviewIssueStatus(jobId, issue.issueId, "processed");
      });
      ignored.addEventListener("click", function () {
        updateDeterministicFormatReviewIssueStatus(jobId, issue.issueId, "ignored");
      });
      row.appendChild(locate);
      row.appendChild(processed);
      row.appendChild(ignored);
      actions.appendChild(row);
    });
  }

  function loadDeterministicFormatReviewIssuePage(jobId, report, cursor) {
    var filters = state.deterministicFormatReviewIssueFilters || {};
    var path = "/word/format-review/jobs/" + encodeURIComponent(jobId) +
      "/issues?pageSize=20&sort=" + encodeURIComponent(filters.sort || "source");
    if (filters.rule) { path += "&ruleId=" + encodeURIComponent(filters.rule); }
    if (filters.severity) { path += "&severity=" + encodeURIComponent(filters.severity); }
    if (filters.dataStatus) { path += "&dataStatus=" + encodeURIComponent(filters.dataStatus); }
    if (cursor) { path += "&cursor=" + encodeURIComponent(cursor); }
    return request(path, null, { timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS }).then(function (body) {
      var pageData = body.data || {};
      pageData._cursor = cursor || "";
      state.deterministicFormatReviewIssueJobId = jobId;
      state.deterministicFormatReviewReport = report;
      renderDeterministicFormatReviewIssuePage(report, pageData, jobId);
    });
  }

  function loadDeterministicFormatReviewReport(jobId) {
    return request("/word/format-review/jobs/" + encodeURIComponent(jobId) + "/report?format=summary", null, {
      timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var report = body.data || {};
      state.deterministicFormatReviewIssueCursorHistory = [""];
      return loadDeterministicFormatReviewIssuePage(jobId, report, "");
    });
  }

  function updateDeterministicFormatReviewIssueStatus(jobId, issueId, status) {
    if (!jobId || !issueId || ["open", "processed", "ignored"].indexOf(status) < 0) {
      return Promise.reject(new Error("格式审查问题状态参数无效。"));
    }
    return request(
      "/word/format-review/jobs/" + encodeURIComponent(jobId) + "/issues/" + encodeURIComponent(issueId),
      { status: status },
      { method: "PATCH", timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS }
    ).then(function () {
      return loadDeterministicFormatReviewIssuePage(
        jobId, state.deterministicFormatReviewReport,
        state.deterministicFormatReviewIssueCursorHistory.slice(-1)[0] || ""
      );
    });
  }

  function changeDeterministicFormatReviewIssueFilter(name, value) {
    if (!state.deterministicFormatReviewIssueFilters ||
        ["rule", "severity", "dataStatus", "sort"].indexOf(name) < 0) {
      return;
    }
    state.deterministicFormatReviewIssueFilters[name] = String(value || "");
    state.deterministicFormatReviewIssueCursorHistory = [""];
    if (state.deterministicFormatReviewIssueJobId && state.deterministicFormatReviewReport) {
      loadDeterministicFormatReviewIssuePage(
        state.deterministicFormatReviewIssueJobId,
        state.deterministicFormatReviewReport,
        ""
      ).catch(function (error) { setStatus("格式问题筛选读取失败：" + describeFetchError(error)); });
    }
  }

  function downloadDeterministicFormatReviewExport(jobId, format) {
    var path = "/word/format-review/jobs/" + encodeURIComponent(jobId) +
      "/report?format=" + encodeURIComponent(format);
    return fetch(ADAPTER_BASE_URL + path).then(function (response) {
      if (!response.ok) {
        return response.json().then(function (body) { throw new Error(body.message || "格式审查报告导出失败。"); });
      }
      return format === "markdown" ? response.text() : response.json();
    }).then(function (body) {
      var extension = format === "markdown" ? "md" : "json";
      var text = format === "markdown" ? body : JSON.stringify(body.data || body, null, 2);
      var blob = new Blob([text], { type: format === "markdown" ? "text/markdown" : "application/json" });
      var objectUrl = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = objectUrl;
      link.download = "word-format-review." + extension;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    }).catch(function (error) { setStatus("格式审查报告导出失败：" + describeFetchError(error)); });
  }

  function renderFullDocumentReviewReport(report, jobId) {
    var snapshot = report && report.snapshot || {};
    var coverage = report && report.coverage || {};
    var excludedRegions = Array.isArray(coverage.excludedRegions) ? coverage.excludedRegions : [];
    var enumerationStatus = report && report.enumerationStatus || "limited";
    var issueEnumerationLabel = "问题枚举：" +
      (enumerationStatus === "complete" ? "完整" : "受限");
    var disclaimer = report && report.disclaimer ||
      "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部问题。";
    state.fullDocumentReviewReportMetadata = {
      snapshotId: snapshot.snapshotId || "",
      coverageStatus: coverage.status || "",
      excludedRegions: excludedRegions,
      issueEnumeration: issueEnumerationLabel,
      disclaimer: disclaimer
    };
    state.fullDocumentReviewIssueFilters = {
      severity: "",
      category: "",
      location: "",
      status: "",
      sort: "source"
    };
    state.fullDocumentReviewIssueCursorHistory = [""];
    return loadFullDocumentReviewIssuePage(jobId, report, "");
  }

  function pollFullDocumentReviewJob(jobId) {
    if (!jobId || state.fullDocumentReviewJobId !== jobId) {
      return;
    }
    request("/word/document-review/full/jobs/" + encodeURIComponent(jobId), null, {
      timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (state.fullDocumentReviewJobId !== jobId) {
        return;
      }
      if (job.status === "completed") {
        return request("/word/document-review/full/jobs/" + encodeURIComponent(jobId) + "/report", null, {
          timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
        }).then(function (reportBody) {
          state.fullDocumentReviewJobId = "";
          state.fullDocumentReviewPollErrorCount = 0;
          clearFullDocumentReviewActiveJob(jobId);
          setModelTaskBusy(false);
          setDocumentReviewCancelVisible(false, false);
          renderFullDocumentReviewEntry();
          renderFullDocumentReviewReport(reportBody.data || {}, jobId).catch(function (error) {
            setStatus("全篇审查报告分页读取失败：" + describeFetchError(error));
          });
        });
      }
      if (job.status === "failed" || job.status === "cancelled") {
        var terminalMessage = job.error && job.error.message || "全篇审查未生成报告。";
        state.fullDocumentReviewJobId = "";
        state.fullDocumentReviewPollErrorCount = 0;
        clearFullDocumentReviewActiveJob(jobId);
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        renderFullDocumentReviewEntry();
        setStatus(job.status === "cancelled" ? "全篇审查已取消。" : "全篇审查失败：" + terminalMessage);
        setResult(terminalMessage);
        return;
      }
      setDocumentReviewCancelVisible(Boolean(job.canCancel), false);
      state.fullDocumentReviewPollErrorCount = 0;
      setStatus("全篇审查：" + (DOCUMENT_REVIEW_PHASE_TEXT[job.phase] || job.phase || "处理中"));
      setTimeout(function () {
        pollFullDocumentReviewJob(jobId);
      }, DOCUMENT_REVIEW_POLL_INTERVAL_MS);
    }).catch(function (error) {
      if (state.fullDocumentReviewJobId !== jobId) {
        return;
      }
      if (isFullDocumentReviewPermanentPollError(error)) {
        state.fullDocumentReviewJobId = "";
        state.fullDocumentReviewPollErrorCount = 0;
        clearFullDocumentReviewActiveJob(jobId);
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        renderFullDocumentReviewEntry();
        setStatus(Number(error.httpStatus) === 404
          ? "原全篇审查任务不存在或已过期，请重新发起。"
          : "原全篇审查任务已无法继续查询，请检查配置后重新发起。");
        setResult(describeFetchError(error));
        return;
      }
      state.fullDocumentReviewPollErrorCount += 1;
      setStatus("全篇审查连接暂时中断，正在保留任务并重试：" + describeFetchError(error));
      setTimeout(function () {
        pollFullDocumentReviewJob(jobId);
      }, Math.min(30000, DOCUMENT_REVIEW_POLL_INTERVAL_MS *
        Math.pow(2, Math.min(state.fullDocumentReviewPollErrorCount, 4))));
    });
  }

  function extractFullDocumentReviewBodyYielding() {
    return new Promise(function (resolve, reject) {
      setTimeout(function () {
        try {
          resolve(extractFullDocumentReviewBody());
        } catch (error) {
          reject(error);
        }
      }, 0);
    });
  }

  function uploadFullDocumentReviewBatches(session, body) {
    var batches = Array.isArray(body && body.batches) ? body.batches : [];
    return batches.reduce(function (promise, batch) {
      return promise.then(function () {
        return new Promise(function (resolve) {
          setTimeout(resolve, 0);
        });
      }).then(function () {
        ensureFullDocumentReviewPreparation(body.editSignal);
        return request(
          "/word/document-review/full/snapshots/" + encodeURIComponent(session.sessionId) +
            "/batches/" + batch.sequence,
          {
            uploadToken: session.uploadToken,
            batchId: batch.batchId,
            blocks: batch.blocks,
            characterCount: batch.characterCount,
            contentSha256: batch.contentSha256,
            structureSha256: batch.structureSha256,
            range: batch.range,
            editSequence: body.editSignal
          },
          { method: "PUT" }
        );
      });
    }, Promise.resolve());
  }

  function ensureFullDocumentReviewPreparation(editSignal) {
    var document;
    var currentSignal;
    if (state.fullDocumentReviewCancelRequested) {
      throw new Error("已取消全篇审查准备，未调用模型。");
    }
    document = getActiveDocument();
    currentSignal = helpers.readFullDocumentReviewEditSignal
      ? helpers.readFullDocumentReviewEditSignal(document)
      : "";
    if (editSignal && currentSignal !== editSignal) {
      throw new Error("检测到文档在全篇审查准备期间被编辑，已停止并清理快照。");
    }
  }

  function runFullDocumentReview() {
    var readiness = getFullDocumentReviewReadiness();
    var firstPass;
    var session = null;
    var firstPassStartedAt = Date.now();
    if (!state.fullDocumentReviewEnabled || !readiness.fullDocumentReviewReady) {
      setStatus(readiness.label || "全篇审查尚未就绪。");
      return;
    }
    if (state.fullDocumentReviewJobId || state.documentReviewJobId) {
      setStatus("已有文档审查任务尚未结束。");
      return;
    }
    setModelTaskBusy(true);
    state.fullDocumentReviewPreparing = true;
    state.fullDocumentReviewCancelRequested = false;
    setDocumentReviewCancelVisible(true, false);
    renderFullDocumentReviewEntry();
    setStatus("正在执行第一遍轻量抽取...");
    return extractFullDocumentReviewBodyYielding().then(function (body) {
      firstPass = body;
      ensureFullDocumentReviewPreparation(firstPass.editSignal);
      firstPass.firstPassDurationMs = Date.now() - firstPassStartedAt;
      setStatus("正在创建全篇审查快照...");
      return request("/word/document-review/full/snapshots", {
        documentId: firstPass.documentId,
        documentType: state.technicalDocumentType,
        reviewPrompt: state.technicalReviewPrompt,
        writingPolicyScene: getWritingPolicyScene(),
        coverage: {
          includedRegions: ["body", "tables"],
          excludedRegions: ["headers", "footers", "footnotes", "endnotes", "comments",
            "revisions", "textBoxes", "shapes", "images", "formulas", "charts",
            "attachments", "hiddenText"]
        }
      });
    }).then(function (body) {
      session = body.data || {};
      ensureFullDocumentReviewPreparation(firstPass.editSignal);
      return uploadFullDocumentReviewBatches(session, firstPass);
    }).then(function () {
      setStatus("正在执行第二遍轻量哈希验证...");
      firstPass.secondPassStartedAt = Date.now();
      ensureFullDocumentReviewPreparation(firstPass.editSignal);
      return extractFullDocumentReviewBodyYielding();
    }).then(function (secondPass) {
      secondPass.secondPassDurationMs = Date.now() - firstPass.secondPassStartedAt;
      if (firstPass.contentSha256 !== secondPass.contentSha256 ||
          firstPass.structureSha256 !== secondPass.structureSha256 ||
          firstPass.reviewCharacterCount !== secondPass.reviewCharacterCount ||
          firstPass.blocks.length !== secondPass.blocks.length ||
          firstPass.tableCount !== secondPass.tableCount ||
          firstPass.cellCount !== secondPass.cellCount ||
          firstPass.batches.length !== secondPass.batches.length ||
          firstPass.editSignal !== secondPass.editSignal) {
        throw new Error("两遍正文与表格校验不一致，请停止编辑后重新发起全篇审查。");
      }
      return request(
        "/word/document-review/full/snapshots/" + encodeURIComponent(session.sessionId) + "/commit",
        {
          uploadToken: session.uploadToken,
          batchCount: firstPass.batches.length,
          reviewCharacterCount: firstPass.reviewCharacterCount,
          contentSha256: firstPass.contentSha256,
          verificationSha256: secondPass.contentSha256,
          verification: {
            batchCount: secondPass.batches.length,
            reviewCharacterCount: secondPass.reviewCharacterCount,
            contentSha256: secondPass.contentSha256,
            structureSha256: secondPass.structureSha256,
            blockCount: secondPass.blocks.length,
            tableCount: secondPass.tableCount,
            cellCount: secondPass.cellCount,
            editSequence: secondPass.editSignal
          }
        }
      );
    }).then(function (body) {
      var snapshot = body.data || {};
      var capacity = snapshot.capacity || {};
      ensureFullDocumentReviewPreparation(firstPass.editSignal);
      session.snapshotToken = snapshot.snapshotToken;
      setStatus("快照完成：" + firstPass.reviewCharacterCount + " 个审查字符，初始约 " +
        Number(capacity.initialChunkCount || 0) + " 个分片，调用上限 " +
        Number(capacity.callLimit || 0) + " 次。");
      if (capacity.requiresConfirmation) {
        setStatus("大型文档已冻结，等待确认后才会调用模型。");
        if (typeof window === "undefined" || typeof window.confirm !== "function" ||
            !window.confirm("本次全篇审查将处理 " + firstPass.reviewCharacterCount +
              " 个审查字符，初始约 " + capacity.initialChunkCount +
              " 个分片，调用上限 " + capacity.callLimit + " 次。是否继续？")) {
          throw new Error("已取消大型全篇审查，快照未调用模型并将清理。");
        }
      }
      return request("/word/document-review/full/jobs", {
        snapshotId: snapshot.snapshotId,
        snapshotToken: session.snapshotToken,
        confirmLarge: Boolean(capacity.requiresConfirmation),
        confirmationToken: snapshot.confirmationToken || ""
      });
    }).then(function (body) {
      var job = body.data || {};
      if (!job.jobId) {
        throw new Error("Adapter 未返回全篇审查任务编号。");
      }
      state.fullDocumentReviewPreparing = false;
      state.fullDocumentReviewCancelRequested = false;
      state.fullDocumentReviewJobId = job.jobId;
      state.fullDocumentReviewPollErrorCount = 0;
      saveFullDocumentReviewActiveJob(job.jobId);
      renderFullDocumentReviewEntry();
      setStatus("全篇审查任务已提交。");
      pollFullDocumentReviewJob(job.jobId);
    }).catch(function (error) {
      var cleanup = Promise.resolve();
      if (session && session.sessionId && session.uploadToken) {
        cleanup = request(
          "/word/document-review/full/snapshots/" + encodeURIComponent(session.sessionId),
          { uploadToken: session.uploadToken, snapshotToken: session.snapshotToken },
          { method: "DELETE" }
        ).catch(function () { return null; });
      }
      return cleanup.then(function () {
        state.fullDocumentReviewJobId = "";
        state.fullDocumentReviewPollErrorCount = 0;
        state.fullDocumentReviewPreparing = false;
        state.fullDocumentReviewCancelRequested = false;
        clearFullDocumentReviewActiveJob();
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        renderFullDocumentReviewEntry();
        setStatus("全篇审查失败：" + describeFetchError(error));
        setResult(describeFetchError(error));
      });
    });
  }

  function cancelFullDocumentReviewJob() {
    var jobId = state.fullDocumentReviewJobId;
    if (!jobId) {
      return;
    }
    request("/word/document-review/full/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: DOCUMENT_REVIEW_POLL_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (body.data && body.data.status === "cancelled") {
        state.fullDocumentReviewJobId = "";
        state.fullDocumentReviewPollErrorCount = 0;
        clearFullDocumentReviewActiveJob(jobId);
        setModelTaskBusy(false);
        renderFullDocumentReviewEntry();
        setStatus("排队中的全篇审查任务已取消。");
      }
    }).catch(function (error) {
      setStatus("取消全篇审查失败：" + describeFetchError(error));
    });
  }

  function cancelFullDocumentReviewPreparation() {
    state.fullDocumentReviewCancelRequested = true;
    setStatus("正在取消全篇审查准备并清理暂存快照...");
  }

  function resumeFullDocumentReviewActiveJob() {
    var active = loadFullDocumentReviewActiveJob();
    if (!state.fullDocumentReviewEnabled || !active || !active.jobId) {
      return false;
    }
    state.fullDocumentReviewJobId = active.jobId;
    state.fullDocumentReviewPollErrorCount = 0;
    setModelTaskBusy(true);
    renderFullDocumentReviewEntry();
    setStatus("正在续查未完成的全篇审查任务...");
    pollFullDocumentReviewJob(active.jobId);
    return true;
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
    var scope;
    if (state.documentReviewJobId) {
      setStatus("已有文档审查任务尚未结束，请等待当前任务完成。排队任务可使用“取消排队任务”。");
      return;
    }
    scope = resolveSelectionScope(false);
    resetSmartWritePreviewState();
    resetDocumentReviewState();
    clearDocumentReviewActiveJob();
    if (!scope.ok) {
      setStatus(scope.message);
      setResult(scope.message);
      return;
    }

    setModelTaskBusy(true);
    setStatus("正在读取文档审查范围...");
    setPlainResult("正在读取文档审查范围，请稍候。");
    setApplyEnabled(false);

    setTimeout(function () {
      var stopWaiting;
      var clientJobId;
      var startedAt;
      try {
        state.latestDocumentPayload = extractDocument(scope.selectionMode, null, DOCUMENT_REVIEW_EXTRACTION_OPTIONS);
        state.latestDocumentPayload.writingPolicyScene = getWritingPolicyScene();
        state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
      } catch (error) {
        setModelTaskBusy(false);
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus("正在提交文档审查请求...");
      setPlainResult("文档审查请求已提交，正在等待模型后台返回。");
      stopWaiting = startDocumentReviewWaitFeedback();
      state.documentReviewStopWaiting = stopWaiting;
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
            stopDocumentReviewWaitFeedback(stopWaiting);
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
            stopDocumentReviewWaitFeedback(stopWaiting);
            completeDocumentReview(job.result || {}, body.traceId || job.traceId || jobId);
            return;
          }
          renderDocumentReviewJobProgress(job, jobId);
          pollDocumentReviewJob(state.documentReviewJobId, stopWaiting, true);
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
            stopDocumentReviewWaitFeedback(stopWaiting);
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
          pollDocumentReviewJob(clientJobId, stopWaiting, false);
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

    setModelTaskBusy(true);
    setStatus("正在读取格式审查范围...");
    setResult("正在读取格式审查范围，请稍候。");
    setApplyEnabled(false);

    setTimeout(function () {
      try {
        state.latestDocumentPayload = extractDocument(scope.selectionMode, null, FORMAT_REVIEW_EXTRACTION_OPTIONS);
        state.latestDocumentPayload.options.templateId = "technical-file-format-requirements";
        state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
      } catch (error) {
        setModelTaskBusy(false);
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus("正在执行格式审查...");
      request("/word/format-review", state.latestDocumentPayload)
        .then(function (body) {
          setModelTaskBusy(false);
          state.pendingApplyAction = "";
          setApplyEnabled(false);
          setTrace(body.traceId);
          setResult(renderGroupedFormatReview(body.data || {}));
          setStatus("格式审查完成。");
        })
        .catch(function (error) {
          var message = describeFetchError(error);
          setModelTaskBusy(false);
          setStatus("格式审查失败：" + message);
          setResult(message);
        });
    }, 0);
  }

  function pollDeterministicFormatReviewJob(jobId) {
    request("/word/format-review/jobs/" + encodeURIComponent(jobId), null, {
      timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      var job = body.data || {};
      if (state.deterministicFormatReviewJobId !== jobId) {
        return;
      }
      setTrace(body.traceId || job.traceId || jobId);
      if (job.status === "completed") {
        loadDeterministicFormatReviewReport(jobId).then(function () {
          state.deterministicFormatReviewJobId = "";
          state.deterministicFormatReviewSnapshot = null;
          setModelTaskBusy(false);
          setDocumentReviewCancelVisible(false, false);
          setStatus("确定性格式审查完成，结构化报告已生成。");
        }).catch(function (error) {
          state.deterministicFormatReviewJobId = "";
          state.deterministicFormatReviewSnapshot = null;
          setModelTaskBusy(false);
          setDocumentReviewCancelVisible(false, false);
          setStatus("确定性格式审查完成，但报告读取失败：" + describeFetchError(error));
          setResult(renderGroupedFormatReview(job.result || {}));
        });
        return;
      }
      if (job.status === "failed" || job.status === "cancelled") {
        state.deterministicFormatReviewJobId = "";
        state.deterministicFormatReviewSnapshot = null;
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        setStatus("确定性格式审查" + (job.status === "cancelled" ? "已取消。" : "失败。"));
        setResult(job.error && job.error.message || "确定性格式审查后台任务执行失败，请重试。");
        return;
      }
      setStatus(job.runningMessage || "正在执行确定性格式审查...");
      setPlainResult("确定性格式审查任务已提交，正在按本地规则生成结构化结果。\n任务编号：" + jobId);
      setTimeout(function () {
        pollDeterministicFormatReviewJob(jobId);
      }, DETERMINISTIC_FORMAT_REVIEW_POLL_INTERVAL_MS);
    }).catch(function (error) {
      if (state.deterministicFormatReviewJobId !== jobId) {
        return;
      }
      state.deterministicFormatReviewJobId = "";
      state.deterministicFormatReviewSnapshot = null;
      setModelTaskBusy(false);
      setDocumentReviewCancelVisible(false, false);
      setStatus("确定性格式审查失败：" + describeFetchError(error));
      setResult(describeFetchError(error));
    });
  }

  function cancelDeterministicFormatReviewJob() {
    var jobId = state.deterministicFormatReviewJobId;
    if (!jobId) {
      return;
    }
    setDocumentReviewCancelVisible(true, true);
    request("/word/format-review/jobs/" + encodeURIComponent(jobId), null, {
      method: "DELETE",
      timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS
    }).then(function (body) {
      if (body.data && body.data.status === "cancelled") {
        state.deterministicFormatReviewJobId = "";
        state.deterministicFormatReviewSnapshot = null;
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        setStatus("确定性格式审查任务已取消，未保留问题实例。");
        setPlainResult("确定性格式审查任务已取消。");
        return;
      }
      setStatus("已请求取消确定性格式审查任务，正在等待后台确认。");
    }).catch(function (error) {
      setDocumentReviewCancelVisible(true, false);
      setStatus("取消确定性格式审查失败：" + describeFetchError(error));
    });
  }

  function discardDeterministicFormatReviewSnapshot() {
    var snapshot = state.deterministicFormatReviewSnapshot;
    state.deterministicFormatReviewSnapshot = null;
    if (!snapshot || !snapshot.snapshotId || !(snapshot.snapshotToken || snapshot.uploadToken)) {
      return;
    }
    request(
      "/word/format-review/snapshots/" + encodeURIComponent(snapshot.snapshotId),
      { snapshotToken: snapshot.snapshotToken || snapshot.uploadToken },
      {
        method: "DELETE",
        timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS
      }
    ).catch(function () {
      // The adapter also expires abandoned snapshots; cleanup must not hide the original error.
    });
  }

  function extractDeterministicFormatReviewSnapshot(scope) {
    var document = getActiveDocument();
    var payload;
    var documentName;
    var editSequence;
    var documentIdentity;
    var tables = [];
    var contextBlocks = [];
    if (!document) {
      throw new Error("未检测到活动文档。");
    }
    payload = extractDocument(
      scope.selectionMode,
      null,
      DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS
    );
    documentName = getDocumentName(document);
    editSequence = helpers.readFullDocumentReviewEditSignal
      ? helpers.readFullDocumentReviewEditSignal(document)
      : "";
    documentIdentity = {
      documentIdSha256: helpers.sha256Text(documentName).slice(0, 64),
      hostDocumentId: String(readValue(document, "Id") || readValue(document, "ID") || documentName)
    };
    if (helpers.collectFullDocumentReviewTables) {
      if (scope.selectionMode === "selection") {
        var selectionSources = getSelectionSources(document);
        for (var sourceIndex = 0; sourceIndex < selectionSources.length; sourceIndex += 1) {
          var selectedTables = helpers.collectFullDocumentReviewTables(
            selectionSources[sourceIndex], DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS
          );
          if (selectedTables.length) {
            tables = selectedTables;
            break;
          }
        }
      } else {
        tables = helpers.collectFullDocumentReviewTables(
          document, DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS
        );
      }
    }
    payload.content.documentStructure = payload.content.documentStructure || {};
    payload.content.documentStructure.tables = tables;
    if (scope.selectionMode === "selection" && helpers.collectParagraphs) {
      var selectedIndexes = (payload.content.paragraphs || []).map(function (paragraph) {
        return Number(paragraph.index || 0);
      }).filter(function (index) { return index > 0; });
      var semanticIndexes = selectedIndexes.concat(tables.map(function (table) {
        return Number(table.paragraphIndex || 0);
      }).filter(function (index) { return index > 0; }));
      if (semanticIndexes.length) {
        helpers.collectParagraphs(document, {
          maxParagraphTextLength: 500,
          avoidFallbackTextRead: true
        }).forEach(function (paragraph) {
          var paragraphIndex = Number(paragraph.index || 0);
          var styleName = String(paragraph.styleName || paragraph.style_name || "");
          var paragraphText = String(paragraph.text || "").trim();
          var isCaption = /caption|题注/i.test(styleName) ||
            /^(图|表)\s*[0-9０-９一二三四五六七八九十]+[：:.、\s]/.test(paragraphText);
          if (selectedIndexes.indexOf(paragraphIndex) < 0 && isCaption && semanticIndexes.some(function (index) {
            return Math.abs(paragraphIndex - index) <= 1;
          })) {
            payload.content.paragraphs.push({
              index: paragraphIndex,
              text: paragraphText,
              styleName: paragraph.styleName || paragraph.style_name || "Caption",
              fontName: paragraph.fontName || paragraph.font_name || "",
              fontSize: paragraph.fontSize,
              bold: Boolean(paragraph.bold),
              italic: Boolean(paragraph.italic),
              underline: paragraph.underline,
              alignment: paragraph.alignment || "",
              outlineLevel: paragraph.outlineLevel || 0,
              captionFor: paragraph.captionFor || "",
              range: { paragraphIndex: paragraphIndex }
            });
          } else if (selectedIndexes.length && selectedIndexes.indexOf(paragraphIndex) < 0 &&
              Math.abs(paragraphIndex - selectedIndexes[0]) <= 1) {
            contextBlocks.push({
              blockId: "format-context-paragraph-" + paragraphIndex,
              paragraphIndex: paragraphIndex,
              text: paragraph.text || "",
              format: {
                styleName: paragraph.styleName || "",
                outlineLevel: paragraph.outlineLevel || 0,
                dataStatus: "context_only"
              },
              range: { paragraphIndex: paragraphIndex }
            });
          }
        });
      }
    }
    return helpers.buildDeterministicFormatReviewBody(payload, {
      contextBlocks: contextBlocks,
      documentIdentity: documentIdentity,
      editSequence: editSequence,
      coverage: helpers.collectFormatReviewCoverage
        ? helpers.collectFormatReviewCoverage(document) : {},
      scope: {
        mode: scope.selectionMode,
        expandedToSemanticUnits: scope.selectionMode === "selection",
        selectedTextSha256: scope.selectionMode === "selection"
          ? helpers.sha256Text(scope.selectedText || getSelectionText(document)) : "",
        contextOnly: contextBlocks.map(function (block) { return block.blockId; })
      }
    });
  }

  function ensureDeterministicFormatReviewPreparation(editSequence, documentIdentity) {
    var document = getActiveDocument();
    var currentSequence;
    var currentName;
    if (!document) {
      throw new Error("活动文档已关闭，已安全中止格式审查并清理快照。");
    }
    currentSequence = helpers.readFullDocumentReviewEditSignal
      ? helpers.readFullDocumentReviewEditSignal(document)
      : "";
    currentName = getDocumentName(document);
    if (String(editSequence || "") !== String(currentSequence || "") ||
        String(documentIdentity && documentIdentity.hostDocumentId || "") !==
          String(readValue(document, "Id") || readValue(document, "ID") || currentName)) {
      throw new Error("检测到文档编辑或文档身份变化，已安全中止格式审查并清理快照。");
    }
  }

  function uploadDeterministicFormatReviewBatches(session, body) {
    var batches = Array.isArray(body && body.batches) ? body.batches : [];
    return batches.reduce(function (promise, batch) {
      return promise.then(function () {
        return new Promise(function (resolve) { setTimeout(resolve, 0); });
      }).then(function () {
        ensureDeterministicFormatReviewPreparation(body.editSequence, body.documentIdentity);
        return request(
          "/word/format-review/snapshots/" + encodeURIComponent(session.snapshotId) +
            "/batches/" + batch.sequence,
          {
            uploadToken: session.uploadToken || session.snapshotToken,
            batchId: batch.batchId,
            blocks: batch.blocks,
            characterCount: batch.characterCount,
            contentSha256: batch.contentSha256,
            structureSha256: batch.structureSha256,
            formatSha256: batch.formatSha256,
            range: batch.range,
            editSequence: body.editSequence
          },
          { method: "PUT", timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS }
        );
      });
    }, Promise.resolve());
  }

  function runDeterministicFormatReview() {
    var scope;
    var firstPass;
    var session = null;
    // Extraction is bounded by DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS.
    if (!state.deterministicFormatReviewEnabled) {
      setStatus("确定性格式审查功能尚未启用。");
      return;
    }
    if (state.deterministicFormatReviewJobId || state.modelTaskBusy) {
      setStatus("已有格式审查任务正在执行，请等待当前任务完成。");
      return;
    }
    scope = resolveSelectionScope(false);
    if (!scope.ok) {
      setStatus(scope.message);
      setResult(scope.message);
      return;
    }
    setModelTaskBusy(true);
    setStatus("正在执行第一遍格式语义抽取...");
    setPlainResult("正在分批读取格式语义单元，请稍候。不会修改 Word 文档。");
    setTimeout(function () {
      try {
        firstPass = extractDeterministicFormatReviewSnapshot(scope);
        firstPass.batches = helpers.buildDeterministicFormatReviewBatches(firstPass, 3500);
        ensureDeterministicFormatReviewPreparation(firstPass.editSequence, firstPass.documentIdentity);
        state.deterministicFormatReviewDocumentIdentity = firstPass.documentIdentity;
        state.latestSelectionMode = firstPass.selectionMode;
      } catch (error) {
        setModelTaskBusy(false);
        setStatus(error.message);
        setResult(error.message);
        return;
      }
      setStatus("正在创建格式快照会话...");
      request("/word/format-review/snapshots", {
        documentId: firstPass.documentId,
        selectionMode: firstPass.selectionMode,
        documentIdentity: firstPass.documentIdentity,
        editSequence: firstPass.editSequence,
        templateId: firstPass.templateId,
        pageSetup: firstPass.pageSetup,
        scope: firstPass.scope,
        coverage: firstPass.coverage
      }, {
        timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS
      }).then(function (snapshotBody) {
        session = snapshotBody.data || {};
        state.deterministicFormatReviewSnapshot = session;
        setTrace(snapshotBody.traceId || session.snapshotId || "");
        setStatus("正在上传第一遍格式事实，共 " + firstPass.batches.length + " 个批次...");
        return uploadDeterministicFormatReviewBatches(session, firstPass);
      }).then(function () {
        setStatus("正在执行第二遍格式结构与指纹验证...");
        ensureDeterministicFormatReviewPreparation(firstPass.editSequence, firstPass.documentIdentity);
        return new Promise(function (resolve, reject) {
          setTimeout(function () {
            try {
              resolve(extractDeterministicFormatReviewSnapshot(scope));
            } catch (error) {
              reject(error);
            }
          }, 0);
        });
      }).then(function (secondPass) {
        secondPass.batches = helpers.buildDeterministicFormatReviewBatches(secondPass, 3500);
        if (firstPass.contentSha256 !== secondPass.contentSha256 ||
            firstPass.structureSha256 !== secondPass.structureSha256 ||
            firstPass.formatSha256 !== secondPass.formatSha256 ||
            firstPass.reviewCharacterCount !== secondPass.reviewCharacterCount ||
            firstPass.blocks.length !== secondPass.blocks.length ||
            JSON.stringify(firstPass.coverage) !== JSON.stringify(secondPass.coverage) ||
            firstPass.batches.length !== secondPass.batches.length ||
            firstPass.editSequence !== secondPass.editSequence ||
            JSON.stringify(firstPass.documentIdentity) !== JSON.stringify(secondPass.documentIdentity)) {
          throw new Error("两遍格式结构、对象、覆盖或格式指纹不一致，请停止编辑后重新发起格式审查。");
        }
        return request(
          "/word/format-review/snapshots/" + encodeURIComponent(session.snapshotId) + "/commit",
          {
            uploadToken: session.uploadToken || session.snapshotToken,
            batchCount: firstPass.batches.length,
            blockCount: firstPass.blocks.length,
            reviewCharacterCount: firstPass.reviewCharacterCount,
            contentSha256: firstPass.contentSha256,
            structureSha256: firstPass.structureSha256,
            formatSha256: firstPass.formatSha256,
            coverage: firstPass.coverage,
            verification: {
              batchCount: secondPass.batches.length,
              blockCount: secondPass.blocks.length,
              reviewCharacterCount: secondPass.reviewCharacterCount,
              contentSha256: secondPass.contentSha256,
              structureSha256: secondPass.structureSha256,
              formatSha256: secondPass.formatSha256,
              documentIdentity: secondPass.documentIdentity,
              editSequence: secondPass.editSequence,
              coverage: secondPass.coverage
            }
          },
          { method: "POST", timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS }
        );
      }).then(function (commitBody) {
        var committed = commitBody.data || {};
        state.deterministicFormatReviewSnapshot = committed;
        state.deterministicFormatReviewJobId = "format-client-" +
          Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
        setTrace(commitBody.traceId || committed.snapshotId || "");
        setStatus("正在提交确定性格式审查后台任务...");
        return request("/word/format-review/jobs", {
          snapshotId: committed.snapshotId,
          snapshotToken: committed.snapshotToken,
          clientJobId: state.deterministicFormatReviewJobId
        }, { timeoutMs: DETERMINISTIC_FORMAT_REVIEW_REQUEST_TIMEOUT_MS });
      }).then(function (jobBody) {
        var job = jobBody.data || {};
        var requestedJobId = state.deterministicFormatReviewJobId;
        var jobId = job.jobId || requestedJobId || jobBody.traceId;
        if (!jobId) {
          throw new Error("adapter 未返回确定性格式审查任务编号。");
        }
        state.deterministicFormatReviewJobId = jobId;
        setDocumentReviewCancelVisible(true, false);
        pollDeterministicFormatReviewJob(jobId);
      }).catch(function (error) {
        state.deterministicFormatReviewJobId = "";
        discardDeterministicFormatReviewSnapshot();
        setModelTaskBusy(false);
        setDocumentReviewCancelVisible(false, false);
        setStatus("确定性格式审查失败：" + describeFetchError(error));
        setResult(describeFetchError(error));
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
    setModelTaskBusy(true);
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
        setModelTaskBusy(false);
        setStatus(error.message);
        setResult(error.message);
        return;
      }

      setStatus(config.runningText);
      startWritingJob(state.latestDocumentPayload, "word.smart_write", "smartWrite");
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
      writingPolicyScene: getWritingPolicyScene(),
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

    setModelTaskBusy(true);
    setStatus(config.runningText);
    setPlainResult("正在生成仿写内容，请稍候。");
    startWritingJob(state.latestDocumentPayload, "word.smart_imitation", "smartImitation");
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
    var taskType = getCurrentWorkflowTaskType();
    var key = helpers.writingPolicySceneStorageKey
      ? helpers.writingPolicySceneStorageKey(taskType)
      : "ai-wps:writing-policy-scene:" + taskType;
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
    var taskType = getCurrentWorkflowTaskType();
    var key = helpers.writingPolicySceneStorageKey
      ? helpers.writingPolicySceneStorageKey(taskType)
      : "ai-wps:writing-policy-scene:" + taskType;
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
    if (state.adapterHealthStatus === "recovery" || !state.modelTasksAllowed) {
      setStatus("Adapter 当前处于恢复模式，模型任务已被安全阻止。");
      return;
    }
    if (state.workflowProfileMutationBusy) {
      setStatus("模型配置正在更新，请稍后再提交任务。");
      return;
    }
    setInterruptedRetryVisible(false);
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
    var writingPolicyLayerButtons = document.querySelectorAll("[data-writing-policy-layer]");
    var writingPolicyLayerIndex;
    byId("btn-open-settings").addEventListener("click", function () {
      toggleSettingsShortcut();
    });
    byId("btn-cancel-document-review-job").addEventListener("click", function () {
      if (state.writingJobId) {
        cancelQueuedWritingJob();
      } else if (state.fullDocumentReviewJobId) {
        cancelFullDocumentReviewJob();
      } else if (state.deterministicFormatReviewJobId) {
        cancelDeterministicFormatReviewJob();
      } else if (state.fullDocumentReviewPreparing) {
        cancelFullDocumentReviewPreparation();
      } else {
        cancelQueuedDocumentReviewJob();
      }
    });
    byId("btn-run-full-document-review").addEventListener("click", runFullDocumentReview);
    byId("btn-run-deterministic-format-review").addEventListener("click", runDeterministicFormatReview);
    ["severity", "category", "location", "status", "sort"].forEach(function (name) {
      byId("full-review-filter-" + name).addEventListener("change", function (event) {
        changeFullDocumentReviewIssueFilter(name, event.target.value);
      });
    });
    byId("format-review-filter-rule").addEventListener("change", function (event) {
      changeDeterministicFormatReviewIssueFilter("rule", event.target.value);
    });
    byId("format-review-filter-severity").addEventListener("change", function (event) {
      changeDeterministicFormatReviewIssueFilter("severity", event.target.value);
    });
    byId("format-review-filter-data-status").addEventListener("change", function (event) {
      changeDeterministicFormatReviewIssueFilter("dataStatus", event.target.value);
    });
    byId("format-review-filter-sort").addEventListener("change", function (event) {
      changeDeterministicFormatReviewIssueFilter("sort", event.target.value);
    });
    byId("btn-resubmit-interrupted-job").addEventListener("click", runPrimaryAction);
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
    byId("btn-recovery-refresh").addEventListener("click", function () {
      refreshConfig({ silent: false });
    });
    byId("btn-recovery-backup").addEventListener("click", createRecoveryBackup);
    byId("btn-recovery-diagnostics").addEventListener("click", exportRecoveryDiagnostics);
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
    document.addEventListener("visibilitychange", syncScopeWatcher);
    byId("workflow-profile-manager").addEventListener("click", handleWorkflowProfileManagerAction);
    byId("workflow-profile-manager").addEventListener("input", markWorkflowProfileEditorDirty);
    byId("workflow-profile-manager").addEventListener("change", handleModelConfigurationEditorChange);
    byId("btn-open-writing-policy-manager").addEventListener("click", openWritingPolicyPresetView);
    for (writingPolicyLayerIndex = 0; writingPolicyLayerIndex < writingPolicyLayerButtons.length; writingPolicyLayerIndex += 1) {
      writingPolicyLayerButtons[writingPolicyLayerIndex].addEventListener("click", handleWritingPolicyLayerClick);
    }
    byId("btn-writing-policy-preset-back").addEventListener("click", function () {
      setWritingPolicyView("home");
    });
    byId("writing-policy-preset-pack-select").addEventListener("change", function (event) {
      selectWritingPolicyPresetPack(event.target.value);
    });
    byId("writing-policy-preset-item-list").addEventListener("click", handleWritingPolicyPresetAction);
    byId("btn-writing-policy-preset-previous").addEventListener("click", function () {
      changeWritingPolicyPresetPage(-1);
    });
    byId("btn-writing-policy-preset-next").addEventListener("click", function () {
      changeWritingPolicyPresetPage(1);
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
    byId("btn-writing-policy-previous").addEventListener("click", function () {
      changeWritingPolicyPage(-1);
    });
    byId("btn-writing-policy-next").addEventListener("click", function () {
      changeWritingPolicyPage(1);
    });
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
    byId("btn-writing-policy-more").addEventListener("click", openWritingPolicyMore);
    byId("btn-writing-policy-more-back").addEventListener("click", closeWritingPolicyMore);
    byId("btn-writing-policy-more-import").addEventListener("click", openWritingPolicyImport);
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
    byId("btn-writing-policy-export-csv").addEventListener("click", function () {
      exportWritingPolicies("csv");
    });
    byId("btn-writing-policy-export-xlsx").addEventListener("click", function () {
      exportWritingPolicies("xlsx");
    });
    byId("btn-writing-policy-download-backup").addEventListener("click", function () {
      runWritingPolicyDownload(
        "/writing-policies/backup",
        "writing-policies-backup.db",
        "写作规范库备份已下载。"
      );
    });
    byId("btn-writing-policy-refresh-diagnostics").addEventListener("click", refreshWritingPolicyDiagnostics);
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
  state.scopeWatcher = helpers.createWordSelectionWatcher({
    intervalMs: 2000,
    getEventSource: getWordSelectionEventSource,
    refresh: updateScopeIndicator
  });
  switchMode(getInitialMode());
  if (!state.settingsRefreshController.isRunning()) {
    refreshConfig({ silent: false });
  }
  syncScopeWatcher();
})();
