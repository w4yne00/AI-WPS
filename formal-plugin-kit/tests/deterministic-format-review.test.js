const assert = require("assert");
const fs = require("fs");

const root = "formal-plugin-kit/wps-ai-assistant_1.0.0";
const html = fs.readFileSync(`${root}/taskpane.html`, "utf8");
const js = fs.readFileSync(`${root}/taskpane.js`, "utf8");
const helpers = require("../wps-ai-assistant_1.0.0/taskpane-helpers.js");

function functionSource(name) {
  const start = js.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing function ${name}`);
  const end = js.indexOf("\n  function ", start + 1);
  return js.slice(start, end < 0 ? js.length : end);
}

assert.ok(html.includes('id="btn-run-primary"'));
assert.ok(!html.includes('id="deterministic-format-review-entry"'));
assert.ok(!html.includes('id="btn-run-deterministic-format-review"'));
assert.ok(html.includes('id="deterministic-format-review-diagnostics"'));
assert.ok(js.includes("deterministicFormatReviewEnabled: false"));

const applyConfig = functionSource("applyProviderConfig");
assert.ok(applyConfig.includes("deterministicFormatReviewEnabled"));
assert.ok(applyConfig.includes("resumeDeterministicFormatReviewActiveJob"));

const run = functionSource("runDeterministicFormatReview");
[
  "/word/format-review/snapshots",
  "/word/format-review/jobs",
  "DETERMINISTIC_FORMAT_REVIEW_EXTRACTION_OPTIONS",
  "snapshotToken",
  "pollDeterministicFormatReviewJob"
].forEach((token) => assert.ok(run.includes(token), token));
assert.ok(run.includes("无法开始格式审查"));
assert.ok(run.includes("请确认本地 Adapter 已升级到当前版本并重新启动"));
assert.ok(run.includes("设置 > 高级诊断"));
assert.ok(!run.includes("格式审查 v2 后台任务当前未启用"));
assert.ok(!run.includes("未调用旧同步审查结果链"));
assert.ok(run.includes("ensureDeterministicFormatReviewPreparation"));
assert.ok(js.includes("/image-groups"));
assert.ok(js.includes("SaveAsPicture(slotPath, 2)"));
[
  "InsertAfter",
  "Text =",
  "Delete",
  "applyRewrite"
].forEach((token) => assert.ok(!run.includes(token), token));

const cleanup = functionSource("discardDeterministicFormatReviewSnapshot");
assert.ok(cleanup.includes("/word/format-review/snapshots/"));
assert.ok(cleanup.includes('method: "DELETE"'));

const poll = functionSource("pollDeterministicFormatReviewJob");
assert.ok(poll.includes("/word/format-review/jobs/"));
assert.ok(poll.includes('job.status === "completed"'));
assert.ok(poll.includes("loadDeterministicFormatReviewReport"));
assert.ok(poll.includes("DETERMINISTIC_FORMAT_REVIEW_POLL_RETRY_DELAY_MS"));

const issuePage = functionSource("renderDeterministicFormatReviewIssuePage");
["renderReadableDeterministicFormatReview", "renderDeterministicFormatReviewDiagnostics", "summary", "issues"].forEach((token) => {
  assert.ok(issuePage.includes(token), token);
});
["propertyPath", "formatFactDiagnostics"].forEach((token) => {
  assert.ok(!issuePage.includes(token), token);
});
const locate = functionSource("locateDeterministicFormatReviewIssue");
["textSha256", "adjacentStructureSha256", "anchorVerification", "markDeterministicFormatReviewAnchorVerification"].forEach((token) => {
  assert.ok(locate.includes(token), token);
});
assert.ok(locate.includes('issue.ruleId === "structure.heading_hierarchy"'));
assert.ok(locate.includes('"format-paragraph-" + neighborIndex'));
assert.ok(functionSource("loadDeterministicFormatReviewIssuePage").includes("dataStatus"));
assert.ok(functionSource("downloadDeterministicFormatReviewExport").includes("word-format-review"));
assert.ok(functionSource("bindEvents").includes("format-review-filter-data-status"));
assert.ok(functionSource("cancelDeterministicFormatReviewJob").includes('method: "DELETE"'));

const primary = functionSource("runPrimaryAction");
assert.ok(primary.includes("runDeterministicFormatReview()"));
assert.ok(!primary.includes("runFormatReview();"));
assert.ok(js.includes("saveDeterministicFormatReviewActiveJob"));
assert.ok(js.includes("resumeDeterministicFormatReviewActiveJob"));
assert.ok(js.includes("DETERMINISTIC_FORMAT_REVIEW_ACTIVE_JOB_STORAGE_KEY"));

const readable = helpers.renderReadableDeterministicFormatReview({
  summary: {
    templateId: "technical-document-template-rules",
    executionStatus: "completed",
    complianceStatus: "violations_found",
    coverageStatus: "complete",
    semanticStatus: "degraded",
    rulePackVersion: "1.0.0",
    rulePackSourceVersion: "wx-doc-format 0.12.15"
  },
  issues: [{
    issueId: "format-issue-1",
    ruleId: "font_size",
    role: "body",
    paragraphIndex: 1,
    anchorVerification: "verified",
    sourceAnchor: {
      chapterPath: ["第一章", "1.1 范围"],
      textSnippet: "正文段落",
      pageNumber: 3
    },
    currentValue: "14pt",
    expectedValue: "12pt",
    suggestion: "请调整字号。"
  }]
});
assert.ok(readable.includes("技术文档模板规则"));
assert.ok(readable.includes("规则版本：1.0.0"));
assert.ok(readable.includes("来源版本：wx-doc-format 0.12.15"));
assert.ok(readable.includes("四号（14pt）"));
assert.ok(readable.includes("小四（12pt）"));
assert.ok(readable.includes("章节：第一章 > 1.1 范围；第 1 段；原文：“正文段落”；第 3 页"));
assert.ok(!readable.includes("font_size"));
assert.ok(!readable.includes("violations_found"));

const sectionReadable = helpers.renderReadableDeterministicFormatReview({
  summary: { templateId: "technical-document-template-rules" },
  issues: [{
    ruleId: "section_layout",
    role: "section",
    sourceAnchor: {
      locationScope: "section",
      sectionIndex: 2,
      sectionName: "实施范围",
      chapterPath: ["第二章"],
      pageRange: { start: 3, end: 5 }
    }
  }]
});
assert.ok(sectionReadable.includes("第 2 节：实施范围"));
assert.ok(sectionReadable.includes("第 3 至第 5 页"));
assert.ok(!sectionReadable.includes("无法验证位置"));

const documentReadable = helpers.renderReadableDeterministicFormatReview({
  summary: { templateId: "technical-document-template-rules" },
  issues: [{ ruleId: "page_setup", role: "page_setup" }]
});
assert.ok(documentReadable.includes("页面设置（全文）"));
assert.ok(!documentReadable.includes("P0"));

const pageAwareParagraphs = helpers.collectParagraphs({
  Paragraphs: {
    Count: 1,
    Item: function () {
      return {
        Text: "带位置正文",
        Range: {
          Text: "带位置正文",
          Start: 101,
          End: 106,
          Information: function (kind) {
            return kind === 2 ? 1 : kind === 3 ? 4 : null;
          }
        },
        StyleNameLocal: "Normal",
        Font: { NameFarEast: "宋体", Size: 12 },
        ParagraphFormat: { OutlineLevel: 0 }
      };
    }
  }
}, { includeCharacterFormatSegments: true });
assert.strictEqual(pageAwareParagraphs[0].range.start, 101);
assert.strictEqual(pageAwareParagraphs[0].range.end, 106);
assert.strictEqual(pageAwareParagraphs[0].range.pageNumber, 4);
assert.strictEqual(pageAwareParagraphs[0].range.sectionIndex, 1);

const pageUnavailableParagraphs = helpers.collectParagraphs({
  Paragraphs: {
    Count: 1,
    Item: function () {
      return {
        Text: "无法读取页码的正文",
        Range: {
          Text: "无法读取页码的正文",
          Start: 201,
          End: 210,
          Information: function () { return null; }
        },
        StyleNameLocal: "Normal",
        Font: { NameFarEast: "宋体", Size: 12 },
        ParagraphFormat: { OutlineLevel: 0 }
      };
    }
  }
});
assert.ok(!Object.prototype.hasOwnProperty.call(pageUnavailableParagraphs[0].range, "pageNumber"));
assert.ok(!Object.prototype.hasOwnProperty.call(pageUnavailableParagraphs[0].range, "sectionIndex"));

const preparation = functionSource("ensureDeterministicFormatReviewPreparation");
assert.ok(preparation.includes("检测到文档编辑或文档身份变化"));

const unmapped = helpers.renderReadableDeterministicFormatReview({
  summary: { templateId: "technical-document-template-rules" },
  issues: [{
    ruleId: "font_name",
    role: "body",
    paragraphIndex: 1,
    anchorVerification: "verified",
    currentValue: "Unmapped Font",
    expectedValue: "宋体",
    suggestion: "建议字号调整为 14.5pt。"
  }]
});
assert.ok(unmapped.includes("无法识别"));
assert.ok(!unmapped.includes("Unmapped Font"));
assert.ok(!unmapped.includes("14.5pt"));

const localizedPageAndSpacing = helpers.renderReadableDeterministicFormatReview({
  summary: {
    templateId: "technical-document-template-rules",
    formatFactDiagnostics: {
      blocks: [{
        paragraphIndex: 1,
        facts: {
          lineSpacing: {
            dataStatus: "verified",
            normalizedValue: 1.5,
            normalizedUnit: "multiple",
            mode: "one_point_five"
          }
        }
      }]
    }
  },
  issues: [{
    ruleId: "page_setup",
    role: "page_setup",
    currentValue: JSON.stringify({ paperSize: "A4", marginTop: 720 }),
    expectedValue: "A4 页面及模板页边距"
  }, {
    ruleId: "line_spacing",
    role: "body",
    paragraphIndex: 1,
    anchorVerification: "verified",
    currentValue: "1.5",
    expectedValue: "1"
  }, {
    ruleId: "style_name",
    role: "body",
    paragraphIndex: 1,
    anchorVerification: "verified",
    currentValue: "Normal",
    expectedValue: "heading 1"
  }]
});
assert.ok(localizedPageAndSpacing.includes("纸张：A4"));
assert.ok(localizedPageAndSpacing.includes("上边距 36 磅"));
assert.ok(localizedPageAndSpacing.includes("A4 纸张及模板页边距"));
assert.ok(localizedPageAndSpacing.includes("1.5 倍行距"));
assert.ok(localizedPageAndSpacing.includes("正文样式"));
assert.ok(!localizedPageAndSpacing.includes("Normal"));
assert.ok(!localizedPageAndSpacing.includes("heading 1"));
assert.ok(!localizedPageAndSpacing.includes('"paperSize"'));

const mixedPage = helpers.renderReadableDeterministicFormatReview({
  summary: {
    templateId: "technical-document-template-rules",
    formatFactDiagnostics: {
      pageSetup: {
        marginTop: { dataStatus: "mixed" }
      }
    }
  },
  issues: [{
    ruleId: "page_setup",
    currentValue: JSON.stringify({ paperSize: "A4", marginTop: 720 }),
    expectedValue: "A4 页面及模板页边距"
  }]
});
assert.ok(mixedPage.includes("当前值：格式不一致"));
assert.ok(!mixedPage.includes("当前值：纸张：A4"));

assert.ok(js.includes('configData.features && configData.features.deterministicFormatReviewEnabled'));
assert.ok(js.includes('byId("btn-run-primary")'));
assert.ok(!js.includes('request("/word/format-review", state.latestDocumentPayload)'));
assert.ok(!js.includes("function runFormatReview("));
assert.ok(!js.includes("function renderGroupedFormatReview("));
assert.ok(!js.includes("renderReadableFormatReview"));
assert.ok(js.includes("function runDeterministicFormatReview("));

const body = helpers.buildDeterministicFormatReviewBody({
  documentId: "table.docx",
  selectionMode: "document",
  content: {
    paragraphs: [{ index: 1, text: "正文", styleName: "Normal" }],
    documentStructure: {
      page_setup: { paperSize: "A4", marginTop: 72 },
      tables: [{
        tableId: "table-1",
        rows: [{ cells: [{ text: "表头" }] }, { cells: [{ text: "单元格" }] }]
      }]
    }
  }
});
assert.strictEqual(body.reviewCharacterCount, "正文".length + "表头\n单元格".length);
assert.strictEqual(body.coverage.tableCount, 1);
assert.deepStrictEqual(body.pageSetup, { paperSize: "A4", marginTop: 72 });
assert.strictEqual(body.formatSnapshotSchemaVersion, "word.format_review.snapshot.v2");

const fixedLineSpacing = helpers.normalizeWpsLineSpacingFact(15, "fixed");
assert.strictEqual(fixedLineSpacing.rawUnit, "pt");
assert.strictEqual(fixedLineSpacing.normalizedValue, 300);
assert.strictEqual(fixedLineSpacing.normalizedUnit, "twip");
assert.strictEqual(fixedLineSpacing.mode, "fixed");
const multipleLineSpacing = helpers.normalizeWpsLineSpacingFact(1.25, "multiple");
assert.strictEqual(multipleLineSpacing.normalizedValue, 1.25);
assert.strictEqual(multipleLineSpacing.normalizedUnit, "multiple");
const pageFacts = helpers.buildWpsPageSetupFacts({
  paperSize: 7,
  marginTop: 72,
  marginBottom: 90
});
assert.strictEqual(pageFacts.paperSize.normalizedValue, "A4");
assert.strictEqual(pageFacts.marginTop.normalizedValue, 1440);
assert.strictEqual(pageFacts.marginBottom.normalizedValue, 1800);
const paragraphFacts = helpers.buildWpsFormatFacts({
  fontSize: 12,
  lineSpacing: 15,
  lineSpacingMode: "fixed"
});
assert.strictEqual(paragraphFacts.lineSpacing.normalizedValue, 300);
assert.strictEqual(paragraphFacts.lineSpacing.dataStatus, "verified");
assert.strictEqual(
  helpers.buildWpsFormatFacts({ firstLineIndent: 32 }).firstLineIndent.normalizedValue,
  640
);
const diagnosticLines = [];
helpers.appendFormatFactDiagnostics(diagnosticLines, {
  schemaVersion: "format_snapshot.v2",
  pageSetup: pageFacts,
  statusCounts: { verified: 2, mixed: 1 },
  blocks: [{ paragraphIndex: 1, facts: { lineSpacing: paragraphFacts.lineSpacing } }]
});
assert.ok(diagnosticLines.join("\n").includes("15 pt → 300 twip"));
assert.ok(diagnosticLines.join("\n").includes("mixed 1"));
const batches = helpers.buildDeterministicFormatReviewBatches(body, 1);
assert.ok(batches.length >= 2);
assert.strictEqual(batches[0].characterCount, batches[0].blocks
  .filter((block) => block.scope === "in_scope")
  .reduce((sum, block) => sum + String(block.text || "").length, 0));
const captionBody = helpers.buildDeterministicFormatReviewBody({
  selectionMode: "selection",
  content: {
    paragraphs: [{ index: 1, text: "表 1：测试", styleName: "Caption" }],
    documentStructure: {}
  }
});
assert.strictEqual(captionBody.blocks[0].blockType, "caption");
assert.strictEqual(captionBody.coverage.captionCount, 1);

assert.deepStrictEqual(helpers.getDeterministicFormatReviewCapacity(60000), {
  tier: "standard",
  accepted: true,
  requiresConfirmation: false
});
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(60001).tier, "large");
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(120000).accepted, true);
assert.strictEqual(helpers.getDeterministicFormatReviewCapacity(120001).accepted, false);

const mixedRange = {
  Text: "甲乙丙丁",
  Font: { Name: "混合", Size: 9999999, Bold: 9999999 },
  Characters(start, end) {
    const formats = [
      { Name: "宋体", Size: 12, Bold: false },
      { Name: "宋体", Size: 12, Bold: false },
      { Name: "黑体", Size: 12, Bold: true },
      { Name: "黑体", Size: 14, Bold: true }
    ];
    const first = start - 1;
    const last = end || start;
    const selected = formats.slice(first, last);
    const same = selected.every((item) => JSON.stringify(item) === JSON.stringify(selected[0]));
    return {
      Text: this.Text.slice(first, last),
      Font: same ? selected[0] : { Name: "mixed", Size: 9999999, Bold: 9999999 }
    };
  }
};
const mixedSegments = helpers.extractHomogeneousFormatSegments(mixedRange, { maxSegments: 16 });
assert.strictEqual(mixedSegments.dataStatus, "verified");
assert.deepStrictEqual(mixedSegments.segments.map((item) => [item.start, item.end]), [[0, 2], [2, 3], [3, 4]]);
assert.strictEqual(mixedSegments.segments[0].format.fontName, "宋体");
assert.strictEqual(mixedSegments.segments[2].format.fontSize, 14);

const insufficientSegments = helpers.extractHomogeneousFormatSegments(mixedRange, { maxSegments: 2 });
assert.strictEqual(insufficientSegments.dataStatus, "insufficient");
assert.strictEqual(insufficientSegments.insufficientReason, "format_fragmentation_limit");
assert.strictEqual(helpers.extractHomogeneousFormatSegments({ Text: "无格式属性" }).dataStatus, "insufficient");

const coveredBody = helpers.buildDeterministicFormatReviewBody({
  selectionMode: "document",
  content: {
    paragraphs: [{
      index: 1,
      text: "混合格式正文",
      formatSegments: mixedSegments.segments,
      formatDataStatus: mixedSegments.dataStatus
    }],
    documentStructure: {}
  }
}, {
  coverage: {
    headerFooter: {
      header: { status: "unavailable", failureCount: 1 },
      footer: { status: "read", characterCount: 8 }
    },
    unsupportedObjects: [{ type: "textBox", count: 2, status: "not_supported" }]
  }
});
assert.strictEqual(coveredBody.coverage.formatSegmentCount, 3);
assert.strictEqual(coveredBody.coverage.unsupportedObjectCount, 2);
assert.strictEqual(coveredBody.coverage.headerFooter.header.status, "unavailable");
