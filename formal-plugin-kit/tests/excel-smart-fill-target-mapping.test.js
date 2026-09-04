const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function buildRange(address, values, extras) {
  const rows = values.length;
  const columns = values[0].length;
  const cells = {};
  const cellsByAddress = {};
  const options = extras || {};
  const startRow = options.startRow || 1;
  const startColumn = options.startColumn || 1;

  const worksheetObj = {
    Name: options.sheetName || "客户表",
    ProtectContents: Boolean(options.protectContents),
    Range(addr) {
      return cellsByAddress[addr] || null;
    },
    getRange(addr) {
      return cellsByAddress[addr] || null;
    }
  };

  values.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
    const sheetRow = startRow + rowIndex;
    const sheetColumn = startColumn + columnIndex;
    const colLetters = String.fromCharCode(64 + sheetColumn);
    const cellAddress = `$${colLetters}$${sheetRow}`;
    let currentVal = value;
    const cellObj = {
      Address: cellAddress,
      Worksheet: worksheetObj,
      Row: sheetRow,
      Column: sheetColumn,
      EntireRow: { Hidden: Boolean(options.rowHidden) },
      EntireColumn: { Hidden: Boolean(options.colHidden) },
      Hidden: Boolean(options.hidden),
      get Formula() {
        if (options.throwOnProperty === "Formula") throw new Error("Mock COM error on Formula");
        return options.formula || "";
      },
      get HasFormula() {
        if (options.throwOnProperty === "HasFormula") throw new Error("Mock COM error on HasFormula");
        return Boolean(options.hasFormula);
      },
      get MergeCells() {
        if (options.throwOnProperty === "MergeCells") throw new Error("Mock COM error on MergeCells");
        return Boolean(options.mergeCells);
      },
      get Locked() {
        if (options.throwOnProperty === "Locked") throw new Error("Mock COM error on Locked");
        return typeof options.locked !== "undefined" ? Boolean(options.locked) : true;
      },
      get Text() {
        if (options.throwOnProperty === "Text") throw new Error("Mock COM error on Text");
        if (options.formattedTexts && options.formattedTexts[cellAddress]) {
          return options.formattedTexts[cellAddress];
        }
        return currentVal == null ? "" : String(currentVal);
      },
      set Text(v) {
        currentVal = v;
      },
      get Value2() {
        if (options.throwOnProperty === "Value2") throw new Error("Mock COM error on Value2");
        return currentVal;
      },
      set Value2(v) {
        if (options.failOnNewValue && v !== "原D2" && v !== "原D3" && v !== "") {
          throw new Error("Mock write failure on " + cellAddress);
        }
        if (options.throwOnWrite) {
          throw new Error("Mock write failure on " + cellAddress);
        }
        currentVal = v;
      }
    };
    cells[`${sheetRow},${sheetColumn}`] = cellObj;
    cells[`${rowIndex + 1},${columnIndex + 1}`] = cellObj;
    cellsByAddress[cellAddress] = cellObj;
    cellsByAddress[`${colLetters}${sheetRow}`] = cellObj;
    cellsByAddress[`$${colLetters}${sheetRow}`] = cellObj;
  }));

  const rangeObj = {
    Address: address,
    Worksheet: worksheetObj,
    Rows: { Count: rows },
    Columns: { Count: columns },
    Areas: { Count: options.areaCount || 1 },
    Cells: {
      Item(row, column) {
        return cells[`${row},${column}`] || null;
      }
    }
  };

  return rangeObj;
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

  // Critical 1: Sheet unprotected (ProtectContents: false), cell locked (Locked: true)
  // In Excel, cells are locked by default; when worksheet is unprotected, it should NOT be rejected!
  const normalLockedRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    protectContents: false,
    locked: true
  });
  const normalLockedInsp = helpers.inspectExcelSmartFillTargetSelection(normalLockedRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(normalLockedInsp.ok, true, "Unlocked sheet with default locked cells must be writable");

  // Critical 1: Sheet protected (ProtectContents: true), cell locked (Locked: true)
  // Must be rejected as protected!
  const protectedSheetRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    protectContents: true,
    locked: true
  });
  const protectedSheetInsp = helpers.inspectExcelSmartFillTargetSelection(protectedSheetRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(protectedSheetInsp.ok, false);
  assert.match(protectedSheetInsp.error, /受保护/);

  // Critical 1: Sheet protected (ProtectContents: true), but cell unlocked (Locked: false)
  // Must be allowed!
  const unlockedCellProtectedSheetRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    protectContents: true,
    locked: false
  });
  const unlockedCellInsp = helpers.inspectExcelSmartFillTargetSelection(unlockedCellProtectedSheetRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(unlockedCellInsp.ok, true, "Unlocked cells on a protected sheet must be writable");

  // Important 4: Cell getter throwing error (COM failure) fails closed safely
  const getterErrorRange = buildRange("$D$2:$D$3", [[""], [""]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    throwOnProperty: "HasFormula"
  });
  const getterErrorInsp = helpers.inspectExcelSmartFillTargetSelection(getterErrorRange, {
    source,
    previewItems,
    draftItems
  });
  assert.strictEqual(getterErrorInsp.ok, false);
  assert.match(getterErrorInsp.error, /无法安全读取目标单元格状态/);

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
    draftItems,
    jobId: "job_001",
    workbookId: "wb_001",
    sourceSnapshotHash: "hash_001",
    resultRevision: 1
  });

  assert.strictEqual(mapping.items.length, 3);
  assert.strictEqual(mapping.items[0].itemId, "sf_001");
  assert.strictEqual(mapping.items[0].address, "$D$2");
  assert.strictEqual(mapping.items[0].row, 2);
  assert.strictEqual(mapping.items[0].column, 4);
  assert.strictEqual(mapping.items[0].originalValue, "原D2");
  assert.ok(mapping.items[0].originalSnapshot, "originalSnapshot must be saved on item");

  assert.strictEqual(mapping.items[1].itemId, "sf_002");
  assert.strictEqual(mapping.items[1].address, "$D$3");
  assert.strictEqual(mapping.items[1].originalValue, "原D3");

  assert.strictEqual(mapping.items[2].itemId, "sf_003");
  assert.strictEqual(mapping.items[2].address, "$D$4");
  assert.strictEqual(mapping.items[2].originalValue, "原D4");

  // Verify commitContext is created
  assert.ok(mapping.commitContext, "commitContext must be returned");
  assert.strictEqual(mapping.commitContext.targetAddress, "$D$2:$D$4");
  assert.strictEqual(mapping.commitContext.itemCount, 3);

  // Perform write using writeExcelSmartFillCells
  const writeResults = [
    { itemId: "sf_001", status: "completed", valueType: "text", value: "新D2" },
    { itemId: "sf_002", status: "failed", valueType: "text", value: "", skip: true },
    { itemId: "sf_003", status: "completed", valueType: "text", value: "新D4" }
  ];

  const writeRes = helpers.writeExcelSmartFillCells(
    mapping.items,
    writeResults,
    (item) => targetRange.Cells.Item(item.row, item.column),
    { commitContext: mapping.commitContext }
  );

  assert.strictEqual(writeRes.writtenCount, 2);
  assert.strictEqual(writeRes.skippedCount, 1);

  // D2 is written, D3 is untouched (kept original value), D4 is written (not shifted!)
  assert.strictEqual(targetRange.Cells.Item(2, 4).Value2, "新D2");
  assert.strictEqual(targetRange.Cells.Item(3, 4).Value2, "原D3");
  assert.strictEqual(targetRange.Cells.Item(4, 4).Value2, "新D4");
}

