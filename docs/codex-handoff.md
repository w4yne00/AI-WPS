# Codex Handoff - AI-WPS

更新时间：2026-07-10

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`codex/smart-format-full-document-preview`

当前版本：`v0.16.0-alpha`

版本规则号：`AI-WPS-P1-WORD-EXCEL-0.16.0-20260710`

当前交付包：`dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz`

## 1. 当前项目状态

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、企业 Dify/大模型 HTTP API 三层架构。

当前版本采用 Word/Excel 宿主分离的两个 WPS JS 插件入口。Word 侧 Ribbon 保留五个入口：

- 智能编写：`POST /word/smart-write`，任务类型 `word.smart_write`。
- 智能仿写：`POST /word/smart-imitation`，任务类型 `word.smart_imitation`。
- 文档审查：`POST /word/document-review`，任务类型 `word.document_review`。
- 格式审查：`POST /word/format-review`，任务类型 `word.format_review`。
- 设置：统一 API URL、统一模型 API Key、四类 Word 工作流配置档案、诊断信息。

Excel 侧 Ribbon 只显示：

- Excel 智能分析：`POST /excel/analysis/jobs` 提交后台任务并轮询状态，兼容保留 `POST /excel/analysis`，任务类型 `excel.analysis`。
- 设置：复用同一 adapter 配置、统一 API URL、统一模型 API Key 和 Excel 智能分析工作流配置档案。

Excel 智能分析首版是只读分析能力：优先读取 Excel 当前选区，无有效选区时回退当前工作表已用范围；前端只提供分析报告预览、汇报段落和复制，不写回单元格，不新增工作表，不生成公式。

## 2. 当前接口与 Dify 入参

adapter 继续使用 Dify 官方 `/chat-messages`。旧工作流默认使用：

