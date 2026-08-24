# Codex Handoff - AI-WPS

更新时间：2026-08-24

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`codex/readme-zh-sync`

当前版本：`v0.25.1-alpha`

版本规则号：`AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824`

当前唯一自动化候选为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-f953c58312c8d3d42d3dccea402fccf55a3c7d53`，源码提交为 `f953c58312c8d3d42d3dccea402fccf55a3c7d53`，归档为 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz`，SHA-256 为 `833e71fcf5a6e2172c93e44cc3502d46e1ea89c5dc4abb77f658ac8c5ee77ee7`，状态为 `candidate`。其 supersedes 的 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-afe109c27bf6bc9e663a0c107ccfd70876f95655` 已登记为 `rejected`；源码提交为 `afe109c27bf6bc9e663a0c107ccfd70876f95655`，归档 SHA-256 为 `e3d4da0d1d8e1edc619d2101f45afb104ef8e3a6e5197e4b8e59b46513f78c6b`，拒绝原因是目标机验收审计/测试在缺失必测第 8 或第 9 行时未 fail closed，归档保持不可变。`799adf9`、`5318d4b`、`2e7a3e6`、`ccad09f` 及更早候选均保持 `rejected`，不改变历史归档。Issue #59 的目标 WPS GUI、真实模型和人工文档验收仍为 `manual-pending`，不得写为 `passed` 或 `accepted`。

历史候选 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-ccad09f-v0251.tar.gz`（SHA-256：`2c3f8b5004c40fb7271a6afe7e4c8a292acb227b9d3ec08afc7f6b561d413a02`，源码提交：`ccad09fb1d8019da3a40f14610ab3bd75de1ec23`）已确认存在 `word.format_review.snapshot.v2` JS/Python structure/format 哈希契约漂移，登记为 `rejected`，不得继续分发。`e43dc8c` 及更早候选均为 `rejected`。修复报告见 `.superpowers/sdd/2026-08-24-v0251-format-review-hash-contract-fix/task-1-report.md`。

## 当前候选状态：跨运行时格式审查哈希契约

- JavaScript 上传前与 Python Adapter 信任边界现在按同一固定投影、UTF-16 字符计数、紧凑稳定 JSON 和 UTF-8 SHA-256 计算；Python 继续独立重算四项指标并 fail closed。
- 新增真实 Node→Python 子进程对拍测试，覆盖正文/标题、递归表格与 cell format、图片元数据、空/非空 insufficient reason、WPS 大纲级别及 `😀/🚀/𠮷`；structure/format 篡改均要求 409 且不启动 reviewer/provider。
- `20260824-f953c58` 是 `packaging/v0251-candidate-status.json` 中唯一 `candidate`；`20260824-ccad09f`、`20260824-2e7a3e6`、`20260824-5318d4b`、`20260824-799adf9` 与 `20260824-afe109c` 均登记为 `rejected`，不替代 Issue #59 目标机验收。

## 0.1 v0.25.1-alpha 已实现能力

- Issue #35 已形成默认关闭的 Word 全篇审查单分片最小闭环，开关为 `AI_WPS_ENABLE_FULL_DOCUMENT_REVIEW=1`。关闭时 WPS 隐藏入口，全部新协议端点返回 `FULL_DOCUMENT_REVIEW_DISABLED`，且不会创建暂存目录；现有限量审查接口不变。
- Issue #43、#67 已形成默认启用的确定性格式审查后台闭环；`AI_WPS_ENABLE_DETERMINISTIC_FORMAT_REVIEW=0` 仅作为运维止损开关。关闭时快照/任务协议返回 `DETERMINISTIC_FORMAT_REVIEW_DISABLED`，且不会创建暂存目录；旧同步 `/word/format-review` 仅保留明确的 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED` 退役响应。
- 首个闭环只读抽取不超过 20,000 审查字符的普通正文段落，执行两遍内容哈希确认；表格内段落、页眉页脚、脚注尾注、批注修订、文本框、形状、图片、公式、图表、附件和隐藏文本均明确列为未审查区域，不写回 Word。
- 全篇审查复用 `word.document_review` 模型配置，但仅模型直连、显式上下文容量和至少 2,048 输出 Token 的配置可启动；设置页分别披露限量审查和全篇审查就绪度。
- 全篇审查使用独立的快照、批次、提交、任务、状态、运行中协作取消和报告协议，以及版本化分片、纠正和跨片汇总 System Prompt 与严格 JSON Schema。多分片按约 18,000 字符目标、20,000 硬上限和 800 字符上下文重叠执行，标题/段落/句子/字符优先；大型表格按行、单元格、句子和字符递归拆分，重复表头仅作为 overlap 上下文。每个分片输出摘要、受控事实、跨片核对项和问题索引；两个及以上分片再调用只接收压缩索引的全局汇总，并拒绝未知问题、事实或锚点引用。请求体按实际接收字节限制为 2 MB，快照只能原子提交一次；暂存目录在启动时无条件扫描，并由后台维护线程周期清理。格式错误固定纠正一次，再次失败则任务失败，不以原始文本或限量结果降级。
- 报告固定披露快照哈希、审查字符数、覆盖范围、排除区域和枚举状态，并声明覆盖完整不等于承诺检出全部问题。该闭环尚未完成麒麟 V10/WPS 真机验收，不能替代 Issue #59 的独立目标机验收。

## 0.3 Issue #39 已实现的全篇审查恢复与生命周期

- 每个已完成分片都写入带序号、分片 ID、快照内容哈希和结构哈希的本地检查点；Adapter 重启时只在模型配置、API Key 引用及不可逆指纹、System Prompt 元数据和分片策略一致时恢复，继续未完成分片，不重复已完成的模型调用。
- 可恢复失败任务保留两小时，最终结构化报告保留二十四小时；完成、取消、不可恢复失败和主动删除会立即清理全文、分片文本、受控事实和模型中间响应。启动及周期清理会删除过期或校验失败的持久化任务。
- 持久化任务目录使用 `0700`、文件使用 `0600`，任务记录不保存 API Key 明文；原子写入、记录哈希、检查点哈希和双重快照校验用于拒绝损坏或被篡改的恢复数据。相同活跃任务身份会复用原任务号。
- 该能力已通过全篇审查协议测试和仓库 Python 回归；当前开发机缺少 FastAPI/Pydantic 的部分 API 测试依赖，因此对应测试仍按现有测试发现规则跳过，麒麟 V10/WPS 真机验收仍待执行。

## 0.2 Issue #36 当前实现事实

- 全篇审查快照协议已扩展为正文、标题、列表及结构化正文表格，保留表格行列、合并跨度、单元格和嵌套表格关系；首版未覆盖区域仍由报告固定披露。
- WPS 首遍按约 3,500 审查字符自适应分批并在批次间让出任务窗格线程，第二遍重新抽取正文与表格结构摘要，提交前比较完整哈希、字符数、块数、表格/单元格统计和编辑信号；两遍或提交指标不一致时删除暂存。
- Adapter 上传会话使用至少 256 位随机令牌的哈希、连续批次、批次幂等编号、原文范围、字符数和内容哈希校验；暂存默认十分钟清理，大型快照确认最多保留三十分钟。
- 审查字符数分为不超过 20,000、20,001–60,000、60,001–120,000 和超过 120,000 四档；大型快照在模型调用前要求确认字符数、初始分片估算和调用上限，超过 120,000 直接拒绝。
- 以上是源码和自动化契约实现状态，不替代麒麟 V10、WPS 12.1.2 的两遍抽取性能、取消/编辑响应和结构化表格真机验收。

## 0. v0.23.1-alpha 当前事实

