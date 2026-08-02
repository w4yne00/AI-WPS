const assert = require("assert");
const fs = require("fs");

const root = "formal-plugin-kit/wps-ai-assistant-et_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const ribbon = fs.readFileSync(`${root}/ribbon.xml`, "utf8");
const ribbonJs = fs.readFileSync(`${root}/ribbon.js`, "utf8");
const helpers = require(`../wps-ai-assistant-et_1.0.0/taskpane-helpers.js`);

function functionSource(name) {
  const start = js.indexOf(`  function ${name}(`);
  assert.notStrictEqual(start, -1, `missing function ${name}`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

function buildRange(rowCount, columnCount) {
  const cells = {};
  for (let row = 1; row <= rowCount; row += 1) {
    for (let column = 1; column <= columnCount; column += 1) {
      const key = `${row},${column}`;
      cells[key] = {
        Address: `$${String.fromCharCode(64 + Math.min(column, 26))}$${row}`,
        Text: row === 1 ? `表头${column}` : `${row * column}`,
        Value2: row === 1 ? `表头${column}` : row * column,
        Formula: row === 3 && column === 2 ? "=B2*2" : ""
      };
    }
  }
  return {
    Address: "$A$1:$U$31",
    Rows: { Count: rowCount },
    Columns: { Count: columnCount },
    Cells: {
      Item(row, column) { return cells[`${row},${column}`]; }
    }
  };
}

function testBoundedExplicitSelectionExtraction() {
  assert.strictEqual(typeof helpers.extractExcelFormulaSelection, "function");
  const selection = helpers.extractExcelFormulaSelection(
    buildRange(31, 21),
    { sheetName: "统计表" }
  );

  assert.strictEqual(selection.sheetName, "统计表");
  assert.strictEqual(selection.address, "$A$1:$U$31");
  assert.strictEqual(selection.rowCount, 31);
  assert.strictEqual(selection.columnCount, 21);
  assert.strictEqual(selection.cells.length, 30);
  assert.strictEqual(selection.cells[0].length, 20);
  assert.strictEqual(selection.headers.length, 20);
  assert.strictEqual(selection.truncated, true);
  assert.deepStrictEqual(selection.cells[2][1], {
    address: "$B$3",
    text: "6",
    valueType: "formula",
    formula: "=B2*2"
  });

  assert.throws(
    () => helpers.extractExcelFormulaSelection(null, { sheetName: "统计表" }),
    /明确选区/
  );

  const callableCell = {
    Address() { return "$B$2"; },
    Text() { return "42"; },
    Value2() { return 42; },
    Formula() { return "=B1*2"; }
  };
  const callableCells = { Item() { return callableCell; } };
  const callableRange = {
    Address() { return "$B$2"; },
    Rows() { return { Count() { return 1; } }; },
    Columns() { return { Count() { return 1; } }; },
    Cells() { return callableCells; }
  };
  const callableSelection = helpers.extractExcelFormulaSelection(
    callableRange,
    { sheetName: "函数式属性" }
  );
  assert.strictEqual(callableSelection.address, "$B$2");
  assert.deepStrictEqual(callableSelection.cells[0][0], {
    address: "$B$2",
    text: "42",
    valueType: "formula",
    formula: "=B1*2"
  });
}

function testFormulaAssistantTaskAndReadOnlyContracts() {
  assert.ok(ribbon.includes('id="btnAiExcelFormulaAssistant" label="公式助手"'));
  assert.ok(ribbonJs.includes('btnAiExcelFormulaAssistant: "excelFormulaAssistant"'));
  assert.ok(html.includes('id="excel-formula-options"'));
  assert.ok(html.includes('id="excel-formula-requirement"'));
  assert.ok(html.includes('data-workflow-task-tab="excel.formula_assistant"'));
  assert.ok(html.includes('id="btn-copy-formula"'));

  const extract = functionSource("extractExcelFormulaRange");
  assert.ok(extract.includes("getSelectionRange(app)"));
  assert.ok(extract.includes("helpers.extractExcelFormulaSelection"));
  assert.ok(!extract.includes("getUsedRange"), "Formula Assistant must never fall back to UsedRange");

  const run = functionSource("runExcelFormulaAction");
  assert.ok(run.includes('request("/excel/formula-assistant/jobs"'));
  assert.ok(run.includes("extractExcelFormulaRange()"));
  assert.ok(run.includes("requirement"));

  assert.ok(js.includes('var EXCEL_FORMULA_WORKFLOW_TASK_TYPE = "excel.formula_assistant";'));
  assert.ok(js.includes('request("/excel/formula-assistant/jobs/"'));
  assert.ok(!/\.Formula\s*=/.test(js), "Formula Assistant must not write Formula");
  assert.ok(!/\.FormulaLocal\s*=/.test(js), "Formula Assistant must not write FormulaLocal");
  assert.ok(!/Worksheets\.Add|Sheets\.Add/.test(js), "Formula Assistant must not create sheets");
}

testBoundedExplicitSelectionExtraction();
testFormulaAssistantTaskAndReadOnlyContracts();

console.log("Excel formula assistant tests passed");
