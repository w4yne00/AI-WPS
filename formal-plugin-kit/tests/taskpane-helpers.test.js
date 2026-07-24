const assert = require("assert");
const helpers = require("../wps-ai-assistant_1.0.0/taskpane-helpers.js");
const excelHelpers = require("../wps-ai-assistant-et_1.0.0/taskpane-helpers.js");

function assertSettingsStateContract(targetHelpers) {
  const baseInput = {
    detectable: true,
    providerBaseUrl: " https://model.example.test/v1 ",
    taskTypes: ["task.one", "task.two"],
    profilesByTask: {
      "task.one": {
        activeProfileId: "one-active",
        profiles: [
          { id: "one-active", keyConfigured: false },
          { id: "one-backup", keyConfigured: true }
        ]
      },
      "task.two": {
        activeProfileId: "two-active",
        profiles: [{ id: "two-active", keyConfigured: true }]
      }
    }
  };

  assert.deepStrictEqual(targetHelpers.deriveModelInterfaceState(baseInput), {
    code: "partial",
    label: "部分就绪 · 1/2",
    readyCount: 1,
    totalCount: 2
  });
  assert.deepStrictEqual(
    targetHelpers.deriveModelInterfaceState(Object.assign({}, baseInput, { providerBaseUrl: "  " })),
    { code: "unconfigured", label: "未配置", readyCount: 1, totalCount: 2 }
  );
  assert.deepStrictEqual(
    targetHelpers.deriveModelInterfaceState(Object.assign({}, baseInput, { detectable: false })),
    { code: "unavailable", label: "无法检测", readyCount: 0, totalCount: 2 }
  );
  assert.deepStrictEqual(
    targetHelpers.deriveModelInterfaceState({
      detectable: true,
      providerBaseUrl: "https://model.example.test/v1",
      taskTypes: ["task.one", "task.two"],
      profilesByTask: {
        "task.one": {
          activeProfileId: "one-active",
          profiles: [{ id: "one-active", keyConfigured: true }]
        },
        "task.two": {
          activeProfileId: "two-active",
          profiles: [{ id: "two-active", keyConfigured: true }]
        }
      }
    }),
    { code: "ready", label: "已就绪", readyCount: 2, totalCount: 2 }
  );
  assert.deepStrictEqual(
    targetHelpers.deriveModelInterfaceState({
      detectable: true,
      providerBaseUrl: "https://model.example.test/v1",
      taskTypes: ["task.one"],
      profilesByTask: {
        "task.one": {
          activeProfileId: "missing",
          profiles: [{ id: "backup", keyConfigured: true }]
        }
      }
    }),
    { code: "unconfigured", label: "未配置", readyCount: 0, totalCount: 1 }
  );
}

function assertSettingsRefreshControllerContract(targetHelpers) {
  let refreshCount = 0;
  let intervalCount = 0;
  let clearCount = 0;
  let intervalCallback = null;
  let scheduledIntervalMs = null;
  let clearedTimerId = null;
  const controller = targetHelpers.createSettingsRefreshController({
    refresh: function () {
      refreshCount += 1;
    },
    setIntervalFn: function (callback, intervalMs) {
      intervalCount += 1;
      intervalCallback = callback;
      scheduledIntervalMs = intervalMs;
      return 0;
    },
    clearIntervalFn: function (timerId) {
      clearCount += 1;
      clearedTimerId = timerId;
    }
  });

  assert.strictEqual(controller.isRunning(), false);
  controller.start();
  assert.strictEqual(refreshCount, 1);
  assert.strictEqual(intervalCount, 1);
  assert.strictEqual(scheduledIntervalMs, 30000);
  assert.strictEqual(controller.isRunning(), true);

  controller.start();
  assert.strictEqual(refreshCount, 1);
  assert.strictEqual(intervalCount, 1);

  intervalCallback();
  assert.strictEqual(refreshCount, 2);

  controller.stop();
  assert.strictEqual(clearCount, 1);
  assert.strictEqual(clearedTimerId, 0);
  assert.strictEqual(controller.isRunning(), false);

  controller.stop();
  assert.strictEqual(clearCount, 1);
}

