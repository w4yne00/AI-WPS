const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const css = fs.readFileSync(path.join(root, "taskpane.css"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function buildRange(address, values, extras) {
  const rows = values.length;
  const columns = values[0].length;
  const cells = {};
  const options = extras || {};
  values.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
    const sheetRow = rowIndex + 1;
    const sheetColumn = columnIndex + 1;
    const cellAddress = `$${String.fromCharCode(65 + columnIndex)}$${sheetRow}`;
    cells[`${sheetRow},${sheetColumn}`] = {
      Address: cellAddress,
      Text: String(value == null ? "" : value),
      Value2: value,
      Formula: "",
      HasFormula: false,
      MergeCells: false,
      Locked: false,
      Hidden: false,
      Row: sheetRow,
      Column: sheetColumn,
      EntireRow: { Hidden: false },
      EntireColumn: { Hidden: false }
    };
  }));
  return {
    Address: address,
    Worksheet: { Name: options.sheetName || "客户表" },
    Rows: { Count: rows },
    Columns: { Count: columns },
    Areas: { Count: options.areaCount || 1 },
    Cells: {
      Item(row, column) {
        return cells[`${row},${column}`];
      }
    }
  };
}

function sequentialItemIdFactory() {
  let n = 0;
  return function createItemId() {
    n += 1;
    return "sf_" + String(n).padStart(32, "0");
  };
}

function testLiveSourceSummaryUsesSheetAddressHeadersAndDataRows() {
  assert.strictEqual(typeof helpers.inspectExcelSmartFillSourceSelection, "function");
  const source = buildRange("$A$1:$C$11", [
    ["姓名", "部门", "城市"],
    ["张三", "研发", "北京"],
    ["李四", "销售", "上海"],
    ["王五", "运营", "广州"],
    ["赵六", "人事", "成都"],
    ["钱七", "财务", "武汉"],
    ["孙八", "法务", "南京"],
    ["周九", "采购", "杭州"],
    ["吴十", "质量", "西安"],
    ["郑十一", "客服", "长沙"],
    ["冯十二", "行政", "郑州"]
  ]);
  const inspection = helpers.inspectExcelSmartFillSourceSelection(source);
  assert.strictEqual(inspection.ok, true);
  assert.strictEqual(inspection.summary, "数据范围：客户表!A1:C11 · 1 行表头 · 10 行数据");
  assert.strictEqual(inspection.sheetName, "客户表");
  assert.strictEqual(inspection.address, "A1:C11");
  assert.strictEqual(inspection.headerCount, 1);
  assert.strictEqual(inspection.dataRowCount, 10);
  assert.strictEqual(inspection.error, "");
  assert.ok(!Object.prototype.hasOwnProperty.call(inspection, "items"));
  assert.ok(!Object.prototype.hasOwnProperty.call(inspection, "snapshotHash"));
}

function testInspectingSelectionDoesNotCreateASourceSnapshot() {
  const source = buildRange("$A$1:$B$3", [["姓名", "部门"], ["张三", "研发"], ["李四", "销售"]]);
  const first = helpers.inspectExcelSmartFillSourceSelection(source);
  source.Cells.Item(2, 1).Text = "被改写";
  const second = helpers.inspectExcelSmartFillSourceSelection(source);
  assert.deepStrictEqual(Object.keys(first).sort(), Object.keys(second).sort());
  assert.ok(!first.items);
  assert.ok(!second.items);
  assert.notStrictEqual(first.summary, undefined);
}

