# Excel“智能分析”Dify 工作流配置

适用任务：`excel.analysis`

适用版本：`v0.15.1-alpha` 及以上

推荐任务级 API Key 引用：`excel_analysis`

用户可见名称：智能分析

提示词模板：`docs/prompt-templates/excel-smart-analysis-prompt-template.md`

## 输入约定

adapter 始终把完整提示词放入 Dify `/chat-messages` 顶层 `query`。旧工作流默认同时获得 `inputs.query`；新版“用户输入”节点应在下游节点引用 `userinput.query`，HTTP 400 时 adapter 会自动切换输入格式。

提示词内包含工作簿、工作表、范围地址、行列数、表头、样本行、是否截断和用户分析要求。

## 输出约定

推荐输出 JSON：

```json
{
  "structuredReport": {
    "overview": "数据概览",
    "findings": ["关键发现"],
    "risks": ["风险异常"],
    "actions": ["建议动作"]
  },
  "plainText": "可直接复制到 Word 或 PPT 的汇报段落。"
}
```

不要输出公式，不要声称已经修改 Excel 单元格。

## 长任务等待

- adapter 对 `excel.analysis` 的模型等待预算为 1800 秒，与文档审查一致。
- WPS 任务窗格通过 `POST /excel/analysis/jobs` 提交后台任务，再轮询 `GET /excel/analysis/jobs/{jobId}`，不使用单次长连接等待结果。
- 每次提交和状态查询的前台请求上限为 10 秒；短暂超时或连接中断不会清空任务编号，任务窗格会继续自动刷新。
- 未完成任务号保存在任务窗格本地存储中，重新打开“智能分析”任务窗格后会尝试恢复查询。

## 建议模型参数

建议温度在 `0.2` 到 `0.4` 之间。分析类任务应优先稳定、克制、少编造。

## 排查

在 WPS 设置页查看“最近一次任务诊断”，确认 `taskType=excel.analysis`，并确认任务级 API Key 命中 `excel_analysis`。
