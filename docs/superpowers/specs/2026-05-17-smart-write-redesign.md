# Smart Write Redesign Design Spec

更新时间：2026-05-17

适用版本目标：`v0.11.0-alpha`

版本规则号目标：`AI-WPS-P1-WORD-0.11.0-20260517`

## 1. 背景与目标

当前 `v0.10.3-alpha` 中，智能改写和智能续写分别作为两个 Ribbon 入口存在，并通过 Dify Chat `/chat-messages` 形态向后端传递 `query` 和 `inputs`。目标机测试发现，即使前端输入原文，模型输出仍可能原样返回。根因不是单点 bug，而是产品、adapter 和 Dify 工作流之间的输入契约不够硬：Chat App 的 `query` 与 Workflow 的 User Input 变量容易混用，Dify 起始节点未定义自定义变量时，adapter 发送的 `inputs.source_text` 不一定被工作流消费。

本次改版的目标是把“智能改写”和“智能续写”合并为一个稳定、可验证的“智能编写”任务，改为 Dify Workflow `/workflows/run` 输入契约，以 `source_text -> Dify Start 输入变量 -> LLM -> outputs.result -> WPS 结果预览` 为唯一闭环。

## 2. 设计治理规则

从本版本开始，除明确的 bug 修复外，所有新功能和功能改进必须先更新本文档，再进入代码实施。代码实现、测试、交付包、部署手册必须与本文档保持一致。

本文档作为以下内容的设计基线：

- Ribbon 功能入口和图标。
- 任务窗格信息架构和交互。
- adapter API、provider taskRoutes 和密钥策略。
- Dify 工作流输入变量、输出字段和联调验收标准。
- 版本状态和交付口径。

## 3. 范围

### 本次变更范围

- 合并“智能改写”和“智能续写”为“智能编写”。
- 智能编写使用独立任务 ID：`word.smart_write`。
- 智能编写使用独立 API Key 引用：`smart_write`。
- 智能编写固定走 Dify Workflow：`/workflows/run`。
- 设置页保留一个全局 API URL。
- 设置页移除全局 API Key。
- 设置页移除运行探针入口。
- 设置页保留每任务独立 API Key：智能编写、格式校对、智能排版、技术审查。
- Ribbon 按新功能标题重新配置图标，移除旧改写/续写图标。

### 不变范围

- 格式校对业务能力不改。
- 智能排版业务能力不改。
- 技术文档审查业务能力不改。
- 三个既有任务仍保留独立 API Key 设置能力。
- WPS 选中文本/全文抽取机制继续沿用现有实现。
- 结果预览和应用结果能力继续沿用现有交互。

## 4. 产品原型

### 4.1 Ribbon

新的 Ribbon 只保留五个入口：

```text
WPS AI 助理
┌────────────┬────────────┬────────────┬────────────┬────────┐
│ 智能编写   │ 格式校对   │ 智能排版   │ 技术审查   │ 设置   │
└────────────┴────────────┴────────────┴────────────┴────────┘
```

旧入口移除：

- 智能改写。
- 智能续写。

### 4.2 智能编写任务窗格

```text
WPS AI 助理
智能编写                                      ok

┌────────────────────────────────────┐
│ 识别范围                      选中文本 │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ 编写动作                            │
│ [ 改写润色 ▼ ]                      │
│ 改写润色 / 续写扩展 / 提炼总结 / 自定义 │
│                                    │
│ 表达风格                            │
│ [ 正式清晰 ▼ ]                      │
│                                    │
│ 侧重点                              │
│ [ 保持完整 ▼ ]                      │
│                                    │
│ 篇幅                                │
│ [ 基本不变 ▼ ]                      │
│                                    │
│ 编写要求                            │
│ ┌──────────────────────────────┐   │
│ │ 补充要求：请突出风险和下一步计划... │   │
│ └──────────────────────────────┘   │
│                                    │
│ [ 生成内容 ]                        │
│ [ 应用结果 ]                        │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ [复制] 结果预览                    │
│                                    │
│ 大模型返回的最终正文                │
└────────────────────────────────────┘
```

### 4.3 设置页

```text
WPS AI 助理
设置

┌────────────────────────────────────┐
│ API 服务地址                         │
│ https://aibot.chinasatnet.com.cn/v1 │
│ [编辑地址]                           │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ 功能密钥                             │
│ 智能编写          已配置   [编辑]      │
│ 格式校对          已配置   [编辑]      │
│ 智能排版          未配置   [编辑]      │
│ 技术审查          已配置   [编辑]      │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ 联调状态                             │
│ 服务：已连接                         │
│ API URL：已配置                      │
│ 任务密钥：按功能显示                 │
└────────────────────────────────────┘
```

