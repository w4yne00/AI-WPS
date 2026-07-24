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

assert.ok(wordHtml.includes('id="writing-policy-usage-strip"'));
assert.ok(wordHtml.includes('id="writing-policy-usage-summary"'));
assert.ok(wordHtml.includes('id="writing-policy-usage-details"'));
assert.ok(wordHtml.includes('id="writing-policy-usage-list"'));
assert.ok(wordHtml.indexOf('id="writing-policy-usage-strip"') < wordHtml.indexOf('id="result-output"'));
assert.ok(/<section[^>]*id="writing-policy-usage-strip"[^>]*hidden/.test(wordHtml));
assert.ok(!excelHtml.includes('id="writing-policy-usage-strip"'));
assert.ok(!pptHtml.includes('id="writing-policy-usage-strip"'));
assert.ok(wordHtml.includes('id="writing-policy-scene-block"'));
assert.ok(wordHtml.includes('id="writing-policy-scene"'));
[
  "auto",
  "yangqi",
  "cybersecurity",
  "official",
  "disabled"
].forEach((value) => assert.ok(wordHtml.includes(`value="${value}"`), value));
assert.ok(!excelHtml.includes('id="writing-policy-scene"'));
assert.ok(!pptHtml.includes('id="writing-policy-scene"'));
assert.ok(wordHtml.includes('id="writing-policy-audit-summary"'));
assert.ok(wordHtml.includes('id="writing-policy-audit-details"'));
assert.ok(wordHtml.includes('id="writing-policy-needs-review"'));
assert.ok(wordHtml.includes('id="writing-policy-expression-suggestions"'));

assert.ok(wordCss.includes(".writing-policy-usage-strip"));
assert.ok(wordCss.includes(".writing-policy-usage-summary"));

const renderSource = functionSource("renderWritingPolicyUsage");
assert.ok(renderSource.includes("helpers.normalizeWritingPolicyUsage"));
assert.ok(renderSource.includes("helpers.writingPolicyUsageSummary"));
assert.ok(renderSource.includes("helpers.writingPolicyUsageDetails"));
assert.ok(renderSource.includes("textContent"));
assert.ok(renderSource.includes("document.createElement(\"li\")"));
assert.ok(!renderSource.includes("innerHTML"));

const auditRenderSource = functionSource("renderWritingPolicyAudit");
assert.ok(auditRenderSource.includes("helpers.normalizeWritingPolicyAudit"));
assert.ok(auditRenderSource.includes("需要核对"));
assert.ok(auditRenderSource.includes("表达建议"));
assert.ok(auditRenderSource.includes("textContent"));
assert.ok(!auditRenderSource.includes("innerHTML"));

const smartWriteActionSource = functionSource("runSmartWriteAction");
assert.ok(smartWriteActionSource.includes("getWritingPolicyScene"));
assert.ok(!smartWriteActionSource.includes('writingPolicyScene = "auto"'));

const modeVisibilitySource = functionSource("switchMode");
assert.ok(modeVisibilitySource.includes('"writing-policy-scene-block"'));
assert.ok(modeVisibilitySource.includes('state.currentMode !== "smartWrite"'));

const clearSource = functionSource("clearWritingPolicyUsage");
assert.ok(clearSource.includes("hidden = true"));
assert.ok(clearSource.includes("textContent = \"\""));

const smartResultSource = functionSource("setSmartWriteResult");
assert.ok(smartResultSource.includes("renderWritingPolicyUsage"));
assert.ok(wordJs.includes('setSmartWriteResult(body.data, "word.smart_write")'));
assert.ok(wordJs.includes('setSmartWriteResult(body.data, "word.smart_imitation")'));

const reviewResultSource = functionSource("renderDocumentReviewResult");
assert.ok(reviewResultSource.includes('renderWritingPolicyUsage(data && data.writingPolicyUsage, "word.document_review")'));

const smartResetSource = functionSource("resetSmartWritePreviewState");
const reviewResetSource = functionSource("resetDocumentReviewState");
assert.ok(smartResetSource.includes("clearWritingPolicyUsage()"));
assert.ok(reviewResetSource.includes("clearWritingPolicyUsage()"));

[
  "state.rewriteResult = setSmartWriteResult",
  "state.pendingApplyAction = \"rewrite\"",
  "applyRewrite()",
  "buildDocumentReviewRecord",
  "documentReviewIssueStatus"
].forEach((token) => assert.ok(wordJs.includes(token), token));

