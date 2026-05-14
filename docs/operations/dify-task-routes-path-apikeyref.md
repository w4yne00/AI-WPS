# Dify 多任务路由部署手册

适用版本：`v0.10.0-alpha`

## 1. 设计目标

当前版本不再推荐把所有 Word 任务塞进一个 Dify 工作流后用判断节点分流。adapter 改为负责路由：同一个 `providerBaseUrl` 下，每个任务可以配置独立的接口路径、API Key 引用和请求体类型。

```text
单 providerBaseUrl + taskRoutes + 每任务 path/apiKeyRef/payloadStyle
```

## 2. 推荐 Dify 应用拆分

| WPS 任务 | taskRoute key | 推荐 Dify 类型 | path | payloadStyle | apiKeyRef |
| --- | --- | --- | --- | --- | --- |
| 智能改写 | `word.rewrite` | Chatflow/Chat App | `/chat-messages` | `chat` | `rewrite` |
| 智能续写 | `word.continue` | Chatflow/Chat App | `/chat-messages` | `chat` | `continue` |
| 格式校对 | `word.proofread` | Workflow | `/workflows/run` | `workflow` | `proofread` |
| 智能排版 | `word.format_preview` | Workflow | `/workflows/run` | `workflow` | `format_preview` |
| 技术文档审查 | `word.technical_review` | Workflow | `/workflows/run` | `workflow` | `technical_review` |

如果企业封装接口对所有应用仍使用同一路径，也可以把多个任务的 `path` 配成相同值，但 API Key 应按任务分开。

## 3. adapter 配置示例

```json
{
  "providerName": "星辰大模型接口",
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerMode": "blocking",
  "taskRoutes": {
    "word.rewrite": {
      "taskId": "word.rewrite",
      "path": "/chat-messages",
      "apiKeyRef": "rewrite",
      "payloadStyle": "chat",
      "responseMode": "blocking",
      "outputKey": "answer",
      "enabled": true
    },
    "word.proofread": {
      "taskId": "word.proofread",
      "path": "/workflows/run",
      "apiKeyRef": "proofread",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
      "enabled": true
    }
  }
}
```

## 4. API Key 存储

插件设置页可给每个任务单独保存密钥。adapter 保存到：

```text
adapter_service/run/provider_api_keys/<apiKeyRef>
```

默认密钥仍保留：

```text
adapter_service/run/provider_api_key
```

读取顺序：

1. 当前任务的 `provider_api_keys/<apiKeyRef>`。
2. 环境变量 `ENTERPRISE_AI_API_KEY`。
3. 默认本地密钥 `provider_api_key`。

## 5. Dify 字段要求

### Chat `/chat-messages`

adapter 发送：

```json
{
  "query": "完整任务提示词，包含改写/续写要求和待处理原文",
  "inputs": {
    "scene": "word",
    "task_id": "word.rewrite",
    "taskType": "word.rewrite",
    "trace_id": "word-rewrite-...",
    "source_text": "待处理原文",
    "text": "待处理原文",
    "mode": "rewrite",
    "rewrite_mode": "rewrite",
    "query": "完整任务提示词，包含改写/续写要求和待处理原文",
    "prompt": "完整任务提示词，包含改写/续写要求和待处理原文",
    "user_instruction": "用户补充要求",
    "rewrite_style": "formal",
    "focus_point": "risk",
    "length_mode": "same"
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

如果企业封装接口仍要求旧格式字段，可把对应任务的 `payloadStyle` 改成 `legacy-chat`。此时 adapter 会额外发送 `input_data` 和 `mode`，用于兼容旧封装；标准 Dify Chat App 建议保持 `payloadStyle=chat`。

### Workflow `/workflows/run`

adapter 发送：

```json
{
  "inputs": {
    "scene": "word",
    "task_id": "word.proofread",
    "taskType": "word.proofread",
    "trace_id": "word-proofread-...",
    "query": "审校提示词",
    "document_text": "文档正文",
    "document_structure": {}
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

Dify Workflow 需要在 User Input 中接收对应字段，并在 Output 节点输出 JSON 文本。建议输出字段命名为 `result`，adapter 也兼容 `answer`、`text`、`output`。

## 6. 验证步骤

1. 启动 adapter：`./start_uvicorn_adapter.sh 18100`。
2. 打开 WPS 设置页，刷新配置。
3. 在“任务接口”区域逐个保存每个任务的 API Key。
4. 验证智能改写、智能续写、格式校对、智能排版、技术文档审查。
5. 在 Dify 日志确认每个任务进入对应应用或工作流。
