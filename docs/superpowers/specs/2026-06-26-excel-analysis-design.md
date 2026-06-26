# Excel Analysis Design

## Goal

Add the first Excel workflow for AI-WPS: "Excel 智能分析". Users can select a data range in WPS Spreadsheets, or use the current worksheet's used range when no valid selection exists, then generate a readable Chinese analysis report in the task pane.

The first version is read-only. It must not write to cells, create sheets, change formulas, or modify workbook content.

## Product Scope

Excel 智能分析 is the first Phase 2 Excel capability. It focuses on general-purpose table analysis rather than a fixed business template.

The feature has an independent model-backend task:

```text
POST /excel/analysis
taskType = excel.analysis
taskApiKeyRef = excel_analysis
```

It does not reuse Word 智能编写, 智能仿写, 文档审查, or 格式审查 workflows. This keeps prompt design, timeout tuning, diagnostics, and task-level API key configuration separate from Word behavior.

## Host Separation And Delivery

Word and Excel Ribbon entries must not be shown in the wrong host application.

When WPS Writer opens, the WPS AI assistant Ribbon shows only Word actions:

- 智能编写
- 智能仿写
- 文档审查
- 格式审查
- 设置

When WPS Spreadsheets opens, the WPS AI assistant Ribbon shows only Excel actions:

- Excel 智能分析
- 设置

The Linux WPS target should not depend on runtime Ribbon button hiding for this separation. The safer design is to package separate host-specific add-in entries:

- Word add-in entry: `type="wps"`
- Excel add-in entry: `type="et"`

The final delivery remains one installable package. The installer deploys both host add-in folders, rewrites `publish.xml` with both `wps` and `et` entries, and continues to deploy one shared adapter start kit.

The installer must still be able to overwrite a previously installed Word-only version. Existing runtime configuration must be preserved:

- `config/adapter.json`
- `run/provider_api_key`
- `run/provider_api_keys/`

## User Workflow

1. The user opens WPS Spreadsheets.
2. The Ribbon shows `WPS AI 助理` with `Excel 智能分析` and `设置`.
3. The user optionally selects a table range.
4. The user clicks `Excel 智能分析`.
5. The task pane opens in Excel Analysis mode.
6. The pane reads the selected range if available; otherwise it reads the current worksheet used range.
7. The user may fill in `分析要求`, such as "生成经营分析", "关注异常波动", or "总结项目进展".
8. The user clicks `生成分析报告`.
9. The pane shows a structured report by default.
10. The user can switch to a plain report paragraph view and copy the result.

No Excel writeback operation is available in the first version.

## Input Range Rules

The first version reads one range only:

1. Prefer the current selected range when it contains usable cells.
2. If there is no valid selection, use the active worksheet's used range.
3. Do not scan the whole workbook.
4. Do not read multiple worksheets in the first version.
5. Do not read external links or embedded objects.

To avoid task-pane freezes and oversized model payloads, the frontend should apply bounded extraction. The exact limits can be tuned during implementation, but the design should cap:

- maximum rows
- maximum columns
- maximum cell text length
- maximum total serialized characters

When the range exceeds limits, the task pane should still return a useful result by sending headers, representative rows, and summary metadata rather than blocking on a full extraction.

## Extracted Data Shape

The frontend should send structured table data rather than ad hoc text. A first-version payload can use:

```json
{
  "workbookId": "active-workbook",
  "scene": "excel",
  "scope": {
    "type": "selection",
    "sheetName": "Sheet1",
    "address": "A1:F30"
  },
  "table": {
    "headers": ["月份", "部门", "金额", "状态"],
    "rows": [
      ["2026-01", "市场部", "120000", "已完成"]
    ],
    "rowCount": 30,
    "columnCount": 4,
    "truncated": false
  },
  "options": {
    "analysisRequirement": "关注金额变化和异常项"
  }
}
```

The adapter may enrich this with local summary statistics before forwarding to the model backend.

## Result Design

The default result view is a structured analysis report:

- 数据概览
- 关键发现
- 风险异常
- 建议动作

The task pane also provides a plain-text report paragraph view for direct copy into Word or PPT.

