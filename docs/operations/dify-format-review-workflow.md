# AI-WPS 格式审查 Dify 工作流配置手册

适用版本：`v0.25.1-alpha`（旧同步入口仅保留退役响应）

适用任务：`word.format_review`

## 1. 功能定位

### 1.1 两遍格式快照协议

确定性格式审查的新任务窗格入口使用独立的格式快照会话，而不是一次性提交全文：

1. WPS 先按稳定文档顺序抽取正文、标题、列表、表格和题注等格式语义单元，并按批次上传；批次必须使用秘密上传令牌、连续序号、批次编号和内容/结构/格式哈希。
2. 选区会扩展到完整段落、表格或题注语义单元；为判定读取的相邻标题等上下文标记为 `context`，只参与判定，不计入问题范围。
3. 上传完成后，WPS 重新读取同一范围，只比较文档身份、编辑序号、对象数量、覆盖统计、结构哈希和格式指纹。任一不一致都会清理快照并要求重试。
4. 只有二遍校验通过后才提交后台任务。快照目录为本地隔离暂存，目录权限为 `0700`，文件权限为 `0600`；任务终态立即删除完整格式事实。

格式快照按以下容量档位执行，前端与 Adapter 使用相同边界：审查字符数不超过 `60,000` 为 `standard`，`60,001–120,000` 为 `large`，超过 `120,000` 直接拒绝，不截断、不静默降级。两档均不要求二次确认。每次上传和提交还会校验内容块、表格单元格、格式区段、不支持对象和累计快照字节数；当前安全上限分别为 `10,000`、`50,000`、`50,000`、`5,000` 和 `16 MiB`，超限返回实际维度与上限并清理暂存。

段落或表格单元格中的混合字体、字号、粗斜体、上下标、颜色等字符属性按递归二分读取为相对范围区段，相邻同属性区段会合并。单对象格式区段超过 `2,048` 时不保留部分区段，而是标记 `formatDataStatus=insufficient`，报告覆盖状态为“数据不足”。快照 coverage 同时披露 `formatSegmentCount`、`tableCellCount`、`unsupportedObjectCount` 及类型分布；页眉页脚分别记录 `read` 或 `unavailable`、字符数和失败次数，文本框、SmartArt、公式内部、批注、修订和浮动形状只盘点不审查。

协议端点为：

```text
POST /word/format-review/snapshots
PUT  /word/format-review/snapshots/{snapshotId}/batches/{sequence}
POST /word/format-review/snapshots/{snapshotId}/commit
POST /word/format-review/jobs
GET  /word/format-review/jobs/{jobId}
GET  /word/format-review/jobs/{jobId}/issues
PATCH /word/format-review/jobs/{jobId}/issues/{issueId}
GET  /word/format-review/jobs/{jobId}/report
DELETE /word/format-review/jobs/{jobId}
DELETE /word/format-review/jobs/{jobId}/report
```

旧的 `POST /word/format-review/snapshots` 直接提交 `WordDocumentRequest` 的 v1 行为已退役，返回 `410 DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_VERSION_UNSUPPORTED`；v1 快照缓存和报告也不会进入 v2 规则或渲染链，必须重新读取文档并提交 v2 审查。

“格式审查”由原“智能排版”收敛而来。当前版本只做“根据标准文档模板进行格式检查”，不再让大模型生成全文排版结果，也不再自动写回 Word 格式。

本地 adapter 会根据 `技术文件格式及书写要求` 模板执行确定性检查，覆盖页面、标题、正文、图表题、注、列项、附录等规则。Dify 只作为可选辅助，用于识别段落角色，帮助判断某段更像标题、正文、图表题、注释或附录。

`v0.25.0-alpha` 起，Dify 的 `suggest_table_caption` 只接收确定性算法同时确认“数据表、缺少表题、关联无歧义”的候选。候选证据视图固定包含多级表头、合并关系、行列数、单位、来源、表下注、所在标题和邻近上下文；完整表格超过单次输入预算时，必须显式标记 `evidenceStatus=restricted`，并只保留首三行和末两行样例。模型只能返回不超过 80 个 Unicode 字符的表题正文，不得包含表前缀、表号、Markdown、换行或解释；证据不足或引入证据外的机构、时间、地域、数值、统计口径时，adapter 拒绝该建议并返回“无法可靠建议”。所有表题建议均为只读结果，不会自动写回 Word。

