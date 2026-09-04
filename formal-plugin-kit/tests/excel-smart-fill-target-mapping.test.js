const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function buildRange(address, values, extras) {
  const rows = values.length;
  const columns = values[0].length;
  const cells = {};
  const options = extras || {};
  const startRow = options.startRow || 1;
  const startColumn = options.startColumn || 1;

  values.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
    const sheetRow = startRow + rowIndex;
    const sheetColumn = startColumn + columnIndex;
    const colLetters = String.fromCharCode(64 + sheetColumn);
    const cellAddress = `$${colLetters}$${sheetRow}`;
    let currentVal = value;
    const cellObj = {
      Address: cellAddress,
      Formula: options.formula || "",
      HasFormula: Boolean(options.hasFormula),
      MergeCells: Boolean(options.mergeCells),
      Locked: Boolean(options.locked),
      Hidden: Boolean(options.hidden),
      Row: sheetRow,
      Column: sheetColumn,
      EntireRow: { Hidden: Boolean(options.rowHidden) },
      EntireColumn: { Hidden: Boolean(options.colHidden) },
      get Text() {
        return currentVal == null ? "" : String(currentVal);
      },
      set Text(v) {
        currentVal = v;
      },
      get Value2() {
        return currentVal;
      },
      set Value2(v) {
        currentVal = v;
      }
    };
    cells[`${sheetRow},${sheetColumn}`] = cellObj;
    cells[`${rowIndex + 1},${columnIndex + 1}`] = cellObj;
  }));

  return {
    Address: address,
    Worksheet: { Name: options.sheetName || "客户表" },
    Rows: { Count: rows },
    Columns: { Count: columns },
    Areas: { Count: options.areaCount || 1 },
    Cells: {
      Item(row, column) {
        return cells[`${row},${column}`] || null;
      }
    }
  };
}