function testOverwriteCountCalculationForActiveWritableItemsOnly() {
  const source = { sheetName: "客户表", address: "$A$1:$C$6", rowCount: 5 };
  const previewItems = [
    { itemId: "sf_001", status: "completed" },
    { itemId: "sf_002", status: "completed" },
    { itemId: "sf_003", status: "failed" },
    { itemId: "sf_004", status: "insufficient_context" },
    { itemId: "sf_005", status: "completed" }
  ];
  // Item 1: completed, selected, target cell has "已有文本1" -> writable & overwrites
  // Item 2: completed, UNSELECTED (selected: false), target has "已有文本2" -> not writable, not overwrite
  // Item 3: failed, selected: true, but draft has value "草稿3", target has "已有文本3" -> NOT writable, NOT overwrite (Important 2)
  // Item 4: insufficient_context, selected: true, draft has value "草稿4", target has "已有文本4" -> NOT writable, NOT overwrite (Important 2)
  // Item 5: completed, selected: true, target cell is blank "" -> writable, not overwrite
  const draftItems = [
    { itemId: "sf_001", selected: true, value: "新值1", valueType: "text" },
    { itemId: "sf_002", selected: false, value: "新值2", valueType: "text" },
    { itemId: "sf_003", selected: true, value: "草稿3", valueType: "text" },
    { itemId: "sf_004", selected: true, value: "草稿4", valueType: "text" },
    { itemId: "sf_005", selected: true, value: "新值5", valueType: "text" }
  ];

  const targetRange = buildRange(
    "$D$2:$D$6",
    [["已有文本1"], ["已有文本2"], ["已有文本3"], ["已有文本4"], [""]],
    {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4
    }
  );

  const inspection = helpers.inspectExcelSmartFillTargetSelection(targetRange, {
    source,
    previewItems,
    draftItems
  });

  assert.strictEqual(inspection.ok, true);
  assert.strictEqual(inspection.cellCount, 5);
  assert.strictEqual(inspection.writableCount, 2, "Only items 1 and 5 should be counted as writable");
  assert.strictEqual(inspection.overwriteCount, 1, "Only item 1 should be counted as overwriting");
  assert.strictEqual(inspection.summary, "写入位置：D2:D6 · 5 个单元格 · 将写入 2 项");
}

