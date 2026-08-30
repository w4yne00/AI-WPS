const assert = require("assert");
const fs = require("fs");

const root = "formal-plugin-kit/wps-ai-assistant-et_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const ribbon = fs.readFileSync(`${root}/ribbon.xml`, "utf8");
const ribbonJs = fs.readFileSync(`${root}/ribbon.js`, "utf8");
const helpers = require(`../wps-ai-assistant-et_1.0.0/taskpane-helpers.js`);

function buildRange(address, values) {
  const rows = values.length;
  const columns = values[0].length;
  const cells = {};
  values.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
    const cellAddress = `$${String.fromCharCode(65 + columnIndex)}$${rowIndex + 1}`;
    cells[`${rowIndex + 1},${columnIndex + 1}`] = {
      Address: cellAddress,
      Text: String(value == null ? "" : value),
      Value2: value,
      Formula: "",
      HasFormula: false,
      MergeCells: false,
      Locked: false,
      Hidden: false
    };
  }));
  return {
    Address: address,
    Rows: { Count: rows },
    Columns: { Count: columns },
    Cells: {
      Item(row, column) {
        return cells[`${row},${column}`];
      }
    }
  };
}

function testSmartFillPayloadCapturesFrozenSnapshots() {
  assert.strictEqual(typeof helpers.extractExcelSmartFillPayload, "function");
  const target = buildRange("$B$2:$C$3", [["待填写", "已有"], ["", "待填写"]]);
  const source = buildRange("$F$1:$G$3", [["姓名", "部门"], ["张三", "研发"], ["李四", "销售"]]);
  target.Cells.Item(1, 1).Formula = "";
  target.Cells.Item(1, 1).HasFormula = false;

  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "数据表",
    maxItems: 500,
    maxSourceRows: 500,
    maxSourceColumns: 50,
    maxCellTextLength: 2000,
    maxTotalTextLength: 200000
  });

  assert.deepStrictEqual(payload.target.sheetName, "目标表");
  assert.strictEqual(payload.target.address, "$B$2:$C$3");
  assert.strictEqual(payload.target.items.length, 4);
  assert.strictEqual(payload.target.items[0].itemId, "target-1");
  assert.strictEqual(payload.target.items[0].address, "$A$1");
  assert.strictEqual(payload.target.items[0].originalValue, "待填写");
  assert.strictEqual(payload.target.items[0].originalValueType, "text");
  assert.strictEqual(payload.target.items[0].originalFormula, "");
  assert.strictEqual(payload.target.items[0].isFormula, false);
  assert.strictEqual(payload.target.items[0].isMerged, false);
  assert.strictEqual(payload.target.items[0].isProtected, false);
  assert.strictEqual(payload.target.items[0].isHidden, false);
  assert.strictEqual(payload.target.items[0].row, 1);
  assert.strictEqual(payload.target.items[0].column, 1);

  assert.deepStrictEqual(payload.source.headers, ["姓名", "部门"]);
  assert.deepStrictEqual(payload.source.rows, [["张三", "研发"], ["李四", "销售"]]);
  assert.strictEqual(payload.source.rowCount, 2);
  assert.strictEqual(payload.source.columnCount, 2);
  assert.strictEqual(payload.source.truncated, false);
  assert.ok(!Object.prototype.hasOwnProperty.call(payload.source.rows[0][0], "formula"));
}

function testSmartFillWritebackGuardsSnapshotAndFormulaSafety() {
  assert.strictEqual(typeof helpers.writeExcelSmartFillCells, "function");
  function makeCell(value, extra) {
    let current = value;
    const cell = {
      Formula: "",
      HasFormula: false,
      MergeCells: false,
      Locked: false,
      Hidden: false
    };
    Object.defineProperties(cell, {
      Value2: {
        enumerable: true,
        configurable: true,
        get() { return current; },
        set(next) { current = next; }
      },
      Text: {
        enumerable: true,
        configurable: true,
        get() { return current == null ? "" : String(current); }
      }
    });
    if (extra) {
      Object.defineProperties(cell, Object.getOwnPropertyDescriptors(extra));
    }
    return cell;
  }
  const items = [
    {
      itemId: "target-1", address: "$B$2", originalValue: "原值", originalValueType: "text",
      originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
    }
  ];
  const cell = makeCell("原值");
  const result = [{ itemId: "target-1", status: "completed", valueType: "text", value: "新值" }];
  assert.deepStrictEqual(
    helpers.writeExcelSmartFillCells(items, result, (item) => item.itemId === "target-1" ? cell : null),
    { writtenCount: 1, skippedCount: 0 }
  );
  assert.strictEqual(cell.Value2, "新值");

  const changedCell = makeCell("已经改变");
  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, result, () => changedCell),
    /已变化/
  );
  assert.strictEqual(changedCell.Value2, "已经改变");

  const typeChangedCell = makeCell(1);
  assert.throws(
    () => helpers.writeExcelSmartFillCells(items, result, () => typeChangedCell),
    /已变化/
  );
  assert.strictEqual(typeChangedCell.Value2, 1);

  const formulaCell = makeCell("原值", { Formula: "=A1", HasFormula: true });
  assert.throws(
    () => helpers.writeExcelSmartFillCells(
      [Object.assign({}, items[0], { isFormula: true, originalFormula: "=A1", originalValueType: "formula" })],
      result,
      () => formulaCell
    ),
    /公式/
  );
  assert.strictEqual(formulaCell.Value2, "原值");
}