```json
{
  "inputs": {
    "query": "完整中文任务提示词..."
  },
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

如果新版 Dify“用户输入”节点拒绝 `inputs.query` 并返回 HTTP 400，adapter 自动重试：

```json
{
  "inputs": {},
  "query": "完整中文任务提示词...",
  "conversation_id": "",
  "response_mode": "blocking",
  "user": "wps-ai-assistant",
  "files": []
}
```

成功输入模式按 API URL、path、任务类型和任务级 API Key 引用在当前 adapter 进程中缓存。认证失败、服务不可达、超时和 HTTP 5xx 不触发格式回退。

所有任务都通过同一 `providerBaseUrl + providerChatPath` 发送。任务级 API Key 只决定认证密钥，不决定 path、payloadStyle 或 outputKey。未配置任务级 key 时回退统一 key。

推荐配置：

```json
{
  "servicePort": 18100,
  "providerName": "企业大模型接口",
  "providerType": "enterprise-dify-chat",
  "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
  "providerApiKeyEnv": "ENTERPRISE_AI_API_KEY",
  "providerChatPath": "/chat-messages",
  "providerMode": "blocking",
  "taskApiKeyRefs": {
    "word.smart_write": "word_smart_write",
    "word.smart_imitation": "word_smart_imitation",
    "word.document_review": "word_document_review",
    "word.format_review": "word_format_review",
    "excel.analysis": "excel_analysis"
  },
  "taskRoutes": {}
}
```

当前关键接口：

```text
GET    /health
GET    /config
GET    /templates
GET    /provider/status
GET    /provider/route-diagnostics
GET    /provider/debug-last
GET    /provider/task-api-keys
GET    /provider/workflow-profiles?taskType={taskType}
POST   /provider/base-url
POST   /provider/api-key
DELETE /provider/api-key
POST   /provider/task-api-key
DELETE /provider/task-api-key/{taskType}
POST   /provider/workflow-profiles
PATCH  /provider/workflow-profiles/{profileId}
POST   /provider/workflow-profiles/{profileId}/api-key
POST   /provider/workflow-profiles/{profileId}/activate
DELETE /provider/workflow-profiles/{profileId}
POST   /word/smart-write
POST   /word/smart-imitation
POST   /word/document-review
POST   /word/document-review/jobs
GET    /word/document-review/jobs/{jobId}
POST   /word/format-review
POST   /excel/analysis
POST   /excel/analysis/jobs
GET    /excel/analysis/jobs/{jobId}
```

## 3. 本版本关键变化

- Word 前台 Ribbon 入口保持“智能编写 / 智能仿写 / 文档审查 / 格式审查 / 设置”。
- Excel 前台 Ribbon 新增独立 `et` 插件入口，只显示“Excel 智能分析 / 设置”，不会显示 Word 专用按钮。
- 安装包现在同时安装 `wps-ai-assistant_1.0.0` 和 `wps-ai-assistant-et_1.0.0`，`publish.xml` 同时包含 `type="wps"` 与 `type="et"`。
- 删除旧 Word 路由和服务文件，只保留当前四条任务 API。
- 智能仿写作为独立新增工作流与智能编写并列：支持从 Word 选中文本自动带入模板，也支持在任务窗口手动粘贴模板；仿写需求必填，参考素材选填；adapter 通过 `/word/smart-imitation` 和 `word.smart_imitation` 调用独立模型后台任务。
- 智能仿写首版只复用智能编写的结果预览、纯文本和复制能力；不显示对照视图，不提供“应用预览”，不写回 Word 正文。
- 智能编写主要面向鼠标框选的一个或几个段落：点击生成后先刷新“正在读取选中文本”状态，再异步执行选区轻量抽取；不再同步扫描全文段落，避免任务窗格在发起 adapter 请求前卡死。
- 智能编写结果预览改为结构感知：普通段落按朴素文本回显并保留换行，避免额外套排版；当原文或模型结果包含标题、列表、序号、表格、加粗等结构时，自动使用安全 Markdown/结构化回显。
- 智能编写结果在进入预览和写回前会先做分段规范化：已存在的换行保持不变；若用户框选连续多个段落但模型返回单行结果，会按原文段落数量和输出句意边界恢复自然段；内联中文序号、章节/条目标题也会自动拆行。
- 智能编写写回选区时按内容结构选择策略：普通段落按原文段落形态做无样式文本替换；结构化内容尝试标题、列表、加粗等格式化写回，宿主不支持时降级为结构化文本。
- 智能编写提示词新增约束：保持待处理原文的段落数量和换行结构；如果原文有多个段落，输出也应保留相近分段；原文已有标题、列表、序号、表格或强调格式时，应尽量保持对应结构和层级；不要额外新增原文没有、用户也未要求的 Markdown 标题、项目符号、编号列表或表格。
- 智能编写设置展示：表达风格、侧重点、篇幅下方说明文字已统一挪入“当前要求”窗格，窗格按内容自动撑开。
- 文档审查复用原技术审查的界面形态：文档类型为技术方案、合同验收文档、测试大纲及细则；不再选择文档模板，不再检查格式合规。
- 文档审查支持选中文本和全文审查，用户可通过框选段落分段规避 Dify 输出长度和模型上下文限制。
- 文档审查点击后先刷新“正在读取文档审查范围”状态，再异步执行限量抽取；最多读取 80 段、每段 800 字、正文 12000 字，框选文本时直接按选中文本拆段，不同步扫描全文。
- 文档审查请求提交后会在 8 秒和 30 秒继续刷新等待模型后台的状态，避免模型后台慢返回时任务窗格看起来无反馈。
- 文档审查 adapter 解析 Dify 返回时新增兜底：非标准 JSON、普通 Markdown 或未包含 `issues` 的 JSON 会保留为 `rawAnswer`，前端显示“原始模型回复”，便于区分 Dify 输出格式问题和前端渲染问题。
- 格式审查固定使用 `technical-file-format-requirements` 模板，不再提供模板下拉，不提供“应用预览”写回。
- 格式审查保留 AI 段落角色识别能力；Dify 不可用或返回不可解析时回退本地规则。
- 2026-05-29 排查格式审查现场报“无法连接 adapter”：根因是 AI 段落角色识别作为可选能力时，Dify 非 JSON、超时或其它 provider 边界异常可能拖住/打断 `/word/format-review`。现已将格式审查 AI 角色识别限制为短预算调用：最多前 40 段、每批 20 段、单次 Dify 请求最多 8 秒；任何 provider 边界异常都会记录摘要并回退本地格式规则，保证前台能返回格式审查结果。
- 2026-05-31 排查格式审查点击后任务窗格卡死且 Dify 无调用记录：根因是前端在发起 `fetch` 前同步扫描 WPS 全文 `Paragraphs`，大文档下会阻塞任务窗格。现已为格式审查增加专用限量抽取：最多读取 80 段、每段 800 字、正文 12000 字；框选文本时直接按选中文本构造段落，不再先扫描全文；点击后先刷新“正在读取格式审查范围”状态，再异步执行抽取和请求。
- 文档审查结果改为按错别字、语言表达、逻辑表达、通畅性、专业性分组展示，每条问题固定展示严重程度、位置、原文片段、问题说明、修改建议和建议改写。
- 格式审查结果改为按页面设置、标题层级、正文格式、段落格式、图表题/注释、其他格式项分组展示，每条问题固定展示段落号、段落角色、当前值、模板要求和建议操作。
- `v0.12.16-alpha` 起，格式审查结果预览改为“审查概览 / 优先处理清单 / 详细问题 / 诊断信息”结构：优先处理清单用表格集中展示段落、问题类型、当前值、模板要求和建议，详细问题按页面设置、标题层级、正文格式、段落格式、图表题/注释、其他格式项分组展开。
- 格式审查预览层尽量中文化显示普通用户会看到的反馈：模板名显示为“技术文件格式及书写要求”，字体标准显示“宋体”，字号标准显示“小四（12pt）”，样式名、对齐、行距、首行缩进、页面设置、识别来源和 AI 兜底原因也转成中文可读表达。
- 设置页新增“最近一次任务诊断”，聚合 `/provider/debug-last`、`/provider/status`、`/provider/route-diagnostics` 和 `/provider/task-api-keys` 的脱敏摘要，并支持一键复制。
- `/provider/debug-last` 增补 `providerName`、`providerType`、`taskApiKeyRef`、`taskAuthSource` 等脱敏字段，便于判断当前任务是否命中对应 Dify 应用密钥。
- adapter 启动包新增麒麟 V10/systemd 开机自启动脚本：`scripts/install_autostart.sh` 安装 `ai-wps-adapter.service`，开机后复用现有 `scripts/start_adapter.sh 18100`；`scripts/uninstall_autostart.sh` 用于停止并移除自启动服务。
- `v0.13.0-alpha` 起，智能编写结果预览新增只读“预览 / 对照 / 纯文本”切换；该切换只影响任务窗格显示，不改变复制文本、`state.rewriteResult` 和“应用预览”写回路径。
- `v0.13.0-alpha` 起，文档审查结果以可处理问题卡片展示；每条问题支持标记“已处理/忽略”、复制修改建议、复制建议改写，并可生成本次审查处理记录。所有状态仅保存在前端任务窗格，不自动修改 Word 正文。
- `v0.13.1-alpha` 起，智能编写“对照”视图会将改动后文字以黄色高亮显示；标题、列表、引用和表格行会尽量保留原 Markdown 结构，只在发生变化的字、词或短句上加高亮，未变化内容不高亮。该能力只影响任务窗格只读对照视图，不改变复制文本和写回逻辑。
- `v0.13.1-alpha` 起，文档审查 provider 超时、不可达或认证失败时，adapter 不再让任务窗格只看到网络错误；`WordDocumentReviewer` 会返回可读兜底结果、`parseFallbackReason` 和 `rawAnswer`，设置页最近一次任务诊断仍保留 provider 脱敏错误摘要。
- `v0.13.1-alpha` 起，文档审查前端结果渲染增加兜底：交互卡片渲染异常时自动退回简洁 Markdown 结果，避免模型后台已返回但任务窗格结果区空白。
- 文档审查提示词新增约束：Dify 只输出本次审查发现的问题列表，不输出前端处理状态、复制动作或处理记录；问题处理状态和审查记录仍完全由 WPS 前端本地生成。
- `v0.13.2-alpha` 起，交付包安装脚本在覆盖新版 adapter-start-kit 前会备份并恢复目标机已有 `config/adapter.json`、`run/provider_api_key` 和 `run/provider_api_keys/`，避免新版本安装清空 API URL、统一 API Key 和任务级 API Key。
- `v0.13.2-alpha` 起，adapter 默认 `timeoutSeconds` 从 30 秒提高到 75 秒；智能编写使用该全局预算，文档审查使用更长的 150 秒 provider 预算，格式审查 AI 段落角色识别从 8 秒提高到 60 秒但仍保留上限，兼顾慢模型响应和格式审查可用性。
- `v0.13.2-alpha` 起，文档审查前台改为提交后台任务并轮询 `/word/document-review/jobs/{jobId}`；adapter 后台继续等待模型后台返回，避免 think 模式或模型性能不足时任务窗格用长连接等待并误报“无法连接后台”。
- `v0.13.2-alpha` 起，任务窗口前台反馈统一使用“模型后台”“模型接口”等说法，不再在用户可见反馈中显示“Dify 后台”等字样；内部 provider 类型和 Dify 配置手册仍保留技术名称。
- `v0.13.2-alpha` 起，adapter 在统一抽取模型答案时会剥离 `<think>...</think>` 深度思考标签内容；智能编写、文档审查和格式审查结果预览只使用最终输出，普通无 think 标签的返回保持原样。
- `v0.13.3-alpha` 起，文档审查长文本 think 模式稳定性增强：provider 等待预算从 150 秒提高到 240 秒；任务窗格轮询后台任务状态时，遇到短暂查询失败会保留 `jobId` 并继续自动重试，避免 100 秒以上长任务因一次状态查询抖动误报 adapter 连接失败。
- `v0.13.4-alpha` 起，格式审查框选文本时优先读取 `Selection/Range` 段落格式，不再只按纯文本构造默认 `0pt/左对齐` 段落；前端会解包 WPS COM 标量返回值并规范化对齐枚举，adapter 侧也会把字号 `0` 视为未读取到字号、把对齐值 `3` 规范化为两端对齐后再判断。
- `v0.13.5-alpha` 起，文档审查慢模型等待进一步增强：provider 等待预算提高到 600 秒；任务窗格状态轮询最多容忍 120 次短暂失败、总等待 30 分钟；最终失败反馈改为“文档审查状态查询多次失败”并引导查看最近一次任务诊断，避免模型仍在处理时被前台误判为连接失败。
- `v0.13.6-alpha` 起，文档审查 think 模式慢响应继续增强：provider 等待预算提高到 1800 秒；任务窗格状态轮询最多容忍 240 次短暂失败、总等待 60 分钟；轮询阶段 adapter 短暂不可达时改为提示“状态查询暂时未连上本地 adapter”，继续等待后台任务，避免慢模型处理被前台解释为连接失败。
- `v0.13.7-alpha` 起，文档审查“预览审查记录”按钮改为双态切换：首次点击显示审查记录预览，再次点击返回初始文档审查结果卡片视图，并保留本地问题处理状态和复制审查记录能力。
- `v0.13.8-alpha` 起，文档审查长任务连接恢复增强：前端提交任务时生成 `clientJobId` 并本地保存未完成任务；adapter 用该任务号做幂等后台 job，状态接口返回运行耗时和 1800 秒 provider 等待预算；任务窗格状态查询使用 10 秒短请求，遇到 180 秒附近连接中断后不丢弃任务号，改为低频恢复查询，重开文档审查任务窗格也会继续查询未完成任务。
- `v0.14.0-alpha` 起，新增独立“智能仿写”工作流：Ribbon 增加入口，任务窗口支持仿写模板、仿写需求、参考素材输入，adapter 新增 `/word/smart-imitation` 和 `word.smart_imitation` 任务级 API Key，并新增智能仿写 Dify 工作流手册。
- `v0.15.0-alpha` 起，新增首个 Excel 工作流“Excel 智能分析”：Excel 使用独立 `et` 插件入口，adapter 新增 `/excel/analysis` 和 `excel.analysis` 任务级 API Key；前端只读读取选区或已用范围，返回“数据概览 / 关键发现 / 风险异常 / 建议动作”和汇报段落，不写回 Excel。
- `v0.15.1-alpha` 起，Excel 智能分析改为与文档审查一致的长任务等待链路：前端生成并持久化 `clientJobId`，通过 `/excel/analysis/jobs` 提交后台任务，使用 10 秒短请求轮询状态，连接抖动时保留任务编号并在 60 分钟恢复预算内持续查询；adapter 的 `excel.analysis` provider 等待预算提高到 1800 秒。
- `v0.15.2-alpha` 起，统一 `/chat-messages` 请求兼容新旧 Dify Chatflow：默认保留旧版 `inputs.query`，若收到 HTTP 400 则使用 `inputs: {}` 和顶层 `query/files` 自动重试一次并缓存成功模式；非 400 错误不重试，业务提示词、超时、结果解析、前端和回写逻辑保持不变。
- `v0.16.0-alpha` 起，五个任务均支持工作流配置档案：每个任务可保存最多 20 个“自定义名称 + API Key + 备注”档案，功能页通过下拉菜单明确切换，设置页支持新增、重命名、单独更换密钥和删除备用档案。
- 旧 `taskApiKeyRefs` 首次读取时自动迁移为名为“当前配置”的档案，复用原密钥文件；激活档案时同步镜像旧映射，旧前端或回退版本仍使用最后一次选择。
- API Key 正文继续只保存在 `run/provider_api_keys/`，新密钥文件权限为 `0600`；档案查询和 `/provider/debug-last` 仅返回档案 ID、名称、密钥引用和配置状态，不返回密钥正文。
- Word 任务窗格只加载四类 Word 档案，Excel 任务窗格只加载 `excel.analysis` 档案；切换只影响下一次新任务，不改变已提交的文档审查或 Excel 后台任务。
- 任务窗口结果区继续区分任务类型：智能编写按内容结构选择朴素或结构化回显，文档审查/格式审查/诊断继续显示安全渲染后的 Markdown 成品；复制和写回仍使用原始模型文本。
- adapter 版本、前端缓存参数、manifest、启动脚本版本统一更新到 `0.16.0-alpha`，确保目标机重新打开 WPS 后加载新工作流档案界面。

## 4. 需要重点保护的既有逻辑

- 智能编写 Dify 调用、任务级 API Key 选路和“不允许原样返回”的提示词约束。
- 智能编写新菜单值和旧值兼容映射：前端只展示新选项，adapter 仍识别旧 payload 值。
- `/chat-messages` 顶层 `query` 必须始终携带完整提示词；旧模式同时携带 `inputs.query`，新版“用户输入”节点模式保持 `inputs: {}`，两种模式不得修改提示词正文。
- 统一 API URL + 统一 API Key + 任务级 API Key 的回退链路。
- `/provider/debug-last` 脱敏诊断，不泄露完整原文和密钥。
- Markdown 安全渲染：HTML 转义，危险链接不可点击，复制仍保留原始文本。
- WPS COM 对象容错：段落集合、选区文本、全文 Range 和宿主对象清洗逻辑不能被审查功能改动破坏。
- 文档审查不能回退为同步全文扫描；`DOCUMENT_REVIEW_EXTRACTION_OPTIONS` 必须保留 `preferSelectionTextParagraphs`、`avoidFullTextRead`、`avoidFallbackTextRead`。
- 文档审查长任务必须继续走 `clientJobId` + `/word/document-review/jobs/{jobId}` 的可恢复轮询链路；前端不要在短暂连接失败后清空 jobId，adapter job store 不要对同一 `clientJobId` 重复发起模型后台任务。
- 文档审查 Dify 非标准返回也要在前台可见：`rawAnswer` 和 `parseFallbackReason` 是现场判断 Dify 输出格式问题的重要兜底。
- 智能编写选区轻量抽取不能回退为同步全文段落扫描；`SMART_WRITE_EXTRACTION_OPTIONS` 必须保留 `preferSelectionTextParagraphs`、`avoidFullTextRead`、`avoidFallbackTextRead`。
- 智能编写结果预览必须保持结构感知：简单段落不要额外套 Markdown 排版；标题、列表、序号、表格、加粗等结构存在时要尽量结构化回显和写回。
- `v0.13.0-alpha` 以来的智能编写结果视图切换不能改动写回功能；`applyRewrite`、`tryApplyFormattedRewrite`、`buildMarkdownWritebackBlocks` 只允许作为既有能力保留，不在本版扩展。
- `v0.13.1-alpha` 的对照高亮只允许作用于只读 comparison Markdown，不允许把 `==...==` 标记传入复制文本或写回正文。
- 智能仿写首版必须保持 preview/copy only：只复用智能编写的预览、纯文本和复制能力，不显示对照，不设置 `pendingApplyAction`，不调用任何 Word 写回路径。
- Excel 智能分析首版必须保持 read-only：不调用任何 Excel 写回、插入公式、新增工作表或修改单元格路径；只允许选区/已用范围读取、预览、纯文本和复制。
- Excel 智能分析长任务必须使用 `clientJobId` + `/excel/analysis/jobs/{jobId}` 的可恢复轮询链路；短暂状态查询失败不得清空任务号，同一 `clientJobId` 不得重复发起模型任务。
- Word/Excel Ribbon 必须保持宿主隔离：Word `type="wps"` 插件不显示 Excel 智能分析；Excel `type="et"` 插件不显示智能编写、智能仿写、文档审查、格式审查。
- 新版本安装脚本必须继续保护目标机运行时配置：不得覆盖 `config/adapter.json`、`run/provider_api_key`、`run/provider_api_keys/` 中的现场 API URL 和 API Key。
- 文档审查闭环只能管理前端处理状态和复制审查记录，不允许自动写回或自动修改正文。
- 本轮格式审查只改前端结果预览渲染和中文展示，不改 `/word/format-review` 接口、模板规则检查、AI 段落角色识别、任务级 API Key 选路和 Dify payload。
- 智能编写和文档审查逻辑不要因格式审查预览优化被改动；对应抽取限制、等待反馈、`rawAnswer` 兜底和写回策略都要保持当前行为。
- uvicorn 优先、standalone 兜底的 adapter 启动方式，以及旧进程版本替换逻辑。

## 5. 当前关键文件

- `adapter_service/app/api/word.py`：当前 Word 四任务路由。
- `adapter_service/app/api/excel.py`：Excel 智能分析路由。
- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、任务级 API Key、脱敏 provider 调试记录、智能编写/智能仿写/文档审查/格式审查 provider 调用。
- `adapter_service/app/services/excel/analyzer.py`：Excel 表格可用性校验和 provider 调用封装。
- `adapter_service/app/services/excel/analysis_jobs.py`：Excel 智能分析幂等后台任务、运行状态和耗时诊断。
- `adapter_service/app/services/word/smart_imitator.py`：智能仿写服务，负责模板抽取、必填校验、provider 调用和 rewrite 形态结果输出。
- `adapter_service/app/services/word/document_reviewer.py`：文档审查服务，负责选区/全文、默认提示词、模型结果解析和问题列表输出。
- `adapter_service/app/services/word/format_reviewer.py`：格式审查服务，负责模板规则检查、可选 AI 段落角色识别和本地兜底。
- `adapter_service/app/core/models.py`：当前请求/响应模型。
- `adapter_service/standalone_adapter.py`：standalone 模式，与 FastAPI 当前输出保持一致。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`、`taskpane.js`、`taskpane.css`、`taskpane-helpers.js`：当前任务窗格、设置页、Markdown 渲染和 WPS 读取逻辑。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`、`ribbon.js`：当前 Ribbon 入口和图标映射。
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/`：Excel 专用插件包，包含 Excel 智能分析 Ribbon、任务窗格、图标和 manifest。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png`：智能仿写 Ribbon 图标。
- `adapter-start-kit/scripts/install_autostart.sh`、`adapter-start-kit/scripts/uninstall_autostart.sh`、`adapter-start-kit/docs/autostart-guide.md`：麒麟 V10 目标机 systemd 开机自启动安装、卸载和运维说明。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages`、四个 Word 任务和一个 Excel 任务的 `taskApiKeyRefs`。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify 配置手册。
- `docs/operations/dify-smart-imitation-workflow.md`：智能仿写 Dify 配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 配置手册。
- `docs/operations/dify-excel-analysis-workflow.md`：Excel 智能分析 Dify 配置手册。
- `docs/superpowers/plans/2026-05-29-review-mode-consolidation-plan.md`：审查入口收敛执行计划。
- `docs/superpowers/plans/2026-05-31-stability-enhancement-plan.md`：本轮稳定增强执行计划。

