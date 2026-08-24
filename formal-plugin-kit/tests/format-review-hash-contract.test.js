const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "../..");
const helpers = require(path.join(
  ROOT,
  "formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js"
));

const PYTHON_BRIDGE = String.raw`
import json
import os
import sys
import tempfile
import copy
import time
from pathlib import Path

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import DeterministicFormatReviewService


class Reviewer:
    def __init__(self):
        self.calls = 0
        self.requests = []

    def review(self, request, trace_id=""):
        self.calls += 1
        self.requests.append(request)
        return {"issues": [], "summary": {}}


payload = json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
    reviewer = Reviewer()
    service = DeterministicFormatReviewService(
        staging_root=Path(directory),
        reviewer=reviewer,
        coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
    )
    if payload.get("mode") == "metrics":
        normalized = service._normalize_format_blocks(payload["blocks"])
        metrics = service._format_metrics(normalized, payload.get("sourceCoverage"))
        print(json.dumps({"normalized": normalized, "metrics": metrics}, ensure_ascii=False, sort_keys=True))
    elif payload.get("mode") == "protocol":
        first = payload["firstBody"]
        second = payload.get("secondBody", first)
        session = service.create_snapshot({
            "documentId": first["documentId"],
            "selectionMode": first.get("selectionMode", "document"),
            "documentIdentity": first.get("documentIdentity", {}),
            "editSequence": first.get("editSequence"),
            "coverage": first.get("coverage", {}),
        })
        for batch in first["batches"]:
            service.upload_batch(session["snapshotId"], batch["sequence"], {
                "uploadToken": session["uploadToken"],
                "batchId": batch["batchId"],
                "blocks": batch["blocks"],
                "characterCount": batch["characterCount"],
                "contentSha256": batch["contentSha256"],
                "structureSha256": batch["structureSha256"],
                "formatSha256": batch["formatSha256"],
                "editSequence": first.get("editSequence"),
            })
        commit_payload = {
            "uploadToken": session["uploadToken"],
            "batchCount": len(first["batches"]),
            "blockCount": len(first["blocks"]),
            "reviewCharacterCount": first["reviewCharacterCount"],
            "contentSha256": first["contentSha256"],
            "structureSha256": first["structureSha256"],
            "formatSha256": first["formatSha256"],
            "coverage": first["coverage"],
            "verification": {
                "batchCount": len(second["batches"]),
                "blockCount": len(second["blocks"]),
                "reviewCharacterCount": second["reviewCharacterCount"],
                "contentSha256": second["contentSha256"],
                "structureSha256": second["structureSha256"],
                "formatSha256": second["formatSha256"],
                "coverage": second["coverage"],
                "documentIdentity": second.get("documentIdentity", {}),
                "editSequence": second.get("editSequence"),
            },
        }
        committed = service.commit_snapshot(session["snapshotId"], commit_payload)
        job = service.start_job({
            "snapshotId": session["snapshotId"],
            "snapshotToken": committed["snapshotToken"],
            "clientJobId": "format-job-contract-" + str(first["documentId"]).replace(".", "-")[:60],
        }, "format-trace-contract")
        current = None
        for _ in range(200):
            current = service.get_job(job["jobId"])
            if current and current.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        print(json.dumps({
            "status": committed["status"],
            "jobStatus": current.get("status") if current else None,
            "reviewerCalls": reviewer.calls,
            "coverage": committed["coverage"],
        }, ensure_ascii=False, sort_keys=True))
    elif payload.get("mode") == "normalize":
        try:
            normalized = service._normalize_format_blocks(payload["blocks"])
        except AdapterError as error:
            print(json.dumps({"ok": False, "code": error.code, "status": error.status_code}, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps({"ok": True, "normalized": normalized}, ensure_ascii=False, sort_keys=True))
    elif payload.get("mode") == "negative":
        normalized = service._normalize_format_blocks(payload["blocks"])
        metrics = service._format_metrics(normalized)
        results = []
        nested_format_blocks = copy.deepcopy(normalized)
        next(block for block in nested_format_blocks if block.get("blockType") == "table")["nestedTables"][0]["format"]["styleName"] = "TamperedNestedTable"
        cell_text_blocks = copy.deepcopy(normalized)
        next(block for block in cell_text_blocks if block.get("blockType") == "table")["rows"][0]["cells"][0]["text"] = "篡改后的表格正文"
        table_structure_blocks = copy.deepcopy(normalized)
        next(block for block in table_structure_blocks if block.get("blockType") == "table")["rows"][0]["cells"][0]["rowSpan"] = 3
        cases = [
            ("nestedTableFormat", nested_format_blocks),
            ("tableCellText", cell_text_blocks),
            ("tableStructure", table_structure_blocks),
        ]
        for key, tampered_blocks in cases:
            session = service.create_snapshot({"documentId": "contract.docx", "selectionMode": "document"})
            body = {
                "uploadToken": session["uploadToken"],
                "batchId": "format-batch-0",
                "blocks": tampered_blocks,
                "characterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": metrics["structureSha256"],
                "formatSha256": metrics["formatSha256"],
                "editSequence": None,
            }
            try:
                service.upload_batch(session["snapshotId"], 0, body)
            except AdapterError as error:
                results.append({"key": key, "code": error.code, "status": error.status_code})
        print(json.dumps({"results": results, "reviewerCalls": reviewer.calls}, ensure_ascii=False, sort_keys=True))
    elif payload.get("mode") == "canonicalText":
        normalized = service._normalize_format_blocks(payload["blocks"])
        metrics = service._format_metrics(normalized)
        tampered_blocks = copy.deepcopy(normalized)
        tampered_table = next(block for block in tampered_blocks if block.get("blockType") == "table")
        tampered_table["text"] = "客户端篡改的冗余表格正文"
        session = service.create_snapshot({"documentId": "contract.docx", "selectionMode": "document"})
        upload_payload = {
            "uploadToken": session["uploadToken"],
            "batchId": "format-batch-0",
            "blocks": tampered_blocks,
            "characterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "editSequence": None,
        }
        service.upload_batch(session["snapshotId"], 0, upload_payload)
        stored = service._load_snapshot(session["snapshotId"])
        stored_table = next(
            block for block in stored["batches"][0]["blocks"] if block.get("blockType") == "table"
        )
        committed_metrics = service._format_metrics(
            stored["batches"][0]["blocks"], stored.get("sourceCoverage")
        )
        verification = {
            "batchCount": 1,
            "blockCount": len(tampered_blocks),
            "reviewCharacterCount": committed_metrics["characterCount"],
            "contentSha256": committed_metrics["contentSha256"],
            "structureSha256": committed_metrics["structureSha256"],
            "formatSha256": committed_metrics["formatSha256"],
            "coverage": committed_metrics["coverage"],
            "documentIdentity": service._load_snapshot(session["snapshotId"])["documentIdentity"],
            "editSequence": None,
        }
        service.commit_snapshot(session["snapshotId"], {
            "uploadToken": session["uploadToken"],
            "batchCount": 1,
            "blockCount": len(tampered_blocks),
            "reviewCharacterCount": committed_metrics["characterCount"],
            "contentSha256": committed_metrics["contentSha256"],
            "structureSha256": committed_metrics["structureSha256"],
            "formatSha256": committed_metrics["formatSha256"],
            "verification": verification,
        })
        job = service.start_job(
            {"snapshotId": session["snapshotId"], "snapshotToken": session["snapshotToken"]},
            "format-job-canonical",
        )
        for _ in range(100):
            current = service.get_job(job["jobId"])
            if current and current.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        request_blocks = reviewer.requests[-1].content.document_structure["formatBlocks"]
        request_table = next(block for block in request_blocks if block.get("blockType") == "table")
        print(json.dumps({
            "acceptedText": stored_table["text"],
            "requestText": request_table["text"],
            "tamperedText": "客户端篡改的冗余表格正文",
            "reviewerCalls": reviewer.calls,
            "jobStatus": current.get("status") if current else None,
        }, ensure_ascii=False, sort_keys=True))
    else:
        raise SystemExit("unknown mode")
`;

