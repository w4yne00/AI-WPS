const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { etRoot: root } = require("./support/plugin-roots");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const css = fs.readFileSync(path.join(root, "taskpane.css"), "utf8");
const ribbon = fs.readFileSync(path.join(root, "ribbon.xml"), "utf8");
const ribbonJs = fs.readFileSync(path.join(root, "ribbon.js"), "utf8");
const helperJs = fs.readFileSync(path.join(root, "taskpane-helpers.js"), "utf8");
const helpers = require(path.join(root, "taskpane-helpers.js"));

function functionSource(name) {
  const start = js.indexOf(`  function ${name}(`);
  assert.notStrictEqual(start, -1, `missing function ${name}`);
  const next = js.indexOf("\n  function ", start + 3);
  return js.slice(start, next === -1 ? js.length : next);
}

function buildFunction(names, dependencies, resultName) {
  const source = names.map(functionSource).join("\n");
  const dependencyNames = Object.keys(dependencies);
  return Function(...dependencyNames, `${source}\nreturn ${resultName};`)(
    ...dependencyNames.map((name) => dependencies[name])
  );
}

function createFormulaModeHarness() {
  const nodes = {
    "excel-formula-requirement-label": { textContent: "" },
    "excel-formula-requirement": {
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; }
    },
    "btn-run-primary": { textContent: "" }
  };
  const buttons = ["generate", "explain"].map((mode) => ({
    mode,
    attributes: { "data-formula-mode": mode },
    classList: { toggle() {} },
    focused: false,
    getAttribute(name) { return this.attributes[name]; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; }
  }));
  const state = { formulaMode: "generate", currentMode: "excelFormulaAssistant" };
  const document = { querySelectorAll() { return buttons; } };
  const byId = (id) => nodes[id];
  const setMode = buildFunction(
    ["getFormulaModeUi", "setFormulaAssistantMode"],
    { state, document, byId, FORMULA_MODE_UI: {
      generate: {
        requirementLabel: "计算需求",
        placeholder: "生成占位",
        actionLabel: "生成推荐公式"
      },
      explain: {
        requirementLabel: "排错说明（选填）",
        placeholder: "解释占位",
        actionLabel: "解释并排错"
      }
    } },
    "setFormulaAssistantMode"
  );
  return { nodes, buttons, state, document, byId, setMode };
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

  const formulaFallbackRange = {
    Address: "$A$1:$C$1",
    Rows: { Count: 1 },
    Columns: { Count: 3 },
    Cells: {
      Item(_row, column) {
        if (column === 1) {
          return {
            Address: "$A$1",
            Text: "3",
            Value2: 3,
            HasFormula: true,
            Formula: "",
            FormulaLocal: "=SUMME(A2:A3)"
          };
        }
        if (column === 2) {
          return {
            Address: "$B$1",
            Text: "6",
            Value2: 6,
            HasFormula() { return -1; },
            Formula: "",
            FormulaLocal: "",
            FormulaR1C1: "=RC[-1]*2"
          };
        }
        return {
          Address: "$C$1",
          Text: "=A1",
          Value2: "=A1",
          HasFormula: false,
          Formula: "=A1"
        };
      }
    }
  };
  const fallbackSelection = helpers.extractExcelFormulaSelection(
    formulaFallbackRange,
    { sheetName: "降级路径" }
  );
  assert.strictEqual(fallbackSelection.cells[0][0].formula, "=SUMME(A2:A3)");
  assert.strictEqual(fallbackSelection.cells[0][0].valueType, "formula");
  assert.strictEqual(fallbackSelection.cells[0][1].formula, "=RC[-1]*2");
  assert.strictEqual(fallbackSelection.cells[0][1].valueType, "formula");
  assert.strictEqual(fallbackSelection.cells[0][2].formula, "");
  assert.strictEqual(fallbackSelection.cells[0][2].valueType, "text");
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
  const excelRuntime = `${js}\n${helperJs}`;
  assert.ok(!/\.Formula\s*=/.test(excelRuntime), "Formula Assistant must not write Formula");
  assert.ok(!/\.FormulaLocal\s*=/.test(excelRuntime), "Formula Assistant must not write FormulaLocal");
  assert.ok(!/\.FormulaR1C1\s*=/.test(excelRuntime), "Formula Assistant must not write FormulaR1C1");
  assert.ok(!/\.Calculation(?:Mode)?\s*=/.test(excelRuntime), "Formula Assistant must not change calculation state");
  assert.ok(!/Worksheets\.Add|Sheets\.Add/.test(excelRuntime), "Formula Assistant must not create sheets");
}