function assertWorkflowUiContract(targetHelpers) {
  assert.deepStrictEqual(
    targetHelpers.workflowProfileOptionState(
      { id: "p1", name: "生产版", keyConfigured: true },
      "p1"
    ),
    { id: "p1", label: "✓ 生产版", active: true, disabled: false }
  );
  assert.strictEqual(
    targetHelpers.workflowProfileOptionState(
      { id: "p2", name: "旧版", keyConfigured: false },
      "p1"
    ).disabled,
    true
  );
  assert.deepStrictEqual(
    targetHelpers.validateWorkflowProfileDraft({ name: "", note: "", apiKey: "" }, "create"),
    { ok: false, field: "name", message: "请输入工作流名称。" }
  );
  assert.deepStrictEqual(
    targetHelpers.validateWorkflowProfileDraft({ name: "测试版", note: "", apiKey: "" }, "create"),
    { ok: false, field: "apiKey", message: "请输入工作流 API Key。" }
  );
  assert.strictEqual(
    targetHelpers.validateWorkflowProfileDraft({ name: "生产版", note: "稳定", apiKey: "" }, "edit").ok,
    true
  );
  assert.strictEqual(targetHelpers.shouldActivateNewWorkflowProfile(0, false), true);
  assert.strictEqual(targetHelpers.shouldActivateNewWorkflowProfile(2, false), false);
  assert.strictEqual(targetHelpers.shouldActivateNewWorkflowProfile(2, true), true);
}

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

function testCollectParagraphsSupportsWpsComCollection() {
  const paragraphs = [
    {
      Text: "1 总则",
      StyleNameLocal: "Heading 1",
      Font: {
        NameFarEast: "黑体",
        Name: "SimHei",
        Size: 16,
        Bold: -1,
        Italic: 0
      },
      ParagraphFormat: {
        Alignment: 1,
        OutlineLevel: 1,
        LineSpacing: 300,
        FirstLineIndent: 0
      }
    },
    {
      Text: "正文内容",
      StyleNameLocal: "Normal",
      Font: {
        NameFarEast: "宋体",
        Name: "SimSun",
        Size: 12,
        Bold: 0,
        Italic: 0
      },
      ParagraphFormat: {
        Alignment: 3,
        OutlineLevel: 0,
        LineSpacing: 300,
        FirstLineIndent: 480
      }
    }
  ];
  const document = {
    Paragraphs: {
      Count: 2,
      Item: function (index) {
        return paragraphs[index - 1];
      }
    }
  };

  const result = helpers.collectParagraphs(document);

  assert.strictEqual(result.length, 2);
  assert.strictEqual(result[0].index, 1);
  assert.strictEqual(result[0].text, "1 总则");
  assert.strictEqual(result[0].fontName, "黑体");
  assert.strictEqual(result[0].bold, true);
  assert.strictEqual(result[1].index, 2);
  assert.strictEqual(result[1].text, "正文内容");
  assert.strictEqual(result[1].firstLineIndent, 480);
}

function testCollectParagraphsReadsRangeTextAndContentCollection() {
  const paragraphs = [
    {
      Range: {
        Text: "第一段标题\r",
        Font: {
          NameFarEast: "黑体",
          Size: 16,
          Bold: -1
        },
        ParagraphFormat: {
          OutlineLevel: 1
        },
        Style: {
          NameLocal: "标题 1"
        }
      }
    },
    {
      Range: {
        Text: "第二段正文\r",
        Font: {
          NameFarEast: "宋体",
          Size: 12,
          Bold: 0
        },
        ParagraphFormat: {
          OutlineLevel: 0
        },
        Style: {
          NameLocal: "正文"
        }
      }
    }
  ];
  const document = {
    Content: {
      Paragraphs: {
        Count: function () {
          return 2;
        },
        Item: function (index) {
          return paragraphs[index - 1];
        }
      }
    }
  };

  const result = helpers.collectParagraphs(document);

  assert.strictEqual(result.length, 2);
  assert.strictEqual(result[0].text, "第一段标题");
  assert.strictEqual(result[0].styleName, "标题 1");
  assert.strictEqual(result[0].fontName, "黑体");
  assert.strictEqual(result[1].text, "第二段正文");
}

function testCollectParagraphsFallsBackToDocumentText() {
  const document = {
    Content: {
      Text: "第一段\n\n第二段\r第三段"
    }
  };

  const result = helpers.collectParagraphs(document);

  assert.strictEqual(result.length, 3);
  assert.strictEqual(result[0].index, 1);
  assert.strictEqual(result[0].text, "第一段");
  assert.strictEqual(result[2].text, "第三段");
}

function testCollectParagraphsCanSkipFallbackDocumentTextRead() {
  const document = {
    Content: {
      Text: "第一段\n第二段"
    }
  };

  const result = helpers.collectParagraphs(document, {
    avoidFallbackTextRead: true
  });

  assert.strictEqual(result.length, 0);
}