function runPython(input) {
  const python = process.env.AI_WPS_HASH_CONTRACT_PYTHON || "python3";
  const env = Object.assign({}, process.env, {
    PYTHONPATH: path.join(ROOT, "adapter_service")
  });
  return JSON.parse(execFileSync(python, ["-c", PYTHON_BRIDGE], {
    cwd: ROOT,
    env,
    input: JSON.stringify(input),
    encoding: "utf8"
  }));
}

function fixture() {
  const paragraphs = [
    { index: 1, text: "正文😀", outlineLevel: 0, styleName: "Normal" },
    { index: 2, text: "一级标题", outlineLevel: 1, styleName: "Heading 1" },
    { index: 3, text: "三级标题", outlineLevel: 3, styleName: "Heading 3" },
    { index: 4, text: "标题四", outlineLevel: 4, styleName: "Heading 4" },
    { index: 5, text: "标题五", outlineLevel: 5, styleName: "Heading 5" },
    { index: 6, text: "标题六", outlineLevel: 6, styleName: "Heading 6" },
    { index: 7, text: "标题七", outlineLevel: 7, styleName: "Heading 7" },
    { index: 8, text: "标题八", outlineLevel: 8, styleName: "Heading 8" },
    { index: 9, text: "标题九", outlineLevel: 9, styleName: "Heading 9" },
    {
      index: 10,
      text: "不完整𠮷",
      outlineLevel: 10,
      styleName: "Normal",
      formatDataStatus: "insufficient",
      formatInsufficientReason: "format_fragmentation_limit"
    },
    {
      index: 11,
      text: "失败🚀",
      outlineLevel: 0,
      styleName: "Normal",
      formatDataStatus: "read_failed",
      formatInsufficientReason: "should-be-dropped"
    }
  ];
  return {
    documentId: "cross-runtime.docx",
    selectionMode: "document",
    content: {
      paragraphs,
      documentStructure: {
        tables: [{
          tableId: "table-main",
          tableIndex: 1,
          rows: [{
            cells: [{
              text: "表格😀",
              rowSpan: 2,
              columnSpan: 2,
              format: { styleName: "TableCell", fontSize: 12, dataStatus: "verified" }
            }]
          }, {
            rowIndex: 2,
            cells: [{
              cellId: "cell-explicit",
              rowIndex: 2,
              columnIndex: 1,
              text: "单元格🚀",
              format: { styleName: "TableCell", lineSpacing: 15, lineSpacingMode: "fixed", dataStatus: "verified" }
            }]
          }],
          nestedTables: [{
            rows: [{ cells: [{ text: "嵌套𠮷", format: { dataStatus: "verified" } }] }],
            nestedTables: []
          }],
          format: { styleName: "Table", dataStatus: "verified" }
        }]
      }
    },
    options: { templateId: "technical-document-template-rules" }
  };
}

