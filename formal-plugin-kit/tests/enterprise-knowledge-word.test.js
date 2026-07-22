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
  "btn-knowledge-delete",
  "knowledge-import-view",
  "knowledge-import-file",
  "btn-knowledge-download-csv-template",
  "btn-knowledge-download-xlsx-template",
  "btn-knowledge-export-scope",
  "btn-knowledge-download-backup"
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
assert.deepStrictEqual(
  helpers.validateKnowledgeImportFile({ name: "knowledge.txt", size: 10 }),
  { ok: false, message: "请选择 CSV 或 XLSX 文件。" }
);
assert.deepStrictEqual(
  helpers.validateKnowledgeImportFile({ name: "knowledge.csv", size: 5 * 1024 * 1024 + 1 }),
  { ok: false, message: "导入文件不能超过 5 MB。" }
);
assert.deepStrictEqual(
  helpers.validateKnowledgeImportFile({ name: "knowledge.xlsx", size: 120 }),
  { ok: true, message: "" }
);
assert.deepStrictEqual(
  helpers.buildKnowledgeImportRequest(
    { name: "knowledge.csv", type: "text/csv", size: 3 },
    "YWJj"
  ),
  { fileName: "knowledge.csv", mimeType: "text/csv", sizeBytes: 3, contentBase64: "YWJj" }
);
assert.strictEqual(helpers.normalizeKnowledgeConflictDecision("skip"), "skip");
assert.strictEqual(helpers.normalizeKnowledgeConflictDecision("overwrite"), "keep_existing");
assert.strictEqual(helpers.knowledgeImportRowLabel({ row: 6, message: "第 6 行：字段无效。" }), "第 6 行：字段无效。");
assert.strictEqual(helpers.isKnowledgePreviewExpired({ httpStatus: 410 }), true);
assert.strictEqual(helpers.isKnowledgePreviewExpired({ adapterCode: "IMPORT_PREVIEW_NOT_FOUND" }), true);
assert.strictEqual(helpers.knowledgeConflictField({ adapterCode: "TERM_TEXT_CONFLICT" }), "preferredText");
assert.strictEqual(helpers.knowledgeConflictField({ adapterCode: "STYLE_NAME_CONFLICT" }), "name");
assert.strictEqual(helpers.knowledgeConflictField({ adapterCode: "STORAGE_UNAVAILABLE" }), "");
assert.strictEqual(helpers.knowledgeConflictField({ httpStatus: 503 }), "");
assert.strictEqual(helpers.nextKnowledgeTabIndex(0, "ArrowRight", 2), 1);
assert.strictEqual(helpers.nextKnowledgeTabIndex(0, "ArrowLeft", 2), 1);
assert.strictEqual(helpers.nextKnowledgeTabIndex(1, "Home", 2), 0);
assert.strictEqual(helpers.nextKnowledgeTabIndex(0, "End", 2), 1);

const updatedAt = "2026-07-16T00:00:00Z";
const expectedUpdatedAt = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false
}).format(new Date(updatedAt));
assert.strictEqual(helpers.formatKnowledgeUpdatedAt(updatedAt), `最近更新：${expectedUpdatedAt}`);
assert.strictEqual(helpers.formatKnowledgeUpdatedAt("not-a-date"), "最近更新：not-a-date");

const previewModel = helpers.normalizeKnowledgeImportPreview({
  previewToken: "token",
  newCount: 2,
  updateCount: 1,
  conflictCount: 1,
  errorCount: 1,
  errors: [{ row: 6, message: "第 6 行：字段无效。" }],
  conflicts: [{ rowNumber: 4, message: "第 4 行：冲突。", defaultDecision: "keep_existing" }]
});
assert.strictEqual(previewModel.previewToken, "token");
assert.deepStrictEqual(previewModel.stats, { newCount: 2, updateCount: 1, conflictCount: 1, errorCount: 1 });
assert.strictEqual(previewModel.conflicts[0].decision, "keep_existing");

const manyErrors = Array.from({ length: 105 }, (_, index) => ({
  row: index + 2,
  message: `第 ${index + 2} 行：字段无效。`
}));
const manyConflicts = Array.from({ length: 103 }, (_, index) => ({
  rowNumber: index + 2,
  message: `第 ${index + 2} 行：术语冲突。`,
  defaultDecision: index === 0 ? "overwrite" : "skip"
}));
const limitedPreview = helpers.normalizeKnowledgeImportPreview({
  previewToken: "large-token",
  newCount: 3,
  updateCount: 4,
  conflictCount: 103,
  errorCount: 105,
  errors: manyErrors,
  conflicts: manyConflicts
});
assert.strictEqual(limitedPreview.errors.length, 100);
assert.strictEqual(limitedPreview.conflicts.length, 100);
assert.strictEqual(limitedPreview.stats.errorCount, 105);
assert.strictEqual(limitedPreview.stats.conflictCount, 103);
assert.strictEqual(limitedPreview.conflicts[0].decision, "keep_existing");
assert.strictEqual(limitedPreview.conflicts[1].decision, "keep_existing");
assert.strictEqual(helpers.knowledgeImportCountLabel("校验错误", 105, 100), "校验错误（显示前 100 条，共 105 条）");
assert.strictEqual(helpers.knowledgeImportCountLabel("冲突处理", 2, 2), "冲突处理（共 2 条）");
assert.deepStrictEqual(
  helpers.buildKnowledgeImportApplyRequest(limitedPreview),
  {
    previewToken: "large-token",
    acceptedConflictRows: limitedPreview.conflicts.map((item) => ({
      rowNumber: item.rowNumber,
      decision: item.decision
    }))
  }
);

