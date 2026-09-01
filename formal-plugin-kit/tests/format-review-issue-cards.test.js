const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));
const wordHtml = fs.readFileSync(path.join(wordRoot, "taskpane.html"), "utf8");
const wordCss = fs.readFileSync(path.join(wordRoot, "taskpane.css"), "utf8");

function present(input) {
  assert.strictEqual(typeof helpers.presentDeterministicFormatReviewIssueView, "function");
  return helpers.presentDeterministicFormatReviewIssueView(input);
}

function sameLocationIssues() {
  return [
    {
      issueId: "font-1",
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 12,
      anchorId: "format-paragraph-12",
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt",
      message: "字号不符合模板要求。",
      suggestion: "建议调整字号。",
      evidence: [{ kind: "deterministic_format_fact", propertyPath: "format.fontSize" }],
      sourceAnchor: { textSnippet: "建设依据如下", paragraphIndex: 12 }
    },
    {
      issueId: "name-1",
      ruleId: "font_name",
      role: "body",
      paragraphIndex: 12,
      anchorId: "format-paragraph-12",
      anchorVerification: "verified",
      currentValue: "Unmapped Font",
      expectedValue: "宋体",
      message: "字体不符合模板要求。",
      suggestion: "建议调整字体。",
      sourceAnchor: { textSnippet: "建设依据如下", paragraphIndex: 12 }
    }
  ];
}

function headerSlice(html) {
  const start = html.indexOf("review-location-header");
  const body = html.indexOf("review-location-body");
  assert.ok(start >= 0, "missing location header");
  assert.ok(body >= 0, "missing location body");
  return html.slice(start, body);
}

function cssRule(selector) {
  const pattern = new RegExp(
    `(?:^|\\n)[ \\t]*${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[ \\t]*\\{([^}]*)\\}`,
    "g"
  );
  const match = Array.from(wordCss.matchAll(pattern)).pop();
  assert.ok(match, `missing CSS rule ${selector}`);
  return match[1];
}

function testPreviewShowsCoverageAndCountOnly() {
  const view = present({
    summary: {
      coverageStatus: "complete",
      executionStatus: "completed",
      complianceStatus: "violations_found",
      templateId: "technical-document-template-rules",
      rulePackVersion: "1.0.0"
    },
    total: 2,
    issues: sameLocationIssues()
  });

  assert.ok(view.previewText.includes("覆盖状态：已完成"));
  assert.ok(view.previewText.includes("问题数量：2"));
  assert.ok(!view.previewText.includes("问题清单"));
  assert.ok(!view.previewText.includes("详细说明"));
  assert.ok(!view.previewText.includes("| 位置 |"));
  assert.ok(!view.previewText.includes("当前值："));
  assert.ok(!view.previewText.includes("规则版本："));
  assert.ok(!view.previewText.includes("技术文档模板规则"));
}

function testSameAnchorIssuesFormOneCollapsedLocationCard() {
  // Break: each format issue still renders as its own expanded card with a locate button.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: sameLocationIssues()
  });

  assert.strictEqual(view.locationGroups.length, 1);
  assert.strictEqual(view.locationGroups[0].issueCount, 2);
  assert.strictEqual(view.locationGroups[0].issues[0].issueId, "font-1");
  assert.strictEqual(view.locationGroups[0].issues[1].issueId, "name-1");
  assert.ok(view.html.includes("建设依据如下"));
  assert.ok(view.html.includes("第 12 段"));
  assert.ok(view.html.includes("2 个问题"));
  assert.strictEqual((view.html.match(/data-format-review-action="locate"/g) || []).length, 1);
  assert.ok(view.html.includes(">定位<"));
  assert.ok(!view.html.includes("定位原文"));
  const header = headerSlice(view.html);
  assert.ok(header.indexOf("aria-expanded=\"false\"") >= 0);
  assert.ok(header.indexOf("aria-controls=") >= 0);
  assert.ok(header.indexOf("问题说明") < 0);
  assert.ok(header.indexOf("建议") < 0);
  assert.ok(header.indexOf("当前值 → 期望值") < 0);
  assert.ok(view.html.includes("hidden"));
}