function testCollectParagraphsSanitizesHostObjectsBeforeJson() {
  const document = {
    Content: {
      Paragraphs: {
        Count: 1,
        Item: function () {
          return {
            Range: {
              Text: function () {
                return "正文段落\r";
              },
              Font: {
                NameFarEast: { value: "宋体对象" },
                Size: { value: 12 },
                Bold: -1,
                Italic: 0,
                Underline: -4142
              },
              ParagraphFormat: {
                Alignment: { value: 3 },
                OutlineLevel: { value: 0 },
                LineSpacing: { value: 300 }
              },
              Style: {}
            }
          };
        }
      }
    }
  };

  const result = helpers.collectParagraphs(document);
  const encoded = JSON.stringify({ paragraphs: result });

  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].text, "正文段落");
  assert.strictEqual(result[0].styleName, "Body");
  assert.strictEqual(result[0].fontName, "宋体对象");
  assert.strictEqual(result[0].fontSize, 12);
  assert.strictEqual(result[0].alignment, "justify");
  assert.strictEqual(result[0].outlineLevel, 0);
  assert.strictEqual(result[0].lineSpacing, 300);
  assert.strictEqual(result[0].underline, -4142);
  assert.ok(encoded.includes('"text":"正文段落"'));
  assert.ok(!encoded.includes("function"));
  assert.ok(!encoded.includes("[object Object]"));
}

function testCollectParagraphsFromSelectionSourcesPreservesFormat() {
  const selection = {
    Range: {
      Paragraphs: {
        Count: 1,
        Item: function () {
          return {
            Range: {
              Text: "选中正文\r",
              Font: {
                NameFarEast: "宋体",
                Size: { value: 12 },
                Bold: 0
              },
              ParagraphFormat: {
                Alignment: { value: 3 },
                OutlineLevel: 0,
                LineSpacing: 300,
                FirstLineIndent: 640
              },
              Style: {
                NameLocal: "Normal"
              }
            }
          };
        }
      }
    }
  };

  const result = helpers.collectParagraphsFromSelectionSources([selection], "选中正文", {
    maxParagraphs: 5,
    maxParagraphTextLength: 100
  });

  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].text, "选中正文");
  assert.strictEqual(result[0].fontName, "宋体");
  assert.strictEqual(result[0].fontSize, 12);
  assert.strictEqual(result[0].alignment, "justify");
  assert.strictEqual(result[0].firstLineIndent, 640);
}

function testCollectParagraphsFromTextDoesNotInventFormat() {
  const result = helpers.collectParagraphsFromText("纯文本选区", {});

  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].fontSize, null);
  assert.strictEqual(result[0].alignment, "");
}

function testCollectParagraphsCanLimitWpsComCollection() {
  let calls = 0;
  const document = {
    Paragraphs: {
      Count: 1000,
      Item: function (index) {
        calls += 1;
        return {
          Text: "第" + index + "段正文内容",
          StyleNameLocal: "Normal",
          Font: {
            NameFarEast: "宋体",
            Size: 12
          },
          ParagraphFormat: {
            OutlineLevel: 0
          }
        };
      }
    }
  };

  const result = helpers.collectParagraphs(document, {
    maxParagraphs: 3,
    maxParagraphTextLength: 3
  });

  assert.strictEqual(calls, 3);
  assert.strictEqual(result.length, 3);
  assert.strictEqual(result[0].text, "第1段");
  assert.strictEqual(result[2].index, 3);
}

function testCollectParagraphsFromTextCanLimitSelectionText() {
  const result = helpers.collectParagraphsFromText("第一段很长\n第二段\n第三段", {
    maxParagraphs: 2,
    maxParagraphTextLength: 3
  });

  assert.strictEqual(result.length, 2);
  assert.strictEqual(result[0].text, "第一段");
  assert.strictEqual(result[1].text, "第二段");
  assert.strictEqual(result[0].styleName, "Normal");
}

