(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.12.2-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var TECHNICAL_REVIEW_PROMPTS = {
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
  var DEFAULT_TECHNICAL_REVIEW_PROMPT = TECHNICAL_REVIEW_PROMPTS.technical_solution;
  var REWRITE_STYLE_PROMPTS = {
    default: "使用正式、清晰、简洁的中文表达。",
    formal: "使用正式、清晰、简洁的中文表达。",
    structured: "使用结构清晰、层次分明的中文表达。",
    reporting: "使用更像工作汇报材料的表达，突出结论与执行状态。"
  };
  var REWRITE_FOCUS_PROMPTS = {
    default: "保持内容完整。",
    conclusion: "优先突出结论和关键判断。",
    risk: "优先突出风险、问题与影响。",
    next_step: "优先突出下一步计划和行动项。",
    implementation: "优先突出实施路径、步骤与安排。"
  };
  var REWRITE_LENGTH_PROMPTS = {
    default: "保持原有篇幅附近。",
    concise: "尽量精简表达，避免冗余。",
    same: "保持篇幅基本不变。",
    expanded: "可适度扩写，使表达更完整。"
  };
  var REWRITE_OUTPUT_PROMPT = "不要原样返回待处理内容；只输出最终正文。";
  var fallbackTemplates = [
    { id: "technical-file-format-requirements", name: "技术文件格式及书写要求" },
    { id: "general-office", name: "通用办公模板" }
  ];
  var TASK_API_KEY_DEFS = [
    { taskType: "word.smart_write", label: "智能编写" },
    { taskType: "word.smart_format", label: "智能排版" },
    { taskType: "word.proofread", label: "格式校对" },
    { taskType: "word.technical_review", label: "技术文档审查" }
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
      showPromptFragments: true,
      showTemplate: false
    },
    proofread: {
      title: "格式校对",
      primaryText: "开始校对",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: true
    },
    format: {
      title: "智能排版",
      primaryText: "生成排版预览",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: true,
      showTechnicalReviewOptions: false
    },
    technicalReview: {
      title: "技术文档审查",
      primaryText: "开始审查",
      showRewriteOptions: false,
      showInstruction: false,
      showTemplate: false,
      showTechnicalReviewOptions: true
    },
    settings: {
      title: "设置"
    }
  };
  var state = {
    templates: [],
    selectedTemplateId: "technical-file-format-requirements",
    writeAction: "rewrite",
    rewriteStyle: "default",
    focusPoint: "default",
    lengthMode: "default",
    userInstruction: "",
    technicalDocumentType: "technical_solution",
    technicalReviewPrompt: DEFAULT_TECHNICAL_REVIEW_PROMPT,
    traceId: "",
    pendingApplyAction: "",
    formatChanges: [],
    rewriteResult: null,
    latestDocumentPayload: null,
    latestSelectionMode: "document",
    providerName: "未检测",
    providerBaseUrl: "",
    providerAuthSource: "none",
    taskApiKeys: {},
    currentMode: "smartWrite",
    copyText: "",
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

  function setProviderLine(providerName, configured) {
    var providerText = {
      "enterprise-chat-api": "企业接口",
      "enterprise-dify-chat": "Dify Chat",
      "enterprise-dify-workflow": "Dify 工作流",
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
    renderTaskApiKeys();
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

  function setResult(text) {
    var output = byId("result-output");
    output.hidden = false;
    if (helpers.renderMarkdown) {
      output.innerHTML = helpers.renderMarkdown(text);
    } else {
      output.textContent = text;
    }
    state.copyText = text || "";
  }

  function setRewriteResult(result) {
    setResult(result.rewrittenText || "");
  }

  function setApplyEnabled(enabled) {
    byId("btn-apply").disabled = !enabled;
  }

  function getRewritePromptFragments() {
    return {
      style: REWRITE_STYLE_PROMPTS[state.rewriteStyle] || REWRITE_STYLE_PROMPTS.default,
      focus: REWRITE_FOCUS_PROMPTS[state.focusPoint] || REWRITE_FOCUS_PROMPTS.default,
      length: REWRITE_LENGTH_PROMPTS[state.lengthMode] || REWRITE_LENGTH_PROMPTS.default
    };
  }

  function updateRewritePromptPreview() {
    var fragments = getRewritePromptFragments();
    var shouldShowPromptFragments = state.currentMode === "smartWrite";
    byId("rewrite-prompt-label").textContent = "编写要求";
    byId("prompt-fragment-card").hidden = !shouldShowPromptFragments;
    byId("style-prompt-text").textContent = fragments.style;
    byId("focus-prompt-text").textContent = fragments.focus;
    byId("length-prompt-text").textContent = fragments.length;
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
    byId("task-title").textContent = config.title;

    if (state.currentMode === "settings") {
      switchView("settings");
      return;
    }

    switchView("home");
    byId("rewrite-options").hidden = !config.showRewriteOptions;
    byId("instruction-block").hidden = !config.showInstruction;
    byId("template-options").hidden = !config.showTemplate;
    byId("technical-review-options").hidden = !config.showTechnicalReviewOptions;
    byId("style-field-label").textContent = config.styleLabel || "表达风格";
    byId("btn-run-primary").textContent = config.primaryText;
    updateRewritePromptPreview();
    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("等待操作。");
  }

  function getHostApplication() {
    return window.Application || window.wps || {};
  }

  function getActiveDocument() {
    var app = getHostApplication();
    return app.ActiveDocument || null;
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
    return (document && (document.Paragraphs || document.paragraphs)) || [];
  }

  function getSelectionText(document) {
    return helpers.getEffectiveSelectionText
      ? helpers.getEffectiveSelectionText(getSelectionSources(document))
      : "";
  }

  function getWritableSelection(document) {
    return helpers.getWritableSelection
      ? helpers.getWritableSelection(getSelectionSources(document))
      : (document && document.Selection) || null;
  }

  function collectParagraphs(document) {
    var paragraphs = getParagraphs(document);
    var items = [];
    for (var i = 0; i < paragraphs.length; i += 1) {
      var paragraph = paragraphs[i];
      var font = paragraph.Font || {};
      var paragraphFormat = paragraph.ParagraphFormat || {};
      items.push({
        index: i + 1,
        text: paragraph.Text || paragraph.text || "",
        styleName: paragraph.StyleNameLocal || paragraph.styleName || "Body",
        fontName: font.NameFarEast || font.Name || "",
        fontSize: font.Size || 0,
        bold: Boolean(font.Bold),
        italic: Boolean(font.Italic),
        underline: font.Underline || null,
        alignment: String(paragraphFormat.Alignment || "left"),
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

  function extractDocument(selectionMode, rewriteAction) {
    var document = getActiveDocument();
    if (!document) {
      throw new Error("未检测到活动文档。");
    }

    var paragraphs = collectParagraphs(document);
    var plainText = document.Content && document.Content.Text
      ? document.Content.Text
      : paragraphs.map(function (item) { return item.text; }).join("\n");

    if (selectionMode === "selection") {
      plainText = getSelectionText(document) || plainText;
    }

    var headings = collectHeadings(paragraphs);
    var documentStructure = helpers.buildDocumentStructure
      ? helpers.buildDocumentStructure({
        documentId: document.Name || "unnamed.docx",
        templateId: state.selectedTemplateId,
        selectionMode: selectionMode,
        plainText: plainText,
        pageSetup: collectPageSetup(document),
        paragraphs: paragraphs,
        headings: headings
      })
      : {};

    return {
      documentId: document.Name || "unnamed.docx",
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

  function request(path, payload) {
    var options = {
      method: payload ? "POST" : "GET"
    };

    if (payload) {
      options.headers = {
        "Content-Type": "application/json"
      };
      options.body = JSON.stringify(payload);
    }

    return fetch(ADAPTER_BASE_URL + path, {
      method: options.method,
      headers: options.headers,
      body: options.body
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) || body.message || ("HTTP " + response.status));
        }
        return body;
      });
    });
  }

  function describeFetchError(error) {
    var message = error && error.message ? error.message : String(error || "");
    if (message === "Failed to fetch" || message.indexOf("NetworkError") >= 0) {
      return "插件无法访问 http://127.0.0.1:18100。请确认 adapter 正在运行、端口为 18100，并重新打开任务窗格。";
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
      setStatus("就绪");
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
      setStatus("请输入统一 Dify Chat API Key。");
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

  function getTaskApiKeyStatus(taskType) {
    return state.taskApiKeys[taskType] || {};
  }

  function renderTaskApiKeys() {
    var list = byId("task-api-key-list");
    if (!list) {
      return;
    }
    list.innerHTML = "";
    TASK_API_KEY_DEFS.forEach(function (item) {
      var status = getTaskApiKeyStatus(item.taskType);
      var configured = Boolean(status.taskKeyConfigured);
      var effective = Boolean(status.configured);
      var row = document.createElement("div");
      row.className = "task-route-item";
      row.innerHTML = [
        '<div class="task-route-main">',
        "<strong>" + item.label + "</strong>",
        "<span>" + (configured ? "任务密钥已配置" : (effective ? "使用统一密钥" : "未配置密钥")) + "</span>",
        "</div>",
        '<span class="provider-badge">' + (configured ? "独立" : "兜底") + "</span>",
        '<input type="password" data-task-key-input="' + item.taskType + '" placeholder="粘贴' + item.label + ' API Key" />',
        '<div class="button-row route-actions">',
        '<button type="button" data-save-task-key="' + item.taskType + '">保存密钥</button>',
        '<button type="button" class="ghost-action" data-clear-task-key="' + item.taskType + '">清除</button>',
        "</div>"
      ].join("");
      list.appendChild(row);
    });
  }

  function saveTaskApiKey(taskType) {
    var input = document.querySelector('[data-task-key-input="' + taskType + '"]');
    var apiKey = input ? (input.value || "").trim() : "";
    if (!apiKey) {
      setStatus("请输入任务 API Key。");
      return;
    }
    request("/provider/task-api-key", { taskType: taskType, apiKey: apiKey })
      .then(function () {
        if (input) {
          input.value = "";
        }
        setStatus("任务密钥已保存。");
        return refreshConfig();
      })
      .catch(function (error) {
        setStatus("保存任务密钥失败：" + describeFetchError(error));
      });
  }

  function clearTaskApiKey(taskType) {
    fetch(ADAPTER_BASE_URL + "/provider/task-api-key/" + encodeURIComponent(taskType), {
      method: "DELETE"
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) || body.message || ("HTTP " + response.status));
        }
        return body;
      });
    }).then(function () {
      setStatus("任务密钥已清除。");
      return refreshConfig();
    }).catch(function (error) {
      setStatus("清除任务密钥失败：" + describeFetchError(error));
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

  function renderIssues(issues) {
    if (!issues || !issues.length) {
      return "未发现需要处理的问题。";
    }
    var categoryText = {
      format: "格式合规",
      typo: "错别字",
      grammar: "语病",
      expression: "表述规范",
      logic: "逻辑清晰",
      heading_consistency: "章节命名"
    };
    return issues.map(function (issue) {
      var category = categoryText[issue.category] || issue.category || "格式合规";
      var original = issue.original ? ("原文：" + issue.original) : "";
      var reason = issue.reason ? ("依据：" + issue.reason) : "";
      return [
        "类型：" + category,
        "规则：" + issue.ruleId,
        "级别：" + issue.severity,
        "段落：" + (issue.paragraphIndex || "无"),
        "说明：" + issue.message,
        "建议：" + (issue.suggestion || "无"),
        original,
        reason,
        "可自动修复：" + (issue.autoFixable ? "是" : "否")
      ].filter(Boolean).join(" | ");
    }).join("\n");
  }

  function renderFormatChanges(summary, changes) {
    var lines = [
      "模板：" + summary.templateId,
      "待调整项：" + summary.changeCount
    ];
    var hasCoverageStats = typeof summary.paragraphCount !== "undefined";

    if (hasCoverageStats) {
      lines.push("全文扫描段落：" + summary.paragraphCount);
      lines.push(
        "AI 识别段落：" + (summary.aiClassifiedParagraphCount || 0) +
        " | 本地兜底段落：" + (summary.localFallbackParagraphCount || 0)
      );
    }
    lines.push("识别来源：" + (summary.provider || "local"));
    lines.push("");
    if (hasCoverageStats) {
      lines.push("以下仅显示需要调整的格式项，正文内容不会在预览中改写。");
      lines.push("");
    }

    if (!changes || !changes.length) {
      lines.push("当前文档暂无可预览的排版变更。");
      return lines.join("\n");
    }

    changes.forEach(function (change) {
      lines.push(
        "第 " + change.paragraphIndex + " 段：" +
        change.currentStyle + " → " + change.targetStyle +
        " | 角色：" + (change.role || "未识别") +
        " | " + change.reason
      );
    });

    return lines.join("\n");
  }

  function renderTechnicalReview(data) {
    var categoryText = {
      accuracy: "功能描述准确性",
      terminology: "术语专业性",
      design: "设计合理性",
      requirement: "要求明确性"
    };
    var severityText = {
      high: "高",
      medium: "中",
      low: "低"
    };
    var documentTypeText = {
      technical_solution: "技术方案",
      contract_acceptance: "合同验收文档",
      test_outline: "测试大纲和细则"
    };
    var issues = data.issues || [];
    var lines = [
      "技术文档审查结果",
      "",
      "文档类型：" + (documentTypeText[data.documentType] || data.documentType || "技术方案"),
      "总体结论：" + (data.summary || "审查完成。"),
      ""
    ];

    if (!issues.length) {
      lines.push("未发现明显技术文档审查问题。");
      return lines.join("\n");
    }

    issues.forEach(function (issue, index) {
      lines.push(
        "[" + (severityText[issue.severity] || issue.severity || "中") + "] " +
        (categoryText[issue.category] || issue.category || "技术审查") +
        " #" + (index + 1)
      );
      lines.push("位置：" + (issue.location || "未定位"));
      if (issue.originalText) {
        lines.push("原文：" + issue.originalText);
      }
      lines.push("问题：" + (issue.problem || "未说明"));
      lines.push("建议：" + (issue.suggestion || "无"));
      if (issue.suggestedRewrite) {
        lines.push("建议改写：" + issue.suggestedRewrite);
      }
      lines.push("");
    });

    return lines.join("\n").trim();
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

  function applyTechnicalReviewPrompt(documentType) {
    var nextType = TECHNICAL_REVIEW_PROMPTS[documentType] ? documentType : "technical_solution";
    state.technicalDocumentType = nextType;
    state.technicalReviewPrompt = TECHNICAL_REVIEW_PROMPTS[nextType];
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

  function twipsToPoints(value) {
    var numeric = Number(value);
    if (!isFinite(numeric)) {
      return null;
    }
    return numeric / 20;
  }

  function applyPageSetup(document, properties) {
    var setup = document && (document.PageSetup || document.pageSetup);
    if (!setup || !properties) {
      return;
    }
    var marginMap = [
      ["marginTopTwips", "TopMargin"],
      ["marginBottomTwips", "BottomMargin"],
      ["marginLeftTwips", "LeftMargin"],
      ["marginRightTwips", "RightMargin"]
    ];
    marginMap.forEach(function (item) {
      var value = twipsToPoints(properties[item[0]]);
      if (value !== null) {
        setup[item[1]] = value;
      }
    });
  }

  function setIfPresent(target, key, value) {
    if (typeof value !== "undefined" && value !== null) {
      target[key] = value;
    }
  }

  function applyParagraphStyle(paragraph, targetStyle, targetProperties) {
    var properties = targetProperties || {};
    paragraph.StyleNameLocal = targetStyle;
    paragraph.styleName = targetStyle;
    paragraph.Font = paragraph.Font || {};
    paragraph.ParagraphFormat = paragraph.ParagraphFormat || {};

    if (properties.fontName) {
      paragraph.Font.NameFarEast = properties.fontName;
      paragraph.Font.Name = properties.asciiFontName || properties.fontName;
    }
    setIfPresent(paragraph.Font, "Size", properties.fontSize);
    if (typeof properties.bold === "boolean") {
      paragraph.Font.Bold = properties.bold;
    }
    setIfPresent(paragraph.ParagraphFormat, "Alignment", properties.alignment);
    setIfPresent(paragraph.ParagraphFormat, "LineSpacing", properties.lineSpacingTwips);
    setIfPresent(paragraph.ParagraphFormat, "OutlineLevel", properties.outlineLevel);
    var firstLineIndent = twipsToPoints(properties.firstLineIndentTwips);
    var leftIndent = twipsToPoints(properties.leftIndentTwips);
    var rightIndent = twipsToPoints(properties.rightIndentTwips);
    var spaceBefore = twipsToPoints(properties.spaceBeforeTwips);
    var spaceAfter = twipsToPoints(properties.spaceAfterTwips);
    if (firstLineIndent !== null) {
      paragraph.ParagraphFormat.FirstLineIndent = firstLineIndent;
    }
    if (leftIndent !== null) {
      paragraph.ParagraphFormat.LeftIndent = leftIndent;
    }
    if (rightIndent !== null) {
      paragraph.ParagraphFormat.RightIndent = rightIndent;
    }
    if (spaceBefore !== null) {
      paragraph.ParagraphFormat.SpaceBefore = spaceBefore;
    }
    if (spaceAfter !== null) {
      paragraph.ParagraphFormat.SpaceAfter = spaceAfter;
    }

    if (Object.keys(properties).length) {
      return;
    }

    if (targetStyle === "Body" || targetStyle === "Normal") {
      paragraph.Font.NameFarEast = "SimSun";
      paragraph.Font.Name = "SimSun";
      paragraph.Font.Size = 12;
      paragraph.ParagraphFormat.OutlineLevel = 0;
    } else if (targetStyle.indexOf("Heading") === 0) {
      var level = Number(targetStyle.split(" ")[1] || 1);
      paragraph.Font.NameFarEast = "SimHei";
      paragraph.Font.Name = "SimHei";
      paragraph.Font.Size = level === 1 ? 16 : 14;
      paragraph.ParagraphFormat.OutlineLevel = level;
    }
  }

  function applyFormatChanges() {
    var document = getActiveDocument();
    var paragraphs = getParagraphs(document);
    state.formatChanges.forEach(function (change) {
      if (change.paragraphIndex === 0) {
        applyPageSetup(document, change.targetProperties || {});
        return;
      }
      var paragraph = paragraphs[change.paragraphIndex - 1];
      if (!paragraph) {
        return;
      }
      applyParagraphStyle(paragraph, change.targetStyle, change.targetProperties || {});
    });
    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("排版变更已应用。");
  }

  function applyRewrite() {
    var document = getActiveDocument();
    if (!document || !state.rewriteResult) {
      return;
    }

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
      if (typeof writableSelection.Text !== "undefined") {
        writableSelection.Text = state.rewriteResult.rewrittenText;
      }
      if (writableSelection.Range && typeof writableSelection.Range.Text !== "undefined") {
        writableSelection.Range.Text = state.rewriteResult.rewrittenText;
      }
    } else if (document.Content) {
      document.Content.Text = state.rewriteResult.rewrittenText;
    }

    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("结果已应用。");
  }

  function runProofread() {
    try {
      state.latestDocumentPayload = extractDocument("document");
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    setStatus("正在执行格式校对...");
    request("/word/proofread", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "";
        setApplyEnabled(false);
        setTrace(body.traceId);
        setResult(renderIssues(body.data.issues));
        setStatus("格式校对完成。");
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("格式校对失败：" + message);
        setResult(message);
      });
  }

  function runFormatPreview() {
    try {
      state.latestDocumentPayload = extractDocument("document");
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    setStatus("正在生成排版预览...");
    request("/word/format-preview", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "format";
        state.formatChanges = body.data.changes || [];
        setApplyEnabled(true);
        setTrace(body.traceId);
        setResult(renderFormatChanges(body.data.summary, body.data.changes));
        setStatus("排版预览已生成。");
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("排版预览失败：" + message);
        setResult(message);
      });
  }

  function runTechnicalReview() {
    var scope = resolveSelectionScope(false);
    if (!scope.ok) {
      setStatus(scope.message);
      setResult(scope.message);
      return;
    }

    try {
      state.latestDocumentPayload = extractDocument(scope.selectionMode);
      state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    setStatus("正在执行技术文档审查...");
    request("/word/technical-review", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "";
        setApplyEnabled(false);
        setTrace(body.traceId);
        setResult(renderTechnicalReview(body.data || {}));
        setStatus("技术文档审查完成。");
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("技术文档审查失败：" + message);
        setResult(message);
      });
  }

  function runSmartWriteAction() {
    var selectionScope = resolveSelectionScope(true);
    if (!selectionScope.ok) {
      setStatus(selectionScope.message);
      setResult(selectionScope.message);
      return;
    }

    try {
      state.latestDocumentPayload = extractDocument("selection", state.writeAction || "rewrite");
      state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    var config = modeConfig[state.currentMode] || modeConfig.smartWrite;
    setStatus(config.runningText);
    request("/word/smart-write", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "rewrite";
        state.rewriteResult = body.data;
        setApplyEnabled(true);
        setTrace(body.traceId);
        setRewriteResult(body.data);
        setStatus(config.doneText);
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("生成失败：" + message);
        setResult(message);
      });
  }

  function applyPreview() {
    if (state.pendingApplyAction === "format") {
      applyFormatChanges();
      return;
    }

    if (state.pendingApplyAction === "rewrite") {
      applyRewrite();
    }
  }

  function runPrimaryAction() {
    if (state.currentMode === "smartWrite") {
      runSmartWriteAction();
      return;
    }
    if (state.currentMode === "proofread") {
      runProofread();
      return;
    }
    if (state.currentMode === "format") {
      runFormatPreview();
      return;
    }
    if (state.currentMode === "technicalReview") {
      runTechnicalReview();
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
      applyTechnicalReviewPrompt(event.target.value);
    });
    byId("technical-review-prompt").addEventListener("input", function (event) {
      state.technicalReviewPrompt = event.target.value;
    });
    byId("btn-save-provider-url").addEventListener("click", saveProviderBaseUrl);
    byId("btn-save-api-key").addEventListener("click", saveProviderApiKey);
    byId("btn-clear-api-key").addEventListener("click", clearProviderApiKey);
    byId("btn-refresh").addEventListener("click", refreshConfig);
    byId("btn-edit-provider").addEventListener("click", function () {
      showProviderEditor(true);
    });
    byId("btn-back-provider-summary").addEventListener("click", function () {
      showProviderEditor(false);
    });
    byId("task-api-key-list").addEventListener("click", function (event) {
      var saveTask = event.target.getAttribute("data-save-task-key");
      var clearTask = event.target.getAttribute("data-clear-task-key");
      if (saveTask) {
        saveTaskApiKey(saveTask);
      }
      if (clearTask) {
        clearTaskApiKey(clearTask);
      }
    });
    byId("btn-apply").addEventListener("click", applyPreview);
    byId("btn-copy-result").addEventListener("click", copyResult);
    byId("btn-run-primary").addEventListener("click", runPrimaryAction);
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