function testFormattedCellValuesDoNotTriggerConflict() {
  // Important 1: Target cell with formatted number or date does not falsely trigger conflict
  const source = { sheetName: "客户表", address: "$A$1:$C$3", rowCount: 2 };
  const previewItems = [
    { itemId: "sf_001", status: "completed" },
    { itemId: "sf_002", status: "completed" }
  ];
  const draftItems = [
    { itemId: "sf_001", selected: true, value: "填1", valueType: "text" },
    { itemId: "sf_002", selected: true, value: "填2", valueType: "text" }
  ];

  const targetRange = buildRange("$D$2:$D$3", [[1234], [5678]], {
    sheetName: "客户表",
    startRow: 2,
    startColumn: 4,
    formattedTexts: {
      "$D$2": "1,234.00",
      "$D$3": "5,678.00"
    }
  });

  const mapping = helpers.mapExcelSmartFillPreviewToTarget(targetRange, {
    source,
    previewItems,
    draftItems,
    jobId: "job_fmt",
    workbookId: "wb_fmt",
    sourceSnapshotHash: "hash_fmt",
    resultRevision: 1
  });

  // Verify initial snapshot preserved
  assert.strictEqual(mapping.items[0].originalSnapshot.rawValue, 1234);
  assert.strictEqual(mapping.items[0].originalSnapshot.text, "1,234.00");

  // Conflict detection before write should pass without conflict
  const preflight = helpers.detectExcelSmartFillConflicts(
    mapping.items,
    (item) => targetRange.Cells.Item(item.row, item.column),
    ["sf_001", "sf_002"]
  );
  assert.strictEqual(preflight.hasConflict, false, "Formatted numeric cell must not trigger conflict when untouched");

  // Now simulate user changing D2 in the worksheet to 9999
  targetRange.Cells.Item(2, 4).Value2 = 9999;
  targetRange.Cells.Item(2, 4).Text = "9,999.00";

  const changedConflict = helpers.detectExcelSmartFillConflicts(
    mapping.items,
    (item) => targetRange.Cells.Item(item.row, item.column),
    ["sf_001", "sf_002"]
  );
  assert.strictEqual(changedConflict.hasConflict, true, "Modified cell must be detected as conflict");
  assert.strictEqual(changedConflict.conflicts[0].itemId, "sf_001");
  assert.strictEqual(changedConflict.conflicts[0].reason, "content_changed");
}