- Issue #34 已修复 Word、Excel、PPT 前台模型选择器反复操作后间歇性卡死的问题：渲染时复用稳定的 `option` 节点，模型激活延迟到当前下拉交互结束后执行，并合并连续选择为最后一次操作；三宿主均有节点复用和快速切换回归测试，麒麟 V10/WPS WebView 现场验收仍待执行。
- Issue #33 已把交付构建改为源白名单组装：仅复制明确允许的安装器、三宿主插件、Adapter 生产模块、目标 Python 3.8 ARM Wheel、清单、运维/验收脚本、必要文档和许可证材料；测试、缓存、standalone、开发生成工具、现场配置与旧依赖安装残留不进入产物。
- 构建生成 `release-allowlist.json` 与 `release-file-hashes.json`，并执行精确文件集合、版本一致性、发布清单/插件/System Prompt/Wheel 引用闭包、敏感值和目标依赖哈希审计。归档外 `.sha256` 继续覆盖包含文件哈希清单在内的最终 tar 包。
- 新增唯一的 `python38_delivery_lifecycle_gate.py` 候选门禁入口：从最终 tar 包复验审计，调用真实 Python 3.8 导入/Uvicorn 门禁，并覆盖全新安装、v0.22 升级、损坏 v0.23.0、核心/规范数据故障、导入/启动/版本故障、权限错误、WPS 未退出和安装中断恢复。门禁终态固定为 `candidate`，不宣称目标机恢复。
- Issue #32 已实现恢复候选的显式激活门禁：候选只达到 `recovery` 时，默认安装在切换前停止，并保留当前安装、候选目录、候选状态副本和已完整复制校验的安装前快照；只有当前安装不就绪、备份已校验且候选存活并明确处于恢复模式时，`--activate-recovery` 才能继续。
- 恢复激活事务使用独立终态 `recovery_activated`，不写入 `committedAt`，也不输出普通安装成功标记。恢复模式只开放重新检测、只读备份与脱敏诊断，不开放前端重置或一键恢复。
- FastAPI 与 standalone 新增 `POST /recovery/backups` 和 `GET /recovery/diagnostics`。诊断只输出健康子系统、操作策略、备份摘要和受控审计字段，不包含配置内容、文档正文、API Key、模型原始响应、异常原文或敏感绝对路径。
- 快照清单新增 `copyVerified`：完整复制校验与业务有效性分开记录。整体恢复仍要求有效快照 ID 和 `RESTORE_WHOLE_STATE` 二次确认，并在全文件复验后原子切换；三宿主只显示最近有效/已校验备份状态。
- Issue #29 已实现旧布局运行数据的写时复制迁移和一致性快照：安装器先停止旧 Adapter 并确认端口释放；快照对配置、Key、数据库及 WAL/SHM 做前后稳定性校验，只在同文件系统副本上迁移，并以 Linux/macOS 原生目录交换整体切换。核心失败保持正式状态不变并返回 `recovery`，仅写作规范失败保留原数据库字节并返回 `degraded`。
- 快照清单记录版本、八类任务配置数量、Key 引用/不可逆 SHA-256 指纹、激活关系、规范条目数量/启用状态、数据库完整性和文件校验值，不记录 Key 明文或服务地址正文；状态、快照目录为 `0700`，文件为 `0600`。
- 运行数据恢复只支持带快照 ID 和 `RESTORE_WHOLE_STATE` 二次确认的整体恢复；恢复前再创建 `pre_restore` 快照。默认保留最近三个有效快照，并保护标记为上一已验收版本最后有效快照的快照。
- Issue #28 已将健康契约拆为 `/health/live`、`/health/ready` 和兼容聚合 `/health`：存活检查不读取业务数据；核心配置与任务路由可用时业务就绪，写作规范单项失败为 `degraded`，核心数据失败为 `recovery`。
- 聚合健康在三种状态下均返回 HTTP 200；业务就绪接口在 `recovery` 返回 503。子系统仅披露稳定错误码、阶段和允许动作，不返回配置正文、API Key、异常原文或敏感绝对路径。
- `degraded` 状态下 Word 核心任务继续并沿用既有 `writingPolicyUsage`/审查提示，写作规范管理只读；`recovery` 状态下 Adapter 仍可连接，但配置变更和新模型任务由 FastAPI、standalone 与三宿主共同阻止。
- Word、Excel、PPT 设置页分别显示“已连接”“增强降级”“恢复模式”或“未连接”，恢复模式不会继续读取模型配置，从而避免把核心数据故障误报为网络断开或显示敏感异常。
- Issue #27 已建立兼容旧布局的运行路径契约：显式 `AI_WPS_STATE_DIR` 保存配置、API Key 与写作规范数据库，`AI_WPS_BACKUP_DIR` 预留一致性快照，`AI_WPS_VAR_DIR` 隔离日志、PID 与事务记录；仅配置状态目录时自动使用同级 `backups/` 和 `var/`，三项均未配置时继续使用旧 `config/`、`run/`、`logs/`。
- 三个运行路径环境变量必须是无控制字符的绝对路径（空格受支持，`~` 不自动展开）；systemd unit 会引用并转义路径，API Key 通过 `0600` 临时文件原子替换，避免首次创建的权限窗口。
- Adapter 配置、模型配置、兼容工作流配置、统一/任务 Key 和写作规范库均遵循共享状态路径；Key 文件保持 `0600`、Key 目录保持 `0700`。启动、停止、状态、日志和 systemd 自启动脚本共享同一路径解析，避免管理命令读写不同 PID 或日志位置。
- Python 3.8 最终包门禁会同时验证发布程序目录不产生配置、Key、数据库、日志、PID 或事务记录，且运行状态、备份和 `var/{logs,run,transactions}` 边界成立。本次 Issue #32 本地验证为 Python `656 tests OK / 66 skipped`、正式插件 Node 契约测试 `15/15`、三宿主 JavaScript 与全部 Shell 语法检查通过、Python 3.8 静态兼容扫描 `111` 个生产文件通过。当前 Mac 没有真实 Python 3.8，完整打包已执行到运行时门禁并按预期以 `PYTHON38_REQUIRED current=3.9` 停止；合并或交付前仍须用真实 Python 3.8 重跑最终包 Uvicorn 门禁。
- 修复 `WorkflowProfileCompatibilityStore._platform_configurations` 在 Python 3.8 导入时执行 `tuple[...]` 导致 Adapter 退出的问题，改用 `typing.Tuple/Dict/List`。
- 新增生产 Python 兼容性扫描和最终 tar 包运行门禁；门禁必须由真实 Python 3.8 完整导入应用、启动 Uvicorn，并检查版本、Provider 状态、模型配置和写作规范摘要接口。
- 自动化门禁通过只代表候选构建，不能替代麒麟 V10、目标 WPS 和 `cloud` 用户现场验收。
- 本次兼容修复不改变八类任务模型配置迁移、API Key 引用、写作规范或业务任务行为。

`v0.23.0-alpha` 的既有双模型接入与任务行为继续作为恢复候选基线：

- 八类任务统一使用按任务隔离的“模型配置”，支持“工作流平台”与“模型直连”两种接入方式；运行时不再回退统一 URL 或统一 Key。
- 工作流平台使用类 Dify `/chat-messages`，继续兼容旧 `inputs.query` 与新版顶层 `query/files`；模型直连使用 OpenAI 兼容 `/chat/completions`。
- 原工作流档案原位迁移为 `workflow_platform` 配置并复用原密钥引用。新前端使用 `/provider/model-configurations`；旧 `/provider/workflow-profiles` 仅保留一个版本的兼容包装。
- 每个配置独立保存服务地址、API Key 和接入参数。切换接入方式必须清空不兼容参数和 Key；配置完整性由地址、Key 及直连模型标识共同决定。
- 模型直连使用 `adapter_service/system_prompts/` 中八份版本化 Markdown System Prompt；清单记录 SHA-256，交付构建验证文件和任务集合。
- 智能编写和智能仿写已改为可恢复后台任务，前端通过 10 秒短请求提交/轮询，Provider 等待预算为 600 秒；文档审查、Excel 和 PPT 既有长任务机制保持不变。
- 共享协调器仍为 2 个运行槽位、8 个排队位置；智能编写/仿写为交互优先级，连续 3 个交互任务后必须给普通长任务一次调度机会。
- 生产环境默认禁止 mock 结果，仅设置 `AI_WPS_ENABLE_MOCK_PROVIDER=1` 时允许开发模拟。
- 三宿主设置页使用紧凑下钻模型配置编辑器，任务页下拉只显示完整配置；Word 结果与回写、Excel/PPT 只读边界不变。
- 本地验证结果：Python `584 tests OK / 59 skipped`，真实 Python 3.8 最终包运行门禁通过，正式插件 Node 契约测试 `14/14`，三宿主 JavaScript 检查通过；当前开发机未安装 `wps-addon` 开发依赖，未重复执行该脚手架的 TypeScript 检查；麒麟 V10/WPS 真机验收仍待执行。

## 1. 当前项目状态

AI-WPS 是面向公司内网办公终端的 WPS AI 助理插件。目标环境是麒麟 V10 ARM、WPS 12.1.2、Python 3.8、离线内网部署。系统采用 WPS 原生 JS/HTML 插件、本地 Python adapter、工作流平台或 OpenAI 兼容模型 HTTP API 三层架构。

当前版本采用 Word/Excel/PPT 宿主分离的三个 WPS JS 插件入口。Word 侧 Ribbon 保留五个入口：

- 智能编写：`POST /word/smart-write/jobs`，任务类型 `word.smart_write`。
- 智能仿写：`POST /word/smart-imitation/jobs`，任务类型 `word.smart_imitation`。
- 文档审查：`POST /word/document-review`，任务类型 `word.document_review`。
- 格式审查：先 `POST /word/format-review/snapshots` 创建 v2 快照，再 `POST /word/format-review/jobs` 提交后台任务，任务类型 `word.format_review.deterministic`。
- 设置：四类 Word 模型配置和诊断信息；任务窗格不显示统一 URL 或统一 API Key 编辑器。

Excel 侧 Ribbon 只显示：

- 智能分析：`POST /excel/analysis/jobs` 提交后台任务并轮询状态，兼容保留 `POST /excel/analysis`，任务类型 `excel.analysis`。
- 公式助手：`POST /excel/formula-assistant/jobs` 提交后台任务并轮询状态，任务类型 `excel.formula_assistant`；用户明确选择“生成公式 / 解释排错”，最多读取 30 行、20 列，返回一个主公式和仅在确有差异时折叠显示的一个备选公式。
- 设置：智能分析与公式助手分别使用独立模型配置和 API Key。

智能分析是只读分析能力：优先读取 Excel 当前选区，无有效选区时回退当前工作表已用范围；前端只提供分析报告预览、汇报段落和复制，不写回单元格，不新增工作表，不生成公式。

公式助手同样只读，但不会回退 `UsedRange`。它采集选区地址、表头、显示文本、有限值类型、已有公式和截断状态；解释模式返回原公式、组件说明、引用范围、发现问题和有依据的修正公式。本地只做不执行的基础语法、引用与兼容风险检查，不设置 `Formula`、不试算、不填充范围、不新建工作表、不修改计算模式，也不提供伪造的写回撤销。

PPT 侧 Ribbon 只显示：

- 智能总结：通过“当前页总结 / 文档总结”切换模式，`POST /ppt/slide-assistant/jobs` 提交后台任务并轮询状态，任务类型 `ppt.slide_assistant`。
- 结构审查：`POST /ppt/structure-review/jobs` 提交最多 60 页的只读结构审查任务，任务类型 `ppt.structure_review`。
- 设置：智能总结与结构审查分别使用独立模型配置和 API Key。

当前页总结读取当前页主标题、可选副标题、普通文本形状以及前后页标题；正文充分时自动优化，正文不足时按用户要求生成。文档总结接受单个 UTF-8 `.md` 或有效 `.docx` 文件，大小不超过 10 MB，用户可选择整套 5、8、10、12、15 页建议，默认 10 页。两种模式共用同一个 `ppt.slide_assistant` 工作流档案，结果只提供预览、纯文本和分类复制，绝不创建、修改或写回幻灯片。

