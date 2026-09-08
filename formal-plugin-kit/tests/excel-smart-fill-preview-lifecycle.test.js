const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { etRoot } = require("./support/plugin-roots");
const helpers = require(path.join(etRoot, "taskpane-helpers.js"));
const html = fs.readFileSync(path.join(etRoot, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(etRoot, "taskpane.js"), "utf8");
const css = fs.readFileSync(path.join(etRoot, "taskpane.css"), "utf8");

function itemId(n) {
  return "sf_" + String(n).padStart(32, "0");
}

function sampleResult() {
  return {
    schemaVersion: "excel.smart_fill.v2",
    items: [
      { itemId: itemId(1), status: "completed", valueType: "text", value: "甲类", sourceRowLabel: "第 2 行" },
      { itemId: itemId(2), status: "completed", valueType: "text", value: "乙类", sourceRowLabel: "第 3 行" }
    ]
  };
}

function sampleFingerprint(overrides) {
  return Object.assign({
    sourceAddress: "$A$1:$C$3",
    sourceSnapshotHash: "hash-source-1",
    instruction: "根据姓名生成岗位标签",
    workbookId: "wb-1",
    sheetName: "客户表"
  }, overrides || {});
}

function makeCell(value) {
  let current = value;
  return {
    get Value2() { return current; },
    set Value2(next) { current = next; },
    get Text() { return current == null ? "" : String(current); },
    Formula: "",
    HasFormula: false,
    MergeCells: false,
    Locked: false,
    Hidden: false
  };
}

function testReturnToEditWithoutInputChangeKeepsWritablePreview() {
  assert.strictEqual(typeof helpers.createExcelSmartFillPreview, "function");
  assert.strictEqual(typeof helpers.returnToExcelSmartFillEdit, "function");
  assert.strictEqual(typeof helpers.describeExcelSmartFillPreviewLifecycle, "function");

  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  const afterReturn = helpers.returnToExcelSmartFillEdit(preview);
  const life = helpers.describeExcelSmartFillPreviewLifecycle(afterReturn);

  assert.strictEqual(life.status, "ready");
  assert.strictEqual(life.writeEnabled, true);
  assert.strictEqual(life.showReturnToEdit, false);
  assert.strictEqual(life.showStartNew, false);
  assert.strictEqual(life.sourceInputsVisible, true);
  assert.ok(afterReturn.result);
  assert.strictEqual(afterReturn.result.items[0].value, "甲类");
  assert.strictEqual(afterReturn.consumed, false);
}

function testSourceOrInstructionChangeInvalidatesPreviewWithoutDeletingResult() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.returnToExcelSmartFillEdit(preview);
  const invalidated = helpers.syncExcelSmartFillPreviewWithInputs(
    preview,
    sampleFingerprint({ instruction: "改成英文岗位标签" })
  );
  const life = helpers.describeExcelSmartFillPreviewLifecycle(invalidated);

  assert.strictEqual(life.status, "invalid");
  assert.strictEqual(life.writeEnabled, false);
  assert.ok(life.reason);
  assert.match(life.reason, /来源范围或填写意图/);
  assert.strictEqual(invalidated.consumed, false);
  assert.strictEqual(invalidated.result.items[1].value, "乙类");
  assert.ok(life.previewReadonly);

  const htmlPreview = helpers.buildExcelSmartFillLifecyclePreview(invalidated, [], []);
  assert.ok(htmlPreview.includes("甲类"));
  assert.ok(htmlPreview.includes("失效"));
  assert.ok(!htmlPreview.includes("data-smart-fill-value-input"));
  assert.ok(!htmlPreview.includes("<input"));
}

function testAddressChangeAlsoInvalidatesPreview() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.syncExcelSmartFillPreviewWithInputs(
    preview,
    sampleFingerprint({ sourceAddress: "$A$1:$D$10", sourceSnapshotHash: "hash-source-2" })
  );
  assert.strictEqual(helpers.describeExcelSmartFillPreviewLifecycle(preview).status, "invalid");
}

function testUnchangedInputsAfterReturnDoNotInvalidate() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.returnToExcelSmartFillEdit(preview);
  helpers.syncExcelSmartFillPreviewWithInputs(preview, sampleFingerprint());
  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview);
  assert.strictEqual(life.status, "ready");
  assert.strictEqual(life.writeEnabled, true);
}

