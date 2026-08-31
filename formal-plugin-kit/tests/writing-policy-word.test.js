const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { wordRoot, etRoot: excelRoot, pptRoot } = require("./support/plugin-roots");
const wordHtml = fs.readFileSync(path.join(wordRoot, "taskpane.html"), "utf8");
const wordCss = fs.readFileSync(path.join(wordRoot, "taskpane.css"), "utf8");
const wordJs = fs.readFileSync(path.join(wordRoot, "taskpane.js"), "utf8");
const excelHtml = fs.readFileSync(path.join(excelRoot, "taskpane.html"), "utf8");
const pptHtml = fs.readFileSync(path.join(pptRoot, "taskpane.html"), "utf8");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));

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

const smartImitationActionSource = functionSource("runSmartImitationAction");
assert.ok(smartImitationActionSource.includes("getWritingPolicyScene()"));
assert.ok(!smartImitationActionSource.includes('writingPolicyScene: "auto"'));

const documentReviewActionSource = functionSource("runDocumentReview");
assert.ok(documentReviewActionSource.includes("getWritingPolicyScene()"));
assert.ok(!documentReviewActionSource.includes('writingPolicyScene = "auto"'));

const modeVisibilitySource = functionSource("switchMode");
assert.ok(modeVisibilitySource.includes('"writing-policy-scene-block"'));
assert.ok(modeVisibilitySource.includes('"smartWrite", "smartImitation", "documentReview"'));
assert.ok(modeVisibilitySource.includes("restoreWritingPolicyScene()"));

const saveSceneSource = functionSource("saveWritingPolicyScene");
const restoreSceneSource = functionSource("restoreWritingPolicyScene");
assert.ok(saveSceneSource.includes("getCurrentWorkflowTaskType()"));
assert.ok(restoreSceneSource.includes("getCurrentWorkflowTaskType()"));
assert.ok(!saveSceneSource.includes('writingPolicySceneStorageKey("word.smart_write")'));
assert.ok(!restoreSceneSource.includes('writingPolicySceneStorageKey("word.smart_write")'));

const clearSource = functionSource("clearWritingPolicyUsage");
assert.ok(clearSource.includes("hidden = true"));
assert.ok(clearSource.includes("textContent = \"\""));

const smartResultSource = functionSource("setSmartWriteResult");
assert.ok(smartResultSource.includes("renderWritingPolicyUsage"));
assert.ok(wordJs.includes('startWritingJob(state.latestDocumentPayload, "word.smart_write", "smartWrite")'));
assert.ok(wordJs.includes('startWritingJob(state.latestDocumentPayload, "word.smart_imitation", "smartImitation")'));
assert.ok(wordJs.includes("state.rewriteResult = setSmartWriteResult(result || {}, taskType)"));

const reviewResultSource = functionSource("renderDocumentReviewResult");
assert.ok(reviewResultSource.includes('renderWritingPolicyUsage(data && data.writingPolicyUsage, "word.document_review")'));

