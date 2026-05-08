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
    getEffectiveSelectionText: getEffectiveSelectionText,
    getWritableSelection: getWritableSelection,
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection,
    buildDocumentStructure: buildDocumentStructure
  };
});