Copy should copy the currently relevant generated text. It must not copy hidden diagnostics or raw JSON.

## Frontend Design

Create an Excel-specific Ribbon entry and task-pane mode:

```text
mode = excelAnalysis
```

The Excel task pane can reuse the existing visual language and result view components, but should not expose Word-only controls:

- write action
- style/focus/length controls
- Word template options
- document review controls
- format review controls
- apply preview or writeback buttons

Excel Analysis mode should expose:

- current range summary
- `分析要求` textarea
- run button: `生成分析报告`
- result switch: structured report / plain report
- copy button
- trace and diagnostics lines

Settings should be shared, with task-level API key support extended to:

```text
excel.analysis -> excel_analysis
```

## Adapter API Design

Add a new API namespace rather than placing Excel under `/word`:

```text
POST /excel/analysis
```

The response envelope should follow the existing success/error style:

```json
{
  "success": true,
  "traceId": "excel-analysis-...",
  "taskType": "excel.analysis",
  "message": "completed",
  "data": {
    "structuredReport": {
      "overview": "...",
      "findings": [],
      "risks": [],
      "actions": []
    },
    "plainText": "..."
  },
  "errors": []
}
```

The adapter should accept model responses in either structured JSON or readable Markdown/plain text. If JSON parsing fails, it should keep a readable fallback result rather than leaving the task pane blank.

## Provider Prompt Design

`ProviderClient` should add a dedicated `excel_analysis` method and prompt builder.

Prompt requirements:

- Explain that the model is analyzing spreadsheet data.
- Include sheet name, range address, row/column counts, headers, sample rows, and local summary statistics.
- Ask for concise Chinese business analysis.
- Ask for the four sections: 数据概览、关键发现、风险异常、建议动作.
- Ask for a separate plain report paragraph.
- Avoid inventing facts not present in the data.
- If data is truncated, clearly state that the analysis is based on sampled/limited data.
- Do not output formulas or instructions that imply cells were modified.

The provider call uses the same Dify `/chat-messages` convention as existing tasks: the full prompt is present in both top-level `query` and `inputs.query`.

## Error Handling

User-facing failures should be specific and Chinese:

- no active workbook
- no usable selected range or used range
- range too large and cannot be summarized
- adapter not reachable
- model backend not configured
- model backend timeout or malformed response

If the model backend is slow, the task pane should show visible waiting feedback. The first Excel version does not need the full recoverable background job design used by long Document Review, unless real testing shows model calls regularly exceed normal request budgets.

## Security And Diagnostics

Diagnostics must remain sanitized:

- Do not store or show full spreadsheet content in `/provider/debug-last`.
- Include task type, provider status, auth source, row/column counts, truncation status, and prompt length.
- Mask API keys as existing provider diagnostics already do.

The frontend should avoid logging raw cell data to console in normal operation.

## Testing Strategy

Backend tests:

- request model accepts Excel analysis payload
- provider prompt includes headers, range metadata, requirement, and no-writeback constraints
- task API key status includes `excel.analysis`
- parser accepts structured JSON and falls back to readable text
- route returns sanitized envelope

Frontend/static tests:

- Excel Ribbon package contains only Excel 智能分析 and 设置
- Word Ribbon package still contains only Word buttons and 设置
- shared settings includes `excel.analysis`
- task pane has `excelAnalysis` mode and no writeback path
- result switch supports structured report and plain report

Packaging tests:

- delivery package includes both Word and Excel add-in folders
- `publish.xml` contains both `type="wps"` and `type="et"` entries
- installer preserves runtime adapter configuration when overwriting an older Word-only install

## Non-Goals

The first version does not implement:

- writing reports back to Excel
- creating a new worksheet
- modifying cells or formulas
- multi-sheet analysis
- multi-file comparison
- chart generation
- pivot table generation
- formula generation or formula repair
- background recoverable jobs unless testing proves they are needed

These are candidates for later Excel versions after the read-only analysis workflow is stable on the Linux WPS target.

## Open Implementation Decision

Implementation should verify the exact Linux WPS ET object model methods for selected range and used range extraction on the target machine. The product design does not depend on a specific API name; it requires bounded extraction and clear fallback behavior.