assert.ok(wordJs.includes('knowledgeView: "home"'));
assert.ok(wordJs.includes("var KNOWLEDGE_MANAGEMENT_REQUEST_TIMEOUT_MS = 15000;"));
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
assert.ok(saveSource.includes('options.method = "PATCH"'));
assert.ok(saveSource.includes("KNOWLEDGE_MANAGEMENT_REQUEST_TIMEOUT_MS"));
assert.ok(saveSource.includes("helpers.knowledgeConflictField"));
assert.ok(saveSource.includes("setKnowledgeMutationBusy(false)"));
const saveFailureSource = saveSource.slice(saveSource.indexOf(".catch"));
assert.ok(!saveFailureSource.includes("clearKnowledgeEditorState"));

const deleteKnowledgeSource = functionSource("deleteKnowledgeItem");
assert.ok(deleteKnowledgeSource.includes("window.confirm"));
assert.ok(deleteKnowledgeSource.includes('method: "DELETE"'));
assert.ok(deleteKnowledgeSource.includes("KNOWLEDGE_MANAGEMENT_REQUEST_TIMEOUT_MS"));
assert.ok(deleteKnowledgeSource.includes("setKnowledgeMutationBusy(false)"));
const deleteFailureSource = deleteKnowledgeSource.slice(deleteKnowledgeSource.indexOf(".catch"));
assert.ok(!deleteFailureSource.includes("clearKnowledgeEditorState"));

const updatedAtSource = functionSource("formatKnowledgeUpdatedAt");
assert.ok(updatedAtSource.includes("helpers.formatKnowledgeUpdatedAt"));
assert.ok(!updatedAtSource.includes('replace("T"'));

const viewSource = functionSource("setKnowledgeView");
assert.ok(viewSource.includes("focusKnowledgeView"));
const focusSource = functionSource("focusKnowledgeView");
assert.ok(focusSource.includes("btn-open-knowledge-manager"));
assert.ok(focusSource.includes("knowledge-scope-title"));
assert.ok(focusSource.includes("knowledge-list-title"));
assert.ok(focusSource.includes("knowledge-editor-title"));
assert.ok(focusSource.includes("knowledge-import-title"));

const typeRenderSource = functionSource("renderKnowledgeTypeSwitch");
assert.ok(typeRenderSource.includes("tabIndex"));
const typeKeyboardSource = functionSource("handleKnowledgeTypeKeydown");
["ArrowLeft", "ArrowRight", "Home", "End", "preventDefault", "focus"].forEach((token) => {
  assert.ok(typeKeyboardSource.includes(token), `missing tab keyboard behavior ${token}`);
});

const previewImportSource = functionSource("previewKnowledgeImport");
assert.ok(previewImportSource.includes("FileReader"));
assert.ok(previewImportSource.includes("readAsArrayBuffer"));
assert.ok(previewImportSource.includes('request("/enterprise-knowledge/imports/preview"'));
assert.ok(!previewImportSource.includes("console"));

const applyImportSource = functionSource("applyKnowledgeImport");
assert.ok(applyImportSource.includes("acceptedConflictRows"));
assert.ok(applyImportSource.includes("isKnowledgePreviewExpired"));
assert.ok(applyImportSource.includes("导入预览已过期，请重新选择文件。"));

const downloadSource = functionSource("downloadKnowledgeFile");
assert.ok(downloadSource.includes("URL.createObjectURL"));
assert.ok(downloadSource.includes("URL.revokeObjectURL"));
assert.ok(downloadSource.includes("cleanup"));

const renderImportSource = functionSource("renderKnowledgeImportPreview");
assert.ok(renderImportSource.includes("knowledgeImportCountLabel"));
assert.ok(renderImportSource.includes("textContent"));
assert.ok(!renderImportSource.includes("innerHTML"));
const renderImportStepSource = functionSource("renderKnowledgeImportStep");
assert.ok(renderImportStepSource.includes('aria-current'));

const bindSource = functionSource("bindEvents");
[
  "btn-knowledge-import-entry",
  "knowledge-overflow-menu",
  "btn-knowledge-import-back",
  "btn-preview-knowledge-import",
  "knowledge-import-conflict-list",
  "btn-apply-knowledge-import",
  "btn-knowledge-download-csv-template",
  "btn-knowledge-download-xlsx-template",
  "btn-knowledge-export-scope",
  "btn-knowledge-download-backup"
].forEach((id) => assert.ok(bindSource.includes(`byId(\"${id}\")`), `missing event binding for ${id}`));
assert.ok(bindSource.includes('byId("knowledge-type-switch").addEventListener("keydown", handleKnowledgeTypeKeydown)'));

[
  "knowledge-scope-title",
  "knowledge-list-title",
  "knowledge-editor-title",
  "knowledge-import-title"
].forEach((id) => {
  assert.ok(wordHtml.includes(`id="${id}"`), id);
  assert.ok(new RegExp(`id="${id}"[^>]*tabindex="-1"`).test(wordHtml), `${id} must accept programmatic focus`);
});

[
  "选择文件",
  "校验",
  "处理冲突",
  "应用"
].reduce((previousIndex, label) => {
  const index = wordHtml.indexOf(`>${label}</li>`);
  assert.ok(index > previousIndex, `import step order: ${label}`);
  return index;
}, -1);

[
  "/enterprise-knowledge/import-template.csv",
  "/enterprise-knowledge/import-template.xlsx",
  "/enterprise-knowledge/export.csv?scope=",
  "/enterprise-knowledge/backup"
].forEach((path) => assert.ok(wordJs.includes(path), `missing knowledge download path ${path}`));

console.log("enterprise knowledge Word result and manager tests passed");