[
  "writing-policies-summary-card",
  "writing-policy-scope-view",
  "writing-policy-preset-view",
  "writing-policy-preset-title",
  "writing-policy-preset-pack-meta",
  "writing-policy-preset-item-list",
  "btn-writing-policy-preset-back",
  "btn-writing-policy-open-organization",
  "writing-policy-list-view",
  "writing-policy-editor-view",
  "btn-writing-policy-scope-back",
  "btn-writing-policy-list-back",
  "btn-writing-policy-editor-back",
  "writing-policy-type-switch",
  "writing-policy-search-input",
  "btn-writing-policy-add",
  "writing-policy-overflow-menu",
  "writing-policy-editor-advanced",
  "btn-writing-policy-delete",
  "writing-policy-import-view",
  "writing-policy-import-file",
  "btn-writing-policy-download-csv-template",
  "btn-writing-policy-download-xlsx-template",
  "btn-writing-policy-export-scope",
  "btn-writing-policy-download-backup"
].forEach((id) => assert.ok(wordHtml.includes(`id="${id}"`), id));

[
  "writing-policies-summary-card",
  "writing-policy-scope-view",
  "writing-policy-list-view",
  "writing-policy-editor-view"
].forEach((id) => {
  assert.ok(!excelHtml.includes(`id="${id}"`), `Excel must not include ${id}`);
  assert.ok(!pptHtml.includes(`id="${id}"`), `PPT must not include ${id}`);
});

assert.strictEqual((wordHtml.match(/data-writing-policy-scope=/g) || []).length, 4);
assert.ok(wordHtml.includes('data-writing-policy-type="term"'));
assert.ok(wordHtml.includes('data-writing-policy-type="style"'));
assert.ok(wordHtml.includes('title="新增规范条目"'));
assert.ok(wordHtml.includes("<details id=\"writing-policy-editor-advanced\""));

assert.deepStrictEqual(
  helpers.validateWritingPolicyDraft({ type: "term", scope: "word.smart_write" }),
  { ok: false, field: "scope", message: "企业术语首版仅支持全局范围。" }
);
assert.deepStrictEqual(
  helpers.validateWritingPolicyDraft({ type: "style", scope: "global", name: "", ruleText: "" }),
  { ok: false, field: "name", message: "请输入规则名称。" }
);
assert.deepStrictEqual(
  helpers.validateWritingPolicyDraft({ type: "term", scope: "global", preferredText: "标准名称" }),
  { ok: true, field: "", message: "" }
);
assert.deepStrictEqual(
  helpers.validateWritingPolicyImportFile({ name: "writingPolicy.txt", size: 10 }),
  { ok: false, message: "请选择 CSV 或 XLSX 文件。" }
);
assert.deepStrictEqual(
  helpers.validateWritingPolicyImportFile({ name: "writingPolicy.csv", size: 5 * 1024 * 1024 + 1 }),
  { ok: false, message: "导入文件不能超过 5 MB。" }
);
assert.deepStrictEqual(
  helpers.validateWritingPolicyImportFile({ name: "writingPolicy.xlsx", size: 120 }),
  { ok: true, message: "" }
);
assert.deepStrictEqual(
  helpers.buildWritingPolicyImportRequest(
    { name: "writingPolicy.csv", type: "text/csv", size: 3 },
    "YWJj"
  ),
  { fileName: "writingPolicy.csv", mimeType: "text/csv", sizeBytes: 3, contentBase64: "YWJj" }
);
assert.strictEqual(helpers.normalizeWritingPolicyConflictDecision("skip"), "skip");
assert.strictEqual(helpers.normalizeWritingPolicyConflictDecision("overwrite"), "keep_existing");
assert.strictEqual(helpers.writingPolicyImportRowLabel({ row: 6, message: "第 6 行：字段无效。" }), "第 6 行：字段无效。");
assert.strictEqual(helpers.isWritingPolicyPreviewExpired({ httpStatus: 410 }), true);
assert.strictEqual(helpers.isWritingPolicyPreviewExpired({ adapterCode: "IMPORT_PREVIEW_NOT_FOUND" }), true);
assert.strictEqual(helpers.writingPolicyConflictField({ adapterCode: "TERM_TEXT_CONFLICT" }), "preferredText");
assert.strictEqual(helpers.writingPolicyConflictField({ adapterCode: "STYLE_NAME_CONFLICT" }), "name");
assert.strictEqual(helpers.writingPolicyConflictField({ adapterCode: "STORAGE_UNAVAILABLE" }), "");
assert.strictEqual(helpers.writingPolicyConflictField({ httpStatus: 503 }), "");
assert.strictEqual(helpers.nextWritingPolicyTabIndex(0, "ArrowRight", 2), 1);
assert.strictEqual(helpers.nextWritingPolicyTabIndex(0, "ArrowLeft", 2), 1);
assert.strictEqual(helpers.nextWritingPolicyTabIndex(1, "Home", 2), 0);
assert.strictEqual(helpers.nextWritingPolicyTabIndex(0, "End", 2), 1);

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
assert.strictEqual(helpers.formatWritingPolicyUpdatedAt(updatedAt), `最近更新：${expectedUpdatedAt}`);
assert.strictEqual(helpers.formatWritingPolicyUpdatedAt("not-a-date"), "最近更新：not-a-date");

