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

function makeDefaultSourceCell(text, extra) {
  return Object.assign({
    text: text,
    hidden: false,
    hasFormula: false,
    formula: "",
    comment: ""
  }, extra || {});
}

function testSmartFillDefaultSourceUsesHeaderAndCurrentRowOnly() {
  assert.strictEqual(typeof helpers.buildExcelSmartFillDefaultSource, "function");
  const cells = {
    "1,1": makeDefaultSourceCell("名称"),
    "1,2": makeDefaultSourceCell("部门"),
    "1,3": makeDefaultSourceCell("说明"),
    "1,4": makeDefaultSourceCell("摘要"),
    "2,1": makeDefaultSourceCell("甲", { comment: "内部批注不得外发" }),
    "2,2": makeDefaultSourceCell("研发", { hidden: true }),
    "2,3": makeDefaultSourceCell("=A2", { hasFormula: true, formula: "=A2" }),
    "2,4": makeDefaultSourceCell("旧摘要"),
    "3,1": makeDefaultSourceCell("乙"),
    "3,2": makeDefaultSourceCell("销售"),
    "3,3": makeDefaultSourceCell("第二项"),
    "3,4": makeDefaultSourceCell("不应进入默认来源")
  };
  const target = {
    sheetName: "目标表",
    address: "$D$2",
    items: [{
      itemId: "target-1",
      address: "$D$2",
      row: 2,
      column: 4,
      originalValue: "",
      originalValueType: "blank",
      originalFormula: "",
      isFormula: false,
      isMerged: false,
      isProtected: false,
      isHidden: false
    }]
  };
  const source = helpers.buildExcelSmartFillDefaultSource(target, (row, column) => (
    cells[`${row},${column}`] || makeDefaultSourceCell("")
  ));

  assert.strictEqual(target.columnHeader, "摘要");
  assert.deepStrictEqual(source.headers, ["名称", "部门", "说明", "摘要"]);
  assert.strictEqual(source.rowCount, 1);
  assert.strictEqual(source.columnCount, 4);
  assert.deepStrictEqual(source.rows, [["甲", "", "", ""]]);
  assert.ok(!JSON.stringify(source).includes("内部批注不得外发"));
  assert.ok(!JSON.stringify(source).includes("=A2"));
  assert.ok(!JSON.stringify(source).includes("不应进入默认来源"));
  assert.ok(!JSON.stringify(source).includes("旧摘要"));
  assert.ok(!Object.prototype.hasOwnProperty.call(source, "comments"));
}

function testSmartFillDefaultSourceKeepsARowForEachTargetItem() {
  const cells = {
    "1,1": makeDefaultSourceCell("名称"),
    "1,4": makeDefaultSourceCell("摘要"),
    "2,1": makeDefaultSourceCell("甲"),
    "2,4": makeDefaultSourceCell("旧D2"),
    "3,1": makeDefaultSourceCell("乙"),
    "3,4": makeDefaultSourceCell("旧D3"),
    "4,1": makeDefaultSourceCell("丙")
  };
  const target = {
    sheetName: "目标表",
    address: "$D$2:$D$3",
    items: [
      {
        itemId: "target-1", address: "$D$2", row: 2, column: 4,
        originalValue: "", originalValueType: "blank", originalFormula: "",
        isFormula: false, isMerged: false, isProtected: false, isHidden: false
      },
      {
        itemId: "target-2", address: "$D$3", row: 3, column: 4,
        originalValue: "", originalValueType: "blank", originalFormula: "",
        isFormula: false, isMerged: false, isProtected: false, isHidden: false
      }
    ]
  };
  const source = helpers.buildExcelSmartFillDefaultSource(target, (row, column) => (
    cells[`${row},${column}`] || makeDefaultSourceCell("")
  ));
  assert.strictEqual(source.rowCount, 2);
  assert.deepStrictEqual(source.rows, [
    ["甲", "", "", ""],
    ["乙", "", "", ""]
  ]);
  assert.ok(!JSON.stringify(source).includes("丙"));
  assert.ok(!JSON.stringify(source).includes("旧D2"));
  assert.ok(!JSON.stringify(source).includes("旧D3"));
}

