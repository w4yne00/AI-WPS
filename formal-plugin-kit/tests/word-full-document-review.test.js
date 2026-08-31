const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = process.env.AI_WPS_WORD_PLUGIN_DIR || path.resolve(__dirname, "../wps-ai-assistant_1.0.0");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

// The feature entry exists but remains hidden until /config explicitly enables it.
assert.ok(html.includes('id="btn-run-full-document-review"'));
assert.ok(html.includes('id="full-document-review-entry"'));
assert.ok(html.includes('id="full-document-review-entry"') &&
  html.slice(html.indexOf('id="full-document-review-entry"'), html.indexOf('id="full-document-review-entry"') + 160).includes("hidden"));
assert.ok(js.includes("fullDocumentReviewEnabled: false"));
const applyConfig = functionSource("applyProviderConfig");
assert.ok(applyConfig.includes("configData.features"));
assert.ok(applyConfig.includes("fullDocumentReviewEnabled"));
assert.ok(applyConfig.includes("renderFullDocumentReviewEntry"));
const renderEntry = functionSource("renderFullDocumentReviewEntry");
assert.ok(renderEntry.includes("state.fullDocumentReviewEnabled"));
assert.ok(renderEntry.includes("fullDocumentReviewReady"));

// Model settings display limited-review and full-review readiness separately.
const manager = functionSource("renderWorkflowProfileManager");
assert.ok(manager.includes("limitedReviewReady"));
assert.ok(manager.includes("fullDocumentReviewReadiness"));
assert.ok(manager.includes("限量审查"));
assert.ok(manager.includes("全篇审查"));

// Snapshot preparation is deterministic, capped at 20,000 review characters,
// and exposes only ordinary body paragraph facts.
assert.strictEqual(
  helpers.sha256Text("系统应尽快完成联调。"),
  "ada346dbaccf1b2fe4655e5503522fe31e2911acecf39aaaa4e59a31b1cabfa2"
);
const snapshot = helpers.buildFullDocumentReviewBody([
  { text: "第一段。" },
  { text: "第二段。" }
], 20000);
assert.strictEqual(snapshot.reviewCharacterCount, 8);
assert.strictEqual(snapshot.blocks.length, 2);
assert.strictEqual(snapshot.blocks[0].blockId, "paragraph-1");
assert.strictEqual(snapshot.blocks[0].blockType, "paragraph");
assert.strictEqual(snapshot.sourceText, "第一段。\n第二段。");
assert.throws(
  () => helpers.buildFullDocumentReviewBody([{ text: "文".repeat(20001) }], 20000),
  /20,000/
);

const structured = helpers.buildFullDocumentReviewBody({
  paragraphs: [
    { index: 1, text: "第一标题", outlineLevel: 1 },
    { index: 2, text: "第一段正文", listLabel: "1." }
  ],
  tables: [{
    tableId: "table-1",
    tableIndex: 1,
    rows: [{
      rowIndex: 1,
      cells: [{
        cellId: "cell-1",
        rowIndex: 1,
        columnIndex: 1,
        rowSpan: 1,
        columnSpan: 2,
        mergeId: "merge-1",
        text: "表头",
        nestedTableIds: ["table-1-1"]
      }]
    }],
    nestedTables: [{
      tableId: "table-1-1",
      parentCellId: "cell-1",
      rows: [{
        rowIndex: 1,
        cells: [{
          cellId: "cell-1-1",
          rowIndex: 1,
          columnIndex: 1,
          text: "嵌套"
        }]
      }]
    }]
  }]
}, 20000);
assert.strictEqual(structured.blocks[0].blockType, "heading");
assert.strictEqual(structured.blocks[1].blockType, "listItem");
assert.strictEqual(structured.tableCount, 2);
assert.strictEqual(structured.cellCount, 2);
assert.deepStrictEqual(structured.capacity, {
  tier: "single_chunk",
  requiresConfirmation: false,
  initialChunkCount: 1,
  estimatedCallCount: 1,
  callLimit: 8
});
assert.deepStrictEqual(helpers.getFullDocumentReviewCapacity(60001), {
  tier: "large",
  requiresConfirmation: true,
  initialChunkCount: 4,
  estimatedCallCount: 5,
  callLimit: 24
});
assert.throws(() => helpers.getFullDocumentReviewCapacity(120001), /120,000/);
const batches = helpers.buildFullDocumentReviewBatches({ blocks: [
  { blockId: "paragraph-1", blockType: "paragraph", text: "甲".repeat(4) },
  { blockId: "paragraph-2", blockType: "paragraph", text: "乙".repeat(4) },
  { blockId: "paragraph-3", blockType: "paragraph", text: "丙".repeat(4) }
] }, 5);
assert.strictEqual(batches.length, 3);
assert.strictEqual(batches[1].sequence, 1);
assert.strictEqual(batches[2].range.end, "paragraph-3");

const extract = functionSource("extractFullDocumentReviewBody");
assert.ok(extract.includes("collectParagraphs"));
assert.ok(extract.includes("collectFullDocumentReviewTables"));
assert.ok(extract.includes("readFullDocumentReviewEditSignal"));
assert.ok(extract.includes("buildFullDocumentReviewBody"));
assert.ok(!extract.includes("InsertAfter"));
assert.ok(!extract.includes("Text ="));
assert.ok(!extract.includes("Delete"));