## 6. 本轮测试命令

已执行：

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/standalone_adapter.py adapter_service/app/api/provider.py adapter_service/app/api/word.py adapter_service/app/api/excel.py adapter_service/app/main.py adapter_service/app/services/workflow_profiles.py adapter_service/app/services/provider_client.py adapter_service/app/services/excel/analyzer.py adapter_service/app/services/excel/analysis_jobs.py adapter_service/app/services/word/smart_imitator.py adapter_service/app/core/models.py
git diff --check
DATE_TAG=20260710 bash packaging/build_phase1_delivery_kit.sh
```

当前结果：

- Python 标准单测：`136 tests OK (skipped=8)`；工作区 bundled Python 缺少 FastAPI，相关接口测试按条件跳过。
- 临时加载仓库离线 FastAPI 轮包后，工作流档案 4 项接口测试全部通过，覆盖 CRUD、激活、当前档案删除保护、重复名称冲突和旧任务密钥接口兼容。
- JS layout smoke：通过，覆盖 `0.16.0-alpha` 缓存参数、Word/Excel Ribbon 与工作流档案宿主隔离、五类档案管理入口、明确切换动作，以及既有 Excel/文档审查长任务、智能编写写回和智能仿写只读契约。
- JS helpers：通过，新增档案响应清洗、按任务过滤、当前档案名称和删除保护状态测试；原智能编写分段/对照、文档审查记录和格式审查中文化测试继续通过。
- `taskpane.js`、`taskpane-helpers.js`、`ribbon.js` 语法检查：通过。
- 420×900 窄任务窗格视觉检查：Word 设置页、Word 智能编写快捷选择器和 Excel 设置页均无控件重叠或宿主串项。
- `git diff --check`：通过。
- 已生成 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260710.tar.gz`，SHA256：`2bdd8d1b651ecb86281f5a77b9ec38de8fb9d417697bdaf33fb2a55e9f04025d`。
- 包内已校验同时包含 Word/Excel 插件、FastAPI/standalone 档案接口、`workflow_profiles.py` 和工作流档案运维手册，且未夹带运行时 `config/adapter.json`。