function testGenerateFreezeCreatesOpaqueItemsWithoutTarget() {
  assert.strictEqual(typeof helpers.extractExcelSmartFillSourcePayload, "function");
  const source = buildRange("$A$1:$C$3", [
    ["姓名", "部门", "城市"],
    ["张三", "研发", "北京"],
    ["李四", "销售", "上海"]
  ]);
  const payload = helpers.extractExcelSmartFillSourcePayload(source, {
    workbookId: "book-1",
    createItemId: sequentialItemIdFactory()
  });
  assert.strictEqual(payload.target, undefined);
  assert.ok(!Object.prototype.hasOwnProperty.call(payload, "target"));
  assert.strictEqual(payload.source.sheetName, "客户表");
  assert.deepStrictEqual(payload.source.headers, ["姓名", "部门", "城市"]);
  assert.deepStrictEqual(payload.source.rows, [
    ["张三", "研发", "北京"],
    ["李四", "销售", "上海"]
  ]);
  assert.strictEqual(payload.items.length, 2);
  assert.strictEqual(payload.items[0].itemId, "sf_" + "1".padStart(32, "0"));
  assert.strictEqual(payload.items[1].itemId, "sf_" + "2".padStart(32, "0"));
  assert.strictEqual(payload.items[0].sourceRowIndex, 1);
  assert.strictEqual(payload.items[1].sourceRowIndex, 2);
  assert.strictEqual(payload.items[0].sourceRowLabel, "第 2 行");
  assert.strictEqual(payload.items[1].sourceRowLabel, "第 3 行");
  payload.items.forEach((item) => {
    assert.ok(!Object.prototype.hasOwnProperty.call(item, "address"));
    assert.ok(!Object.prototype.hasOwnProperty.call(item, "originalValue"));
    assert.ok(!/target-\d+/.test(item.itemId));
    assert.ok(!/\$[A-Z]+\$\d+/i.test(item.itemId));
    assert.ok(!/^row-\d+-col-\d+$/i.test(item.itemId));
  });
  assert.ok(!JSON.stringify(payload).includes("originalValue"));
}

function testCreatedItemIdsAreOpaqueAndDoNotEncodeAddresses() {
  assert.strictEqual(typeof helpers.createExcelSmartFillItemId, "function");
  const ids = new Set();
  for (let index = 0; index < 16; index += 1) {
    const itemId = helpers.createExcelSmartFillItemId();
    ids.add(itemId);
    assert.ok(/^sf_[0-9a-f]{32}$/.test(itemId), itemId);
    assert.ok(!/\$[A-Z]+\$\d+/i.test(itemId));
    assert.ok(!/^[A-Z]+\d+$/i.test(itemId));
  }
  assert.strictEqual(ids.size, 16);
}

function testHiddenFormulaAndCommentsStayOutOfFrozenSource() {
  const source = buildRange("$A$1:$B$3", [["姓名", "部门"], ["张三", "研发"], ["李四", "销售"]]);
  source.Cells.Item(2, 2).HasFormula = true;
  source.Cells.Item(2, 2).Formula = "=C2";
  source.Cells.Item(2, 2).Text = "不应外发的公式结果";
  source.Cells.Item(2, 2).Comment = { Text: "批注不应进入模型" };
  const payload = helpers.extractExcelSmartFillSourcePayload(source, {
    createItemId: sequentialItemIdFactory()
  });
  assert.deepStrictEqual(payload.source.rows[0], ["张三", ""]);
  assert.ok(!JSON.stringify(payload.source).includes("不应外发的公式结果"));
  assert.ok(!JSON.stringify(payload).includes("批注不应进入模型"));
  assert.ok(!JSON.stringify(payload.source).includes("=C2"));
}

function expectSourceError(range, extras, pattern) {
  const inspection = helpers.inspectExcelSmartFillSourceSelection(range, extras);
  assert.strictEqual(inspection.ok, false);
  assert.match(inspection.error, pattern);
  assert.throws(
    () => helpers.extractExcelSmartFillSourcePayload(range, extras),
    pattern
  );
}

