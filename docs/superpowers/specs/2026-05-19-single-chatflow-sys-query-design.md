# v0.11.2-alpha Single Chatflow sys.query Design

更新时间：2026-05-19

## 背景

`v0.11.0-alpha` 和 `v0.11.1-alpha` 尝试通过 Dify Workflow Start 自定义变量、每任务路由和每任务 API Key 来稳定智能编写链路。目标机实测仍出现“adapter 发出原文后，任务窗格结果原样返回”的问题。为了排除多路由、多 Key、多 Start 变量和 Output 字段映射带来的不确定性，本版本先收敛为单一 Dify Chat 应用调用。

早期智能改写/续写正常的关键路径是：adapter 构造完整中文提示词，作为 Dify Chat `/chat-messages` 的顶层 `query` 发送，由 Dify 应用通过系统自带 `sys.query` 读取。`v0.11.2-alpha` 回归这条路径。

## 目标

- 所有 AI 任务统一调用同一个 Dify Chat 应用。
- adapter 不再按任务选择 `path`、`payloadStyle`、`apiKeyRef`。
- adapter 将完整任务提示词放入 `/chat-messages` 顶层 `query`。
- Dify 端只需要读取系统自带 `sys.query`，不要求新增 `source_text`、`write_action` 等 Start 输入变量。
- 设置页只保留统一 API URL 和统一 API Key 配置。

## 非目标

- 不继续调试多 Workflow 路由。
- 不支持每任务独立 API Key。
- 不要求 Dify Workflow 自定义 Start 字段。
- 不删除现有 Word 功能入口；只改变 adapter 调 Dify 的方式。

## 统一调用协议

adapter 统一发送：

```json
{
  "inputs": {},
  "query": "完整中文任务提示词，包含任务类型、选项、用户要求、待处理原文和输出约束",
  "response_mode": "blocking",
  "conversation_id": "",
  "user": "wps-ai-assistant",
  "files": []
}
```

默认配置：

```json
{
  "providerType": "enterprise-dify-chat",
  "providerChatPath": "/chat-messages",
  "providerMode": "blocking"
}
```

## 设置页

设置页保留：

- 模型提供商名称。
- 大模型 API URL。
- 统一 Dify Chat API Key。
- 保存地址、保存密钥、清除密钥、刷新配置。

设置页移除：

- 任务接口列表。
- 每任务 API Key 输入。
- 每任务 `path/payloadStyle/apiKeyRef` 展示。

## 后端行为

- `ProviderClient.post_task()` 改为统一调用 `providerBaseUrl + providerChatPath`。
- 鉴权只读取统一密钥：`run/provider_api_key` 或环境变量 `ENTERPRISE_AI_API_KEY`。
- `taskRoutes` 可在配置文件中保留兼容，但运行时忽略。
- `/config` 不再暴露任务路由配置作为主要设置项；可保留空对象或兼容字段。
- `/provider/route-diagnostics` 改为显示统一 Chat endpoint、统一 key 状态和 `sys.query` 模式。

## 各任务提示词

智能编写、旧改写、格式校对 AI、技术文档审查仍使用现有 adapter 内的 prompt 构造函数。差异是这些 prompt 不再拆成 Start 变量，而是完整作为 `query` 发送。

## 验收标准

1. `/config` 显示 `providerChatPath=/chat-messages`，统一密钥配置状态正确。
2. 设置页不再显示“任务接口”和每任务 API Key 控件。
3. 保存统一 API Key 后，所有 AI 任务都使用同一个 Authorization Bearer key。
4. 智能编写请求体顶层 `query` 包含“待处理原文”和“不允许原样返回原文”。
5. 智能编写请求体不依赖 `inputs.source_text`、`inputs.write_action` 等自定义 Workflow 字段。
6. Dify Chat 应用中通过 `sys.query` 可看到完整提示词。
