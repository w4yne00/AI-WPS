# Review Mode Consolidation And Format Review Redesign

日期：2026-05-29

目标版本：`v0.12.9-alpha`

## 背景

当前 Word 侧任务入口包括智能编写、格式校对、智能排版、技术文档审查和设置。经过近期目标机测试，智能编写链路已经稳定；智能排版可通过任务级 API Key 命中独立 Dify 工作流，但长文档场景容易受 Dify 输出和模型上下文限制影响；格式校对与技术文档审查的职责存在重叠。

本次重构目标是把任务入口重新整理为更清晰的四类能力：

1. 智能编写：只改前端说明展示，不改后端接口和 adapter 路由逻辑。
2. 文档审查：合并原格式校对和原技术文档审查，专注文档内容质量和专业性审查。
3. 格式审查：由原智能排版演进而来，只检查格式问题，保留 AI 段落角色识别辅助判断，不再自动写回排版。
4. 设置：更新任务级 API Key 名称和诊断文案。

## 设计目标

- 智能编写的“表达风格、侧重点、篇幅”说明统一进入“当前要求”窗格，窗格随内容自然增高，确保说明文字完整可见。
- “智能排版”改为“格式审查”，保留段落角色 AI 识别能力，但只用于选择模板规则和输出格式问题清单。
- 格式审查支持鼠标框选局部检查；无选区时检查全文。
- “格式校对”改为“文档审查”，并合并原“技术文档审查”能力。
- 文档审查采用原技术文档审查的界面形态：文档类型下拉 + 审查重点提示词。
- 文档审查去掉文档模板下拉和格式合规检查，聚焦错别字、语言逻辑表达、通畅性和对应文档类型专业性评估。
- 清理无用旧接口、旧模式和旧测试，避免后续维护多条重复路径。

## 最终入口

Ribbon 和任务窗格保留四个入口：

| 入口 | 前端模式 | 后端接口 | taskType | Dify |
| --- | --- | --- | --- | --- |
| 智能编写 | `smartWrite` | `/word/smart-write` | `word.smart_write` | 需要 |
| 文档审查 | `documentReview` | `/word/document-review` | `word.document_review` | 需要 |
| 格式审查 | `formatReview` | `/word/format-review` | `word.format_review` | 可选，用于段落角色识别 |
| 设置 | `settings` | 配置接口 | 无 | 无 |

删除独立 Ribbon 入口：

- 格式校对
- 智能排版
- 技术文档审查

## 智能编写前端调整

智能编写不修改后端请求、提示词构造、taskType 或 API Key 逻辑。

前端只做布局调整：

- 删除三个下拉菜单下方的 `field-help` 小字展示。
- “当前要求”窗格改为完整说明区，包含：
  - 当前选项摘要：例如 `技术方案正式 / 保持信息完整 / 保持篇幅`。
  - 表达风格说明全文。
  - 侧重点说明全文。
  - 篇幅说明全文。
  - 输出约束说明：不要原样返回待处理内容，只输出最终正文。
- “当前要求”窗格不设置固定高度，不使用截断、省略或内部滚动；内容多少由文字自然撑开。
- 下拉菜单变化时，继续复用现有 `updateRewritePromptPreview()` 更新摘要和说明。

## 文档审查设计

文档审查合并原格式校对中的 AI 文本质量审校，以及原技术文档审查中的文档类型专业性评估。

### 前端界面

文档审查使用原技术文档审查界面：

- 文档类型：
  - 技术方案
  - 合同验收文档
  - 测试大纲及细则
- 审查重点提示词：
  - 默认使用不同文档类型的内置提示词。
  - 用户可编辑。
- 不显示文档模板下拉。
- 不显示格式检查相关控件。
- 不显示“应用预览”。

### 范围选择

保留选区/全文逻辑：

- 鼠标框选段落或文本时，只发送选中内容。
- 点击空白处、没有有效选区或选区为空时，默认发送全文。
- 任务窗格显示实际范围：`选中内容` 或 `全文`。

这样用户可以主动分段审查长文档，规避模型上下文和 Dify 最大输出限制。

### 后端行为

新增 `POST /word/document-review`。

后端服务建议命名为 `WordDocumentReviewer`，职责包括：

- 从 `WordDocumentRequest` 获取当前选区或全文文本。
- 根据 `technicalDocumentType` 选择默认文档类型提示词。
- 合并用户编辑的审查重点。
- 调用 `ProviderClient.document_review()`。
- 解析 Dify 返回的 Markdown 包裹 JSON 或纯 JSON。

文档审查输出结构建议：