结构审查按用户明确页段读取页码、主标题和可选副标题；无标题页才允许读取最多 120 字符正文，单次最多 10 页。整套超过 60 页时前端和 adapter 均先拒绝，不截断也不拆分模型调用。adapter 先执行空标题、完全重复标题、长标题和明显编号跳号检查，再与一次模型语义审查合并去重；结果显示整体主线、推断章节、分级问题、逐页建议和推荐目录，不显示数值总分，只允许复制结论和目录，绝不创建、删除、重排或修改幻灯片。

## 2. 当前模型接入

模型直连接入使用配置服务地址拼接 `/chat/completions`，发送任务 System Prompt 与用户内容；默认上下文容量为 40000，提交前执行预算检查。PPT 文档总结在直连模式由 Adapter 本地解析 Markdown/DOCX，不上传文件。

以下 Dify 入参仅适用于“工作流平台”接入方式：

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

工作流平台配置按自身 `serviceBaseUrl + /chat-messages` 发送；模型直连配置按自身 `serviceBaseUrl + /chat/completions` 发送。每个任务只使用当前激活配置的参数和 API Key，不跨配置、不跨任务，也不回退统一 URL 或统一 Key。

文档总结先由 adapter 使用当前 `ppt.slide_assistant` 档案解析出的同一 API Key 调用 `providerBaseUrl + /files/upload`，取得 `upload_file_id` 后再调用 `/chat-messages`。旧版 `inputs.query` 和新版 `inputs: {}` 两种消息格式都必须携带同一个顶层 `files` 引用；一次任务使用同一份认证快照，切换档案只影响下一次新任务。

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
    "excel.analysis": "excel_analysis",
    "excel.formula_assistant": "excel_formula_assistant",
    "ppt.slide_assistant": "ppt_slide_assistant",
    "ppt.structure_review": "ppt_structure_review"
  },
  "taskRoutes": {}
}
```

当前关键接口：

```text
GET    /health/live
GET    /health/ready
GET    /health
POST   /recovery/backups
GET    /recovery/diagnostics
GET    /config
GET    /config/image-semantics
PUT    /config/image-semantics
GET    /templates
GET    /provider/status
GET    /provider/route-diagnostics
GET    /provider/debug-last
GET    /provider/task-api-keys
GET    /provider/model-configurations?taskType={taskType}
POST   /provider/model-configurations
PATCH  /provider/model-configurations/{configurationId}
DELETE /provider/model-configurations/{configurationId}
POST   /provider/model-configurations/{configurationId}/api-key
POST   /provider/model-configurations/{configurationId}/activate
POST   /provider/model-configurations/{configurationId}/copy
POST   /provider/model-configurations/{configurationId}/validate
POST   /provider/model-configurations/{configurationId}/image-authorization
POST   /provider/base-url
POST   /provider/api-key
DELETE /provider/api-key
POST   /provider/task-api-key
DELETE /provider/task-api-key/{taskType}
GET    /provider/workflow-profiles?taskType={taskType}  # 一版本兼容包装
GET    /writing-policies/summary
GET    /writing-policies/packs
GET    /writing-policies/items
POST   /writing-policies/items
PATCH  /writing-policies/items/{itemId}
DELETE /writing-policies/items/{itemId}
PUT    /writing-policies/preset-overrides/{presetEntryId}
DELETE /writing-policies/preset-overrides/{presetEntryId}
GET    /writing-policies/import-template.csv
GET    /writing-policies/import-template.xlsx
POST   /writing-policies/imports/preview
POST   /writing-policies/imports/apply
GET    /writing-policies/export.csv
GET    /writing-policies/export.xlsx
GET    /writing-policies/backup
GET    /writing-policies/diagnostics
POST   /word/smart-write
POST   /word/smart-imitation
POST   /word/smart-write/jobs
GET    /word/smart-write/jobs/{jobId}[?resume=1]
DELETE /word/smart-write/jobs/{jobId}[?resume=1]
POST   /word/smart-imitation/jobs
GET    /word/smart-imitation/jobs/{jobId}[?resume=1]
DELETE /word/smart-imitation/jobs/{jobId}[?resume=1]
POST   /word/document-review
POST   /word/document-review/jobs
GET    /word/document-review/jobs/{jobId}[?resume=1]
DELETE /word/document-review/jobs/{jobId}[?resume=1]
POST   /word/document-review/full/snapshots
PUT    /word/document-review/full/snapshots/{sessionId}/batches/{sequence}
POST   /word/document-review/full/snapshots/{sessionId}/commit
DELETE /word/document-review/full/snapshots/{sessionId}
POST   /word/document-review/full/jobs
GET    /word/document-review/full/jobs/{jobId}
DELETE /word/document-review/full/jobs/{jobId}
GET    /word/document-review/full/jobs/{jobId}/issues
PATCH  /word/document-review/full/jobs/{jobId}/issues/{issueId}
GET    /word/document-review/full/jobs/{jobId}/report
DELETE /word/document-review/full/jobs/{jobId}/result