function buildProtocolBody(payload, options) {
  const body = helpers.buildDeterministicFormatReviewBody(payload, Object.assign({
    coverage: helpers.collectFormatReviewCoverage({}),
    documentIdentity: { hostDocumentId: payload.documentId }
  }, options || {}));
  body.batches = helpers.buildDeterministicFormatReviewBatches(body, 3500);
  return body;
}

function compatibilityProtocolFixtures() {
  const cases = [
    ["heading-only", { headingLevel: 2 }],
    ["format-outline-only", { format: { outlineLevel: 2 } }]
  ];
  return cases.map(([label, compatibility]) => {
    const payload = {
      documentId: `contract-outline-${label}.docx`,
      selectionMode: "document",
      content: {
        paragraphs: [{ index: 1, text: "兼容标题", outlineLevel: 2 }],
        documentStructure: {}
      }
    };
    const canonicalBody = buildProtocolBody(payload);
    const compatibilityBlock = JSON.parse(JSON.stringify(canonicalBody.blocks[0]));
    delete compatibilityBlock.outlineLevel;
    delete compatibilityBlock.headingLevel;
    delete compatibilityBlock.format.outlineLevel;
    Object.keys(compatibility).forEach((key) => {
      compatibilityBlock[key] = key === "format"
        ? Object.assign({}, compatibilityBlock.format, compatibility.format)
        : compatibility[key];
    });
    const body = Object.assign({}, canonicalBody, {
      blocks: [helpers.normalizeDeterministicFormatReviewBlock(compatibilityBlock)]
    });
    body.batches = helpers.buildDeterministicFormatReviewBatches(body, 3500);
    return [label, body];
  });
}

