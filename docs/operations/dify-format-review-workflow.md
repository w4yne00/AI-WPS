# AI-WPS 格式审查 Dify 工作流配置手册

适用版本：`v0.12.9-alpha`

适用任务：`word.format_review`

## 1. 功能定位

“格式审查”由原“智能排版”收敛而来。当前版本只做“根据标准文档模板进行格式检查”，不再让大模型生成全文排版结果，也不再自动写回 Word 格式。

本地 adapter 会根据 `技术文件格式及书写要求` 模板执行确定性检查，覆盖页面、标题、正文、图表题、注、列项、附录等规则。Dify 只作为可选辅助，用于识别段落角色，帮助判断某段更像标题、正文、图表题、注释或附录。

由于 Dify 和模型上下文窗口有限，建议用户框选局部内容进行格式审查；未选中文本时，前端仍会尝试读取全文，但长文档以本地规则为主。

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

开始节点可以只使用系统自带 `sys.query`。如果现场已经自定义了 `query` 输入变量，也可以继续引用，因为 adapter 同步写入 `inputs.query`。

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

你的任务不是改写正文，也不是输出排版后的全文。请只根据用户通过 sys.query 发送的段落列表，判断每个段落最可能的文档角色。

可选角色只能使用：
- heading：标题或小标题；
- body：正文段落；
- list：编号列表或条目列表；
- caption：图题、表题；
- note：注释、说明、备注；
- appendix：附录标题或附录正文；
- table：表格正文或表格内容说明；
- unknown：无法判断。

输出必须是 Markdown 文本，其中只能包含一个 json 代码块，代码块内必须是合法 JSON：

```json
{
  "paragraphs": [
    {
      "index": 1,
      "role": "heading",
      "confidence": 0.86,
      "reason": "该段为章节标题"
    }
  ]
}
```

字段要求：
- index 必须使用用户输入中的段落序号；
- role 必须从上述角色中选择；
- confidence 为 0 到 1 之间的小数；
- reason 用一句中文说明判断依据；
- 不要返回原文全文，不要输出格式修改建议，不要在 json 代码块外输出解释。
```

如果当前 Dify 版本不能强制 JSON 输出，也可以保持普通 Markdown 输出，但必须让大模型把 JSON 放入 `json` 代码块。adapter 会从 Markdown 代码块中提取 JSON；提取失败时会自动回退本地规则。

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

如果结果预览显示“识别来源：local”，通常表示未配置格式审查任务级 Key、Dify 请求失败或 Dify 返回内容无法解析为段落角色 JSON。此时本地模板规则仍会继续输出格式检查意见。

如果 Dify 后台没有调用记录，优先检查：

1. 设置页是否保存了格式审查任务级 API Key；
2. `/provider/debug-last.skipReason` 是否为 `provider_not_configured`；
3. 当前 WPS 是否成功读取到选中文本或全文段落。