全篇审查问题接口默认每页 20 项，`pageSize` 支持 1–100，使用不透明 `cursor` 续读；`sort` 支持 `source`（原文顺序）和 `severity`（高到低），并支持 `severity`、`category`、`location`（`body`/`chapter`/`table`）和 `status`（`open`/`processed`/`ignored`）筛选。终态任务和摘要报告不返回完整问题数组；`PATCH` 仅按稳定 `issueId` 更新独立处理状态。报告默认返回摘要，`?format=json` 导出完整版本化 JSON，`?format=markdown` 导出 Markdown；结果可由 `/result` 主动删除。
DELETE /word/document-review/jobs/{jobId}[?resume=1]
POST   /word/format-review                         # 仅返回 410 退役响应
POST   /word/format-review/snapshots               # v2 快照
POST   /word/format-review/jobs                    # v2 后台任务
GET    /word/format-review/jobs/{jobId}
GET    /word/format-review/jobs/{jobId}/issues
PATCH  /word/format-review/jobs/{jobId}/issues/{issueId}
GET    /word/format-review/jobs/{jobId}/report
DELETE /word/format-review/jobs/{jobId}
DELETE /word/format-review/jobs/{jobId}/report
POST   /excel/analysis
POST   /excel/analysis/jobs
GET    /excel/analysis/jobs/{jobId}[?resume=1]
DELETE /excel/analysis/jobs/{jobId}[?resume=1]
POST   /excel/formula-assistant/jobs
GET    /excel/formula-assistant/jobs/{jobId}[?resume=1]
DELETE /excel/formula-assistant/jobs/{jobId}[?resume=1]
POST   /ppt/document-files
POST   /ppt/slide-assistant/jobs
GET    /ppt/slide-assistant/jobs/{jobId}[?resume=1]
DELETE /ppt/slide-assistant/jobs/{jobId}[?resume=1]
POST   /ppt/structure-review/jobs
GET    /ppt/structure-review/jobs/{jobId}[?resume=1]
DELETE /ppt/structure-review/jobs/{jobId}[?resume=1]
```

## 3. 本版本关键变化

`v0.23.0-alpha` 实现双模型接入与写作长任务稳定化：

- 新增 `ModelConfigurationStore`、模型配置 CRUD/复制/激活/验证 API、旧档案迁移和旧 API 兼容包装；密钥继续独立文件存储并保持 `0600`。
- `ProviderClient` 根据当前任务配置选择工作流平台或模型直连传输，统一剥离 `<think>`，执行输入预算检查，并在生产环境拒绝未配置任务而不返回模拟结果。
- 八类任务 System Prompt 以 Markdown 和哈希清单交付；PPT 文档总结在直连模式本地解析 Markdown/DOCX。
- 智能编写与智能仿写新增后台任务接口、客户端任务号幂等、短轮询恢复、排队取消和 600 秒 Provider 预算；写回实现未改，恢复任务因缺少原选区快照只允许预览和复制。
- 长任务协调器新增交互优先级及三次突发公平限制；总容量仍为 2 运行、8 排队。
- Word、Excel、PPT 设置页统一为宿主色的紧凑模型配置编辑器，支持接入方式、独立地址、双录 Key、直连高级参数和验证调用；任务页只显示完整配置。

Issue #23 已补齐 PPT 结构审查的超长与无标题页边界：

- 起止页严格要求正整数，并分别反馈范围倒置、页码越界、超过 60 页和幻灯片读取失败；320px 窄窗下输入改为纵向排列。
- 正常页只读取可识别的主标题和副标题，不为识别副标题而预读普通正文；无标题页正文兜底按尝试页数计数，最多 10 页、每页 120 字符。
- 第 11 个及后续无标题页携带 `bodyFallbackOmitted=true`，正文不被读取；Adapter 移除这些页面的模型内容推断、逐页建议和目录定位，只保留“信息不足”。
- 结构化结果和非结构化降级结果均固定显示“本次审查第 X–Y 页”；本地确定性问题和模型问题按页码与问题语义跨优先级去重。

`v0.22.0-alpha` 已完成 issue #22 的 PPT“结构审查”最小闭环：

- PPT Ribbon 新增独立“结构审查”，设置页为 `ppt.structure_review` 提供与 `ppt.slide_assistant` 隔离的工作流档案和 API Key。
- 前端按 Slides 集合只读提取显式页段；主标题与副标题分离，有标题页不读取正文，无标题页正文兜底限制为每页 120 字符、单次 10 页。空标题占位符不会把普通正文误判为标题。
- 整套演示文稿或显式页段超过 60 页时，在模型调用前明确拒绝；不静默截断、不自动拆段，也不发起多次模型调用。
- adapter 本地检查空标题、完全重复标题、超过 30 字符标题和明显编号跳号；一次模型调用审查整体主线、推断章节、顺序、重复和内容缺口，本地与模型问题按代码和页码合并去重。
- 模型返回的章节、问题、逐页建议和目录页码统一限制在本次审查范围内；纯越界定位被忽略，混合定位只保留有效页码。未闭合 `<think>` 不进入原始降级文本。
- FastAPI 与 standalone 均提供提交、恢复查询和排队取消接口；任务复用共享长任务协调器，`clientJobId` 幂等，提交时冻结独立认证快照，保留重开续查和 adapter 重启中断语义。
- PPT 设置页同时读取智能总结和结构审查档案后计算宿主整体就绪度；认证快照读取失败直接显示原错误，不误报为 adapter 重启中断。
- 结果按整体主线、高优先级问题、一般建议、逐页调整意见和推荐目录分区，不显示数值总分；非结构化模型回复会剥离 `<think>` 后保留原文和解析诊断。
- 正式包包含 `dify-ppt-structure-review-workflow.md` 和 `ppt-structure-review-prompt-template.md`，并新增结构审查真机只读前后摘要验收项。

`v0.21.0-alpha` 已将 issue #19、#20 的 Excel 公式助手收敛为独立正式功能版本：

- Word、Excel、PPT 与 adapter 版本统一为 `0.21.0-alpha`；Word 和 PPT 不新增业务变化。
- 公式助手保持严格明确选区和 30 行 × 20 列上限，不回退 `UsedRange`；生成/解释模式、独立工作流档案、共享队列、任务恢复和复制结果均纳入正式交付。
- WPS ET 单元格公式读取由 `HasFormula` 保护，并按 `Formula`、`FormulaLocal`、`FormulaR1C1` 顺序只读降级；明确非公式时不会把以 `=` 开头的普通文本误判为公式。
- 自动化继续禁止 `Formula`、`FormulaLocal`、`FormulaR1C1` 赋值、工作表新增和计算模式修改；麒麟 V10 实际属性可用性及工作簿前后摘要必须按包内验收记录执行，当前 Mac 结果不能代替真机结论。
- 正式包包含 `dify-excel-formula-assistant-workflow.md` 和 `excel-formula-assistant-prompt-template.md`；模板补齐 max token、错误降级和禁止事项。

issue #20 已补齐公式解释排错与本地检查，并随 `v0.21.0-alpha` 统一打包：

- 公式助手任务窗格新增可用方向键、Home 和 End 操作的“生成公式 / 解释排错”分段控件；生成模式要求计算需求，解释模式要求明确选区中存在已有公式。
- 解释结果分区展示原公式、组件说明、引用范围、发现问题和有依据的修正或保留公式；主公式保持唯一，备选公式只有与主公式确有差异时才在折叠区显示。
- adapter 新增完全不执行公式的本地检查，覆盖等号前缀、括号、引号、长度、外部工作簿、URL/网络函数、明显越界引用、版本敏感函数和未列入本地支持清单的函数；未知函数只提示目标 WPS 核对，不直接判为不支持。结果只显示“基础检查通过”或具体风险，不证明公式或计算结果正确。
- 模型非结构化输出会保留去除 think 后的原始最终结果、中文诊断和复制入口；仍不通过隐藏单元格、临时工作表或任何 Excel 写入路径试算。

issue #19 已完成 Excel 公式生成最小闭环，并随 `v0.21.0-alpha` 统一打包：

- Excel Ribbon 新增独立“公式助手”，设置页为 `excel.formula_assistant` 提供单独的工作流档案与 API Key。
- 任务只接受用户明确选区和必填计算要求；前端提取最多 30 行、20 列的地址、表头、显示文本、有限值类型和已有公式，并标记截断，不读取 `UsedRange`。
- FastAPI 与 standalone 均提供公式任务提交、查询恢复和排队取消接口；任务复用共享长任务队列，提交时冻结认证快照，保留真实阶段、幂等任务号和 adapter 重启中断语义。
- Dify 调用兼容两种输入格式并使用 1800 秒等待预算；结果过滤 think 内容，固定为一个主公式、建议位置、解释、假设、兼容性说明和复制文本。
- 该能力严格只读，不设置公式、不批量填充、不创建工作表、不修改计算模式；Excel 智能分析及其他既有任务保持原有契约。

`v0.20.1-alpha` 将 issue #12 至 #17 的共享长任务队列与选区监听优化收敛为稳定补丁，不新增业务入口：

- issue #17 已将 Excel 范围摘要改为 `SheetSelectionChange` 事件优先：支持 `wps.ApiEvent`、`et.ApiEvent` 和 `Application.ApiEvent` 兼容入口，事件后立即更新，并以约 2 秒低频读取修正事件不可用或漏报状态。
- Excel 范围监听在页面隐藏、进入设置和智能分析任务运行期间暂停；页面重新可见、返回任务页或任务终止后立即读取当前范围。范围类型、工作表、地址和行列摘要未变化时不改写可访问状态文本。
- 智能分析点击提交后仍重新读取当前 Excel 对象，继续保持选区优先、UsedRange 兜底、`120 × 30` 单元格及 20000 字符数据预算，不使用范围摘要或旧 payload 代替真实选区。
- issue #15 已闭合三宿主共享容量契约：Word 文档审查、Excel 智能分析和 PPT 智能总结共同受默认 2 个运行槽位与 8 个 FIFO 排队位置限制；跨宿主排队、中文满队列拒绝和排队取消使用同一个协调器，活动任务不参与终态 TTL 或数量清理。兼容保留的 `POST /word/document-review` 与 `POST /excel/analysis` 也通过同一协调器提交并等待终态，不能绕过全局容量。
- `/provider/route-diagnostics` 在有效容量、运行数、排队数和最近脱敏终态基础上新增进程内取消、拒绝、超时计数；超时只记录受控错误码，不记录异常正文。Provider 请求诊断不再保存或展示 `queryPreview`，三宿主高级诊断均不显示 API Key、用户正文、公式正文或完整上传文件名。
- 三个任务页只显示当前任务的队列位置、阶段、总耗时、阶段耗时和可取消状态；Excel/PPT 补齐排队取消按钮。三个宿主从任务 ID 写入本地活动记录起，后续查询均使用 `resume=1`；无论任务窗格是否重开，服务端任务缺失都会显示明确的 adapter 重启中断提示和重新提交按钮，普通未知或过期任务仍使用各自 `*_JOB_NOT_FOUND` 错误码。

- issue #12 已让 Word 文档审查成为共享长任务协调器的首条链路：默认同时运行 2 个任务，FIFO 排队最多 8 个；`clientJobId` 继续幂等，重复提交不会再次调用模型后台。
- 文档审查任务状态现在包含 `queued / running / completed / failed / cancelled`、排队位置、真实阶段、总耗时、阶段耗时和 `canCancel`；只有排队任务可通过 `DELETE /word/document-review/jobs/{jobId}` 取消，运行中的阻塞式模型请求不伪装为可取消。
- 提交任务时冻结请求、工作流档案、API URL/path、Dify 输入模式和仅存在内存中的认证快照；配置切换只影响后续任务。认证正文不进入任务响应、日志或诊断，并在完成、失败或排队取消后释放。
- 运行中和排队任务不因容量被淘汰；终态从完成时起保留 2 小时且最多 50 条。任务窗格重开后按原 `clientJobId` 和 `resume=1` 查询；只有此前已持久化为活动任务的查询缺失才解释为 adapter 重启中断，普通未知或过期任务仍返回 `DOCUMENT_REVIEW_JOB_NOT_FOUND`。
- `/provider/route-diagnostics` 包含共享协调器容量、当前计数和最多 10 条脱敏终态摘要；摘要不包含请求、结果、异常正文或认证信息。
- FastAPI 与 standalone 均支持相同的文档审查提交、查询、排队取消、队列满和重启中断响应契约；兼容同步路由的结果 envelope、think 过滤、审查记录和只读行为保持不变，但执行也纳入共享协调器。
- issue #13 已让 Excel 智能分析复用同一共享长任务协调器：与文档审查共同受默认并发 2、FIFO 排队容量 8 的全局限制，重复 `clientJobId` 继续只调用一次模型后台；提交时冻结表格请求与工作流认证快照，排队期间切换档案只影响后续任务。
- 智能分析任务状态现包含 `queued / running / completed / failed / cancelled`、排队位置、真实阶段、总耗时和阶段耗时；FastAPI 与 standalone 均支持提交、查询、排队取消和中文队列满错误。
- Excel 任务窗格继续保留选区优先、UsedRange 兜底、报告预览、汇报段落、复制、短暂断连恢复和重开续查，并新增共享队列位置、当前阶段与耗时显示；仍不写回任何单元格。
- issue #14 已让 PPT 当前页总结和文档总结复用同一共享长任务协调器：与 Word 文档审查、Excel 智能分析共同受默认并发 2、FIFO 排队容量 8 的全局限制，重复 `clientJobId` 不会重复消费文件令牌、上传文件或调用模型后台。
- PPT 文档任务在提交队列时即验证并消费一次性文件令牌，本地暂存文件转为任务独占资源；排队期间不上传模型后台且不再受令牌 30 分钟有效期影响，只有取得执行槽位后才依次上传文件和发送消息，两步使用提交时冻结的同一认证快照。
- PPT 智能总结状态现包含 `queued / running / completed / failed / cancelled`、排队位置、`preparing / uploading / provider_processing / parsing` 真实阶段及耗时；FastAPI 与 standalone 均支持提交、查询和排队取消。任务文件在排队取消、完成、失败及 Adapter 退出时清理。
- PPT 任务窗格按真实阶段显示排队、准备、上传、模型处理和解析，不显示估算百分比；当前页标题/副标题、文档页数选项、长任务恢复、结果预览、分类复制和只读边界保持不变。

`v0.20.0-alpha` 正式打包 issue #4 至 issue #11 的写作规范库完整基线：

- issue #4 已补齐四个经门禁加载的预置规范包：G企技术写作基础、技术文件文体、网络安全术语和党政公文文体；每个包保留稳定 ID、来源、许可证及逐条审阅摘要。
- 智能编写新增“自动匹配 / G企技术材料 / 网络安全技术材料 / 党政公文 / 不使用写作规范”选择；自动匹配无法可靠判断时只使用 G企基础包。
- 智能编写规范解析按保护项、用户本次要求、组织层、预置层、通用去模板化规则固定排序；注入继续限制为 3000 字符、30 个术语和 8 条规则，并为文体/去模板化保留 5/3 配额，仍只调用一次模型后台。
- 智能编写结果新增非阻断本地检查：数字、日期、标准编号、责任主体、专有名词、型号标识、规范性词或标准术语变化显示“需要核对”，明确 T1/T2/T3 模板化线索显示“表达建议”，无问题只显示一行通过状态；检查失败不丢弃正文，也不影响预览、复制、对照或写回。
- issue #5 已让智能仿写复用与智能编写一致的紧凑规范场景选择，并按 `word.smart_imitation` 独立记忆；自动匹配、明确场景和停用语义保持一致。
- 智能仿写使用对应场景规范包中的 `smart_imitate` 条目，冲突顺序为保护项、用户本次要求、组织层、模板结构与句式意图、预置层、通用去模板化规则；模板意图高于预置文体，去模板化不得破坏用户明确要求保留的结构。
- 智能仿写对用户要求和参考素材中的保护项及组织术语执行非阻断结果检查；仅用于模仿的模板事实不会被误判为必须保留，但用户明确要求保留的模板日期、数字、责任主体等保护项会进入“需要核对”。结果展示规范应用摘要、“需要核对”和“表达建议”，检查失败保留模型正文，任务仍只调用一次模型后台，且不新增对照或写回。
- issue #6 已让文档审查复用相同的紧凑规范场景选择，并按 `word.document_review` 独立记忆；对应场景的预置术语、文体和去模板化规则进入既有文档审查提示词，仍只执行一次模型调用。
- 文档审查把同一次模型调用识别的语义型文体问题与本地可确定的非标准术语、术语别名和模板化表达合并为既有审查问题；重复的模型/本地问题按类别和原文片段去重，初始结果与审查记录预览复用同一问题列表，仍只读且不修改 Word 原文。
- 文档审查规范解析或本地检查异常采用 fail-open，只降级规范检查并保留模型审查结果，不反馈为模型后台连接失败；`think` 过滤、`clientJobId` 幂等任务、1800 秒 provider 预算、60 分钟轮询恢复和既有超时策略保持不变。
- issue #7 已为预置术语增加组织覆盖、预置停用和恢复基线操作；操作以稳定预置条目 ID 保存到 `writing_policies.db`，不修改预置 JSON，并在 adapter/WPS 重启后保持。
- Word 写作规范管理页可切换四个预置规范包，组织自定义、组织覆盖、预置停用及最终生效状态分别展示；三个 Word 任务的解析、提示词注入和本地结果检查使用同一份生效术语。
- issue #8 已将预置规范与组织规范分层管理；组织层独立维护术语、文体规则和去模板化规则，文体/去模板化规则支持三个 Word 任务与三个规范场景多选，新建默认全选。
- 预置文体与去模板化规则现与预置术语一样支持组织覆盖、停用和恢复基线；同层同名规则使用稳定优先级顺序在本地裁决，结果返回冲突摘要，不增加模型调用。
- issue #9 已补齐 CSV/XLSX 规范往返：两种格式使用同一列契约，可分别导出当前生效规范或仅组织规范，并保留稳定 ID、规范包、来源、版本、层级、覆盖状态、任务范围和场景范围。
- 往返导入按明确操作解释新增、修改、停用、恢复和删除；文件缺行不触发删除。预览分别统计五类变更、冲突和错误，令牌绑定文件 SHA-256 摘要并保持 10 分钟单次使用。
- 往返应用前创建规范库备份，全部组织条目与预置操作在单个 SQLite 事务中完成，任一错误完整回滚。Word 设置页把导入、CSV/XLSX 导出、完整备份和规范库诊断集中到次级“更多”页面。
- issue #10 已将预置包加载改为逐包隔离：单包缺失、校验失败或版本不兼容时只跳过该包，组织规范和其他可用预置包继续生效；三个 Word 任务在规范完全未应用时统一显示“写作规范暂未应用，已继续处理”，部分应用时显示“写作规范暂未完整应用，已继续处理”，不会误报为模型后台连接失败。
- 既有组织数据库在迁移前创建原始恢复备份；数据库不可读时保留主文件和原始备份，迁移失败时主文件恢复为迁移前字节，不自动清空、重建或覆盖异常数据。规范解析和结果检查分别记录阶段、耗时、受控错误码、规则 ID 和预置版本，不记录 API Key、用户全文或完整规则正文。
- 写作规范列表接口新增 `limit`、`offset`、`pageCount` 和 `hasMore`，Word 前端每页最多请求并渲染 50 条，通过键盘可操作的上一页、下一页访问完整列表，并继续使用 250 ms 防抖搜索。开发机默认性能目标为本地解析加检查不超过 100 ms；麒麟 V10 以 `AI_WPS_WRITING_POLICY_PERFORMANCE_TARGET_MS=200` 执行目标机验收。
- issue #11 已把写作规范库纳入统一三宿主交付基线：首次安装显式初始化权限为 `0600` 的空组织规范数据库；覆盖安装对已有数据库（包括异常文件）只复用不覆盖，并继续恢复全部已有备份和模型配置。
- `release-manifest.json` 固定记录 `0.20.0-alpha`、三宿主 Ribbon 类型、四个规范包、来源许可资产、CSV/XLSX 模板和运行态排除策略；构建阶段核对规范包/审阅清单完整性，并拒绝数据库、备份、`adapter.json`、API Key、日志、用户导入内容和未确认草稿进入交付包。
- Word、Excel、PPT 与 adapter 版本统一为 `0.20.0-alpha`；格式审查、Excel 智能分析、PPT 智能总结、工作流档案、写回、超时和轮询逻辑未作功能改动。
- `v0.19.1-alpha` 是三宿主任务窗格体验补丁版，只调整界面、设置状态探测和交互保护，不新增或改动智能编写、智能仿写、文档审查、格式审查、智能分析、智能总结及任何回写链路。
- Word、Excel、PPT 的任务页与设置页完成同构体验更新：继续保持 Word 蓝、Excel 绿、PPT 橙宿主配色，统一使用系统字体、8px 以内圆角、克制的按压/披露动效和清晰键盘焦点；任务主按钮继续使用高对比度纯文字，不增加图标。
- 三宿主设置首页统一为“模型接口 / 工作流设置 / 高级诊断”渐进披露结构。模型接口状态不再读取 adapter 的统一 Key 配置标记，而是按当前宿主的统一 API URL、真实任务类型和工作流档案计算“无法检测 / 未配置 / 部分就绪 / 已就绪”。
- 设置状态刷新仅在设置首页可见、页面未隐藏、URL/工作流编辑器未打开且工作流未变更时运行；进入设置立即读取，随后每 30 秒刷新。配置探测使用 8 秒短预算、单飞请求和迟到响应废弃，绝不改变 Word 文档审查、Excel 智能分析或 PPT 智能总结的长任务等待预算。
- URL 编辑、工作流新增/修改/切换/删除期间会暂停并废弃设置刷新，操作结束后恢复且不重复创建计时器。临时读取失败会保留上一份稳定工作流、当前档案和用户选择，只附加中文错误及重试入口，不把失败误解释为空列表。
- 三宿主工作流说明改为 `i` 悬浮/聚焦提示，支持点击固定、外部点击和 `Escape` 关闭；任务选项卡支持方向键和 `Home/End`，Word 显示四个真实任务，Excel/PPT 只显示当前已交付功能。未填写备注时不再显示“暂无备注/无备注”占位。
- 高级诊断默认折叠，仅在用户展开或手动刷新时请求诊断；诊断刷新和复制反馈只写设置页状态，不覆盖任务页状态、结果或复制内容。自动刷新对相同状态采用 changed-only DOM 更新，避免 `aria-live` 每 30 秒重复播报。
- PPT 设置页的网络不可达和设置探测超时反馈已中文化；`Failed to fetch` 等浏览器原始错误不再直接展示给用户。`checkHealth()` 继续只负责右上角“已连接/未连接”，模型接口就绪度由 `/config` 与 `ppt.slide_assistant` 档案独立计算。
- 三宿主前端 9 项测试、6 个 taskpane/helper 脚本语法检查和 `git diff --check` 已通过；真实 Chromium 在 420×900、320×700 下完成任务页和设置页验收，三宿主均无页面横向溢出，Word 四任务选项卡在 320px 下按设计横向滚动。
- `v0.19.0-alpha` 新增仅作用于 Word 的写作规范库，智能编写、智能仿写和文档审查在提交模型前按全局及任务范围匹配；Excel、PPT 不接入该规范库。
- 写作规范使用本地 SQLite `run/writing_policies.db` 保存；术语支持规范名称、别名和说明，文体规则支持名称、规则正文、备注和 `global / word.smart_write / word.smart_imitation / word.document_review` 范围。
- Word 设置页新增下钻式规范管理：概览页保持紧凑，进入管理页后可新增、修改、删除、筛选，并支持最大 5 MB 的 CSV/XLSX 预览导入、冲突跳过、CSV 导出和完整数据库备份。
- 导入预览令牌有效期 10 分钟且只能应用一次；冲突策略固定为保留已有项并跳过冲突，不提供覆盖导入，避免批量误改现场规范。
- 智能编写、智能仿写和文档审查结果区显示本次使用的术语/规则数量；规范库不可读、损坏或暂时不可用时采用 fail-open，任务继续调用模型并明确显示降级提示。
- 规范匹配和管理诊断不记录 API Key、原文全文、规则正文或术语说明；`/writing-policies/diagnostics` 只提供脱敏健康信息。
- 覆盖安装除继续保护 API URL 与各类 API Key 外，还会恢复 `run/writing_policies.db` 和全部已有 `backup-*` 规范库备份；交付包自带 CSV/XLSX 导入模板和写作规范运维手册。
- 本版本不改变智能编写既有回写、智能仿写只读、文档审查闭环、格式审查规则、Excel 智能分析和 PPT 智能总结链路。
- `v0.18.1-alpha` 统一收敛三宿主设置交互：设置首页只保留统一 API URL 和当前宿主工作流列表，去掉统一 Key 与模型提供商名称输入；adapter 的统一 Key 回退接口和覆盖安装保护继续保留。
- Word 按智能编写、智能仿写、文档审查、格式审查四个页签分别管理档案；Excel 固定管理 `excel.analysis`，PPT 固定管理 `ppt.slide_assistant`，三个宿主的数据和界面互不交叉。
- 工作流支持自定义名称、备注、独立 Key、新建、修改和删除；编辑时 Key 留空保持原密钥，当前工作流不可删除，读取失败时禁止误创建并提供重新读取。
- 功能页下拉选择工作流后立即激活，不再需要额外“切换”按钮；激活期间禁用任务提交，失败时回退原选项并显示中文反馈。
- 三宿主工作流设置增加异步请求顺序保护、重复提交保护、未保存编辑确认和密钥输入清理，避免慢响应覆盖新状态或敏感输入留在隐藏 DOM。
- Word 前台 Ribbon 入口保持“智能编写 / 智能仿写 / 文档审查 / 格式审查 / 设置”。
- Excel 前台独立 `et` 插件入口当前只显示“智能分析 / 设置”，内部任务键仍为 `excel.analysis`。
- PPT 前台独立 `wpp` 插件入口当前只显示“智能总结 / 设置”，提供“当前页总结 / 文档总结”双模式，内部任务键仍为 `ppt.slide_assistant`。
- 文档总结只接受单个 UTF-8 `.md` 或有效 `.docx` 文件，最大 10 MB；页数选项为 5、8、10、12、15，默认 10，模型输出整套 PPT 标题、摘要、逐页文字/版式/视觉建议和整体风格建议。
- 文档总结由 `POST /ppt/document-files` 返回 30 分钟一次性文件令牌，再通过现有后台任务接口提交；adapter 使用同一 PPT 档案密钥依次调用 Dify `/files/upload` 与 `/chat-messages`，不在本地提取正文。
- 智能总结长任务沿用 1800 秒 provider 等待预算和可恢复轮询；状态查询短暂失败或重开任务窗格时保留任务号，不重复上传文件或发起模型任务。
- Word、Excel、PPT 统一标题栏、连接状态、按钮、输入控件、结果区和设置页视觉；三宿主插件目录、Ribbon 入口、任务档案和业务行为继续隔离。
- Word、Excel、PPT 任务窗格分别使用文字蓝、表格绿、演示橙的平衡宿主主题；布局和状态语义保持统一。
- 三个宿主根据聚合健康显示“已连接”“增强降级”或“恢复模式”；只有请求无法到达 Adapter 时显示“未连接”。恢复模式不再继续读取配置或允许提交新模型任务。
- Word 和 Excel 右上角新增与 PPT 一致的设置/返回快捷按钮；Word 返回进入设置前的功能，Excel 返回智能分析。
- 三个宿主的主生成按钮均为高对比度纯文字按钮，不显示图片、SVG 或伪元素图标。
- 统一正式交付包包含 `docs/prompt-templates/excel-smart-analysis-prompt-template.md` 与 `docs/prompt-templates/ppt-smart-summary-prompt-template.md`，仍由一个安装脚本覆盖安装三个宿主并保留现场 API URL、统一 API Key 和全部工作流档案密钥。
- 统一正式交付包通过一个安装脚本同时安装 `wps-ai-assistant_1.0.0`、`wps-ai-assistant-et_1.0.0` 和 `wps-ai-assistant-wpp_1.0.0`，`publish.xml` 同时包含 `type="wps"`、`type="et"` 与 `type="wpp"`。
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
- 格式审查固定使用 `technical-document-template-rules`（显示名称“技术文档模板规则”、规则版本 `1.0.0`、来源版本 `wx-doc-format 0.12.15`），不再提供模板下拉，不提供“应用预览”写回；当前入口只消费 v2 快照、后台任务和版本化报告。
- v2 格式语义增强只接受 `format_semantics.v1`，Dify 不可用或返回不可解析时，任务明确记录降级状态和原因，不调用旧同步审查链。
- 2026-05-29 的旧同步格式审查链已退役；`POST /word/format-review` 只返回 `410 WORD_FORMAT_REVIEW_SYNC_RETIRED`，不再执行审查或返回旧报告。
- 2026-05-31 排查格式审查点击后任务窗格卡死且 Dify 无调用记录：根因是前端在发起 `fetch` 前同步扫描 WPS 全文 `Paragraphs`，大文档下会阻塞任务窗格。现已为格式审查增加专用限量抽取：最多读取 80 段、每段 800 字、正文 12000 字；框选文本时直接按选中文本构造段落，不再先扫描全文；点击后先刷新“正在读取格式审查范围”状态，再异步执行抽取和请求。
- 文档审查结果改为按错别字、语言表达、逻辑表达、通畅性、专业性分组展示，每条问题固定展示严重程度、位置、原文片段、问题说明、修改建议和建议改写。
- 历史版本的格式审查结果曾按页面设置、标题层级、正文格式、段落格式、图表题/注释和其他格式项分组展示；该同步渲染链已由 v2 结构化报告替代。
- v2 报告预览展示执行/合规/覆盖/语义状态、问题清单、已验证格式事实和诊断信息；无法由已验证事实确认的值显示为“无法识别”或“无法验证位置”，不猜测单位、不翻译旧当前值、不使用旧报告兜底。
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
- Word 任务窗格只加载四类 Word 档案，Excel 任务窗格只加载 `excel.analysis` 档案，PPT 任务窗格只加载 `ppt.slide_assistant` 档案；切换只影响下一次新任务，不改变已提交的后台任务。
- `v0.18.1-alpha` 起，功能页工作流下拉选择后立即激活；设置页使用紧凑列表和独立新建/编辑子页，当前档案不可删除，编辑 Key 留空不替换原密钥。
- 任务窗口结果区继续区分任务类型：智能编写按内容结构选择朴素或结构化回显，文档审查/格式审查/诊断继续显示安全渲染后的 Markdown 成品；复制和写回仍使用原始模型文本。
- `v0.16.0-alpha` 的 adapter、前端缓存参数、manifest 和启动脚本曾统一更新，以确保目标机重新打开 WPS 后加载工作流档案界面。
- `v0.17.0-alpha` 起，新增只读 PPT 单页助手：当前页输入区分主标题、可选副标题和普通正文形状，相邻页只读取标题；动态输入总预算 4600 字符，模型等待预算 1800 秒，前端通过可恢复后台任务轮询避免慢模型被误判为连接失败。
- PPT 单页助手结果只提供预览、纯文本、复制标题、复制要点、复制结论和复制全文，不调用任何 WPS 演示写接口。
- adapter、Word/Excel/PPT 前端缓存参数、manifest 和启动脚本统一更新到 `0.17.0-alpha`。

## 4. 需要重点保护的既有逻辑

- 设置页 30 秒探测必须继续与业务任务隔离：不得覆盖任务页状态、结果正文、复制内容、任务 trace、后台任务号或回写状态；URL/工作流编辑期间必须暂停并废弃在途探测，不能用迟到响应覆盖用户草稿。
- 工作流档案临时读取失败必须保留上一份稳定 `profiles`、`activeProfileId` 和用户选择；请求被更新操作取代时应视为 superseded，不得误报“无法检测”或清空档案。
- 设置页配置探测保持 8 秒短预算和单飞机制；不得把该预算传入文档审查、Excel 智能分析或 PPT 智能总结的模型请求与长任务轮询。
- 写作规范匹配必须保持 fail-open：数据库不可读、损坏、迁移失败或匹配异常时，只能返回脱敏降级信息，不能阻断智能编写、智能仿写或文档审查。
- 写作规范只允许注入 Word 智能编写、智能仿写和文档审查；不得扩散到格式审查、Excel 智能分析或 PPT 智能总结。
- 写作规范诊断和任务日志不得包含 API Key、原文全文、规范术语说明或文体规则正文；前端结果只展示命中数量、名称摘要和降级状态。
- CSV/XLSX 导入必须先预览后应用，预览令牌保持 10 分钟有效且单次使用；冲突项只能跳过并保留现场已有知识，不得静默覆盖。
- 覆盖安装必须继续保护 `run/writing_policies.db` 和全部已有 `backup-*` 规范库备份，不能把包内空库覆盖到目标机。
- 智能编写 Dify 调用、任务级 API Key 选路和“不允许原样返回”的提示词约束。
- 智能编写新菜单值和旧值兼容映射：前端只展示新选项，adapter 仍识别旧 payload 值。
- `/chat-messages` 顶层 `query` 必须始终携带完整提示词；旧模式同时携带 `inputs.query`，新版“用户输入”节点模式保持 `inputs: {}`，两种模式不得修改提示词正文。
- 统一 API URL + 统一 API Key + 任务级 API Key 的回退链路。
- `/provider/debug-last` 脱敏诊断，不泄露完整原文和密钥。
- Markdown 安全渲染：HTML 转义，危险链接不可点击，复制仍保留原始文本。
- WPS COM 对象容错：段落集合、选区文本、全文 Range 和宿主对象清洗逻辑不能被审查功能改动破坏。
- 文档审查不能回退为同步全文扫描；`DOCUMENT_REVIEW_EXTRACTION_OPTIONS` 必须保留 `preferSelectionTextParagraphs`、`avoidFullTextRead`、`avoidFallbackTextRead`。
- 文档审查长任务必须继续走 `clientJobId` + `/word/document-review/jobs/{jobId}` 的可恢复轮询链路；前端不要在短暂连接失败后清空 jobId，adapter job store 不要对同一 `clientJobId` 重复发起模型后台任务。
- 文档审查的“可恢复”只覆盖同一 adapter 进程内的任务窗格关闭、重开和短暂断连；adapter 重启是明确中断边界，不得把不存在的阻塞式 provider 任务伪装为仍可恢复。
- 共享长任务协调器默认并发 2、排队容量 8；只有 queued 状态允许取消，running 状态不得返回虚假取消成功。运行中和排队任务不得因终态容量或 TTL 被淘汰。
- 文档审查 Dify 非标准返回也要在前台可见：`rawAnswer` 和 `parseFallbackReason` 是现场判断 Dify 输出格式问题的重要兜底。
- 智能编写选区轻量抽取不能回退为同步全文段落扫描；`SMART_WRITE_EXTRACTION_OPTIONS` 必须保留 `preferSelectionTextParagraphs`、`avoidFullTextRead`、`avoidFallbackTextRead`。
- 智能编写结果预览必须保持结构感知：简单段落不要额外套 Markdown 排版；标题、列表、序号、表格、加粗等结构存在时要尽量结构化回显和写回。
- `v0.13.0-alpha` 以来的智能编写结果视图切换不能改动写回功能；`applyRewrite`、`tryApplyFormattedRewrite`、`buildMarkdownWritebackBlocks` 只允许作为既有能力保留，不在本版扩展。
- `v0.13.1-alpha` 的对照高亮只允许作用于只读 comparison Markdown，不允许把 `==...==` 标记传入复制文本或写回正文。
- 智能仿写首版必须保持 preview/copy only：只复用智能编写的预览、纯文本和复制能力，不显示对照，不设置 `pendingApplyAction`，不调用任何 Word 写回路径。
- 智能分析必须保持 read-only：不调用任何 Excel 写回、插入公式、新增工作表或修改单元格路径；只允许选区/已用范围读取、预览、纯文本和复制。
- 智能分析长任务必须使用 `clientJobId` + `/excel/analysis/jobs/{jobId}` 的可恢复轮询链路；短暂状态查询失败不得清空任务号，同一 `clientJobId` 不得重复发起模型任务。
- PPT 智能总结必须保持 read-only：不得调用幻灯片、形状、文本、版式、主题、图表、动画或备注写接口；只允许读取当前页或用户主动选择的文档、预览、纯文本与复制。
- PPT 智能总结长任务必须使用 `clientJobId` + `/ppt/slide-assistant/jobs/{jobId}` 的可恢复轮询链路；短暂状态查询失败不得清空任务号，同一 `clientJobId` 不得重复上传文件或发起模型任务。
- PPT 文档任务必须在提交 `clientJobId` 时取得暂存文件所有权；排队期间不得提前上传模型后台，所有终态、排队取消和 Adapter 退出路径必须清理任务文件。
- 文档总结文件必须限制为单个 UTF-8 `.md` 或有效 `.docx`、1 字节至 10 MB；一次性令牌在上传成功、任务失败或过期时清理，日志和诊断不得记录正文、Base64、完整文件名或 API Key。
- PPT 文档任务必须使用同一个 `ppt.slide_assistant` 档案认证快照调用 `/files/upload` 和 `/chat-messages`；旧版与新版 Dify 输入模式回退时必须保留同一个 `files` 引用。
- PPT 主标题和副标题必须分开识别；副标题是可选字段，不得混入 `textBlocks`，也不得覆盖主标题。
- Word/Excel/PPT Ribbon 必须保持宿主隔离：Word `type="wps"`、Excel `type="et"`、PPT `type="wpp"` 只显示各自功能和设置。
- Word/Excel/PPT 宿主配色、连接文案、设置快捷入口和纯文字主按钮均为前端展示层变化；不得借此改动 Word 回写、文档审查/智能分析/智能总结长任务恢复、模型请求或三个 Ribbon 的宿主隔离。
- 新版本安装脚本必须继续保护目标机运行时配置：不得覆盖 `config/adapter.json`、`run/provider_api_key`、`run/provider_api_keys/` 中的现场 API URL 和 API Key，也不得覆盖写作规范数据库和应保留的备份。
- 文档审查闭环只能管理前端处理状态和复制审查记录，不允许自动写回或自动修改正文。
- v0.25.1 的格式审查主入口只走 v2 快照、后台任务和 v2 报告协议；旧同步 `/word/format-review` 不再执行审查，v1 快照、缓存和报告只返回明确失效错误并要求重新审查。模板规则检查、任务级 API Key 选路和 Dify payload 仍由 v2 后台任务统一承载。
- 智能编写和文档审查逻辑不要因格式审查预览优化被改动；对应抽取限制、等待反馈、`rawAnswer` 兜底和写回策略都要保持当前行为。
- uvicorn 优先、standalone 兜底的 adapter 启动方式，以及旧进程版本替换逻辑。

## 5. 当前关键文件

- `adapter_service/app/api/writing_policies.py`：写作规范 CRUD、模板、导入预览/应用、导出、备份和诊断接口。
- `adapter_service/app/services/writing_policy/`：SQLite 存储、匹配、导入解析、预览令牌、备份和 fail-open 服务边界。
- `adapter_service/app/api/word.py`：当前 Word 四任务路由。
- `adapter_service/app/api/excel.py`：智能分析路由。
- `adapter_service/app/api/ppt.py`：PPT 文档文件、智能总结和结构审查后台任务路由。
- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、任务级 API Key、脱敏 provider 调试记录，以及 Word/Excel/PPT provider 调用。
- `adapter_service/app/services/excel/analyzer.py`：Excel 表格可用性校验和 provider 调用封装。
- `adapter_service/app/services/excel/formula_checks.py`：公式字符串的只读基础语法、引用和兼容风险检查。
- `adapter_service/app/services/excel/analysis_jobs.py`：智能分析幂等后台任务、运行状态和耗时诊断。
- `adapter_service/app/services/ppt/document_files.py`：PPT Markdown/DOCX 校验、一次性暂存、过期和安全清理。
- `adapter_service/app/services/ppt/slide_assistant.py`：PPT 单页输入预算、生成/优化模式和 provider 调用封装。
- `adapter_service/app/services/ppt/slide_assistant_jobs.py`：PPT 当前页/文档智能总结幂等后台任务、阶段状态和耗时诊断。
- `adapter_service/app/services/ppt/structure_review.py`：PPT 结构审查输入预算、本地标题检查、模型结果合并与复制文本。
- `adapter_service/app/services/ppt/structure_review_jobs.py`：结构审查幂等后台任务、独立认证快照、共享队列和恢复语义。
- `adapter_service/app/services/word/smart_imitator.py`：智能仿写服务，负责模板抽取、必填校验、provider 调用和 rewrite 形态结果输出。
- `adapter_service/app/services/word/document_reviewer.py`：文档审查服务，负责选区/全文、默认提示词、模型结果解析和问题列表输出。
- `adapter_service/app/services/word/format_reviewer.py`：格式审查服务，负责模板规则检查、可选 AI 段落角色识别和本地兜底。
- `adapter_service/app/core/models.py`：当前请求/响应模型。
- `adapter_service/standalone_adapter.py`：standalone 模式，与 FastAPI 当前输出保持一致。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`、`taskpane.js`、`taskpane.css`、`taskpane-helpers.js`：当前任务窗格、设置页、Markdown 渲染和 WPS 读取逻辑。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.xml`、`ribbon.js`：当前 Ribbon 入口和图标映射。
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/`：Excel 专用插件包，包含“智能分析”Ribbon、任务窗格、图标和 manifest。
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/`：PPT 专用只读插件包，包含“智能总结”“结构审查”Ribbon、任务窗格、图标和 manifest。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png`：智能仿写 Ribbon 图标。
- `adapter-start-kit/scripts/install_autostart.sh`、`adapter-start-kit/scripts/uninstall_autostart.sh`、`adapter-start-kit/docs/autostart-guide.md`：麒麟 V10 目标机 systemd 开机自启动安装、卸载和运维说明。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages`、四个 Word 任务、一个 Excel 任务和一个 PPT 任务的 `taskApiKeyRefs`。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify 配置手册。
- `docs/operations/dify-smart-imitation-workflow.md`：智能仿写 Dify 配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 配置手册。
- `docs/operations/dify-excel-analysis-workflow.md`：Excel“智能分析”Dify 配置手册。
- `docs/operations/dify-ppt-slide-assistant-workflow.md`：PPT“智能总结”双模式 Dify 配置手册。
- `docs/operations/dify-ppt-structure-review-workflow.md`：PPT“结构审查”Dify 配置、页段边界与只读验收手册。
- `docs/operations/workflow-profile-management.md`：Word/Excel/PPT 工作流档案、切换和密钥保护手册。
- `docs/operations/writing-policy-library.md`：Word 写作规范维护、导入、导出、备份、降级与恢复手册。
- `docs/prompt-templates/excel-smart-analysis-prompt-template.md`：Excel“智能分析”Markdown 提示词模板。
- `docs/prompt-templates/ppt-smart-summary-prompt-template.md`：PPT“智能总结”当前页/文档双模式 Markdown 提示词模板。
- `docs/prompt-templates/ppt-structure-review-prompt-template.md`：PPT“结构审查”固定 JSON 输出、错误降级和禁止事项模板。
- `docs/superpowers/plans/2026-05-29-review-mode-consolidation-plan.md`：审查入口收敛执行计划。
- `docs/superpowers/plans/2026-05-31-stability-enhancement-plan.md`：本轮稳定增强执行计划。
- `docs/superpowers/plans/2026-07-16-enterprise-terminology-style-knowledge-implementation-plan.md`：Word 写作规范库实现及发布计划。

## 6. 验证状态

`v0.25.1-alpha` 已将 `20260816`、`20260822-275099e`、`20260822-4ff1862`、`20260822-afc5470`、`20260822-385a251`、`20260822-e43dc8c`、`20260824-ccad09f`、`20260824-2e7a3e6`、`20260824-5318d4b`、`20260824-799adf9` 和 `20260824-afe109c` 登记为 `rejected`；当前唯一候选为 `20260824-f953c58`：完整 sourceCommit 为 `f953c58312c8d3d42d3dccea402fccf55a3c7d53`，candidateBuildId 为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-f953c58312c8d3d42d3dccea402fccf55a3c7d53`，归档为 `ai-wps-phase1-delivery-20260824-f953c58-v0251.tar.gz`，SHA-256 为 `833e71fcf5a6e2172c93e44cc3502d46e1ea89c5dc4abb77f658ac8c5ee77ee7`，终态为 `candidate`。该候选 supersedes 的 `afe109c` 完整 sourceCommit 为 `afe109c27bf6bc9e663a0c107ccfd70876f95655`，candidateBuildId 为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-afe109c27bf6bc9e663a0c107ccfd70876f95655`，归档为 `ai-wps-phase1-delivery-20260824-afe109c-v0251.tar.gz`，SHA-256 为 `e3d4da0d1d8e1edc619d2101f45afb104ef8e3a6e5197e4b8e59b46513f78c6b`，拒绝原因为目标机验收审计/测试在缺失必测第 8 或第 9 行时未 fail closed，归档保持不可变。历史归档不得修改。

历史候选源码 `ccad09fb1d8019da3a40f14610ab3bd75de1ec23` 曾修复格式审查批次级块 ID 范围、直连模型输出能力、空最终正文诊断、旧工作流重复迁移及运行时快照误判，但其跨运行时 structure/format 哈希契约仍有阻断缺陷，因此归档已拒绝。本轮又发现目标机验收审计/测试在缺失必测第 8 或第 9 行时未 fail closed；`afe109c` 归档冻结为 rejected，已由 `f953c58` 新候选替代。

```bash
AI_WPS_V0250_BASELINE_ARCHIVE=<v0.25.0-alpha archive> \
AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-afe109c-v0251.tar.gz \
DATE_TAG=20260824 PYTHON_BIN=/mnt/ai-wps-test-venv/bin/python PYTHON38_BIN=/mnt/ai-wps-test-venv/bin/python \
bash packaging/build_v0251_delivery_kit.sh
```

当前可复核结果：

- `20260824-f953c58` 的 Kylin Python `3.8.10` 来源、白名单、规则/插件/审计/运行时/生命周期门禁通过，终态为 `candidate`；`20260824-afe109c`、`20260824-799adf9`、`20260824-5318d4b`、`20260824-2e7a3e6`、`20260824-ccad09f` 和更早归档均为 `rejected`，历史归档不得分发。
- 当前源码 Adapter 全量测试为 `833 passed, 95 skipped`，v0.25.1 交付/prepare/audit focused 为 `46 passed`（`test_v0251_delivery.py`），三项协议/交付 focused 合计 `82 passed`，正式插件契约为 `25/25`；这些自动化证据仍不替代目标机验收。
- `20260824-f953c58` 归档 SHA-256 为 `833e71fcf5a6e2172c93e44cc3502d46e1ea89c5dc4abb77f658ac8c5ee77ee7`，包内 manifest/status/delivery note/target-acceptance identity、精确 1..9 行及九项 `manual-pending` 状态均可复核；`20260824-afe109c` 归档保持原始字节，SHA-256 为 `e3d4da0d1d8e1edc619d2101f45afb104ef8e3a6e5197e4b8e59b46513f78c6b`。
- Issue #59 未标记为接受，真实 WPS GUI、模型直连和目标机人工文档验收仍为 `manual-pending`。

## 7. 目标机验证建议

1. 在无历史安装目录的麒麟 V10 终端安装通过生命周期门禁的新版 `v0.25.1-alpha` 候选包，确认自动生成权限为 `0600` 的 `state/writing_policies.db`；创建组织自定义、组织覆盖和预置停用状态，重启 WPS/adapter 后确认持久化。
2. 记录 API URL、统一 API Key、`state/provider_api_keys/`、规范数据库及全部已有备份摘要，再次执行同一候选包覆盖安装；关闭并重新打开 WPS，确认设置页“前端版本”为 `0.25.1-alpha` 且所有运行态数据未丢失。
3. 设置页配置统一 API URL，例如 `https://aibot.chinasatnet.com.cn/v1`。
4. 分别为“智能编写”“智能仿写”“文档审查”“格式审查”“智能分析”“公式助手”“智能总结”“结构审查”保存两个具名工作流档案；确认功能页下拉选择后立即激活、当前档案不可删除、编辑 Key 留空保持原密钥，并验证下一次任务命中所选档案；当前页和文档总结必须共用 `ppt.slide_assistant`，结构审查必须独立使用 `ppt.structure_review`。
5. 在 Word 设置页进入写作规范管理，验证术语和文体规则的新增、修改、删除、任务范围筛选、CSV/XLSX 预览导入、冲突跳过、CSV 导出和数据库备份；再临时制造规范库不可用状态，确认 Word 三任务仍继续且结果显示降级提示。
6. 执行“智能编写”，确认 `/provider/debug-last.taskType=word.smart_write`，模型后台命中智能编写应用；结果显示本次命中的术语/规则摘要，既有对照和写回行为不变。
7. 执行“智能仿写”，可先框选模板段落再打开任务；填写仿写需求和参考素材后确认 `/provider/debug-last.taskType=word.smart_imitation`，结果区显示知识命中摘要，且只有预览/纯文本/复制，不显示对照和应用预览。
8. 执行“文档审查”，优先框选 3 到 10 个段落联调；确认 `/provider/debug-last.taskType=word.document_review`，结果区显示知识命中摘要、审查摘要和问题列表。
9. 执行“格式审查”，可框选局部段落；确认结果区显示“审查概览 / 优先处理清单 / 详细问题 / 诊断信息”，字体标准为“宋体”、字号标准为“小四（12pt）”，且不使用写作规范。
10. 打开 WPS Excel，确认 Ribbon 下只有“智能分析”“公式助手”和“设置”；选择一块表格区域后执行分析，确认 `/provider/debug-last.taskType=excel.analysis`，结果区显示数据概览、关键发现、风险异常、建议动作和汇报段落。使用慢模型验证 180 秒以上任务仍持续轮询，不提前提示连接失败。
11. 按公式助手操作手册逐项记录 `HasFormula`、`Formula`、`FormulaLocal`、`FormulaR1C1` 可用性和降级结果；验证 30×20、空选区、混合值/公式、超长公式、外部引用、版本敏感函数、虚构函数 `FOOBAR` 的核对提示、独立工作流、慢模型排队、重开续查和复制。每个场景前后核对单元格值/公式、工作表清单和计算模式完全一致。
12. 打开 WPS 演示，确认 Ribbon 下只有“智能总结”“结构审查”和“设置”；在当前页模式分别测试“主标题 + 副标题 + 正文”和“仅主标题 + 正文”，确认副标题可选且不混入正文。
13. 在文档模式分别测试 UTF-8 `.md`、有效 `.docx`、损坏 DOCX、不支持类型和超过 10 MB 文件；确认页数只允许 5、8、10、12、15 且默认 10，结果给出整套逐页建议和复制动作，任何场景都不修改 PPT。
14. 使用慢模型验证 180 秒以上任务仍持续轮询；状态查询短暂中断或重开任务窗格后恢复同一任务，不重复调用 `/files/upload` 或 `/chat-messages`。
15. 分别连接旧版 `inputs.query` 工作流和新版“用户输入”节点工作流；新版首次 HTTP 400 后应自动以 `inputs: {}` 重试成功，`/provider/debug-last.inputMode=user-input-node`，文档任务的两个模式都保留相同 `files` 引用。
16. 使用结构审查验证 60 页整套、超过 60 页整套拒绝和不超过 60 页显式页段；记录主副标题分离、无标题页有限兜底、本地与模型问题去重、单次模型调用、慢任务恢复和结论/目录复制结果。
17. 结构审查前后分别记录幻灯片数量、顺序、主标题和副标题摘要，确认完全一致；不得创建、删除、重排或修改幻灯片。
18. 在麒麟 V10 目标机上安装 adapter 开机自启动：进入 adapter 启动包目录后执行 `bash scripts/install_autostart.sh 18100`，重启系统后执行 `bash scripts/status_adapter.sh 18100` 验证 `adapter_health=reachable`。
19. 如果模型后台有调用但 WPS 结果为空，检查回复节点是否绑定 LLM 输出正文，而不是开始节点原始 query。
20. 如果 `provider=mock` 或 `skipReason=provider_not_configured`，检查任务级 API Key 文件是否已保存，以及统一 API URL 是否带 `/v1`。

