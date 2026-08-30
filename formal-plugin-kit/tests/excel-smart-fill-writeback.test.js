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

testFormulaLikeValuesRemainLiteral();
testInsufficientItemsAreSkippedWithoutWriting();

console.log("Excel smart fill writeback tests passed");
