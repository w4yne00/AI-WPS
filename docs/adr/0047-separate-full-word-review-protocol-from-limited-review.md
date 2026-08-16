# Word 全篇审查使用独立协议并复用同一模型配置

现有 `/word/document-review` 与 `/word/document-review/jobs` 继续表示限量单次审查，保持工作流平台兼容、现有请求结构和 Markdown 降级；全篇审查通过独立的 `/word/document-review/full/...` 暂存、任务、分页问题和报告接口完成。两种模式仍共用用户可见的文档审查功能、`word.document_review` 模型配置、API Key和共享协调器，通过 `reviewMode=limited/full` 区分诊断与结果。

在同一个提交和终态接口中联合全文正文、快照会话、分页摘要和两种解析契约，会使旧前端可能误入全篇链路，并混淆工作流平台与模型直连能力边界。独立协议增加了路由数量，但避免破坏现有限量审查，也不新增用户需要维护的任务配置。