const smartResetSource = functionSource("resetSmartWritePreviewState");
const reviewResetSource = functionSource("resetDocumentReviewState");
assert.ok(smartResetSource.includes("clearWritingPolicyUsage()"));
assert.ok(reviewResetSource.includes("clearWritingPolicyUsage()"));
assert.ok(wordJs.includes("WRITING_POLICY_LIST_PAGE_SIZE = 50"));
const loadPresetItemsSource = functionSource("loadWritingPolicyPresetItems");
const loadOrganizationItemsSource = functionSource("loadWritingPolicyItems");
assert.ok(loadPresetItemsSource.includes("limit=\" + WRITING_POLICY_LIST_PAGE_SIZE"));
assert.ok(loadPresetItemsSource.includes("state.writingPolicyPresetItemOffset"));
assert.ok(loadPresetItemsSource.includes(".slice(0, WRITING_POLICY_LIST_PAGE_SIZE)"));
assert.ok(loadOrganizationItemsSource.includes("limit=\" + WRITING_POLICY_LIST_PAGE_SIZE"));
assert.ok(loadOrganizationItemsSource.includes("state.writingPolicyItemOffset"));
assert.ok(loadOrganizationItemsSource.includes(".slice(0, WRITING_POLICY_LIST_PAGE_SIZE)"));
const presetPageSource = functionSource("changeWritingPolicyPresetPage");
const organizationPageSource = functionSource("changeWritingPolicyPage");
assert.ok(loadPresetItemsSource.includes("writingPolicyPresetLoadSequence"));
assert.ok(presetPageSource.includes("WRITING_POLICY_LIST_PAGE_SIZE"));
assert.ok(presetPageSource.includes("loadWritingPolicyPresetItems"));
assert.ok(organizationPageSource.includes("WRITING_POLICY_LIST_PAGE_SIZE"));
assert.ok(organizationPageSource.includes("loadWritingPolicyItems"));
const scheduleSearchSource = functionSource("scheduleWritingPolicySearch");
let scheduledSearchCallback = null;
let scheduledSearchLoads = 0;
let scheduledSearchRenders = 0;
const scheduledSearchStatus = { textContent: "" };
const scheduledSearchState = {
  writingPolicySearch: "",
  writingPolicyItemOffset: 50,
  writingPolicyLoadSequence: 7,
  writingPolicyItems: [{ id: "stale-item" }],
  writingPolicyItemTotal: 55,
  writingPolicyListError: ""
};
const executableScheduleSearch = new Function(
  "state",
  "setTimeout",
  "clearTimeout",
  "loadWritingPolicyItems",
  "renderWritingPolicyList",
  "byId",
  `return (${scheduleSearchSource});`
)(
  scheduledSearchState,
  function (callback) {
    scheduledSearchCallback = callback;
    return 99;
  },
  function () {},
  function () {
    scheduledSearchLoads += 1;
  },
  function () {
    scheduledSearchRenders += 1;
  },
  function () {
    return scheduledSearchStatus;
  }
);
executableScheduleSearch("新查询");
assert.strictEqual(scheduledSearchState.writingPolicyLoadSequence, 8);
assert.deepStrictEqual(scheduledSearchState.writingPolicyItems, []);
assert.strictEqual(scheduledSearchState.writingPolicyItemTotal, 0);
assert.strictEqual(scheduledSearchState.writingPolicyItemOffset, 0);
assert.strictEqual(scheduledSearchRenders, 1);
assert.strictEqual(scheduledSearchLoads, 0);
assert.strictEqual(scheduledSearchStatus.textContent, "正在筛选...");
scheduledSearchCallback();
assert.strictEqual(scheduledSearchLoads, 1);

[
  "state.rewriteResult = setSmartWriteResult",
  "state.pendingApplyAction = taskType === \"word.smart_write\"",
  "setApplyEnabled(state.pendingApplyAction === \"rewrite\")",
  "applyRewrite()",
  "buildDocumentReviewRecord",
  "documentReviewIssueStatus"
].forEach((token) => assert.ok(wordJs.includes(token), token));

[
  "writing-policies-summary-card",
  "writing-policy-scope-view",
  "writing-policy-preset-view",
  "writing-policy-preset-title",
  "writing-policy-preset-pack-select",
  "writing-policy-preset-pack-meta",
  "writing-policy-preset-item-list",
  "btn-writing-policy-preset-previous",
  "writing-policy-preset-page-status",
  "btn-writing-policy-preset-next",
  "btn-writing-policy-preset-back",
  "btn-writing-policy-open-organization",
  "writing-policy-list-view",
  "writing-policy-editor-view",
  "btn-writing-policy-scope-back",
  "btn-writing-policy-list-back",
  "btn-writing-policy-editor-back",
  "writing-policy-type-switch",
  "writing-policy-search-input",
  "btn-writing-policy-previous",
  "writing-policy-page-status",
  "btn-writing-policy-next",
  "btn-writing-policy-add",
  "btn-writing-policy-more",
  "writing-policy-more-view",
  "writing-policy-export-scope",
  "writing-policy-editor-advanced",
  "btn-writing-policy-delete",
  "writing-policy-import-view",
  "writing-policy-import-file",
  "btn-writing-policy-download-csv-template",
  "btn-writing-policy-download-xlsx-template",
  "btn-writing-policy-export-csv",
  "btn-writing-policy-export-xlsx",
  "btn-writing-policy-download-backup"
].forEach((id) => assert.ok(wordHtml.includes(`id="${id}"`), id));

assert.ok(wordHtml.includes('data-writing-policy-layer="preset"'));
assert.ok(wordHtml.includes('data-writing-policy-layer="organization"'));
assert.ok(wordHtml.includes('data-writing-policy-type="anti_template"'));
[
  "writing-policy-task-smart-write",
  "writing-policy-task-smart-imitation",
  "writing-policy-task-document-review",
  "writing-policy-scene-yangqi",
  "writing-policy-scene-cybersecurity",
  "writing-policy-scene-official"
].forEach((id) => assert.ok(wordHtml.includes(`id="${id}"`), id));
assert.ok(/id="btn-writing-policy-import-entry"[^>]*hidden/.test(wordHtml));