设置页删除：

- 全局 API Key 输入。
- 清除全局 API Key 按钮。
- 运行探针按钮。
- 旧的智能改写/智能续写任务密钥项。

## 5. Ribbon 图标设计

所有 Ribbon 图标按新功能标题重新设置，不复用旧改写/续写图标。

| 功能 | 图标建议 | 文件名 |
| --- | --- | --- |
| 智能编写 | 笔尖 + 星光 | `assets/icon-smart-write.png` |
| 格式校对 | 文档 + 对勾 | `assets/icon-proofread.png` |
| 智能排版 | 网格页面 + 对齐线 | `assets/icon-format.png` |
| 技术审查 | 盾牌 + 文档 | `assets/icon-review.png` |
| 设置 | 齿轮 | `assets/icon-settings.png` |

图标约束：

- 统一线性简约风格。
- 文件名必须 ASCII。
- Ribbon 实际引用 PNG，避免 WPS 在目标机显示问号。
- 推荐保留 SVG 源文件，但运行时不依赖 SVG。
- 每个按钮必须在 `ribbon.js` 中显式映射图标路径。

## 6. 数据流

```text
WPS 选中文本/全文
  ↓
任务窗格 smartWrite 参数
  ↓
POST /word/smart-write
  ↓
adapter 读取 taskRoutes.word.smart_write
  ↓
POST {providerBaseUrl}/workflows/run
  ↓
Dify Start 输入变量 source_text/write_action/style/focus/length/user_prompt
  ↓
Dify LLM 节点生成正文
  ↓
Dify Output 节点 outputs.result
  ↓
adapter data.rewrittenText
  ↓
WPS 任务窗格结果预览
```

## 7. adapter API 设计

### 7.1 新增接口

```text
POST /word/smart-write
```

请求体沿用 `WordDocumentRequest`，但 `options` 中新增/复用字段：

```json
{
  "documentId": "wps-doc",
  "scene": "word",
  "selectionMode": "selection",
  "content": {
    "plainText": "用户选中的原文"
  },
  "options": {
    "writeAction": "rewrite",
    "rewriteStyle": "formal",
    "focusPoint": "complete",
    "lengthMode": "same",
    "userInstruction": "补充要求：请突出风险和下一步计划"
  }
}
```

adapter 响应：

```json
{
  "success": true,
  "traceId": "word-smart-write-20260517-0001",
  "taskType": "word.smart_write",
  "data": {
    "rewrittenText": "大模型生成后的最终正文",
    "originalText": "用户选中的原文",
    "rewriteMode": "rewrite",
    "provider": "enterprise-dify-workflow/route-file"
  }
}
```

为了兼容现有应用结果逻辑，响应字段继续使用 `rewrittenText` 和 `rewriteMode`，但业务名称改为“智能编写”。

### 7.2 旧接口兼容

`POST /word/rewrite` 可暂时保留，但前端不再调用。后续版本可以标记为 deprecated。保留它可以降低目标机回滚风险。

## 8. Provider 配置设计

`config/adapter.example.json` 目标结构：

```json
{
  "servicePort": 18100,
  "providerName": "企业大模型接口",
  "providerType": "enterprise-dify-workflow",
  "providerBaseUrl": "",
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
    },
    "word.format_preview": {
      "taskId": "word.format_preview",
      "path": "/workflows/run",
      "apiKeyRef": "format_preview",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
      "enabled": true
    },
    "word.technical_review": {
      "taskId": "word.technical_review",
      "path": "/workflows/run",
      "apiKeyRef": "technical_review",
      "payloadStyle": "workflow",
      "responseMode": "blocking",
      "outputKey": "result",
      "enabled": true
    }
  }
}
```

## 9. API Key 策略

本版本取消全局 API Key 作为产品设置项。每个功能必须配置自己的 API Key。

保存位置：

```text
adapter_service/run/provider_api_keys/<apiKeyRef>
```

读取策略：

1. 优先读取当前任务的 `provider_api_keys/<apiKeyRef>`。
2. 产品层不再展示也不推荐默认 `provider_api_key`。
3. 产品层不再依赖 `ENTERPRISE_AI_API_KEY` 作为正常配置路径。