function testSourceErrorsUseOneHighestPriorityReason() {
  const headerOnly = buildRange("$A$1:$B$1", [["姓名", "部门"]]);
  expectSourceError(headerOnly, {}, /表头.*数据/);

  const nonContiguous = buildRange("$A$1:$B$2", [["姓名", "部门"], ["张三", "研发"]], { areaCount: 2 });
  expectSourceError(nonContiguous, {}, /连续/);

  const merged = buildRange("$A$1:$B$2", [["姓名", "部门"], ["张三", "研发"]]);
  merged.Cells.Item(2, 1).MergeCells = true;
  expectSourceError(merged, {}, /合并/);

  const hidden = buildRange("$A$1:$B$2", [["姓名", "部门"], ["张三", "研发"]]);
  hidden.Cells.Item(2, 1).EntireRow.Hidden = true;
  expectSourceError(hidden, {}, /隐藏/);

  const mergedAndHidden = buildRange("$A$1:$B$2", [["姓名", "部门"], ["张三", "研发"]]);
  mergedAndHidden.Cells.Item(2, 1).MergeCells = true;
  mergedAndHidden.Cells.Item(2, 1).EntireRow.Hidden = true;
  const inspection = helpers.inspectExcelSmartFillSourceSelection(mergedAndHidden);
  assert.strictEqual(inspection.ok, false);
  assert.match(inspection.error, /合并/);
  assert.ok(!/隐藏/.test(inspection.error));

  const values = [["表头"]];
  for (let index = 0; index < 501; index += 1) {
    values.push(["行" + index]);
  }
  const oversized = buildRange("$A$1:$A$502", values);
  expectSourceError(oversized, { maxSourceRows: 500 }, /500/);
}

function testInstructionIsRequiredAndNotInferred() {
  assert.strictEqual(typeof helpers.requireExcelSmartFillInstruction, "function");
  assert.throws(() => helpers.requireExcelSmartFillInstruction(""), /需要生成什么/);
  assert.throws(() => helpers.requireExcelSmartFillInstruction("   "), /需要生成什么/);
  assert.strictEqual(helpers.requireExcelSmartFillInstruction("按部门生成标签"), "按部门生成标签");
}

function testPreviewKeepsSourceOrderEditExcludeAndFailedSlots() {
  const data = {
    schemaVersion: "excel.smart_fill.v2",
    items: [
      { itemId: "sf_" + "1".padStart(32, "0"), status: "completed", valueType: "text", value: "甲类" },
      { itemId: "sf_" + "2".padStart(32, "0"), status: "failed", valueType: "text", value: "" },
      { itemId: "sf_" + "3".padStart(32, "0"), status: "unprocessed", valueType: "text", value: "" }
    ]
  };
  const rows = [
    { itemId: "sf_" + "1".padStart(32, "0"), sourceRowLabel: "第 2 行" },
    { itemId: "sf_" + "2".padStart(32, "0"), sourceRowLabel: "第 3 行" },
    { itemId: "sf_" + "3".padStart(32, "0"), sourceRowLabel: "第 4 行" }
  ];
  const drafts = [
    { itemId: "sf_" + "1".padStart(32, "0"), status: "completed", valueType: "text", value: "已编辑甲类", selected: true },
    { itemId: "sf_" + "2".padStart(32, "0"), status: "failed", valueType: "text", value: "", selected: false },
    { itemId: "sf_" + "3".padStart(32, "0"), status: "unprocessed", valueType: "text", value: "", selected: false }
  ];
  const preview = helpers.buildExcelSmartFillEditorPreview(data, rows, drafts);
  assert.ok(preview.includes("第 2 行"));
  assert.ok(preview.includes("第 3 行"));
  assert.ok(preview.includes("第 4 行"));
  assert.ok(preview.includes("已编辑甲类"));
  assert.ok(preview.includes("失败"));
  assert.ok(preview.includes("未处理"));
  assert.ok(preview.includes("data-smart-fill-select="));
  assert.ok(!preview.includes("$D$"));
  assert.ok(!preview.includes("target-1"));
  assert.ok(!/draggable\s*=/.test(preview));
  const order = Array.from(preview.matchAll(/data-smart-fill-item-id="([^"]+)"/g)).map((match) => match[1]);
  assert.deepStrictEqual(order, rows.map((row) => row.itemId));
}

