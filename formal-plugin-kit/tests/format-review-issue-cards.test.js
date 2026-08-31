const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));
const wordJs = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");

function present(input) {
  assert.strictEqual(typeof helpers.presentDeterministicFormatReviewIssueView, "function");
  return helpers.presentDeterministicFormatReviewIssueView(input);
}

function functionSource(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = source.indexOf("\n  function ", start + 1);
  return source.slice(start, end < 0 ? source.length : end);
}

function locateButtonHtml(html) {
  const match = String(html || "").match(/<button\b[^>]*>定位原文<\/button>/);
  assert.ok(match, "missing locate button");
  return match[0];
}

function actionBarSlice(html) {
  const start = html.indexOf("定位原文");
  const end = html.indexOf("标记已忽略");
  assert.ok(start >= 0, "missing 定位原文");
  assert.ok(end >= 0, "missing 标记已忽略");
  return html.slice(start, end + "标记已忽略".length);
}

function testPreviewShowsCoverageAndCountOnly() {
  // Break: preview still dumps the issue table / 详细说明 as the operation surface.
  const view = present({
    summary: {
      coverageStatus: "complete",
      executionStatus: "completed",
      complianceStatus: "violations_found",
      templateId: "technical-document-template-rules",
      rulePackVersion: "1.0.0"
    },
    total: 2,
    issues: [
      {
        issueId: "font-1",
        ruleId: "font_size",
        role: "body",
        paragraphIndex: 12,
        anchorVerification: "verified",
        currentValue: "14pt",
        expectedValue: "12pt"
      },
      {
        issueId: "caption-1",
        ruleId: "structure.caption_association",
        role: "caption",
        paragraphIndex: 20,
        anchorVerification: "verified",
        currentValue: "orphaned",
        expectedValue: "associated",
        sourceAnchor: { textSnippet: "表 9：跨节孤立" }
      }
    ]
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

function testCardPutsActionBarAboveLocationAndKeepsButtonsTogether() {
  // Break: location sentence and the three buttons share one inline node.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "font-1",
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 12,
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt"
    }]
  });

  const html = view.html;
  assert.ok(html.indexOf("定位原文") < html.indexOf("标记已处理"));
  assert.ok(html.indexOf("标记已处理") < html.indexOf("标记已忽略"));
  assert.ok(html.indexOf("定位原文") < html.indexOf("位置："));
  assert.ok(html.indexOf("位置：") < html.indexOf("角色："));
  assert.ok(actionBarSlice(html).indexOf("第 12 段") < 0);
  assert.ok(html.includes("位置：第 12 段"));
  assert.ok(html.includes("角色：正文"));
  assert.ok(html.includes("问题说明："));
  assert.ok(html.includes("建议："));
}

function testUnverifiedAnchorDisablesLocateWithoutHidingIt() {
  // Break: locate is hidden, or still enabled, when the anchor is unverified.
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

  const button = locateButtonHtml(view.html);
  assert.ok(button.indexOf("disabled") >= 0);
  assert.ok(view.html.includes("定位原文"));
  assert.ok(view.cards[0].locateEnabled === false);
}

function testVerifiedAnchorKeepsLocateEnabled() {
  // Break: locate is always disabled.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "font-1",
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 1,
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt"
    }]
  });

  const button = locateButtonHtml(view.html);
  assert.ok(button.indexOf("disabled") < 0);
  assert.strictEqual(view.cards[0].locateEnabled, true);
}

function testCaptionAssociationShowsConclusionNotUnrecognized() {
  // Break: association conclusion is shown as 无法识别.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "caption-1",
      ruleId: "structure.caption_association",
      role: "caption",
      paragraphIndex: 20,
      anchorVerification: "verified",
      currentValue: "orphaned",
      expectedValue: "associated",
      sourceAnchor: { textSnippet: "表 9：跨节孤立" }
    }]
  });

  assert.ok(view.html.includes("题注关联结论：孤立"));
  assert.ok(!view.html.includes("无法识别"));
  assert.ok(!view.html.includes("{\"status\""));
}

