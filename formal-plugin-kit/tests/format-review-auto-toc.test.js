const assert = require("assert");
const path = require("path");

const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));

function tocParagraph(index, text) {
  return {
    ParagraphIndex: index,
    paragraphIndex: index,
    Text: text,
    Range: { paragraphIndex: index }
  };
}

function testExtractsTablesOfContentsRegionIncludingTitleAndEntries() {
  // Break: plugin ignores TablesOfContents and cannot express a complete auto TOC region.
  assert.strictEqual(typeof helpers.collectWordAutoTocRegions, "function");
  const regions = helpers.collectWordAutoTocRegions({
    TablesOfContents: [{
      Range: {
        Paragraphs: [
          tocParagraph(2, "目录"),
          tocParagraph(3, "一、概述.........1"),
          tocParagraph(4, "二、建设目标.........3")
        ]
      }
    }],
    Fields: [],
    Paragraphs: [
      tocParagraph(1, "项目名称"),
      tocParagraph(2, "目录"),
      tocParagraph(3, "一、概述.........1"),
      tocParagraph(4, "二、建设目标.........3"),
      tocParagraph(5, "正文从这里开始")
    ]
  });

  assert.strictEqual(regions.length, 1);
  assert.strictEqual(regions[0].source, "tables_of_contents");
  assert.strictEqual(regions[0].startParagraphIndex, 2);
  assert.strictEqual(regions[0].endParagraphIndex, 4);
  assert.strictEqual(regions[0].titleParagraphIndex, 2);
  assert.deepStrictEqual(regions[0].paragraphIndexes, [2, 3, 4]);
  assert.ok(String(regions[0].regionId || "").length > 0);
}

function testExtractsTocFieldWhenTablesOfContentsIsMissing() {
  // Break: field-type TOC objects are ignored, so WPS field TOCs never become regions.
  const regions = helpers.collectWordAutoTocRegions({
    TablesOfContents: [],
    Fields: [{
      Type: 13,
      Code: { Text: 'TOC \\o "1-3" \\h \\z \\u' },
      Result: {
        Paragraphs: [
          tocParagraph(10, "1 范围.........2"),
          tocParagraph(11, "2 依据.........4")
        ]
      }
    }]
  });

  assert.strictEqual(regions.length, 1);
  assert.strictEqual(regions[0].source, "field");
  assert.deepStrictEqual(regions[0].paragraphIndexes, [10, 11]);
}

function testAttachesPrecedingTitleToAutoTocRange() {
  // Break: TOC field range without the heading leaves the 目录 title outside the region.
  const regions = helpers.collectWordAutoTocRegions({
    Paragraphs: [
      tocParagraph(5, "目录"),
      tocParagraph(6, "一、概述.........1"),
      tocParagraph(7, "二、范围.........3"),
      tocParagraph(8, "第一章 正文")
    ],
    TablesOfContents: [{
      Range: {
        Paragraphs: [
          tocParagraph(6, "一、概述.........1"),
          tocParagraph(7, "二、范围.........3")
        ]
      }
    }]
  });

  assert.strictEqual(regions.length, 1);
  assert.deepStrictEqual(regions[0].paragraphIndexes, [5, 6, 7]);
  assert.strictEqual(regions[0].titleParagraphIndex, 5);
}

function testBareCatalogWordDoesNotCreateAutoTocRegion() {
  // Break: a lone 目录 paragraph is treated as an auto TOC exemption.
  const regions = helpers.collectWordAutoTocRegions({
    Paragraphs: [
      tocParagraph(1, "目录"),
      tocParagraph(2, "这是普通正文，不是自动目录。")
    ]
  });
  assert.deepStrictEqual(regions, []);
}

function testCoverageAndSnapshotBodyKeepAutoTocRegions() {
  // Break: collected TOC regions are dropped before the snapshot coverage contract.
  const document = {
    TablesOfContents: [{
      Range: {
        Paragraphs: [
          tocParagraph(2, "目录"),
          tocParagraph(3, "一、概述.........1")
        ]
      }
    }],
    Sections: []
  };
  const coverage = helpers.collectFormatReviewCoverage(document);
  assert.ok(Array.isArray(coverage.tocRegions));
  assert.strictEqual(coverage.tocRegions.length, 1);

  const body = helpers.buildDeterministicFormatReviewBody({
    selectionMode: "document",
    content: {
      paragraphs: [
        { index: 2, text: "目录", styleName: "Heading 1" },
        { index: 3, text: "一、概述.........1", styleName: "TOC 1", fontName: "楷体", fontSize: 14 },
        { index: 5, text: "正文从这里开始", styleName: "Normal", fontName: "楷体", fontSize: 14 }
      ],
      documentStructure: {}
    }
  }, { coverage: coverage });

  assert.ok(Array.isArray(body.coverage.tocRegions));
  assert.deepStrictEqual(body.coverage.tocRegions[0].paragraphIndexes, [2, 3]);
}

function testChineseRoleDisplayClosesTocEnums() {
  // Break: toc_title / toc_entry stay unmapped machine enums in the UI.
  assert.strictEqual(helpers.formatReviewRole("toc_title"), "目录标题");
  assert.strictEqual(helpers.formatReviewRole("toc_entry"), "目录项");
}

function testCoverageSummaryShowsSkippedAutoToc() {
  // Break: task pane coverage summary never discloses skipped TOC regions.
  const view = helpers.presentDeterministicFormatReviewIssueView({
    summary: {
      coverageStatus: "complete",
      tocExemptionSummary: "已识别并略过目录：1 个区域，共 23 段",
      exemptedTocRegionCount: 1,
      exemptedTocParagraphCount: 23
    },
    coverage: {
      tocExemptionSummary: "已识别并略过目录：1 个区域，共 23 段"
    },
    issues: []
  });
  assert.ok(view.previewText.includes("已识别并略过目录：1 个区域，共 23 段"));
  assert.ok(view.previewText.includes("覆盖状态："));
  assert.ok(!view.previewText.includes("问题清单"));
}

function testReadableReportDisclosesSkippedAutoToc() {
  const markdown = helpers.renderReadableDeterministicFormatReview({
    summary: {
      coverageStatus: "complete",
      executionStatus: "completed",
      complianceStatus: "passed",
      tocExemptionSummary: "已识别并略过目录：1 个区域，共 23 段"
    },
    issues: []
  });
  assert.ok(markdown.includes("已识别并略过目录：1 个区域，共 23 段"));
}

testExtractsTablesOfContentsRegionIncludingTitleAndEntries();
testExtractsTocFieldWhenTablesOfContentsIsMissing();
testAttachesPrecedingTitleToAutoTocRange();
testBareCatalogWordDoesNotCreateAutoTocRegion();
testCoverageAndSnapshotBodyKeepAutoTocRegions();
testChineseRoleDisplayClosesTocEnums();
testCoverageSummaryShowsSkippedAutoToc();
testReadableReportDisclosesSkippedAutoToc();

console.log("format review auto toc tests passed");
