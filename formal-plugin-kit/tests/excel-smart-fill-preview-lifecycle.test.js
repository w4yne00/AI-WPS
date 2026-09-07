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
    instruction: "根据姓名生成岗位标签"
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

function testTaskpaneDoesNotClearPreviewOnSuccessfulWrite() {
  const codeToRun = js.replace(
    "if (!isTaskpanePage()) {",
    `window.__TEST_EXPORTS__ = {
      state: state,
      writeExcelSmartFillResult: writeExcelSmartFillResult
    };
    return;
    if (!isTaskpanePage()) {`
  );
  const dom = {};
  function el(id) {
    if (!dom[id]) {
      dom[id] = {
        id: id,
        innerHTML: "",
        textContent: "",
        hidden: false,
        disabled: false,
        className: "",
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        attributes: {},
        getAttribute(k) { return this.attributes[k]; },
        setAttribute(k, v) { this.attributes[k] = v; },
        addEventListener() {}
      };
    }
    return dom[id];
  }
  ["result-output", "status-line", "btn-write-smart-fill", "btn-edit-smart-fill", "btn-new-smart-fill", "btn-run-primary", "smart-fill-write-summary", "excel-smart-fill-options"].forEach(el);
  const context = {
    window: {
      WpsAiAssistantHelpers: helpers,
      localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
      confirm() { return true; },
      Application: {},
      __TEST_EXPORTS__: null
    },
    document: { getElementById: el, querySelector() { return null; }, querySelectorAll() { return []; } },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout
  };
  vm.createContext(context);
  vm.runInContext(codeToRun, context);
  assert.ok(js.includes("开始新的填写"));
  assert.ok(js.includes("返回修改"));
  assert.ok(js.includes("sanitizeRestoredExcelSmartFillState") || js.includes("startNewExcelSmartFill"));
}

testReturnToEditWithoutInputChangeKeepsWritablePreview();
testSourceOrInstructionChangeInvalidatesPreviewWithoutDeletingResult();
testAddressChangeAlsoInvalidatesPreview();
testUnchangedInputsAfterReturnDoNotInvalidate();
testReturnToEditDoesNotTreatCurrentTargetSelectionAsSourceChange();
testNewSourceSelectionAfterReturnInvalidatesPreview();
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
testTaskpaneDoesNotClearPreviewOnSuccessfulWrite();

console.log("Excel smart fill preview lifecycle tests passed");
