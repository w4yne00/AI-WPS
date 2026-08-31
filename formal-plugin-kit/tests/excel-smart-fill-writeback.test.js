const assert = require("assert");

const helpers = require("../wps-ai-assistant-et_1.0.0/taskpane-helpers.js");

function makeCell(value, text) {
  let current = value;
  let currentText = text;
  return {
    get Value2() { return current; },
    set Value2(next) {
      current = next;
      if (typeof currentText !== "undefined") {
        currentText = next == null ? "" : String(next);
      }
    },
    get Text() {
      if (typeof currentText !== "undefined") {
        return currentText == null ? "" : String(currentText);
      }
      return current == null ? "" : String(current);
    },
    set Text(next) { currentText = next; },
    Formula: "",
    HasFormula: false,
    MergeCells: false,
    Locked: false,
    Hidden: false
  };
}

function testFormulaLikeValuesRemainLiteral() {
  ["=文本", "+文本", "-文本", "@文本"].forEach((value) => {
    const item = {
      itemId: "target-1", address: "$C$2", originalValue: "原值", originalValueType: "text",
      originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
    };
    const cell = makeCell("原值");
    helpers.writeExcelSmartFillCells(
      [item],
      [{ itemId: "target-1", status: "completed", valueType: "text", value }],
      () => cell
    );
    assert.strictEqual(cell.Value2, "'" + value);
  });
}

function testBlankCellWritesNumberWithoutChangingNumberFormat() {
  const item = {
    itemId: "target-1",
    address: "$D$2",
    originalValue: "",
    originalValueType: "blank",
    originalFormula: "",
    isFormula: false,
    isMerged: false,
    isProtected: false,
    isHidden: false
  };
  const cell = makeCell("");
  cell.NumberFormat = "0.00";
  cell.Style = { Name: "常规" };
  const result = helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "completed", valueType: "number", value: 12.5 }],
    () => cell
  );
  assert.deepStrictEqual(result, { writtenCount: 1, skippedCount: 0 });
  assert.strictEqual(cell.Value2, 12.5);
  assert.strictEqual(typeof cell.Value2, "number");
  assert.strictEqual(cell.NumberFormat, "0.00");
  assert.strictEqual(cell.Style.Name, "常规");
  assert.ok(!Object.prototype.hasOwnProperty.call(cell, "Formula") || cell.Formula === "");
}

function testBlankCellWritesFormulaLikeTextAsLiteral() {
  const item = {
    itemId: "target-1",
    address: "$D$2",
    originalValue: "",
    originalValueType: "blank",
    originalFormula: "",
    isFormula: false,
    isMerged: false,
    isProtected: false,
    isHidden: false
  };
  const cell = makeCell("");
  helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "=SUM(A1:A2)" }],
    () => cell
  );
  assert.strictEqual(cell.Value2, "'=SUM(A1:A2)");
}

function testInsufficientItemsAreSkippedWithoutWriting() {
  const item = {
    itemId: "target-1", address: "$C$2", originalValue: "原值", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const cell = makeCell("原值");
  const result = helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "insufficient_information", valueType: "text", value: "" }],
    () => cell
  );
  assert.deepStrictEqual(result, { writtenCount: 0, skippedCount: 1 });
  assert.strictEqual(cell.Value2, "原值");
}

function testWritebackRejectsFormulaMergedProtectedAndHiddenTargets() {
  const item = {
    itemId: "target-1", address: "$C$2", originalValue: "原值", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const results = [{ itemId: "target-1", status: "completed", valueType: "text", value: "新值" }];

  // Formula target
  const formulaCell = makeCell("原值");
  formulaCell.HasFormula = true;
  formulaCell.Formula = "=A1";
  assert.throws(
    () => helpers.writeExcelSmartFillCells([item], results, () => formulaCell),
    /公式|合并|受保护|隐藏/
  );

  // Merged cell
  const mergedCell = makeCell("原值");
  mergedCell.MergeCells = true;
  assert.throws(
    () => helpers.writeExcelSmartFillCells([item], results, () => mergedCell),
    /公式|合并|受保护|隐藏/
  );

  // Protected cell
  const protectedCell = makeCell("原值");
  protectedCell.Locked = true;
  protectedCell.Worksheet = { ProtectContents: true };
  assert.throws(
    () => helpers.writeExcelSmartFillCells([item], results, () => protectedCell),
    /公式|合并|受保护|隐藏/
  );

  // Hidden cell
  const hiddenCell = makeCell("原值");
  hiddenCell.Hidden = true;
  assert.throws(
    () => helpers.writeExcelSmartFillCells([item], results, () => hiddenCell),
    /公式|合并|受保护|隐藏/
  );
}

function testDateAndBooleanTreatedAsText() {
  const item = {
    itemId: "target-1", address: "$C$2", originalValue: "", originalValueType: "blank",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const dateCell = makeCell("");
  helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "2026-08-31" }],
    () => dateCell
  );
  assert.strictEqual(dateCell.Value2, "2026-08-31");

  const boolCell = makeCell("");
  helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "true" }],
    () => boolCell
  );
  assert.strictEqual(boolCell.Value2, "true");
}

