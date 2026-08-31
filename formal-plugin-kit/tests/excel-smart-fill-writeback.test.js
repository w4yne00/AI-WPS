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

testFormulaLikeValuesRemainLiteral();
testBlankCellWritesNumberWithoutChangingNumberFormat();
testBlankCellWritesFormulaLikeTextAsLiteral();
testInsufficientItemsAreSkippedWithoutWriting();
testWritebackRejectsFormulaMergedProtectedAndHiddenTargets();
testDateAndBooleanTreatedAsText();
testDateAndBooleanTargetValidationAndRollback();
testUnselectedConflictDoesNotBlockSelectedWrites();
testWritebackDetectsSnapshotConflict();

console.log("Excel smart fill writeback tests passed");