function testFormulaAssistantModeResultAndAccessibilityContracts() {
  assert.ok(html.includes('id="excel-formula-mode-segment"'));
  assert.ok(html.includes('role="tablist" aria-label="公式助手模式"'));
  assert.ok(html.includes('data-formula-mode="generate"'));
  assert.ok(html.includes('data-formula-mode="explain"'));
  assert.ok(html.includes('id="excel-formula-alternative"'));
  assert.ok(html.includes('id="excel-formula-alternative-code"'));

  const extract = functionSource("extractExcelFormulaRange");
  assert.ok(extract.includes("mode: state.formulaMode"));

  const selectMode = functionSource("setFormulaAssistantMode");
  assert.ok(selectMode.includes('setAttribute("aria-selected"'));
  assert.ok(selectMode.includes('setAttribute("tabindex"'));
  assert.ok(selectMode.includes("modeUi.requirementLabel"));
  assert.ok(js.includes('requirementLabel: "计算需求"'));
  assert.ok(js.includes('requirementLabel: "排错说明（选填）"'));

  const keyboard = functionSource("handleFormulaModeKeydown");
  ["ArrowLeft", "ArrowRight", "Home", "End"].forEach((key) => {
    assert.ok(keyboard.includes(key), `formula mode keyboard contract missing ${key}`);
  });

  const render = functionSource("buildExcelFormulaMarkdown");
  [
    "originalFormula",
    "components",
    "referenceRanges",
    "issues",
    "localCheck",
    "parseDiagnostic",
    "rawFinalResult"
  ].forEach((field) => assert.ok(render.includes(field), `result contract missing ${field}`));

  const copy = functionSource("copyPrimaryFormula");
  assert.ok(copy.includes("formulaResult.copyText"));
  assert.ok(copy.includes("原始结果已复制"));
  assert.ok(css.includes(".formula-mode-segment"));
  assert.ok(css.includes(".formula-alternative"));
  assert.ok(css.includes("@media (max-width: 420px)"));
}

function testFormulaModeSwitchAndKeyboardBehavior() {
  const harness = createFormulaModeHarness();
  harness.setMode("explain", true);
  assert.strictEqual(harness.state.formulaMode, "explain");
  assert.strictEqual(harness.buttons[1].attributes["aria-selected"], "true");
  assert.strictEqual(harness.buttons[1].attributes.tabindex, "0");
  assert.strictEqual(harness.nodes["excel-formula-requirement-label"].textContent, "排错说明（选填）");
  assert.strictEqual(harness.nodes["btn-run-primary"].textContent, "解释并排错");
  assert.strictEqual(harness.buttons[1].focused, true);

  const keydown = buildFunction(
    ["handleFormulaModeKeydown"],
    {
      document: harness.document,
      setFormulaAssistantMode: harness.setMode
    },
    "handleFormulaModeKeydown"
  );
  let prevented = false;
  keydown({ key: "Home", target: harness.buttons[1], preventDefault() { prevented = true; } });
  assert.strictEqual(prevented, true);
  assert.strictEqual(harness.state.formulaMode, "generate");
  assert.strictEqual(harness.buttons[0].focused, true);
}

function testFormulaCopyBehaviorAndNarrowLayoutContract() {
  function executeCopy(result) {
    const state = { formulaResult: result };
    let copied = "";
    let status = "";
    const copy = buildFunction(
      ["copyPrimaryFormula"],
      {
        state,
        navigator: {},
        setStatus(message) { status = message; },
        fallbackCopy(text, feedback) { copied = text; feedback(); }
      },
      "copyPrimaryFormula"
    );
    copy();
    return { copied, status };
  }

  assert.deepStrictEqual(
    executeCopy({ primaryFormula: "=SUM(B2:B3)", copyText: "=SUM(B2:B3)" }),
    { copied: "=SUM(B2:B3)", status: "主公式已复制，工作簿未被修改。" }
  );
  assert.deepStrictEqual(
    executeCopy({ parseDiagnostic: "解析失败", copyText: "原始最终结果" }),
    { copied: "原始最终结果", status: "原始结果已复制，请人工核对。" }
  );
  assert.match(css, /\.formula-mode-segment\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css, /@media \(max-width: 420px\)[\s\S]*?\.formula-mode-segment\s*\{[\s\S]*?width:\s*100%/);
}

function testStructuredResultKeepsFullExplanationCopyContract() {
  const nodes = {
    "result-view-switch": { hidden: false },
    "btn-copy-formula": {
      hidden: true,
      textContent: "",
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; }
    },
    "excel-formula-alternative": { hidden: true, open: false },
    "excel-formula-alternative-code": { textContent: "" }
  };
  const state = { formulaResult: null };
  let copiedText = "";
  const render = buildFunction(
    ["setExcelResultViewSwitchForMode", "renderExcelFormulaResult"],
    {
      state,
      helpers: {
        shouldShowExcelResultViewSwitch: function (mode) {
          return mode === "excelAnalysis";
        }
      },
      byId(id) { return nodes[id]; },
      buildExcelFormulaMarkdown() { return "完整公式解释"; },
      setResult(markdown, copyText) { copiedText = copyText; }
    },
    "renderExcelFormulaResult"
  );

  render({ primaryFormula: "=SUM(B2:B3)", copyText: "=SUM(B2:B3)" });
  assert.strictEqual(copiedText, "完整公式解释");
  assert.strictEqual(nodes["btn-copy-formula"].hidden, false);
  assert.strictEqual(nodes["result-view-switch"].hidden, true);

  render({ parseDiagnostic: "解析失败", rawFinalResult: "原始结果", copyText: "原始结果" });
  assert.strictEqual(copiedText, "原始结果");
  assert.strictEqual(nodes["btn-copy-formula"].textContent, "复制原始结果");
}

testBoundedExplicitSelectionExtraction();
testFormulaAssistantTaskAndReadOnlyContracts();
testFormulaAssistantModeResultAndAccessibilityContracts();
testFormulaModeSwitchAndKeyboardBehavior();
testFormulaCopyBehaviorAndNarrowLayoutContract();
testStructuredResultKeepsFullExplanationCopyContract();

console.log("Excel formula assistant tests passed");
