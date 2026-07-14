# AI-WPS 三宿主界面统一与 PPT 文档智能总结设计

日期：2026-07-14

状态：已确认

目标版本：`v0.18.0-alpha`

## 1. 背景

当前 Word、Excel、PPT 插件已经实现宿主隔离和统一 adapter 接入，但 PPT 任务窗格仍使用独立视觉样式，顶部显示固定版本号，用户可见名称“PPT 单页助手”也不能覆盖新增的文档总结场景。

本版本统一三宿主视觉系统，并将 PPT 功能升级为“智能总结”。智能总结保留当前页只读总结，同时允许用户上传一个 Markdown 或 DOCX 文件，由现有 `ppt.slide_assistant` 模型工作流解析文档并生成整套 PPT 页面结构、排版和文字建议。用户只在结果区预览和复制，不自动创建或修改幻灯片。

## 2. 已确认决策

- PPT 用户可见名称统一为“智能总结”。
- Excel 用户可见名称统一由“Excel 智能分析”改为“智能分析”。
- Word 保留智能编写、智能仿写、文档审查、格式审查等现有任务名称。
- 三宿主同步统一界面和按钮图标，但 Word、Excel 既有功能布局、业务逻辑、接口、轮询和写回边界保持不变。
- PPT 使用“当前页总结 / 文档总结”分段切换，共享结果预览和复制区域。
- 文档总结复用 `ppt.slide_assistant` 工作流、工作流档案和 API Key。
- 文档通过 Dify 文件上传接口传递给模型后台，不在 adapter 本地提取正文。
- 文件只支持 `.md` 和 `.docx`，每次一个，最大 10 MB。
- 文档总结生成整套 PPT 方案，用户可选择 5、8、10、12 或 15 页，默认 10 页。
- 统一交付包新增 Excel 智能分析和 PPT 智能总结 Markdown 提示词模板。

## 3. 范围与非目标

### 3.1 本版本范围

- 三宿主视觉令牌、标题栏、状态徽标、按钮、输入控件、结果区和设置页统一。
- Word、Excel、PPT Ribbon 图标和用户可见名称同步更新。
- PPT 当前页总结界面更名并接入统一连接状态。
- PPT 文档文件临时上传、Dify 文件上传、后台总结任务、结果预览和复制。
- Dify 工作流配置手册、提示词模板、验收清单、README 和统一安装包同步更新。

### 3.2 非目标

- 不自动新增 PPT 页面。
- 不修改幻灯片文字、形状、版式、主题、动画或备注。
- 不在本地解析 Markdown 或 DOCX 正文。
- 不新增独立 PPT 文档总结工作流或 API Key。
- 不改变 Word、Excel 的任务路由、请求数据、结果数据和业务行为。
- 不引入新的第三方前端或 Python 依赖。

## 4. 三宿主界面设计

### 4.1 统一设计系统

三个插件各自保留独立静态文件，使用相同的 CSS 变量和组件规则，不增加跨插件运行时依赖：

- 中性浅灰背景、白色工具面板、雾蓝主色和绿色/黄色/红色状态色。
- 页面不使用装饰性渐变、光斑或浮动色块。
- 面板和按钮圆角不超过 8px，不在面板内嵌套装饰卡片。
- 标题、字段标签、正文、辅助说明使用一致字号层级。
- 顶部左侧显示“WPS AI 助理”和当前功能名，右侧显示连接状态徽标。
- 状态徽标统一为“检测中 / 已连接 / 未连接”，不显示固定版本号。
- 主操作使用带功能图标的主按钮；上传、复制、刷新、编辑使用统一尺寸的小图标和明确文字。
- 图标使用本地资源，保持现有雾蓝银白线性风格，不引入在线图标库。

### 4.2 宿主名称和隔离

- Word Ribbon 继续只显示 Word 专用功能和设置。
- Excel Ribbon 只显示“智能分析”和“设置”。内部任务键仍为 `excel.analysis`。
- PPT Ribbon 只显示“智能总结”和“设置”。内部任务键仍为 `ppt.slide_assistant`。
- Word、Excel、PPT 的 `type="wps"`、`type="et"`、`type="wpp"` 发布项保持隔离。

### 4.3 设置页

三宿主设置页统一使用以下结构：

1. 当前模型接口摘要和编辑入口。
2. 模型提供商名称、API URL、统一 API Key 编辑区。
3. 当前宿主专用工作流档案管理。
4. 联调状态和前端版本。
5. 最近一次任务诊断、刷新和复制。

Word 和 Excel 保留现有 DOM ID 和事件绑定。样式调整不得改变配置保存、档案切换、密钥保护和诊断脱敏行为。

## 5. PPT 智能总结交互

### 5.1 当前页总结