function testGetCollectionItemSupportsOneBasedWpsItem() {
  const collection = {
    Count: 2,
    Item: function (index) {
      return { value: "p" + index };
    }
  };

  assert.strictEqual(helpers.getCollectionItem(collection, 1).value, "p1");
  assert.strictEqual(helpers.getCollectionItem(collection, 2).value, "p2");
  assert.strictEqual(helpers.getCollectionItem([{ value: "a" }], 1).value, "a");
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

function testRenderMarkdownFormatsSmartWriteDiffHighlight() {
  const html = helpers.renderMarkdown("改写后：==优化后的表述==");

  assert.ok(html.includes('<mark class="smart-diff-highlight">优化后的表述</mark>'));
  assert.ok(!html.includes("==优化后的表述=="));
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

function testBuildMarkdownWritebackBlocksPreservesSupportedStructure() {
  const blocks = helpers.buildMarkdownWritebackBlocks([
    "# 总体要求",
    "",
    "第一段包含**重点**内容。",
    "",
    "- 第一项",
    "- 第二项",
    "",
    "1. 步骤一",
    "2. 步骤二"
  ].join("\n"));

  assert.strictEqual(blocks.length, 6);
  assert.deepStrictEqual(blocks[0], {
    type: "heading",
    level: 1,
    text: "总体要求",
    runs: [{ text: "总体要求", bold: false }]
  });
  assert.strictEqual(blocks[1].type, "paragraph");
  assert.strictEqual(blocks[1].text, "第一段包含重点内容。");
  assert.deepStrictEqual(blocks[1].runs, [
    { text: "第一段包含", bold: false },
    { text: "重点", bold: true },
    { text: "内容。", bold: false }
  ]);
  assert.strictEqual(blocks[2].type, "unorderedListItem");
  assert.strictEqual(blocks[2].text, "第一项");
  assert.strictEqual(blocks[3].type, "unorderedListItem");
  assert.strictEqual(blocks[3].text, "第二项");
  assert.strictEqual(blocks[4].type, "orderedListItem");
  assert.strictEqual(blocks[4].ordinal, 1);
  assert.strictEqual(blocks[5].type, "orderedListItem");
  assert.strictEqual(blocks[5].ordinal, 2);
  assert.deepStrictEqual(blocks[5].runs, [{ text: "步骤二", bold: false }]);
}

function testBuildMarkdownWritebackBlocksKeepsTechnicalUnderscores() {
  const blocks = helpers.buildMarkdownWritebackBlocks("请配置 `API_KEY` 和 service_url。");

  assert.strictEqual(blocks.length, 1);
  assert.strictEqual(blocks[0].text, "请配置 API_KEY 和 service_url。");
  assert.deepStrictEqual(blocks[0].runs, [
    { text: "请配置 API_KEY 和 service_url。", bold: false }
  ]);
}

function testHasStructuredSmartWriteContentDetectsDocumentStructure() {
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("普通正文，没有结构。"), false);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("# 一级标题\n正文"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("- 第一项\n- 第二项"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("1. 第一步\n2. 第二步"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("一、总体要求\n正文内容"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("| 项目 | 状态 |\n| --- | --- |\n| A | 完成 |"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("字段A\t字段B\n值A\t值B"), true);
  assert.strictEqual(helpers.hasStructuredSmartWriteContent("需要**重点关注**风险。"), true);
}

function testShouldUseStructuredSmartWriteResultUsesOriginalOrResultStructure() {
  assert.strictEqual(helpers.shouldUseStructuredSmartWriteResult("普通原文", "普通结果"), false);
  assert.strictEqual(helpers.shouldUseStructuredSmartWriteResult("一、总体要求\n正文", "优化后的正文"), true);
  assert.strictEqual(helpers.shouldUseStructuredSmartWriteResult("普通原文", "## 优化标题\n正文"), true);
}

function testFormatSmartWriteResultSplitsSingleLineByOriginalParagraphs() {
  const formatted = helpers.formatSmartWriteResult(
    "第一段说明当前建设情况。\n\n第二段说明下一步计划。",
    "当前建设工作整体推进正常，关键任务已按计划完成。下一步将继续跟踪遗留事项，明确责任人和完成时限。"
  );

  assert.strictEqual(
    formatted,
    "当前建设工作整体推进正常，关键任务已按计划完成。\n\n下一步将继续跟踪遗留事项，明确责任人和完成时限。"
  );
}

function testFormatSmartWriteResultPreservesExistingLineBreaks() {
  const formatted = helpers.formatSmartWriteResult(
    "第一段。\n\n第二段。",
    "第一段已经优化。\n\n第二段已经优化。"
  );

  assert.strictEqual(formatted, "第一段已经优化。\n\n第二段已经优化。");
}

function testFormatSmartWriteResultBreaksInlineChineseHeadings() {
  const formatted = helpers.formatSmartWriteResult(
    "一、总体要求\n正文",
    "一、总体要求当前工作应保持闭环管理。二、下一步安排继续跟踪风险并明确责任。"
  );

  assert.strictEqual(
    formatted,
    "一、总体要求当前工作应保持闭环管理。\n\n二、下一步安排继续跟踪风险并明确责任。"
  );
}

function testBuildSmartWritePreviewModelUsesStructuredReadOnlyViews() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "一、总体要求\n原文第一段。",
    rewrittenText: "一、总体要求\n优化后第一段。\n\n- 第一项\n- 第二项",
    rewriteMode: "rewrite"
  });

  assert.strictEqual(model.hasOriginal, true);
  assert.strictEqual(model.hasStructuredResult, true);
  assert.ok(model.previewMarkdown.includes("一、总体要求"));
  assert.ok(model.previewMarkdown.includes("- 第一项"));
  assert.ok(model.plainText.includes("优化后第一段。"));
  assert.ok(model.comparisonMarkdown.includes("### 原文"));
  assert.ok(model.comparisonMarkdown.includes("原文第一段。"));
  assert.ok(model.comparisonMarkdown.includes("### 智能编写结果"));
}

function testBuildSmartWritePreviewModelHighlightsChangedResultText() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "第一段原文。\n\n第二段保持不变。",
    rewrittenText: "第一段优化后。\n\n第二段保持不变。",
    rewriteMode: "rewrite"
  });
  const html = helpers.renderMarkdown(model.comparisonMarkdown);

  assert.ok(model.comparisonMarkdown.includes("第一段==优化后==。"));
  assert.ok(!model.comparisonMarkdown.includes("==第一段优化后。=="));
  assert.ok(!model.comparisonMarkdown.includes("==第二段保持不变。=="));
  assert.ok(html.includes('第一段<mark class="smart-diff-highlight">优化后</mark>。'));
}