由于 Dify 和模型上下文窗口有限，建议用户框选局部内容进行格式审查；未选中文本时，前端仍会尝试读取全文，但长文档以本地规则为主。当前 adapter 只把最多前 40 个段落用于可选 AI 角色识别，每批最多 20 段，单次 Dify 请求最多等待 60 秒；超时、不可达或协议校验失败都不会中断确定性审查，任务会记录 v2 语义降级原因并继续执行本地模板规则。

`v0.25.1-alpha` 起，格式审查结果预览只消费 v2 结构化报告和格式事实诊断，按执行状态、合规状态、覆盖状态、问题清单和详细说明展示。无法由已验证事实确认的字体、字号、对齐、位置等值显示为“无法识别”或“无法验证位置”，不再猜测单位、翻译旧当前值或使用旧同步报告兜底。

v2 格式事实显示规则：

- 字体标准显示为“宋体”。
- 已验证的字号显示为“小四（12pt）”等中文字号；未映射或状态不足的值显示为“无法识别”。
- 对齐方式显示为“左对齐、居中、右对齐、两端对齐”等中文。
- 行距显示为“单倍行距（1倍）”“1.5 倍行距”等中文。
- 首行缩进显示为“无首行缩进”或“首行缩进 2 字符”。
- 样式名、页面事实和数据状态按 v2 格式事实协议显示；已验证的段落问题显示章节路径、段落序号、原文摘要和稳定原文锚点，不能确认的字段不擅自补值。

`v0.25.1-alpha` 起，格式问题位置按问题范围表达：段落问题的 `sourceAnchor` 保留 `blockId`、`paragraphIndex`、原文 `textSha256`、文本摘要、字符 `range` 和相邻块信息；章节路径由已读取的标题层级按段落顺序确定。WPS 能验证布局时，`range.pageNumber` 作为页码提示写入报告；页码读取失败、文档在两遍读取间发生编辑或校验不一致时安全省略页码，不影响稳定文本锚点。

节级问题使用 `locationScope=section`、章节/节名称和可选 `pageRange` 展示“第 N 节”或章节路径；文档级问题使用 `locationScope=document` 展示“全文”。页码只是布局提示，不参与 `issueId`，也不能替代段落字符范围、原文摘要和校验哈希；重复正文通过不同 `anchorId` 与相邻块哈希区分。验证到章节或段落时，前端不再用“无法验证位置”覆盖这些已有位置。

`v0.13.4-alpha` 起，框选文本执行格式审查时，任务窗格会优先读取 WPS 选区 `Selection/Range` 的段落格式，再退回纯文本兜底；如果只读取到纯文本，不再伪造 `0pt` 字号或左对齐。adapter 侧也会将 WPS 对齐枚举值（例如 `3`）规范化为两端对齐后再判断。

## 2. Dify 应用类型

建议创建独立 Chat / Chatflow 应用，使用标准 `/chat-messages` 接口。

adapter 请求体只依赖 Dify 官方字段：

```json
{
  "inputs": {
    "query": "adapter 组装后的段落角色识别提示词"
  },
  "query": "adapter 组装后的段落角色识别提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

旧版开始节点可继续引用自定义 `query` 输入变量，adapter 默认发送 `inputs.query`。新版“用户输入”节点应引用 `userinput.query`；HTTP 400 时 adapter 会自动切换为顶层 `query` 和 `files` 输入格式。

## 3. 任务级 API Key

在 WPS 任务窗口设置页：

1. 配置统一 API URL，例如 `https://aibot.chinasatnet.com.cn/v1`。
2. 在“任务接口”中找到“格式审查”。
3. 保存该 Dify 格式审查应用的 API Key。

配置文件示例：

```json
{
  "taskApiKeyRefs": {
    "word.smart_write": "word_smart_write",
    "word.document_review": "word_document_review",
    "word.format_review": "word_format_review"
  }
}
```

