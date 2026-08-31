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

## 参考输入与输出合同

### 输入结构（由 Adapter 组装在 `query` 中）

工作流从 `query`（或旧版 `inputs.query`）中接收 JSON 结构，包含目标项标识与授权来源数据：

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "userInstruction": "根据来源上下文补齐分类或数值。",
  "targetItems": [
    { "itemId": "item-001" },
    { "itemId": "item-002" },
    { "itemId": "item-003" }
  ],
  "targetContext": {
    "columnHeader": "目标列",
    "rowContext": ["上下文A", "上下文B"]
  },
  "source": {
    "headers": ["名称", "数值", "分类"],
    "itemRows": [
      { "itemId": "item-001", "values": ["甲", "100", "A类"] },
      { "itemId": "item-002", "values": ["乙", "200", "B类"] },
      { "itemId": "item-003", "values": ["丙", "", ""] }
    ],
    "truncated": false
  }
}
```

### 单项输出示例（文本完成）

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "items": [
    {
      "itemId": "item-001",
      "status": "completed",
      "valueType": "text",
      "value": "A类"
    }
  ]
}
```

### 单项输出示例（数值完成）

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "items": [
    {
      "itemId": "item-002",
      "status": "completed",
      "valueType": "number",
      "value": 200.5
    }
  ]
}
```

### 单项输出示例（信息不足）

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "items": [
    {
      "itemId": "item-003",
      "status": "insufficient_information",
      "valueType": "text",
      "value": ""
    }
  ]
}
```

### 批量混合输出示例（多项包含文本、数值与信息不足）

```json
{
  "schemaVersion": "excel.smart_fill.v1",
  "items": [
    {
      "itemId": "item-001",
      "status": "completed",
      "valueType": "text",
      "value": "A类"
    },
    {
      "itemId": "item-002",
      "status": "completed",
      "valueType": "number",
      "value": 200.5
    },
    {
      "itemId": "item-003",
      "status": "insufficient_information",
      "valueType": "text",
      "value": ""
    }
  ]
}
```

不要返回 `address`、`row`、`column`、`originalValue`、`formula`、`reason` 或其它额外字段。`insufficient_information` 严禁使用“未知”“待补充”等占位文字替代空字符串。

## 建议节点设置

- 用户输入节点：接收 Adapter 提供的 `query`，保持 `files` 为空。
- LLM/回答节点：温度建议 `0.2` 到 `0.4`；使用严格 JSON 输出约束（若平台支持），并完整覆盖输入中的所有 `itemId`。
- 输出节点：原样返回最终 JSON 字符串，不包裹 markdown 代码围栏（如 ` ```json `），不增加前缀、后缀或解释文字。
- 日志节点：只记录请求长度、目标数量、阶段和错误码，不记录 `query`、来源值、用户指令和回答正文。

Adapter 会在平台成功返回后再次校验 Schema、ID 集合、类型、有限数字和文本长度。工作流平台的结构化输出约束不能替代 Adapter 校验。

## 验证样例与失败案例

在 WPS 之外先用无敏感合成数据验证：一列连续目标、同表来源、一个可由来源直接得到的文本项和一个无法得到的项。预期是一个 `completed` 项和一个空值的 `insufficient_information` 项。不得使用真实工作簿、客户姓名、API Key、生产接口日志或真实模型原始回复。

### 典型失败案例与错误处理

| 失败模式 | 典型响应内容 | 拒绝原因 / 错误码 | 处理方式 |
| --- | --- | --- | --- |
| 自由文本输出 | `已为您生成结果：A类` | `MODEL_RESULT_INVALID`（不接受自由文本兜底） | 配置工作流回答节点仅输出严格 JSON 字符串 |
| Markdown 代码围栏包裹 | ` ```json {"schemaVersion": ...} ``` ` | 首次触发单次结构纠正重试，二次失败抛 `MODEL_RESULT_INVALID` | 移除回答节点的代码块围栏标记 |
| 缺少目标 ID | `items` 仅包含部分 `itemId` | `MODEL_RESULT_INVALID`（目标数量/ID 不匹配） | 确保回答节点按输入的全部 `itemId` 逐一输出 |
| 包含未知 ID | `items` 包含未请求的 `itemId` | `MODEL_RESULT_INVALID`（未知目标标识） | 限制回答节点仅使用输入中的 `itemId` |
| 重复目标 ID | 同一 `itemId` 在 `items` 中出现两次 | `MODEL_RESULT_INVALID`（目标标识重复） | 确保每个 `itemId` 唯一 |
| 包含额外字段 | 项中包含 `address` 或 `formula` | `MODEL_RESULT_INVALID`（协议外多余字段） | 严格限制每个 item 仅含 `itemId, status, valueType, value` 四字段 |
| 信息不足非空值 | `status=insufficient_information, value="暂无"` | `MODEL_RESULT_INVALID`（信息不足值非空） | 信息不足时 `value` 必须设为空字符串 `""` |
| 非有限数值 / 布尔值 | `valueType=number, value=true` 或 `value="NaN"` | `MODEL_RESULT_INVALID`（非有限数值） | 数值必须为有效 JSON 有限数字，严禁布尔类型 |
| 顶层协议版本不符 | `schemaVersion="v1"` | `MODEL_RESULT_INVALID`（版本不匹配） | 固定使用 `schemaVersion: "excel.smart_fill.v1"` |

## 设置页验证

设置页验证必须确认：

1. 工作流平台配置的名称和 API Key 引用是 `excel_smart_fill`；
2. 智能填写验证与其他任务（如智能分析、公式助手）和模型直连配置完全隔离；
3. 只返回合成 JSON 时状态可用；
4. 返回自由文本、未知 ID、重复 ID、缺字段、公式样文本或无限数字时状态失败；
5. 日志与 Provider 诊断中只保留长度、计数、Token、阶段和错误码，不出现来源内容、生成值、用户指令、API Key 或原始错误正文。

## 验收状态规则

没有真实工作流平台现场环境时：
- 自动化合同与合成测试通过仅记录自动化候选 `candidate` 状态；
- 目标机验收记录保持 `manual-pending`，不阻塞直连候选；
- 任何情况下不得宣称工作流平台已经完成人工验收。