function testBuildSmartWritePreviewModelHighlightsChangedWordsOnly() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "第一段原文。",
    rewrittenText: "第一段优化后。",
    rewriteMode: "rewrite"
  });
  const html = helpers.renderMarkdown(model.comparisonMarkdown);

  assert.ok(model.comparisonMarkdown.includes("第一段==优化后==。"));
  assert.ok(!model.comparisonMarkdown.includes("==第一段优化后。=="));
  assert.ok(html.includes('第一段<mark class="smart-diff-highlight">优化后</mark>。'));
}

function testBuildSmartWritePreviewModelHighlightsListItemTextOnly() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "- 原始条目",
    rewrittenText: "- 优化条目",
    rewriteMode: "rewrite"
  });
  const html = helpers.renderMarkdown(model.comparisonMarkdown);

  assert.ok(model.comparisonMarkdown.includes("- ==优化==条目"));
  assert.ok(!model.comparisonMarkdown.includes("- ==优化条目=="));
  assert.ok(html.includes('<li><mark class="smart-diff-highlight">优化</mark>条目</li>'));
}

function testBuildSmartWritePreviewModelHighlightsChangedTableCellsOnly() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "| 项目 | 状态 |\n| --- | --- |\n| 任务 | 未完成 |",
    rewrittenText: "| 项目 | 状态 |\n| --- | --- |\n| 任务 | 已完成 |",
    rewriteMode: "rewrite"
  });
  const html = helpers.renderMarkdown(model.comparisonMarkdown);

  assert.ok(model.comparisonMarkdown.includes("| 任务 | ==已==完成 |"));
  assert.ok(!model.comparisonMarkdown.includes("| ==任务== |"));
  assert.ok(html.includes('<mark class="smart-diff-highlight">已</mark>完成'));
}

function testBuildSmartWritePreviewModelSeparatesMultipleChangedSegments() {
  const model = helpers.buildSmartWritePreviewModel({
    originalText: "甲A乙B丙",
    rewrittenText: "甲X乙Y丙",
    rewriteMode: "rewrite"
  });
  const html = helpers.renderMarkdown(model.comparisonMarkdown);

  assert.ok(model.comparisonMarkdown.includes("甲==X==乙==Y==丙"));
  assert.ok(!model.comparisonMarkdown.includes("==X乙Y=="));
  assert.ok(html.includes('甲<mark class="smart-diff-highlight">X</mark>乙<mark class="smart-diff-highlight">Y</mark>丙'));
}

function testBuildSmartWritePreviewModelHandlesEmptyResult() {
  const model = helpers.buildSmartWritePreviewModel({});

  assert.strictEqual(model.hasOriginal, false);
  assert.strictEqual(model.hasStructuredResult, false);
  assert.strictEqual(model.previewMarkdown, "");
  assert.strictEqual(model.plainText, "");
  assert.strictEqual(model.comparisonMarkdown, "");
}