说明：当前 bundled Python 环境有 Pydantic，但没有 FastAPI；本次通过仓库自带离线轮包临时加载 FastAPI 运行环境执行新增接口测试，没有修改项目依赖。

## 7. 目标机验证建议

1. 关闭并重新打开 WPS，确认设置页“前端版本”为 `0.16.0-alpha`。
2. 设置页配置统一 API URL，例如 `https://aibot.chinasatnet.com.cn/v1`。
3. 分别为“智能编写”“智能仿写”“文档审查”“格式审查”“Excel 智能分析”保存两个具名工作流档案，切换后确认下一次任务命中所选档案。
4. 执行“智能编写”，确认 `/provider/debug-last.taskType=word.smart_write`，模型后台命中智能编写应用。
5. 执行“智能仿写”，可先框选模板段落再打开任务；填写仿写需求和参考素材后确认 `/provider/debug-last.taskType=word.smart_imitation`，结果区只有预览/纯文本/复制，不显示对照和应用预览。
6. 执行“文档审查”，优先框选 3 到 10 个段落联调；确认 `/provider/debug-last.taskType=word.document_review`，结果区显示审查摘要和问题列表。
7. 执行“格式审查”，可框选局部段落；确认结果区显示“审查概览 / 优先处理清单 / 详细问题 / 诊断信息”，字体标准为“宋体”、字号标准为“小四（12pt）”，识别来源显示“AI 辅助 + 本地规则”或“本地规则”。
8. 打开 WPS Excel，确认 Ribbon 下只有“Excel 智能分析”和“设置”；选择一块表格区域后执行分析，确认 `/provider/debug-last.taskType=excel.analysis`，结果区显示数据概览、关键发现、风险异常、建议动作和汇报段落。使用慢模型验证 180 秒以上任务仍持续轮询，不提前提示连接失败。
9. 分别连接旧版 `inputs.query` 工作流和新版“用户输入”节点工作流；新版首次 HTTP 400 后应自动以 `inputs: {}` 重试成功，`/provider/debug-last.inputMode=user-input-node`，后续同任务不再先发送旧格式。
10. 在麒麟 V10 目标机上安装 adapter 开机自启动：进入 adapter 启动包目录后执行 `bash scripts/install_autostart.sh 18100`，重启系统后执行 `bash scripts/status_adapter.sh 18100` 验证 `adapter_health=reachable`。
11. 如果模型后台有调用但 WPS 结果为空，检查回复节点是否绑定 LLM 输出正文，而不是开始节点原始 query。
12. 如果 `provider=mock` 或 `skipReason=provider_not_configured`，检查任务级 API Key 文件是否已保存，以及统一 API URL 是否带 `/v1`。

## 8. 遗留项

- 智能排版暂缓：目标机已确认任务级 API Key 选路可命中独立 Dify 工作流，但长文档角色识别受 Dify 输出最大值和模型上下文窗口限制影响。当前版本不再尝试自动写回排版，改为“格式审查”。
- 文档审查要求 Dify 输出 Markdown 中的 JSON 代码块。若现场 Dify 只能输出普通 Markdown，也应至少保留一个合法 `json` 代码块；adapter 会从代码块中提取问题列表。
- Excel/WPS ET 对象模型仍需在目标机真机验证，尤其是 `Selection`、`UsedRange`、`Cells.Item(row, column)` 的可用性；前端已做多路径读取和已用范围兜底。
- 历史操作文档中仍可能保留旧版本部署背景；当前交付和配置以本 handoff、README、`dify-smart-imitation-workflow.md`、`dify-document-review-workflow.md`、`dify-format-review-workflow.md`、`dify-excel-analysis-workflow.md` 为准。
