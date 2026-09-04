# Excel“智能填写”模型调用合同

适用任务：`excel.smart_fill`

用户可见名称：智能填写

稳定结果版本：`excel.smart_fill.v2`

本合同同时适用于模型直连和工作流平台。Adapter 负责来源边界、逐行填写项、严格解析和写回安全；模型只根据已授权的来源上下文，为不可猜测的 `itemId` 返回文本或普通数值。目标地址在本版本生成请求中不存在，写入目标由后续写回阶段单独绑定。

## 输入

Adapter 接收 JSON 请求，并在内存中冻结工作簿身份、来源范围和来源快照；目标地址及目标原值不属于生成请求。请求的主要结构如下；示例使用合成数据，不代表真实业务内容：

```json
{
  "workbookId": "synthetic-workbook",
  "scene": "excel",
  "clientJobId": "smart-fill-doc-001",
  "items": [
    {
      "itemId": "sf_00000000000000000000000000000001",
      "sourceRowIndex": 1,
      "sourceRowLabel": "第 2 行"
    }
  ],
  "source": {
    "sheetName": "Sheet1",
    "address": "A1:C3",
    "snapshotHash": "00000000",
    "headers": ["名称", "说明", "规则"],
    "rows": [["甲", "第一项", "A"]],
    "rowCount": 1,
    "columnCount": 3,
    "truncated": false
  },
  "userInstruction": "根据来源上下文填写分类。"
}
```

实际生成请求包含工作簿身份、填写项标识、来源范围和用户填写意图；目标地址、目标原值、公式标记和批注不会进入模型提示词。模型看到的来源按表头与逐行 `itemRows` 绑定。隐藏单元格、来源公式表达式、公式单元格的计算结果、批注、其他工作表和整个 `UsedRange` 不进入上下文。公式单元格以空显示值进入对应来源行，不把 `Formula` 或可见计算结果送给模型。公开 `itemId` 必须匹配 `^sf_[0-9a-f]{32}$`。

来源必须是同一工作表中包含一行表头和至少一行可见数据的连续矩形区域，最多 500 个数据行。非连续、跨表、仅表头、含隐藏数据、含合并区域或超限来源在提交前拒绝。填写意图为空时，Adapter 返回 `EXCEL_SMART_FILL_INSTRUCTION_REQUIRED`，不调用模型。

## 输出

模型必须只返回一个 JSON 对象，不能返回 Markdown、解释文字、注释、地址或额外字段：

```json
{
  "schemaVersion": "excel.smart_fill.v2",
  "items": [
    {
      "itemId": "sf_00000000000000000000000000000001",
      "status": "completed",
      "valueType": "text",
      "value": "A类"
    }
  ]
}
```

`items` 必须与本批填写项一一对应，每个 `itemId` 只能出现一次，不能新增、遗漏、改写或通过地址推断。`status` 只能是 `completed` 或 `insufficient_information`；后者的 `value` 必须是空字符串。`valueType` 只能是 `text` 或 `number`；完成的文本不能为空，数字必须是有限 JSON 数字，不能是布尔值或 `NaN`/`Infinity`。

模型不得返回或执行公式。以 `=`, `+`, `-`, `@` 开头的业务文本仍按普通文本返回；前端写回时会将其作为字面值保护。日期和布尔值首版按文本处理。无法从授权上下文可靠得到的事实必须返回 `insufficient_information`，不得使用外部知识补齐姓名、机构、日期、金额、数量、地域或责任主体。

## 容量和任务生命周期

- 单任务最多 500 个目标；单批最多 50 个目标。
- 用户指令最多 4,000 个 Unicode 码点；单个上下文文本最多 2,000 个码点；请求文本合计最多 200,000 个码点。
- 请求体最多 2 MiB；Adapter 会根据已授权来源上下文动态缩小批次，不静默截断。
- 单次 provider 调用最长 30 分钟；任务总时限 60 分钟，排队、纠正、重试和批次间等待均计入。
- 终态结果仅保留在当前 Adapter 进程内，默认两小时；Adapter 重启后任务视为中断，不支持跨重启恢复。
- 公开进度只包含任务阶段、计数、排队位置和时间摘要，不包含来源、用户指令或生成值。

模型结果首次不符合严格结构时，Adapter 最多发起一次只带校验错误的结构纠正请求；第二次仍无效则整批失败，不从自由文本或无效结果中挑选部分内容。

## 接口与错误

任务接口：

- `POST /excel/smart-fill/jobs`：提交后台任务。
- `GET /excel/smart-fill/jobs/{jobId}`：查询任务或使用 `?resume=1` 识别 Adapter 重启中断。
- `DELETE /excel/smart-fill/jobs/{jobId}`：排队时取消；运行中请求协作取消，当前 provider 调用结束后不再启动下一批。
- `POST /excel/smart-fill`：兼容同步入口，仍使用同一后台协调器。

常见错误码包括 `EXCEL_SMART_FILL_TARGET_SHAPE_INVALID`、`EXCEL_SMART_FILL_CROSS_SHEET`、`EXCEL_SMART_FILL_TARGET_UNSAFE`、`EXCEL_SMART_FILL_INSTRUCTION_REQUIRED`、`EXCEL_SMART_FILL_REQUEST_TOO_LARGE`、`MODEL_RESULT_INVALID` 和 `EXCEL_SMART_FILL_RESULT_TOO_LARGE`。错误 envelope 只返回 `traceId`、`taskType`、稳定错误码和脱敏中文说明。

## 写回边界

模型生成阶段仅接受来源区域，模型无目标地址感知权。生成预览后，用户在当前工作表中动态选择目标区域，任务窗格实时校验目标有效性并展示候选摘要与可写入项计数。

产品写回规则：模型没有地址控制权。生成后任务窗格展示逐项预览，用户可以编辑、取消勾选或单独重试；用户点击“写入内容”时，前端现场读取当前选区并执行以下校验与写入流程：
1. 目标区域必须与来源位于同一工作表，且为连续单列区域；
2. 目标单元格总数必须严格等于预览项总数（`items.length`），自上而下一一对应；用户未勾选、失败或信息不足项对应的目标单元格保持原样跳过，不向上移位；
3. 目标区域不得与来源区域重叠；
4. 目标区域内若包含公式单元格、合并单元格、隐藏单元格或受保护单元格，立即拒绝写入；
5. 空白单元格直接写入；若包含已有文本或数字单元格，在写入前弹出一次合并确认对话框（告知覆盖单元格数与目标区域）；
6. 写入前复核工作簿标识、工作表状态和来源区域快照（`snapshotHash`）；若来源已改动或发生冲突则中止写入；
7. 写入过程保持单元格既有格式与样式，对以 `=` 等公式前缀开头的文本添加 `'` 保护；遇宿主写入故障自动逆序补偿回滚；补偿失败时明确提示需人工核对的单元格地址。系统不提供撤销按钮或原生 Undo 承诺。

## 隐私要求

工作流日志、Adapter 日志和诊断只能记录任务类型、计数、长度、阶段、耗时、Token、provider 和错误码。禁止记录用户正文、来源表格、用户指令、生成值、公式、API Key、完整模型原始回复和敏感本地路径。