实现上可以保留底层兼容函数，但 `word.smart_write`、`word.proofread`、`word.format_preview`、`word.technical_review` 的配置状态应以任务级密钥为准。

## 10. Dify Workflow 设计

智能编写必须使用 Dify Workflow。Dify 开始节点必须手工新增自定义输入变量，不能只依赖系统变量 `sys.query`。

### 10.1 Start 输入变量

| 变量名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source_text` | Paragraph/Text | 是 | WPS 抽取的原文 |
| `write_action` | Text/Select | 是 | `rewrite`、`continue`、`summarize`、`custom` |
| `style` | Text/Select | 否 | 表达风格 |
| `focus` | Text/Select | 否 | 侧重点 |
| `length` | Text/Select | 否 | 篇幅要求 |
| `user_prompt` | Paragraph | 否 | 用户补充要求 |
| `selection_mode` | Text | 否 | `selection` 或 `document` |
| `trace_id` | Text | 否 | 联调追踪号 |

### 10.2 adapter 调 Dify 请求

```json
{
  "inputs": {
    "source_text": "WPS 插件抽取到的原文",
    "write_action": "rewrite",
    "style": "formal",
    "focus": "complete",
    "length": "same",
    "user_prompt": "补充要求：请突出风险和下一步计划",
    "selection_mode": "selection",
    "trace_id": "word-smart-write-20260517-0001"
  },
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

### 10.3 LLM 节点提示词

LLM 节点必须通过变量选择器引用 Start 输入变量，不建议手写变量路径。提示词语义如下：

```text
你是企业办公文档智能编写助手。

任务类型：{{write_action}}
表达风格：{{style}}
侧重点：{{focus}}
篇幅要求：{{length}}
用户补充要求：{{user_prompt}}

待处理原文：
{{source_text}}

要求：
1. 必须基于“待处理原文”生成新内容。
2. 不允许原样返回原文。
3. 如果任务类型是 rewrite，请保留原意并优化表达。
4. 如果任务类型是 continue，请基于原文继续扩展，不要重复原文。
5. 如果任务类型是 summarize，请提炼重点。
6. 如果任务类型是 custom，请优先遵循用户补充要求。
7. 只输出最终正文，不要解释过程。
```

### 10.4 Output 节点

Output 节点必须输出：

```json
{
  "result": "大模型生成后的最终正文"
}
```

adapter 只读取 `data.outputs.result`。如果读取失败，任务窗格应显示明确错误：

```text
Dify 工作流未返回 outputs.result，请检查智能编写工作流 Output 节点配置。
```

## 11. 错误处理

智能编写必须覆盖以下错误：

- 未选中文本且全文为空：提示“当前文档没有可处理文本”。
- 未配置全局 API URL：提示“请先在设置中配置 API 服务地址”。
- 未配置智能编写 API Key：提示“请先在设置中配置智能编写密钥”。
- Dify 返回 HTTP 401/403：提示“智能编写密钥无效或无权限”。
- Dify 未返回 `outputs.result`：提示 Output 节点配置错误。
- adapter 不可达：提示本地适配服务未启动或端口未监听。

## 12. 测试与验收

### 12.1 单元测试

- `word.smart_write` route 加载测试。
- `/word/smart-write` 请求体解析测试。
- `ProviderClient.smart_write()` 构造 workflow payload 测试。
- `outputs.result` 解析测试。
- 设置页只渲染四个任务密钥测试。
- Ribbon 只包含五个入口测试。
- 运行探针按钮不存在测试。

### 12.2 目标机验收

1. 启动 adapter。
2. 设置全局 API URL。
3. 配置智能编写 API Key。
4. 在 WPS 选中一段文本。
5. 打开“智能编写”。
6. 选择“改写润色”，填写补充要求。
7. 点击“生成内容”。
8. Dify 日志确认 `source_text` 有值。
9. Dify Output 确认 `result` 有值。
10. WPS 结果预览显示 `result`。
11. 点击“应用结果”替换选中文本。

## 13. 版本与文档同步

实现本设计时必须同步更新：

- `README.md`
- `README-ZH.md`
- `docs/codex-handoff.md`
- `docs/operations/dify-task-routes-path-apikeyref.md`
- 新版本部署手册或既有部署手册中的任务路由说明
- 交付包 README

版本升级：

```text
v0.11.0-alpha
AI-WPS-P1-WORD-0.11.0-20260517
```