const editorRenderSource = functionSource("renderWritingPolicyEditor");
assert.ok(editorRenderSource.includes("normalizeWritingPolicyRuleTasks"));
assert.ok(editorRenderSource.includes("normalizeWritingPolicyRuleScenes"));
assert.ok(editorRenderSource.includes("setWritingPolicyCheckedValues"));
assert.ok(editorRenderSource.includes('editor.mode === "preset-override"'));
assert.ok(editorRenderSource.includes("item.alwaysApply !== false"));
const draftSource = functionSource("readWritingPolicyDraft");
assert.ok(draftSource.includes("taskTypes"));
assert.ok(draftSource.includes("sceneIds"));
assert.ok(draftSource.includes("anti_template"));

const validAntiTemplate = helpers.validateWritingPolicyDraft({
  type: "anti_template",
  name: "删除空泛铺垫",
  ruleText: "直接陈述事实和结论。",
  taskTypes: ["word.smart_write", "word.document_review"],
  sceneIds: ["yangqi", "cybersecurity"]
});
assert.strictEqual(validAntiTemplate.ok, true);
assert.strictEqual(
  helpers.validateWritingPolicyDraft({
    type: "style",
    name: "结论先行",
    ruleText: "先写结论。",
    taskTypes: [],
    sceneIds: ["yangqi"]
  }).field,
  "taskTypes"
);
assert.strictEqual(
  helpers.validateWritingPolicyDraft({
    type: "style",
    name: "结论先行",
    ruleText: "先写结论。",
    taskTypes: ["word.smart_write"],
    sceneIds: []
  }).field,
  "sceneIds"
);

const conflictUsage = helpers.normalizeWritingPolicyUsage({
  applied: true,
  sceneLabel: "G企技术材料",
  conflictCount: 1,
  conflicts: [
    {
      name: "结论先行",
      winnerId: "rule-high",
      itemIds: ["rule-high", "rule-low"]
    }
  ]
});
assert.strictEqual(conflictUsage.conflictCount, 1);
assert.strictEqual(conflictUsage.conflicts[0].winnerId, "rule-high");
assert.ok(
  helpers.writingPolicyUsageSummary(conflictUsage, "word.smart_write")
    .includes("1 组同层冲突")
);
assert.ok(
  helpers.writingPolicyUsageDetails(conflictUsage)
    .some((item) => item.includes("结论先行"))
);

[
  "writing-policies-summary-card",
  "writing-policy-scope-view",
  "writing-policy-list-view",
  "writing-policy-editor-view"
].forEach((id) => {
  assert.ok(!excelHtml.includes(`id="${id}"`), `Excel must not include ${id}`);
  assert.ok(!pptHtml.includes(`id="${id}"`), `PPT must not include ${id}`);
});

assert.strictEqual((wordHtml.match(/data-writing-policy-scope=/g) || []).length, 3);
assert.ok(wordHtml.includes('data-writing-policy-type="term"'));
assert.ok(wordHtml.includes('data-writing-policy-type="style"'));
assert.ok(wordHtml.includes('data-writing-policy-type="anti_template"'));
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
assert.strictEqual(
  helpers.writingPolicyItemStateLabel({ enabled: true }, "organization"),
  "组织自定义 · 已生效"
);
assert.strictEqual(
  helpers.writingPolicyItemStateLabel({ organizationState: "overridden", effective: true }, "preset"),
  "组织覆盖 · 已生效"
);
assert.strictEqual(
  helpers.writingPolicyItemStateLabel({ organizationState: "disabled", effective: false }, "preset"),
  "预置停用 · 未生效"
);
assert.strictEqual(
  helpers.writingPolicyItemStateLabel({ organizationState: "preset", effective: true }, "preset"),
  "预置基线 · 已生效"
);
assert.strictEqual(helpers.normalizeWritingPolicyPriority(88), "high");
assert.strictEqual(helpers.normalizeWritingPolicyPriority(50), "medium");
assert.strictEqual(helpers.normalizeWritingPolicyPriority(20), "low");
assert.strictEqual(helpers.normalizeWritingPolicyPriority("high"), "high");
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
  fileDigest: "digest",
  newCount: 2,
  modifyCount: 1,
  disableCount: 2,
  restoreCount: 3,
  deleteCount: 4,
  conflictCount: 1,
  errorCount: 1,
  errors: [{ row: 6, message: "第 6 行：字段无效。" }],
  conflicts: [{ rowNumber: 4, message: "第 4 行：冲突。", defaultDecision: "keep_existing" }]
});
assert.strictEqual(previewModel.previewToken, "token");
assert.strictEqual(previewModel.fileDigest, "digest");
assert.deepStrictEqual(previewModel.stats, {
  newCount: 2,
  modifyCount: 1,
  disableCount: 2,
  restoreCount: 3,
  deleteCount: 4,
  conflictCount: 1,
  errorCount: 1
});
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
    fileDigest: "",
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
assert.ok(presetRenderSource.includes("helpers.writingPolicyItemStateLabel"));
assert.ok(presetRenderSource.includes("data-writing-policy-preset-action"));
assert.ok(presetRenderSource.includes('"edit"'));
assert.ok(presetRenderSource.includes('"disable"'));
assert.ok(presetRenderSource.includes('"restore"'));
assert.ok(!presetRenderSource.includes("innerHTML"));