保存后密钥位于 `run/provider_api_keys/word_format_review`。如果该任务级密钥不存在，adapter 会回退统一 Dify API Key；如仍未配置，格式审查会只使用本地模板规则。

## 4. LLM 系统提示词

可直接放入 Dify 大模型节点 SYSTEM：

```text
你是企业 Word 文档格式审查的段落角色识别助手。

你的任务不是改写正文，也不是输出排版后的全文。请只处理输入 JSON 中 `candidates` 列出的模糊候选，判断每个候选最可能的文档角色。

输入包含 `operation=classify_role`、当前 `snapshotBinding` 和候选对象。每个候选都有 `blockId` 与 `allowedTargets`；只能从该候选的 `allowedTargets` 选择角色及属性，不得处理确定性规则已确认的对象。

输出必须是一个符合 `format_semantics.v1` 的 JSON 对象，不要 Markdown 代码围栏、推理过程、思考标签或格式合规结论：

```json
{
  "schemaVersion": "format_semantics.v1",
  "operation": "classify_role",
  "snapshotBinding": {
    "contentSha256": "与输入完全一致",
    "structureSha256": "与输入完全一致",
    "formatSha256": "与输入完全一致"
  },
  "items": [
    {
      "blockId": "输入候选中的 blockId",
      "role": "heading",
      "level": 1,
      "confidence": 0.95
    }
  ]
}
```

字段要求：
- `schemaVersion` 必须为 `format_semantics.v1`，`operation` 必须与输入一致；
- `snapshotBinding` 必须逐字段复现当前输入，不能省略或改写哈希；
- `items` 必须覆盖本批全部候选，`blockId` 不得重复或越界；
- `role`、`level`、`ordered`、`numbered` 只能使用对应候选的 `allowedTargets`，`confidence` 为 0 到 1 之间的小数；
- 不要返回 `paragraphs`、`candidates`、`reason`、Markdown 或其它未声明字段。

格式审查的 AI 段落角色识别是可选增强。Dify 超时、不可达、未配置或 v1 契约校验失败时，adapter 会继续本地模板规则，并在 v2 诊断中记录语义降级原因；不会提取旧 JSON，也不会调用旧同步审查链。

## 5. 回复节点

回复节点绑定 LLM 节点输出正文即可。不要绑定开始节点原始 `query`，否则 WPS 侧会看到原文或提示词返回。

推荐链路：

```text
开始节点(sys.query) -> 大模型节点 -> 回复节点(大模型 text)
```

## 6. 联调检查

执行一次“格式审查”后访问：

```text
http://127.0.0.1:18100/provider/debug-last
```

正常转发时应看到：

```json
{
  "taskType": "word.format_review",
  "provider": "enterprise-dify-chat",
  "request": {
    "bodyKeys": ["conversation_id", "files", "inputs", "query", "response_mode", "user"],
    "inputsKeys": ["query"]
  }
}
```

如果结果预览显示“识别来源：本地规则”，通常表示未配置格式审查任务级 Key、模型后台请求失败或模型后台返回内容无法解析为段落角色 JSON。此时本地模板规则仍会继续输出格式检查意见。

如果 Dify 后台没有调用记录，优先检查：

1. 设置页是否保存了格式审查任务级 API Key；
2. `/provider/debug-last.skipReason` 是否为 `provider_not_configured`；
3. 当前 WPS 是否成功读取到选中文本或全文段落。

## 7. 现场诊断

设置页“最近一次任务诊断”对应 adapter 的 `/provider/debug-last`、`/provider/status`、`/provider/route-diagnostics`、`/provider/task-api-keys`。诊断信息只显示脱敏摘要，不显示完整原文和 API Key。

如果前台结果异常，优先确认：

1. `taskType` 是否为 `word.format_review`。
2. `authSource` 或 `taskAuthSource` 是否为任务级密钥文件。
3. `url` 是否为统一 API URL 拼接 `/chat-messages`。
4. `request.bodyKeys` 是否包含 `inputs`、`query`、`response_mode`、`user`。
5. `response.answerLength` 是否大于 0，或是否记录了 `skipReason` / `error`。
