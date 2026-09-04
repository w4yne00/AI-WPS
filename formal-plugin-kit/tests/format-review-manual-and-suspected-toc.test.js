const assert = require("assert");
const path = require("path");

const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));

function para(index, text, styleName) {
  return {
    ParagraphIndex: index,
    paragraphIndex: index,
    Text: text,
    text: text,
    StyleName: styleName || "Normal",
    styleName: styleName || "Normal",
    Range: { paragraphIndex: index, ParagraphIndex: index, Text: text }
  };
}

function testIdentifiesReliableManualTocWithTitleEntriesAndDots() {
  // Break: manual TOC with title, numbered entries, dot leaders and pages is ignored
  const document = {
    Paragraphs: [
      para(1, "总体方案", "Title"),
      para(2, "目录", "Heading 1"),
      para(3, "一、概述...........................1", "Normal"),
      para(4, "二、建设目标.......................5", "Normal"),
      para(5, "三、总体架构.......................12", "Normal"),
      para(6, "正文第一章 概述")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 1);
  assert.strictEqual(result.manualTocRegions[0].source, "manual_toc");
  assert.deepStrictEqual(result.manualTocRegions[0].paragraphIndexes, [2, 3, 4, 5]);
  assert.strictEqual(result.manualTocRegions[0].titleParagraphIndex, 2);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}

function testIdentifiesReliableManualTocWithoutTitleViaStyleDotsAndPages() {
  // Break: titleless manual TOC with TOC style, dot leaders, and trailing page is ignored
  const document = {
    Paragraphs: [
      para(1, "1.1 总体架构 ................. 2", "TOC 1"),
      para(2, "1.2 实施路径 ................. 4", "TOC 1"),
      para(3, "1.3 预期成效 ................. 8", "TOC 2"),
      para(4, "正文内容开始")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 1);
  assert.strictEqual(result.manualTocRegions[0].source, "manual_toc");
  assert.deepStrictEqual(result.manualTocRegions[0].paragraphIndexes, [1, 2, 3]);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}

function testIdentifiesSuspectedTocWhenEvidenceInsufficient() {
  // Break: consecutive numbered entries + trailing numbers without dot leaders and without title
  const document = {
    Paragraphs: [
      para(1, "一、概述 1"),
      para(2, "二、目标 5"),
      para(3, "三、实施 10"),
      para(4, "正文内容")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 1);
  assert.strictEqual(result.suspectedTocRegions[0].source, "suspected_toc");
  assert.deepStrictEqual(result.suspectedTocRegions[0].paragraphIndexes, [1, 2, 3]);
  assert.ok(String(result.suspectedTocRegions[0].reason || "").length > 0);
}

function testIdentifiesSuspectedTocWithTitleAndDotsWithoutPages() {
  // Break: Title + dots but missing page numbers is marked as suspected
  const document = {
    Paragraphs: [
      para(1, "目录"),
      para(2, "项目概述....................."),
      para(3, "建设目标....................."),
      para(4, "正文")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 1);
  assert.strictEqual(result.suspectedTocRegions[0].source, "suspected_toc");
  assert.deepStrictEqual(result.suspectedTocRegions[0].paragraphIndexes, [1, 2, 3]);
}

function testNegativeCasesDoNotProduceTocRegions() {
  // Negative 1: body referencing 目录
  // Negative 2: normal paragraph ending with numbers
  // Negative 3: isolated dashed line
  const document = {
    Paragraphs: [
      para(1, "本规范请参见详细目录中的说明。"),
      para(2, "项目采购清单第 1 项合计 3000 元。"),
      para(3, "----------------------------------"),
      para(4, "普通正文段落。")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}

function testBareCatalogWordWithoutEntriesDoesNotProduceAnyToc() {
  const document = {
    Paragraphs: [
      para(1, "目录"),
      para(2, "这是正文第一段，不是目录条目。")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}

function testCoverageContractIncludesManualAndSuspectedToc() {
  const document = {
    Paragraphs: [
      para(1, "目录", "Heading 1"),
      para(2, "一、概述...........................1", "Normal"),
      para(3, "二、建设目标.......................5", "Normal"),
      para(4, "正文第一段")
    ],
    Sections: []
  };
  const coverage = helpers.collectFormatReviewCoverage(document);
  assert.ok(Array.isArray(coverage.tocRegions));
  assert.strictEqual(coverage.tocRegions.length, 1);
  assert.strictEqual(coverage.tocRegions[0].source, "manual_toc");
  assert.deepStrictEqual(coverage.tocRegions[0].paragraphIndexes, [1, 2, 3]);
}

testIdentifiesReliableManualTocWithTitleEntriesAndDots();
testIdentifiesReliableManualTocWithoutTitleViaStyleDotsAndPages();
testIdentifiesSuspectedTocWhenEvidenceInsufficient();
testIdentifiesSuspectedTocWithTitleAndDotsWithoutPages();
testNegativeCasesDoNotProduceTocRegions();
testBareCatalogWordWithoutEntriesDoesNotProduceAnyToc();
testCoverageContractIncludesManualAndSuspectedToc();

console.log("format review manual and suspected toc tests passed");