function testRenderReadableFormatReviewUsesChineseLabelsAndValues() {
  const markdown = helpers.renderReadableFormatReview({
    summary: {
      scope: "selection",
      templateId: "technical-file-format-requirements",
      provider: "enterprise-dify-chat/task-file",
      paragraphCount: 4,
      issueCount: 4,
      aiClassifiedParagraphCount: 2,
      localFallbackParagraphCount: 2,
      aiFallbackReason: "provider_request_failed"
    },
    issues: [
      {
        ruleId: "font_size",
        paragraphIndex: 2,
        role: "body",
        message: "字号不符合模板要求。",
        currentValue: "14pt",
        expectedValue: "12pt",
        suggestion: "建议字号调整为12pt。"
      },
      {
        ruleId: "font_name",
        paragraphIndex: 2,
        role: "body",
        message: "字体不符合模板要求。",
        currentValue: "楷体",
        expectedValue: "SimSun",
        suggestion: "建议字体调整为宋体。"
      },
      {
        ruleId: "alignment",
        paragraphIndex: 3,
        role: "heading1",
        message: "对齐方式不符合模板要求。",
        currentValue: "left",
        expectedValue: "center",
        suggestion: "建议对齐方式调整为center。"
      },
      {
        ruleId: "first_line_indent",
        paragraphIndex: 4,
        role: "body",
        message: "首行缩进不符合模板要求。",
        currentValue: "0",
        expectedValue: "480",
        suggestion: "建议按模板设置首行缩进。"
      }
    ]
  });

  assert.ok(markdown.includes("## 审查概览"));
  assert.ok(markdown.includes("## 优先处理清单"));
  assert.ok(markdown.includes("## 详细问题"));
  assert.ok(markdown.includes("## 诊断信息"));
  assert.ok(markdown.includes("正文格式 2"));
  assert.ok(markdown.includes("标题层级 1"));
  assert.ok(markdown.includes("段落格式 1"));
  assert.ok(markdown.includes("P2 | 字号 | 四号（14pt） | 小四（12pt） | 字号调整为小四。"));
  assert.ok(markdown.includes("P2 | 字体 | 楷体 | 宋体 | 字体调整为宋体。"));
  assert.ok(markdown.includes("P3 | 对齐方式 | 左对齐 | 居中 | 对齐方式调整为居中。"));
  assert.ok(markdown.includes("P4 | 首行缩进 | 无首行缩进 | 首行缩进 2 字符（约 480 twips）"));
  assert.ok(markdown.includes("#### P2 正文 - 字号不符合模板要求"));
  assert.ok(markdown.includes("- 现状：四号（14pt）"));
  assert.ok(markdown.includes("- 要求：小四（12pt）"));
  assert.ok(markdown.includes("- 建议：字号调整为小四。"));
  assert.ok(markdown.includes("- AI 兜底原因：模型后台请求失败，已使用本地模板规则。"));
  assert.ok(!markdown.includes("font_size"));
  assert.ok(!markdown.includes("body_text"));
}

function testRenderReadableFormatReviewHandlesNoIssues() {
  const markdown = helpers.renderReadableFormatReview({
    summary: {
      scope: "document",
      templateId: "technical-file-format-requirements",
      provider: "local",
      paragraphCount: 3,
      issueCount: 0
    },
    issues: []
  });

  assert.ok(markdown.includes("问题总数：0"));
  assert.ok(markdown.includes("当前范围未发现明显格式问题。"));
  assert.ok(markdown.includes("识别来源：本地规则"));
}

function testRenderReadableFormatReviewLocalizesOtherFeedback() {
  const markdown = helpers.renderReadableFormatReview({
    summary: {
      scope: "document",
      templateId: "technical-file-format-requirements",
      provider: "mock",
      paragraphCount: 45,
      issueCount: 3,
      aiClassifiedParagraphCount: 40,
      localFallbackParagraphCount: 5,
      aiInvalidRoleCount: 1,
      aiOutOfBatchCount: 2,
      aiFallbackReason: "ai_budget_limited"
    },
    issues: [
      {
        ruleId: "page_setup",
        paragraphIndex: 0,
        role: "page_setup",
        message: "页面设置不符合模板要求。",
        currentValue: JSON.stringify({
          paperSize: "A4",
          marginTop: 1440,
          marginBottom: 1440,
          marginLeft: 1800,
          marginRight: 1800
        }),
        expectedValue: "A4 页面及模板页边距",
        suggestion: "建议按模板设置 A4 页面和页边距。"
      },
      {
        ruleId: "style_name",
        paragraphIndex: 1,
        role: "document_title",
        message: "段落样式不符合模板要求。",
        currentValue: "Normal",
        expectedValue: "文档标题",
        suggestion: "建议按document_title套用模板样式。"
      },
      {
        ruleId: "line_spacing",
        paragraphIndex: 5,
        role: "body",
        message: "行距不符合模板要求。",
        currentValue: "1.0倍",
        expectedValue: "1.25倍",
        suggestion: "建议行距调整为1.25倍。"
      }
    ]
  });

  assert.ok(markdown.includes("页面 | 页面设置 | 纸张：A4；页边距：上 1440、下 1440、左 1800、右 1800 | A4 页面及模板页边距"));
  assert.ok(markdown.includes("P1 | 段落样式 | 正文样式（Normal） | 文档标题 | 按文档标题套用模板样式。"));
  assert.ok(markdown.includes("P5 | 行距 | 单倍行距（1倍） | 1.25 倍行距 | 行距调整为 1.25 倍。"));
  assert.ok(markdown.includes("- 模板：技术文件格式及书写要求"));
  assert.ok(markdown.includes("- 识别来源：模拟服务"));
  assert.ok(markdown.includes("- AI 兜底原因：文档段落较多，AI 角色识别仅处理前 40 段；其余段落已使用本地模板规则。"));
  assert.ok(!markdown.includes("fallback"));
  assert.ok(!markdown.includes("ai_budget_limited"));
  assert.ok(!markdown.includes("technical-file-format-requirements"));
  assert.ok(!markdown.includes("document_title"));
}

