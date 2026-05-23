# AI-WPS 智能排版 Dify 工作流配置手册

适用版本：`v0.12.0-alpha`

适用任务：`word.smart_format`

## 1. 设计边界

智能排版不是让大模型直接改 Word 文档，也不是让 Dify 输出排版代码。本版本采用：

```text
Word 文档结构 -> adapter 提取段落 -> Dify 识别段落角色 -> adapter 按模板规则生成预览 -> 用户确认 -> WPS 写回格式
```

Dify 只做“段落角色识别”。真正的字体、字号、行距、缩进、标题级别、段前段后、页面边距等格式由本地 adapter 根据 `templates/company/technical-file-format-requirements.json` 执行。

这样做可以保护三个既有逻辑：

- 智能编写仍走 `word.smart_write`，输出正文内容。
- 格式校对仍走本地规则和可选 AI 审校，输出问题列表。
- 技术文档审查仍走 `word.technical_review`，输出审查意见。

## 2. 推荐 Dify 应用类型

推荐创建一个独立的 Dify Chat / Chatflow 应用，专门用于智能排版段落角色识别。

工作流结构：

```text
开始节点 -> 大模型节点 -> 回复节点
```

接口使用 Dify Chat API：

```text
POST /v1/chat-messages
```

AI-WPS adapter 侧统一配置：

```json
{
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerChatPath": "/chat-messages",
  "providerMode": "blocking",
  "taskApiKeyRefs": {
    "word.smart_format": "word_smart_format"
  }
}
```

任务窗口设置页中：

- `大模型 API URL` 填写到 `/v1` 这一层，例如 `https://aibot.chinasatnet.com.cn/v1`。
- `任务级 API Key` 中为“智能排版”粘贴该 Dify 应用的 API Key。
- 如果智能排版任务级 Key 未配置，adapter 会回退统一 Dify Chat API Key。
- 如果没有任何可用 Key，adapter 不调用 Dify，仅使用本地模板规则生成排版预览。

## 3. 开始节点配置

开始节点建议只保留 Dify 系统默认输入，优先使用系统变量：

```text
sys.query
```

不要把 `source_text`、`style`、`focus`、`length` 等智能编写字段复制到智能排版工作流。这些字段属于智能编写任务，智能排版只需要 adapter 组装后的完整结构识别提示词。

兼容说明：

- 当前 adapter 会把同一份提示词同时写到顶层 `query` 和 `inputs.query`。
- Dify 大模型节点优先引用 `sys.query`。
- 如果现场 Dify 版本必须使用自定义输入变量，也可以新增一个非必填的 `query` 输入变量，并在大模型节点中引用它；但不推荐把它作为唯一入口。

adapter 发送的请求体形态如下：

```json
{
  "inputs": {
    "query": "完整的智能排版段落角色识别提示词"
  },
  "query": "完整的智能排版段落角色识别提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

## 4. 大模型节点提示词

大模型节点的职责是根据 adapter 传入的段落列表，判断每个段落对应模板中的角色。建议提示词如下：

```text
你是 Word 技术文件排版结构识别助手。

你的任务只判断每个段落在标准模板中的角色，不要改写原文，不要补充正文，不要输出排版代码。

只能返回 JSON 对象，不要 Markdown，不要解释，不要代码块。

JSON 格式必须为：
{
  "paragraphs": [
    {
      "paragraphIndex": 1,
      "role": "heading1",
      "confidence": 0.95
    }
  ]
}

要求：
1. paragraphIndex 必须使用输入段落中的编号。
2. role 只能使用输入 roles 列表中的值。
3. 无法判断时使用 "body"。
4. 不允许返回原文全文。
5. 不允许返回 Markdown 代码块。

