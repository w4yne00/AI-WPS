# 一期 Provider Task Routes 闭环设计

更新时间：2026-05-09

## 1. 设计目标

在不增加目标机配置复杂度的前提下，让 WPS AI 助理一期的 Word 能力可以共用一个企业 Dify 工作流入口，并通过 adapter 传递任务标识，由 Dify 工作流内部判断节点分流到不同任务路径。

一期目标不是做多模型供应商，也不是做多密钥路由，而是先闭环以下能力：

- 智能改写
- 智能续写
- 格式校对
- 智能排版预览
- 技术审查

## 2. 最终路线

一期采用：

```text
单 provider + 单 API Key + 单 Dify 工作流 + task_id 判断节点
```

adapter 仍保留 `taskRoutes` 概念，但一期的 `taskRoutes` 只负责维护任务 ID、启用状态和默认任务元数据，不负责选择不同 API Key。

这样可以做到：

- 设置页只需要配置一个模型提供商名称、一个 API URL、一个 API Key。
- WPS 插件继续只调用本地 adapter 的固定接口。
- adapter 统一调用一个企业 Dify 工作流。
- Dify 工作流根据 `task_id` 选择不同处理路径。
- 后续如果要拆多工作流，可以在不推翻接口的前提下扩展 `taskRoutes`。

## 3. 不采用 appName 路由的原因

经核对 Dify 官方开发文档，Dify 原生 Service API 没有标准的 `appName` 路由参数。Dify 通常是每个 App 或 Workflow 独立发布 API，并通过该 App 的 API Key 访问。

因此，`appName -> Dify App` 的路由只有在企业封装层自行支持时才成立。当前内网 Dify 页面没有该配置项，所以一期不依赖 `appName` 路由。

## 4. 一期配置结构

建议 `config/adapter.json` 保持单 provider 配置，并增加轻量 `taskRoutes`：

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
    "word.rewrite": {
      "taskId": "word.rewrite",
      "enabled": true
    },
    "word.continue": {
      "taskId": "word.continue",
      "enabled": true
    },
    "word.proofread": {
      "taskId": "word.proofread",
      "enabled": true
    },
    "word.format_preview": {
      "taskId": "word.format_preview",
      "enabled": true
    },
    "word.technical_review": {
      "taskId": "word.technical_review",
      "enabled": true
    }
  }
}
```

兼容要求：

- 如果 `taskRoutes` 不存在，adapter 仍按当前逻辑运行。
- 如果某个 `taskType` 没有配置 route，adapter 使用同名 `taskType` 作为 `task_id`。
- 如果 provider 未配置 URL 或 API Key，继续使用 mock 结果，保证插件链路可验收。

## 5. Adapter 请求结构

adapter 调用 Dify 工作流时，统一把任务信息放入 `inputs` 或企业封装要求的 `input_data` 中。

推荐结构：

```json
{
  "inputs": {
    "task_id": "word.proofread",
    "scene": "word",
    "trace_id": "word-proofread-20260509-0001",
    "selection_mode": "document",
    "document_text": "...",
    "document_structure": {},
    "template_id": "technical-file-format-requirements",
    "user_instruction": "",
    "options": {}
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant"
}
```

如果企业封装 API 仍使用当前 Dify 对话型格式，也可以保持：

```json
{
  "input_data": {
    "task_id": "word.proofread",
    "scene": "word",
    "trace_id": "word-proofread-20260509-0001",
    "payload": {}
  },
  "query": "任务提示词",
  "mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

一期实现时应以当前企业封装 API 已验证通过的字段为准，避免一次性切换请求协议造成目标机回归风险。

## 6. Dify 工作流分流设计

Dify 工作流入口接收 `task_id` 后，通过判断节点分流：

```text
if task_id == "word.rewrite"           -> 智能改写路径
if task_id == "word.continue"          -> 智能续写路径
if task_id == "word.proofread"         -> 格式校对路径
if task_id == "word.format_preview"    -> 智能排版预览路径
if task_id == "word.technical_review"  -> 技术审查路径
else                                    -> 返回不支持的任务类型
```

每条路径必须输出 adapter 可解析的 JSON：

- `word.rewrite` / `word.continue`：返回 `answer`，内容为最终文本。
- `word.proofread`：返回 `{"issues": [...]}`。
- `word.format_preview`：返回排版建议列表，后续可扩展为 AI 参与，当前仍可保留本地规则为主。
- `word.technical_review`：返回 `{"summary":"...","issues":[...]}`。

## 7. Adapter 内部职责

adapter 负责稳定边界：

- 从 WPS 插件接收任务请求。
- 读取 `taskRoutes`，解析当前任务的 `task_id`。
- 注入 `task_id`、`trace_id`、`scene`、`selection_mode` 等通用字段。
- 构造 Dify 请求。
- 解析 Dify 输出为当前前端已使用的数据结构。
- 保持 mock 回退能力。
- 保持本地规则检查能力，不把所有确定性格式规则都交给大模型。

## 8. 前端设置页边界

一期设置页保持简单：

- 模型提供商名称
- 大模型 API URL
- 企业接口密钥
- 联调状态
- 运行探针

暂不在 UI 上暴露每个任务的路由配置。`taskRoutes` 先通过 `config/adapter.json` 或交付包默认配置维护。

## 9. 一期验收标准

- 只配置一次 API URL 和 API Key。
- adapter `/health` 可显示 provider 已配置。
- WPS 五个入口可以打开同一个任务窗格并切换任务。
- 智能改写、智能续写、格式校对、智能排版预览、技术审查都能通过相同 provider 发起请求。
- Dify 工作流可以通过 `task_id` 正确进入对应路径。
- 未配置 provider 时，插件仍可通过 mock 完成基础链路验证。

## 10. 后续演进方向

当一期能力稳定后，再升级到：

```text
单 provider + taskRoutes + 多任务密钥 / 多工作流
```

演进时可以保留当前 `taskRoutes` 结构，只增加：

- `path`
- `apiKeyRef`
- `responseMode`
- `workflowId`
- `enabled`
- `fallbackToDefault`

这样不会推翻 WPS 插件和 adapter 的任务接口。
