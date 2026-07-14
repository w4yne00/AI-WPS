const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js",
  "utf8"
);
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);
const helpers = context.window.WpsAiPptHelpers;

function collection(items) {
  return {
    Count: items.length,
    Item(index) {
      return items[index - 1];
    }
  };
}

function textFrameShape(text, options) {
  const shape = {
    TextFrame: {
      HasText: true,
      TextRange: { Text: text }
    }
  };
  options = options || {};
  if (options.name) {
    shape.Name = options.name;
  }
  if (options.id) {
    shape.Id = options.id;
  }
  if (typeof options.top === "number") {
    shape.Top = options.top;
  }
  if (typeof options.left === "number") {
    shape.Left = options.left;
  }
  if (typeof options.width === "number") {
    shape.Width = options.width;
  }
  if (typeof options.height === "number") {
    shape.Height = options.height;
  }
  if (typeof options.placeholderType === "number") {
    shape.PlaceholderFormat = { Type: options.placeholderType };
  }
  return shape;
}

function textFrame2Shape(text) {
  return {
    TextFrame2: {
      HasText: true,
      TextRange: { Text: text }
    }
  };
}

function slide(index, title, bodyShapes, options) {
  const titleShape = options && options.noTitle ? null : textFrameShape(title, {
    id: options && options.titleId,
    name: options && options.titleName,
    top: options && options.titleTop,
    left: options && options.titleLeft,
    width: options && options.titleWidth,
    height: options && options.titleHeight
  });
  const shapes = (titleShape ? [titleShape] : []).concat(bodyShapes || []);
  const shapeCollection = collection(shapes);
  if (titleShape) {
    shapeCollection.Title = options && options.detachedTitleWrapper
      ? textFrameShape(title)
      : titleShape;
  }
  return {
    SlideIndex: index,
    Shapes: shapeCollection
  };
}

function applicationFor(slides, activeIndex, name) {
  return {
    ActivePresentation: {
      Name: name || "汇报材料.pptx",
      Slides: collection(slides)
    },
    ActiveWindow: {
      View: {
        Slide: slides[activeIndex - 1]
      }
    }
  };
}

const limits = {
  maxTitleLength: 200,
  maxBlockLength: 1000,
  maxBodyLength: 3000,
  maxAdjacentTitleLength: 200
};

{
  const slides = [
    slide(1, "项目背景", [textFrameShape("背景正文")]),
    slide(2, "项目进展", [
      textFrameShape("总体方案设计已完成"),
      textFrame2Shape("正在开展接口联调")
    ]),
    slide(3, "风险与措施", [textFrameShape("风险正文")])
  ];
  const result = helpers.extractPresentationSlide(applicationFor(slides, 2), limits);

  assert.strictEqual(result.presentationId, "汇报材料.pptx");
  assert.strictEqual(result.scene, "ppt");
  assert.strictEqual(result.slide.index, 2);
  assert.strictEqual(result.slide.title, "项目进展");
  assert.strictEqual(result.slide.subtitle, "");
  assert.deepStrictEqual(
    Array.from(result.slide.textBlocks),
    ["总体方案设计已完成", "正在开展接口联调"]
  );
  assert.strictEqual(result.slide.previousTitle, "项目背景");
  assert.strictEqual(result.slide.nextTitle, "风险与措施");
  assert.strictEqual(result.slide.truncated, false);
}

{
  const slides = [
    slide(1, "", [textFrameShape("没有标题占位符的候选标题"), textFrameShape("正文内容")], { noTitle: true })
  ];
  const result = helpers.extractPresentationSlide(applicationFor(slides, 1), limits);

  assert.strictEqual(result.slide.title, "没有标题占位符的候选标题");
  assert.strictEqual(result.slide.subtitle, "");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), ["正文内容"]);
  assert.strictEqual(result.slide.previousTitle, "");
  assert.strictEqual(result.slide.nextTitle, "");
}