function testReturnToEditDoesNotTreatCurrentTargetSelectionAsSourceChange() {
  assert.strictEqual(typeof helpers.buildExcelSmartFillEditFingerprint, "function");
  const frozen = sampleFingerprint();
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), frozen);
  helpers.returnToExcelSmartFillEdit(preview);
  const next = helpers.buildExcelSmartFillEditFingerprint(frozen, {
    liveSource: { ok: true, address: "$D$2:$D$4", rawAddress: "$D$2:$D$4" },
    baselineAddress: "$D$2:$D$4",
    instruction: frozen.instruction
  });
  helpers.syncExcelSmartFillPreviewWithInputs(preview, next);
  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview);
  assert.strictEqual(life.status, "ready", "staying on the write target must not invalidate");
  assert.strictEqual(life.writeEnabled, true);
}

function testNewSourceSelectionAfterReturnInvalidatesPreview() {
  const frozen = sampleFingerprint();
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), frozen);
  helpers.returnToExcelSmartFillEdit(preview);
  const next = helpers.buildExcelSmartFillEditFingerprint(frozen, {
    liveSource: { ok: true, address: "$E$1:$G$10", rawAddress: "$E$1:$G$10" },
    baselineAddress: "$D$2:$D$4",
    instruction: frozen.instruction
  });
  helpers.syncExcelSmartFillPreviewWithInputs(preview, next);
  assert.strictEqual(helpers.describeExcelSmartFillPreviewLifecycle(preview).status, "invalid");
}

function testInvalidReadonlyPreviewShowsSourceRowLabelsNotItemIds() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.syncExcelSmartFillPreviewWithInputs(
    preview,
    sampleFingerprint({ instruction: "新意图" })
  );
  const htmlPreview = helpers.buildExcelSmartFillLifecyclePreview(preview, [], []);
  assert.ok(htmlPreview.includes("第 2 行"));
  assert.ok(!htmlPreview.includes(itemId(1)));
}

function testRegenerateAfterInvalidCreatesNewWritablePreview() {
  const oldPreview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.syncExcelSmartFillPreviewWithInputs(
    oldPreview,
    sampleFingerprint({ instruction: "新意图" })
  );
  const next = helpers.createExcelSmartFillPreview({
    schemaVersion: "excel.smart_fill.v2",
    items: [
      { itemId: itemId(3), status: "completed", valueType: "text", value: "新结果", sourceRowLabel: "第 2 行" }
    ]
  }, sampleFingerprint({ instruction: "新意图" }));
  const life = helpers.describeExcelSmartFillPreviewLifecycle(next);
  assert.strictEqual(life.status, "ready");
  assert.strictEqual(life.writeEnabled, true);
  assert.strictEqual(next.result.items[0].value, "新结果");
}

function testTargetPrecheckFailureDoesNotConsumePreview() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  const kept = helpers.markExcelSmartFillPreviewTargetRejected(preview, "目标必须是连续的单列区域。");
  const life = helpers.describeExcelSmartFillPreviewLifecycle(kept);
  assert.strictEqual(life.status, "ready");
  assert.strictEqual(life.writeEnabled, true);
  assert.strictEqual(kept.consumed, false);
  assert.ok(life.targetError.includes("连续的单列"));
  assert.strictEqual(kept.result.items.length, 2);
}

function testCompensationSuccessKeepsPreviewAndAllowsRetryWithoutConsuming() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.markExcelSmartFillPreviewWriteFailed(preview, {
    compensated: true,
    message: "写入中途失败，已恢复原值。",
    addresses: []
  });
  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview);
  assert.strictEqual(life.status, "ready");
  assert.strictEqual(life.writeEnabled, true);
  assert.strictEqual(preview.consumed, false);
  assert.match(life.writeFailureReason, /恢复原值/);
  assert.ok(!life.overallWriteSuccess);
}

function testCompensationFailureListsExactAddressesAndIsNotSuccess() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.markExcelSmartFillPreviewWriteFailed(preview, {
    compensated: false,
    message: "内部故障处理未能完全恢复",
    addresses: ["$D$2", "$D$3"]
  });
  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview);
  assert.strictEqual(life.overallWriteSuccess, false);
  assert.deepStrictEqual(life.manualReviewAddresses, ["$D$2", "$D$3"]);
  assert.ok(life.writeFailureReason.includes("$D$2"));
  assert.ok(life.writeFailureReason.includes("$D$3"));
  assert.strictEqual(preview.consumed, false);
}

