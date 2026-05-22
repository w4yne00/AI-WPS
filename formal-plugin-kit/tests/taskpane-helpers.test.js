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
  assert.strictEqual(missingSelection.scopeLabel, "当前范围：全文");
  assert.ok(missingSelection.message.includes("请先用鼠标选中"));

  const cursorScope = helpers.resolveRewriteScope({
    selectionText: "",
    requireSelection: false
  });
  assert.strictEqual(cursorScope.ok, true);
  assert.strictEqual(cursorScope.selectionMode, "document");
  assert.strictEqual(cursorScope.scopeLabel, "当前范围：全文");
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

function testBuildDocumentStructureForProofread() {
  const structure = helpers.buildDocumentStructure({
    documentId: "安全运行方案.docx",
    templateId: "technical-file-format-requirements",
    selectionMode: "document",
    plainText: "一、总体要求\n正文内容",
    paragraphs: [
      {
        index: 1,
        text: "一、总体要求",
        styleName: "Heading 1",
        fontName: "黑体",
        fontSize: 12,
        bold: false,
        alignment: "center",
        outlineLevel: 1,
        lineSpacing: 1.25,
        firstLineIndent: 0,
        spaceBefore: 6,
        spaceAfter: 6
      }
    ],
    headings: [
      {
        level: 1,
        text: "一、总体要求",
        paragraphIndex: 1
      }
    ]
  });

  assert.strictEqual(structure.doc_name, "安全运行方案.docx");
  assert.strictEqual(structure.template_id, "technical-file-format-requirements");
  assert.strictEqual(structure.paragraphs[0].style_name, "Heading 1");
  assert.strictEqual(structure.paragraphs[0].font_family, "黑体");
  assert.strictEqual(structure.paragraphs[0].first_line_indent, 0);
  assert.strictEqual(structure.headings[0].paragraph_index, 1);
  assert.strictEqual(structure.capabilities.paragraph_style_extracted, true);
  assert.strictEqual(structure.capabilities.table_extracted, false);
}

function testRenderMarkdownFormatsCommonBlocks() {
  const html = helpers.renderMarkdown([
    "# 审查结果",
    "",
    "第一段第一行",
    "第一段第二行",
    "",
    "- **结论**：可以发布",
    "- `trace_id` 已记录",
    "",
    "---",
    "",
    "> 请复核关键风险。",
    "",
    "| 项目 | 状态 |",
    "| --- | :---: |",
    "| 任务 | 已完成 |",
    "",
    "```json",
    "{\"ok\": true}",
    "```"
  ].join("\n"));

  assert.ok(html.includes("<h1>审查结果</h1>"));
  assert.ok(html.includes("<p>第一段第一行<br>第一段第二行</p>"));
  assert.ok(html.includes("<ul>"));
  assert.ok(html.includes("<strong>结论</strong>"));
  assert.ok(html.includes("<code>trace_id</code>"));
  assert.ok(html.includes("<hr>"));
  assert.ok(html.includes("<blockquote>"));
  assert.ok(html.includes('<div class="markdown-table-wrap">'));
  assert.ok(html.includes("<th>项目</th>"));
  assert.ok(html.includes("<td>已完成</td>"));
  assert.ok(html.includes('<pre><code class="language-json">'));
  assert.ok(html.includes("{&quot;ok&quot;: true}"));
}

function testRenderMarkdownEscapesUnsafeHtmlAndLinks() {
  const html = helpers.renderMarkdown([
    '<img src=x onerror="alert(1)">',
    "[危险链接](javascript:alert(1))",
    "[官网](https://example.com?a=1&b=2)"
  ].join("\n"));

  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("onerror"));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("javascript:"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(html.includes('href="https://example.com?a=1&amp;b=2"'));
}

testGetEffectiveSelectionText();
testResolveRewriteScope();
testSelectionWritebackGuard();
testGetWritableSelection();
testBuildDocumentStructureForProofread();
testRenderMarkdownFormatsCommonBlocks();
testRenderMarkdownEscapesUnsafeHtmlAndLinks();

console.log("taskpane-helpers tests passed");
