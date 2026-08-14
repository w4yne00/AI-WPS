const assert = require("assert");
const fs = require("fs");

const root = "formal-plugin-kit/wps-ai-assistant_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const helpers = require("../wps-ai-assistant_1.0.0/taskpane-helpers.js");

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

assert.ok(html.includes('id="deterministic-format-review-entry"'));
assert.ok(html.includes('id="btn-run-deterministic-format-review"'));
const entryStart = html.indexOf('id="deterministic-format-review-entry"');
assert.ok(html.slice(entryStart, entryStart + 180).includes("hidden"));
assert.ok(js.includes("deterministicFormatReviewEnabled: false"));

const applyConfig = functionSource("applyProviderConfig");
assert.ok(applyConfig.includes("deterministicFormatReviewEnabled"));
assert.ok(applyConfig.includes("renderDeterministicFormatReviewEntry"));

const renderEntry = functionSource("renderDeterministicFormatReviewEntry");
assert.ok(renderEntry.includes("state.deterministicFormatReviewEnabled"));
assert.ok(renderEntry.includes("entry.hidden"));
assert.ok(renderEntry.includes("button.disabled"));

const run = functionSource("runDeterministicFormatReview");
[
  "/word/format-review/snapshots",
  "/word/format-review/jobs",
  "DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS",
  "snapshotToken",
  "pollDeterministicFormatReviewJob"
].forEach((token) => assert.ok(run.includes(token), token));
[
  "InsertAfter",
  "Text =",
  "Delete",
  "applyRewrite"
].forEach((token) => assert.ok(!run.includes(token), token));

const cleanup = functionSource("discardDeterministicFormatReviewSnapshot");
assert.ok(cleanup.includes("/word/format-review/snapshots/"));
assert.ok(cleanup.includes('method: "DELETE"'));

const poll = functionSource("pollDeterministicFormatReviewJob");
assert.ok(poll.includes("/word/format-review/jobs/"));
assert.ok(poll.includes('job.status === "completed"'));
assert.ok(poll.includes("renderGroupedFormatReview"));
assert.ok(poll.includes("loadDeterministicFormatReviewReport"));

const issuePage = functionSource("renderDeterministicFormatReviewIssuePage");
["executionStatus", "complianceStatus", "coverageStatus", "semanticStatus", "issueId",
  "propertyPath", "duplicateGroupSize", "anchorVerification"].forEach((token) => {
  assert.ok(issuePage.includes(token), token);
});
const locate = functionSource("locateDeterministicFormatReviewIssue");
["textSha256", "adjacentStructureSha256", "anchorVerification", "markDeterministicFormatReviewAnchorVerification"].forEach((token) => {
  assert.ok(locate.includes(token), token);
});
assert.ok(functionSource("loadDeterministicFormatReviewIssuePage").includes("dataStatus"));
assert.ok(functionSource("downloadDeterministicFormatReviewExport").includes("word-format-review"));
assert.ok(functionSource("bindEvents").includes("format-review-filter-data-status"));
assert.ok(functionSource("cancelDeterministicFormatReviewJob").includes('method: "DELETE"'));

assert.ok(js.includes('configData.features && configData.features.deterministicFormatReviewEnabled'));
assert.ok(js.includes('byId("btn-run-deterministic-format-review")'));

const body = helpers.buildDeterministicFormatReviewBody({
  documentId: "table.docx",
  selectionMode: "document",
  content: {
    paragraphs: [{ index: 1, text: "正文", styleName: "Normal" }],
    documentStructure: {
      page_setup: { paperSize: "A4", marginTop: 72 },
      tables: [{
        tableId: "table-1",
        rows: [{ cells: [{ text: "表头" }] }, { cells: [{ text: "单元格" }] }]
      }]
    }
  }
});
assert.strictEqual(body.reviewCharacterCount, "正文".length + "表头\n单元格".length);
assert.strictEqual(body.coverage.tableCount, 1);
assert.deepStrictEqual(body.pageSetup, { paperSize: "A4", marginTop: 72 });
const batches = helpers.buildDeterministicFormatReviewBatches(body, 1);
assert.ok(batches.length >= 2);
assert.strictEqual(batches[0].characterCount, batches[0].blocks
  .filter((block) => block.scope === "in_scope")
  .reduce((sum, block) => sum + String(block.text || "").length, 0));
const captionBody = helpers.buildDeterministicFormatReviewBody({
  selectionMode: "selection",
  content: {
    paragraphs: [{ index: 1, text: "表 1：测试", styleName: "Caption" }],
    documentStructure: {}
  }
});
assert.strictEqual(captionBody.blocks[0].blockType, "caption");
assert.strictEqual(captionBody.coverage.captionCount, 1);

assert.deepStrictEqual(helpers.getDeterministicFormatReviewCapacity(60000), {
  tier: "standard",
  accepted: true,
  requiresConfirmation: false
});
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(60001).tier, "large");
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(120000).accepted, true);
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(120001).accepted, false);

const mixedRange = {
  Text: "甲乙丙丁",
  Font: { Name: "混合", Size: 9999999, Bold: 9999999 },
  Characters(start, end) {
    const formats = [
      { Name: "宋体", Size: 12, Bold: false },
      { Name: "宋体", Size: 12, Bold: false },
      { Name: "黑体", Size: 12, Bold: true },
      { Name: "黑体", Size: 14, Bold: true }
    ];
    const first = start - 1;
    const last = end || start;
    const selected = formats.slice(first, last);
    const same = selected.every((item) => JSON.stringify(item) === JSON.stringify(selected[0]));
    return {
      Text: this.Text.slice(first, last),
      Font: same ? selected[0] : { Name: "mixed", Size: 9999999, Bold: 9999999 }
    };
  }
};
const mixedSegments = helpers.extractHomogeneousFormatSegments(mixedRange, { maxSegments: 16 });
assert.strictEqual(mixedSegments.dataStatus, "verified");
assert.deepStrictEqual(mixedSegments.segments.map((item) => [item.start, item.end]), [[0, 2], [2, 3], [3, 4]]);
assert.strictEqual(mixedSegments.segments[0].format.fontName, "宋体");
assert.strictEqual(mixedSegments.segments[2].format.fontSize, 14);

const insufficientSegments = helpers.extractHomogeneousFormatSegments(mixedRange, { maxSegments: 2 });
assert.strictEqual(insufficientSegments.dataStatus, "insufficient");
assert.strictEqual(insufficientSegments.insufficientReason, "format_fragmentation_limit");
assert.strictEqual(helpers.extractHomogeneousFormatSegments({ Text: "无格式属性" }).dataStatus, "insufficient");

const coveredBody = helpers.buildDeterministicFormatReviewBody({
  selectionMode: "document",
  content: {
    paragraphs: [{
      index: 1,
      text: "混合格式正文",
      formatSegments: mixedSegments.segments,
      formatDataStatus: mixedSegments.dataStatus
    }],
    documentStructure: {}
  }
}, {
  coverage: {
    headerFooter: {
      header: { status: "unavailable", failureCount: 1 },
      footer: { status: "read", characterCount: 8 }
    },
    unsupportedObjects: [{ type: "textBox", count: 2, status: "not_supported" }]
  }
});
assert.strictEqual(coveredBody.coverage.formatSegmentCount, 3);
assert.strictEqual(coveredBody.coverage.unsupportedObjectCount, 2);
assert.strictEqual(coveredBody.coverage.headerFooter.header.status, "unavailable");