{
  const titleOnly = slide(1, "仅标题页", []);
  const result = helpers.extractPresentationSlide(applicationFor([titleOnly], 1), limits);

  assert.strictEqual(result.slide.title, "仅标题页");
  assert.strictEqual(result.slide.subtitle, "");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), []);
  assert.strictEqual(result.slide.bodyCharacterCount, 0);
}

{
  const blank = slide(1, "", [], { noTitle: true });
  const result = helpers.extractPresentationSlide(applicationFor([blank], 1), limits);

  assert.strictEqual(result.slide.title, "");
  assert.strictEqual(result.slide.subtitle, "");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), []);
  assert.strictEqual(result.slide.truncated, false);
}

{
  const oversized = slide(1, "超长页面", [
    textFrameShape("甲".repeat(1200)),
    textFrameShape("乙".repeat(1000)),
    textFrameShape("丙".repeat(1000)),
    textFrameShape("丁".repeat(1000))
  ]);
  const result = helpers.extractPresentationSlide(applicationFor([oversized], 1), limits);
  const bodyLength = result.slide.textBlocks.reduce((total, item) => total + item.length, 0);

  assert.strictEqual(result.slide.textBlocks[0].length, 1000);
  assert.strictEqual(bodyLength, 3000);
  assert.strictEqual(result.slide.truncated, true);
  assert.strictEqual(result.slide.bodyCharacterCount, 3000);
}

{
  const screenshotLikeSlide = slide(2, "二、项目进展", [
    textFrameShape("总体方案设计已完成", { top: 190, left: 40, width: 300, height: 240 }),
    textFrameShape("副标题", { name: "TextBox 7", top: 96, left: 40, width: 620, height: 38 }),
    textFrameShape("正在开展接口联调", { top: 190, left: 380, width: 300, height: 240 })
  ], {
    detachedTitleWrapper: true,
    titleTop: 30,
    titleLeft: 40,
    titleWidth: 620,
    titleHeight: 42
  });
  const result = helpers.extractPresentationSlide(
    applicationFor([
      slide(1, "一、项目背景", [textFrameShape("背景正文")]),
      screenshotLikeSlide,
      slide(3, "三、风险与措施", [textFrameShape("风险正文")])
    ], 2),
    limits
  );

  assert.strictEqual(result.slide.title, "二、项目进展");
  assert.strictEqual(result.slide.subtitle, "副标题");
  assert.deepStrictEqual(
    Array.from(result.slide.textBlocks),
    ["总体方案设计已完成", "正在开展接口联调"]
  );
  assert.strictEqual(result.slide.subtitleCharacterCount, 3);
  assert.strictEqual(result.slide.bodyCharacterCount, 17);
  assert.strictEqual(result.slide.contentCharacterCount, 20);
}

{
  const subtitlePlaceholder = textFrameShape("面向管理层的阶段汇报", {
    name: "Subtitle 2",
    placeholderType: 4,
    top: 100,
    height: 32
  });
  const result = helpers.extractPresentationSlide(
    applicationFor([
      slide(1, "项目总体进展", [subtitlePlaceholder], {
        titleTop: 32,
        titleHeight: 42
      })
    ], 1),
    limits
  );

  assert.strictEqual(result.slide.subtitle, "面向管理层的阶段汇报");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), []);
}

{
  const result = helpers.extractPresentationSlide(
    applicationFor([
      slide(1, "项目总体进展", [
        textFrameShape("本页只有一条正文", { top: 180, height: 220 })
      ], {
        detachedTitleWrapper: true,
        titleTop: 30,
        titleHeight: 42
      })
    ], 1),
    limits
  );

  assert.strictEqual(result.slide.subtitle, "");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), ["本页只有一条正文"]);
}

assert.strictEqual(helpers.truncateText("abcdef", 3), "abc");

