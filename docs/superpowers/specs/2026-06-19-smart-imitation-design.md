# Smart Imitation Design

## Goal

Add an independent Word workflow named "智能仿写" that lets users provide a known sentence pattern or paragraph template, describe a new professional scenario or writing need, optionally provide reference material, and receive generated imitation text in the task pane.

The first version is a preview-and-copy feature only. It must not write back to Word, replace a selection, or modify existing smart write, document review, format review, or writeback behavior.

## Product Scope

智能仿写 sits alongside the current Ribbon entries:

- 智能编写
- 智能仿写
- 文档审查
- 格式审查
- 设置

The feature has a separate model-backend task:

```text
POST /word/smart-imitation
taskType = word.smart_imitation
taskApiKeyRef = word_smart_imitation
```

It is not a new action under 智能编写. This keeps workflow routing, model temperature, diagnostics, and task-level API key configuration separate from the existing smart write behavior.

## User Workflow

1. The user clicks the Ribbon button "智能仿写".
2. The task pane opens in Smart Imitation mode.
3. The pane tries to read the current Word selection as the imitation template.
4. The user may edit, replace, or paste the template in the pane.
5. The user fills in "仿写需求". This is required.
6. The user may fill in "参考素材". This is optional.
7. The user clicks "生成仿写内容".
8. The pane shows the generated result.
9. The user can switch between "预览" and "纯文本", then copy the result.

No "对照" view is shown. No "应用预览" button is shown. No writeback operation is available in the first version.

## Frontend Design

### Ribbon

Add a new large button:

```xml
<button id="btnAiSmartImitation" label="智能仿写" size="large" getImage="GetImage" onAction="OnAction" />
```

`ribbon.js` maps:

```js
btnAiSmartImitation -> smartImitation
```

### Icon

Add a new icon asset:

```text
formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png
```

Icon requirements:

- Same visual family as `icon-smart-write.png`, `icon-review.png`, and `icon-format.png`.
- PNG asset used through the existing `GetImage` Ribbon pattern.
- Distinct from "智能编写"; suggested metaphor is "template + generated line" or "copywriting pattern".
- Keep consistent canvas size, stroke weight, color treatment, and transparent background with existing icons.
- No external runtime dependency.

`ribbonIconMap` adds:

```js
btnAiSmartImitation: "assets/icon-smart-imitation.png"
```

### Mode

Add a new task-pane mode:

```js
smartImitation: {
  title: "智能仿写",
  primaryText: "生成仿写内容",
  runningText: "正在执行智能仿写...",
  doneText: "智能仿写结果已生成。",
  showSmartImitationOptions: true
}
```

### State

Add frontend state:

```js
imitationTemplateText: "",
imitationRequirement: "",
imitationReferenceMaterial: ""
```

Entering Smart Imitation mode should attempt a lightweight selection text read. If selected text exists, it fills `imitationTemplateText`. If there is no selected text, the template field remains empty and the user can paste a template manually.

The feature must not require a Word selection.

### Input Panel

Add a dedicated Smart Imitation input section instead of reusing the Smart Write controls:

- `仿写模板`: multiline textarea, auto-filled from Word selection when available.
- `仿写需求`: multiline textarea, required.
- `参考素材`: multiline textarea, optional.

Do not show these Smart Write controls in Smart Imitation mode:

- 表达风格
- 侧重点
- 篇幅
- 编写要求 fragments

### Result Panel

Smart Imitation reuses only these Smart Write result capabilities:

- 预览
- 纯文本
- 复制

It must not expose:

- 对照
- 应用预览
- Word writeback

Preview rendering should reuse the existing safe markdown/plain-text rendering pipeline:

- Plain paragraphs stay readable without extra layout.
- Headings, lists, tables, numbering, and other structured model output render through safe Markdown.
- `<think>...</think>` content remains stripped by the adapter/provider extraction layer.

Copy uses the final generated text, not the template.

## Adapter API Design

### Request

Reuse the existing Word task envelope with a small options extension:

```json
{
  "documentId": "example.docx",
  "scene": "word",
  "selectionMode": "selection",
  "content": {
    "plainText": "仿写模板文本",
    "paragraphs": [],
    "headings": []
  },
  "options": {
    "imitationRequirement": "仿写需求",
    "imitationReferenceMaterial": "参考素材"
  }
}
```

Field meaning:

- `content.plainText`: the final template text after user edits.
- `options.imitationRequirement`: required generation requirement.
- `options.imitationReferenceMaterial`: optional factual reference material.

Do not overload `userInstruction`; keep Smart Imitation semantics explicit.

### Response

Return the existing rewrite-style response data shape:

```json
{
  "originalText": "仿写模板文本",
  "rewrittenText": "生成的仿写内容",
  "rewriteMode": "imitate",
  "diffHints": [],
  "provider": "enterprise-dify-chat/task-file"
}
```

`originalText` is retained as the template for diagnostics and consistency, but the frontend must not render a comparison view for Smart Imitation.

## Backend Service Design

Add a focused service:

```text
adapter_service/app/services/word/smart_imitator.py
```

Responsibilities:

- Extract template text from `request.content.plain_text`, falling back to paragraphs if needed.
- Validate that the template and requirement are non-empty.
- Call `ProviderClient.smart_imitation`.
- Return `RewriteResponseData` compatible fields.