function testSuccessfulWriteLocksPreviewAndRejectsDuplicateSubmit() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.finalizeExcelSmartFillWriteSuccess(preview, { writtenCount: 2, skippedCount: 0 });
  assert.strictEqual(preview.consumed, true);
  assert.ok(preview.result, "locked preview must keep original results for review");
  assert.strictEqual(preview.result.items[0].value, "甲类");

  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview);
  assert.strictEqual(life.status, "locked");
  assert.strictEqual(life.writeEnabled, false);
  assert.strictEqual(life.showStartNew, true);
  assert.strictEqual(life.showReturnToEdit, false);
  assert.strictEqual(life.writtenCount, 2);
  assert.strictEqual(life.skippedCount, 0);
  assert.match(life.summary, /写入.*2/);
  assert.match(life.summary, /跳过.*0/);

  assert.throws(() => helpers.consumeExcelSmartFillPreview(preview), /重复/);
  assert.throws(
    () => helpers.finalizeExcelSmartFillWriteSuccess(preview, { writtenCount: 2, skippedCount: 0 }),
    /重复/
  );
}

function testStartNewFillClearsLockedPreview() {
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.finalizeExcelSmartFillWriteSuccess(preview, { writtenCount: 1, skippedCount: 1 });
  const cleared = helpers.startNewExcelSmartFill(preview);
  assert.strictEqual(cleared, null);
}

function testSameCountNewTargetDoesNotReuseOldAddressBinding() {
  const oldItems = [
    { itemId: itemId(1), address: "$D$2", row: 2, column: 4, sheetName: "客户表", originalValue: "", originalValueType: "blank" },
    { itemId: itemId(2), address: "$D$3", row: 3, column: 4, sheetName: "客户表", originalValue: "", originalValueType: "blank" }
  ];
  const newItems = [
    { itemId: itemId(1), address: "$E$2", row: 2, column: 5, sheetName: "客户表", originalValue: "", originalValueType: "blank" },
    { itemId: itemId(2), address: "$E$3", row: 3, column: 5, sheetName: "客户表", originalValue: "", originalValueType: "blank" }
  ];
  const staleCommit = {
    jobId: "job-1",
    workbookId: "wb-1",
    sourceSnapshotHash: "hash-source-1",
    resultRevision: 1,
    targetSheetName: "客户表",
    targetAddress: "$D$2:$D$3",
    itemCount: 2
  };
  const results = [
    { itemId: itemId(1), status: "completed", valueType: "text", value: "甲" },
    { itemId: itemId(2), status: "completed", valueType: "text", value: "乙" }
  ];
  const cells = { "$E$2": makeCell(""), "$E$3": makeCell("") };

  assert.throws(
    () => helpers.writeExcelSmartFillCells(newItems, results, (item) => cells[item.address], { commitContext: staleCommit }),
    /旧绑定|当前选区|目标地址/
  );
  assert.strictEqual(cells["$E$2"].Value2, "");
  assert.strictEqual(cells["$E$3"].Value2, "");

  const restored = helpers.sanitizeRestoredExcelSmartFillState({
    smartFillResult: sampleResult(),
    smartFillTarget: { address: "$D$2:$D$3", items: oldItems, sheetName: "客户表" },
    smartFillSource: { address: "$A$1:$C$3", snapshotHash: "hash-source-1" }
  });
  assert.strictEqual(restored.smartFillTarget, null);
  assert.ok(restored.smartFillResult);
  assert.ok(restored.smartFillSource);
}

function testRestoreWithoutFrozenSourceDisablesWrite() {
  const restored = helpers.sanitizeRestoredExcelSmartFillState({
    smartFillResult: sampleResult(),
    smartFillSource: null,
    smartFillItems: [],
    smartFillTarget: { address: "$D$2:$D$3", items: [{ itemId: itemId(1) }] }
  });
  const preview = helpers.createExcelSmartFillPreview(restored.smartFillResult, null);
  const life = helpers.describeExcelSmartFillPreviewLifecycle(preview, {
    frozenSource: restored.smartFillSource
  });
  assert.strictEqual(life.writeEnabled, false);
}