function testHostDisplayedEmptyDoesNotFallBackToRawValue() {
  assert.strictEqual(typeof helpers.describeExcelSmartFillHostCell, "function");
  const cell = helpers.describeExcelSmartFillHostCell("", {
    hasFormula: true,
    formula: "=A1",
    rawText: "12"
  });
  assert.strictEqual(cell.text, "");
  assert.strictEqual(cell.hasFormula, true);
  assert.ok(!JSON.stringify(cell).includes("12"));
}

function testSuccessfulWriteStillConsumesPreviewIfConsumeWouldThrow() {
  assert.strictEqual(typeof helpers.finalizeExcelSmartFillWriteSuccess, "function");
  const preview = { consumed: false, result: null };
  helpers.finalizeExcelSmartFillWriteSuccess(preview);
  assert.strictEqual(preview.consumed, true);
  assert.strictEqual(preview.result, null);
  const ok = helpers.createExcelSmartFillPreview({
    schemaVersion: "excel.smart_fill.v1",
    items: [{ itemId: "target-1", status: "completed", valueType: "text", value: "甲类" }]
  });
  helpers.finalizeExcelSmartFillWriteSuccess(ok);
  assert.throws(() => helpers.consumeExcelSmartFillPreview(ok), /重复/);
}

function testSmartFillReadonlyPreviewOmitsEditingAndUndo() {
  assert.strictEqual(typeof helpers.buildExcelSmartFillReadonlyPreview, "function");
  const html = helpers.buildExcelSmartFillReadonlyPreview({
    items: [
      { itemId: "target-1", status: "completed", valueType: "text", value: "甲类" },
      { itemId: "target-2", status: "insufficient_information", valueType: "text", value: "" }
    ]
  }, [
    { itemId: "target-1", address: "$D$2" },
    { itemId: "target-2", address: "$D$3" }
  ]);
  assert.ok(html.includes("智能填写预览"));
  assert.ok(html.includes("$D$2"));
  assert.ok(html.includes("甲类"));
  assert.ok(html.includes("信息不足"));
  assert.ok(!html.includes("<input"));
  assert.ok(!html.includes("textarea"));
  assert.ok(!html.includes("撤销"));
  assert.ok(!/undo/i.test(html));
  assert.ok(!html.includes("可编辑"));
}

function testSmartFillPreviewCannotBeSubmittedTwice() {
  assert.strictEqual(typeof helpers.createExcelSmartFillPreview, "function");
  assert.strictEqual(typeof helpers.consumeExcelSmartFillPreview, "function");
  const preview = helpers.createExcelSmartFillPreview({
    schemaVersion: "excel.smart_fill.v1",
    items: [{ itemId: "target-1", status: "completed", valueType: "text", value: "甲类" }]
  });
  helpers.consumeExcelSmartFillPreview(preview);
  assert.strictEqual(preview.consumed, true);
  assert.strictEqual(preview.result, null);
  assert.throws(
    () => helpers.consumeExcelSmartFillPreview(preview),
    /重复/
  );
}

function testSmartFillExtractionFailsClosedOnOversizedCellText() {
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$A$2", [["说明"], ["x".repeat(2001)]]);
  assert.throws(
    () => helpers.extractExcelSmartFillPayload(target, source, {
      targetSheetName: "目标表",
      sourceSheetName: "目标表",
      maxCellTextLength: 2000,
      maxTotalTextLength: 200000
    }),
    /2000/
  );
}

function testSmartFillExtractionFailsClosedOnOversizedSourceRange() {
  const values = [["表头"]];
  for (let index = 0; index < 501; index += 1) {
    values.push(["行" + index]);
  }
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$A$502", values);
  assert.throws(
    () => helpers.extractExcelSmartFillPayload(target, source, {
      targetSheetName: "目标表",
      sourceSheetName: "目标表",
      maxSourceRows: 500
    }),
    /500/
  );
}