function testMissingAssociationConclusionDoesNotSayUnrecognized() {
  // Break: empty association currentValue is displayed as 无法识别.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "caption-2",
      ruleId: "structure.caption_association",
      role: "caption",
      paragraphIndex: 8,
      anchorVerification: "verified",
      currentValue: "",
      expectedValue: "associated"
    }]
  });

  assert.ok(!view.html.includes("无法识别"));
  assert.ok(!view.html.includes("题注关联结论："));
}

function testOrdinaryFormatIssueShowsUserDisplayValue() {
  // Break: font-size card omits the user-facing 四号 display value.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "font-1",
      ruleId: "font_size",
      role: "body",
      paragraphIndex: 1,
      anchorVerification: "verified",
      currentValue: "14pt",
      expectedValue: "12pt"
    }]
  });

  assert.ok(view.html.includes("当前值：四号（14pt）"));
  assert.ok(!view.html.includes("题注关联结论："));
}

function testUnmappedFontStaysUnrecognized() {
  // Break: unmapped font name leaks into the card.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [{
      issueId: "font-2",
      ruleId: "font_name",
      role: "body",
      paragraphIndex: 1,
      anchorVerification: "verified",
      currentValue: "Unmapped Font",
      expectedValue: "宋体"
    }]
  });

  assert.ok(view.html.includes("当前值：无法识别"));
  assert.ok(!view.html.includes("Unmapped Font"));
}

function testProcessedAndIgnoredStatusStayPerIssue() {
  // Break: processed/ignored disable state is shared across instances.
  const view = present({
    summary: { coverageStatus: "complete" },
    issues: [
      {
        issueId: "a",
        ruleId: "alignment",
        role: "body",
        paragraphIndex: 3,
        anchorVerification: "verified",
        currentValue: "left",
        expectedValue: "justify",
        status: "processed"
      },
      {
        issueId: "b",
        ruleId: "alignment",
        role: "body",
        paragraphIndex: 4,
        anchorVerification: "verified",
        currentValue: "left",
        expectedValue: "justify",
        status: "ignored"
      }
    ]
  });

  assert.strictEqual(view.cards[0].processedEnabled, false);
  assert.strictEqual(view.cards[0].ignoredEnabled, true);
  assert.strictEqual(view.cards[1].processedEnabled, true);
  assert.strictEqual(view.cards[1].ignoredEnabled, false);
  assert.ok(view.html.includes('data-issue-id="a"'));
  assert.ok(view.html.includes('data-issue-id="b"'));
}

function testExportMarkdownStillKeepsIssueTable() {
  // Break: removing the preview table also deletes it from export markdown.
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

function testIssuePageNoLongerMixesLocationIntoButtonRow() {
  // Break: renderDeterministicFormatReviewIssuePage still concatenates
  // location text and the three buttons onto one unstyled row.
  const issuePage = functionSource(wordJs, "renderDeterministicFormatReviewIssuePage");
  assert.ok(issuePage.includes("presentDeterministicFormatReviewIssueView"));
  assert.ok(!issuePage.includes("full-review-issue-row"));
  assert.ok(!issuePage.includes("row.textContent = deterministicFormatReviewIssuePosition"));
}

testPreviewShowsCoverageAndCountOnly();
testCardPutsActionBarAboveLocationAndKeepsButtonsTogether();
testUnverifiedAnchorDisablesLocateWithoutHidingIt();
testVerifiedAnchorKeepsLocateEnabled();
testCaptionAssociationShowsConclusionNotUnrecognized();
testMissingAssociationConclusionDoesNotSayUnrecognized();
testOrdinaryFormatIssueShowsUserDisplayValue();
testUnmappedFontStaysUnrecognized();
testProcessedAndIgnoredStatusStayPerIssue();
testExportMarkdownStillKeepsIssueTable();
testIssuePageNoLongerMixesLocationIntoButtonRow();

console.log("format review issue card tests passed");