function testLifecycleControlsMatchNarrowWindowContract() {
  assert.ok(html.includes("返回修改"));
  assert.ok(html.includes("开始新的填写"));
  assert.ok(html.includes("id=\"btn-edit-smart-fill\""));
  assert.ok(html.includes("id=\"btn-new-smart-fill\""));
  assert.ok(/id=\"smart-fill-write-summary\"[^>]*tabindex=\"-1\"/.test(html));
  assert.ok(!html.includes("撤销"));

  const sharedTail = css.indexOf("/* Shared restrained settings and interaction treatment. */");
  const editRule = css.indexOf("#btn-edit-smart-fill");
  const newRule = css.indexOf("#btn-new-smart-fill");
  assert.ok(sharedTail > 0);
  assert.ok(editRule >= 0 && editRule < sharedTail);
  assert.ok(newRule >= 0 && newRule < sharedTail);
  assert.match(css.slice(0, sharedTail), /#btn-edit-smart-fill[\s\S]*min-height:\s*36px/);
  assert.match(css.slice(0, sharedTail), /#btn-new-smart-fill[\s\S]*min-height:\s*36px/);

  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  let controls = helpers.resolveExcelSmartFillLifecycleControls(preview, { busy: false });
  assert.strictEqual(controls.returnToEditHidden, false);
  assert.strictEqual(controls.startNewHidden, true);
  assert.strictEqual(controls.writeHidden, false);
  assert.strictEqual(controls.generateHidden, true);

  helpers.returnToExcelSmartFillEdit(preview);
  controls = helpers.resolveExcelSmartFillLifecycleControls(preview, { busy: false });
  assert.strictEqual(controls.generateHidden, false);
  assert.strictEqual(controls.returnToEditHidden, true);

  helpers.finalizeExcelSmartFillWriteSuccess(preview, { writtenCount: 2, skippedCount: 0 });
  controls = helpers.resolveExcelSmartFillLifecycleControls(preview, { busy: false });
  assert.strictEqual(controls.writeHidden, true);
  assert.strictEqual(controls.generateHidden, true);
  assert.strictEqual(controls.returnToEditHidden, true);
  assert.strictEqual(controls.startNewHidden, false);
  assert.strictEqual(controls.startNewDisabled, false);
}

function testSameAddressOnAnotherSheetInvalidatesPreview() {
  const frozen = sampleFingerprint();
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), frozen);
  helpers.returnToExcelSmartFillEdit(preview);
  const next = helpers.buildExcelSmartFillEditFingerprint(frozen, {
    liveSource: { ok: true, address: "$A$1:$C$3", rawAddress: "$A$1:$C$3", sheetName: "备份表" },
    baselineAddress: "$D$2:$D$4",
    instruction: frozen.instruction,
    workbookId: "wb-1"
  });
  helpers.syncExcelSmartFillPreviewWithInputs(preview, next);
  assert.strictEqual(
    helpers.describeExcelSmartFillPreviewLifecycle(preview).status,
    "invalid",
    "same A1 on another sheet must invalidate"
  );
}

function testTargetBaselineOnDifferentSheetDoesNotInvalidate() {
  const frozen = sampleFingerprint();
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), frozen);
  helpers.returnToExcelSmartFillEdit(preview);
  const next = helpers.buildExcelSmartFillEditFingerprint(frozen, {
    liveSource: { ok: true, address: "$D$2:$D$4", rawAddress: "$D$2:$D$4", sheetName: "目标表" },
    baselineAddress: "$D$2:$D$4",
    instruction: frozen.instruction,
    workbookId: "wb-1"
  });
  helpers.syncExcelSmartFillPreviewWithInputs(preview, next);
  assert.strictEqual(helpers.describeExcelSmartFillPreviewLifecycle(preview).status, "ready");
}

function testWorkbookIdentityChangeInvalidatesPreview() {
  const frozen = sampleFingerprint();
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), frozen);
  helpers.returnToExcelSmartFillEdit(preview);
  const next = helpers.buildExcelSmartFillEditFingerprint(frozen, {
    liveSource: { ok: true, address: "$A$1:$C$3", rawAddress: "$A$1:$C$3", sheetName: "客户表" },
    baselineAddress: "$D$2:$D$4",
    instruction: frozen.instruction,
    workbookId: "wb-other"
  });
  helpers.syncExcelSmartFillPreviewWithInputs(preview, next);
  assert.strictEqual(helpers.describeExcelSmartFillPreviewLifecycle(preview).status, "invalid");
}