const previewModel = helpers.normalizeWritingPolicyImportPreview({
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
const limitedPreview = helpers.normalizeWritingPolicyImportPreview({
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
assert.strictEqual(helpers.writingPolicyImportCountLabel("校验错误", 105, 100), "校验错误（显示前 100 条，共 105 条）");
assert.strictEqual(helpers.writingPolicyImportCountLabel("冲突处理", 2, 2), "冲突处理（共 2 条）");
assert.deepStrictEqual(
  helpers.buildWritingPolicyImportApplyRequest(limitedPreview),
  {
    previewToken: "large-token",
    acceptedConflictRows: limitedPreview.conflicts.map((item) => ({
      rowNumber: item.rowNumber,
      decision: item.decision
    }))
  }
);

assert.ok(wordJs.includes('writingPolicyView: "home"'));
assert.ok(wordJs.includes("var WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS = 15000;"));
assert.ok(wordJs.includes('writingPolicyScope: "global"'));
assert.ok(wordJs.includes('writingPolicyType: "term"'));
assert.ok(wordJs.includes("writingPolicyLoadSequence: 0"));
assert.ok(wordJs.includes("writingPolicyMutationBusy: false"));
assert.ok(wordJs.includes("writingPolicyEditorDirty: false"));

const summarySource = functionSource("loadWritingPolicySummary");
assert.ok(summarySource.includes('request("/writing-policies/summary")'));
assert.ok(summarySource.includes("writingPolicyLoadSequence"));
assert.ok(summarySource.includes("httpStatus === 404"));

const presetLoadSource = functionSource("loadWritingPolicyPresetPacks");
assert.ok(presetLoadSource.includes('request("/writing-policies/packs")'));
assert.ok(presetLoadSource.includes("yangqi-tech-writing-base"));

const presetItemsSource = functionSource("loadWritingPolicyPresetItems");
assert.ok(presetItemsSource.includes("/writing-policies/items?layer=preset&packId="));

const presetRenderSource = functionSource("renderWritingPolicyPresetItems");
assert.ok(presetRenderSource.includes("textContent"));
assert.ok(presetRenderSource.includes("source.version"));
assert.ok(presetRenderSource.includes("source.commit"));
assert.ok(presetRenderSource.includes("source.license"));
assert.ok(!presetRenderSource.includes("innerHTML"));

const listSource = functionSource("loadWritingPolicyItems");
assert.ok(listSource.includes('request("/writing-policies/items?scope="'));
assert.ok(listSource.includes("writingPolicyLoadSequence"));

const listRenderSource = functionSource("renderWritingPolicyList");
assert.ok(listRenderSource.includes("textContent"));
assert.ok(!listRenderSource.includes("innerHTML"));

const editorSource = functionSource("renderWritingPolicyEditor");
assert.ok(editorSource.includes("textContent"));
assert.ok(editorSource.includes("writing-policy-editor-advanced"));

const discardSource = functionSource("confirmWritingPolicyEditorDiscard");
assert.ok(discardSource.includes("writingPolicyEditorDirty"));
assert.ok(discardSource.includes("window.confirm"));

const saveSource = functionSource("saveWritingPolicyItem");
assert.ok(saveSource.includes("writingPolicyMutationBusy"));
assert.ok(saveSource.includes('options.method = "PATCH"'));
assert.ok(saveSource.includes("WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS"));
assert.ok(saveSource.includes("helpers.writingPolicyConflictField"));
assert.ok(saveSource.includes("setWritingPolicyMutationBusy(false)"));
const saveFailureSource = saveSource.slice(saveSource.indexOf(".catch"));
assert.ok(!saveFailureSource.includes("clearWritingPolicyEditorState"));

const deleteWritingPolicySource = functionSource("deleteWritingPolicyItem");
assert.ok(deleteWritingPolicySource.includes("window.confirm"));
assert.ok(deleteWritingPolicySource.includes('method: "DELETE"'));
assert.ok(deleteWritingPolicySource.includes("WRITING_POLICY_MANAGEMENT_REQUEST_TIMEOUT_MS"));
assert.ok(deleteWritingPolicySource.includes("setWritingPolicyMutationBusy(false)"));
const deleteFailureSource = deleteWritingPolicySource.slice(deleteWritingPolicySource.indexOf(".catch"));
assert.ok(!deleteFailureSource.includes("clearWritingPolicyEditorState"));

const updatedAtSource = functionSource("formatWritingPolicyUpdatedAt");
assert.ok(updatedAtSource.includes("helpers.formatWritingPolicyUpdatedAt"));
assert.ok(!updatedAtSource.includes('replace("T"'));

const viewSource = functionSource("setWritingPolicyView");
assert.ok(viewSource.includes("focusWritingPolicyView"));
const focusSource = functionSource("focusWritingPolicyView");
assert.ok(focusSource.includes("btn-open-writing-policy-manager"));
assert.ok(focusSource.includes("writing-policy-scope-title"));
assert.ok(focusSource.includes("writing-policy-list-title"));
assert.ok(focusSource.includes("writing-policy-editor-title"));
assert.ok(focusSource.includes("writing-policy-import-title"));

const typeRenderSource = functionSource("renderWritingPolicyTypeSwitch");
assert.ok(typeRenderSource.includes("tabIndex"));
const typeKeyboardSource = functionSource("handleWritingPolicyTypeKeydown");
["ArrowLeft", "ArrowRight", "Home", "End", "preventDefault", "focus"].forEach((token) => {
  assert.ok(typeKeyboardSource.includes(token), `missing tab keyboard behavior ${token}`);
});

const previewImportSource = functionSource("previewWritingPolicyImport");
assert.ok(previewImportSource.includes("FileReader"));
assert.ok(previewImportSource.includes("readAsArrayBuffer"));
assert.ok(previewImportSource.includes('request("/writing-policies/imports/preview"'));
assert.ok(!previewImportSource.includes("console"));

const applyImportSource = functionSource("applyWritingPolicyImport");
assert.ok(applyImportSource.includes("acceptedConflictRows"));
assert.ok(applyImportSource.includes("isWritingPolicyPreviewExpired"));
assert.ok(applyImportSource.includes("导入预览已过期，请重新选择文件。"));

const downloadSource = functionSource("downloadWritingPolicyFile");
assert.ok(downloadSource.includes("URL.createObjectURL"));
assert.ok(downloadSource.includes("URL.revokeObjectURL"));
assert.ok(downloadSource.includes("cleanup"));

const renderImportSource = functionSource("renderWritingPolicyImportPreview");
assert.ok(renderImportSource.includes("writingPolicyImportCountLabel"));
assert.ok(renderImportSource.includes("textContent"));
assert.ok(!renderImportSource.includes("innerHTML"));
const renderImportStepSource = functionSource("renderWritingPolicyImportStep");
assert.ok(renderImportStepSource.includes('aria-current'));

const bindSource = functionSource("bindEvents");
[
  "btn-writing-policy-import-entry",
  "writing-policy-overflow-menu",
  "btn-writing-policy-import-back",
  "btn-preview-writing-policy-import",
  "writing-policy-import-conflict-list",
  "btn-apply-writing-policy-import",
  "btn-writing-policy-download-csv-template",
  "btn-writing-policy-download-xlsx-template",
  "btn-writing-policy-export-scope",
  "btn-writing-policy-download-backup"
].forEach((id) => assert.ok(bindSource.includes(`byId(\"${id}\")`), `missing event binding for ${id}`));
assert.ok(bindSource.includes('byId("writing-policy-type-switch").addEventListener("keydown", handleWritingPolicyTypeKeydown)'));

[
  "writing-policy-scope-title",
  "writing-policy-list-title",
  "writing-policy-editor-title",
  "writing-policy-import-title"
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
  "/writing-policies/import-template.csv",
  "/writing-policies/import-template.xlsx",
  "/writing-policies/export.csv?scope=",
  "/writing-policies/backup"
].forEach((path) => assert.ok(wordJs.includes(path), `missing writingPolicy download path ${path}`));

console.log("writing policy Word result and manager tests passed");