const collectedBody = helpers.collectParagraphs({
  Paragraphs: [
    { Text: "普通正文。", Range: { Tables: { Count: 0 } } },
    { Text: "表格单元格。", Range: { Tables: { Count: 1 } } }
  ]
}, { avoidFallbackTextRead: true, excludeTableParagraphs: true });
assert.strictEqual(collectedBody.length, 1);
assert.strictEqual(collectedBody[0].text, "普通正文。");

const tables = helpers.collectFullDocumentReviewTables({
  Tables: [{
    Id: "table-1",
    Rows: [{
      Index: 1,
      Cells: [{
        Id: "cell-1",
        RowIndex: 1,
        ColumnIndex: 1,
        RowSpan: 1,
        ColumnSpan: 2,
        MergeId: "merge-1",
        Text: "表格正文"
      }]
    }]
  }]
});
assert.strictEqual(tables.length, 1);
assert.strictEqual(tables[0].rows[0].cells[0].text, "表格正文");

// The WPS path uses the independent session/job/report protocol and performs
// a second extraction before commit. It never invokes any Word writeback path.
const run = functionSource("runFullDocumentReview");
[
  "/word/document-review/full/snapshots",
  "/commit",
  "/word/document-review/full/jobs"
].forEach((token) => assert.ok(run.includes(token), token));
assert.ok(functionSource("uploadFullDocumentReviewBatches").includes("/batches/"));
assert.ok(run.includes("extractFullDocumentReviewBody"));
assert.ok(run.includes("verificationSha256"));
assert.ok(run.includes("firstPass.contentSha256 !== secondPass.contentSha256"));
assert.ok(run.includes('"tables"'));
assert.ok(!run.includes("applyRewrite"));
assert.ok(!run.includes("InsertAfter"));
assert.ok(!run.includes("Text ="));

const poll = functionSource("pollFullDocumentReviewJob");
assert.ok(poll.includes("/word/document-review/full/jobs/"));
assert.ok(poll.includes("/report"));
assert.ok(poll.includes("fullDocumentReviewPollErrorCount"));
assert.ok(poll.includes("setTimeout"));
assert.ok(poll.includes("isFullDocumentReviewPermanentPollError"));
assert.ok(poll.includes("原全篇审查任务不存在或已过期，请重新发起"));
assert.ok(poll.includes('job.status === "cancelled" ? "全篇审查已取消。"'));
assert.ok(functionSource("isFullDocumentReviewPermanentPollError").includes(
  'error.adapterCode === "FULL_DOCUMENT_REVIEW_JOB_NOT_FOUND"'
));
assert.ok(functionSource("isFullDocumentReviewPermanentPollError").includes(
  "status >= 400 && status < 500"
));
assert.ok(functionSource("resumeFullDocumentReviewActiveJob").includes(
  "loadFullDocumentReviewActiveJob"
));
const renderReport = functionSource("renderFullDocumentReviewReport");
assert.ok(renderReport.includes("snapshot"));
assert.ok(renderReport.includes("coverage"));
assert.ok(renderReport.includes("excludedRegions"));
assert.ok(renderReport.includes("问题枚举"));
assert.ok(renderReport.includes("enumerationStatus"));
assert.ok(renderReport.includes("不承诺检出全部问题"));
assert.ok(!renderReport.includes("applyRewrite"));
const fullIssuePage = functionSource("renderFullDocumentReviewIssuePage");
assert.ok(fullIssuePage.includes("globalFindings"));
assert.ok(fullIssuePage.includes("定位原文"));
assert.ok(fullIssuePage.includes("复制建议"));
assert.ok(fullIssuePage.includes("复制原文"));
assert.ok(html.includes('id="full-review-filter-severity"'));
assert.ok(html.includes('id="full-review-filter-category"'));
assert.ok(html.includes('id="full-review-filter-location"'));
assert.ok(html.includes('id="full-review-filter-status"'));
assert.ok(functionSource("loadFullDocumentReviewIssuePage").includes("severity"));
assert.ok(functionSource("loadFullDocumentReviewIssuePage").includes("category"));
assert.ok(functionSource("loadFullDocumentReviewIssuePage").includes("location"));
assert.ok(functionSource("loadFullDocumentReviewIssuePage").includes("status"));
assert.ok(functionSource("changeFullDocumentReviewIssueFilter").includes("fullDocumentReviewIssueCursorHistory"));
assert.ok(fullIssuePage.includes("duplicateGroupSize"));
assert.ok(functionSource("locateFullDocumentReviewIssue").includes("唯一匹配"));
assert.ok(functionSource("locateFullDocumentReviewIssue").includes("tableIndex"));
assert.ok(functionSource("locateFullDocumentReviewIssue").includes("tablePath"));
assert.ok(functionSource("locateFullDocumentReviewIssue").includes("anchorVerification"));
assert.ok(functionSource("locateFullDocumentReviewIssue").includes("预期附近"));
assert.ok(functionSource("markFullDocumentReviewAnchorVerification").includes("anchorVerification"));
assert.ok(fullIssuePage.includes("issue.issueId"));
assert.ok(fullIssuePage.includes("锚点未验证"));

assert.ok(functionSource("bindEvents").includes(
  'byId("btn-run-full-document-review").addEventListener("click", runFullDocumentReview)'
));

console.log("word full document review contract tests passed");
