const assert = require("assert");
const fs = require("fs");

const root = "formal-plugin-kit/wps-ai-assistant_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");

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
