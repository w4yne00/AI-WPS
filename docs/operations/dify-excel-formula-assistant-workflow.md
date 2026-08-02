# Excel“公式助手”Dify 工作流配置

适用任务：`excel.formula_assistant`

推荐任务级 API Key 引用：`excel_formula_assistant`

用户可见名称：公式助手

提示词模板：`docs/prompt-templates/excel-formula-assistant-prompt-template.md`

## 输入约定

adapter 将完整提示词放入 Dify `/chat-messages` 顶层 `query`。旧工作流默认同时获得 `inputs.query`；新版“用户输入”节点应引用 `userinput.query`，HTTP 400 时 adapter 会自动切换输入格式。

提交必须包含用户明确选择的范围和必填计算要求。adapter 只发送有限上下文：地址、首行表头、单元格显示文本、有限值类型、已有公式及截断状态；前端最多采集 30 行、20 列，不会回退到工作表 `UsedRange`。

## 输出约定

工作流应只返回一个 JSON 对象：

```json
{
  "primaryFormula": "=SUM(B2:B10)",
  "suggestedTarget": "B11",
  "explanation": "汇总 B2 至 B10 的数值。",
  "assumptions": ["B2:B10 为待汇总数据"],
  "compatibilityNotes": ["兼容 WPS 表格常用函数语法"],
  "copyText": "=SUM(B2:B10)"
}
```

`primaryFormula` 必须是唯一主公式并以 `=` 开头，`copyText` 与其一致。不要返回备选公式列表，不要声称已写入、填充或修改工作簿。adapter 会过滤意外出现的 `<think>` 内容，并把主公式单独提供给复制按钮。

## 长任务与队列

- `POST /excel/formula-assistant/jobs` 提交任务，`GET /excel/formula-assistant/jobs/{jobId}` 查询或恢复任务，`DELETE` 仅取消仍在排队的任务。
- 任务与文档审查、智能分析、智能总结共用长任务队列；提交时冻结所选工作流档案和认证快照。
- 运行中的阻塞式 provider 请求不可取消。adapter 重启后，旧任务号会返回 `EXCEL_FORMULA_JOB_INTERRUPTED`，前端提供重新提交入口。
- 模型等待预算为 1800 秒；界面展示排队位置、真实处理阶段和耗时。

## 安全边界

- 公式助手只生成、解释和复制文本，不调用 Excel 写入 API。
- 禁止设置 `Formula`/`FormulaLocal`、批量填充、新建工作表、更改计算模式或提供“撤销写回”。
- 工作流不得补造未提供的数据、字段和业务规则；输入截断时必须在假设或兼容性说明中指出。

## 排查

在 Excel 设置页切换到“公式助手”，确认档案和 API Key 对应 `excel.formula_assistant`。再查看高级诊断中的共享协调器容量、排队数、阶段、终态耗时和脱敏错误；诊断不得展示单元格正文、公式正文或密钥。
