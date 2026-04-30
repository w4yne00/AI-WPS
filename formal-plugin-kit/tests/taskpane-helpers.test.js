const assert = require("assert");
const helpers = require("../wps-ai-assistant_1.0.0/taskpane-helpers.js");

function testGetEffectiveSelectionText() {
  assert.strictEqual(
    helpers.getEffectiveSelectionText({
      Text: "  已选中的文字  "
    }),
    "已选中的文字"
  );
  assert.strictEqual(
    helpers.getEffectiveSelectionText({
      Range: {
        Text: "\n\n第二种选区来源\n"
      }
    }),
    "第二种选区来源"
  );
  assert.strictEqual(helpers.getEffectiveSelectionText({ Text: "   " }), "");
  assert.strictEqual(
    helpers.getEffectiveSelectionText([
      null,
      { Text: "" },
      { Range: { Text: " 来自 Application.Selection " } }
    ]),
    "来自 Application.Selection"
  );
}

function testResolveRewriteScope() {
  const selectionScope = helpers.resolveRewriteScope({
    selectionText: "已选中段落",
    requireSelection: true
  });
  assert.strictEqual(selectionScope.selectionMode, "selection");
  assert.strictEqual(selectionScope.scopeLabel, "当前范围：选中文本");

  const missingSelection = helpers.resolveRewriteScope({
    selectionText: "",
    requireSelection: true
  });
  assert.strictEqual(missingSelection.ok, false);
  assert.ok(missingSelection.message.includes("请先用鼠标选中"));
}

function testSelectionWritebackGuard() {
  const matched = helpers.canApplyRewriteToSelection("原文", " 原文 ");
  assert.strictEqual(matched.ok, true);

  const changed = helpers.canApplyRewriteToSelection("原文", "别的内容");
  assert.strictEqual(changed.ok, false);
  assert.ok(changed.message.includes("选区已变化"));
}

function testGetWritableSelection() {
  const target = helpers.getWritableSelection([
    null,
    { Range: { Text: "abc" } },
    { Text: "later" }
  ]);
  assert.ok(target);
  assert.strictEqual(target.Range.Text, "abc");
}

testGetEffectiveSelectionText();
testResolveRewriteScope();
testSelectionWritebackGuard();
testGetWritableSelection();

console.log("taskpane-helpers tests passed");
