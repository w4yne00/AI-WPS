# AI-WPS 文档审查 Dify 工作流配置手册

适用版本：`v0.12.9-alpha`

适用任务：`word.document_review`

## 1. 功能定位

“文档审查”用于替代原“格式校对”和“技术文档审查”的语言与专业性审查部分。它不检查 Word 模板格式，也不写回正文，专注于：

- 错别字、漏字、多字和明显用词错误；
- 语言表达是否准确、正式、适合企业技术文档；
- 前后逻辑、因果关系、范围边界和结论是否一致；
- 句子是否通顺、重复、冗长或歧义明显；
- 按文档类型判断专业性，当前包括技术方案、合同验收文档、测试大纲及细则。

用户可以框选局部段落进行审查；点击空白处或未选择文本时，前端会按全文发送。受 Dify 输出长度和模型上下文限制影响，长文档建议分段审查。

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

Dify 开始节点可以只使用系统自带 `sys.query`。如果现场已经自定义了 `query` 输入变量，也可以继续在 LLM 节点中引用 `query`，因为 adapter 会同步写入 `inputs.query`。

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
- 不要在 json 代码块外输出解释、寒暄或原文复述。
```

如果当前 Dify 版本不能强制 JSON 输出，也可以保持普通 Markdown 输出，但必须让大模型把 JSON 放入 `json` 代码块。adapter 会从 Markdown 代码块中提取 JSON。

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

如果 Dify 后台有调用记录但 WPS 结果为空，优先检查回复节点是否绑定 LLM 输出正文，以及输出中是否包含合法 JSON 代码块。