function testCommitContextEnforcesJobAndRevisionBinding() {
  // Important 3: writeExcelSmartFillCells strictly validates commitContext
  const targetItems = [
    { itemId: "sf_001", sheetName: "客户表", address: "$D$2", row: 2, column: 4, originalValue: "", originalSnapshot: { readable: true, rawValue: "", text: "", isFormula: false, formula: "", isMerged: false, isProtected: false, isHidden: false, valueType: "blank" } }
  ];
  const results = [
    { itemId: "sf_001", status: "completed", valueType: "text", value: "新值" }
  ];
  const targetRange = buildRange("$D$2:$D$2", [[""]], { sheetName: "客户表", startRow: 2, startColumn: 4 });
  const getCell = (item) => targetRange.Cells.Item(item.row, item.column);

  const validCommitContext = {
    jobId: "job_001",
    workbookId: "wb_001",
    sourceSnapshotHash: "hash_001",
    resultRevision: 1,
    targetSheetName: "客户表",
    targetAddress: "D2:D2",
    itemCount: 1
  };

  // Valid write succeeds
  const res = helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
    commitContext: validCommitContext
  });
  assert.strictEqual(res.writtenCount, 1);

  // Mismatched itemCount throws
  assert.throws(() => {
    helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
      commitContext: Object.assign({}, validCommitContext, { itemCount: 99 })
    });
  }, /数量/);

  // Missing or empty jobId throws
  assert.throws(() => {
    helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
      commitContext: Object.assign({}, validCommitContext, { jobId: "" })
    });
  }, /任务/);

  // Missing or empty workbookId throws
  assert.throws(() => {
    helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
      commitContext: Object.assign({}, validCommitContext, { workbookId: "" })
    });
  }, /工作簿/);

  // Missing or empty sourceSnapshotHash throws
  assert.throws(() => {
    helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
      commitContext: Object.assign({}, validCommitContext, { sourceSnapshotHash: "" })
    });
  }, /来源快照/);

  // Mismatched targetSheetName throws
  assert.throws(() => {
    helpers.writeExcelSmartFillCells(targetItems, results, getCell, {
      commitContext: Object.assign({}, validCommitContext, { targetSheetName: "其他表" })
    });
  }, /工作表/);
}

function testUncompletedItemsRenderDisabledAndCannotBeWritten() {
  // Important 2: Uncompleted items and conflict items render disabled
  const previewData = {
    items: [
      { itemId: "sf_001", status: "completed", value: "正常值1" },
      { itemId: "sf_002", status: "failed", reason: "error", value: "失败值" },
      { itemId: "sf_003", status: "insufficient_context", reason: "no_data", value: "不足值" },
      { itemId: "sf_004", status: "completed", value: "冲突值" }
    ]
  };
  const targetList = [
    { itemId: "sf_001", address: "$D$2" },
    { itemId: "sf_002", address: "$D$3" },
    { itemId: "sf_003", address: "$D$4" },
    { itemId: "sf_004", address: "$D$5" }
  ];
  const draftList = [
    { itemId: "sf_001", selected: true, value: "正常值1", valueType: "text" },
    { itemId: "sf_002", selected: false, value: "失败值", valueType: "text" },
    { itemId: "sf_003", selected: false, value: "不足值", valueType: "text" },
    { itemId: "sf_004", selected: false, value: "冲突值", valueType: "text", status: "write_conflict" }
  ];

  const htmlOutput = helpers.buildExcelSmartFillEditorPreview(
    previewData,
    targetList,
    draftList,
    { conflicts: { sf_004: "content_changed" } }
  );

  // Completed item sf_001 input and checkbox should be editable (not disabled)
  assert.ok(
    htmlOutput.includes('data-smart-fill-value-input="sf_001"') &&
    !htmlOutput.includes('data-smart-fill-value-input="sf_001" value="正常值1" disabled="disabled"'),
    "Completed item input should be enabled"
  );
  assert.ok(
    htmlOutput.includes('data-smart-fill-select="sf_001"') &&
    !htmlOutput.includes('data-smart-fill-select="sf_001" checked disabled="disabled"'),
    "Completed item checkbox should be enabled"
  );

  // Failed item sf_002 should have disabled inputs/checkboxes
  assert.ok(
    htmlOutput.includes('data-smart-fill-value-input="sf_002" value="失败值" disabled="disabled"'),
    "Failed item input must be disabled"
  );
  assert.ok(
    htmlOutput.includes('data-smart-fill-select="sf_002" disabled="disabled"'),
    "Failed item checkbox must be disabled"
  );

  // Insufficient context item sf_003 should have disabled inputs/checkboxes
  assert.ok(
    htmlOutput.includes('data-smart-fill-value-input="sf_003" value="不足值" disabled="disabled"'),
    "Insufficient context item input must be disabled"
  );
  assert.ok(
    htmlOutput.includes('data-smart-fill-select="sf_003" disabled="disabled"'),
    "Insufficient context item checkbox must be disabled"
  );

  // Conflict item sf_004 should have disabled input/checkbox
  assert.ok(
    htmlOutput.includes('data-smart-fill-value-input="sf_004" value="冲突值" disabled="disabled"'),
    "Conflict item input must be disabled"
  );
  assert.ok(
    htmlOutput.includes('data-smart-fill-select="sf_004" disabled="disabled"'),
    "Conflict item checkbox must be disabled"
  );
}