function protocolFixtureFamilies() {
  const source = fixture();
  const paragraph = {
    documentId: "contract-paragraph.docx",
    selectionMode: "document",
    content: {
      paragraphs: [source.content.paragraphs[0]],
      documentStructure: {}
    }
  };
  const outline = {
    documentId: "contract-outline.docx",
    selectionMode: "document",
    content: {
      paragraphs: source.content.paragraphs.slice(1, 3),
      documentStructure: {}
    }
  };
  const tableNested = {
    documentId: "contract-table-nested.docx",
    selectionMode: "document",
    content: {
      paragraphs: [{ index: 1, text: "表格前言", outlineLevel: 0 }],
      documentStructure: source.content.documentStructure
    }
  };
  const imageMetadata = {
    documentId: "contract-image-metadata.docx",
    selectionMode: "document",
    content: {
      paragraphs: [{ index: 1, text: "图片说明", outlineLevel: 0 }],
      documentStructure: {}
    }
  };
  const insufficient = {
    documentId: "contract-insufficient.docx",
    selectionMode: "document",
    content: {
      paragraphs: [{
        index: 1,
        text: "格式数据不足",
        outlineLevel: 0,
        formatDataStatus: "insufficient",
        formatInsufficientReason: "format_fragmentation_limit"
      }],
      documentStructure: {}
    }
  };
  const emoji = {
    documentId: "contract-emoji-nonbmp.docx",
    selectionMode: "document",
    content: {
      paragraphs: [{ index: 1, text: "😀🚀𠮷", outlineLevel: 0 }],
      documentStructure: {
        tables: [{
          tableId: "emoji-table",
          tableIndex: 1,
          rows: [{ cells: [{ text: "单元格😀𠮷", format: { dataStatus: "verified" } }] }],
          nestedTables: []
        }]
      }
    }
  };
  return [
    ["paragraph", paragraph, {}],
    ["outline", outline, {}],
    ["table-nested", tableNested, {}],
    ["image-metadata", imageMetadata, {
      imageFacts: [{
        imageId: "image-contract-1",
        groupId: "group-contract-1",
        fingerprint: "fingerprint-contract-1",
        captionStatus: "missing",
        associationStatus: "missing",
        supported: true,
        altText: "示意图",
        nearbyText: "图片说明"
      }]
    }],
    ["insufficient-reason", insufficient, {}],
    ["emoji-nonbmp", emoji, {}]
  ];
}

test("real JS coverage survives snapshot, upload, commit, and job start", () => {
  const results = protocolFixtureFamilies().map(([label, payload, options]) => {
    const firstBody = buildProtocolBody(payload, options);
    const secondBody = buildProtocolBody(payload, options);
    const python = runPython({ mode: "protocol", firstBody, secondBody });
    assert.equal(python.status, "committed", `${label} commit`);
    assert.equal(python.jobStatus, "completed", `${label} job start`);
    assert.ok(python.reviewerCalls >= 1, `${label} reviewer invocation`);
    assert.deepEqual(python.coverage, firstBody.coverage, `${label} coverage equality`);
    return {
      label,
      characterCount: firstBody.reviewCharacterCount,
      imageCount: firstBody.coverage.imageCount,
      formatDataStatus: firstBody.coverage.formatDataStatus
    };
  });
  assert.deepEqual(results.map((item) => item.label), [
    "paragraph", "outline", "table-nested", "image-metadata", "insufficient-reason", "emoji-nonbmp"
  ]);
  assert.equal(results.find((item) => item.label === "image-metadata").imageCount, 1);
  assert.equal(results.find((item) => item.label === "insufficient-reason").formatDataStatus, "insufficient");
  assert.equal(results.find((item) => item.label === "emoji-nonbmp").characterCount, 13);
});