function testDateAndBooleanTargetValidationAndRollback() {
  // Test boolean cell target
  const boolTargetItem = {
    itemId: "target-1", address: "$C$2", row: 2, column: 3,
    originalValue: "true", originalValueType: "boolean",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  assert.strictEqual(helpers.validateExcelSmartFillTarget({ items: [boolTargetItem] }), true);

  const boolSummary = helpers.calculateExcelSmartFillDraftsSummary(
    [{ itemId: "target-1", value: "已确认", valueType: "text", selected: true }],
    [boolTargetItem]
  );
  assert.strictEqual(boolSummary.overwriteCount, 1);
  assert.strictEqual(boolSummary.writableCount, 1);

  const boolCell = makeCell(true);
  boolCell.Text = "true";
  const boolWriteResult = helpers.writeExcelSmartFillCells(
    [boolTargetItem],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "已确认" }],
    () => boolCell
  );
  assert.strictEqual(boolWriteResult.writtenCount, 1);
  assert.strictEqual(boolCell.Value2, "已确认");
  assert.strictEqual(typeof boolCell.Value2, "string");

  // Test date cell target
  const dateTargetItem = {
    itemId: "target-1", address: "$C$2", row: 2, column: 3,
    originalValue: "2024-08-31", originalValueType: "date",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  assert.strictEqual(helpers.validateExcelSmartFillTarget({ items: [dateTargetItem] }), true);

  const dateSummary = helpers.calculateExcelSmartFillDraftsSummary(
    [{ itemId: "target-1", value: "2026-08-31", valueType: "text", selected: true }],
    [dateTargetItem]
  );
  assert.strictEqual(dateSummary.overwriteCount, 1);
  assert.strictEqual(dateSummary.writableCount, 1);

  const dateCell = makeCell(45535);
  dateCell.NumberFormat = "yyyy-mm-dd";
  dateCell.Text = "2024-08-31";
  const dateWriteResult = helpers.writeExcelSmartFillCells(
    [dateTargetItem],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "2026-08-31" }],
    () => dateCell
  );
  assert.strictEqual(dateWriteResult.writtenCount, 1);
  assert.strictEqual(dateCell.Value2, "2026-08-31");
  assert.strictEqual(typeof dateCell.Value2, "string");

  // Test rollback on boolean and date cells when subsequent write fails
  let boolVal = true;
  const rollbackBoolCell = {
    get Value2() { return boolVal; },
    set Value2(v) { boolVal = v; },
    get Text() { return String(boolVal); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };
  const failingSecondCell = makeCell("原值2");
  Object.defineProperty(failingSecondCell, "Value2", {
    get() { return "原值2"; },
    set() { throw new Error("mock write failure"); }
  });

  assert.throws(
    () => helpers.writeExcelSmartFillCells(
      [
        boolTargetItem,
        { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
      ],
      [
        { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
        { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
      ],
      (item) => item.itemId === "target-1" ? rollbackBoolCell : failingSecondCell
    ),
    /mock write failure/
  );
  assert.strictEqual(boolVal, true);
}

function testUnselectedConflictDoesNotBlockSelectedWrites() {
  const item1 = {
    itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const item2 = {
    itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };

  const cell1 = makeCell("原值1");
  const cell2Changed = makeCell("在Excel中已修改");

  // 1. Conflict detection filtered by active writable candidate ("target-1" only)
  const conflictReport = helpers.detectExcelSmartFillConflicts(
    [item1, item2],
    (item) => item.itemId === "target-1" ? cell1 : cell2Changed,
    ["target-1"]
  );
  assert.strictEqual(conflictReport.hasConflict, false);

  // 2. Writing item1 while item2 is unselected/skipped does not fail or inspect cell2
  const writeResult = helpers.writeExcelSmartFillCells(
    [item1, item2],
    [
      { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
      { itemId: "target-2", status: "insufficient_information", valueType: "text", value: "" }
    ],
    (item) => item.itemId === "target-1" ? cell1 : cell2Changed
  );
  assert.strictEqual(writeResult.writtenCount, 1);
  assert.strictEqual(writeResult.skippedCount, 1);
  assert.strictEqual(cell1.Value2, "新值1");
  assert.strictEqual(cell2Changed.Value2, "在Excel中已修改");
}

function testWritebackDetectsSnapshotConflict() {
  assert.strictEqual(typeof helpers.detectExcelSmartFillConflicts, "function");
  const item = {
    itemId: "target-1", address: "$C$2", originalValue: "原值", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const changedCell = makeCell("已在Excel中被修改");
  const result = helpers.detectExcelSmartFillConflicts([item], () => changedCell);
  assert.strictEqual(result.hasConflict, true);
  assert.strictEqual(result.conflicts.length, 1);
  assert.strictEqual(result.conflicts[0].itemId, "target-1");
  assert.strictEqual(result.conflicts[0].reason, "content_changed");
}

function testMultiCellWriteFailureTriggersReverseRollback() {
  const rollbackOrder = [];
  let cell1Val = "原值1";
  let cell2Val = "原值2";
  let cell3Written = false;
  let cell4Written = false;

  const cell1 = {
    get Value2() { return cell1Val; },
    set Value2(v) {
      if (v === "原值1") rollbackOrder.push("target-1");
      cell1Val = v;
    },
    get Text() { return String(cell1Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const cell2 = {
    get Value2() { return cell2Val; },
    set Value2(v) {
      if (v === "原值2") rollbackOrder.push("target-2");
      cell2Val = v;
    },
    get Text() { return String(cell2Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const cell3 = {
    get Value2() { return "原值3"; },
    set Value2(v) {
      cell3Written = true;
      throw new Error("mock write failure on item 3");
    },
    get Text() { return "原值3"; },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const cell4 = {
    get Value2() { return "原值4"; },
    set Value2(v) { cell4Written = true; },
    get Text() { return "原值4"; },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-3", address: "$C$4", row: 4, column: 3, originalValue: "原值3", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-4", address: "$C$5", row: 5, column: 3, originalValue: "原值4", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" },
    { itemId: "target-3", status: "completed", valueType: "text", value: "新值3" },
    { itemId: "target-4", status: "completed", valueType: "text", value: "新值4" }
  ];

  const cellMap = { "target-1": cell1, "target-2": cell2, "target-3": cell3, "target-4": cell4 };

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => cellMap[item.itemId]),
    (err) => {
      assert.ok(err.message.includes("智能填写写回失败，已尝试恢复已写入单元格"));
      assert.ok(err.message.includes("mock write failure on item 3"));
      assert.ok(!err.message.includes("以下地址需要人工核对"), "Compensation succeeded, so no manual review addresses should be reported");
      return true;
    }
  );

  // Verify reverse rollback order (target-2 first, then target-1)
  assert.deepStrictEqual(rollbackOrder, ["target-2", "target-1"]);
  assert.strictEqual(cell1Val, "原值1");
  assert.strictEqual(cell2Val, "原值2");
  assert.strictEqual(cell3Written, true);
  assert.strictEqual(cell4Written, false, "Cell 4 must not be written to after cell 3 failure");
}

function testCompensationFailureDisclosesAccurateManualReviewAddresses() {
  let cell1Val = "原值1";
  let cell2Val = "原值2";

  // Cell 1 fails during rollback
  const cell1 = {
    get Value2() { return cell1Val; },
    set Value2(v) {
      if (v === "新值1") {
        cell1Val = v;
      } else {
        throw new Error("mock rollback error on cell 1");
      }
    },
    get Text() { return String(cell1Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  // Cell 2 rolls back successfully
  const cell2 = {
    get Value2() { return cell2Val; },
    set Value2(v) { cell2Val = v; },
    get Text() { return String(cell2Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  // Cell 3 throws on write
  const cell3 = {
    get Value2() { return "原值3"; },
    set Value2(v) { throw new Error("mock write failure on item 3"); },
    get Text() { return "原值3"; },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-3", address: "$C$4", row: 4, column: 3, originalValue: "原值3", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" },
    { itemId: "target-3", status: "completed", valueType: "text", value: "新值3" }
  ];

  const cellMap = { "target-1": cell1, "target-2": cell2, "target-3": cell3 };

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => cellMap[item.itemId]),
    (err) => {
      assert.ok(err.message.includes("智能填写写回失败，已尝试恢复已写入单元格；以下地址需要人工核对：$C$2"));
      assert.ok(!err.message.includes("$C$3"), "Cell 2 was restored successfully and should not appear in manual review list");
      return true;
    }
  );
}

function testBlankCellRollbackRestoresBlankSnapshot() {
  let cell1Val = null;
  let cell1Text = "";

  const blankCell = {
    get Value2() { return cell1Val; },
    set Value2(v) {
      cell1Val = v;
      cell1Text = v == null ? "" : String(v);
    },
    get Text() { return cell1Text; },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const failingCell = makeCell("原值2");
  Object.defineProperty(failingCell, "Value2", {
    get() { return "原值2"; },
    set() { throw new Error("mock write failure on cell 2"); }
  });

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "", originalValueType: "blank", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新写入文本" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
  ];

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => item.itemId === "target-1" ? blankCell : failingCell),
    (err) => {
      assert.ok(err.message.includes("智能填写写回失败，已尝试恢复已写入单元格"));
      assert.ok(!err.message.includes("以下地址需要人工核对"), "Blank cell should restore cleanly without reporting failure");
      return true;
    }
  );

  assert.strictEqual(blankCell.Text, "");
  assert.strictEqual(blankCell.Value2 == null || blankCell.Value2 === "", true);
}

function testPostWriteVerificationMismatchTriggersRollback() {
  let cell1Val = "原值1";
  let cell2Val = "原值2";
  const corruptedCell2 = {
    get Value2() { return cell2Val; },
    set Value2(v) { cell2Val = v; },
    get Text() { return cell2Val === "新值2" ? "corrupted_text" : String(cell2Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const cell1 = {
    get Value2() { return cell1Val; },
    set Value2(v) { cell1Val = v; },
    get Text() { return String(cell1Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
  ];

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => item.itemId === "target-1" ? cell1 : corruptedCell2),
    (err) => {
      assert.ok(err.message.includes("智能填写写回失败，已尝试恢复已写入单元格"));
      assert.ok(err.message.includes("写回后未能核对目标地址 $C$3"));
      assert.ok(!err.message.includes("以下地址需要人工核对"), "Both cells restored successfully during compensation");
      return true;
    }
  );

  // cell 1 and cell 2 both rolled back
  assert.strictEqual(cell1Val, "原值1");
  assert.strictEqual(cell2Val, "原值2");
}

function testPostRollbackVerificationMismatchDisclosesManualReviewAddress() {
  let cell1Val = "原值1";
  let cell1CorruptedAfterRollback = false;

  const cell1 = {
    get Value2() { return cell1Val; },
    set Value2(v) {
      if (v === "新值1") {
        cell1Val = v;
      } else {
        // Rollback sets it back, but cell state becomes corrupt / formula
        cell1Val = v;
        cell1CorruptedAfterRollback = true;
      }
    },
    get Text() { return cell1CorruptedAfterRollback ? "tampered_after_rollback" : String(cell1Val); },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const failingCell2 = makeCell("原值2");
  Object.defineProperty(failingCell2, "Value2", {
    get() { return "原值2"; },
    set() { throw new Error("mock write failure on cell 2"); }
  });

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { itemId: "target-2", address: "$C$3", row: 3, column: 3, originalValue: "原值2", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
  ];

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => item.itemId === "target-1" ? cell1 : failingCell2),
    (err) => {
      assert.ok(err.message.includes("智能填写写回失败，已尝试恢复已写入单元格；以下地址需要人工核对：$C$2"));
      return true;
    }
  );
}

function testPreflightRejectionOnAnyItemPreventsAllWrites() {
  let cell1Written = false;
  const cell1 = {
    get Value2() { return "原值1"; },
    set Value2(v) { cell1Written = true; },
    get Text() { return "原值1"; },
    Formula: "", HasFormula: false, MergeCells: false, Locked: false, Hidden: false
  };

  const formulaItem = {
    itemId: "target-2", address: "$C$3", row: 3, column: 3,
    originalValue: "=A1+B1", originalValueType: "formula", originalFormula: "=A1+B1",
    isFormula: true, isMerged: false, isProtected: false, isHidden: false
  };
  const formulaCell = makeCell("=A1+B1");
  formulaCell.HasFormula = true;

  const items = [
    { itemId: "target-1", address: "$C$2", row: 2, column: 3, originalValue: "原值1", originalValueType: "text", originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    formulaItem
  ];

  const results = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
    { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
  ];

  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, results, (item) => item.itemId === "target-1" ? cell1 : formulaCell),
    /公式|合并|受保护|隐藏/
  );

  assert.strictEqual(cell1Written, false, "Preflight must prevent any writes from starting");
}

testFormulaLikeValuesRemainLiteral();
testBlankCellWritesNumberWithoutChangingNumberFormat();
testBlankCellWritesFormulaLikeTextAsLiteral();
testInsufficientItemsAreSkippedWithoutWriting();
testWritebackRejectsFormulaMergedProtectedAndHiddenTargets();
testDateAndBooleanTreatedAsText();
testDateAndBooleanTargetValidationAndRollback();
testUnselectedConflictDoesNotBlockSelectedWrites();
testWritebackDetectsSnapshotConflict();
testMultiCellWriteFailureTriggersReverseRollback();
testCompensationFailureDisclosesAccurateManualReviewAddresses();
testBlankCellRollbackRestoresBlankSnapshot();
testPostWriteVerificationMismatchTriggersRollback();
testPostRollbackVerificationMismatchDisclosesManualReviewAddress();
testPreflightRejectionOnAnyItemPreventsAllWrites();
console.log("Excel smart fill writeback tests passed");