function createIntegrationEnvironment(customConfig) {
  const cfg = customConfig || {};
  const domElements = {};
  function mockElement(id) {
    if (!domElements[id]) {
      domElements[id] = {
        id: id,
        innerHTML: "",
        textContent: "",
        value: "",
        hidden: false,
        disabled: false,
        className: "",
        classList: {
          add(c) {},
          remove(c) {},
          contains(c) { return false; },
          toggle(c) {}
        },
        style: {},
        attributes: {},
        getAttribute(k) { return this.attributes[k]; },
        setAttribute(k, v) { this.attributes[k] = v; },
        removeAttribute(k) { delete this.attributes[k]; },
        addEventListener() {},
        removeEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; }
      };
    }
    return domElements[id];
  }

  [
    "result-output",
    "status-text",
    "status-line",
    "plain-result",
    "btn-write-smart-fill",
    "smart-fill-editor",
    "taskpane-content",
    "frontend-version-line"
  ].forEach(mockElement);

  const windowMock = {
    WpsAiAssistantHelpers: helpers,
    localStorage: {
      getItem() { return null; },
      setItem() {},
      removeItem() {}
    },
    confirm: typeof cfg.confirm === "function" ? cfg.confirm : (() => true),
    openTaskpane: null,
    __TEST_EXPORTS__: null
  };

  const documentMock = {
    getElementById(id) { return mockElement(id); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement(tag) { return { tag, style: {}, addEventListener() {} }; }
  };

  const appMock = cfg.appMock || {};
  windowMock.Application = appMock;
  windowMock.wps = appMock;
  windowMock.et = appMock;

  const codeToRun = js.replace(
    "if (!isTaskpanePage()) {",
    `window.__TEST_EXPORTS__ = {
      state: state,
      writeExcelSmartFillResult: writeExcelSmartFillResult,
      tryRebindSmartFillTarget: tryRebindSmartFillTarget,
      getSmartFillTargetCell: getSmartFillTargetCell,
      buildExcelSmartFillWriteResults: buildExcelSmartFillWriteResults,
      setSmartFillWriteButtonState: setSmartFillWriteButtonState,
      checkSmartFillPreflight: checkSmartFillPreflight,
      getSmartFillTargetSheet: getSmartFillTargetSheet
    };
    return;
    if (!isTaskpanePage()) {`
  );

  const context = {
    window: windowMock,
    document: documentMock,
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: setInterval,
    clearInterval: clearInterval
  };
  vm.createContext(context);
  vm.runInContext(codeToRun, context);

  return {
    exports: windowMock.__TEST_EXPORTS__,
    domElements: domElements,
    window: windowMock
  };
}

