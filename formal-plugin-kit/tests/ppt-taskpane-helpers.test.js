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

function textFrameShape(text) {
  return {
    TextFrame: {
      HasText: true,
      TextRange: { Text: text }
    }
  };
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
  const titleShape = options && options.noTitle ? null : textFrameShape(title);
  const shapes = (titleShape ? [titleShape] : []).concat(bodyShapes || []);
  const shapeCollection = collection(shapes);
  if (titleShape) {
    shapeCollection.Title = titleShape;
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
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), ["正文内容"]);
  assert.strictEqual(result.slide.previousTitle, "");
  assert.strictEqual(result.slide.nextTitle, "");
}

{
  const titleOnly = slide(1, "仅标题页", []);
  const result = helpers.extractPresentationSlide(applicationFor([titleOnly], 1), limits);

  assert.strictEqual(result.slide.title, "仅标题页");
  assert.deepStrictEqual(Array.from(result.slide.textBlocks), []);
  assert.strictEqual(result.slide.bodyCharacterCount, 0);
}

{
  const blank = slide(1, "", [], { noTitle: true });
  const result = helpers.extractPresentationSlide(applicationFor([blank], 1), limits);

  assert.strictEqual(result.slide.title, "");
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

assert.strictEqual(helpers.truncateText("abcdef", 3), "abc");
console.log("ppt taskpane helper tests passed");