function testInspectTargetSelectionValidatesSheetContinuousAndCount() {
  assert.strictEqual(typeof helpers.inspectExcelSmartFillTargetSelection, "function");

  const source = {
    sheetName: "客户表",
    address: "$A$1:$C$11",
    rowCount: 10
  };
  const previewItems = Array.from({ length: 10 }, (_, i) => ({
    itemId: `sf_${String(i + 1).padStart(32, "0")}`,
    status: "completed"
  }));
  const draftItems = previewItems.map((item) => ({
    itemId: item.itemId,
    selected: true,
    value: "填写值",
    valueType: "text"
  }));

  // 1. Cross-sheet target must be rejected
  const crossSheetRange = buildRange("$D$2:$D$11", Array(10).fill([""]), {
    sheetName: "其他表",
    startRow: 2,
    startColumn: 4
  });
  const crossInspection = helpers.inspectExcelSmartFillTargetSelection(crossSheetRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(crossInspection.ok, false);
  assert.match(crossInspection.error, /同一工作表/);

  // 2. Multi-column target must be rejected
  const multiColRange = buildRange("$D$2:$E$11", Array(10).fill(["", ""]), {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4
  });
  const multiColInspection = helpers.inspectExcelSmartFillTargetSelection(multiColRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(multiColInspection.ok, false);
  assert.match(multiColInspection.error, /单列/);

  // 3. Count mismatch must be rejected
  const shortRange = buildRange("$D$2:$D$6", Array(5).fill([""]), {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4
  });
  const shortInspection = helpers.inspectExcelSmartFillTargetSelection(shortRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(shortInspection.ok, false);
  assert.match(shortInspection.error, /数量.*不一致/);

  // 4. Overlapping target with source must be rejected
  const overlapRange = buildRange("$A$2:$A$11", Array(10).fill([""]), {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 1
  });
  const overlapInspection = helpers.inspectExcelSmartFillTargetSelection(overlapRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(overlapInspection.ok, false);
  assert.match(overlapInspection.error, /重叠/);

  // 5. Valid target on same sheet, non-overlapping single column with matching count
  const validRange = buildRange("$D$2:$D$11", Array(10).fill([""]), {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4
  });
  const validInspection = helpers.inspectExcelSmartFillTargetSelection(validRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(validInspection.ok, true);
  assert.strictEqual(validInspection.address, "D2:D11");
  assert.strictEqual(validInspection.cellCount, 10);
  assert.strictEqual(validInspection.writableCount, 10);
  assert.strictEqual(validInspection.overwriteCount, 0);
  assert.strictEqual(validInspection.summary, "写入位置：D2:D11 · 10 个单元格 · 将写入 10 项");
  assert.strictEqual(validInspection.error, "");
}

function testInspectTargetSelectionRejectsFormulaMergedHiddenLocked() {
  const source = { sheetName: "客户表", address: "$A$1:$C$3", rowCount: 2 };
  const previewItems = [
    { itemId: "sf_001", status: "completed" },
    { itemId: "sf_002", status: "completed" }
  ];
  const draftItems = [
    { itemId: "sf_001", selected: true, value: "1", valueType: "text" },
    { itemId: "sf_002", selected: true, value: "2", valueType: "text" }
  ];

  // Formula cell
  const formulaRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    hasFormula: true,
    formula: "=A2"
  });
  const formulaInsp = helpers.inspectExcelSmartFillTargetSelection(formulaRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(formulaInsp.ok, false);
  assert.match(formulaInsp.error, /公式/);

  // Merged cell
  const mergedRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    mergeCells: true
  });
  const mergedInsp = helpers.inspectExcelSmartFillTargetSelection(mergedRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(mergedInsp.ok, false);
  assert.match(mergedInsp.error, /合并/);

  // Hidden row
  const hiddenRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    rowHidden: true
  });
  const hiddenInsp = helpers.inspectExcelSmartFillTargetSelection(hiddenRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(hiddenInsp.ok, false);
  assert.match(hiddenInsp.error, /隐藏/);

  // Locked cell
  const lockedRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    locked: true
  });
  const lockedInsp = helpers.inspectExcelSmartFillTargetSelection(lockedRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(lockedInsp.ok, false);
  assert.match(lockedInsp.error, /受保护/);
}

function testTargetMappingTopToBottomWithEmptySlotsForExcludedOrFailed() {
  assert.strictEqual(typeof helpers.mapExcelSmartFillPreviewToTarget, "function");

  const source = { sheetName: "客户表", address: "$A$1:$C$4", rowCount: 3 };
  const previewItems = [
    { itemId: "sf_001", status: "completed" },
    { itemId: "sf_002", status: "failed" },
    { itemId: "sf_003", status: "completed" }
  ];
  const draftItems = [
    { itemId: "sf_001", selected: true, value: "第一项", valueType: "text" },
    { itemId: "sf_002", selected: false, value: "", valueType: "text" },
    { itemId: "sf_003", selected: true, value: "第三项", valueType: "text" }
  ];

  const targetRange = buildRange("$D$2:$D$4", [["原D2"], ["原D3"], ["原D4"]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4
  });

  const mapping = helpers.mapExcelSmartFillPreviewToTarget(targetRange, {
    source,
    previewItems,
    draftItems
  });

  assert.strictEqual(mapping.items.length, 3);
  assert.strictEqual(mapping.items[0].itemId, "sf_001");
  assert.strictEqual(mapping.items[0].address, "$D$2");
  assert.strictEqual(mapping.items[0].row, 2);
  assert.strictEqual(mapping.items[0].column, 4);
  assert.strictEqual(mapping.items[0].originalValue, "原D2");

  assert.strictEqual(mapping.items[1].itemId, "sf_002");
  assert.strictEqual(mapping.items[1].address, "$D$3");
  assert.strictEqual(mapping.items[1].originalValue, "原D3");

  assert.strictEqual(mapping.items[2].itemId, "sf_003");
  assert.strictEqual(mapping.items[2].address, "$D$4");
  assert.strictEqual(mapping.items[2].originalValue, "原D4");

  // Perform write using writeExcelSmartFillCells
  const writeResults = [
    { itemId: "sf_001", status: "completed", valueType: "text", value: "新D2" },
    { itemId: "sf_002", status: "failed", valueType: "text", value: "" },
    { itemId: "sf_003", status: "completed", valueType: "text", value: "新D4" }
  ];

  const writeRes = helpers.writeExcelSmartFillCells(
    mapping.items,
    writeResults,
    (item) => targetRange.Cells.Item(item.row, item.column)
  );

  assert.strictEqual(writeRes.writtenCount, 2);
  assert.strictEqual(writeRes.skippedCount, 1);

  // D2 is written, D3 is untouched (kept original value), D4 is written (not shifted!)
  assert.strictEqual(targetRange.Cells.Item(2, 4).Value2, "新D2");
  assert.strictEqual(targetRange.Cells.Item(3, 4).Value2, "原D3");
  assert.strictEqual(targetRange.Cells.Item(4, 4).Value2, "新D4");
}

function testOverwriteCountCalculationForActiveWritableItemsOnly() {
  const source = { sheetName: "客户表", address: "$A$1:$C$4", rowCount: 3 };
  const previewItems = [
    { itemId: "sf_001", status: "completed" },
    { itemId: "sf_002", status: "completed" },
    { itemId: "sf_003", status: "completed" }
  ];
  // Item 1 is selected and overwrites "已有文本"
  // Item 2 is UNSELECTED (excluded), so even though target cell has "已有文本2", it won't overwrite!
  // Item 3 is selected and target cell is blank ""
  const draftItems = [
    { itemId: "sf_001", selected: true, value: "新值1", valueType: "text" },
    { itemId: "sf_002", selected: false, value: "新值2", valueType: "text" },
    { itemId: "sf_003", selected: true, value: "新值3", valueType: "text" }
  ];

  const targetRange = buildRange("$D$2:$D$4", [["已有文本1"], ["已有文本2"], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4
  });

  const inspection = helpers.inspectExcelSmartFillTargetSelection(targetRange, {
    source,
    previewItems,
    draftItems
  });

  assert.strictEqual(inspection.ok, true);
  assert.strictEqual(inspection.cellCount, 3);
  assert.strictEqual(inspection.writableCount, 2);
  assert.strictEqual(inspection.overwriteCount, 1);
  assert.strictEqual(inspection.summary, "写入位置：D2:D4 · 3 个单元格 · 将写入 2 项");
}

function testTaskpaneIntegratesTargetLiveInspectionAndWrite() {
  assert.ok(js.includes("inspectExcelSmartFillTargetSelection"), "taskpane.js must use inspectExcelSmartFillTargetSelection");
  assert.ok(js.includes("mapExcelSmartFillPreviewToTarget"), "taskpane.js must use mapExcelSmartFillPreviewToTarget");
  assert.ok(js.includes("写入位置："), "taskpane.js must format target summary with 写入位置：");
  assert.ok(!/function tryRebindSmartFillTarget[\s\S]{0,80}return false/.test(js), "tryRebindSmartFillTarget must not just return false");
}

testInspectTargetSelectionValidatesSheetContinuousAndCount();
testInspectTargetSelectionRejectsFormulaMergedHiddenLocked();
testTargetMappingTopToBottomWithEmptySlotsForExcludedOrFailed();
testOverwriteCountCalculationForActiveWritableItemsOnly();
testTaskpaneIntegratesTargetLiveInspectionAndWrite();

console.log("Excel smart fill target mapping tests passed");
