# Word 全篇审查分片结果纠正

上一次输出未通过严格契约校验。请只返回完整的 `word.document_review.full.chunk.v2` JSON。

必须包含 `facts`、`crossChecks` 和 `issues` 数组；每个问题必须提供锚点内 UTF-16 起始偏移 `anchorStart`；跨章节问题可额外提供 `anchors` 数组，数组每项只包含 `anchorId`、`anchorStart`、`originalText`；所有锚点必须来自当前分片的核心内容块，不能引用 overlap 上下文块。不得输出 Markdown、解释、代码围栏或任何额外字段。
