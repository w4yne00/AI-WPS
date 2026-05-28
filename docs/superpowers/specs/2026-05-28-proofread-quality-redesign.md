# Proofread Quality Redesign

日期：2026-05-28

目标版本：`v0.12.8-alpha`

## 背景

目标机已经确认智能编写和智能排版的 adapter 工作流选路正常：不同任务可根据各自配置的 API Key 进入对应 Dify 工作流。智能编写功能正常，智能排版暂缓继续改造。

智能排版暴露出的核心限制是：长文档一次或大批量发送给 Dify 后，受模型上下文窗口和最大输出 token 影响，容易执行卡住或返回不完整。格式校对下一版需要吸收这个经验，不能把整篇文档作为单次大提示词交给模型处理。

## 设计目标

格式校对需要覆盖四类能力：

- 错别字检测：识别明显错别字、同音错词、专业术语误写。
- 格式检测：检查字体、字号、行距、段前段后、标题层级、编号、空格、中文标点和模板规则一致性。
- 语言逻辑表达检测：识别语病、主谓宾缺失、前后矛盾、因果关系不清、结论和依据不匹配。
- 通畅性检测：识别句子拗口、重复堆砌、指代不清、衔接不顺和表达不够简洁的问题。

## 已确认保护边界

- 不修改已经正常的智能编写功能。
- 不修改智能排版功能，本轮只把其上下文限制问题记入遗留项。
- 不修改智能编写、智能排版现有 adapter 选择路由和任务级 API Key 逻辑。
- 格式校对继续使用独立任务类型 `word.proofread`。
- 格式校对继续使用自己的独立 API Key，通过现有任务级密钥配置命中自己的 Dify 工作流。
- 所有任务仍使用统一 `/chat-messages` 调用路径；任务级 API Key 只决定进入哪个 Dify 应用。

## 推荐方案

采用方案 A：本地规则保底 + 小批量 AI 审校 + 结果聚合去重。

格式检测继续由 adapter 本地规则完成，因为格式规则来自模板和 WPS 段落属性，不需要模型判断。AI 只处理文本质量类问题，包括错别字、语病、表达逻辑和通畅性。adapter 将文档切成小批段落发送给 `word.proofread` Dify 工作流，每批返回短 JSON 问题列表，然后由 adapter 合并、去重、排序并返回任务窗格。

## 数据流

```text
WPS 文档段落与结构
  -> POST /word/proofread
  -> 本地格式规则检查
  -> 文本段落按小批切分
  -> word.proofread /chat-messages
  -> Dify 返回短 JSON 问题列表
  -> adapter 解析、校验、去重、合并本地问题
  -> 任务窗口按类别展示问题清单
```

## 本地规则职责

本地规则负责稳定、可解释的格式问题：

- 模板字体和字号不一致。
- 正文、标题、图表题、注、列项的行距、缩进、段前段后不一致。
- 标题层级跳级。
- 正文字体或字号混用。
- 连续空格。
- 中文标点前多余空格。
- 章节命名或编号格式明显不一致。

本地规则输出继续使用现有 `Issue` 结构，`source=local`，可自动修复项保留 `autoFixable=true`。

## AI 审校职责

AI 只负责文本质量问题，不负责判定复杂 Word 版式：

- `typo`：错别字、同音错词、术语误写。
- `grammar`：明显语病、成分残缺、搭配不当。
- `expression`：表述不规范、口语化、冗余、措辞不适合技术文件。
- `logic`：前后矛盾、因果关系不清、条件和结论不匹配。
- `fluency`：不通顺、重复堆砌、指代不清、衔接不自然。

AI 不返回全文改写，不返回 Markdown，不输出解释性前后缀，只返回结构化 JSON。

## Dify 输入约束

为避免上下文和输出 token 限制，adapter 应动态控制每批输入规模：

- 每批建议 `15-30` 段。
- 每批总文本建议不超过 `3000-5000` 个中文字符。
- 单段进入 AI 的文本可限制为 `500-800` 字，超长段落后续可再做句级切分。
- 每批携带最小上下文：段落编号、段落文本、可选标题路径。
- 不发送完整 `documentStructure`，只发送必要的本批信息和检查范围。

推荐请求提示词中的输入形态：

```json
{
  "checkScope": ["typo", "grammar", "expression", "logic", "fluency"],
  "paragraphs": [
    {
      "paragraphIndex": 12,
      "headingPath": "2.1 系统组成",
      "text": "待校对段落文本"
    }
  ]
}
```

## Dify 输出约束

推荐 Dify 回复节点直接输出如下 JSON，不包裹 Markdown 代码块：

```json
{
  "issues": [
    {
      "paragraphIndex": 12,
      "category": "typo",
      "severity": "warning",
      "original": "文挡",
      "suggestion": "文档",
      "message": "疑似错别字",
      "reason": "上下文中应为“文档”。",
      "confidence": 0.92
    }
  ]
}
```

字段约束：

- `category` 只能使用 `typo`、`grammar`、`expression`、`logic`、`fluency`。
- `severity` 只能使用 `info`、`warning`、`error`。
- `paragraphIndex` 必须来自输入段落。
- 没有问题时返回 `{"issues":[]}`。
- `original` 必须是本批输入里的原文片段。
- `suggestion` 只给局部建议，不输出整篇重写。

## 聚合与去重

adapter 合并本地和 AI 结果时应：

- 按 `paragraphIndex`、`category`、`original`、`suggestion` 做去重。
- 同一位置多个同类问题优先保留高严重级别和高置信度项。
- 保留本地格式问题，不被 AI 结果覆盖。
- 对 AI 返回的越界段落号、非法分类、空 original 的问题丢弃并计入诊断。
- 单批 Dify 请求失败时，只跳过该批，其他批和本地规则继续返回。

## 任务窗口展示

任务窗口仍保持问题清单，不做自动改写正文。

建议按类别显示：

- 格式规范
- 错别字/用词
- 语病与表达
- 逻辑清晰
- 通畅性

每条问题展示段落号、问题类型、原文片段、建议、依据、严重级别和是否可自动修复。

## 诊断能力

`/provider/debug-last` 保留最后一次 `word.proofread` 批次调用摘要。后续可在 `/word/proofread` 响应中增加 summary：

| 字段 | 含义 |
| --- | --- |
| `paragraphCount` | 本次校对段落数 |
| `localIssueCount` | 本地规则发现数量 |
| `aiBatchCount` | 尝试调用 Dify 的批次数 |
| `aiIssueCount` | AI 接受的问题数量 |
| `aiRequestErrorCount` | AI 批次请求失败数量 |
| `aiInvalidIssueCount` | AI 返回非法问题数量 |
| `provider` | `local` 或 `enterprise-dify-chat/<authSource>` |

## 测试策略

- proofreader 单测覆盖本地格式规则仍能独立工作。
- proofreader 单测覆盖长文档被切成多批小请求。
- provider 单测覆盖 `word.proofread` 继续使用任务级 API Key。
- parser 单测覆盖 Dify 返回 `issues`、包装字段、空结果和非法分类。
- 前端布局冒烟验证格式校对入口、分类文案和问题清单展示。
- 回归智能编写和智能排版相关测试，确保本改造不触碰它们的路由、API Key 和业务行为。

## 不做事项

- 不实现智能排版的小批量优化，本项已记入 handoff 遗留项。
- 不修改智能编写、智能排版、技术文档审查的接口语义。
- 不恢复 `taskRoutes` 路由 path 选择。
- 不让 Dify 输出全文改写结果。
- 不在格式校对中直接修改 Word 正文。