function testSmartFillWritesFormulaLikeTextAsLiteralAndReportsRollbackAddresses() {
  function makeCell(value, extra) {
    let current = value;
    const cell = {
      Formula: "",
      HasFormula: false,
      MergeCells: false,
      Locked: false,
      Hidden: false
    };
    Object.defineProperties(cell, {
      Value2: {
        enumerable: true,
        configurable: true,
        get() { return current; },
        set(next) { current = next; }
      },
      Text: {
        enumerable: true,
        configurable: true,
        get() { return current == null ? "" : String(current); }
      }
    });
    if (extra) {
      Object.defineProperties(cell, Object.getOwnPropertyDescriptors(extra));
    }
    return cell;
  }
  const item = {
    itemId: "target-1", address: "$B$2", originalValue: "原值", originalValueType: "text",
    originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
  };
  const literalCell = makeCell("原值");
  helpers.writeExcelSmartFillCells(
    [item],
    [{ itemId: "target-1", status: "completed", valueType: "text", value: "=按字面填写" }],
    () => literalCell
  );
  assert.strictEqual(literalCell.Value2, "'=按字面填写");

  let firstValue = "原值1";
  const firstCell = makeCell("原值1", {
    get Value2() { return firstValue; },
    set Value2(next) {
      if (next === "原值1") throw new Error("rollback failed");
      firstValue = next;
    },
    get Text() { return firstValue; }
  });
  const secondCell = makeCell("原值2", {
    get Value2() { return "原值2"; },
    set Value2(next) {
      if (next === "新值2") throw new Error("write failed");
    }
  });
  assert.throws(
    () => helpers.writeExcelSmartFillCells(
      [
        Object.assign({}, item, { itemId: "target-1", address: "$B$2", originalValue: "原值1" }),
        Object.assign({}, item, { itemId: "target-2", address: "$B$3", originalValue: "原值2" })
      ],
      [
        { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
        { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
      ],
      (candidate) => candidate.itemId === "target-1" ? firstCell : secondCell
    ),
    /\$B\$2/
  );

  let silentlyUnrestoredValue = "原值1";
  const silentlyUnrestoredCell = makeCell("原值1", {
    get Value2() { return silentlyUnrestoredValue; },
    set Value2(next) {
      if (next !== "原值1") silentlyUnrestoredValue = next;
    },
    get Text() { return silentlyUnrestoredValue; }
  });
  const failedWriteCell = makeCell("原值2", {
    get Value2() { return "原值2"; },
    set Value2(next) {
      if (next === "新值2") return;
    }
  });
  assert.throws(
    () => helpers.writeExcelSmartFillCells(
      [
        Object.assign({}, item, { itemId: "target-1", address: "$C$2", originalValue: "原值1" }),
        Object.assign({}, item, { itemId: "target-2", address: "$C$3", originalValue: "原值2" })
      ],
      [
        { itemId: "target-1", status: "completed", valueType: "text", value: "新值1" },
        { itemId: "target-2", status: "completed", valueType: "text", value: "新值2" }
      ],
      (candidate) => candidate.itemId === "target-1" ? silentlyUnrestoredCell : failedWriteCell
    ),
    /\$C\$2/
  );
  assert.strictEqual(silentlyUnrestoredValue, "新值1");
}

function testSmartFillFailsClosedWhenHostSafetyPropertiesCannotBeRead() {
  function makeUnsafeCell() {
    let current = "原值";
    const cell = {};
    Object.defineProperties(cell, {
      Value2: {
        enumerable: true,
        configurable: true,
        get() { return current; },
        set(next) { current = next; }
      },
      Text: {
        enumerable: true,
        configurable: true,
        get() { return current; }
      },
      HasFormula: {
        enumerable: true,
        configurable: true,
        get() { throw new Error("HasFormula unavailable"); }
      },
      MergeCells: {
        enumerable: true,
        configurable: true,
        get() { throw new Error("MergeCells unavailable"); }
      },
      Locked: {
        enumerable: true,
        configurable: true,
        get() { throw new Error("Locked unavailable"); }
      },
      Hidden: {
        enumerable: true,
        configurable: true,
        get() { throw new Error("Hidden unavailable"); }
      }
    });
    return cell;
  }
  assert.throws(
    () => helpers.writeExcelSmartFillCells(
      [{
        itemId: "target-1", address: "$D$2", originalValue: "原值", originalValueType: "text",
        originalFormula: "", isFormula: false, isMerged: false, isProtected: false, isHidden: false
      }],
      [{ itemId: "target-1", status: "completed", valueType: "text", value: "新值" }],
      makeUnsafeCell
    ),
    /无法安全读取|安全读取/
  );
}

function testSmartFillExcludesHiddenSourceValuesAndValidatesTargetShape() {
  const target = buildRange("$D$2:$D$3", [["", ""], ["", ""]]);
  const source = buildRange("$A$1:$B$3", [["姓名", "部门"], ["张三", "研发"], ["李四", "销售"]]);
  source.Cells.Item(2, 2).Hidden = true;
  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  assert.strictEqual(payload.source.rows[0][1], "");
  assert.strictEqual(typeof helpers.validateExcelSmartFillTarget, "function");
  assert.doesNotThrow(() => helpers.validateExcelSmartFillTarget({ items: [
    { row: 2, column: 4, isFormula: false, isMerged: false, isProtected: false, isHidden: false },
    { row: 3, column: 4, isFormula: false, isMerged: false, isProtected: false, isHidden: false }
  ] }));
  assert.throws(() => helpers.validateExcelSmartFillTarget({ items: [
    { row: 2, column: 4 }, { row: 2, column: 5 }
  ] }), /单列/);
}

function testSmartFillExtractionFailsClosedOnUnreadableHostFlags() {
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$A$2", [["说明"], ["不应外泄"]]);
  Object.defineProperties(source.Cells.Item(2, 1), {
    HasFormula: {
      configurable: true,
      get() { throw new Error("HasFormula unavailable"); }
    }
  });
  Object.defineProperties(target.Cells.Item(1, 1), {
    Hidden: {
      configurable: true,
      get() { throw new Error("Hidden unavailable"); }
    }
  });
  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  assert.strictEqual(payload.source.rows[0][0], "");
  assert.strictEqual(payload.target.items[0].isHidden, true);
  assert.throws(() => helpers.validateExcelSmartFillTarget(payload.target), /隐藏/);
}

function testSmartFillUiContract() {
  [
    'id="excel-smart-fill-options"',
    'id="btn-capture-smart-fill-target"',
    'id="btn-capture-smart-fill-source"',
    'id="excel-smart-fill-instruction"',
    'id="btn-write-smart-fill"',
    'id="smart-fill-write-summary"',
    '生成预览',
    '写入内容'
  ].forEach((marker) => assert.ok(html.includes(marker), `missing smart fill UI marker: ${marker}`));
  assert.ok(ribbon.includes('id="btnAiExcelSmartFill" label="智能填写"'));
  assert.ok(ribbonJs.includes('btnAiExcelSmartFill: "excelSmartFill"'));
  assert.ok(js.includes('var EXCEL_SMART_FILL_WORKFLOW_TASK_TYPE = "excel.smart_fill";'));
  assert.ok(js.includes("/excel/smart-fill/jobs"));
  assert.ok(js.includes("writeExcelSmartFillResult"));
  assert.ok(js.includes("smartFillDraftItems"));
  assert.ok(js.includes("smartFillRetryBaseDraftItems"));
  assert.ok(js.includes("retryExcelSmartFillItem"));
  assert.ok(js.includes("window.confirm"));
  [
    "EXCEL_SMART_FILL_TARGET_SHAPE_INVALID",
    "EXCEL_SMART_FILL_CROSS_SHEET",
    "EXCEL_SMART_FILL_INSTRUCTION_REQUIRED"
  ].forEach((code) => assert.ok(js.includes(code), `missing smart fill fatal error code: ${code}`));
  assert.ok(!/\.Formula\s*=/.test(js), "smart fill taskpane must never write Formula");
}

testSmartFillPayloadCapturesFrozenSnapshots();
testSmartFillWritebackGuardsSnapshotAndFormulaSafety();
testSmartFillWritesFormulaLikeTextAsLiteralAndReportsRollbackAddresses();
testSmartFillFailsClosedWhenHostSafetyPropertiesCannotBeRead();
testSmartFillExcludesHiddenSourceValuesAndValidatesTargetShape();
testSmartFillExtractionFailsClosedOnUnreadableHostFlags();
testSmartFillUiContract();

console.log("Excel smart fill tests passed");