```json
{
  "documentType": "technical_solution",
  "reviewPrompt": "审查重点...",
  "scope": "selection",
  "summary": "发现 2 项问题。",
  "issues": [
    {
      "category": "logic",
      "severity": "high",
      "location": "第 3 段",
      "originalText": "原文短片段",
      "problem": "问题说明",
      "suggestion": "修改建议",
      "suggestedRewrite": "可选局部改写"
    }
  ],
  "provider": "enterprise-dify-chat/task-file"
}
```

### 审查类别

文档审查类别收敛为：

| category | 含义 |
| --- | --- |
| `typo` | 错别字、同音错词、术语误写 |
| `expression` | 表达不规范、口语化、冗余、措辞不适合正式材料 |
| `logic` | 前后矛盾、条件和结论不匹配、因果关系不清 |
| `fluency` | 不通顺、衔接不自然、指代不清、重复堆砌 |
| `professional` | 与技术方案、合同验收文档、测试大纲及细则类型相关的专业性问题 |

不再在文档审查中输出 `format` 类问题。

### Dify 输出约束

由于目标 Dify 只能配置 Markdown 输出，文档审查提示词要求 Dify 输出 Markdown 中的单个 `json` 代码块：

````markdown
```json
{"summary":"未发现明显问题。","issues":[]}
```
````

adapter 继续从返回文本中提取 JSON 对象。Dify 不应输出普通 Markdown 标题、列表、解释性文字或全文改写结果。

## 格式审查设计

格式审查由原智能排版能力收敛而来。它保留 AI 段落角色识别，但不再生成自动排版写回计划。

### 前端界面

“智能排版”改名为“格式审查”。

前端显示：

- 检查范围：选中内容或全文。
- 文档模板：固定使用标准模板 `technical-file-format-requirements`，不显示模板下拉。
- 主按钮：`开始格式审查`。
- 不显示“应用预览”。
- 结果区显示格式问题清单。

### 范围选择

格式审查新增选区/全文逻辑：

- 有有效选区时，只检查选中段落。
- 无有效选区时，默认检查全文。
- 前端必须传 `selectionMode`，后端摘要返回同样的 `scope`。
- AI 段落角色识别只对当前范围内的段落调用。

### 后端行为

新增 `POST /word/format-review`。

后端服务建议命名为 `WordFormatReviewer`，可从现有 `WordFormatter` 中提取和保留以下能力：

- 模板加载。
- 本地段落角色推断。
- Dify 段落角色识别。
- Dify 角色 JSON 解析。
- 页面、标题、正文、图表题、注、列项、附录和表正文的模板规则读取。

以下能力不进入新接口，并从前端调用链中删除：

- 自动排版写回计划。
- `targetProperties` 作为应用预览指令。
- 前端 `applyFormatChanges()` 调用链。

格式审查输出结构建议：

```json
{
  "summary": {
    "scope": "document",
    "templateId": "technical-file-format-requirements",
    "paragraphCount": 20,
    "issueCount": 6,
    "aiClassifiedParagraphCount": 12,
    "localFallbackParagraphCount": 8,
    "aiBatchCount": 1,
    "provider": "enterprise-dify-chat/task-file",
    "aiFallbackReason": ""
  },
  "issues": [
    {
      "ruleId": "template_font_size",
      "category": "format",
      "severity": "warning",
      "paragraphIndex": 5,
      "role": "body",
      "message": "正文字号不符合模板要求。",
      "currentValue": "14pt",
      "expectedValue": "12pt",
      "suggestion": "建议按模板设置为 12pt。"
    }
  ]
}
```

### AI 角色识别边界

AI 只判断段落角色，不判断格式是否合规。

Dify 仍返回段落角色 JSON：

```json
{
  "paragraphs": [
    {"paragraphIndex": 1, "role": "heading1", "confidence": 0.92}
  ]
}
```

adapter 用角色选择模板规则，再由本地代码比对实际格式和期望格式。

## 任务级 API Key

设置页任务级 API Key 更新为：

| 显示名称 | taskType | key ref |
| --- | --- | --- |
| 智能编写 | `word.smart_write` | `word_smart_write` |
| 文档审查 | `word.document_review` | `word_document_review` |
| 格式审查 | `word.format_review` | `word_format_review` |

删除设置页显示项：

- `word.proofread`
- `word.technical_review`
- `word.smart_format`

本次不设计旧 key 自动回退。目标机升级后需要重新保存“文档审查”和“格式审查”任务级 API Key。这样做会减少后续维护中的隐藏兼容分支。

## 删除清单

为了避免冗余代码继续堆积，本轮实施时应删除无用旧接口和旧前端路径。

### 后端删除