- 保留当前页主标题、可选副标题、普通正文文本形状和相邻页标题读取。
- 保留自动生成/优化模式、1800 秒 provider 预算和可恢复轮询。
- 结果继续提供预览、纯文本、复制标题、复制要点、复制结论和复制完整结果。
- 主标题与可选副标题继续分开识别，副标题不得混入普通正文。

### 5.2 文档总结

用户切换到“文档总结”后显示：

- 文件选择区：仅接受 `.md`、`.docx`。
- 已选文件摘要：文件名、类型和大小只在前端显示。
- 建议页数：5、8、10、12、15，默认 10。
- 补充要求：最多 1000 字，用于说明汇报对象、重点、语气或视觉偏好。
- 主按钮：“开始总结”。

切换模式不清空已经完成的结果。正在运行的任务不能重复提交；切换工作流档案只影响下一次任务。

## 6. adapter 文件上传设计

### 6.1 本地文件入口

新增：

```text
POST /ppt/document-files
```

前端使用原生 `FileReader` 读取文件并发送 JSON：

```json
{
  "fileName": "项目报告.md",
  "mimeType": "text/markdown",
  "sizeBytes": 13,
  "contentBase64": "IyBQUFQgc291cmNlCg=="
}
```

成功响应只返回一次性引用：

```json
{
  "success": true,
  "data": {
    "fileToken": "随机不可预测令牌",
    "extension": "md",
    "sizeBytes": 13,
    "expiresInSeconds": 1800
  }
}
```

adapter 必须执行以下校验：

- Base64 解码后的实际大小必须与声明一致，且范围为 1 字节至 10 MB。
- Markdown 必须是 UTF-8 文本，可接受 UTF-8 BOM。
- DOCX 必须是有效 ZIP，并包含 `[Content_Types].xml` 和 `word/document.xml`。
- 文件名只用于扩展名校验，不写入诊断和普通日志。

临时目录位于操作系统临时目录下的 `ai-wps-adapter/ppt-document-files`。目录权限为 `0700`，文件权限为 `0600`。令牌 30 分钟过期；上传模型后台成功、任务失败或过期扫描时删除文件。

### 6.2 后台任务请求

现有 `POST /ppt/slide-assistant/jobs` 扩展为判别式请求：

```json
{
  "sourceMode": "document",
  "fileToken": "一次性令牌",
  "requestedSlideCount": 10,
  "userInstruction": "面向管理层，突出风险和下一步安排",
  "clientJobId": "client-ppt-summary-m6w9q2-ab12cd34"
}
```

`sourceMode=slide` 时继续使用现有 `slide` 数据结构。`sourceMode=document` 时不要求 `slide`，但必须包含有效 `fileToken` 和允许的页数。

同一 `clientJobId` 保持幂等，不重复上传文件或发起模型任务。任务状态继续通过：

```text
GET /ppt/slide-assistant/jobs/{jobId}
```

轮询状态增加阶段性 `runningMessage`：本地文件已接收、正在上传模型后台、模型后台正在解析文档、正在生成 PPT 建议。

### 6.3 Dify 文件调用

adapter 使用当前 `ppt.slide_assistant` 工作流档案解析出的同一 API Key：

1. 向 `providerBaseUrl + /files/upload` 发送 `multipart/form-data`。
2. `user` 固定与消息请求一致，继续使用 `wps-ai-assistant`。
3. 获取 `upload_file_id` 后，在 `/chat-messages` 中发送：

```json
{
  "files": [
    {
      "type": "document",
      "transfer_method": "local_file",
      "upload_file_id": "Dify 文件 ID"
    }
  ]
}
```

旧版请求继续携带 `inputs.query`，新版用户输入模式继续使用 `inputs: {}` 和顶层 `query/files`。HTTP 400 输入模式回退和成功模式缓存规则保持不变，两个模式都必须保留相同文件引用。

multipart 编码使用 Python 标准库实现，不增加 `python-multipart` 或其它依赖。API Key 只保存在 adapter 侧。

## 7. 模型输出和结果预览

### 7.1 当前页结果

保留现有结构：

- `suggestedTitle`
- `bullets`
- `conclusion`
- `plainText`
- `rawAnswer`
- `parseFallbackReason`

### 7.2 文档结果

文档总结返回：

```json
{
  "resultType": "document",
  "deckTitle": "建议的整套 PPT 标题",
  "documentSummary": "原文核心摘要",
  "recommendedSlideCount": 10,
  "slides": [
    {
      "index": 1,
      "role": "封面/目录/背景/进展/风险/计划/结论等",
      "title": "主标题",
      "subtitle": "可选副标题",
      "bullets": ["2 至 5 条页面文字"],
      "conclusion": "可选结论句",
      "layoutSuggestion": "页面版式建议",
      "visualSuggestion": "图表或视觉建议"
    }
  ],
  "globalStyleAdvice": "整套 PPT 字体、色彩、图表和内容密度建议",
  "plainText": "可完整复制的纯文本"
}
```

