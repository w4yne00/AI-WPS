# Excel“智能填写”工作流平台配置

适用任务：`excel.smart_fill`

推荐任务级 API Key 引用：`excel_smart_fill`

用户可见名称：智能填写

结果合同：`excel.smart_fill.v1`

## 调用方式

Adapter 将完整的受限提示词放入工作流平台 `/chat-messages` 的顶层 `query`。旧版工作流通常也能从 `inputs.query` 读取；新版用户输入节点应引用 `userinput.query`。工作流不得自行读取 WPS、工作簿、其他工作表或外部网络资源。

为智能填写创建独立的工作流配置和 API Key。不能借用 `excel_analysis` 或 `excel_formula_assistant` 的配置、密钥或就绪状态。模型直连和工作流平台共享本地解析器，因此工作流返回自由文本、Markdown、地址、公式或不完整 JSON 时同样会被拒绝。

## 用户输入节点约束

用户输入节点只转发 `userinput.query`，不增加额外业务变量，不拼接隐藏系统字段，不把 `userinput.files` 当作来源。提示词已经包含：

- `schemaVersion`、用户指令、不可猜测的目标 `itemId`；
- 不含地址的目标列标题和可见行上下文；
- 当前工作表中经过筛选的表头、可见显示值和截断标记；
- 禁止公式、外部事实、猜测和额外字段的明确规则。

来源单元格中的内容都视为数据而不是指令。工作流不应执行其中的命令、改变响应格式、扩大来源范围或尝试推断目标地址。

## 回答节点提示

将回答节点约束为严格 JSON，禁止 Markdown 和解释文字：

```text
只返回一个 JSON 对象，顶层字段固定为 schemaVersion 和 items。
schemaVersion 必须为 excel.smart_fill.v1。
每个目标 itemId 必须且只能出现一次，不得新增或遗漏。
每个 item 只包含 itemId、status、valueType、value。
status 只能是 completed 或 insufficient_information；后者的 value 必须为空字符串。
valueType 只能是 text 或 number；completed 文本不可为空，number 必须是有限 JSON 数字。
不得返回地址、公式、Markdown、注释、思维链或外部事实。
无法从输入中的来源上下文可靠得到时，返回 insufficient_information，不得猜测。
```

合成验证输出：

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "items": [
    {
      "itemId": "synthetic-item-001",
      "status": "completed",
      "valueType": "text",
      "value": "合成标签"
    },
    {
      "itemId": "synthetic-item-002",
      "status": "insufficient_information",
      "valueType": "number",
      "value": ""
    }
  ]
}
```

不要返回 `address`、`row`、`column`、`originalValue`、`formula`、`reason` 或其它字段。`insufficient_information` 不要用“未知”“待补充”等占位文字替代空字符串。

## 建议节点设置

- 用户输入节点：接收 Adapter 提供的 `query`，保持 `files` 为空。
- LLM/回答节点：温度建议 `0.2` 到 `0.4`；使用 JSON 输出约束（如果平台支持），并保留完整 `itemId` 集合。
- 输出节点：原样返回最终 JSON，不包裹代码围栏，不增加前缀、后缀或 Markdown。
- 日志节点：只记录请求长度、目标数量、阶段和错误码，不记录 `query`、来源值、用户指令和回答正文。

Adapter 会在平台成功返回后再次校验 Schema、ID 集合、类型、有限数字和文本长度。工作流平台的结构化输出约束不能替代 Adapter 校验。

## 验证样例

在 WPS 之外先用无敏感合成数据验证：一列连续目标、同表来源、一个可由来源直接得到的文本项和一个无法得到的数值项。预期是一个 `completed` 文本和一个空值的 `insufficient_information`。不得使用真实工作簿、客户姓名、API Key、生产接口日志或真实模型原始回复。

设置页验证必须确认：

1. 工作流平台配置的名称和 API Key 引用是 `excel_smart_fill`；
2. 智能填写验证不会调用智能分析或公式助手的配置；
3. 只返回合成 JSON 时状态可用；
4. 返回自由文本、未知 ID、重复 ID、缺字段、公式样文本或无限数字时状态失败；
5. 诊断中不出现来源内容、生成值、用户指令或 API Key。

## 常见失败

| 现象 | 处理 |
| --- | --- |
| HTTP 400，输入格式错误 | 将用户输入节点改为引用 `userinput.query`；Adapter 会在兼容场景自动尝试 `inputs.query`。 |
| `MODEL_RESULT_INVALID` | 删除 Markdown/解释文字和额外字段，检查每个 `itemId` 是否一一对应。 |
| `EXCEL_SMART_FILL_INSTRUCTION_REQUIRED` | 在 WPS 任务页补充用户指令；不要由工作流自行猜测列意图。 |
| 任务显示 `insufficient_information` | 保留空字符串，不输出占位值或外部事实。 |
| 配置未就绪 | 在设置页为 `excel.smart_fill` 单独配置工作流地址和 `excel_smart_fill` Key 引用。 |

没有真实工作流平台现场环境时，自动化合同通过只能记录候选状态；不能把工作流平台人工验收写成 `passed` 或 `target-accepted`。