function testRebindClearsTransientWriteConflict() {
  assert.strictEqual(typeof helpers.resetExcelSmartFillDraftWriteConflicts, "function");
  const drafts = [
    { itemId: itemId(1), status: "write_conflict", selected: false, value: "甲类" },
    { itemId: itemId(2), status: "completed", selected: true, value: "乙类" }
  ];
  helpers.resetExcelSmartFillDraftWriteConflicts(drafts);
  assert.strictEqual(drafts[0].status, "completed");
  assert.strictEqual(drafts[0].selected, true);
  assert.strictEqual(drafts[1].status, "completed");
}

function testSuccessfulTargetBindClearsTargetError() {
  assert.strictEqual(typeof helpers.clearExcelSmartFillPreviewTargetError, "function");
  const preview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  helpers.markExcelSmartFillPreviewTargetRejected(preview, "目标必须是连续的单列区域。");
  helpers.clearExcelSmartFillPreviewTargetError(preview);
  assert.strictEqual(helpers.describeExcelSmartFillPreviewLifecycle(preview).targetError, "");
}

function makeDom() {
  const dom = {};
  function el(id) {
    if (!dom[id]) {
      dom[id] = {
        id: id,
        innerHTML: "",
        textContent: "",
        value: "",
        hidden: false,
        disabled: false,
        className: "",
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        attributes: {},
        getAttribute(k) { return this.attributes[k]; },
        setAttribute(k, v) { this.attributes[k] = v; },
        addEventListener() {},
        focus() {}
      };
    }
    return dom[id];
  }
  [
    "result-output", "status-line", "settings-status-line", "btn-write-smart-fill",
    "btn-edit-smart-fill", "btn-new-smart-fill", "btn-run-primary",
    "smart-fill-write-summary", "excel-smart-fill-options", "excel-smart-fill-instruction",
    "smart-fill-source-summary", "smart-fill-validation-line", "btn-copy-formula"
  ].forEach(el);
  return { dom, el };
}

function loadTaskpane(fetchImpl, selection) {
  const { el } = makeDom();
  const codeToRun = js.replace(
    "if (!isTaskpanePage()) {",
    `window.__TEST_EXPORTS__ = {
      state: state,
      runExcelSmartFillAction: runExcelSmartFillAction,
      writeExcelSmartFillResult: writeExcelSmartFillResult,
      returnToExcelSmartFillEditAction: returnToExcelSmartFillEditAction,
      renderSmartFillCaptureState: renderSmartFillCaptureState,
      tryRebindSmartFillTarget: tryRebindSmartFillTarget
    };
    return;
    if (!isTaskpanePage()) {`
  );
  const application = {
    ActiveWorkbook: { Name: "wb-1" },
    ActiveSheet: { Name: "客户表" },
    Selection: selection || {
      Address: "$D$2:$D$3",
      Worksheet: { Name: "客户表" }
    }
  };
  const context = {
    window: {
      WpsAiAssistantHelpers: helpers,
      localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
      confirm() { return true; },
      Application: application,
      __TEST_EXPORTS__: null
    },
    document: {
      getElementById: el,
      querySelector() { return null; },
      querySelectorAll() { return []; }
    },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    fetch: fetchImpl || function () {
      return Promise.reject(new Error("fetch not stubbed"));
    },
    Promise: Promise,
    JSON: JSON,
    Error: Error,
    encodeURIComponent: encodeURIComponent
  };
  vm.createContext(context);
  vm.runInContext(codeToRun, context);
  const exported = context.window.__TEST_EXPORTS__;
  exported.application = application;
  exported.status = function () {
    return el("status-line").textContent;
  };
  exported.result = function () {
    return el("result-output").textContent;
  };
  exported.setInstruction = function (value) {
    el("excel-smart-fill-instruction").value = value;
  };
  return exported;
}

function testGeneratePreflightFailureIsVisibleInResultPreview() {
  const cells = [makeCell("姓名"), makeCell("张三")];
  cells.forEach(function (cell) {
    cell.EntireRow = { Hidden: false };
    cell.EntireColumn = { Hidden: false };
  });
  Object.defineProperty(cells[1], "HasFormula", {
    configurable: true,
    get() { throw new Error("HasFormula unavailable"); }
  });
  const source = {
    Address: "$A$1:$A$2",
    Worksheet: { Name: "客户表" },
    Rows: { Count: 2 },
    Columns: { Count: 1 },
    Areas: { Count: 1 },
    Cells: { Item(row) { return cells[row - 1]; } }
  };
  const exported = loadTaskpane(null, source);
  exported.state.currentMode = "excelSmartFill";
  exported.state.modelTasksAllowed = true;
  exported.application.Selection = source;
  exported.application.ActiveSheet = source.Worksheet;
  exported.application.ActiveWorkbook = { Name: "wb-1" };
  exported.state.smartFillRetryItemId = "";
  exported.setInstruction("生成标签");
  exported.runExcelSmartFillAction();
  assert.match(exported.status(), /无法安全读取来源单元格状态/);
  assert.match(exported.result(), /无法安全读取来源单元格状态/);
}

