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
const helpers = require(`../wps-ai-assistant_1.0.0/taskpane-helpers.js`);

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

[
  "enterprise-knowledge-summary-card",
  "knowledge-scope-view",
  "knowledge-list-view",
  "knowledge-editor-view",
  "btn-knowledge-scope-back",
  "btn-knowledge-list-back",
  "btn-knowledge-editor-back",
  "knowledge-type-switch",
  "knowledge-search-input",
  "btn-knowledge-add",
  "knowledge-overflow-menu",
  "knowledge-editor-advanced",
  "btn-knowledge-delete"
].forEach((id) => assert.ok(wordHtml.includes(`id="${id}"`), id));

[
  "enterprise-knowledge-summary-card",
  "knowledge-scope-view",
  "knowledge-list-view",
  "knowledge-editor-view"
].forEach((id) => {
  assert.ok(!excelHtml.includes(`id="${id}"`), `Excel must not include ${id}`);
  assert.ok(!pptHtml.includes(`id="${id}"`), `PPT must not include ${id}`);
});

assert.strictEqual((wordHtml.match(/data-knowledge-scope=/g) || []).length, 4);
assert.ok(wordHtml.includes('data-knowledge-type="term"'));
assert.ok(wordHtml.includes('data-knowledge-type="style"'));
assert.ok(wordHtml.includes('title="新增知识条目"'));
assert.ok(wordHtml.includes("<details id=\"knowledge-editor-advanced\""));

assert.deepStrictEqual(
  helpers.validateKnowledgeDraft({ type: "term", scope: "word.smart_write" }),
  { ok: false, field: "scope", message: "企业术语首版仅支持全局范围。" }
);
assert.deepStrictEqual(
  helpers.validateKnowledgeDraft({ type: "style", scope: "global", name: "", ruleText: "" }),
  { ok: false, field: "name", message: "请输入规则名称。" }
);
assert.deepStrictEqual(
  helpers.validateKnowledgeDraft({ type: "term", scope: "global", preferredText: "标准名称" }),
  { ok: true, field: "", message: "" }
);

assert.ok(wordJs.includes('knowledgeView: "home"'));
assert.ok(wordJs.includes('knowledgeScope: "global"'));
assert.ok(wordJs.includes('knowledgeType: "term"'));
assert.ok(wordJs.includes("knowledgeLoadSequence: 0"));
assert.ok(wordJs.includes("knowledgeMutationBusy: false"));
assert.ok(wordJs.includes("knowledgeEditorDirty: false"));

const summarySource = functionSource("loadKnowledgeSummary");
assert.ok(summarySource.includes('request("/enterprise-knowledge/summary")'));
assert.ok(summarySource.includes("knowledgeLoadSequence"));
assert.ok(summarySource.includes("httpStatus === 404"));

const listSource = functionSource("loadKnowledgeItems");
assert.ok(listSource.includes('request("/enterprise-knowledge/items?scope="'));
assert.ok(listSource.includes("knowledgeLoadSequence"));

const listRenderSource = functionSource("renderKnowledgeList");
assert.ok(listRenderSource.includes("textContent"));
assert.ok(!listRenderSource.includes("innerHTML"));

const editorSource = functionSource("renderKnowledgeEditor");
assert.ok(editorSource.includes("textContent"));
assert.ok(editorSource.includes("knowledge-editor-advanced"));

const discardSource = functionSource("confirmKnowledgeEditorDiscard");
assert.ok(discardSource.includes("knowledgeEditorDirty"));
assert.ok(discardSource.includes("window.confirm"));

const saveSource = functionSource("saveKnowledgeItem");
assert.ok(saveSource.includes("knowledgeMutationBusy"));
assert.ok(saveSource.includes('method: "PATCH"'));

const deleteKnowledgeSource = functionSource("deleteKnowledgeItem");
assert.ok(deleteKnowledgeSource.includes("window.confirm"));
assert.ok(deleteKnowledgeSource.includes('method: "DELETE"'));

console.log("enterprise knowledge Word result and manager tests passed");