function testSmartFillCustomSourceBlanksTargetCurrentValues() {
  const target = buildRange("$D$2:$D$3", [["旧D2"], ["旧D3"]]);
  const source = buildRange("$A$1:$D$3", [
    ["名称", "部门", "说明", "摘要"],
    ["甲", "研发", "第一项", "旧D2"],
    ["乙", "销售", "第二项", "旧D3"]
  ]);
  target.Cells.Item(1, 1).Row = 2;
  target.Cells.Item(1, 1).Column = 4;
  target.Cells.Item(2, 1).Row = 3;
  target.Cells.Item(2, 1).Column = 4;
  source.Cells.Item(2, 4).Row = 2;
  source.Cells.Item(2, 4).Column = 4;
  source.Cells.Item(3, 4).Row = 3;
  source.Cells.Item(3, 4).Column = 4;
  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  assert.deepStrictEqual(payload.source.headers, ["名称", "部门", "说明", "摘要"]);
  assert.deepStrictEqual(payload.source.rows, [
    ["甲", "研发", "第一项", ""],
    ["乙", "销售", "第二项", ""]
  ]);
  assert.ok(!JSON.stringify(payload.source).includes("旧D2"));
  assert.ok(!JSON.stringify(payload.source).includes("旧D3"));
}

function testSmartFillInstructionRejectsMoreThan4000CodePoints() {
  assert.strictEqual(typeof helpers.validateExcelSmartFillInstruction, "function");
  assert.strictEqual(helpers.validateExcelSmartFillInstruction("按来源分类"), "按来源分类");
  assert.strictEqual(helpers.validateExcelSmartFillInstruction("😀".repeat(4000)).length, 8000);
  assert.throws(
    () => helpers.validateExcelSmartFillInstruction("x".repeat(4001)),
    /4000/
  );
  assert.throws(
    () => helpers.validateExcelSmartFillInstruction("😀".repeat(4001)),
    /4000/
  );
}

function testSmartFillPreviewKeepsFailedInsufficientAndCompletedStatuses() {
  const html = helpers.buildExcelSmartFillReadonlyPreview({
    items: [
      { itemId: "item-1", status: "completed", valueType: "text", value: "甲类" },
      { itemId: "item-2", status: "insufficient_information", valueType: "text", value: "" },
      { itemId: "item-3", status: "failed", valueType: "text", value: "" }
    ]
  }, [
    { itemId: "item-1", address: "$D$2" },
    { itemId: "item-2", address: "$D$3" },
    { itemId: "item-3", address: "$D$4" }
  ]);
  assert.ok(html.includes("可写入"));
  assert.ok(html.includes("信息不足"));
  assert.ok(html.includes("失败"));
  assert.ok(html.includes("$D$4"));
  assert.ok(!html.includes("<input"));
}

function testSmartFillRejectsNonContiguousSourceAreas() {
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$B$2", [["姓名", "部门"], ["甲", "研发"]]);
  source.Areas = { Count: 2 };
  assert.throws(
    () => helpers.extractExcelSmartFillPayload(target, source, {
      targetSheetName: "目标表",
      sourceSheetName: "目标表"
    }),
    /连续/
  );
}

function testSmartFillSanitizeHelperBlanksOverlappingTargetColumn() {
  assert.strictEqual(typeof helpers.sanitizeExcelSmartFillSource, "function");
  const sanitized = helpers.sanitizeExcelSmartFillSource({
    sheetName: "目标表",
    address: "$A$1:$D$3",
    headers: ["名称", "部门", "说明", "摘要"],
    rows: [["甲", "研发", "第一项", "旧D2"], ["乙", "销售", "第二项", "旧D3"]],
    rowCount: 2,
    columnCount: 4,
    truncated: false,
    snapshotHash: "deadbeef"
  }, {
    sheetName: "目标表",
    items: [
      { row: 2, column: 4 },
      { row: 3, column: 4 }
    ]
  });
  assert.deepStrictEqual(sanitized.rows, [
    ["甲", "研发", "第一项", ""],
    ["乙", "销售", "第二项", ""]
  ]);
  assert.ok(sanitized.snapshotHash);
  assert.notStrictEqual(sanitized.snapshotHash, "deadbeef");
}