function testExpandedIssueShowsValuePairAndSecondaryDetails() {
  // Break: first screen still dumps 说明/建议, or current/expected stay on separate unlabeled rows.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: sameLocationIssues()
  });
  const bodyStart = view.html.indexOf("review-location-body");
  const body = view.html.slice(bodyStart);
  assert.ok(body.includes("字号"));
  assert.ok(body.includes("四号（14pt） → 小四（12pt）"));
  assert.ok(body.includes("字体"));
  assert.ok(body.includes("无法识别 → 宋体"));
  assert.ok(!body.includes("Unmapped Font"));
  assert.ok(body.includes("<details"));
  assert.ok(body.includes("问题说明：字号不符合模板要求。"));
  assert.ok(body.includes("建议：请按模板要求调整字号。"));
  assert.ok(body.includes("证据：格式事实"));
  assert.ok(!headerSlice(view.html).includes("证据："));
  assert.ok(!body.includes('"kind":"deterministic_format_fact"'));
}

function testCaptionAssociationShowsConclusionNotUnrecognized() {
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "caption-1",
      ruleId: "structure.caption_association",
      role: "caption",
      paragraphIndex: 20,
      anchorId: "format-paragraph-20",
      anchorVerification: "verified",
      currentValue: "orphaned",
      expectedValue: "associated",
      sourceAnchor: { textSnippet: "表 9：跨节孤立" }
    }]
  });

  assert.ok(view.html.includes("孤立 → 已关联"));
  assert.ok(!view.html.includes("无法识别"));
  assert.ok(!view.html.includes("{\"status\""));
}

function testMissingAssociationConclusionDoesNotSayUnrecognized() {
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "caption-2",
      ruleId: "structure.caption_association",
      role: "caption",
      paragraphIndex: 8,
      anchorId: "format-paragraph-8",
      anchorVerification: "verified",
      currentValue: "",
      expectedValue: "associated",
      sourceAnchor: { textSnippet: "表题" }
    }]
  });

  assert.ok(!view.html.includes("无法识别"));
  assert.ok(!view.html.includes("题注关联结论："));
}

function testUnverifiedAnchorDisablesLocateWithoutHidingIt() {
  const view = present({
    summary: { coverageStatus: "partial" },
    issues: [{
      issueId: "orphan-1",
      ruleId: "structure.caption_association",
      role: "caption",
      anchorVerification: "unverified",
      currentValue: "missing",
      expectedValue: "associated"
    }]
  });

  assert.ok(view.html.includes(">定位<"));
  assert.ok(/data-format-review-action="locate"[^>]*disabled/.test(view.html));
  assert.strictEqual(view.locationGroups[0].locateEnabled, false);
}

function testProcessedAndIgnoredStatusStayPerIssue() {
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [
      {
        issueId: "a",
        ruleId: "alignment",
        role: "body",
        paragraphIndex: 3,
        anchorId: "format-paragraph-3",
        anchorVerification: "verified",
        currentValue: "left",
        expectedValue: "justify",
        status: "processed",
        sourceAnchor: { textSnippet: "第一处", paragraphIndex: 3 }
      },
      {
        issueId: "b",
        ruleId: "alignment",
        role: "body",
        paragraphIndex: 3,
        anchorId: "format-paragraph-3",
        anchorVerification: "verified",
        currentValue: "left",
        expectedValue: "justify",
        status: "ignored",
        sourceAnchor: { textSnippet: "第一处", paragraphIndex: 3 }
      }
    ]
  });

  const processedA = view.html.match(/data-format-review-action="processed" data-issue-id="a"[^>]*>/);
  const ignoredA = view.html.match(/data-format-review-action="ignored" data-issue-id="a"[^>]*>/);
  const processedB = view.html.match(/data-format-review-action="processed" data-issue-id="b"[^>]*>/);
  const ignoredB = view.html.match(/data-format-review-action="ignored" data-issue-id="b"[^>]*>/);
  assert.ok(processedA[0].includes("disabled"));
  assert.ok(!ignoredA[0].includes("disabled"));
  assert.ok(!processedB[0].includes("disabled"));
  assert.ok(ignoredB[0].includes("disabled"));
  assert.ok(!view.html.includes('data-format-review-action="processed" data-location-key'));
}