function cannedMapping() {
  return {
    ok: true,
    target: {
      sheetName: "客户表",
      address: "$D$2:$D$3",
      items: [
        {
          itemId: itemId(1), address: "$D$2", row: 2, column: 4, sheetName: "客户表",
          originalValue: "", originalValueType: "blank", originalFormula: "",
          isFormula: false, isMerged: false, isProtected: false, isHidden: false
        },
        {
          itemId: itemId(2), address: "$D$3", row: 3, column: 4, sheetName: "客户表",
          originalValue: "", originalValueType: "blank", originalFormula: "",
          isFormula: false, isMerged: false, isProtected: false, isHidden: false
        }
      ]
    },
    commitContext: {
      jobId: "job-write-1",
      workbookId: "wb-1",
      sourceSnapshotHash: "hash-source-1",
      resultRevision: 1,
      targetSheetName: "客户表",
      targetAddress: "$D$2:$D$3",
      itemCount: 2
    },
    overwriteCount: 0
  };
}

function seedWritableState(exported) {
  exported.state.currentMode = "excelSmartFill";
  exported.state.busy = false;
  exported.state.smartFillResult = sampleResult();
  exported.state.smartFillPreview = helpers.createExcelSmartFillPreview(sampleResult(), sampleFingerprint());
  exported.state.smartFillDraftItems = [
    { itemId: itemId(1), status: "completed", selected: true, value: "甲类", valueType: "text" },
    { itemId: itemId(2), status: "completed", selected: true, value: "乙类", valueType: "text" }
  ];
  exported.state.excelSmartFillCompletedJobId = "job-write-1";
  exported.state.excelSmartFillResultRevision = 1;
  exported.state.smartFillWorkbookId = "wb-1";
  exported.state.smartFillSource = null;
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    json: function () { return Promise.resolve(body); }
  };
}

async function testWriteReservesBeforeHostWrite() {
  const events = [];
  let resolveReserve;
  const fetchImpl = function (url, options) {
    const body = JSON.parse(options.body || "{}");
    events.push("fetch:" + (body.stage || "confirm"));
    if (body.stage === "reserve") {
      return new Promise(function (resolve) {
        resolveReserve = function () {
          resolve(jsonResponse(200, { success: true, data: { writeReserved: true } }));
        };
      });
    }
    return Promise.resolve(jsonResponse(200, { success: true, data: { writeCommitted: true } }));
  };
  const exported = loadTaskpane(fetchImpl);
  helpers.mapExcelSmartFillPreviewToTarget = function () { return cannedMapping(); };
  helpers.detectExcelSmartFillConflicts = function () { return { hasConflict: false, conflicts: [] }; };
  helpers.writeExcelSmartFillCells = function () {
    events.push("host-write");
    return { writtenCount: 2, skippedCount: 0 };
  };
  seedWritableState(exported);

  const pending = exported.writeExcelSmartFillResult();
  assert.ok(pending && typeof pending.then === "function");
  await Promise.resolve();
  assert.deepStrictEqual(events, ["fetch:reserve"]);
  assert.ok(!events.includes("host-write"));
  resolveReserve();
  await pending;
  assert.deepStrictEqual(events, ["fetch:reserve", "host-write", "fetch:confirm"]);
  assert.strictEqual(exported.state.smartFillPreview.consumed, true);
  assert.strictEqual(exported.state.smartFillPreview.status, "locked");
  assert.ok(exported.state.smartFillPreview.result);
}