## 8. 遗留项

- 智能排版暂缓：目标机已确认任务级 API Key 选路可命中独立 Dify 工作流，但长文档角色识别受 Dify 输出最大值和模型上下文窗口限制影响。当前版本不再尝试自动写回排版，改为“格式审查”。
- 文档审查要求 Dify 输出 Markdown 中的 JSON 代码块。若现场 Dify 只能输出普通 Markdown，也应至少保留一个合法 `json` 代码块；adapter 会从代码块中提取问题列表。
- Excel/WPS ET 对象模型仍需在目标机真机验证，尤其是 `SheetSelectionChange`、`Selection`、`UsedRange`、`Cells.Item(row, column)`、`HasFormula`、`Formula`、`FormulaLocal` 和 `FormulaR1C1` 的可用性；智能分析保留已用范围兜底，公式助手严格不使用 `UsedRange` 并按三条公式属性只读降级。
- PPT/WPS WPP 的主标题和普通正文读取已有上一版本目标机基础；结构审查 Slides 集合遍历、主副标题分离、60 页边界、无标题页有限兜底、慢任务恢复及幻灯片只读前后摘要，连同 Markdown/DOCX 上传、三宿主工作流设置、写作规范管理和覆盖安装，仍需用 `v0.22.0-alpha` 正式包完成目标机验收。
- 历史操作文档中仍可能保留旧版本部署背景；当前交付和配置以本 handoff、README 及 `docs/operations/` 下当前手册为准。