function testToolbarMovesFiltersAndExportsOffTheFirstScreen() {
  // Break: four full-width filters and two export buttons still sit in the result toolbar.
  assert.ok(wordHtml.includes('id="btn-format-review-filter"'));
  assert.ok(wordHtml.includes('id="format-review-filter-panel"'));
  assert.ok(wordHtml.includes('id="format-review-filter-status"'));
  assert.ok(wordHtml.includes('id="format-review-filter-count"'));
  assert.ok(wordHtml.includes('id="btn-format-review-more"'));
  assert.ok(wordHtml.includes('id="format-review-more-menu"'));
  const controls = wordHtml.slice(
    wordHtml.indexOf("id=\"deterministic-format-review-issue-controls\""),
    wordHtml.indexOf("id=\"settings-view\"")
  );
  const moreMenu = controls.slice(controls.indexOf("id=\"format-review-more-menu\""));
  assert.ok(moreMenu.includes("btn-format-review-export-json"));
  assert.ok(moreMenu.includes("btn-format-review-export-markdown"));
  assert.ok(controls.includes("format-review-filter-data-status"));
  assert.ok(controls.includes("format-review-filter-rule"));
  assert.ok(controls.includes("format-review-filter-sort"));
  assert.ok(!controls.includes("id=\"format-review-filter-severity\""));
  const toolbar = controls.slice(0, controls.indexOf("id=\"format-review-filter-panel\""));
  assert.ok(!toolbar.includes("导出 JSON"));
  assert.ok(!toolbar.includes("导出 Markdown"));
  assert.ok(!toolbar.includes("<select"));
  assert.ok(controls.includes("format-review-filter-wrap"));
  assert.ok(controls.includes("format-review-filter-badge"));
  const filterStart = wordHtml.indexOf('id="btn-format-review-filter"');
  const filterEnd = wordHtml.indexOf("</button>", filterStart);
  const filterBtn = wordHtml.slice(filterStart, filterEnd);
  assert.ok(!filterBtn.includes("format-review-filter-count"));
}

function testPageStatusAndFilterCountHelpers() {
  assert.strictEqual(
    helpers.formatDeterministicFormatReviewPageStatus({ page: 1, locationGroupCount: 6, pageSize: 1 }),
    "第 1 / 6 页"
  );
  assert.strictEqual(
    helpers.countEnabledFormatReviewFilters({
      rule: "",
      dataStatus: "",
      status: "",
      sort: "source"
    }),
    0
  );
  assert.strictEqual(
    helpers.countEnabledFormatReviewFilters({
      rule: "font_size",
      dataStatus: "verified",
      status: "open",
      sort: "rule"
    }),
    4
  );
}

function testKeyboardHelperClosesPanelAndMovesFocus() {
  const events = [];
  const jsonItem = { tagName: "BUTTON", focus: function () { events.push("json"); } };
  const mdItem = { tagName: "BUTTON", focus: function () { events.push("markdown"); } };
  const panel = {
    hidden: false,
    querySelectorAll: function () { return [jsonItem, mdItem]; }
  };
  const trigger = {
    attrs: { "aria-expanded": "true" },
    setAttribute: function (name, value) { this.attrs[name] = value; events.push("aria:" + value); },
    focus: function () { events.push("trigger"); }
  };

  helpers.handleFormatReviewAnchoredPanelKeydown(
    { key: "Escape", preventDefault: function () { events.push("prevent"); } },
    { panel: panel, trigger: trigger }
  );
  assert.strictEqual(panel.hidden, true);
  assert.strictEqual(trigger.attrs["aria-expanded"], "false");
  assert.deepStrictEqual(events, ["prevent", "aria:false", "trigger"]);

  events.length = 0;
  panel.hidden = false;
  trigger.attrs["aria-expanded"] = "true";
  helpers.handleFormatReviewAnchoredPanelKeydown(
    { key: "ArrowDown", preventDefault: function () { events.push("prevent-down"); } },
    { panel: panel, trigger: trigger, activeElement: jsonItem }
  );
  assert.deepStrictEqual(events, ["prevent-down", "markdown"]);

  events.length = 0;
  const ruleInput = { tagName: "INPUT", focus: function () { events.push("input"); } };
  helpers.handleFormatReviewAnchoredPanelKeydown(
    { key: "ArrowDown", preventDefault: function () { events.push("prevent-input"); } },
    { panel: panel, trigger: trigger, activeElement: ruleInput }
  );
  assert.deepStrictEqual(events, []);

  events.length = 0;
  panel.hidden = true;
  helpers.setFormatReviewAnchoredPanelOpen(panel, trigger, true);
  assert.strictEqual(panel.hidden, false);
  assert.strictEqual(trigger.attrs["aria-expanded"], "true");
  assert.deepStrictEqual(events, ["aria:true", "json"]);
}