function testBuildDocumentReviewRecordUsesIssueStatuses() {
  const record = helpers.buildDocumentReviewRecord({
    summary: "发现 2 项问题。",
    issues: [
      {
        category: "typo",
        severity: "high",
        location: "P1",
        originalText: "错字",
        problem: "存在错别字",
        suggestion: "改为正确文字",
        suggestedRewrite: "正确文字"
      },
      {
        category: "logic",
        severity: "medium",
        location: "P2",
        originalText: "表述",
        problem: "逻辑不完整",
        suggestion: "补充条件",
        suggestedRewrite: "补充条件后的表述"
      }
    ]
  }, {
    "0": "done",
    "1": "ignored"
  });

  assert.ok(record.includes("文档审查处理记录"));
  assert.ok(record.includes("问题总数：2"));
  assert.ok(record.includes("已处理：1"));
  assert.ok(record.includes("已忽略：1"));
  assert.ok(record.includes("错别字"));
  assert.ok(record.includes("逻辑表达"));
  assert.ok(record.includes("建议改写：补充条件后的表述"));
}

function testBuildDocumentReviewRecordHandlesEmptyIssues() {
  const record = helpers.buildDocumentReviewRecord({ summary: "未发现问题。", issues: [] }, {});

  assert.ok(record.includes("问题总数：0"));
  assert.ok(record.includes("未发现需要处理的问题。"));
}

function testNormalizeWorkflowProfileDataFiltersByTask() {
  const data = helpers.normalizeWorkflowProfileData({
    activeProfileId: "profile_word",
    profiles: [
      { id: "profile_word", taskType: "word.smart_write", name: "稳定版", keyConfigured: true },
      { id: "profile_excel", taskType: "excel.analysis", name: "表格版", keyConfigured: true }
    ]
  }, "word.smart_write");

  assert.strictEqual(data.activeProfileId, "profile_word");
  assert.deepStrictEqual(data.profiles.map((item) => item.id), ["profile_word"]);
  assert.strictEqual(helpers.getActiveWorkflowProfileName(data), "稳定版");
  assert.strictEqual(helpers.canDeleteWorkflowProfile(data.profiles[0], "profile_word"), false);
  assert.strictEqual(helpers.workflowProfileStatusText(data.profiles[0], "profile_word"), "当前使用");
}

function testNormalizeWorkflowProfileDataHandlesMalformedInput() {
  const data = helpers.normalizeWorkflowProfileData({
    activeProfileId: "missing",
    profiles: [null, { id: "", taskType: "word.smart_write" }]
  }, "word.smart_write");

  assert.deepStrictEqual(data.profiles, []);
  assert.strictEqual(data.activeProfileId, "");
  assert.strictEqual(helpers.getActiveWorkflowProfileName(data), "尚未配置");
  assert.strictEqual(helpers.workflowProfileStatusText({ id: "p", keyConfigured: false }, ""), "密钥未配置");
}

function testNormalizeWritingPolicyUsageHandlesMissingAndMalformedMetadata() {
  assert.deepStrictEqual(helpers.normalizeWritingPolicyUsage(null), null);
  assert.deepStrictEqual(helpers.normalizeWritingPolicyUsage([]), null);

  const normalized = helpers.normalizeWritingPolicyUsage({
    applied: true,
    degraded: false,
    degradedReason: 123,
    termMatchCount: -2,
    styleRuleCount: 3.8,
    truncatedCount: "4",
    matchedItems: [
      { id: "t1", type: "term", name: "卫星互联网运营管理平台" },
      { id: "s1", type: "style", name: "先结论后说明" },
      { id: "x1", type: "unknown", name: "不应显示" },
      null
    ]
  });

  assert.deepStrictEqual(normalized, {
    applied: true,
    degraded: false,
    degradedReason: "123",
    termMatchCount: 0,
    styleRuleCount: 3,
    truncatedCount: 4,
    matchedItems: [
      { id: "t1", type: "term", name: "卫星互联网运营管理平台" },
      { id: "s1", type: "style", name: "先结论后说明" }
    ]
  });
}

