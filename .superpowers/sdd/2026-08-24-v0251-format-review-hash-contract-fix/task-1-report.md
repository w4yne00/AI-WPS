# Task 1 报告：v0.25.1 格式审查跨运行时哈希契约修复

日期：2026-08-24
产品版本：`v0.25.1-alpha`
旧候选：`20260824-ccad09f`，已在 `packaging/v0251-candidate-status.json` 登记为 `rejected`；旧归档和校验文件未改动。

## 修改内容

- JavaScript `buildDeterministicFormatReviewBody()` 现在先执行唯一的上传前规范化：固定 range/format/image/table 默认值，递归规范化 nested tables 与 cell format，稳定排序行列，递归生成表格文本，保留普通块 `images: []`，仅保留稳定图片元数据，不读取/上传像素。
- JS 与 Python 同步 WPS `OutlineLevel` 规则（`0/10 → 0`、`1..9` 保持、其它为 `null`），有大纲事实时同步顶层和 `format.outlineLevel`；空 `insufficientReason` 删除，只有不足状态的非空 reason 保留并按 120 字符截断。
- Python `_normalize_format_blocks()` 递归规范化 images、tables、cell formats，并使规范化幂等；图片块保留块级稳定元数据以避免 inventory 重复计数。
- Python `_format_metrics()` 仅收集范围内非空文本，表格无显式文本时按递归行/单元格顺序生成内容镜像，字符数使用 UTF-16 code unit，structure 投影固定加入 `images`，继续独立重算四项哈希并逐项强校验。
- 新增真实 Node→Python 子进程跨运行时测试及 structure/format 篡改 409 负向测试；构建脚本显式传递 `AI_WPS_HASH_CONTRACT_PYTHON="$PYTHON_BIN"`，交付测试锁定门禁且不允许该测试 skip。
- 新增 ADR-0120；更新候选拒绝记录、交付说明、目标机验收模板、README 中英文和 handoff；纳入既有 Sol 计划文件。

## TDD RED/GREEN

RED（修改生产代码前）：

```text
AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test formal-plugin-kit/tests/format-review-hash-contract.test.js
```

真实关键输出：

```text
Traceback ... deterministic_format_review.py:2206 ...
AdapterError: 格式审查图片对象标识无效。
✖ JS and Python agree on v2 format snapshot hashes and metrics
✔ Python rejects structure and format tampering before reviewer execution
tests 2 / pass 1 / fail 1
```

原因：旧 Python 规范化把 `blockType == "image"` 的整个块当成顶层图片事实，而 JS 生产块使用 `images: [{...}]`；同时旧投影/默认值存在 structure/format 漂移。该红灯没有通过缩减夹具规避。

GREEN（修复后）：

```text
AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test formal-plugin-kit/tests/format-review-hash-contract.test.js formal-plugin-kit/tests/deterministic-format-review.test.js
```

```text
tests 3 / pass 3 / fail 0
```

## 测试命令与真实输出

Focused：

```text
PYTHONWARNINGS=ignore PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_deterministic_format_snapshot_protocol.py adapter_service/tests/test_outline_levels.py adapter_service/tests/test_v0251_delivery.py
48 passed in 0.41s
```

完整正式插件：

```text
AI_WPS_HASH_CONTRACT_PYTHON=python3 node --test formal-plugin-kit/tests/*.test.js
tests 19 / pass 19 / fail 0
```

完整 Adapter：

```text
PYTHONWARNINGS=ignore PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests
799 passed, 95 skipped in 50.09s
```

静态与交付检查：

```text
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
python3 packaging/check_python38_compatibility.py adapter_service/app packaging
python38_compatibility_scan=passed files=82
bash -n packaging/build_v0251_delivery_kit.sh
git diff --check
python3 -m json.tool packaging/v0251-candidate-status.json
candidate_status_json=valid
```

本机版本：`Python 3.9.6`、`Node v26.7.0`。本次未构建交付包，未 push/发布；本机没有真实 Python 3.8，因此只报告静态兼容扫描，未宣称 Python 3.8 运行时门禁或目标机验收通过。

## 文件清单

- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- `formal-plugin-kit/tests/format-review-hash-contract.test.js`
- `adapter_service/app/services/word/deterministic_format_review.py`
- `adapter_service/tests/test_v0251_delivery.py`
- `packaging/build_v0251_delivery_kit.sh`
- `packaging/v0251-candidate-status.json`
- `packaging/v0251-delivery.md`
- `packaging/v0251-target-machine-acceptance.md`
- `docs/adr/0120-use-one-cross-runtime-format-review-hash-contract.md`
- `docs/superpowers/plans/2026-08-24-v0251-format-review-hash-contract-fix.md`
- `README.md`
- `README-ZH.md`
- `docs/codex-handoff.md`
- 本报告

## 自审与风险

- 已确认 Python 仍逐项重算 `characterCount/content/structure/format`，不接受客户端声明哈希替代值；structure/format 单独篡改均在 reviewer/provider 前返回 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH`。
- 已确认普通图片空文本不进入内容镜像，图片元数据进入 structure，图片 inventory 只计一次且 `pixelExportCount/pixelUploadCount` 均为 0。
- 已确认受保护的 `.scratch/writing-policy-review/`、`config/adapter.json`、`run/` 和旧历史归档未改动、未纳入提交。
- 风险：本地没有真实 Python 3.8、麒麟 V10/WPS 真机和真实模型服务；这些仍需后续候选构建与 Issue #59 人工验收。完整 Adapter 测试的 95 个 skip 为既有测试环境依赖现状，不是跨运行时哈希门禁的 skip。