Add route:

```python
@router.post("/word/smart-imitation")
def smart_imitation_word(request: WordDocumentRequest) -> dict:
    trace_id = new_trace_id("word-smart-imitation")
    imitation = smart_imitator.imitate(request, trace_id=trace_id)
    payload = RewriteResponseData(**imitation)
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "word.smart_imitation",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
```

Use a trace prefix such as:

```text
word-smart-imitation
```

## Provider Design

Add prompt builder:

```python
build_smart_imitation_prompt(template_text, requirement, reference_material)
```

Add provider method:

```python
smart_imitation(template_text, requirement, reference_material, trace_id)
```

Task type:

```text
word.smart_imitation
```

Default task key ref:

```json
"word.smart_imitation": "word_smart_imitation"
```

The provider continues to send the official `/chat-messages` payload shape with the full prompt in both `query` and `inputs.query`, following the current enterprise Dify integration.

## Prompt Design

Recommended prompt:

```text
你是企业办公文档智能仿写助手。

仿写模板：
{{template_text}}

仿写需求：
{{requirement}}

参考素材：
{{reference_material}}

要求：
1. 学习仿写模板的句式、层次、表达节奏和段落结构。
2. 生成内容必须服务于仿写需求。
3. 如提供参考素材，应优先基于参考素材，不编造事实、数据、结论或机构名称。
4. 不要照抄模板中的具体事实、对象、项目名称或数字，除非用户明确要求保留。
5. 尽量保持模板的段落数量、标题层级、列表结构和语气风格。
6. 只输出仿写后的正文，不解释仿写过程。
```

If `reference_material` is empty, the prompt should say "未提供参考素材" or omit that block. The requirement remains mandatory.

## Settings And Diagnostics

Task API key settings add:

```js
{ taskType: "word.smart_imitation", label: "智能仿写" }
```

Route diagnostics include the new task in the current order:

```text
word.smart_write
word.smart_imitation
word.document_review
word.format_review
```

Existing diagnostics continue to apply:

- `/provider/debug-last`
- `/provider/status`
- `/provider/route-diagnostics`
- `/provider/task-api-keys`

User-facing text should keep using "模型后台" rather than "Dify 后台".

## Dify Workflow Documentation

Add:

```text
docs/operations/dify-smart-imitation-workflow.md
```

The document should cover:

- Task type: `word.smart_imitation`
- Suggested API key ref: `word_smart_imitation`
- Required Dify input behavior: use the full `query` as the LLM instruction.
- Response requirement: final answer text only; no explanation; no `<think>` content expected in visible output.
- Recommended model temperature: likely close to Smart Write, but can be slightly higher if more creative imitation is desired.
- Troubleshooting via `/provider/debug-last`.

## Validation And Error Handling

Frontend:

- Missing template: show "请先提供仿写模板。"
- Missing requirement: show "请填写仿写需求。"
- Adapter unavailable: reuse existing adapter connection wording.
- Model backend failure: show existing provider-safe error feedback.

Backend:

- Empty template returns a readable validation error.
- Empty requirement returns a readable validation error.
- Unconfigured provider returns mock/diagnostic behavior consistent with Smart Write.
- Provider answer extraction continues to strip think-tag content.

## Testing Plan

Backend tests:

- `WordDocumentRequest` accepts `imitationRequirement` and `imitationReferenceMaterial`.
- Prompt builder includes template, requirement, reference material, and factuality constraints.
- Provider uses task type `word.smart_imitation`.
- Mock/unconfigured path records task diagnostics for `word.smart_imitation`.
- `/word/smart-imitation` returns `RewriteResponseData` shape.

Frontend/static tests:

- Ribbon includes label "智能仿写".
- `ribbon.js` maps `btnAiSmartImitation` to `smartImitation`.
- `ribbonIconMap` includes `icon-smart-imitation.png`.
- Task API key list includes `word.smart_imitation`.
- Task pane includes Smart Imitation textareas.
- Smart Imitation JS calls `/word/smart-imitation`.
- Smart Imitation hides "对照" and "应用预览".
- Smart Imitation preserves "预览", "纯文本", and "复制".
- Smart Imitation does not call `applyRewrite()` or any writeback function.

Packaging tests:

- Delivery package includes `icon-smart-imitation.png`.
- Delivery package includes `dify-smart-imitation-workflow.md`.
- `config/adapter.example.json` includes `word.smart_imitation`.
- Version strings are consistent.

## Versioning

Recommended next version:

```text
v0.14.0-alpha
AI-WPS-P1-WORD-0.14.0-20260619
```

Reason: this adds a new independent Word workflow, Ribbon entry, backend API route, task type, task-level API key, and Dify workflow documentation.

## Protected Existing Logic

Do not change:

- Existing Smart Write `/word/smart-write` behavior.
- Smart Write comparison highlighting.
- Smart Write writeback behavior.
- Document Review `clientJobId` resumable polling.
- Document Review record preview toggle.
- Format Review recognition and readability behavior.
- Installer preservation of existing API URL and API keys.
- Provider `/chat-messages` payload shape.

Smart Imitation must be additive and isolated.
