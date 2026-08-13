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
