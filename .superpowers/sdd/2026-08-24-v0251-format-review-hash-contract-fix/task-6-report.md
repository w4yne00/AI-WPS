# Task 6 报告：跨运行时 coverage 契约最终修复

## 结论

基于 `68b34bb720d3ac8fe491b974565fc09b5c5ed3e0` 完成 JS coverage canonical
projection、真实 snapshot/upload/commit/job 对拍和交付状态同步。旧的
`5318d4b496d272a5f34bd270c714216f5b6c2e43` 归档保持原字节并登记为
`rejected`；本轮没有构建新归档，修复源尚未形成候选。

## RED：修复前真实复现

在修改前，使用基线提交中的真实
`buildDeterministicFormatReviewBody()`、`buildDeterministicFormatReviewBatches()`，
以及当前 Adapter 的真实 `DeterministicFormatReviewService`，按 snapshot →
upload_batch → commit_snapshot 顺序执行。以下是完整可复现命令（命令内部只把
基线 JS helper 写入临时目录，不修改工作区）：

```text
PYTHONPATH=adapter_service node <<'NODE'
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const base = "68b34bb720d3ac8fe491b974565fc09b5c5ed3e0";
const repo = process.cwd();
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "ai-wps-red-"));
const oldHelpersPath = path.join(temp, "taskpane-helpers.js");
fs.writeFileSync(oldHelpersPath, execFileSync("git", [
  "show", base + ":formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js"
], { cwd: repo }));
const helpers = require(oldHelpersPath);
const payload = {
  documentId: "red-contract.docx",
  selectionMode: "document",
  content: { paragraphs: [{ index: 1, text: "最小段落", outlineLevel: 0 }], documentStructure: {} }
};
const body = helpers.buildDeterministicFormatReviewBody(payload, {
  coverage: helpers.collectFormatReviewCoverage({})
});
body.batches = helpers.buildDeterministicFormatReviewBatches(body, 3500);
const python = String.raw`import json, sys, tempfile
from pathlib import Path
from app.core.errors import AdapterError
from app.services.word.deterministic_format_review import DeterministicFormatReviewService
body = json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
    service = DeterministicFormatReviewService(staging_root=Path(directory))
    session = service.create_snapshot({"documentId": body["documentId"], "selectionMode": body["selectionMode"], "documentIdentity": body.get("documentIdentity", {}), "coverage": body["coverage"]})
    for batch in body["batches"]:
        service.upload_batch(session["snapshotId"], batch["sequence"], {"uploadToken": session["uploadToken"], "batchId": batch["batchId"], "blocks": batch["blocks"], "characterCount": batch["characterCount"], "contentSha256": batch["contentSha256"], "structureSha256": batch["structureSha256"], "formatSha256": batch["formatSha256"]})
    try:
        committed = service.commit_snapshot(session["snapshotId"], {"uploadToken": session["uploadToken"], "batchCount": len(body["batches"]), "blockCount": len(body["blocks"]), "reviewCharacterCount": body["reviewCharacterCount"], "contentSha256": body["contentSha256"], "structureSha256": body["structureSha256"], "formatSha256": body["formatSha256"], "coverage": body["coverage"], "verification": {"batchCount": len(body["batches"]), "blockCount": len(body["blocks"]), "reviewCharacterCount": body["reviewCharacterCount"], "contentSha256": body["contentSha256"], "structureSha256": body["structureSha256"], "formatSha256": body["formatSha256"], "coverage": body["coverage"], "documentIdentity": body.get("documentIdentity", {}), "editSequence": None}})
    except AdapterError as error:
        print(json.dumps({"code": error.code, "message": error.message, "status": "error", "statusCode": error.status_code}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps({"status": committed["status"]}, ensure_ascii=False, sort_keys=True))`;
const result = execFileSync("python3", ["-c", python], { cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, "adapter_service") }, input: JSON.stringify(body), encoding: "utf8" });
process.stdout.write(result);
NODE
```

基线输出：

```json
{"code":"DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_MISMATCH","message":"格式审查快照首遍指标不一致，已清理暂存数据，请停止编辑后重试。","status":"error","statusCode":409}
```

原因是 JS coverage 缺少 Adapter 重算的 `formatFactStatusCounts`、
`unsupportedObjectsByType`、图片计数/像素计数/语义禁用字段，并在空数组和状态
语义上存在差异。

## GREEN：修复与回归

- `AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test formal-plugin-kit/tests/format-review-hash-contract.test.js`：`8 passed`。
- `AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test formal-plugin-kit/tests/*.test.js`：`25 passed, 0 failed`。
- `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_deterministic_format_snapshot_protocol.py adapter_service/tests/test_outline_levels.py adapter_service/tests/test_v0251_delivery.py`：`75 passed`。
- `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_v0251_delivery.py`：`39 passed`。
- `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests`：`826 passed, 95 skipped`。
- `python3 packaging/check_python38_compatibility.py adapter_service/app packaging`：`python38_compatibility_scan=passed files=82`。
- `node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js && node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`：通过。
- `bash -n packaging/build_v0251_delivery_kit.sh`：通过。
- `git diff --check`：通过。

新增真实协议回归覆盖六类独立 fixture：paragraph、outline/headings、table/nested
table、image metadata、`insufficientReason`、emoji/non-BMP；每类均完成真实
JS body/batches → Python snapshot → batch upload → commit → job start，且断言
`coverage` 与 Adapter 独立重算相等、job 完成、reviewer 被调用。图片断言保持
`pixelExportCount=0`、`pixelUploadCount=0`。结构/格式篡改的 fail-closed 409
回归仍保留。

## 变更文件

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`：新增唯一 JS
  coverage projection，补齐固定字段、状态统计、图片/不支持对象统计和空值省略规则。
- `formal-plugin-kit/tests/format-review-hash-contract.test.js`：改用真实 JS
  coverage，新增六类完整协议回归及 coverage 精确断言。
- `packaging/v0251-candidate-status.json`：追加 `5318d4b` 的 rejected 记录，保留
  归档名、`.sha256` 文件和 SHA-256 原值。
- `docs/adr/0120-use-one-cross-runtime-format-review-hash-contract.md`：记录持久
  决策状态，并将候选状态链接到动态 status JSON/handoff。
- `README.md`、`README-ZH.md`、`docs/codex-handoff.md`、`packaging/v0251-delivery.md`、
  `packaging/v0251-target-machine-acceptance.md`：同步无活动候选、拒绝原因、实际
  测试计数和人工验收边界。
- `adapter_service/tests/test_v0251_delivery.py`：同步 rejected 状态及实际计数断言。

## 自审与关注项

- Adapter 仍对 coverage 与四项指标独立重算，commit 仍保持精确、fail-closed 比较；没有把客户端值回填为服务端可信值，也没有放宽 409 边界。
- 图片 coverage 只统计稳定元数据，语义开关和像素计数保持禁用；没有新增像素导出/上传路径。
- 工作区缺少 `/mnt/ai-wps-test-venv/bin/python`，因此简报要求的真实 Python 3.8 focused/full/lifecycle 命令无法执行；已用当前 Python 运行完整 Adapter、兼容性扫描和所有 focused 测试，不能替代目标 Python 3.8/WPS 真机验收。
- Issue #59 目标 WPS GUI、真实模型和人工文档验收仍为 `manual-pending`；旧归档不得分发，本轮未构建、推送或发布新归档。

修复实现提交：`c53ec3b`；本报告随后作为独立报告提交收录。
