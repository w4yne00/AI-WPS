const assert = require("assert");

const helpers = require("../wps-ai-assistant-et_1.0.0/taskpane-helpers.js");

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
testWritebackDetectsSnapshotConflict();

console.log("Excel smart fill writeback tests passed");