- 删除 `/word/proofread`。
- 删除 `/word/technical-review`。
- 删除 `/word/format-preview`。
- 删除旧 `/word/rewrite`，前端已统一走 `/word/smart-write`。
- 删除 `WordProofreader` 服务及只服务于旧格式校对的批量 AI 审校入口。
- 删除 `WordTechnicalReviewer` 服务，能力迁移到 `WordDocumentReviewer`。
- 删除 `WordFormatter.preview()` 的自动排版预览语义，改为 `WordFormatReviewer.review()`。
- 删除 `FormatPreviewResponseData`、`FormatPreviewSummary`、`FormatChange` 中只用于应用预览写回的字段；新增专门的 `FormatReviewIssue` 和 `FormatReviewResponseData`。
- 删除 provider 中只服务旧 taskType 的公开方法：`proofread_document_batch()`、`proofread_document()`、`technical_review()`、旧 `word.smart_format` 调用入口。角色识别可迁移为 `format_review_roles()`。

### 前端删除

- 删除 Ribbon 中独立“格式校对”“智能排版”“技术文档审查”按钮。
- 删除 `proofread`、`format`、`technicalReview` 三个旧模式，新增 `documentReview` 和 `formatReview`。
- 删除 `runProofread()`、`runTechnicalReview()`、`runFormatPreview()`，新增 `runDocumentReview()` 和 `runFormatReview()`。
- 删除 `applyFormatChanges()`、`applyPageSetup()`、`applyParagraphStyle()` 及格式写回相关状态。
- 删除 `state.formatChanges` 和 `pendingApplyAction === "format"` 分支。
- 删除旧格式校对的问题摘要文案，改为文档审查和格式审查各自的结果渲染函数。

### 测试和文档删除

- 删除旧 `/word/proofread` API 测试。
- 删除旧 `/word/technical-review` API 测试。
- 删除旧 `/word/format-preview` API 测试。
- 删除或替换旧 Dify 格式校对手册和智能排版工作流手册中不再适用的入口说明。
- 更新 README、README-ZH、handoff、打包脚本引用。

## 保留清单

以下能力必须保留：

- 智能编写 `/word/smart-write`、`word.smart_write`、现有 Dify 请求体和 Markdown 结果渲染。
- 任务级 API Key 机制本身。
- `/chat-messages` 统一调用路径。
- `/provider/debug-last`、`/provider/status`、`/provider/task-api-keys` 等诊断能力。
- 模板加载和标准模板规则。
- WPS 段落采集的数组、`Paragraphs.Count`/`Item()`、`Paragraph.Range.Text`、`Content.Paragraphs`、`Range().Paragraphs` 和全文文本拆段兜底。
- 技术方案、合同验收文档、测试大纲及细则三类默认审查提示词。

## 迁移影响

这是一次有意打断旧接口兼容的清理型改版。

目标机升级后需要：

1. 重新导入插件资源，确保 Ribbon 显示四个入口。
2. 重新启动 adapter，确认版本为 `v0.12.9-alpha`。
3. 在设置页重新配置：
   - 文档审查 API Key。
   - 格式审查 API Key。
4. 不再使用旧的格式校对、智能排版和技术文档审查 task key。

## 测试策略

后端测试：

- `/word/document-review` 支持选区和全文。
- 文档审查 prompt 包含文档类型、用户审查重点、错别字、表达逻辑、通畅性和专业性要求。
- 文档审查 parser 能从 Markdown `json` 代码块中提取 JSON。
- `/word/format-review` 不返回 `targetProperties` 写回计划。
- 格式审查有选区时只处理选区段落。
- 格式审查无选区时处理全文。
- 格式审查保留 AI 段落角色识别；未配置 Dify key 时本地规则仍可输出格式问题。
- 旧 `/word/proofread`、`/word/technical-review`、`/word/format-preview`、`/word/rewrite` 不再出现在路由测试、文档和前端调用中。

前端测试：

- Ribbon 只包含智能编写、文档审查、格式审查和设置。
- 智能编写“当前要求”包含三类说明全文，旧下拉框下方小字不再显示。
- 文档审查显示文档类型和审查重点，不显示模板下拉。
- 格式审查显示范围、模板和结果清单，不显示“应用预览”。
- 主按钮在不同模式下调用正确的新接口。
- 设置页任务级 API Key 只显示智能编写、文档审查和格式审查。

回归测试：

- 智能编写仍调用 `/word/smart-write`。
- Markdown 结果渲染仍正常。
- provider 配置、debug-last 和 uvicorn 运维脚本仍正常。

## 不做事项

- 不恢复旧 `taskRoutes` path/payloadStyle 路由选择。
- 不为旧 `word.proofread`、`word.technical_review`、`word.smart_format` 做自动 key 迁移。
- 不让文档审查检查字体、字号、行距等格式问题。
- 不让格式审查输出全文改写或自动写回 Word。
- 不在格式审查中让 Dify 判断格式合规；Dify 只做段落角色识别。