test("outline compatibility fallbacks agree on normalized facts and hashes", () => {
  for (const [label, body] of compatibilityProtocolFixtures()) {
    const block = body.blocks[0];
    assert.equal(block.outlineLevel, 2, `${label} top-level outline`);
    assert.equal(block.format.outlineLevel, 2, `${label} format outline`);
    assert.equal(block.headingLevel, 2, `${label} heading level`);
    const python = runPython({ mode: "metrics", blocks: body.blocks, sourceCoverage: body.coverage });
    for (const key of ["characterCount", "contentSha256", "structureSha256", "formatSha256"]) {
      const jsValue = key === "characterCount" ? body.reviewCharacterCount : body[key];
      assert.equal(python.metrics[key], jsValue, `${label} ${key}`);
    }
    assert.deepEqual(python.metrics.coverage, body.coverage, `${label} coverage`);
  }
});

test("outline normalization preserves source priority and value semantics", () => {
  const cases = [
    {
      label: "top-level-wins",
      block: { blockId: "outline-priority-top", blockType: "heading", headingLevel: 3,
        outlineLevel: 0, text: "正文", format: { outlineLevel: 2 } },
      expected: 0,
      expectedType: "paragraph"
    },
    {
      label: "format-fallback",
      block: { blockId: "outline-priority-format", blockType: "heading", headingLevel: 3,
        text: "二级标题", format: { outlineLevel: 2 } },
      expected: 2,
      expectedType: "heading"
    },
    {
      label: "heading-fallback",
      block: { blockId: "outline-priority-heading", blockType: "heading", headingLevel: 3,
        text: "三级标题", format: {} },
      expected: 3,
      expectedType: "heading"
    },
    {
      label: "explicit-null",
      block: { blockId: "outline-priority-null", blockType: "heading", headingLevel: 3,
        outlineLevel: null, text: "未知层级", format: { outlineLevel: 2 } },
      expected: null,
      expectedType: "unknown"
    },
    {
      label: "undefined-falls-through",
      block: { blockId: "outline-priority-undefined", blockType: "heading", headingLevel: 3,
        outlineLevel: undefined, text: "二级标题", format: { outlineLevel: 2 } },
      expected: 2,
      expectedType: "heading"
    },
    {
      label: "all-absent",
      block: { blockId: "outline-priority-absent", blockType: "paragraph", text: "正文", format: {} },
      expected: undefined,
      expectedType: "paragraph"
    }
  ];
  for (const item of cases) {
    const sourceBlock = Object.assign({ paragraphIndex: 0 }, item.block);
    const normalized = helpers.normalizeDeterministicFormatReviewBlock(sourceBlock);
    const python = runPython({ mode: "normalize", blocks: [sourceBlock] });
    assert.equal(python.ok, true, `${item.label} Python normalization`);
    const pythonBlock = python.normalized[0];
    const hasTopLevel = Object.prototype.hasOwnProperty.call(normalized, "outlineLevel");
    const hasFormat = Object.prototype.hasOwnProperty.call(normalized.format, "outlineLevel");
    assert.equal(hasTopLevel, item.expected !== undefined, `${item.label} top-level presence`);
    assert.equal(hasFormat, item.expected !== undefined, `${item.label} format presence`);
    if (item.expected !== undefined) {
      assert.equal(normalized.outlineLevel, item.expected, `${item.label} value`);
      assert.equal(normalized.format.outlineLevel, item.expected, `${item.label} format value`);
    }
    assert.equal(normalized.blockType, item.expectedType, `${item.label} block type`);
    assert.deepEqual(pythonBlock, normalized, `${item.label} cross-runtime normalized block`);
  }
  for (const [value, expected] of [[0, 0], [10, 0], ...Array.from({ length: 9 }, (_, i) => [i + 1, i + 1])]) {
    const normalized = helpers.normalizeDeterministicFormatReviewBlock({
      blockId: `outline-value-${value}`,
      blockType: "heading",
      headingLevel: value,
      text: `级别${value}`,
      format: {}
    });
    assert.equal(normalized.outlineLevel, expected, `value ${value}`);
    assert.equal(normalized.format.outlineLevel, expected, `format value ${value}`);
  }
});

