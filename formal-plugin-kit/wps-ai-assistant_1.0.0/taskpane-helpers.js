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

  return {
    normalizeText: normalizeText,
    getEffectiveSelectionText: getEffectiveSelectionText,
    getWritableSelection: getWritableSelection,
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection
  };
});