function testSmartFillSanitizeFailsClosedOnUnparseableCustomSourceAddress() {
  assert.throws(
    () => helpers.sanitizeExcelSmartFillSource({
      sheetName: "目标表",
      address: "$D:$D",
      headers: ["摘要"],
      rows: [["旧D2"]],
      rowCount: 1,
      columnCount: 1,
      truncated: false
    }, {
      sheetName: "目标表",
      items: [{ row: 2, column: 4 }]
    }),
    /来源/
  );
}

function testSmartFillSanitizeBlanksDefaultSourceWhenAddressIsEmpty() {
  const sanitized = helpers.sanitizeExcelSmartFillSource({
    sheetName: "目标表",
    address: "",
    headers: ["名称", "部门", "说明", "摘要"],
    rows: [["甲", "研发", "第一项", "旧D2"]],
    rowCount: 1,
    columnCount: 4,
    truncated: false
  }, {
    sheetName: "目标表",
    items: [{ row: 2, column: 4 }]
  });
  assert.strictEqual(sanitized.rows[0][3], "");
  assert.ok(!JSON.stringify(sanitized.rows).includes("旧D2"));
}

function testSmartFillSourceTextDoesNotFallBackToRawValue() {
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$A$2", [["说明"], ["显示值"]]);
  Object.defineProperties(source.Cells.Item(2, 1), {
    Text: {
      configurable: true,
      get() { throw new Error("Text unavailable"); }
    },
    Value2: {
      configurable: true,
      get() { return 44927; }
    }
  });
  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  assert.strictEqual(payload.source.rows[0][0], "");
  assert.ok(!JSON.stringify(payload.source).includes("44927"));
}

function testSmartFillSourceTextMissingDoesNotUseValue2() {
  const target = buildRange("$D$2:$D$2", [["待填写"]]);
  const source = buildRange("$A$1:$A$2", [["说明"], ["显示值"]]);
  const cell = source.Cells.Item(2, 1);
  delete cell.Text;
  cell.Value2 = 44927;
  const payload = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  assert.strictEqual(payload.source.rows[0][0], "");
  assert.ok(!JSON.stringify(payload.source).includes("44927"));
}