async function testDuplicateReserveDoesNotWriteHost() {
  const events = [];
  const fetchImpl = function (url, options) {
    const body = JSON.parse(options.body || "{}");
    events.push("fetch:" + (body.stage || "confirm"));
    return Promise.resolve(jsonResponse(409, {
      success: false,
      message: "同一预览不能重复提交写入。",
      errors: [{ code: "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED", message: "同一预览不能重复提交写入。" }]
    }));
  };
  const exported = loadTaskpane(fetchImpl);
  helpers.mapExcelSmartFillPreviewToTarget = function () { return cannedMapping(); };
  helpers.detectExcelSmartFillConflicts = function () { return { hasConflict: false, conflicts: [] }; };
  helpers.writeExcelSmartFillCells = function () {
    events.push("host-write");
    return { writtenCount: 2, skippedCount: 0 };
  };
  seedWritableState(exported);
  await exported.writeExcelSmartFillResult();
  assert.ok(!events.includes("host-write"));
  assert.strictEqual(exported.state.smartFillPreview.consumed, false);
  assert.ok(/重复|已写入|占用/.test(exported.status()));
}

async function testConfirmFailureKeepsSuccessfulHostWrite() {
  const fetchImpl = function (url, options) {
    const body = JSON.parse(options.body || "{}");
    if (body.stage === "reserve") {
      return Promise.resolve(jsonResponse(200, { success: true, data: { writeReserved: true } }));
    }
    return Promise.reject(new Error("Failed to fetch"));
  };
  const exported = loadTaskpane(fetchImpl);
  helpers.mapExcelSmartFillPreviewToTarget = function () { return cannedMapping(); };
  helpers.detectExcelSmartFillConflicts = function () { return { hasConflict: false, conflicts: [] }; };
  helpers.writeExcelSmartFillCells = function () {
    return { writtenCount: 2, skippedCount: 0 };
  };
  seedWritableState(exported);
  await exported.writeExcelSmartFillResult();
  assert.strictEqual(exported.state.smartFillPreview.consumed, true);
  assert.strictEqual(exported.state.smartFillPreview.status, "locked");
}

function testReturnToEditRebindsLiveTargetWhenUnchanged() {
  const exported = loadTaskpane();
  helpers.inspectExcelSmartFillSourceSelection = function () {
    return { ok: true, address: "$D$2:$D$3", rawAddress: "$D$2:$D$3", sheetName: "客户表" };
  };
  helpers.inspectExcelSmartFillTargetSelection = function () {
    return { ok: true, summary: "写入位置：客户表!D2:D3", writableCount: 2, error: "" };
  };
  seedWritableState(exported);
  exported.state.smartFillSource = { address: "$A$1:$C$3", snapshotHash: "hash-source-1", sheetName: "客户表" };
  exported.returnToExcelSmartFillEditAction();
  assert.strictEqual(exported.state.smartFillPreview.editingInputs, true);
  assert.ok(exported.state.smartFillLiveTarget && exported.state.smartFillLiveTarget.ok, "return to edit must rebind writable target");
}

testReturnToEditWithoutInputChangeKeepsWritablePreview();
testSourceOrInstructionChangeInvalidatesPreviewWithoutDeletingResult();
testAddressChangeAlsoInvalidatesPreview();
testUnchangedInputsAfterReturnDoNotInvalidate();
testReturnToEditDoesNotTreatCurrentTargetSelectionAsSourceChange();
testNewSourceSelectionAfterReturnInvalidatesPreview();
testSameAddressOnAnotherSheetInvalidatesPreview();
testTargetBaselineOnDifferentSheetDoesNotInvalidate();
testWorkbookIdentityChangeInvalidatesPreview();
testInvalidReadonlyPreviewShowsSourceRowLabelsNotItemIds();
testRegenerateAfterInvalidCreatesNewWritablePreview();
testTargetPrecheckFailureDoesNotConsumePreview();
testCompensationSuccessKeepsPreviewAndAllowsRetryWithoutConsuming();
testCompensationFailureListsExactAddressesAndIsNotSuccess();
testSuccessfulWriteLocksPreviewAndRejectsDuplicateSubmit();
testStartNewFillClearsLockedPreview();
testSameCountNewTargetDoesNotReuseOldAddressBinding();
testRestoreWithoutFrozenSourceDisablesWrite();
testLifecycleControlsMatchNarrowWindowContract();
testRebindClearsTransientWriteConflict();
testSuccessfulTargetBindClearsTargetError();
testReturnToEditRebindsLiveTargetWhenUnchanged();
testGeneratePreflightFailureIsVisibleInResultPreview();

(async function main() {
  await testWriteReservesBeforeHostWrite();
  await testDuplicateReserveDoesNotWriteHost();
  await testConfirmFailureKeepsSuccessfulHostWrite();
  console.log("Excel smart fill preview lifecycle tests passed");
})().catch(function (error) {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