function testTaskpaneBehavioralIntegration() {
  // Subtest 1: Live selection re-read at click moment & successful writeback
  {
    const sourceRange = buildRange("$A$1:$C$4", [
      ["表头A", "表头B", "表头C"],
      ["A2", "B2", "C2"],
      ["A3", "B3", "C3"],
      ["A4", "B4", "C4"]
    ], { sheetName: "客户表", startRow: 1, startColumn: 1 });

    const targetRange1 = buildRange("$D$2:$D$4", [[""], [""], [""]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4
    });

    // At click moment, active selection moved to E2:E4!
    const targetRange2 = buildRange("$E$2:$E$4", [[""], [""], [""]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 5
    });

    const worksheetObj = {
      Name: "客户表",
      ProtectContents: false,
      Range(addr) {
        if (addr === "$A$1:$C$4" || addr === "A1:C4") return sourceRange;
        const fromT2 = targetRange2.Worksheet.Range(addr);
        if (fromT2) return fromT2;
        const fromT1 = targetRange1.Worksheet.Range(addr);
        if (fromT1) return fromT1;
        return null;
      }
    };

    const workbookObj = {
      Name: "测试表.xlsx",
      Worksheets: {
        Item(name) {
          return name === "客户表" ? worksheetObj : null;
        }
      }
    };

    const appMock = {
      ActiveWorkbook: workbookObj,
      ActiveSheet: worksheetObj,
      Selection: targetRange2 // live selection at click moment
    };

    const env = createIntegrationEnvironment({ appMock });
    const { state, writeExcelSmartFillResult } = env.exports;

    // Set up state as if pollExcelSmartFillJob completed
    state.smartFillSource = helpers.extractExcelSmartFillPayload(null, sourceRange, {
      sourceOnly: true,
      sourceSheetName: "客户表"
    }).source;
    state.smartFillTarget = {
      sheetName: "客户表",
      address: "$D$2:$D$4",
      rowCount: 3
    };
    state.smartFillWorkbookId = "测试表.xlsx";
    state.excelSmartFillCompletedJobId = "job_done_001";
    state.excelSmartFillResultRevision = 1;
    state.smartFillResult = {
      items: [
        { itemId: "sf_001", status: "completed", value: "填1", valueType: "text" },
        { itemId: "sf_002", status: "completed", value: "填2", valueType: "text" },
        { itemId: "sf_003", status: "completed", value: "填3", valueType: "text" }
      ]
    };
    state.smartFillDraftItems = [
      { itemId: "sf_001", selected: true, value: "填1", valueType: "text", status: "completed" },
      { itemId: "sf_002", selected: true, value: "填2", valueType: "text", status: "completed" },
      { itemId: "sf_003", selected: true, value: "填3", valueType: "text", status: "completed" }
    ];

    // Execute write
    writeExcelSmartFillResult();

    // 1. Target range 2 (E2:E4) received the write results
    assert.strictEqual(targetRange2.Cells.Item(2, 5).Value2, "填1");
    assert.strictEqual(targetRange2.Cells.Item(3, 5).Value2, "填2");
    assert.strictEqual(targetRange2.Cells.Item(4, 5).Value2, "填3");

    // 2. State was cleaned up on success
    assert.strictEqual(state.smartFillResult, null);
    assert.strictEqual(state.excelSmartFillCompletedJobId, "");
    assert.strictEqual(state.excelSmartFillResultRevision, 0);

    // 3. Status text updated
    assert.strictEqual(env.domElements["status-line"].textContent, "智能填写已写入 3 个单元格。");
  }

  // Subtest 2: Overwrite confirm dialog called with correct text; user cancellation halts write
  {
    const sourceRange = buildRange("$A$1:$C$4", [
      ["表头A", "表头B", "表头C"],
      ["A2", "B2", "C2"],
      ["A3", "B3", "C3"],
      ["A4", "B4", "C4"]
    ], { sheetName: "客户表", startRow: 1, startColumn: 1 });

    const targetRange = buildRange("$D$2:$D$4", [["已存值1"], [""], [""]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4
    });

    const worksheetObj = {
      Name: "客户表",
      ProtectContents: false,
      Range(addr) {
        if (addr === "$A$1:$C$4" || addr === "A1:C4") return sourceRange;
        return targetRange.Worksheet.Range(addr);
      }
    };
    const appMock = {
      ActiveWorkbook: { Name: "测试表.xlsx", Worksheets: { Item: () => worksheetObj } },
      ActiveSheet: worksheetObj,
      Selection: targetRange
    };

    let confirmPrompt = "";
    const env = createIntegrationEnvironment({
      appMock,
      confirm(prompt) {
        confirmPrompt = prompt;
        return false; // User cancels overwrite
      }
    });
    const { state, writeExcelSmartFillResult } = env.exports;

    state.smartFillSource = helpers.extractExcelSmartFillPayload(null, sourceRange, {
      sourceOnly: true,
      sourceSheetName: "客户表"
    }).source;
    state.smartFillTarget = { sheetName: "客户表", address: "$D$2:$D$4", rowCount: 3 };
    state.smartFillWorkbookId = "测试表.xlsx";
    state.excelSmartFillCompletedJobId = "job_done_002";
    state.excelSmartFillResultRevision = 1;
    state.smartFillResult = {
      items: [
        { itemId: "sf_001", status: "completed", value: "新值1", valueType: "text" },
        { itemId: "sf_002", status: "completed", value: "新值2", valueType: "text" },
        { itemId: "sf_003", status: "completed", value: "新值3", valueType: "text" }
      ]
    };
    state.smartFillDraftItems = [
      { itemId: "sf_001", selected: true, value: "新值1", valueType: "text", status: "completed" },
      { itemId: "sf_002", selected: true, value: "新值2", valueType: "text", status: "completed" },
      { itemId: "sf_003", selected: true, value: "新值3", valueType: "text", status: "completed" }
    ];

    writeExcelSmartFillResult();

    // Confirm dialog was prompted with target info
    assert.match(confirmPrompt, /覆盖 1 个已有文本或数字单元格/);
    assert.match(confirmPrompt, /D2:D4/);

    // Write halted: D2 value remains "已存值1", state not cleared
    assert.strictEqual(targetRange.Cells.Item(2, 4).Value2, "已存值1");
    assert.ok(state.smartFillResult != null, "smartFillResult should not be cleared on cancel");
    assert.strictEqual(env.domElements["status-line"].textContent, "已取消智能填写写回。");
  }

  // Subtest 3: Target cell modified before write -> conflict detected, draft marked write_conflict,
  // tryRebindSmartFillTarget called immediately (Minor 1)
  {
    const sourceRange = buildRange("$A$1:$C$4", [
      ["表头A", "表头B", "表头C"],
      ["A2", "B2", "C2"],
      ["A3", "B3", "C3"],
      ["A4", "B4", "C4"]
    ], { sheetName: "客户表", startRow: 1, startColumn: 1 });

    const targetRange = buildRange("$D$2:$D$4", [["原D2"], [""], [""]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4
    });

    const modifiedCell = Object.assign({}, targetRange.Cells.Item(2, 4), {
      Value2: "被篡改",
      Text: "被篡改"
    });

    const worksheetObj = {
      Name: "客户表",
      ProtectContents: false,
      Range(addr) {
        if (addr === "$A$1:$C$4" || addr === "A1:C4") return sourceRange;
        if (addr === "$D$2" || addr === "D2") return modifiedCell;
        return targetRange.Worksheet.Range(addr);
      }
    };
    const appMock = {
      ActiveWorkbook: { Name: "测试表.xlsx", Worksheets: { Item: () => worksheetObj } },
      ActiveSheet: worksheetObj,
      Selection: targetRange
    };

    const env = createIntegrationEnvironment({ appMock });
    const { state, writeExcelSmartFillResult } = env.exports;

    state.currentMode = "excelSmartFill";
    state.smartFillSource = helpers.extractExcelSmartFillPayload(null, sourceRange, {
      sourceOnly: true,
      sourceSheetName: "客户表"
    }).source;
    state.smartFillTarget = { sheetName: "客户表", address: "$D$2:$D$4", rowCount: 3 };
    state.smartFillWorkbookId = "测试表.xlsx";
    state.excelSmartFillCompletedJobId = "job_done_003";
    state.excelSmartFillResultRevision = 1;
    state.smartFillResult = {
      items: [
        { itemId: "sf_001", status: "completed", value: "填1", valueType: "text" },
        { itemId: "sf_002", status: "completed", value: "填2", valueType: "text" },
        { itemId: "sf_003", status: "completed", value: "填3", valueType: "text" }
      ]
    };
    state.smartFillDraftItems = [
      { itemId: "sf_001", selected: true, value: "填1", valueType: "text", status: "completed" },
      { itemId: "sf_002", selected: true, value: "填2", valueType: "text", status: "completed" },
      { itemId: "sf_003", selected: true, value: "填3", valueType: "text", status: "completed" }
    ];

    writeExcelSmartFillResult();

    // Draft item sf_001 should be marked conflict and unselected
    const draft1 = state.smartFillDraftItems.find((d) => d.itemId === "sf_001");
    assert.strictEqual(draft1.status, "write_conflict");
    assert.strictEqual(draft1.selected, false);

    // Minor 1: draft marked write_conflict and live target rebound immediately
    assert.ok(state.smartFillLiveTarget != null, "tryRebindSmartFillTarget must update smartFillLiveTarget");
    assert.match(env.domElements["status-line"].textContent, /部分目标单元格已变化/);
  }

  // Subtest 4: Missing completed job ID prevents writeback (Important 3)
  {
    const targetRange = buildRange("$D$2:$D$3", [[""], [""]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4
    });
    const appMock = {
      ActiveWorkbook: { Name: "测试表.xlsx" },
      ActiveSheet: targetRange.Worksheet,
      Selection: targetRange
    };
    const env = createIntegrationEnvironment({ appMock });
    const { state, writeExcelSmartFillResult } = env.exports;

    state.smartFillTarget = { sheetName: "客户表", address: "$D$2:$D$3", rowCount: 2 };
    state.smartFillWorkbookId = "测试表.xlsx";
    state.excelSmartFillCompletedJobId = "";
    state.excelSmartFillJobId = "";
    state.smartFillResult = {
      items: [
        { itemId: "sf_001", status: "completed", value: "值1" },
        { itemId: "sf_002", status: "completed", value: "值2" }
      ]
    };
    state.smartFillDraftItems = [
      { itemId: "sf_001", selected: true, value: "值1", valueType: "text" },
      { itemId: "sf_002", selected: true, value: "值2", valueType: "text" }
    ];

    writeExcelSmartFillResult();
    assert.strictEqual(env.domElements["status-line"].textContent, "未绑定有效的智能填写任务，请重新生成预览后再写入。");
  }

  // Subtest 5: Compensation rollback on write failure
  {
    const sourceRange = buildRange("$A$1:$C$3", [
      ["A1", "B1", "C1"],
      ["A2", "B2", "C2"],
      ["A3", "B3", "C3"]
    ], { sheetName: "客户表", startRow: 1, startColumn: 1 });

    const targetRange = buildRange("$D$2:$D$3", [["原D2"], ["原D3"]], {
      sheetName: "客户表",
      startRow: 2,
      startColumn: 4,
      failOnNewValue: true // Triggers write failure during new value write, but rollback restore succeeds
    });

    const worksheetObj = {
      Name: "客户表",
      ProtectContents: false,
      Range(addr) {
        if (addr === "$A$1:$C$3" || addr === "A1:C3") return sourceRange;
        return targetRange.Worksheet.Range(addr);
      }
    };
    const appMock = {
      ActiveWorkbook: { Name: "测试表.xlsx", Worksheets: { Item: () => worksheetObj } },
      ActiveSheet: worksheetObj,
      Selection: targetRange
    };

    const env = createIntegrationEnvironment({ appMock });
    const { state, writeExcelSmartFillResult } = env.exports;

    state.smartFillSource = helpers.extractExcelSmartFillPayload(null, sourceRange, {
      sourceOnly: true,
      sourceSheetName: "客户表"
    }).source;
    state.smartFillTarget = { sheetName: "客户表", address: "$D$2:$D$3", rowCount: 2 };
    state.smartFillWorkbookId = "测试表.xlsx";
    state.excelSmartFillCompletedJobId = "job_done_005";
    state.excelSmartFillResultRevision = 1;
    state.smartFillResult = {
      items: [
        { itemId: "sf_001", status: "completed", value: "写1" },
        { itemId: "sf_002", status: "completed", value: "写2" }
      ]
    };
    state.smartFillDraftItems = [
      { itemId: "sf_001", selected: true, value: "写1", valueType: "text" },
      { itemId: "sf_002", selected: true, value: "写2", valueType: "text" }
    ];

    writeExcelSmartFillResult();
    assert.match(env.domElements["status-line"].textContent, /智能填写写入中断：已通过内部故障处理恢复原值。/);
    assert.match(env.domElements["result-output"].textContent, /已通过内部故障处理恢复全部已改动单元格/);
  }
}

testInspectTargetSelectionValidatesSheetContinuousAndCount();
testInspectTargetSelectionRejectsFormulaMergedHiddenLocked();
testTargetMappingTopToBottomWithEmptySlotsForExcludedOrFailed();
testOverwriteCountCalculationForActiveWritableItemsOnly();
testFormattedCellValuesDoNotTriggerConflict();
testCommitContextEnforcesJobAndRevisionBinding();
testUncompletedItemsRenderDisabledAndCannotBeWritten();
testTaskpaneBehavioralIntegration();

console.log("Excel smart fill target mapping tests passed");
