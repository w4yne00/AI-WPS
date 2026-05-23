# Template Smart Format Design

更新时间：2026-05-23

## 背景

用户已提供标准模板 `/Users/wayne/Desktop/Workspace/XW_work/技术文件格式及书写要求.docx`。目标是在 WPS 任务窗格中把格式散乱的 Word 文档按该模板自动排版，同时不影响智能编写、技术文档审查、格式校对等既有功能。

当前智能排版只返回段落级 `targetStyle`，WPS 侧只设置 `StyleNameLocal`、字体和字号，无法完整覆盖模板中的页面设置、标题层级、正文缩进、图表题、注、列项、表正文、附录标题等要求。

## 目标

采用“模板规则驱动 + 大模型辅助结构识别 + 本地确定性排版执行 + 预览后应用”的方案：

- 模板规则由上传的 Word 模板抽取并维护在 JSON 中。
- 大模型只辅助判断段落角色，不直接生成 WPS JSAPI 调用。
- adapter 生成可预览的排版变更计划。
- WPS 侧只按变更计划执行格式应用。
- 智能排版使用独立任务级 API Key，其他任务继续兼容统一 API Key。

## 非目标

- 不做静默全文自动覆盖，必须先预览后应用。
- 不在第一版处理自动目录刷新、页眉页脚、复杂图片布局、公式编号、跨页表格细节。
- 不改变智能编写、技术文档审查、格式校对现有接口语义。

## 模板规则

以用户上传模板为准，抽取以下规则：

- 页面：A4，页边距上/下 1440 twips，左/右 1800 twips。
- 正文：宋体、Times New Roman、西文字体，12pt，1.25 倍行距，两端对齐，首行缩进 640 twips。
- 文档标题：黑体，14pt，居中。
- 1-4 级标题：黑体，12pt，1.25 倍行距，按模板缩进和大纲级别。
- 图题/表题：黑体，12pt，居中，单倍行距，段前/段后 50 twips。
- 注：宋体，10.5pt，按有编号/无编号注设置悬挂缩进。
- 列项：按一级/二级、有编号/无编号样式处理。
- 附录标题：附录标题、附录一级标题、附录二级标题、附录三级标题。
- 表正文：宋体，居中，最小行距，首行缩进 0。

## 后端设计

### 配置

保留统一 `providerBaseUrl` 和默认 API Key，同时新增任务级 API Key 引用：

```json
{
  "taskApiKeyRefs": {
    "word.smart_format": "word_smart_format",
    "word.smart_write": "word_smart_write",
    "word.technical_review": "word_technical_review",
    "word.proofread": "word_proofread"
  }
}
```

任务级 key 保存到 `run/provider_api_keys/<ref>`。若任务级 key 未配置，则回退到统一 key，保证既有功能不受影响。

### 接口

现有 `/word/format-preview` 保持入口不变，响应扩展：

- `changes[].targetProperties`：WPS 侧可确定执行的格式属性。
- `changes[].role`：段落角色，如 `heading1`、`body`、`caption`、`note`。
- `changes[].confidence`：角色识别置信度。
- `summary.provider`：`local`、`mock` 或 `enterprise-dify-chat/<source>`。
- `summary.pageSetupChangeCount`：页面设置变更数。

新增配置接口：

- `GET /provider/task-api-keys`
- `POST /provider/task-api-key`
- `DELETE /provider/task-api-key/{taskType}`

### 大模型调用

智能排版任务类型为 `word.smart_format`。请求仍使用 Dify Chat `/chat-messages` 官方字段：

```json
{
  "inputs": {"query": "智能排版结构识别提示词"},
  "query": "智能排版结构识别提示词",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

不复用 `conversation_id`，避免 Dify 忽略新的输入。模型只返回 JSON 角色识别结果；解析失败或未配置 key 时回退本地规则。

## WPS 侧设计

- 任务窗口继续显示“生成排版预览”和“应用预览”。
- 预览展示模板、变更数、识别来源、段落角色和理由。
- 应用时优先使用 `targetProperties` 设置 `StyleNameLocal`、字体、字号、段落对齐、行距、缩进、段前段后、大纲级别、页面边距。
- 如果宿主 JSAPI 不支持某个属性，跳过该属性，不影响其他变更。
- 设置页显示任务级 API Key 配置，智能排版可以独立保存/清除密钥。

## 保护边界

- 智能编写继续使用 `/word/smart-write` 和既有提示词，不改变返回结构。
- 技术文档审查继续使用 `/word/technical-review`。
- 格式校对继续使用本地规则 + 可选 AI typo/proofread，不改已有 UI。
- 统一 key 仍作为默认兜底，任务级 key 仅在配置后覆盖对应任务。

## 测试

- 后端单测覆盖：
  - 上传模板规则下正文、标题、注、图表题、附录的变更计划。
  - 任务级 key 优先于统一 key。
  - 智能排版未配置 task key 时可回退统一 key或本地规则。
  - `/config` 和 provider task key 接口输出。
- 前端 helper/语法测试覆盖：
  - `targetProperties` 应用函数不会破坏缺失属性对象。
  - 排版预览文本包含 provider/role。
- 保持现有智能编写、技术审查、格式校对测试通过。