function testWritePreflightHashMatchesSanitizedCapture() {
  const target = buildRange("$D$2:$D$3", [["旧D2"], ["旧D3"]]);
  const source = buildRange("$A$1:$D$3", [
    ["名称", "部门", "说明", "摘要"],
    ["甲", "研发", "第一项", "旧D2"],
    ["乙", "销售", "第二项", "旧D3"]
  ]);
  target.Cells.Item(1, 1).Row = 2;
  target.Cells.Item(1, 1).Column = 4;
  target.Cells.Item(2, 1).Row = 3;
  target.Cells.Item(2, 1).Column = 4;
  source.Cells.Item(2, 4).Row = 2;
  source.Cells.Item(2, 4).Column = 4;
  source.Cells.Item(3, 4).Row = 3;
  source.Cells.Item(3, 4).Column = 4;
  const captured = helpers.extractExcelSmartFillPayload(target, source, {
    targetSheetName: "目标表",
    sourceSheetName: "目标表"
  });
  const reread = helpers.extractExcelSmartFillPayload(null, source, {
    sourceOnly: true,
    sourceSheetName: "目标表"
  });
  const unsanitizedHash = reread.source.snapshotHash;
  const sanitizedReread = helpers.sanitizeExcelSmartFillSource(reread.source, captured.target);
  assert.strictEqual(sanitizedReread.snapshotHash, captured.source.snapshotHash);
  assert.notStrictEqual(unsanitizedHash, captured.source.snapshotHash);
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
  assert.ok(!html.includes("撤销"));
  assert.ok(js.includes("buildExcelSmartFillReadonlyPreview"));
  assert.ok(js.includes("finalizeExcelSmartFillWriteSuccess"));
  assert.ok(js.includes("buildExcelSmartFillDefaultSource"));
  assert.ok(js.includes("describeExcelSmartFillHostCell"));
  assert.ok(js.includes("validateExcelSmartFillInstruction"));
  assert.ok(js.includes("sanitizeExcelSmartFillSource"));
  assert.ok(js.includes("sanitizeExcelSmartFillSource(payload.source, target)"));
  assert.ok(js.includes("EXCEL_SMART_FILL_RESULT_TOO_LARGE"));
  assert.ok(js.includes("智能填写来源校验组件不可用"));
  assert.ok(!/readSmartFillPropertyState\(cell, \[\s*"Text", "text", "Value2"/.test(js));
  assert.ok(js.includes("EXCEL_SMART_FILL_SOURCE_TRUNCATED"));
  [
    "EXCEL_SMART_FILL_TARGET_SHAPE_INVALID",
    "EXCEL_SMART_FILL_CROSS_SHEET",
    "EXCEL_SMART_FILL_INSTRUCTION_REQUIRED",
    "EXCEL_SMART_FILL_INSTRUCTION_TOO_LONG",
    "EXCEL_SMART_FILL_SOURCE_TRUNCATED",
    "EXCEL_SMART_FILL_SOURCE_SHAPE_INVALID",
    "EXCEL_SMART_FILL_RESULT_TOO_LARGE",
    "EXCEL_SMART_FILL_CONTEXT_TOO_LARGE"
  ].forEach((code) => assert.ok(js.includes(code), `missing smart fill fatal error code: ${code}`));
  assert.ok(!/\.Formula\s*=/.test(js), "smart fill taskpane must never write Formula");
}

function testSmartFillJobLifecycleAndCancellationContract() {
  assert.ok(html.includes('id="btn-cancel-excel-smart-fill-job"'), "HTML must include cancel button for smart fill");
  assert.ok(html.includes('id="btn-resubmit-interrupted-smart-fill-job"'), "HTML must include resubmit button for interrupted smart fill");
  assert.ok(js.includes("cancelExcelSmartFillJob"), "taskpane.js must define cancelExcelSmartFillJob");
  assert.ok(js.includes("finishCancelledExcelSmartFill"), "taskpane.js must define finishCancelledExcelSmartFill");
  assert.ok(js.includes("setExcelSmartFillCancelVisible"), "taskpane.js must control cancel button visibility");
  assert.ok(js.includes("renderExcelSmartFillJobProgress"), "taskpane.js must render job progress without text leaks");
  assert.ok(js.includes("pollExcelSmartFillJob"), "taskpane.js must support background job polling");
  assert.ok(js.includes("resumeExcelSmartFillActiveJob"), "taskpane.js must resume active jobs on reopen");
  assert.ok(js.includes("saveExcelSmartFillActiveJob"), "taskpane.js must persist active job metadata");
  assert.ok(js.includes("loadExcelSmartFillActiveJob"), "taskpane.js must load active job metadata");
  assert.ok(js.includes("clearExcelSmartFillActiveJob"), "taskpane.js must clear active job metadata on terminal");
  assert.ok(js.includes("EXCEL_SMART_FILL_JOB_INTERRUPTED"), "taskpane.js must handle adapter restart interruption");
  assert.ok(js.includes("EXCEL_SMART_FILL_JOB_NOT_FOUND"), "taskpane.js must handle job not found");
  assert.ok(js.includes("ai-wps-excel-smart-fill-active-job-v1"), "localStorage key must be ai-wps-excel-smart-fill-active-job-v1");

  // Verify that progress rendering only shows stage, timing, and IDs, without leaking payload content
  const progressMatch = js.match(/function renderExcelSmartFillJobProgress\([^)]*\)\s*\{([\s\S]*?)\n  \}/);
  assert.ok(progressMatch, "renderExcelSmartFillJobProgress function body must be extractable");
  const progressBody = progressMatch[1];
  assert.ok(progressBody.includes("job.status === \"queued\""), "must differentiate queued status");
  assert.ok(progressBody.includes("job.queuePosition"), "must display queue position when queued");
  assert.ok(progressBody.includes("总耗时："), "must display total elapsed time");
  assert.ok(progressBody.includes("本阶段耗时："), "must display phase elapsed time");
  assert.ok(progressBody.includes("adapter 等待预算："), "must display provider timeout budget");
  assert.ok(progressBody.includes("任务编号："), "must display job ID");
  assert.ok(!progressBody.includes("rows"), "progress rendering must not reference source rows");
  assert.ok(!progressBody.includes("userInstruction"), "progress rendering must not reference user instruction");
  assert.ok(!progressBody.includes("items"), "progress rendering must not reference item contents");
}

function testSmartFillPartialPreviewContract() {
  assert.ok(js.includes("stopReason"), "taskpane.js must recognize stopReason in job results");
  assert.ok(js.includes("partial"), "taskpane.js must recognize partial flag in job results");
  assert.ok(js.includes("智能填写任务已取消，已保留部分预览；未完成项不会写入。"), "must inform user on cancellation with partial preview");
  assert.ok(js.includes("智能填写任务失败，已保留部分预览；未完成项不会写入。"), "must inform user on timeout/failure with partial preview");

  // Test that helper formats partial preview correctly
  const fullResult = {
    schemaVersion: "excel.smart_fill.v1",
    items: [
      { itemId: "target-1", status: "completed", valueType: "text", value: "已生成标签" },
      { itemId: "target-2", status: "insufficient_information", valueType: "text", value: "" }
    ],
    partial: true,
    stopReason: "cancelled"
  };
  const targets = [
    { itemId: "target-1", address: "$B$2" },
    { itemId: "target-2", address: "$B$3" }
  ];
  const previewHtml = helpers.buildExcelSmartFillReadonlyPreview(fullResult, targets);
  assert.ok(previewHtml.includes("已生成标签"), "must render completed item value");
  assert.ok(previewHtml.includes("可写入"), "must render completed status as 可写入");
  assert.ok(previewHtml.includes("信息不足"), "must render insufficient item status as 信息不足");
  assert.ok(previewHtml.includes("$B$2"), "must include item 1 address");
  assert.ok(previewHtml.includes("$B$3"), "must include item 2 address");
}

function testSmartFillUnprocessedReadonlyPreview() {
  const partialResult = {
    schemaVersion: "excel.smart_fill.v1",
    items: [
      { itemId: "target-1", status: "completed", valueType: "text", value: "已生成标签" },
      { itemId: "target-2", status: "unprocessed", valueType: "text", value: "" }
    ],
    partial: true,
    stopReason: "cancelled"
  };
  const targets = [
    { itemId: "target-1", address: "$B$2" },
    { itemId: "target-2", address: "$B$3" }
  ];
  const previewHtml = helpers.buildExcelSmartFillReadonlyPreview(partialResult, targets);
  assert.ok(previewHtml.includes("已生成标签"), "must render completed item value");
  assert.ok(previewHtml.includes("可写入"), "must render completed status as 可写入");
  assert.ok(previewHtml.includes("未处理"), "must render unprocessed item status as 未处理");
  assert.ok(previewHtml.includes("is-unprocessed"), "must apply is-unprocessed class to unprocessed item");
  assert.ok(!previewHtml.includes("信息不足"), "unprocessed item must NOT be rendered as 信息不足");
}

function testSmartFillProgressBatchDisplay() {
  const progressMatch = js.match(/function renderExcelSmartFillJobProgress\([^)]*\)\s*\{([\s\S]*?)\n  \}/);
  assert.ok(progressMatch, "renderExcelSmartFillJobProgress function body must be extractable");
  const progressBody = progressMatch[1];
  assert.ok(progressBody.includes("job.totalBatches"), "must check totalBatches for multi-batch progress");
  assert.ok(progressBody.includes("批次进度：第 "), "must format batch progress line");
  assert.ok(progressBody.includes(" 批 / 共 "), "must format total batch count");
}

