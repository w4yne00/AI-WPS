const assert = require("assert");
const fs = require("fs");

const wordRoot = "formal-plugin-kit/wps-ai-assistant_1.0.0";
const excelRoot = "formal-plugin-kit/wps-ai-assistant-et_1.0.0";
const pptRoot = "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0";
const wordHtml = fs.readFileSync(`${wordRoot}/taskpane.html`, "utf8");
const wordCss = fs.readFileSync(`${wordRoot}/taskpane.css`, "utf8");
const wordJs = fs.readFileSync(`${wordRoot}/taskpane.js`, "utf8");
const excelHtml = fs.readFileSync(`${excelRoot}/taskpane.html`, "utf8");
const pptHtml = fs.readFileSync(`${pptRoot}/taskpane.html`, "utf8");

function functionSource(name) {
  const start = wordJs.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = wordJs.indexOf("\n  function ", start + 1);
  return wordJs.slice(start, end < 0 ? wordJs.length : end);
}

assert.ok(wordHtml.includes('id="knowledge-usage-strip"'));
assert.ok(wordHtml.includes('id="knowledge-usage-summary"'));
assert.ok(wordHtml.includes('id="knowledge-usage-details"'));
assert.ok(wordHtml.includes('id="knowledge-usage-list"'));
assert.ok(wordHtml.indexOf('id="knowledge-usage-strip"') < wordHtml.indexOf('id="result-output"'));
assert.ok(/<section[^>]*id="knowledge-usage-strip"[^>]*hidden/.test(wordHtml));
assert.ok(!excelHtml.includes('id="knowledge-usage-strip"'));
assert.ok(!pptHtml.includes('id="knowledge-usage-strip"'));

assert.ok(wordCss.includes(".knowledge-usage-strip"));
assert.ok(wordCss.includes(".knowledge-usage-summary"));

const renderSource = functionSource("renderKnowledgeUsage");
assert.ok(renderSource.includes("helpers.normalizeKnowledgeUsage"));
assert.ok(renderSource.includes("helpers.knowledgeUsageSummary"));
assert.ok(renderSource.includes("helpers.knowledgeUsageDetails"));
assert.ok(renderSource.includes("textContent"));
assert.ok(renderSource.includes("document.createElement(\"li\")"));
assert.ok(!renderSource.includes("innerHTML"));

const clearSource = functionSource("clearKnowledgeUsage");
assert.ok(clearSource.includes("hidden = true"));
assert.ok(clearSource.includes("textContent = \"\""));

const smartResultSource = functionSource("setSmartWriteResult");
assert.ok(smartResultSource.includes("renderKnowledgeUsage"));
assert.ok(wordJs.includes('setSmartWriteResult(body.data, "word.smart_write")'));
assert.ok(wordJs.includes('setSmartWriteResult(body.data, "word.smart_imitation")'));

const reviewResultSource = functionSource("renderDocumentReviewResult");
assert.ok(reviewResultSource.includes('renderKnowledgeUsage(data && data.knowledgeUsage, "word.document_review")'));

const smartResetSource = functionSource("resetSmartWritePreviewState");
const reviewResetSource = functionSource("resetDocumentReviewState");
assert.ok(smartResetSource.includes("clearKnowledgeUsage()"));
assert.ok(reviewResetSource.includes("clearKnowledgeUsage()"));

[
  "state.rewriteResult = setSmartWriteResult",
  "state.pendingApplyAction = \"rewrite\"",
  "applyRewrite()",
  "buildDocumentReviewRecord",
  "documentReviewIssueStatus"
].forEach((token) => assert.ok(wordJs.includes(token), token));

console.log("enterprise knowledge Word result strip tests passed");