test("outline compatibility fallbacks survive the full snapshot protocol", () => {
  for (const [label, body] of compatibilityProtocolFixtures()) {
    const python = runPython({ mode: "protocol", firstBody: body, secondBody: body });
    assert.equal(python.status, "committed", `${label} commit`);
    assert.equal(python.jobStatus, "completed", `${label} job start`);
    assert.ok(python.reviewerCalls >= 1, `${label} reviewer invocation`);
    assert.deepEqual(python.coverage, body.coverage, `${label} protocol coverage`);
  }
});

test("JS and Python agree on v2 format snapshot hashes and metrics", () => {
  const sourceCoverage = helpers.collectFormatReviewCoverage({});
  const imageOptions = {
    coverage: sourceCoverage,
    imageFacts: [{
      imageId: "image-1",
      groupId: "group-1",
      fingerprint: "fp-1",
      captionStatus: "missing",
      associationStatus: "missing",
      supported: true,
      altText: "示意图",
      nearbyText: "图示"
    }]
  };
  const body = helpers.buildDeterministicFormatReviewBody(fixture(), imageOptions);
  const python = runPython({
    mode: "metrics",
    blocks: body.blocks,
    sourceCoverage
  });
  const keys = ["characterCount", "contentSha256", "structureSha256", "formatSha256"];
  for (const key of keys) {
    assert.equal(python.metrics[key], body[key === "characterCount" ? "reviewCharacterCount" : key], key);
  }
  assert.deepEqual(runPython({ mode: "metrics", blocks: python.normalized }).normalized, python.normalized);
  assert.ok(body.blocks.every((block) => Array.isArray(block.images)), "images must always be present");
  assert.equal(body.blocks.find((block) => block.blockId === "format-paragraph-10").format.insufficientReason,
    "format_fragmentation_limit");
  assert.equal(Object.prototype.hasOwnProperty.call(
    body.blocks.find((block) => block.blockId === "format-paragraph-11").format,
    "insufficientReason"
  ), false);
  const withoutImage = helpers.buildDeterministicFormatReviewBody(fixture());
  assert.notEqual(body.structureSha256, withoutImage.structureSha256);
  const changedReasonFixture = fixture();
  changedReasonFixture.content.paragraphs[9].formatInsufficientReason = "changed_reason";
  const changedReason = helpers.buildDeterministicFormatReviewBody(changedReasonFixture, imageOptions);
  const reasonNeutral = JSON.parse(JSON.stringify(changedReason));
  reasonNeutral.blocks.find((block) => block.blockId === "format-paragraph-10")
    .format.insufficientReason = body.blocks.find((block) => block.blockId === "format-paragraph-10")
    .format.insufficientReason;
  assert.deepEqual(reasonNeutral.blocks, JSON.parse(JSON.stringify(body.blocks)));
  assert.notEqual(body.formatSha256, changedReason.formatSha256);
  assert.equal(python.metrics.characterCount, body.reviewCharacterCount);
  assert.equal(python.metrics.coverage.imageCount, 1);
  assert.equal(python.metrics.coverage.pixelExportCount, 0);
  assert.equal(python.metrics.coverage.pixelUploadCount, 0);
  assert.deepEqual(body.coverage, python.metrics.coverage, "coverage projection");
  for (const key of [
    "formatFactStatusCounts", "unsupportedObjectsByType", "imageCount",
    "supportedImageCount", "missingFigureCaptionCount", "textEvidenceOnlyCount",
    "imageNotAssessableCount", "notAssessableCount", "pixelExportCount",
    "pixelUploadCount", "pixelInspectedCount", "imageSemanticStatus", "imageSemanticReason"
  ]) {
    assert.ok(Object.prototype.hasOwnProperty.call(body.coverage, key), `coverage field ${key}`);
  }
  assert.equal(Object.prototype.hasOwnProperty.call(body.coverage, "unsupportedObjects"), false);

  for (const batch of helpers.buildDeterministicFormatReviewBatches(body, 20)) {
    const batchPython = runPython({ mode: "metrics", blocks: batch.blocks, sourceCoverage });
    for (const key of keys) {
      assert.equal(batchPython.metrics[key], batch[key === "characterCount" ? "characterCount" : key],
        `batch ${batch.sequence} ${key}`);
    }
  }
});