输入内容：
{{sys.query}}
```

如果 Dify 变量选择器无法选择 `sys.query`，可改为：

```text
输入内容：
{{query}}
```

但对应开始节点中需要存在非必填的自定义输入变量 `query`。

## 5. 角色枚举

Dify 返回的 `role` 必须限定在以下集合中：

| role | 含义 |
| --- | --- |
| `document_title` | 文档主标题 |
| `heading1` | 一级标题 |
| `heading2` | 二级标题 |
| `heading3` | 三级标题 |
| `heading4` | 四级标题 |
| `body` | 正文段落 |
| `caption` | 图题、表题 |
| `note` | 注释说明 |
| `numbered_note` | 带编号的注释说明 |
| `list1_numbered` | 一级编号列项 |
| `list1_plain` | 一级普通列项 |
| `list2_numbered` | 二级编号列项 |
| `list2_plain` | 二级普通列项 |
| `appendix_title` | 附录标题 |
| `appendix_heading1` | 附录一级标题 |
| `appendix_heading2` | 附录二级标题 |
| `appendix_heading3` | 附录三级标题 |
| `table_body` | 表格正文 |

adapter 会忽略不在集合内的 role，并回退到本地识别结果。

## 6. 回复节点配置

回复节点直接输出大模型节点的正文结果。不要把结果再包装成自然语言说明。

推荐返回：

```json
{
  "paragraphs": [
    {"paragraphIndex": 1, "role": "document_title", "confidence": 0.96},
    {"paragraphIndex": 2, "role": "heading1", "confidence": 0.94},
    {"paragraphIndex": 3, "role": "body", "confidence": 0.88}
  ]
}
```

不推荐返回：

````text
以下是识别结果：
```json
...
```
````

如果返回 Markdown 代码块，adapter 会尽量解析，但现场排查会更困难。

## 7. 任务窗口配置

在 AI-WPS 任务窗口中进入设置页：

1. 保存统一 `大模型 API URL`，例如 `https://aibot.chinasatnet.com.cn/v1`。
2. 在“任务级 API Key”区域找到“智能排版”。
3. 粘贴智能排版 Dify 应用的 API Key。
4. 点击保存密钥。
5. 返回“智能排版”，选择模板并生成排版预览。
6. 检查预览列表后，再点击应用预览。

如果多个功能使用不同 Dify 工作流，建议每个任务使用独立 API Key：

| AI-WPS 任务 | taskType | Dify 应用 |
| --- | --- | --- |
| 智能编写 | `word.smart_write` | 智能编写 Chatflow |
| 智能排版 | `word.smart_format` | 段落角色识别 Chatflow |
| 格式校对 | `word.proofread` | 文档质量审校 Chatflow |
| 技术文档审查 | `word.technical_review` | 技术审查 Chatflow |

当前版本所有任务仍使用同一个路径 `/chat-messages`，任务级 API Key 只决定调用哪个 Dify App，不再决定接口路径或 payload style。

## 8. 验证方法

目标机启动 adapter 后执行：

```bash
bash scripts/check_health.sh
```

应重点确认：

```text
adapter_mode=uvicorn
provider_configured=true
provider_status=reachable
```

在 WPS 中执行一次智能排版后，打开：

```text
http://127.0.0.1:18100/provider/debug-last
```

智能排版真实转发成功时，应看到类似信息：

```json
{
  "success": true,
  "data": {
    "taskType": "word.smart_format",
    "provider": "enterprise-dify-chat",
    "request": {
      "bodyKeys": ["conversation_id", "files", "inputs", "query", "response_mode", "user"],
      "inputsKeys": ["query"],
      "responseMode": "blocking"
    }
  }
}
```

如果看到：

```json
{
  "provider": "mock",
  "skipReason": "provider_not_configured"
}
```

说明 adapter 没有真实调用 Dify。优先检查：

1. `大模型 API URL` 是否保存到 `/v1`。
2. 智能排版任务级 API Key 是否保存。
3. 统一 API Key 是否可作为回退。
4. `bash scripts/status_adapter.sh` 是否显示当前服务是 `uvicorn` 且版本为 `0.12.0-alpha`。

## 9. 常见问题

### Dify 返回原文怎么办？

智能排版工作流不应该返回原文。请收紧大模型节点提示词中的约束：

```text
不允许返回原文全文，只能返回 JSON 对象。
```

如果仍返回原文，adapter 会解析失败并回退本地规则，预览仍可生成，但 AI 角色识别不会生效。

### 是否必须自定义开始节点 query？

不必须。推荐优先使用 Dify 系统默认的 `sys.query`。当前 adapter 同时兼容顶层 `query` 和 `inputs.query`，现场 Dify 如果只能选自定义变量，再新增非必填 `query` 即可。

### Dify 的输出变量需要叫 result 吗？

智能排版走 `/chat-messages` 时，adapter 优先解析 Chat 响应中的 `answer`。如果现场使用 Chatflow 回复节点，回复节点输出大模型正文即可，不需要依赖 `result` 字段。

### 为什么不让大模型直接生成 Word 格式？

因为 Word COM/WPS JS 写回需要确定的属性值。由大模型直接生成格式容易出现不可执行、不可验证和不稳定输出。本版本让模型只做结构判断，格式值全部来自标准模板，排版结果可预览、可回退、可测试。

### 智能排版会不会影响其他任务？

不会。智能排版使用独立 `taskType=word.smart_format` 和独立任务级 API Key；格式写回也只发生在用户点击“应用预览”之后。智能编写、格式校对、技术文档审查仍走各自任务入口。