function testTaskPageDropsTargetFirstChrome() {
  const smartFillBlock = html.slice(
    html.indexOf('id="excel-smart-fill-options"'),
    html.indexOf('id="excel-formula-options"') > html.indexOf('id="excel-smart-fill-options"')
      ? html.indexOf("</div>", html.indexOf('id="excel-smart-fill-instruction"'))
      : html.length
  );
  assert.ok(html.includes("需要生成什么？"));
  assert.ok(html.includes('id="smart-fill-source-summary"'));
  assert.ok(!html.includes('id="btn-capture-smart-fill-target"'));
  assert.ok(!html.includes('id="btn-capture-smart-fill-source"'));
  assert.ok(!/智能填写只使用目标区域/.test(html));
  assert.ok(!html.includes("填写规则"));
  assert.ok(!/placeholder="[^"]*目标区域/.test(html));
  assert.ok(/excel-smart-fill-instruction[\s\S]*placeholder="例如：/.test(html));
  assert.ok(!js.includes("function captureExcelSmartFillTarget"));
  assert.ok(!js.includes("请先捕获目标区域"));
  assert.ok(js.includes("inspectExcelSmartFillSourceSelection"));
  assert.ok(js.includes("extractExcelSmartFillSourcePayload"));
  assert.ok(js.includes("requireExcelSmartFillInstruction"));
  assert.ok(!/target:\s*requestTarget/.test(js));
  assert.ok(js.includes("scope-strip") && /scope-strip[\s\S]{0,80}hidden/.test(js));
}

function testSmartFillPageUsesConfirmedButtonGeometry() {
  assert.ok(/body\[data-task-mode="excelSmartFill"\][\s\S]*#btn-run-primary[\s\S]*min-height:\s*44px/.test(css));
  assert.ok(/body\[data-task-mode="excelSmartFill"\][\s\S]*\.secondary-action[\s\S]*min-height:\s*36px/.test(css));
  assert.ok(/button:active:not\(:disabled\)[\s\S]*100ms/.test(css));
  assert.ok(css.includes("@media (prefers-reduced-motion: reduce)"));
  assert.ok(css.includes("@media (max-width: 320px)") || css.includes("@media (max-width: 420px)"));
}

function testWriteEntryStaysUnavailableWithoutTargetMapping() {
  assert.ok(/id="btn-write-smart-fill"[^>]*hidden/.test(html));
  assert.ok(/id="btn-write-smart-fill"[^>]*disabled/.test(html));
  assert.ok(html.includes("生成预览"));
  assert.ok(html.includes("本步骤不选择写入位置"));
  assert.ok(js.includes("tryRebindSmartFillTarget"));
  assert.ok(/function tryRebindSmartFillTarget[\s\S]{0,80}return false/.test(js));
  assert.ok(!js.includes("确认无误后点击“写入内容”"));
  assert.ok(js.includes("写入位置在后续步骤选择"));
  assert.ok(js.includes("writeBound"));
}

testLiveSourceSummaryUsesSheetAddressHeadersAndDataRows();
testInspectingSelectionDoesNotCreateASourceSnapshot();
testGenerateFreezeCreatesOpaqueItemsWithoutTarget();
testCreatedItemIdsAreOpaqueAndDoNotEncodeAddresses();
testHiddenFormulaAndCommentsStayOutOfFrozenSource();
testSourceErrorsUseOneHighestPriorityReason();
testInstructionIsRequiredAndNotInferred();
testPreviewKeepsSourceOrderEditExcludeAndFailedSlots();
testTaskPageDropsTargetFirstChrome();
testSmartFillPageUsesConfirmedButtonGeometry();
testWriteEntryStaysUnavailableWithoutTargetMapping();
console.log("Excel smart fill source-first tests passed");
