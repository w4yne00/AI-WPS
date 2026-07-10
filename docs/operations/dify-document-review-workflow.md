# AI-WPS 文档审查 Dify 工作流配置手册

适用版本：`v0.13.7-alpha`

适用任务：`word.document_review`

## 1. 功能定位

“文档审查”用于替代原“格式校对”和“技术文档审查”的语言与专业性审查部分。它不检查 Word 模板格式，也不写回正文，专注于：

- 错别字、漏字、多字和明显用词错误；
- 语言表达是否准确、正式、适合企业技术文档；
- 前后逻辑、因果关系、范围边界和结论是否一致；
- 句子是否通顺、重复、冗长或歧义明显；
- 按文档类型判断专业性，当前包括技术方案、合同验收文档、测试大纲及细则。

用户可以框选局部段落进行审查；点击空白处或未选择文本时，前端会按限量全文抽取发送，避免任务窗格同步扫描全文卡住。受 Dify 输出长度和模型上下文限制影响，长文档建议分段审查。

## 2. Dify 应用类型

建议创建独立 Chat / Chatflow 应用，使用标准 `/chat-messages` 接口。

adapter 请求体只依赖 Dify 官方字段：

```json
{
  "inputs": {
    "query": "adapter 组装后的完整文档审查提示词"
  },
  "query": "adapter 组装后的完整文档审查提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

旧版 Dify 开始节点可继续引用自定义 `query` 输入变量，adapter 默认发送 `inputs.query`。新版“用户输入”节点应直接引用 `userinput.query`；如果新版接口因不接受 `inputs.query` 返回 HTTP 400，adapter 会自动改用顶层 `query` 和 `files` 重试。

说明：`v0.13.0-alpha` 之后任务窗格新增的问题处理状态、复制建议和审查记录都由 WPS 前端本地生成；Dify 工作流不要处理“已处理/已忽略/审查记录”等闭环状态，也不要执行任何正文写回动作。

## 3. 任务级 API Key

在 WPS 任务窗口设置页：

1. 配置统一 API URL，例如 `https://aibot.chinasatnet.com.cn/v1`。
2. 在“任务接口”中找到“文档审查”。
3. 保存该 Dify 文档审查应用的 API Key。

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

保存后密钥位于 `run/provider_api_keys/word_document_review`。如果该任务级密钥不存在，adapter 会回退统一 Dify API Key。

## 4. LLM 系统提示词

可直接放入 Dify 大模型节点 SYSTEM：

```text
你是企业 Word 文档审查助手，服务对象是国企技术方案、合同验收文档、测试大纲及细则等正式材料。

你的任务是审查用户通过 sys.query 发送的文档片段或全文。请只基于用户提供的内容判断，不要编造事实，不要扩展正文，不要替用户续写整篇文档。

重点检查：
1. 错别字、漏字、多字、明显用词错误；
2. 语言表达是否准确、正式、通顺，是否存在口语化、重复、歧义或病句；
3. 逻辑关系是否清晰，范围、前提、结论、责任、时间和验收条件是否自洽；
4. 文档类型专业性是否匹配：技术方案关注架构边界、实施路径、风险措施；合同验收文档关注交付物、验收依据、证据闭环；测试大纲及细则关注测试范围、方法、步骤、判据和记录；
5. 只提出有依据的问题，不要把正常表达强行判为错误。

输出必须是 Markdown 文本，其中只能包含一个 json 代码块，代码块内必须是合法 JSON：

```json
{
  "summary": "一句话概括审查结果",
  "issues": [
    {
      "category": "typo",
      "severity": "medium",
      "location": "第 1 段",
      "originalText": "原文片段",
      "problem": "问题说明",
      "suggestion": "修改建议",
      "suggestedRewrite": "可选的建议改写"
    }
  ]
}
```

字段要求：
- category 只能使用 typo、expression、logic、fluency、professional；
- severity 只能使用 high、medium、low；
- location 尽量使用“第 N 段”或原文中的小标题；
- issues 没有问题时返回空数组；
- 不要输出“已处理”“已忽略”“审查处理记录”等前端闭环状态；
- 不要在 json 代码块外输出解释、寒暄或原文复述。
```

如果当前 Dify 版本不能强制 JSON 输出，也可以保持普通 Markdown 输出，但必须让大模型把 JSON 放入 `json` 代码块。adapter 会从 Markdown 代码块中提取 JSON。文档审查可以输出 Markdown，但必须包含一个合法 `json` 代码块，adapter 从该代码块中提取 `summary` 和 `issues`。

## 5. 回复节点

回复节点绑定 LLM 节点输出正文即可。不要把开始节点原始 `query` 直接绑定到回复节点，否则 WPS 任务窗口会看到原文返回。

推荐链路：

```text
开始节点(sys.query) -> 大模型节点 -> 回复节点(大模型 text)
```

## 6. 联调检查

执行一次“文档审查”后访问：

```text
http://127.0.0.1:18100/provider/debug-last
```

正常转发时应看到：

```json
{
  "taskType": "word.document_review",
  "provider": "enterprise-dify-chat",
  "request": {
    "bodyKeys": ["conversation_id", "files", "inputs", "query", "response_mode", "user"],
    "inputsKeys": ["query"]
  }
}
```

如果 `provider=mock` 或 `skipReason=provider_not_configured`，说明统一 URL 或文档审查任务级 API Key 未形成有效配置。

如果 Dify 后台有调用记录但 WPS 结果为空，优先检查回复节点是否绑定 LLM 输出正文，以及输出中是否包含合法 JSON 代码块。`v0.13.7-alpha` 起，文档审查 provider 等待预算为 1800 秒；前台轮询后台任务状态时最多容忍 240 次短暂查询失败、总等待 60 分钟，并在轮询阶段把 adapter 短暂不可达提示为“状态查询暂时未连上本地 adapter”，继续等待后台任务。即使 Dify 返回非标准 JSON、普通 Markdown，或文档审查 provider 超时/不可达，adapter 也会返回可读兜底信息，便于现场区分是 Dify 输出格式问题、Dify 执行超时、前端状态查询抖动，还是前端渲染问题。

文档审查前端采用限量抽取和异步提交：

- 最多读取 80 段；
- 单段最多 800 字；
- 提交正文最多 12000 字；
- 框选文本时优先从选中文本直接拆段，不同步扫描全文；
- 请求等待超过 8 秒和 30 秒时，任务窗格会继续刷新等待 Dify 的状态提示。

## 7. 现场诊断

设置页“最近一次任务诊断”对应 adapter 的 `/provider/debug-last`、`/provider/status`、`/provider/route-diagnostics`、`/provider/task-api-keys`。诊断信息只显示脱敏摘要，不显示完整原文和 API Key。

如果前台结果异常，优先确认：

1. `taskType` 是否为 `word.document_review`。
2. `authSource` 或 `taskAuthSource` 是否为任务级密钥文件。
3. `url` 是否为统一 API URL 拼接 `/chat-messages`。
4. `request.bodyKeys` 是否包含 `inputs`、`query`、`response_mode`、`user`。
5. `response.answerLength` 是否大于 0。