前端先显示文档摘要、建议页数和整体风格，再用带分隔线的逐页清单展示内容。每页提供“复制标题”“复制正文”“复制本页”，顶部提供“复制大纲”和“复制完整方案”。不使用卡片嵌套。

模型返回非标准 JSON 或普通 Markdown 时，保留 `rawAnswer` 和 `parseFallbackReason`，显示原始回复并启用“复制完整结果”。统一答案抽取继续移除 `<think>...</think>`。

## 8. 提示词与 Dify 工作流

同一 `ppt.slide_assistant` 工作流根据 `userinput.files` 是否存在区分：

- 无文件：处理 adapter 在 `query` 中提供的当前页上下文。
- 有文件：文档文件先进入 Dify 文档提取节点，提取文本后与 `query` 中的页数和补充要求一起进入 LLM。

统一交付包新增：

```text
docs/prompt-templates/excel-smart-analysis-prompt-template.md
docs/prompt-templates/ppt-smart-summary-prompt-template.md
```

两个模板均包含适用任务、Dify 输入变量、可复制 System Prompt、输出契约、think 过滤要求、`max token` 控制、错误输出和禁止事项，不包含真实 API URL、API Key 或现场文档。

Excel 模板强调只读分析、异常发现、建议动作和汇报段落。PPT 模板同时覆盖当前页与文档模式，并固定整套 PPT 逐页输出结构。

## 9. 错误处理与安全

- 不支持扩展名：前端提示“不支持该文件类型”。
- 超过 10 MB：前端直接拦截，adapter 再做同样校验。
- DOCX 损坏或伪装扩展名：adapter 返回文件格式错误。
- 文件令牌过期或 adapter 重启后丢失：提示重新选择文件。
- Dify 文件上传失败：区分认证失败、HTTP 400、超时和服务不可达。
- 工作流未启用文件输入或文档提取节点：提示检查 `userinput.files` 和文档提取节点。
- 状态查询短暂失败：保留 `jobId` 并继续恢复轮询，不重复提交文件或模型任务。
- 日志和 `/provider/debug-last` 不记录文件正文、Base64、完整文件名或 API Key，只记录任务类型、扩展名、大小区间、阶段和脱敏错误。
- 任意失败都不得调用 PPT 写接口。

## 10. 测试与验收

### 10.1 Python

- 文件扩展名、大小、Base64、Markdown 编码和 DOCX 结构校验。
- 临时目录权限、文件权限、一次性令牌、过期和失败清理。
- Dify multipart 文件上传、同一任务密钥和同一 user。
- `files` 在旧版和新版 Chatflow 请求中的一致性。
- 文档任务幂等、阶段状态、1800 秒 provider 预算和错误脱敏。
- FastAPI 与 standalone 接口/结果一致。

### 10.2 JavaScript

- 当前页/文档分段切换。
- `.md/.docx`、10 MB、页数和补充要求校验。
- 文件上传、任务提交、轮询恢复和过期文件提示。
- 当前页结果、文档逐页结果、原始回复兜底和所有复制动作。
- PPT 代码不得出现幻灯片或形状写入调用。

### 10.3 布局与回归

- Word、Excel、PPT 的标题、连接徽标、按钮图标、设置页和诊断区一致。
- Excel 所有用户可见入口使用“智能分析”，PPT 使用“智能总结”。
- 三宿主 Ribbon 和工作流档案继续隔离。
- Word/Excel 原有关键 DOM ID、API、长任务和写回契约保持不变。
- 三宿主均进行 420x900 任务窗格截图和重叠检查。
- 完整 Python、JS helper、layout smoke、语法和 shell 打包测试通过。

## 11. 交付与升级

- 版本升级为 `v0.18.0-alpha`。
- 仍只生成一个 Word/Excel/PPT 统一正式交付包和一个安装脚本。
- 安装脚本继续保护目标机已有 `config/adapter.json`、统一 API Key 和 `run/provider_api_keys/`。
- 交付包包含两个提示词模板、更新后的 Dify PPT 工作流手册和验收清单。
- 目标机重点验证 DOCX/Markdown 上传、慢模型 180 秒以上任务恢复、主副标题识别、三宿主视觉一致性和覆盖安装配置保留。

## 12. 重点保护逻辑

- 智能编写结构化预览、对照高亮和既有写回路径。
- 智能仿写 preview/copy only 边界。
- 文档审查和 Excel 智能分析的 `clientJobId` 可恢复长任务。
- 格式审查本地规则和 AI 角色识别回退。
- `/chat-messages` 新旧 Dify 输入模式兼容和 think 标签过滤。
- 工作流档案密钥优先级、旧配置迁移和安装升级配置保护。
- Word、Excel、PPT 宿主隔离。
- PPT 所有功能只读，不新增任何写回能力。
