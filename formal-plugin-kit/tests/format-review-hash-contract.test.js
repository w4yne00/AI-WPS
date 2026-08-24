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
from pathlib import Path

from app.core.errors import AdapterError
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.word.deterministic_format_review import DeterministicFormatReviewService


class Reviewer:
    def __init__(self):
        self.calls = 0

    def review(self, request, trace_id=""):
        self.calls += 1
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
        metrics = service._format_metrics(normalized)
        print(json.dumps({"normalized": normalized, "metrics": metrics}, ensure_ascii=False, sort_keys=True))
    elif payload.get("mode") == "negative":
        normalized = service._normalize_format_blocks(payload["blocks"])
        metrics = service._format_metrics(normalized)
        session = service.create_snapshot({"documentId": "contract.docx", "selectionMode": "document"})
        results = []
        for key in ("structureSha256", "formatSha256"):
            bad = dict(metrics)
            bad[key] = "0" * 64
            body = {
                "uploadToken": session["uploadToken"],
                "batchId": "format-batch-0",
                "blocks": normalized,
                "characterCount": metrics["characterCount"],
                "contentSha256": metrics["contentSha256"],
                "structureSha256": bad["structureSha256"],
                "formatSha256": bad["formatSha256"],
                "editSequence": None,
            }
            try:
                service.upload_batch(session["snapshotId"], 0, body)
            except AdapterError as error:
                results.append({"key": key, "code": error.code, "status": error.status_code})
        print(json.dumps({"results": results, "reviewerCalls": reviewer.calls}, ensure_ascii=False, sort_keys=True))
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

test("JS and Python agree on v2 format snapshot hashes and metrics", () => {
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
  const python = runPython({ mode: "metrics", blocks: body.blocks });
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
  const changedReason = helpers.buildDeterministicFormatReviewBody(changedReasonFixture);
  assert.notEqual(body.formatSha256, changedReason.formatSha256);
  assert.equal(python.metrics.characterCount,
    body.blocks.filter((block) => block.scope === "in_scope")
      .reduce((sum, block) => sum + String(block.text || "").length, 0));
  assert.equal(python.metrics.coverage.imageCount, 1);
  assert.equal(python.metrics.coverage.pixelExportCount, 0);
  assert.equal(python.metrics.coverage.pixelUploadCount, 0);

  for (const batch of helpers.buildDeterministicFormatReviewBatches(body, 20)) {
    const batchPython = runPython({ mode: "metrics", blocks: batch.blocks });
    for (const key of keys) {
      assert.equal(batchPython.metrics[key], batch[key === "characterCount" ? "characterCount" : key],
        `batch ${batch.sequence} ${key}`);
    }
  }
});

test("Python rejects structure and format tampering before reviewer execution", () => {
  const body = helpers.buildDeterministicFormatReviewBody(fixture());
  const result = runPython({ mode: "negative", blocks: body.blocks });
  assert.deepEqual(result.results, [
    { key: "structureSha256", code: "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH", status: 409 },
    { key: "formatSha256", code: "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH", status: 409 }
  ]);
  assert.equal(result.reviewerCalls, 0);
});
