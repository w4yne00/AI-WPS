# Dify 多任务路由部署手册

适用版本：`v0.11.0-alpha`

## 1. 设计目标

adapter 使用“单 providerBaseUrl + taskRoutes + 每任务 path/apiKeyRef/payloadStyle”模式。每个 WPS 任务可以命中独立的 Dify Workflow，并使用独立 API Key。智能编写已从旧的智能改写/智能续写 Chat 调用切换为独立 Workflow，以避免 Dify 工作流未读取原文导致原样返回。

## 2. 推荐 Dify 应用拆分

| WPS 任务 | taskRoute key | 推荐 Dify 类型 | path | payloadStyle | apiKeyRef | Output 字段 |
| --- | --- | --- | --- | --- | --- | --- |
| 智能编写 | `word.smart_write` | Workflow | `/workflows/run` | `workflow` | `smart_write` | `result` |
| 格式校对 | `word.proofread` | Workflow | `/workflows/run` | `workflow` | `proofread` | `result` |
| 智能排版 | `word.format_preview` | Workflow | `/workflows/run` | `workflow` | `format_preview` | `result` |
| 技术文档审查 | `word.technical_review` | Workflow | `/workflows/run` | `workflow` | `technical_review` | `result` |

## 3. adapter 配置示例

```json
{
  "providerName": "星辰大模型接口",
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerMode": "blocking",
  "taskRoutes": {
    "word.smart_write": {
      "taskId": "word.smart_write",
      "path": "/workflows/run",
      "apiKeyRef": "smart_write",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
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

推荐配置：

```text
smart_write
proofread
format_preview
technical_review
```

## 5. 智能编写 Workflow 输入要求

Dify Workflow 的 Start 节点必须创建以下输入变量：

| 变量 | 类型 | 说明 |
| --- | --- | --- |
| `source_text` | String | WPS 当前选中文本，是大模型必须处理的原文 |
| `write_action` | String | `rewrite`、`continue`、`summarize`、`custom` |
| `style` | String | 表达风格，例如 `formal`、`structured` |
| `focus` | String | 侧重点，例如 `risk`、`conclusion` |
| `length` | String | 篇幅要求，例如 `same`、`concise`、`expanded` |
| `user_prompt` | String | 用户自定义补充要求 |
| `selection_mode` | String | `selection` 或 `document` |
| `trace_id` | String | adapter 追踪号 |

adapter 发送示例：

```json
{
  "inputs": {
    "source_text": "待处理原文",
    "write_action": "rewrite",
    "style": "formal",
    "focus": "risk",
    "length": "same",
    "user_prompt": "请更适合正式汇报材料",
    "selection_mode": "selection",
    "trace_id": "word-smart-write-20260517-0001"
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

LLM 节点建议系统提示词：

```text
你是企业办公文档智能编写助手。必须基于 source_text 生成新内容，不允许原样返回原文。根据 write_action 判断任务类型：rewrite 表示改写润色，continue 表示续写扩展，summarize 表示提炼总结，custom 表示按 user_prompt 自定义处理。输出只保留最终正文，不要解释处理过程。
```

Output 节点：

```text
result = LLM 节点输出正文
```

## 6. 格式校对、智能排版、技术审查

这三个任务仍走 Workflow `/workflows/run`。建议 Output 节点统一输出 `result`。如果工作流输出字段不是 `result`，需要同步修改 `config/adapter.json` 中对应 `taskRoutes.*.outputKey`。

## 7. 验证步骤

1. 启动 adapter：`./start_uvicorn_adapter.sh 18100`。
2. 执行健康检查：`./check_health.sh 18100`。
3. 打开 WPS 设置页，填写全局 API URL，保存。
4. 在“任务接口”区域分别保存 `smart_write`、`proofread`、`format_preview`、`technical_review` 的 API Key。
5. 刷新配置，确认对应任务显示“密钥已配置”。
6. 在 WPS 中框选一段文字，点击“智能编写”，选择“改写润色”，执行生成。
7. 在 Dify 日志确认 Start 节点收到 `source_text`，Output 节点返回 `result`。
8. 验证格式校对、智能排版、技术文档审查分别命中对应 Workflow。
