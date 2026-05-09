# Dify 单工作流 task_id 路由部署手册

更新时间：2026-05-09

适用版本：`v0.9.0-alpha`

## 1. 目标

本手册用于在内网 Dify 平台上部署一个统一工作流，由 adapter 传入 `task_id`，Dify 判断节点根据任务类型分流到不同处理路径。

一期采用：

```text
单 provider + 单 API Key + 单 Dify 工作流 + task_id 判断节点
```

不依赖 Dify 原生 `appName` 路由，也不要求多个 Dify API Key。

## 2. Adapter 调用约定

adapter 统一调用同一个 Dify 工作流 API 地址，例如：

```text
https://aibot.chinasatnet.com.cn/v1/workflows/run
```

请求鉴权：

```text
Authorization: Bearer {API_KEY}
```

工作流入参建议配置如下：

| 变量名 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务 ID，用于判断节点分流 |
| `taskType` | string | adapter 原始任务类型，便于日志和兼容 |
| `scene` | string | 当前固定为 `word` |
| `trace_id` | string | adapter 追踪号 |
| `selection_mode` | string | `document` 或 `selection` |
| `query` | string | adapter 为当前任务生成的提示词 |
| `document_text` | string | 文档全文或选中文本 |
| `document_structure` | object | WPS 插件抽取的段落、标题和基础样式结构 |
| `template_id` | string | 文档模板 ID |
| `template_type` | string | 模板名称或类型 |
| `template_version` | string | 模板版本 |
| `local_rule_findings` | array | adapter 本地格式规则发现的问题 |
| `rewrite_mode` | string | `rewrite` 或 `continue` |
| `review_mode` | string | 技术审查模式 |
| `document_type` | string | 技术文档类型 |
| `user_instruction` | string | 用户补充要求 |

## 3. 任务 ID 约定

| task_id | 用途 | 输出要求 |
| --- | --- | --- |
| `word.rewrite` | 智能改写 | 返回最终改写文本 |
| `word.continue` | 智能续写 | 返回最终续写文本 |
| `word.proofread` | 格式校对和文档质量审校 | 返回 `{"issues": [...]}` |
| `word.format_preview` | 智能排版预览 | 当前可先返回排版建议文本；下一版本可结构化 |
| `word.technical_review` | 技术文档审查 | 返回 `{"summary":"...","issues":[...]}` |

## 4. 工作流节点建议

建议工作流结构：

```text
开始节点
  -> 参数规范化节点
  -> 判断节点 task_id
      -> word.rewrite 路径
      -> word.continue 路径
      -> word.proofread 路径
      -> word.format_preview 路径
      -> word.technical_review 路径
      -> unknown_task 路径
  -> 结束节点
```

判断条件：

```text
task_id == "word.rewrite"
task_id == "word.continue"
task_id == "word.proofread"
task_id == "word.format_preview"
task_id == "word.technical_review"
```

## 5. 各路径输出 Schema

### 智能改写 / 智能续写

直接输出正文文本。adapter 会从 Dify 响应的 `answer`、`data.answer`、`text` 或 `rewrittenText` 字段读取最终文本。

### 格式校对

必须输出 JSON：

```json
{
  "issues": [
    {
      "category": "typo",
      "severity": "warning",
      "paragraphIndex": 2,
      "original": "文挡",
      "suggestion": "文档",
      "message": "疑似错别字",
      "reason": "应使用文档。",
      "confidence": 0.93
    }
  ]
}
```

`category` 可用值：

```text
typo, grammar, expression, logic, heading_consistency
```

`severity` 可用值：

```text
info, warning, error
```

### 技术审查

必须输出 JSON：

```json
{
  "summary": "发现 2 项技术文档问题。",
  "issues": [
    {
      "category": "requirement",
      "severity": "medium",
      "location": "第 2 节",
      "originalText": "支持多种接口",
      "problem": "要求边界不清，无法验收。",
      "suggestion": "补充接口类型、数量、调用条件和验收标准。",
      "suggestedRewrite": "系统支持 REST API 和文件导入两类接口，并满足..."
    }
  ]
}
```

`category` 可用值：

```text
accuracy, terminology, design, requirement
```

`severity` 可用值：

```text
high, medium, low
```

## 6. Unknown Task 路径

如果 `task_id` 不匹配任何已知任务，建议返回：

```json
{
  "summary": "不支持的任务类型。",
  "issues": []
}
```

同时在文本中保留 `task_id`，方便排查 adapter 和工作流配置不一致的问题。

## 7. Adapter 配置示例

`config/adapter.json` 示例：

```json
{
  "servicePort": 18100,
  "providerName": "星辰大模型接口",
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerChatPath": "/workflows/run",
  "providerApiKeyEnv": "ENTERPRISE_AI_API_KEY",
  "providerMode": "blocking",
  "timeoutSeconds": 30,
  "taskRoutes": {
    "word.rewrite": {"taskId": "word.rewrite", "enabled": true},
    "word.continue": {"taskId": "word.continue", "enabled": true},
    "word.proofread": {"taskId": "word.proofread", "enabled": true},
    "word.format_preview": {"taskId": "word.format_preview", "enabled": true},
    "word.technical_review": {"taskId": "word.technical_review", "enabled": true}
  }
}
```

## 8. 联调检查

1. 启动 adapter。
2. 执行 `scripts/check_health.sh 18100`，确认 `providerConfigured=true`。
3. 打开 WPS 插件设置页，点击刷新配置。
4. 分别验证智能改写、智能续写、格式校对、智能排版、技术审查。
5. 在 Dify 日志中确认每次请求的 `task_id` 进入了正确判断路径。