test("outline facts preserve absent, undefined, null, body, and heading semantics", () => {
  const cases = [
    { label: "absent", paragraph: { index: 1, text: "缺失" }, expected: undefined },
    { label: "undefined", paragraph: { index: 2, text: "未定义", outlineLevel: undefined }, expected: undefined },
    { label: "null", paragraph: { index: 3, text: "显式空值", outlineLevel: null }, expected: null },
    { label: "zero", paragraph: { index: 4, text: "正文零级", outlineLevel: 0 }, expected: 0 },
    { label: "ten", paragraph: { index: 5, text: "正文十级", outlineLevel: 10 }, expected: 0 },
    ...Array.from({ length: 9 }, (_, index) => ({
      label: String(index + 1),
      paragraph: { index: 6 + index, text: `标题${index + 1}`, outlineLevel: index + 1 },
      expected: index + 1
    }))
  ];

  for (const item of cases) {
    const body = helpers.buildDeterministicFormatReviewBody({
      documentId: `outline-${item.label}.docx`,
      selectionMode: "document",
      content: { paragraphs: [item.paragraph] }
    });
    const block = body.blocks[0];
    const hasOutline = Object.prototype.hasOwnProperty.call(block, "outlineLevel");
    const hasFormatOutline = Object.prototype.hasOwnProperty.call(block.format, "outlineLevel");
    assert.equal(hasOutline, item.expected !== undefined, `${item.label} top-level fact presence`);
    assert.equal(hasFormatOutline, item.expected !== undefined, `${item.label} format fact presence`);
    if (item.expected !== undefined) {
      assert.equal(block.outlineLevel, item.expected, `${item.label} top-level value`);
      assert.equal(block.format.outlineLevel, item.expected, `${item.label} format value`);
    }

    const renormalized = helpers.normalizeDeterministicFormatReviewBlock(
      JSON.parse(JSON.stringify(block))
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(renormalized, "outlineLevel"),
      item.expected !== undefined,
      `${item.label} second normalization top-level fact presence`
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(renormalized.format, "outlineLevel"),
      item.expected !== undefined,
      `${item.label} second normalization format fact presence`
    );
    const python = runPython({ mode: "normalize", blocks: [renormalized] });
    assert.equal(python.ok, true, `${item.label} Python normalization`);
    const pythonBlock = python.normalized[0];
    assert.equal(
      Object.prototype.hasOwnProperty.call(pythonBlock, "outlineLevel"),
      item.expected !== undefined,
      `${item.label} cross-runtime top-level fact presence`
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(pythonBlock.format, "outlineLevel"),
      item.expected !== undefined,
      `${item.label} cross-runtime format fact presence`
    );
    if (item.expected !== undefined) {
      assert.equal(pythonBlock.outlineLevel, item.expected, `${item.label} cross-runtime value`);
      assert.equal(pythonBlock.format.outlineLevel, item.expected, `${item.label} cross-runtime format value`);
    }
  }
});

test("same image block metadata changes are structure-sensitive", () => {
  const build = (overrides) => helpers.buildDeterministicFormatReviewBody(fixture(), {
    imageFacts: [{
      imageId: "image-1",
      groupId: "group-1",
      fingerprint: "fp-1",
      captionStatus: "missing",
      associationStatus: "missing",
      supported: true,
      altText: "示意图",
      nearbyText: "图示",
      ...overrides
    }]
  });
  const baseline = build({});
  const baselineIds = baseline.blocks.map((block) => block.blockId);
  const baselineTypes = baseline.blocks.map((block) => block.blockType);

  for (const change of [
    { fingerprint: "fp-2" },
    { altText: "更新后的示意图" },
    { nearbyText: "更新后的图示" },
    { associationStatus: "captioned" }
  ]) {
    const changed = build(change);
    assert.deepEqual(changed.blocks.map((block) => block.blockId), baselineIds);
    assert.deepEqual(changed.blocks.map((block) => block.blockType), baselineTypes);
    assert.notEqual(changed.structureSha256, baseline.structureSha256, JSON.stringify(change));
    const pythonBaseline = runPython({ mode: "metrics", blocks: baseline.blocks });
    const pythonChanged = runPython({ mode: "metrics", blocks: changed.blocks });
    assert.notEqual(
      pythonChanged.metrics.structureSha256,
      pythonBaseline.metrics.structureSha256,
      `Python ${JSON.stringify(change)}`
    );
    assert.equal(
      pythonChanged.metrics.structureSha256,
      changed.structureSha256,
      `cross-runtime ${JSON.stringify(change)}`
    );
  }
});

