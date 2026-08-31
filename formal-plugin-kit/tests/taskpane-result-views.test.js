const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { wordRoot, etRoot, pptRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));
const excelHelpers = require(path.join(etRoot, "taskpane-helpers.js"));

const pptContext = { window: {} };
vm.createContext(pptContext);
vm.runInContext(
  fs.readFileSync(path.join(pptRoot, "taskpane-helpers.js"), "utf8"),
  pptContext
);
const pptHelpers = pptContext.window.WpsAiPptHelpers;

function presentWord(input) {
  assert.strictEqual(typeof helpers.presentWordResultView, "function");
  return helpers.presentWordResultView(input);
}

function presentExcel(input) {
  assert.strictEqual(typeof excelHelpers.presentExcelAnalysisResultView, "function");
  return excelHelpers.presentExcelAnalysisResultView(input);
}

function presentPpt(input) {
  assert.strictEqual(typeof pptHelpers.presentPptSummaryResultView, "function");
  return pptHelpers.presentPptSummaryResultView(input);
}

function testWordPreviewRendersStructuredMarkdown() {
  // Break: preview of headings/lists/tables falls back to source (`# 结论` visible).
  const view = presentWord({
    originalText: "一、总体要求\n原文。",
    rewrittenText: [
      "# 结论",
      "",
      "- **通过**",
      "",
      "| 项目 | 状态 |",
      "| --- | --- |",
      "| 任务 | 已完成 |"
    ].join("\n"),
    view: "preview",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h1>结论</h1>"));
  assert.ok(view.html.includes("<ul>"));
  assert.ok(view.html.includes("<strong>通过</strong>"));
  assert.ok(!view.html.includes("# 结论"));
  assert.ok(view.html.includes("项目"));
  assert.ok(view.html.includes("已完成"));
}

function testWordPreviewRendersUnstructuredParagraph() {
  // Break: no heading/list/table → preview uses source wall instead of a paragraph.
  const view = presentWord({
    originalText: "原文只有一段说明。",
    rewrittenText: "优化后的一段说明，没有标题或列表。",
    view: "preview",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<p>"));
  assert.ok(view.html.includes("优化后的一段说明，没有标题或列表。"));
  assert.ok(!view.sourceText);
}

function testWordCompareStaysRenderedWithInsertHighlight() {
  // Break: compare becomes raw markdown (`### 原文` / `==优化后==`).
  const view = presentWord({
    originalText: "第一段原文。",
    rewrittenText: "第一段优化后。",
    view: "compare",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h3>原文</h3>"));
  assert.ok(view.html.includes("<h3>智能编写结果</h3>"));
  assert.ok(view.html.includes("第一段原文。"));
  assert.ok(view.html.includes('<mark class="smart-diff-highlight">优化后</mark>'));
  assert.ok(!view.html.includes("### 原文"));
  assert.ok(!view.html.includes("==优化后=="));
}

function testWordPlainViewIsUnrenderedSource() {
  // Break: plain view is rendered HTML instead of source.
  const view = presentWord({
    originalText: "一、总体要求\n原文。",
    rewrittenText: "# 结论\n\n一段正文。",
    view: "plain",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "source");
  assert.strictEqual(view.sourceText, "# 结论\n\n一段正文。");
  assert.strictEqual(view.html, "");
}

function testWordCopyAndWritebackIgnoreCurrentView() {
  // Break: copy/writeback read the current view HTML or compare markdown.
  const resultText = "# 结论\n\n- 第一项";
  const preview = presentWord({
    rewrittenText: resultText,
    view: "preview",
    rewriteMode: "rewrite"
  });
  const compare = presentWord({
    originalText: "原文",
    rewrittenText: resultText,
    view: "compare",
    rewriteMode: "rewrite"
  });
  const plain = presentWord({
    rewrittenText: resultText,
    view: "plain",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(preview.copyText, resultText);
  assert.strictEqual(compare.copyText, resultText);
  assert.strictEqual(plain.copyText, resultText);
  assert.strictEqual(preview.writebackText, resultText);
  assert.strictEqual(compare.writebackText, resultText);
  assert.strictEqual(plain.writebackText, resultText);
  assert.ok(!preview.copyText.includes("<"));
  assert.ok(!plain.copyText.includes("<h1>"));
}

function testWordImitationHasNoCompare() {
  // Break: imitation exposes compare, or compare view shows 原文/结果.
  const compare = presentWord({
    originalText: "样例原文。",
    rewrittenText: "仿写结果。",
    view: "compare",
    rewriteMode: "imitate"
  });

  assert.strictEqual(compare.compareAvailable, false);
  assert.strictEqual(compare.presentation, "rendered");
  assert.ok(!compare.html.includes("<h3>原文</h3>"));
  assert.ok(!compare.html.includes("<h3>智能编写结果</h3>"));
  assert.ok(compare.html.includes("仿写结果。"));
}

function testWordPreviewRejectsHtmlScriptsImagesAndLinkNavigation() {
  // Break: preview emits raw HTML, <script>, <img>, or clickable href.
  const view = presentWord({
    rewrittenText: [
      '<script>alert(1)</script>',
      '<img src="https://cdn.example.com/x.png" onerror="alert(1)">',
      "![示意图](https://cdn.example.com/diagram.png)",
      "[官网](https://example.com/path?a=1&b=2)",
      "[危险](javascript:alert(1))"
    ].join("\n"),
    view: "preview",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("&lt;script&gt;") || view.html.includes("&lt;script"));
  assert.ok(!/<script\b/i.test(view.html));
  assert.ok(!/<img\b/i.test(view.html));
  assert.ok(!/src\s*=\s*["']https:\/\/cdn\.example\.com/i.test(view.html));
  assert.ok(view.html.includes("官网"));
  assert.ok(view.html.includes("危险"));
  assert.ok(!/href\s*=/i.test(view.html));
  assert.ok(!/<a\b/i.test(view.html));
  assert.ok(!view.html.includes("javascript:"));
}

function testWordPreviewTablesAreReadableBlocks() {
  // Break: table is only a wide <table> whose header text appears once in thead.
  const view = presentWord({
    rewrittenText: [
      "| 字段甲 | 字段乙 |",
      "| --- | --- |",
      "| 值一 | 值二 |",
      "| 值三 | 值四 |"
    ].join("\n"),
    view: "preview",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok((view.html.match(/字段甲/g) || []).length >= 2);
  assert.ok(view.html.includes("值一"));
  assert.ok(view.html.includes("值三"));
  assert.ok(!/<table\b/i.test(view.html));
}

function testExcelAnalysisReportRendersAndKeepsNames() {
  // Break: Excel preview is source, or buttons are renamed 预览/纯文本.
  const view = presentExcel({
    result: {
      structuredReport: {
        overview: "本月完成 **3** 项。",
        findings: ["发现一项"],
        risks: ["风险一项"],
        actions: ["动作一项"]
      },
      plainText: "本月完成3项，建议继续跟踪。"
    },
    view: "preview"
  });

  assert.deepStrictEqual(view.viewLabels, {
    preview: "分析报告",
    plain: "汇报段落"
  });
  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h2>数据概览</h2>"));
  assert.ok(view.html.includes("<strong>3</strong>"));
  assert.ok(view.html.includes("<li>发现一项</li>"));
  assert.ok(!view.html.includes("## 数据概览"));
  assert.strictEqual(view.copyText.includes("<h2>"), false);
}

function testExcelReportParagraphStaysUnrendered() {
  // Break: 汇报段落 is rendered HTML or replaced by report source.
  const view = presentExcel({
    result: {
      structuredReport: {
        overview: "概览",
        findings: ["发现"],
        risks: [],
        actions: []
      },
      plainText: "可粘贴简述，不含标题。"
    },
    view: "plain"
  });

  assert.strictEqual(view.presentation, "source");
  assert.strictEqual(view.sourceText, "可粘贴简述，不含标题。");
  assert.strictEqual(view.copyText, "可粘贴简述，不含标题。");
  assert.strictEqual(view.html, "");
  assert.strictEqual(view.viewLabels.plain, "汇报段落");
}

function testExcelPreviewRejectsLinkNavigationAndOnlineImages() {
  // Break: Excel report preview keeps <a href> or <img src>.
  const view = presentExcel({
    result: {
      structuredReport: {
        overview: "见 [说明](https://example.com/doc) 与 ![图](https://cdn.example.com/a.png)",
        findings: [],
        risks: [],
        actions: []
      },
      plainText: "简述"
    },
    view: "preview"
  });

  assert.ok(view.html.includes("说明"));
  assert.ok(!/href\s*=/i.test(view.html));
  assert.ok(!/<a\b/i.test(view.html));
  assert.ok(!/<img\b/i.test(view.html));
}

function testExcelFormulaAssistantHasNoAnalysisSwitch() {
  // Break: formula assistant starts showing 分析报告/汇报段落.
  assert.strictEqual(excelHelpers.shouldShowExcelResultViewSwitch("excelAnalysis"), true);
  assert.strictEqual(excelHelpers.shouldShowExcelResultViewSwitch("excelFormulaAssistant"), false);
}

function testHostMarkupKeepsExcelSwitchNames() {
  // Break: Excel HTML buttons renamed to 预览/纯文本.
  const excelHtml = fs.readFileSync(
    path.join(etRoot, "taskpane.html"),
    "utf8"
  );
  const wordHtml = fs.readFileSync(
    path.join(wordRoot, "taskpane.html"),
    "utf8"
  );

  assert.ok(excelHtml.includes(">分析报告</button>"));
  assert.ok(excelHtml.includes(">汇报段落</button>"));
  assert.ok(!excelHtml.includes(">预览</button>"));
  assert.ok(!excelHtml.includes(">纯文本</button>"));
  assert.ok(wordHtml.includes(">预览</button>"));
  assert.ok(wordHtml.includes(">对照</button>"));
  assert.ok(wordHtml.includes(">纯文本</button>"));
}

function samplePptRawAnswer() {
  return [
    "# 结论",
    "",
    "- **通过**",
    "",
    "| 项目 | 状态 |",
    "| --- | --- |",
    "| 任务 | 已完成 |",
    "| 风险 | 已关闭 |"
  ].join("\n");
}

function testPptPreviewRendersStructuredSlideMarkdown() {
  // Break: structured slide preview stays source (`## 建议标题`, `- **通过**`).
  const view = presentPpt({
    result: {
      suggestedTitle: "本页建议标题",
      bullets: ["**通过**", "下一步联调"],
      conclusion: "保持当前节奏。"
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h2>"));
  assert.ok(view.html.includes("本页建议标题"));
  assert.ok(view.html.includes("<ul>"));
  assert.ok(view.html.includes("<strong>通过</strong>"));
  assert.ok(!view.html.includes("## 建议标题"));
}

function testPptPreviewRendersUnstructuredRawAnswer() {
  // Break: rawAnswer-only preview is forced to source (`# 结论` visible).
  const view = presentPpt({
    result: {
      rawAnswer: samplePptRawAnswer()
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h1>结论</h1>"));
  assert.ok(view.html.includes("<ul>"));
  assert.ok(view.html.includes("<strong>通过</strong>"));
  assert.ok(view.html.includes("项目"));
  assert.ok(view.html.includes("已完成"));
  assert.ok(!view.html.includes("# 结论"));
  assert.ok(!view.sourceText);
}

function testPptPreviewIgnoresRawAnswerWhenStructuredSlideExists() {
  // Break: any rawAnswer hijacks preview to plaintext even if structured fields exist.
  const view = presentPpt({
    result: {
      suggestedTitle: "结构化标题",
      bullets: ["要点一"],
      conclusion: "结构化结论",
      rawAnswer: "# 这段源码不应成为预览"
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("结构化标题"));
  assert.ok(view.html.includes("<ul>"));
  assert.ok(!view.html.includes("# 这段源码不应成为预览"));
}

function testPptDocumentFallbackStillRenders() {
  // Break: document parse fallback uses setPlainResult / presentation === source.
  const view = presentPpt({
    result: {
      resultType: "document",
      parseFallbackReason: "unstructured",
      rawAnswer: samplePptRawAnswer()
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("<h1>结论</h1>"));
  assert.ok(view.html.includes("<strong>通过</strong>"));
  assert.ok(!view.html.includes("# 结论"));
}

function testPptPlainViewIsUnrenderedSource() {
  // Break: plain view is rendered HTML instead of source.
  const raw = samplePptRawAnswer();
  const view = presentPpt({
    result: { rawAnswer: raw },
    view: "plain"
  });

  assert.strictEqual(view.presentation, "source");
  assert.strictEqual(view.sourceText, raw);
  assert.strictEqual(view.html, "");
}

function testPptCopyIgnoresCurrentView() {
  // Break: copy reads rendered HTML.
  const raw = samplePptRawAnswer();
  const preview = presentPpt({ result: { rawAnswer: raw }, view: "preview" });
  const plain = presentPpt({ result: { rawAnswer: raw }, view: "plain" });

  assert.strictEqual(preview.copyText, raw);
  assert.strictEqual(plain.copyText, raw);
  assert.ok(!preview.copyText.includes("<h1>"));
}

function testPptPreviewRejectsHtmlScriptsImagesAndLinkNavigation() {
  // Break: preview emits raw HTML, <script>, <img>, or clickable href.
  const view = presentPpt({
    result: {
      rawAnswer: [
        "<script>alert(1)</script>",
        '<img src="https://cdn.example.com/x.png" onerror="alert(1)">',
        "![示意图](https://cdn.example.com/diagram.png)",
        "[官网](https://example.com/path?a=1&b=2)",
        "[危险](javascript:alert(1))"
      ].join("\n")
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok(view.html.includes("&lt;script&gt;") || view.html.includes("&lt;script"));
  assert.ok(!/<script\b/i.test(view.html));
  assert.ok(!/<img\b/i.test(view.html));
  assert.ok(!/src\s*=\s*["']https:\/\/cdn\.example\.com/i.test(view.html));
  assert.ok(view.html.includes("官网"));
  assert.ok(view.html.includes("危险"));
  assert.ok(!/href\s*=/i.test(view.html));
  assert.ok(!/<a\b/i.test(view.html));
  assert.ok(!view.html.includes("javascript:"));
}

function testPptPreviewTablesAreReadableBlocks() {
  // Break: table is only a wide <table> whose header text appears once.
  const view = presentPpt({
    result: {
      rawAnswer: [
        "| 字段甲 | 字段乙 |",
        "| --- | --- |",
        "| 值一 | 值二 |",
        "| 值三 | 值四 |"
      ].join("\n")
    },
    view: "preview"
  });

  assert.strictEqual(view.presentation, "rendered");
  assert.ok((view.html.match(/字段甲/g) || []).length >= 2);
  assert.ok(view.html.includes("值一"));
  assert.ok(view.html.includes("值三"));
  assert.ok(!/<table\b/i.test(view.html));
}

function testPptStructureReviewAreaStaysSeparate() {
  // Break: structure review result is folded into 预览/纯文本.
  const html = fs.readFileSync(
    path.join(pptRoot, "taskpane.html"),
    "utf8"
  );
  const structureStart = html.indexOf('id="structure-result-section"');
  const summaryStart = html.indexOf('id="summary-result-section"');
  assert.ok(structureStart > 0);
  assert.ok(summaryStart > 0);
  const structureChunk = html.slice(structureStart, structureStart + 800);
  const summaryChunk = html.slice(summaryStart, html.indexOf('id="structure-review-controls"'));

  assert.ok(summaryChunk.includes(">预览</button>"));
  assert.ok(summaryChunk.includes(">纯文本</button>"));
  assert.ok(summaryChunk.includes('id="result-output"'));
  assert.ok(structureChunk.includes('id="structure-result-output"'));
  assert.ok(!structureChunk.includes(">预览</button>"));
  assert.ok(!structureChunk.includes(">纯文本</button>"));
  assert.ok(!structureChunk.includes('id="result-view-switch"'));
}

testWordPreviewRendersStructuredMarkdown();
testWordPreviewRendersUnstructuredParagraph();
testWordCompareStaysRenderedWithInsertHighlight();
testWordPlainViewIsUnrenderedSource();
testWordCopyAndWritebackIgnoreCurrentView();
testWordImitationHasNoCompare();
testWordPreviewRejectsHtmlScriptsImagesAndLinkNavigation();
testWordPreviewTablesAreReadableBlocks();
testExcelAnalysisReportRendersAndKeepsNames();
testExcelReportParagraphStaysUnrendered();
testExcelPreviewRejectsLinkNavigationAndOnlineImages();
testExcelFormulaAssistantHasNoAnalysisSwitch();
testHostMarkupKeepsExcelSwitchNames();
testPptPreviewRendersStructuredSlideMarkdown();
testPptPreviewRendersUnstructuredRawAnswer();
testPptPreviewIgnoresRawAnswerWhenStructuredSlideExists();
testPptDocumentFallbackStillRenders();
testPptPlainViewIsUnrenderedSource();
testPptCopyIgnoresCurrentView();
testPptPreviewRejectsHtmlScriptsImagesAndLinkNavigation();
testPptPreviewTablesAreReadableBlocks();
testPptStructureReviewAreaStaysSeparate();

console.log("taskpane result view tests passed");