const presetDisableSource = functionSource("disableWritingPolicyPresetItem");
assert.ok(presetDisableSource.includes("/writing-policies/preset-overrides/"));
assert.ok(presetDisableSource.includes('method: "PUT"'));
assert.ok(presetDisableSource.includes('operation: "disabled"'));
assert.ok(presetDisableSource.includes("loadWritingPolicyPresetItems"));

const presetRestoreSource = functionSource("restoreWritingPolicyPresetItem");
assert.ok(presetRestoreSource.includes("/writing-policies/preset-overrides/"));
assert.ok(presetRestoreSource.includes('method: "DELETE"'));
assert.ok(presetRestoreSource.includes("loadWritingPolicyPresetItems"));

const listSource = functionSource("loadWritingPolicyItems");
assert.ok(listSource.includes('request("/writing-policies/items?scope="'));
assert.ok(listSource.includes('"organization"'));
assert.ok(listSource.includes("writingPolicyLoadSequence"));

const listRenderSource = functionSource("renderWritingPolicyList");
assert.ok(listRenderSource.includes("textContent"));
assert.ok(!listRenderSource.includes("innerHTML"));

const editorSource = functionSource("renderWritingPolicyEditor");
assert.ok(editorSource.includes("textContent"));
assert.ok(editorSource.includes("writing-policy-editor-advanced"));
assert.ok(editorSource.includes("helpers.normalizeWritingPolicyPriority"));
assert.ok(editorSource.includes("writing-policy-enabled-field"));

const discardSource = functionSource("confirmWritingPolicyEditorDiscard");
assert.ok(discardSource.includes("writingPolicyEditorDirty"));
assert.ok(discardSource.includes("window.confirm"));

const saveSource = functionSource("saveWritingPolicyItem");
assert.ok(saveSource.includes("writingPolicyMutationBusy"));
assert.ok(saveSource.includes('options.method = "PATCH"'));
assert.ok(saveSource.includes('editor.mode === "preset-override"'));
assert.ok(saveSource.includes("/writing-policies/preset-overrides/"));
assert.ok(saveSource.includes('options.method = "PUT"'));
assert.ok(saveSource.includes('draft.operation = "override"'));
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
  "btn-writing-policy-preset-previous",
  "btn-writing-policy-preset-next",
  "btn-writing-policy-previous",
  "btn-writing-policy-next",
  "btn-writing-policy-more",
  "btn-writing-policy-more-back",
  "btn-writing-policy-more-import",
  "btn-writing-policy-import-back",
  "btn-preview-writing-policy-import",
  "writing-policy-import-conflict-list",
  "btn-apply-writing-policy-import",
  "btn-writing-policy-download-csv-template",
  "btn-writing-policy-download-xlsx-template",
  "btn-writing-policy-export-csv",
  "btn-writing-policy-export-xlsx",
  "btn-writing-policy-download-backup",
  "btn-writing-policy-refresh-diagnostics"
].forEach((id) => assert.ok(bindSource.includes(`byId(\"${id}\")`), `missing event binding for ${id}`));
assert.ok(bindSource.includes('byId("writing-policy-preset-pack-select").addEventListener("change"'));
assert.ok(bindSource.includes('byId("writing-policy-preset-item-list").addEventListener("click"'));
assert.ok(bindSource.includes('byId("writing-policy-type-switch").addEventListener("keydown", handleWritingPolicyTypeKeydown)'));

[
  "writing-policy-scope-title",
  "writing-policy-list-title",
  "writing-policy-more-title",
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
  "/writing-policies/export.",
  "?scope=",
  "/writing-policies/backup"
].forEach((path) => assert.ok(wordJs.includes(path), `missing writingPolicy download path ${path}`));

console.log("writing policy Word result and manager tests passed");
