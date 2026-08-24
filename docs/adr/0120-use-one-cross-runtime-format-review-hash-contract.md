# ADR-0120：格式审查使用统一跨运行时哈希契约

状态：已接受（代码修复中；新候选待构建）
日期：2026-08-24

## 背景

`word.format_review.snapshot.v2` 由 WPS JavaScript 生成批次，Adapter Python 在信任边界再次规范化并重算指标。历史候选 `20260824-ccad09f` 在两端使用了不同的哈希前镜像：普通块的 `images`、空 `insufficientReason`、WPS 大纲级别、图片空文本和递归表格默认值存在漂移，导致相同用户文档可能在结构或格式校验阶段返回批次哈希不一致。该候选已登记为 `rejected`；产品版本仍保持 `v0.25.1-alpha`，修复后再单独构建新候选。

## 决策

两端都遵守同一条不可关闭的逻辑：

1. 先规范化块，再生成固定投影；
2. 内容镜像按块顺序收集 `scope == "in_scope"` 的非空文本，以 `\n` 连接；表格按稳定行列顺序递归收集，图片空文本不制造换行；
3. `characterCount` 使用 UTF-16 code unit；哈希输入使用 UTF-8；
4. 结构投影固定为 `blockId/blockType/scope/paragraphIndex/range/tableId/tableIndex/headingLevel/listLabel/captionFor/rows/nestedTables/images`，`images` 始终存在，图片只保留 `imageId/groupId/fingerprint/captionStatus/associationStatus/supported/altText/nearbyText`；
5. 格式投影固定为 `blockId/scope/format/segments/table`，表格与 cell format 递归投影；
6. 空 `insufficientReason` 删除，仅在 `dataStatus="insufficient"` 且 reason 非空时保留；
7. WPS `OutlineLevel` 的 `0`、`10` 规范为正文 `0`，`1..9` 保持，其他为 `null`；存在大纲事实时块顶层和 `format.outlineLevel` 同步；
8. 规范 JSON 使用紧凑、稳定、按键排序的序列化，不 ASCII 转义中文或 emoji，再计算 SHA-256。

JavaScript 上传前规范化与 Python `_normalize_format_blocks()` 都必须幂等；Python `_format_metrics()` 继续独立重算 `characterCount`、`contentSha256`、`structureSha256` 和 `formatSha256`，四项逐项比较失败时固定返回 `409 DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH`，并且不保存批次、不启动 reviewer/provider。两端不得通过删除结构、图片或格式事实来换取一致。

## 取舍与替代方案

拒绝以下方案：

- 关闭或放宽 structure/format 校验，或只校验 content；这会使快照完整性失去意义；
- 直接信任 WPS 传入的哈希，或把 Python 重算值回填为客户端声明；这会越过 Adapter 信任边界；
- 删除图片、表格、cell format 或其它结构维度，换取两端哈希相同；这会隐瞒审查覆盖范围；
- 继续保留 JS/Python 两套字段默认值，或增加第三套兼容投影；这会把同一契约重新分叉。

## 验证与后续

`formal-plugin-kit/tests/format-review-hash-contract.test.js` 通过子进程调用生产 JavaScript body/batch builder 及生产 Python 规范化/指标方法，覆盖标题、正文、递归表格、图片元数据、insufficient reason 和非 BMP 字符，并覆盖 structure/format 篡改的 409 负向边界。新候选必须在代码审查和完整测试后单独构建；在此之前不得宣称新归档、SHA-256、`passed` 或 `target-accepted`。