test("JS upload normalization is idempotent for canonical blocks", () => {
  const body = helpers.buildDeterministicFormatReviewBody(fixture(), {
    imageFacts: [{
      imageId: "image-1",
      groupId: "group-1",
      fingerprint: "fp-1",
      captionStatus: "missing",
      associationStatus: "missing",
      supported: true,
      altText: "示意图",
      nearbyText: "图示"
    }]
  });
  const canonicalBlocks = JSON.parse(JSON.stringify(body.blocks));
  const renormalizedBlocks = canonicalBlocks.map((block) =>
    helpers.normalizeDeterministicFormatReviewBlock(block)
  );
  assert.equal(JSON.stringify(renormalizedBlocks), JSON.stringify(body.blocks));
});

test("Python rejects structure and format tampering before reviewer execution", () => {
  const body = helpers.buildDeterministicFormatReviewBody(fixture());
  const result = runPython({ mode: "negative", blocks: body.blocks });
  assert.deepEqual(result.results, [
    { key: "nestedTableFormat", code: "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH", status: 409 },
    { key: "tableCellText", code: "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH", status: 409 },
    { key: "tableStructure", code: "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH", status: 409 }
  ]);
  assert.equal(result.reviewerCalls, 0);
});

test("Adapter replaces a tampered table block text before provider request", () => {
  const body = helpers.buildDeterministicFormatReviewBody(fixture());
  const result = runPython({ mode: "canonicalText", blocks: body.blocks });
  const canonicalText = "表格😀\n单元格🚀\n嵌套𠮷";
  assert.equal(result.acceptedText, canonicalText);
  assert.equal(result.requestText, canonicalText);
  assert.notEqual(result.acceptedText, result.tamperedText);
  assert.notEqual(result.requestText, result.tamperedText);
  assert.equal(result.reviewerCalls, 1);
  assert.equal(result.jobStatus, "completed");
});

test("numeric format boundaries are cross-runtime stable or rejected", () => {
  const decimalFixture = fixture();
  decimalFixture.content.paragraphs[0].fontSize = -0;
  decimalFixture.content.paragraphs[0].lineSpacing = 1.25;
  decimalFixture.content.paragraphs[0].lineSpacingMode = "multiple";
  const decimalBody = helpers.buildDeterministicFormatReviewBody(decimalFixture);
  const decimalPython = runPython({ mode: "metrics", blocks: decimalBody.blocks });
  for (const key of ["contentSha256", "structureSha256", "formatSha256"]) {
    assert.equal(decimalPython.metrics[key], decimalBody[key], key);
  }
  assert.equal(decimalBody.blocks[0].format.fontSize, 0);
  assert.equal(decimalBody.blocks[0].format.lineSpacing, 1.25);

  for (const exponentValue of [1e-7, 1e-5]) {
    const exponentFixture = fixture();
    exponentFixture.content.paragraphs[0].fontSize = exponentValue;
    assert.throws(
      () => helpers.buildDeterministicFormatReviewBody(exponentFixture),
      /数值表示/
    );
    const exponentBody = helpers.buildDeterministicFormatReviewBody(fixture());
    exponentBody.blocks[0].format.fontSize = exponentValue;
    assert.deepEqual(runPython({ mode: "normalize", blocks: exponentBody.blocks }), {
      code: "DETERMINISTIC_FORMAT_REVIEW_NUMBER_INVALID",
      ok: false,
      status: 400
    });
  }
});
