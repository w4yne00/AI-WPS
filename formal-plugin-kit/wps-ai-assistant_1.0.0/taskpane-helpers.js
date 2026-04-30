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

  function getEffectiveSelectionText(selection) {
    if (!selection) {
      return "";
    }
    return normalizeText(selection.Text || (selection.Range && selection.Range.Text) || "");
  }

  function resolveRewriteScope(options) {
    var selectionText = normalizeText(options.selectionText);
    if (options.requireSelection && !selectionText) {
      return {
        ok: false,
        selectionMode: "selection",
        scopeLabel: "当前范围：未检测到有效选区",
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
    resolveRewriteScope: resolveRewriteScope,
    canApplyRewriteToSelection: canApplyRewriteToSelection
  };
});
