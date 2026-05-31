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

  function normalizePositiveInteger(value) {
    var numeric = Number(value);
    if (isNaN(numeric) || numeric <= 0) {
      return null;
    }
    return Math.floor(numeric);
  }

  function normalizeCollectOptions(options) {
    var source = typeof options === "number" ? { maxParagraphs: options } : (options || {});
    return {
      maxParagraphs: normalizePositiveInteger(source.maxParagraphs),
      maxParagraphTextLength: normalizePositiveInteger(source.maxParagraphTextLength),
      avoidFallbackTextRead: Boolean(source.avoidFallbackTextRead)
    };
  }

  function limitTextLength(value, maxLength) {
    var text = String(value || "");
    if (maxLength && text.length > maxLength) {
      return text.slice(0, maxLength);
    }
    return text;
  }

  function safeRead(object, key) {
    if (!object) {
      return undefined;
    }
    try {
      return object[key];
    } catch (error) {
      return undefined;
    }
  }

  function safeCall(fn, thisArg) {
    if (typeof fn !== "function") {
      return undefined;
    }
    try {
      return fn.call(thisArg);
    } catch (error) {
      return undefined;
    }
  }

  function resolveRange(object) {
    var range = firstDefined(safeRead(object, "Range"), safeRead(object, "range"));
    return typeof range === "function" ? safeCall(range, object) : range;
  }

  function normalizeParagraphText(text) {
    return String(text || "")
      .replace(/\u0007/g, "")
      .replace(/\r/g, "\n")
      .replace(/\n+$/g, "");
  }

  function toSafeString(value, fallback) {
    var resolved = typeof value === "function" ? safeCall(value, null) : value;
    if (typeof resolved === "undefined" || resolved === null) {
      return fallback || "";
    }
    if (typeof resolved === "string") {
      return resolved;
    }
    if (typeof resolved === "number" || typeof resolved === "boolean") {
      return String(resolved);
    }
    return fallback || "";
  }

  function normalizeInteger(value) {
    var numeric = normalizeNumber(typeof value === "function" ? safeCall(value, null) : value);
    if (numeric === null) {
      return null;
    }
    return Math.round(numeric);
  }

  function readText(object) {
    var range = resolveRange(object);
    return normalizeParagraphText(toSafeString(firstDefined(
      safeRead(object, "Text"),
      safeRead(object, "text"),
      safeRead(range, "Text"),
      safeRead(range, "text"),
      safeRead(safeRead(object, "TextRange"), "Text"),
      safeRead(safeRead(range, "TextRange"), "Text")
    )));
  }

  function readDocumentText(document) {
    var content = safeRead(document, "Content") || safeRead(document, "content");
    var range = resolveRange(document);
    return normalizeParagraphText(toSafeString(firstDefined(
      safeRead(document, "Text"),
      safeRead(document, "text"),
      safeRead(content, "Text"),
      safeRead(content, "text"),
      safeRead(range, "Text"),
      safeRead(range, "text")
    )));
  }

  function readStyleName(paragraph) {
    var range = resolveRange(paragraph);
    var style = firstDefined(
      safeRead(paragraph, "Style"),
      safeRead(paragraph, "style"),
      safeRead(range, "Style"),
      safeRead(range, "style")
    );
    if (typeof style === "string") {
      return style;
    }
    return toSafeString(firstDefined(
      safeRead(paragraph, "StyleNameLocal"),
      safeRead(paragraph, "styleName"),
      safeRead(paragraph, "StyleName"),
      safeRead(range, "StyleNameLocal"),
      safeRead(range, "StyleName"),
      safeRead(style, "NameLocal"),
      safeRead(style, "Name"),
      "Body"
    ), "Body");
  }

  function readFont(paragraph) {
    var range = resolveRange(paragraph);
    return firstDefined(
      safeRead(paragraph, "Font"),
      safeRead(range, "Font"),
      {}
    );
  }

  function readParagraphFormat(paragraph) {
    var range = resolveRange(paragraph);
    return firstDefined(
      safeRead(paragraph, "ParagraphFormat"),
      safeRead(range, "ParagraphFormat"),
      {}
    );
  }

  function readCollectionCount(collection) {
    if (!collection) {
      return 0;
    }
    var count = typeof collection.length === "number" ? collection.length : null;
    if (count === null) {
      count = typeof collection.Count === "function" ? safeCall(collection.Count, collection) : safeRead(collection, "Count");
    }
    if (typeof count === "undefined" || count === null) {
      count = typeof collection.count === "function" ? safeCall(collection.count, collection) : safeRead(collection, "count");
    }
    count = Number(count);
    return isNaN(count) || count < 0 ? 0 : count;
  }

  function getCollectionItem(collection, oneBasedIndex) {
    if (!collection || oneBasedIndex < 1) {
      return null;
    }
    var zeroBasedIndex = oneBasedIndex - 1;
    if (typeof collection.length === "number" && collection[zeroBasedIndex]) {
      return collection[zeroBasedIndex];
    }
    if (typeof collection.Item === "function") {
      return safeCall(function () { return collection.Item(oneBasedIndex); }, collection);
    }
    if (typeof collection.item === "function") {
      return safeCall(function () { return collection.item(oneBasedIndex); }, collection);
    }
    return collection[oneBasedIndex] || collection[zeroBasedIndex] || null;
  }

  function getParagraphCollection(document) {
    var content = safeRead(document, "Content") || safeRead(document, "content");
    var range = resolveRange(document);
    return firstDefined(
      safeRead(document, "Paragraphs"),
      safeRead(document, "paragraphs"),
      safeRead(content, "Paragraphs"),
      safeRead(content, "paragraphs"),
      safeRead(range, "Paragraphs"),
      safeRead(range, "paragraphs"),
      []
    );
  }

  function collectParagraphsFromText(text, options) {
    var collectOptions = normalizeCollectOptions(options);
    var normalized = String(text || "").replace(/\r/g, "\n");
    if (!normalized.trim()) {
      return [];
    }
    var lines = normalized.split(/\n+/).map(function (line) {
      return line.trim();
    }).filter(Boolean);
    if (collectOptions.maxParagraphs) {
      lines = lines.slice(0, collectOptions.maxParagraphs);
    }
    return lines.map(function (line, index) {
      return {
        index: index + 1,
        text: limitTextLength(line, collectOptions.maxParagraphTextLength),
        styleName: "Normal",
        fontName: "",
        fontSize: 0,
        bold: false,
        italic: false,
        underline: null,
        alignment: "left",
        outlineLevel: 0,
        lineSpacing: null,
        firstLineIndent: null,
        spaceBefore: null,
        spaceAfter: null,
        leftIndent: null,
        rightIndent: null
      };
    });
  }

  function collectParagraphs(document, options) {
    var collectOptions = normalizeCollectOptions(options);
    var collection = getParagraphCollection(document);
    var count = readCollectionCount(collection);
    if (collectOptions.maxParagraphs) {
      count = Math.min(count, collectOptions.maxParagraphs);
    }
    var items = [];
    for (var i = 1; i <= count; i += 1) {
      var paragraph = getCollectionItem(collection, i);
      if (!paragraph) {
        continue;
      }
      var font = readFont(paragraph);
      var paragraphFormat = readParagraphFormat(paragraph);
      items.push({
        index: i,
        text: limitTextLength(readText(paragraph), collectOptions.maxParagraphTextLength),
        styleName: readStyleName(paragraph),
        fontName: toSafeString(firstDefined(safeRead(font, "NameFarEast"), safeRead(font, "Name")), ""),
        fontSize: normalizeNumber(firstDefined(safeRead(font, "Size"), 0)),
        bold: Boolean(safeRead(font, "Bold")),
        italic: Boolean(safeRead(font, "Italic")),
        underline: normalizeInteger(firstDefined(safeRead(font, "Underline"), null)),
        alignment: toSafeString(firstDefined(safeRead(paragraphFormat, "Alignment"), "left"), "left"),
        outlineLevel: normalizeInteger(firstDefined(safeRead(paragraphFormat, "OutlineLevel"), 0)),
        lineSpacing: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LineSpacing"), safeRead(paragraphFormat, "lineSpacing"), null)),
        firstLineIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "FirstLineIndent"), safeRead(paragraphFormat, "firstLineIndent"), null)),
        spaceBefore: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceBefore"), safeRead(paragraphFormat, "spaceBefore"), null)),
        spaceAfter: normalizeNumber(firstDefined(safeRead(paragraphFormat, "SpaceAfter"), safeRead(paragraphFormat, "spaceAfter"), null)),
        leftIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "LeftIndent"), safeRead(paragraphFormat, "leftIndent"), null)),
        rightIndent: normalizeNumber(firstDefined(safeRead(paragraphFormat, "RightIndent"), safeRead(paragraphFormat, "rightIndent"), null))
      });
    }
    if (items.length) {
      return items;
    }
    if (collectOptions.avoidFallbackTextRead) {
      return [];
    }
    return collectParagraphsFromText(readDocumentText(document), collectOptions);
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
    readCollectionCount: readCollectionCount,
    getCollectionItem: getCollectionItem,
    getParagraphCollection: getParagraphCollection,
    collectParagraphs: collectParagraphs,
    collectParagraphsFromText: collectParagraphsFromText,
    readDocumentText: readDocumentText,
    toSafeString: toSafeString,
    buildDocumentStructure: buildDocumentStructure
  };
});
