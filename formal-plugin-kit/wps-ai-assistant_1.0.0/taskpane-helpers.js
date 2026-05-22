(function (root, factory) {
  var exports = factory();
  root.WpsAiAssistantHelpers = exports;
  if (typeof module === "object" && module.exports) {
    module.exports = exports;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function normalizeText(text) {
    return String(text || "").replace(/\r/g, "").trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function sanitizeMarkdownUrl(value) {
    var url = String(value || "").trim();
    if (/^(https?:\/\/|mailto:)/i.test(url)) {
      return url;
    }
    return "";
  }

  function renderInlineMarkdown(value) {
    var tokens = [];
    var text = String(value || "");

    function storeToken(html) {
      var token = "\u0000MDTOKEN" + tokens.length + "\u0000";
      tokens.push({ token: token, html: html });
      return token;
    }

    text = text.replace(/`([^`]+)`/g, function (_match, code) {
      return storeToken("<code>" + escapeHtml(code) + "</code>");
    });

    text = text.replace(/(!?)\[([^\]]+)\]\(([^)\s]+)\)/g, function (match, imagePrefix, label, url) {
      var safeUrl = imagePrefix ? "" : sanitizeMarkdownUrl(url);
      if (!safeUrl) {
        return escapeHtml(label || match);
      }
      return storeToken(
        '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' +
        escapeHtml(label) +
        "</a>"
      );
    });

    text = escapeHtml(text)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");

    tokens.forEach(function (entry) {
      text = text.split(escapeHtml(entry.token)).join(entry.html);
    });
    return text;
  }

  function renderMarkdown(markdown) {
    var lines = String(markdown || "").replace(/\r/g, "").split("\n");
    var html = [];
    var paragraph = [];
    var listType = "";
    var inCode = false;
    var codeLang = "";
    var codeLines = [];
    var tableRows = [];

    function closeList() {
      if (listType) {
        html.push("</" + listType + ">");
        listType = "";
      }
    }

    function flushParagraph() {
      if (paragraph.length) {
        closeList();
        html.push("<p>" + paragraph.map(renderInlineMarkdown).join("<br>") + "</p>");
        paragraph = [];
      }
    }

    function splitTableRow(line) {
      var value = String(line || "").trim();
      if (value.charAt(0) === "|") {
        value = value.slice(1);
      }
      if (value.charAt(value.length - 1) === "|") {
        value = value.slice(0, -1);
      }
      return value.split("|").map(function (cell) {
        return cell.trim();
      });
    }

    function isTableSeparator(line) {
      var cells = splitTableRow(line);
      return cells.length > 0 && cells.every(function (cell) {
        return /^:?-{3,}:?$/.test(cell);
      });
    }

    function isTableLine(line) {
      return /\|/.test(line || "");
    }

    function flushTable() {
      if (tableRows.length < 2 || !isTableSeparator(tableRows[1])) {
        tableRows.forEach(function (row) {
          paragraph.push(row.trim());
        });
        tableRows = [];
        return;
      }

      flushParagraph();
      closeList();
      var headers = splitTableRow(tableRows[0]);
      var bodyRows = tableRows.slice(2);
      html.push('<div class="markdown-table-wrap"><table><thead><tr>');
      headers.forEach(function (cell) {
        html.push("<th>" + renderInlineMarkdown(cell) + "</th>");
      });
      html.push("</tr></thead><tbody>");
      bodyRows.forEach(function (row) {
        html.push("<tr>");
        splitTableRow(row).forEach(function (cell) {
          html.push("<td>" + renderInlineMarkdown(cell) + "</td>");
        });
        html.push("</tr>");
      });
      html.push("</tbody></table></div>");
      tableRows = [];
    }

    function openList(nextType) {
      flushParagraph();
      if (listType !== nextType) {
        closeList();
        html.push("<" + nextType + ">");
        listType = nextType;
      }
    }

    lines.forEach(function (line) {
      var codeFence = line.match(/^```([A-Za-z0-9_-]*)\s*$/);
      var heading = line.match(/^(#{1,6})\s+(.+)$/);
      var unordered = line.match(/^\s*[-*+]\s+(.+)$/);
      var ordered = line.match(/^\s*\d+\.\s+(.+)$/);
      var quote = line.match(/^>\s?(.+)$/);
      var divider = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line);

      if (inCode) {
        if (codeFence) {
          html.push(
            '<pre><code' +
            (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : "") +
            ">" +
            escapeHtml(codeLines.join("\n")) +
            "</code></pre>"
          );
          inCode = false;
          codeLang = "";
          codeLines = [];
          return;
        }
        codeLines.push(line);
        return;
      }

      if (tableRows.length && !isTableLine(line)) {
        flushTable();
      }

      if (codeFence) {
        flushTable();
        flushParagraph();
        closeList();
        inCode = true;
        codeLang = codeFence[1] || "";
        codeLines = [];
        return;
      }

      if (!line.trim()) {
        flushTable();
        flushParagraph();
        closeList();
        return;
      }

      if (isTableLine(line)) {
        tableRows.push(line);
        return;
      }

      if (heading) {
        flushTable();
        flushParagraph();
        closeList();
        html.push(
          "<h" + heading[1].length + ">" +
          renderInlineMarkdown(heading[2]) +
          "</h" + heading[1].length + ">"
        );
        return;
      }

      if (divider) {
        flushTable();
        flushParagraph();
        closeList();
        html.push("<hr>");
        return;
      }

      if (unordered) {
        flushTable();
        openList("ul");
        html.push("<li>" + renderInlineMarkdown(unordered[1]) + "</li>");
        return;
      }

      if (ordered) {
        flushTable();
        openList("ol");
        html.push("<li>" + renderInlineMarkdown(ordered[1]) + "</li>");
        return;
      }

      if (quote) {
        flushTable();
        flushParagraph();
        closeList();
        html.push("<blockquote>" + renderInlineMarkdown(quote[1]) + "</blockquote>");
        return;
      }

      paragraph.push(line.trim());
    });

    if (inCode) {
      html.push(
        '<pre><code' +
        (codeLang ? ' class="language-' + escapeHtml(codeLang) + '"' : "") +
        ">" +
        escapeHtml(codeLines.join("\n")) +
        "</code></pre>"
      );
    }
    flushTable();
    flushParagraph();
    closeList();

    return html.join("\n");
  }

  function getEffectiveSelectionText(selectionOrSources) {
    if (!selectionOrSources) {
      return "";
    }
    if (Array.isArray(selectionOrSources)) {
      for (var i = 0; i < selectionOrSources.length; i += 1) {
        var value = getEffectiveSelectionText(selectionOrSources[i]);
        if (value) {
          return value;
        }
      }
      return "";
    }
    return normalizeText(
      selectionOrSources.Text ||
      (selectionOrSources.Range && selectionOrSources.Range.Text) ||
      (selectionOrSources.TextRange && selectionOrSources.TextRange.Text) ||
      ""
    );
  }

  function getWritableSelection(sources) {
    for (var i = 0; i < sources.length; i += 1) {
      var selection = sources[i];
      if (!selection) {
        continue;
      }
      if (typeof selection.Text !== "undefined") {
        return selection;
      }
      if (selection.Range && typeof selection.Range.Text !== "undefined") {
        return selection;
      }
    }
    return null;
  }

  function resolveRewriteScope(options) {
    var selectionText = normalizeText(options.selectionText);
    if (options.requireSelection && !selectionText) {
      return {
        ok: false,
        selectionMode: "selection",
        scopeLabel: "当前范围：全文",
        message: "请先用鼠标选中一段文字，再执行改写或续写。"
      };
    }

    if (selectionText) {
      return {
        ok: true,
        selectionMode: "selection",
        scopeLabel: "当前范围：选中文本",
        selectedText: selectionText
      };
    }

    return {
      ok: true,
      selectionMode: "document",
      scopeLabel: "当前范围：全文"
    };
  }

  function canApplyRewriteToSelection(originalText, currentSelectionText) {
    if (!normalizeText(currentSelectionText)) {
      return {
        ok: false,
        message: "当前未检测到有效选区，无法安全写回改写结果。"
      };
    }

    if (normalizeText(originalText) !== normalizeText(currentSelectionText)) {
      return {
        ok: false,
        message: "选区已变化，请重新选中原文后再应用改写结果。"
      };
    }

    return { ok: true };
  }

  function normalizeNumber(value) {
    if (value === null || typeof value === "undefined" || value === "") {
      return null;
    }
    var numeric = Number(value);
    return isNaN(numeric) ? null : numeric;
  }

  function firstDefined() {
    for (var i = 0; i < arguments.length; i += 1) {
      if (typeof arguments[i] !== "undefined" && arguments[i] !== null) {
        return arguments[i];
      }
    }
    return null;
  }

  function buildDocumentStructure(options) {
    var paragraphs = options.paragraphs || [];
    var headings = options.headings || [];
    return {
      doc_name: options.documentId || "unnamed.docx",
      template_id: options.templateId || "general-office",
      selection_mode: options.selectionMode || "document",
      page_setup: options.pageSetup || {},
      paragraphs: paragraphs.map(function (paragraph) {
        return {
          index: paragraph.index,
          text: paragraph.text || "",
          style_name: paragraph.styleName || paragraph.style_name || "",
          font_family: paragraph.fontName || paragraph.font_family || "",
          font_size_pt: normalizeNumber(firstDefined(paragraph.fontSize, paragraph.font_size_pt)),
          bold: Boolean(paragraph.bold),
          italic: Boolean(paragraph.italic),
          underline: paragraph.underline || null,
          alignment: paragraph.alignment || "",
          outline_level: normalizeNumber(firstDefined(paragraph.outlineLevel, paragraph.outline_level)),
          line_spacing: normalizeNumber(firstDefined(paragraph.lineSpacing, paragraph.line_spacing)),
          first_line_indent: normalizeNumber(firstDefined(paragraph.firstLineIndent, paragraph.first_line_indent)),
          space_before: normalizeNumber(firstDefined(paragraph.spaceBefore, paragraph.space_before)),
          space_after: normalizeNumber(firstDefined(paragraph.spaceAfter, paragraph.space_after)),
          left_indent: normalizeNumber(firstDefined(paragraph.leftIndent, paragraph.left_indent)),
          right_indent: normalizeNumber(firstDefined(paragraph.rightIndent, paragraph.right_indent))
        };
      }),
      headings: headings.map(function (heading) {
        return {
          level: heading.level || heading.outlineLevel || 0,
          text: heading.text || "",
          paragraph_index: heading.paragraphIndex || heading.index || null
        };
      }),
      tables: options.tables || [],
      captions: options.captions || [],
      capabilities: {
        page_setup_extracted: Boolean(options.pageSetup && Object.keys(options.pageSetup).length),
        paragraph_style_extracted: paragraphs.length > 0,
        table_extracted: Boolean(options.tables && options.tables.length),
        header_footer_extracted: false
      }
    };
  }

  return {
    normalizeText: normalizeText,
    escapeHtml: escapeHtml,
    renderMarkdown: renderMarkdown,
    getEffectiveSelectionText: getEffectiveSelectionText,
    getWritableSelection: getWritableSelection,
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection,
    buildDocumentStructure: buildDocumentStructure
  };
});