function testSmartFillCancellationCooperativeNotice() {
  assert.ok(
    js.includes("智能填写正在停止，当前批次完成后将保留部分预览。"),
    "taskpane.js must inform user when cancellation is requested on a running job"
  );
  assert.ok(
    js.includes("cancelRequested"),
    "taskpane.js must check cancelRequested property"
  );
}

function testSmartFillEditorPreviewRendersEditableFieldsCheckboxesAndRetryButtons() {
  assert.strictEqual(typeof helpers.buildExcelSmartFillEditorPreview, "function");
  const data = {
    schemaVersion: "excel.smart_fill.v1",
    items: [
      { itemId: "target-1", status: "completed", valueType: "text", value: "甲类" },
      { itemId: "target-2", status: "insufficient_information", valueType: "text", value: "" },
      { itemId: "target-3", status: "failed", valueType: "text", value: "" },
      { itemId: "target-4", status: "unprocessed", valueType: "text", value: "" },
      { itemId: "target-5", status: "write_conflict", valueType: "text", value: "旧值" }
    ]
  };
  const targets = [
    { itemId: "target-1", address: "$D$2" },
    { itemId: "target-2", address: "$D$3" },
    { itemId: "target-3", address: "$D$4" },
    { itemId: "target-4", address: "$D$5" },
    { itemId: "target-5", address: "$D$6" }
  ];
  const drafts = [
    { itemId: "target-1", status: "completed", valueType: "text", value: "已编辑甲类", selected: true },
    { itemId: "target-2", status: "insufficient_information", valueType: "text", value: "", selected: false },
    { itemId: "target-3", status: "failed", valueType: "text", value: "", selected: false },
    { itemId: "target-4", status: "unprocessed", valueType: "text", value: "", selected: false },
    { itemId: "target-5", status: "write_conflict", valueType: "text", value: "冲突值", selected: false }
  ];
  const html = helpers.buildExcelSmartFillEditorPreview(data, targets, drafts);

  assert.ok(html.includes("智能填写预览"));
  assert.ok(html.includes("可编辑、取消勾选或逐项重试"));

  // Check inputs and checkboxes
  assert.ok(html.includes('data-smart-fill-select="target-1"'));
  assert.ok(html.includes('data-smart-fill-value-input="target-1"'));
  assert.ok(html.includes('value="已编辑甲类"'));
  assert.ok(html.includes('aria-label="选择 $D$2"'));
  assert.ok(html.includes('aria-label="编辑 $D$2"'));

  // Check status badges
  assert.ok(html.includes("is-complete") && html.includes("可写入"));
  assert.ok(html.includes("is-insufficient") && html.includes("信息不足"));
  assert.ok(html.includes("is-failed") && html.includes("失败"));
  assert.ok(html.includes("is-unprocessed") && html.includes("未处理"));
  assert.ok(html.includes("is-conflict") && html.includes("写入冲突"));

  // Check retry buttons
  assert.ok(html.includes('data-smart-fill-retry="target-1"'));
  assert.ok(html.includes('data-smart-fill-retry="target-2"'));
  assert.ok(html.includes('data-smart-fill-retry="target-3"'));
  assert.ok(html.includes('data-smart-fill-retry="target-4"'));
  assert.ok(html.includes('data-smart-fill-retry="target-5"'));
  assert.ok(html.includes("重新生成此项"));
}