function testGeometryAndReducedMotion() {
  const pagerButtons = cssRule(".format-review-pager button");
  assert.ok(/min-height:\s*44px/.test(pagerButtons));
  assert.ok(/min-width:\s*44px/.test(pagerButtons));
  assert.ok(/width:\s*100%/.test(pagerButtons));
  const issueActions = cssRule(".review-issue-item .review-action-row button");
  assert.ok(/min-height:\s*44px/.test(issueActions));
  assert.ok(/min-width:\s*44px/.test(issueActions));
  const icon = cssRule(".format-review-icon-button");
  assert.ok(/width:\s*44px/.test(icon));
  assert.ok(/height:\s*44px/.test(icon));
  const iconGlyph = cssRule(".format-review-icon-button > span");
  assert.ok(/width:\s*32px/.test(iconGlyph));
  assert.ok(/height:\s*32px/.test(iconGlyph));
  const badge = cssRule(".format-review-filter-badge");
  assert.ok(/position:\s*absolute/.test(badge));
  const narrow320 = wordCss.slice(wordCss.indexOf("@media (max-width: 320px)"));
  const narrow420 = wordCss.slice(wordCss.indexOf("@media (max-width: 420px)"));
  assert.ok(narrow320.includes(".format-review-toolbar"));
  assert.ok(narrow420.includes(".format-review-toolbar"));
  assert.ok(wordCss.includes("overflow-wrap: anywhere"));
  const reduced = wordCss.slice(wordCss.indexOf("@media (prefers-reduced-motion: reduce)"));
  assert.ok(reduced.includes(".review-location-card"));
  assert.ok(reduced.includes("transform: none"));
}

function testExportMarkdownStillKeepsIssueTable() {
  const markdown = helpers.renderReadableDeterministicFormatReview({
    summary: { coverageStatus: "complete", templateId: "technical-document-template-rules" },
    issues: [{
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 1,
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt"
    }]
  });
  const view = present({
    summary: { coverageStatus: "complete" },
    total: 1,
    issues: [{
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 1,
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt"
    }]
  });

  assert.ok(markdown.includes("## 问题清单"));
  assert.ok(markdown.includes("## 详细说明"));
  assert.ok(!view.previewText.includes("## 问题清单"));
}

testPreviewShowsCoverageAndCountOnly();
testSameAnchorIssuesFormOneCollapsedLocationCard();
testExpandedIssueShowsValuePairAndSecondaryDetails();
testCaptionAssociationShowsConclusionNotUnrecognized();
testMissingAssociationConclusionDoesNotSayUnrecognized();
testUnverifiedAnchorDisablesLocateWithoutHidingIt();
testProcessedAndIgnoredStatusStayPerIssue();
testToolbarMovesFiltersAndExportsOffTheFirstScreen();
testPageStatusAndFilterCountHelpers();
testKeyboardHelperClosesPanelAndMovesFocus();
testGeometryAndReducedMotion();
testExportMarkdownStillKeepsIssueTable();

console.log("format review issue card tests passed");
