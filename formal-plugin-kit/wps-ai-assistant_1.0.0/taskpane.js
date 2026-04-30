(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var TASKPANE_ROOT_ID = "result-output";
  var helpers = window.WpsAiAssistantHelpers || {};
  var state = {
    templates: [],
    selectedTemplateId: "technical-file-format-requirements",
    rewriteStyle: "default",
    focusPoint: "default",
    lengthMode: "default",
    userInstruction: "",
    traceId: "",
    pendingApplyAction: "",
    formatChanges: [],
    rewriteResult: null,
    latestDocumentPayload: null,
    latestSelectionMode: "document",
    providerName: "N/A",
    providerAuthSource: "N/A",
    currentView: "home",
    copyText: "",
    scopeWatcher: null
  };

  function setStatus(message) {
    document.getElementById("status-line").textContent = message;
    document.getElementById("result-mode-chip").textContent = message || "等待运行";
  }

  function isTaskpanePage() {
    return Boolean(document.getElementById(TASKPANE_ROOT_ID));
  }

  function setTrace(traceId) {
    state.traceId = traceId || "";
    document.getElementById("trace-line").textContent = traceId || "N/A";
  }

  function setProviderLine(providerName, configured) {
    var detail = providerName || "N/A";
    if (typeof configured === "boolean") {
      detail += configured ? " / configured" : " / mock";
    }
    state.providerName = detail;
    document.getElementById("provider-line").textContent = "Provider: " + detail;
    document.getElementById("settings-provider-line").textContent = "Provider: " + detail;
  }

  function setProviderAuthLine(source) {
    state.providerAuthSource = source || "N/A";
    document.getElementById("provider-auth-line").textContent = "Provider Auth: " + state.providerAuthSource;
  }

  function setScopeLine(label) {
    var text = label || "当前范围：未检测";
    document.getElementById("scope-line").textContent = text.replace(/^当前范围：/, "");
    document.getElementById("settings-scope-line").textContent = text.replace(/^当前范围：/, "");
  }

  function setHealthBadge(mode, text) {
    var node = document.getElementById("health-indicator");
    node.className = "badge " + mode;
    node.textContent = text;
  }

  function setResult(text) {
    var output = document.getElementById("result-output");
    output.hidden = false;
    output.textContent = text;
    state.copyText = text || "";
  }

  function setRewriteResult(result) {
    setResult(result.rewrittenText || "");
  }

  function setApplyEnabled(enabled) {
    document.getElementById("btn-apply").disabled = !enabled;
  }

  function switchView(viewName) {
    state.currentView = viewName;
    document.getElementById("home-view").classList.toggle("active", viewName === "home");
    document.getElementById("settings-view").classList.toggle("active", viewName === "settings");
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
        alignment: String(paragraphFormat.Alignment || "left"),
        outlineLevel: paragraphFormat.OutlineLevel || 0,
        lineSpacing: paragraphFormat.LineSpacing || paragraphFormat.lineSpacing || null,
        firstLineIndent: paragraphFormat.FirstLineIndent || paragraphFormat.firstLineIndent || null
      });
    }
    return items;
  }

  function collectHeadings(paragraphs) {
    var headings = [];
    for (var i = 0; i < paragraphs.length; i += 1) {
      if ((paragraphs[i].outlineLevel || 0) > 0) {
        headings.push({
          level: paragraphs[i].outlineLevel,
          text: paragraphs[i].text
        });
      }
    }
    return headings;
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

    return {
      documentId: document.Name || "unnamed.docx",
      scene: "word",
      selectionMode: selectionMode,
      content: {
        plainText: plainText,
        paragraphs: paragraphs,
        headings: collectHeadings(paragraphs)
      },
      options: {
        templateId: state.selectedTemplateId,
        trackChanges: true,
        userInstruction: state.userInstruction,
        rewriteStyle: state.rewriteStyle,
        focusPoint: state.focusPoint,
        lengthMode: state.lengthMode,
        rewriteAction: rewriteAction || "rewrite"
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
        ok: !!selectionText,
        selectionMode: selectionText ? "selection" : "document",
        scopeLabel: selectionText ? "当前范围：选中文本" : "当前范围：全文",
        selectedText: selectionText,
        message: "请先用鼠标选中一段文字，再执行改写或续写。"
      };

    setScopeLine(resolved.scopeLabel);
    return resolved;
  }

  function updateScopeIndicator() {
    var document = getActiveDocument();
    if (!document) {
      setScopeLine("当前范围：未检测");
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

  function refreshConfig() {
    setStatus("正在刷新配置...");
    return Promise.all([
      request("/health"),
      request("/templates")
    ]).then(function (results) {
      var health = results[0];
      var templates = results[1];
      setHealthBadge("badge-ok", health.data.status);
      setTrace(health.traceId || "");
      setProviderLine(health.data.providerType || "N/A", health.data.providerConfigured);
      setProviderAuthLine(health.data.providerAuthSource || "none");
      resolveSelectionScope(false);
      state.templates = templates.data.templates || [];
      renderTemplateOptions();
      setStatus("配置已刷新。");
    }).catch(function (error) {
      setHealthBadge("badge-error", "不可达");
      setProviderLine("N/A");
      setProviderAuthLine("N/A");
      setStatus("刷新失败：" + error.message);
      setResult("无法连接本地适配层：" + error.message);
    });
  }

  function saveApiKey() {
    var input = document.getElementById("provider-api-key");
    var apiKey = (input.value || "").trim();
    if (!apiKey) {
      setStatus("请输入 API Key。");
      setResult("请输入 API Key 后再保存。");
      return;
    }
    setStatus("正在保存 API Key...");
    request("/provider/api-key", { apiKey: apiKey })
      .then(function (body) {
        input.value = "";
        setProviderAuthLine(body.data.authSource || "file");
        setStatus("API Key 已保存。");
        return refreshConfig();
      })
      .catch(function (error) {
        setStatus("保存 API Key 失败：" + error.message);
        setResult(error.message);
      });
  }

  function clearApiKey() {
    setStatus("正在清除 API Key...");
    fetch(ADAPTER_BASE_URL + "/provider/api-key", {
      method: "DELETE"
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) || body.message || ("HTTP " + response.status));
        }
        return body;
      });
    }).then(function (body) {
      document.getElementById("provider-api-key").value = "";
      setProviderAuthLine(body.data.authSource || "none");
      setStatus("API Key 已清除。");
      return refreshConfig();
    }).catch(function (error) {
      setStatus("清除 API Key 失败：" + error.message);
      setResult(error.message);
    });
  }

  function renderTemplateOptions() {
    var select = document.getElementById("template-select");
    select.innerHTML = "";

    if (!state.templates.length) {
      var fallback = document.createElement("option");
      fallback.value = "general-office";
      fallback.textContent = "general-office";
      select.appendChild(fallback);
      state.selectedTemplateId = "general-office";
      return;
    }

    state.templates.forEach(function (template) {
      var option = document.createElement("option");
      option.value = template.id;
      option.textContent = template.name + " (" + template.id + ")";
      if (template.id === state.selectedTemplateId) {
        option.selected = true;
      }
      select.appendChild(option);
    });
  }

  function renderIssues(issues) {
    return issues.map(function (issue) {
      return [
        "规则: " + issue.ruleId,
        "级别: " + issue.severity,
        "段落: " + (issue.paragraphIndex || "N/A"),
        "说明: " + issue.message,
        "建议: " + (issue.suggestion || "N/A"),
        "自动修复: " + issue.autoFixable
      ].join(" | ");
    }).join("\n");
  }

  function renderFormatChanges(summary, changes) {
    var lines = [
      "模板: " + summary.templateId,
      "变更数: " + summary.changeCount,
      ""
    ];

    changes.forEach(function (change) {
      lines.push(
        "P" + change.paragraphIndex +
        ": " + change.currentStyle +
        " -> " + change.targetStyle +
        " | " + change.reason
      );
    });

    return lines.join("\n");
  }

  function copyResult() {
    var text = state.copyText || document.getElementById("result-output").textContent || "";
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

  function applyParagraphStyle(paragraph, targetStyle) {
    paragraph.StyleNameLocal = targetStyle;
    paragraph.styleName = targetStyle;
    paragraph.Font = paragraph.Font || {};
    paragraph.ParagraphFormat = paragraph.ParagraphFormat || {};

    if (targetStyle === "Body") {
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
      var paragraph = paragraphs[change.paragraphIndex - 1];
      if (!paragraph) {
        return;
      }
      applyParagraphStyle(paragraph, change.targetStyle);
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
        setResult("当前宿主未暴露可写回的选区对象，请执行运行探针并反馈结果。");
        return;
      }
      if (typeof writableSelection.Text !== "undefined") {
        writableSelection.Text = state.rewriteResult.rewrittenText;
      }
      if (writableSelection.Range && typeof writableSelection.Range.Text !== "undefined") {
        writableSelection.Range.Text = state.rewriteResult.rewrittenText;
      }
    } else {
      if (document.Content) {
        document.Content.Text = state.rewriteResult.rewrittenText;
      }
      var paragraphs = getParagraphs(document);
      if (paragraphs.length > 0) {
        paragraphs[0].Text = state.rewriteResult.rewrittenText;
      }
    }

    state.pendingApplyAction = "";
    setApplyEnabled(false);
    setStatus("改写结果已应用。");
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
        setStatus("格式校对失败：" + error.message);
        setResult(error.message);
      });
  }

  function openSettings() {
    switchView("settings");
  }

  function closeSettings() {
    switchView("home");
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
        setStatus("排版预览失败：" + error.message);
        setResult(error.message);
      });
  }

  function runRewriteAction(action) {
    var selectionScope = resolveSelectionScope(true);
    if (!selectionScope.ok) {
      setStatus(selectionScope.message);
      setResult(selectionScope.message);
      return;
    }

    try {
      state.latestDocumentPayload = extractDocument("selection", action);
      state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    setStatus(action === "continue" ? "正在执行选中续写..." : "正在执行选中改写...");
    request("/word/rewrite", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "rewrite";
        state.rewriteResult = body.data;
        setApplyEnabled(true);
        setTrace(body.traceId);
        setRewriteResult(body.data);
        setStatus("改写结果已生成。");
      })
      .catch(function (error) {
        setStatus("改写失败：" + error.message);
        setResult(error.message);
      });
  }

  function runProbe() {
    var document = getActiveDocument();
    var paragraphs = collectParagraphs(document || {});
    var headingCount = collectHeadings(paragraphs).length;
    var scope = resolveSelectionScope(false);
    var lines = [
      "Runtime Probe",
      "",
      "WPS global: " + (typeof window.wps !== "undefined" || typeof window.Application !== "undefined"),
      "Active document: " + Boolean(document),
      "Selection available: " + Boolean(document && document.Selection),
      "Document name: " + ((document && document.Name) || "N/A"),
      "Paragraph count: " + paragraphs.length,
      "Heading count: " + headingCount,
      scope.scopeLabel,
      "Adapter base URL: " + ADAPTER_BASE_URL
    ];

    setResult(lines.join("\n"));
    setStatus("运行时探针已执行。");
  }

  function collectHeadings(paragraphs) {
    return paragraphs.filter(function (item) {
      return (item.outlineLevel || 0) > 0;
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

  function bindEvents() {
    document.getElementById("template-select").addEventListener("change", function (event) {
      state.selectedTemplateId = event.target.value;
    });
    document.getElementById("rewrite-style").addEventListener("change", function (event) {
      state.rewriteStyle = event.target.value;
    });
    document.getElementById("focus-point").addEventListener("change", function (event) {
      state.focusPoint = event.target.value;
    });
    document.getElementById("length-mode").addEventListener("change", function (event) {
      state.lengthMode = event.target.value;
    });
    document.getElementById("user-instruction").addEventListener("input", function (event) {
      state.userInstruction = event.target.value;
    });
    document.getElementById("btn-save-api-key").addEventListener("click", saveApiKey);
    document.getElementById("btn-clear-api-key").addEventListener("click", clearApiKey);
    document.getElementById("btn-open-settings").addEventListener("click", openSettings);
    document.getElementById("btn-close-settings").addEventListener("click", closeSettings);
    document.getElementById("btn-refresh").addEventListener("click", refreshConfig);
    document.getElementById("btn-proofread").addEventListener("click", runProofread);
    document.getElementById("btn-format").addEventListener("click", runFormatPreview);
    document.getElementById("btn-rewrite-selection").addEventListener("click", function () {
      runRewriteAction("rewrite");
    });
    document.getElementById("btn-continue-selection").addEventListener("click", function () {
      runRewriteAction("continue");
    });
    document.getElementById("btn-probe").addEventListener("click", runProbe);
    document.getElementById("btn-apply").addEventListener("click", applyPreview);
    document.getElementById("btn-copy-result").addEventListener("click", copyResult);
  }

  if (!isTaskpanePage()) {
    window.openTaskpane = function () {
      return true;
    };
    return;
  }

  bindEvents();
  refreshConfig();
  startScopeWatcher();
})();