function testSmartFillDraftValidationAndCapacityConstraints() {
  assert.strictEqual(typeof helpers.validateExcelSmartFillDraft, "function");

  // Valid text
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "正常文本", valueType: "text"
  }).isWriteable, true);

  // Valid number
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "123.45", valueType: "number"
  }).isWriteable, true);

  // Invalid number
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "abc", valueType: "number"
  }).isWriteable, false);

  // Unselected draft
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: false, value: "正常文本", valueType: "text"
  }).isWriteable, false);

  // Empty string
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "   ", valueType: "text"
  }).isWriteable, false);

  // Exceeding 2000 code points per cell
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "a".repeat(2001), valueType: "text"
  }).isWriteable, false);

  // Emoji code point counting
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "😀".repeat(2000), valueType: "text"
  }).isWriteable, true);
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "😀".repeat(2001), valueType: "text"
  }).isWriteable, false);

  // Formula-like text is valid text
  assert.strictEqual(helpers.validateExcelSmartFillDraft({
    itemId: "target-1", selected: true, value: "=SUM(A1:A2)", valueType: "text"
  }).isWriteable, true);
}

function testSmartFillDraftsSummaryCalculation() {
  assert.strictEqual(typeof helpers.calculateExcelSmartFillDraftsSummary, "function");
  const drafts = [
    { itemId: "target-1", selected: true, value: "文本1", valueType: "text" },
    { itemId: "target-2", selected: true, value: "100", valueType: "number" },
    { itemId: "target-3", selected: false, value: "文本3", valueType: "text" },
    { itemId: "target-4", selected: true, value: "", valueType: "text" }
  ];
  const targetItems = [
    { itemId: "target-1", originalValue: "旧值1", originalValueType: "text" },
    { itemId: "target-2", originalValue: "", originalValueType: "blank" },
    { itemId: "target-3", originalValue: "旧值3", originalValueType: "text" },
    { itemId: "target-4", originalValue: "", originalValueType: "blank" }
  ];
  const summary = helpers.calculateExcelSmartFillDraftsSummary(drafts, targetItems);
  assert.strictEqual(summary.writableCount, 2);
  assert.strictEqual(summary.overwriteCount, 1);
  assert.strictEqual(summary.canWrite, true);
  assert.strictEqual(summary.summaryText, "将写入 2 个单元格；未勾选或信息不足项不会写入。");
}

