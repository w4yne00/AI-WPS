# Dify Chat 用户输入兼容设计

日期：2026-07-03

## 目标

让 adapter 的 `/chat-messages` 调用同时兼容两类 Dify Chatflow：

- 旧工作流从 `inputs.query` 读取完整任务提示词。
- 新工作流使用“用户输入”节点，从 `userinput.query` 和 `userinput.files` 读取顶层 `query` 与 `files`。

不修改智能编写、智能仿写、文档审查、格式审查、Excel 智能分析的提示词、超时、结果解析、前端展示或写回逻辑。

## 根因

当前 adapter 固定发送：

```json
{
  "inputs": {"query": "完整提示词"},
  "query": "完整提示词",
  "files": []
}
```

新版 Dify 中，`userinput.query` 和 `userinput.files` 是 Chatflow 内部“用户输入”节点的变量。公开 `/chat-messages` API 仍使用顶层 `query` 和 `files`；`inputs` 只承载应用自定义变量。新应用没有自定义输入字段时，严格校验可能拒绝额外的 `inputs.query` 并返回 HTTP 400。

## 兼容策略

adapter 默认保持旧格式，避免改变现有工作流行为：

```json
{
  "inputs": {"query": "完整提示词"},
  "query": "完整提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

当旧格式收到 HTTP 400 时，adapter 使用相同 URL、API Key、任务提示词和超时预算，自动重试一次新版格式：

```json
{
  "inputs": {},
  "query": "完整提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

认证失败、服务不可达、超时和 HTTP 5xx 不触发格式回退。新版格式仍返回错误时，沿用现有 provider 异常链路返回失败。

## 模式缓存

新版格式成功后，adapter 在当前进程内缓存该目标的输入模式。缓存键由以下非敏感字段组成：

- `providerBaseUrl`
- `providerChatPath`
- `taskType`
- `taskApiKeyRef`

后续同一目标和任务直接使用已成功的新版格式，不再先发送旧格式。URL、path、任务类型或任务级 API Key 引用变化时会形成新的缓存键并重新协商。缓存不写入配置文件，adapter 重启后重新协商一次。

旧格式成功时也可缓存旧模式，确保同一进程内行为稳定。

## 诊断

`/provider/debug-last` 保持脱敏，新增或补充以下信息：

- 本次尝试使用的输入模式：`legacy-input-query` 或 `user-input-node`。
- HTTP 400 响应体的限长脱敏摘要。
- 是否发生兼容回退。
- 最终成功或失败的尝试次数。

不得记录 API Key 或完整提示词。已有 query 预览长度限制继续生效。

## 测试

新增单元测试覆盖：

1. 旧格式首次成功，不发生重试。
2. 旧格式返回 HTTP 400 后以 `inputs: {}` 重试并成功。
3. 新版格式成功后，同一缓存键后续请求直接使用新版格式。
4. 不同 URL、任务类型或任务级 API Key 引用不共享缓存。
5. HTTP 401、403、5xx、网络错误和超时不触发格式回退。
6. 两种格式均失败时保留最终 provider 错误和脱敏诊断。
7. 现有五类任务继续通过同一 `post_task` 链路，无业务 payload、超时或结果解析回归。

## 保持不变

- `/chat-messages` endpoint。
- 顶层 `query`、`files`、`conversation_id`、`response_mode` 和 `user`。
- 统一 API URL、统一 API Key、任务级 API Key 回退规则。
- think 标签剥离和各任务结果解析。
- 文档审查与 Excel 智能分析后台任务、轮询和超时设置。
- Word/Excel 前端、Ribbon、结果预览、复制和写回能力。
