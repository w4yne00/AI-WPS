(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var state = {
    templates: [],
    selectedTemplateId: "general-office",
    traceId: "",
    pendingApplyAction: "",
    formatChanges: [],
    rewriteResult: null,
    latestDocumentPayload: null,
    latestSelectionMode: "document"
  };

  function setStatus(message) {
    document.getElementById("status-line").textContent = message;
  }

  function setTrace(traceId) {
    state.traceId = traceId || "";
    document.getElementById("trace-line").textContent = "Trace: " + (traceId || "N/A");
  }

  function setHealthBadge(mode, text) {
    var node = document.getElementById("health-indicator");
    node.className = "badge " + mode;
    node.textContent = text;
  }

  function setResult(text) {
    document.getElementById("result-output").textContent = text;
  }

  function setApplyEnabled(enabled) {
    document.getElementById("btn-apply").disabled = !enabled;
  }

  function getHostApplication() {
    return window.Application || window.wps || {};
  }

  function getActiveDocument() {
    var app = getHostApplication();
    return app.ActiveDocument || null;
  }

  function getParagraphs(document) {
    return (document && (document.Paragraphs || document.paragraphs)) || [];
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
        alignment: String(paragraphFormat.Alignment || "left"),
        outlineLevel: paragraphFormat.OutlineLevel || 0
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

  function extractDocument(selectionMode) {
    var document = getActiveDocument();
    if (!document) {
      throw new Error("未检测到活动文档。");
    }

    var paragraphs = collectParagraphs(document);
    var plainText = document.Content && document.Content.Text
      ? document.Content.Text
      : paragraphs.map(function (item) { return item.text; }).join("\n");

    if (selectionMode === "selection") {
      var selection = document.Selection || {};
      plainText = selection.Text || (selection.Range && selection.Range.Text) || plainText;
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
        trackChanges: true
      }
    };
  }

  function request(path, payload) {
    return fetch(ADAPTER_BASE_URL + path, {
      method: payload ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json"
      },
      body: payload ? JSON.stringify(payload) : undefined
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
      state.templates = templates.data.templates || [];
      renderTemplateOptions();
      setStatus("配置已刷新。");
    }).catch(function (error) {
      setHealthBadge("badge-error", "不可达");
      setStatus("刷新失败：" + error.message);
      setResult("无法连接本地适配层：" + error.message);
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

  function renderRewrite(result) {
    return [
      "模式: " + result.rewriteMode,
      "",
      "原文:",
      result.originalText,
      "",
      "改写后:",
      result.rewrittenText,
      "",
      "提示: " + result.diffHints.join(", ")
    ].join("\n");
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

    if (state.latestSelectionMode === "selection" && document.Selection) {
      document.Selection.Text = state.rewriteResult.rewrittenText;
      if (document.Selection.Range) {
        document.Selection.Range.Text = state.rewriteResult.rewrittenText;
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

  function runRewrite() {
    try {
      state.latestDocumentPayload = extractDocument("selection");
      state.latestSelectionMode = state.latestDocumentPayload.selectionMode;
    } catch (error) {
      setStatus(error.message);
      setResult(error.message);
      return;
    }

    setStatus("正在执行改写/续写...");
    request("/word/rewrite", state.latestDocumentPayload)
      .then(function (body) {
        state.pendingApplyAction = "rewrite";
        state.rewriteResult = body.data;
        setApplyEnabled(true);
        setTrace(body.traceId);
        setResult(renderRewrite(body.data));
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
    var lines = [
      "Runtime Probe",
      "",
      "WPS global: " + (typeof window.wps !== "undefined" || typeof window.Application !== "undefined"),
      "Active document: " + Boolean(document),
      "Selection available: " + Boolean(document && document.Selection),
      "Document name: " + ((document && document.Name) || "N/A"),
      "Paragraph count: " + paragraphs.length,
      "Heading count: " + headingCount,
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
    document.getElementById("btn-refresh").addEventListener("click", refreshConfig);
    document.getElementById("btn-proofread").addEventListener("click", runProofread);
    document.getElementById("btn-format").addEventListener("click", runFormatPreview);
    document.getElementById("btn-rewrite").addEventListener("click", runRewrite);
    document.getElementById("btn-probe").addEventListener("click", runProbe);
    document.getElementById("btn-apply").addEventListener("click", applyPreview);
  }

  bindEvents();
  refreshConfig();
})();