testSmartFillDefaultSourceUsesHeaderAndCurrentRowOnly();
testSmartFillDefaultSourceKeepsARowForEachTargetItem();
testHostDisplayedEmptyDoesNotFallBackToRawValue();
testSuccessfulWriteStillConsumesPreviewIfConsumeWouldThrow();
testSmartFillReadonlyPreviewOmitsEditingAndUndo();
testSmartFillPreviewCannotBeSubmittedTwice();
testSmartFillPayloadCapturesFrozenSnapshots();
testSmartFillWritebackGuardsSnapshotAndFormulaSafety();
testSmartFillWritesFormulaLikeTextAsLiteralAndReportsRollbackAddresses();
testSmartFillFailsClosedWhenHostSafetyPropertiesCannotBeRead();
testSmartFillExcludesHiddenSourceValuesAndValidatesTargetShape();
testSmartFillExtractionFailsClosedOnUnreadableHostFlags();
testSmartFillExtractionFailsClosedOnOversizedCellText();
testSmartFillExtractionFailsClosedOnOversizedSourceRange();
testSmartFillCustomSourceBlanksTargetCurrentValues();
testSmartFillInstructionRejectsMoreThan4000CodePoints();
testSmartFillPreviewKeepsFailedInsufficientAndCompletedStatuses();
testSmartFillRejectsNonContiguousSourceAreas();
testSmartFillSanitizeHelperBlanksOverlappingTargetColumn();
testSmartFillSanitizeFailsClosedOnUnparseableCustomSourceAddress();
testSmartFillSanitizeBlanksDefaultSourceWhenAddressIsEmpty();
testSmartFillSourceTextDoesNotFallBackToRawValue();
testSmartFillSourceTextMissingDoesNotUseValue2();
testWritePreflightHashMatchesSanitizedCapture();
testSmartFillUiContract();
testSmartFillJobLifecycleAndCancellationContract();
testSmartFillPartialPreviewContract();
testSmartFillUnprocessedReadonlyPreview();
testSmartFillProgressBatchDisplay();
testSmartFillCancellationCooperativeNotice();
testSmartFillEditorPreviewRendersEditableFieldsCheckboxesAndRetryButtons();
testSmartFillDraftValidationAndCapacityConstraints();
testSmartFillDraftsSummaryCalculation();
console.log("Excel smart fill tests passed");