{
  const markdown = helpers.buildPptSlideMarkdown({
    suggestedTitle: "项目总体进展",
    bullets: ["方案设计已完成", "系统进入联调阶段", "重点关注接口稳定性"],
    conclusion: "项目按计划推进。"
  });
  assert.ok(markdown.includes("## 建议标题"));
  assert.ok(markdown.includes("- 方案设计已完成"));
  assert.ok(markdown.includes("## 本页结论"));
}

assert.strictEqual(
  helpers.buildPptSlidePlainText({
    suggestedTitle: "标题",
    bullets: ["要点一", "要点二", "要点三"],
    conclusion: "结论"
  }),
  "标题\n\n1. 要点一\n2. 要点二\n3. 要点三\n\n结论"
);

{
  const markdownFile = helpers.validatePptDocumentFile({ name: "报告.md", size: 1024 });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(markdownFile)), {
    valid: true,
    extension: "md",
    mimeType: "text/markdown"
  });
  assert.strictEqual(
    helpers.validatePptDocumentFile({ name: "报告.pdf", size: 1024 }).code,
    "PPT_DOCUMENT_TYPE_UNSUPPORTED"
  );
  assert.strictEqual(
    helpers.validatePptDocumentFile({ name: "报告.docx", size: 10 * 1024 * 1024 + 1 }).code,
    "PPT_DOCUMENT_TOO_LARGE"
  );
  assert.strictEqual(
    helpers.validatePptDocumentFile({ name: "空文档.docx", size: 0 }).code,
    "PPT_DOCUMENT_TOO_LARGE"
  );
}

{
  const result = helpers.normalizePptDocumentResult({
    resultType: "document",
    deckTitle: "  项目总结  ",
    documentSummary: "项目进入联调阶段。",
    globalStyleAdvice: "使用简洁图表。",
    rawAnswer: "不应进入结构化复制文本",
    slides: [
      {
        index: "2",
        role: "内容页",
        title: "进展",
        subtitle: "阶段成果",
        bullets: ["完成方案", "开始联调"],
        conclusion: "总体可控",
        layoutSuggestion: "左右分栏",
        visualSuggestion: "使用里程碑图"
      },
      { index: 1, role: "封面", title: "封面" }
    ]
  });

  assert.strictEqual(result.resultType, "document");
  assert.strictEqual(result.deckTitle, "项目总结");
  assert.deepStrictEqual(Array.from(result.slides, slideItem => slideItem.index), [1, 2]);
  assert.ok(helpers.buildPptDocumentOutline(result).includes("1. 封面"));
  assert.ok(helpers.buildPptDocumentOutline(result).includes("2. 进展"));
  assert.ok(helpers.buildPptDocumentSlidePlainText(result.slides[1]).includes("版式建议：左右分栏"));
  assert.ok(helpers.buildPptDocumentSlidePlainText(result.slides[1]).includes("视觉建议：使用里程碑图"));
  assert.ok(helpers.buildPptDocumentPlainText(result).includes("文档摘要：项目进入联调阶段。"));
  assert.ok(!helpers.buildPptDocumentPlainText(result).includes("不应进入结构化复制文本"));
}

assert.strictEqual(
  helpers.buildPptDocumentPlainText({ resultType: "document", rawAnswer: "模型原始回复" }),
  "模型原始回复"
);

{
  const fallback = helpers.normalizePptDocumentResult({
    resultType: "document",
    documentSummary: "模型后台已返回结果，但未按结构化 JSON 输出。",
    slides: [],
    plainText: "真实的 Markdown 回复",
    rawAnswer: "真实的 Markdown 回复",
    parseFallbackReason: "模型后台未返回可解析的 PPT 文档总结 JSON。"
  });

  assert.strictEqual(helpers.buildPptDocumentOutline(fallback), "真实的 Markdown 回复");
  assert.strictEqual(helpers.buildPptDocumentPlainText(fallback), "真实的 Markdown 回复");
}
console.log("ppt taskpane helper tests passed");
