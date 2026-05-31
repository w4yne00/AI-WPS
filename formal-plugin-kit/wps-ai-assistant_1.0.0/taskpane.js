(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.12.10-alpha";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var FORMAT_REVIEW_EXTRACTION_OPTIONS = {
    maxParagraphs: 80,
    maxParagraphTextLength: 800,
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
    { taskType: "word.document_review", label: "文档审查" },
    { taskType: "word.format_review", label: "格式审查" }
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
    traceId: "",
    pendingApplyAction: "",
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

    if (state.currentMode === "settings") {
      switchView("settings");
      return;
    }

    switchView("home");
    byId("rewrite-options").hidden = !config.showRewriteOptions;
    byId("instruction-block").hidden = !config.showInstruction;
    byId("template-options").hidden = !config.showTemplate;
    byId("document-review-options").hidden = !config.showDocumentReviewOptions;
    byId("fixed-template-options").hidden = !config.showFixedTemplate;
    byId("style-field-label").textContent = config.styleLabel || "表达风格";
    byId("btn-run-primary").textContent = config.primaryText;
    byId("btn-apply").hidden = state.currentMode !== "smartWrite";
    updateRewritePromptPreview();
    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("等待操作。");
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

  function extractDocument(selectionMode, rewriteAction, extractionOptions) {
    var options = extractionOptions || {};
    var document = getActiveDocument();
    if (!document) {
      throw new Error("未检测到活动文档。");
    }

    var selectedText = selectionMode === "selection" ? getSelectionText(document) : "";
    var paragraphs = [];
    var plainText = "";
    if (options.preferSelectionTextParagraphs && selectedText && helpers.collectParagraphsFromText) {
      plainText = selectedText;
      paragraphs = helpers.collectParagraphsFromText(selectedText, options);
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
          var validation = body.data && body.data.validation;
          if (validation && validation.errors && validation.errors.length) {
            var details = validation.errors.map(function (item) {
              return [item.loc, item.type, item.message].filter(Boolean).join(" | ");
            }).join("\n");
            throw new Error("HTTP " + response.status + " 请求数据校验失败：\n" + details);
          }
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

  function formatAiFallbackReason(reason) {
    var reasonText = {
      no_paragraphs: "未读取到正文段落，未调用 Dify；请确认当前文档对象能暴露正文段落或全文文本。",
      provider_not_configured: "统一 API URL 或格式审查任务 API Key 未形成可用配置，已使用本地模板规则。",
      dify_response_not_role_json: "Dify 未返回段落角色 JSON，已使用本地模板规则。",
      provider_request_failed: "Dify 请求失败，已使用本地模板规则。",
      dify_response_no_valid_roles: "Dify 返回的角色无效，已使用本地模板规则。",
      dify_returned_no_roles: "Dify 未返回有效段落角色，已使用本地模板规则。"
    };
    return reasonText[reason] || reason || "";
  }

  function renderFormatReview(data) {
    var summary = data.summary || {};
    var issues = data.issues || [];
    var lines = [
      "模板：" + summary.templateId,
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
      lines.push("AI 识别提示：" + aiFallbackText);
    }
    if (summary.aiInvalidRoleCount || summary.aiOutOfBatchCount) {
      lines.push(
        "AI 无效角色：" + (summary.aiInvalidRoleCount || 0) +
        " | 越界段落：" + (summary.aiOutOfBatchCount || 0)
      );
    }
    lines.push("");
    if (hasCoverageStats) {
      lines.push("以下仅显示需要调整的格式项，正文内容不会在检查中改写。");
      lines.push("");
    }

    if (!issues.length) {
      lines.push("当前范围未发现明显格式问题。");
      return lines.join("\n");
    }

    issues.forEach(function (issue) {
      lines.push("第 " + (issue.paragraphIndex || 0) + " 段：" + (issue.message || "格式问题"));
      lines.push("角色：" + (issue.role || "未识别") + " | 规则：" + (issue.ruleId || "format"));
      if (issue.currentValue || issue.expectedValue) {
        lines.push("当前：" + (issue.currentValue || "未读取") + " | 应为：" + (issue.expectedValue || "未给出"));
      }
      lines.push("建议：" + (issue.suggestion || "按模板调整。"));
      lines.push("");
    });

    return lines.join("\n").trim();
  }

  function renderDocumentReview(data) {
    var categoryText = {
      typo: "错别字",
      expression: "语言表达",
      logic: "逻辑表达",
      fluency: "通畅性",
      professional: "专业性"
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
      "文档审查结果",
      "",
      "文档类型：" + (documentTypeText[data.documentType] || data.documentType || "技术方案"),
      "检查范围：" + (data.scope === "selection" ? "选中内容" : "全文"),
      "总体结论：" + (data.summary || "审查完成。"),
      ""
    ];

    if (!issues.length) {
      lines.push("未发现明显文档质量问题。");
      return lines.join("\n");
    }

    issues.forEach(function (issue, index) {
      lines.push(
        "[" + (severityText[issue.severity] || issue.severity || "中") + "] " +
        (categoryText[issue.category] || issue.category || "文档审查") +
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

  function runDocumentReview() {
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

    setStatus("正在执行文档审查...");
    request("/word/document-review", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "";
        setApplyEnabled(false);
        setTrace(body.traceId);
        setResult(renderDocumentReview(body.data || {}));
        setStatus("文档审查完成。");
      })
      .catch(function (error) {
        var message = describeFetchError(error);
        setStatus("文档审查失败：" + message);
        setResult(message);
      });
  }

  function runFormatReview() {
    var scope = resolveSelectionScope(false);
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
          setResult(renderFormatReview(body.data || {}));
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
    if (state.pendingApplyAction === "rewrite") {
      applyRewrite();
    }
  }

  function runPrimaryAction() {
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