function testWritingPolicyUsageSummaryUsesTaskSpecificChineseVerb() {
  const usage = { applied: true, termMatchCount: 2, styleRuleCount: 1 };

  assert.strictEqual(
    helpers.writingPolicyUsageSummary(usage, "word.smart_write"),
    "写作规范：已应用 2 条术语、1 条文体规则"
  );
  assert.strictEqual(
    helpers.writingPolicyUsageSummary(usage, "word.smart_imitation"),
    "写作规范：已应用 2 条术语、1 条文体规则"
  );
  assert.strictEqual(
    helpers.writingPolicyUsageSummary(usage, "word.document_review"),
    "写作规范：已检查 2 条术语、1 条文体规则"
  );
  assert.strictEqual(
    helpers.writingPolicyUsageSummary({ applied: false, degraded: true }, "word.document_review"),
    "写作规范未应用，本次结果仅使用模型工作流生成"
  );
  assert.strictEqual(helpers.writingPolicyUsageSummary(null, "word.smart_write"), "");
}

function testWritingPolicyUsageDetailsFiltersLabelsAndCapsItems() {
  const matchedItems = [];
  for (let index = 0; index < 24; index += 1) {
    matchedItems.push({
      id: `item-${index}`,
      type: index % 2 === 0 ? "term" : "style",
      name: `规则 ${index}`
    });
  }
  matchedItems.splice(3, 0, { id: "ignored", type: "other", name: "不应显示" });

  const details = helpers.writingPolicyUsageDetails({ matchedItems });

  assert.strictEqual(details.length, 20);
  assert.strictEqual(details[0], "术语：规则 0");
  assert.strictEqual(details[1], "文体规则：规则 1");
  assert.ok(!details.some((item) => item.includes("不应显示")));
}

testGetEffectiveSelectionText();
testResolveRewriteScope();
testSelectionWritebackGuard();
testGetWritableSelection();
testBuildDocumentStructureForProofread();
testCollectParagraphsSupportsWpsComCollection();
testCollectParagraphsReadsRangeTextAndContentCollection();
testCollectParagraphsFallsBackToDocumentText();
testCollectParagraphsCanSkipFallbackDocumentTextRead();
testCollectParagraphsSanitizesHostObjectsBeforeJson();
testCollectParagraphsFromSelectionSourcesPreservesFormat();
testCollectParagraphsFromTextDoesNotInventFormat();
testCollectParagraphsCanLimitWpsComCollection();
testCollectParagraphsFromTextCanLimitSelectionText();
testGetCollectionItemSupportsOneBasedWpsItem();
testRenderMarkdownFormatsCommonBlocks();
testRenderMarkdownFormatsSmartWriteDiffHighlight();
testRenderMarkdownEscapesUnsafeHtmlAndLinks();
testBuildMarkdownWritebackBlocksPreservesSupportedStructure();
testBuildMarkdownWritebackBlocksKeepsTechnicalUnderscores();
testHasStructuredSmartWriteContentDetectsDocumentStructure();
testShouldUseStructuredSmartWriteResultUsesOriginalOrResultStructure();
testFormatSmartWriteResultSplitsSingleLineByOriginalParagraphs();
testFormatSmartWriteResultPreservesExistingLineBreaks();
testFormatSmartWriteResultBreaksInlineChineseHeadings();
testBuildSmartWritePreviewModelUsesStructuredReadOnlyViews();
testBuildSmartWritePreviewModelHighlightsChangedResultText();
testBuildSmartWritePreviewModelHighlightsChangedWordsOnly();
testBuildSmartWritePreviewModelHighlightsListItemTextOnly();
testBuildSmartWritePreviewModelHighlightsChangedTableCellsOnly();
testBuildSmartWritePreviewModelSeparatesMultipleChangedSegments();
testBuildSmartWritePreviewModelHandlesEmptyResult();
testRenderReadableFormatReviewUsesChineseLabelsAndValues();
testRenderReadableFormatReviewHandlesNoIssues();
testRenderReadableFormatReviewLocalizesOtherFeedback();
testBuildDocumentReviewRecordUsesIssueStatuses();
testBuildDocumentReviewRecordHandlesEmptyIssues();
testNormalizeWorkflowProfileDataFiltersByTask();
testNormalizeWorkflowProfileDataHandlesMalformedInput();
testNormalizeWritingPolicyUsageHandlesMissingAndMalformedMetadata();
testWritingPolicyUsageSummaryUsesTaskSpecificChineseVerb();
testWritingPolicyUsageDetailsFiltersLabelsAndCapsItems();
assertWorkflowUiContract(helpers);
assertWorkflowUiContract(excelHelpers);
assertSettingsStateContract(helpers);
assertSettingsStateContract(excelHelpers);
assertSettingsRefreshControllerContract(helpers);
assertSettingsRefreshControllerContract(excelHelpers);

console.log("taskpane-helpers tests passed");
