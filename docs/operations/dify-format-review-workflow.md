# AI-WPS 格式审查 Dify 工作流配置手册

适用版本：`v0.13.7-alpha`

适用任务：`word.format_review`

## 1. 功能定位

“格式审查”由原“智能排版”收敛而来。当前版本只做“根据标准文档模板进行格式检查”，不再让大模型生成全文排版结果，也不再自动写回 Word 格式。

本地 adapter 会根据 `技术文件格式及书写要求` 模板执行确定性检查，覆盖页面、标题、正文、图表题、注、列项、附录等规则。Dify 只作为可选辅助，用于识别段落角色，帮助判断某段更像标题、正文、图表题、注释或附录。

由于 Dify 和模型上下文窗口有限，建议用户框选局部内容进行格式审查；未选中文本时，前端仍会尝试读取全文，但长文档以本地规则为主。当前 adapter 只把最多前 40 个段落用于可选 AI 角色识别，每批最多 20 段，单次 Dify 请求最多等待 60 秒；超时、非 JSON 响应或解析失败都不会中断格式审查，会自动回退本地模板规则。

`v0.12.16-alpha` 起，格式审查结果预览按“审查概览 / 优先处理清单 / 详细问题 / 诊断信息”展示。普通用户优先看“优先处理清单”和“详细问题”；技术联调时再看末尾诊断信息。预览层会尽量中文化显示段落角色、规则项、模板名、识别来源和 AI 兜底原因。

常见格式值显示规则：

- 字体标准显示为“宋体”。
- 字号标准显示为“小四（12pt）”；当前值会尽量显示为“四号（14pt）”“小四（12pt）”等中文字号。
- 对齐方式显示为“左对齐、居中、右对齐、两端对齐”等中文。
- 行距显示为“单倍行距（1倍）”“1.5 倍行距”等中文。
- 首行缩进显示为“无首行缩进”或“首行缩进 2 字符（约 480 twips）”。
- 样式名、页面行、模拟服务和 AI 兜底诊断会尽量显示为中文提示，避免直接暴露机器字段。

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

格式审查的 AI 段落角色识别是可选增强。Dify 超时、无 JSON 或未配置时，adapter 会回退本地模板规则并在诊断里显示 AI 兜底原因。

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
