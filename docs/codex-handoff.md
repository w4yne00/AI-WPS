# Codex Handoff - AI-WPS

## PR #241 审查修复：资料导入（2026-09-22）

- 导入结果使用真实 DOM 文本赋值；回归测试覆盖浏览器渲染。
- 保留正文中的换行、制表符，读取嵌套内容控件内的段落和表格；出处新增 `bodyPath`（从正文起的 XML 子节点索引路径），用于区分同一内容控件中的片段。
- 表格展开前限制每表最多 256 列、整份资料累计最多 100000 个展开单元格（含补齐的空单元格）；超限返回 `MATERIAL_TABLE_OVER_LIMIT`，不截断。这些是实施安全参数，响应 `limits` 中公开 `tableColumnLimit` 和 `tableCellLimit`，并沿用 `productConfirmed: false`。

## 当前修复：增量文本预览不再读秒（2026-09-22）

- 开启流式后，智能编写和智能仿写的结果预览在正文到达前改为增量文本预览提示，并带等待态标记；不再把「总耗时：N 秒」写进预览。只有任务真实可停止时才写「可以停止生成」；正在停止时改为停止中说明。
- 未开启流式，以及事件接口降级后的状态轮询，结果预览仍保留原来的读秒提示。
- 正文到达后撤掉等待态。`setPlainResult`、`setResult` 和文档审查结果重绘也会撤掉，避免失败或切到审查后仍显示生成中。

## 当前修复：默认开启已验证流式并保证模型配置跨重启持久化（2026-09-21）

- `AI_WPS_ENABLE_DIRECT_STREAMING` 改为默认开启，显式 `0` / `false` 继续作为运维回滚；`streamingCapability == validated` 的服务/模型门禁保持不变，默认开启不等于跳过能力验证。
- 根因定位确认目标机曾在源码测试目录与正式安装目录之间切换运行，工作流配置仍保存在源码目录的 `config/adapter.json`，正式安装进程读取 `$HOME/ai-wps/state/adapter.json`，并非配置文件被删除。
- Python 运行时与 Shell 启动脚本新增当前安装代际识别：只有 `current` 实际指向该 release 时，未配置环境变量的手工启动或 systemd 启动才自动绑定共享 `state/backups/var`。显式绝对路径继续优先，非当前旧 release 保持隔离。
- 回归测试跨两个 release、两个全新 Python 进程创建并恢复真实工作流档案和 Key，防止重启或覆盖升级后回退到 release 内空配置。

## PR #225 审查修复与目标机人工验收候选（2026-09-20）

- 删除以固定数组、预填延迟和源码字符串存在性冒充性能验收的断言；保留实际调用流式解析、Provider 回退、协调器取消/容量和任务窗格停止动作的行为测试。
- 清除目标机记录中的虚构 p50/p95/p99、时间和证据编号。真实模型、真实 WPS、30 次 blocking/streaming 对照、窄窗焦点与滚动仍为 `manual-pending`，Issue #213 不因自动化测试关闭。
- PR #225 原候选曾保持 `AI_WPS_ENABLE_DIRECT_STREAMING=0`；该默认策略已由 2026-09-21 当前修复与 ADR-0133 取代，历史审查结论不再代表当前源码默认值。
- Preview 覆盖升级门禁改为让旧 Adapter 保持运行后再次执行安装器，以验证安装器自行停止旧进程、事务式替换 Adapter 与三宿主插件、保留旧式/现代 Key、规范库数据库、历史和备份，并启动健康的新进程；另注入组件切换失败，验证旧文件、旧运行数据和旧 Adapter 自动恢复。安装器在停机后、完整事务 trap 建立前增加早期失败补偿，候选预检或事务准备失败不再把旧服务留在停机状态。
- 完整交付包及本轮自动化结果以本次最终构建输出为准；目标机人工验收记录见 `packaging/v0260-preview1-target-machine-acceptance.md`。

## 当前功能实现：Issue #212 整合流式性能优化交付与回滚合同（2026-09-20）

- **PR #224 审查修复**：生产链路统一识别真实对象形态的 `streamingCapability.status`，并将 `directStreamingEnabled` 与事件协议选择冻结到任务快照；任务窗格依据 Adapter 返回的 `streamingEnabled` 选择事件长轮询或 3 秒状态轮询，恢复记录保留同一协议。候选审计新增组装产物运行时探针，可识别能力对象退化为字符串比较的集成错误；目标机验收模板补齐每个试点任务、每个模型组合至少 30 次 blocking/streaming 对照与 p50/p95/p99 证据矩阵。
- **交付白名单与候选门禁整合**：遵循 ADR-0132、实施计划 Task 11 与 Issue #212 规格，将完成的交互文本流式（Word 智能编写与智能仿写）、毫秒级性能诊断（Word/Excel/PPT 九类任务）和任务窗格优化正式纳入交付白名单与候选门禁。在 `packaging/delivery-sources-v0260-preview1.json` 中补齐 `docs/operations/runtime-config.md`（`direct_text_stream.py` 位于白名单中），确保组装交付树完整包含流式运行时与配置说明。
- **运维配置与回滚合同完备文档化**：`docs/operations/runtime-config.md` 增设“交互文本流式、毫秒性能诊断与回滚合同”独立章节，详尽规范特性环境变量（`AI_WPS_ENABLE_DIRECT_STREAMING`，默认 `0`）、五元组流式能力探针判定与任务快照冻结、阻塞降级回退机制、运行中任务取消边界（Adapter 关闭当前上游响应并释放本地资源，不承诺供应商立即停止生成或计费；尚未调用模型的准备期取消保持零模型调用）、脱敏诊断规范、资源与耗时边界守护（256 事件环、512 KiB 纯文本快照、5 MiB 总响应体超限即止 `MODEL_RESPONSE_SIZE_LIMIT`、25s 长轮询超时、50ms/4KiB DOM 节流渲染与 30px 阈值智能跟随滚动）。
- **零破坏性迁移的即时关闭与平滑降级**：
  - **特性即时回滚**：当环境配置 `AI_WPS_ENABLE_DIRECT_STREAMING=0` 时，后续新任务直接走原有阻塞调用与 3 秒状态短轮询；运行中任务按提交时快照安全收敛，零破坏性数据迁移；
  - **任务窗格自动降级**：当 `/events` 长轮询接口返回 404（旧版 Adapter）或连续 3 次长轮询失败时，正式任务窗格无感回退至 3 秒状态短轮询，不破坏文档会话、不重置配置存储、不清理历史；
  - **字段向后兼容**：新增 `streamingCapability` 为附加属性，旧版 Adapter 安全忽略，历史配置载入时安全默认赋予 `not_checked`；
  - **只读预览不可写回不变量**：取消与失败保留内存只读预览以供查看与复制，严格禁用写回（`applyEnabled = false`）且不归档历史（`history_store` 零条目）。
- **交付审计脚本与候选门禁增补**：`packaging/audit_v0260_preview1_delivery.py` 增补 `audit_streaming_and_rollback_contract(root)`，严格校验交付产物中流式服务模块 `direct_text_stream.py`、运维说明与边界常量、目标机验收文档章节以及任务窗格降级调用；`packaging/v0260-preview1-delivery.md` 与 `packaging/v0260-preview1-target-machine-acceptance.md` 补全对应说明与核验项。
- **旧原型独立性保障**：旧 `wps-addon` 原型严格不增加流式实现与 `/events` 轮询逻辑，保持既有测试与构建完全独立、互不干扰。
- **全量验证结论**：
  - 本地后端全量（浏览器组装门禁单独运行）：`1505 passed / 54 skipped / 1 deselected`；麒麟 V10 ARM64 / Python 3.8 全量：`1505 passed / 55 skipped`；
  - 正式插件非浏览器契约 `272/272 passed`，沙箱外真实 Chrome 视口 `1/1 passed`；流式交付与降级专项 `5/5 passed`；
  - `wps-addon` vitest 单元测试：`12/12 passed`，Vite 生产构建成功；
  - Python 3.8 兼容性扫描 182 个当前生产与交付文件全部通过，`git diff --check` 与修改后 JavaScript 语法检查通过；本轮未生成正式候选归档，提交级 provenance 与完整交付构建待变更提交后执行；
  - 候选状态保持 `candidate`，目标机真机验收（Kylin V10 SP1 ARM64 / WPS 12.1.2）维持 `manual-pending`（绑定 Issue #154），说明自动化测试不替代真实环境人工复测。

## 当前功能实现：Issue #211 优化 PPT 任务毫秒诊断、结果校验与只读交互（2026-09-20）

- **PR #223 审查修复**：结果门禁改为校验已知 `resultType`、完整结果信封、合法审查范围和结构化数组，同时保留后端明确支持的纯文本降级结果；长任务协调器新增单调 `terminalAgeMs`，任务窗格仅在所属会话的结果真实渲染后记录 `completionToFirstRenderMs`，不再为历史视图、其他文档或校验失败结果伪造首渲染耗时；单页/文档总结未配置模型统一记录 `providerOutcome = not_attempted`；运行中设置页所有写入口补齐 `state.busy` 门禁，诊断卡按 `traceId` 选择对应本地耗时。
- **PPT 两类任务毫秒性能诊断扩展**：遵循 ADR-0132 Task 2 与 Issue #211 规格，将既有写作、审查与 Excel 性能诊断扩展至 PPT 两类核心任务（`ppt.slide_assistant` 幻灯片与文档智能总结、`ppt.structure_review` 结构审查）。长任务轮询接口与协调器终态诊断对外暴露统一单调毫秒指标（`elapsedMs`、`phaseElapsedMs`、`phaseDurationsMs`、`queueWaitMs`、`metrics`），并保留现有秒级兼容字段（`elapsedSeconds`、`phaseDurations`）；阻塞调用首包耗时严格为 `null`（`providerFirstVisibleMs = None`）。
- **阶段耗时与真实上游结果捕获**：单页/文档总结与结构审查细分阶段（`preparing`、`provider_processing`、`parsing`），在发生模型超时或网络错误时真实记录 `providerOutcome`（`provider_timeout` 或 `provider_error`）及标准错误码，未配置模型时准确记录为 `not_attempted`。
- **任务窗格全链路性能度量与高级诊断展示**：PPT 任务窗格在 `state.taskPerformanceByJobId` / `state.taskPerformanceByTraceId` 维护最多 50 条按创建顺序有界淘汰的性能记录，记录用户操作全生命周期毫秒耗时（点击到本地反馈 `clickToFeedbackMs`、本地数据准备 `localExtractionMs`、点击到 Adapter 接受请求 `clickToAdapterAcceptedMs`、完成到首渲染 `completionToFirstRenderMs`）。高级诊断卡片按当前 `traceId` 展示对应的 `## 任务窗格本地耗时` 章节。
- **总结与结构审查结果严格全结构化校验**：`validateSlideAssistantResult` 严格校验单页总结（有效标题、要点、结论或正文）与全篇文档总结（幻灯片列表、封面、摘要或正文）；`validateStructureReviewResult` 严格校验审查范围与结构化建议/问题数据。校验不通过时安全置为失败，绝不渲染伪造或残缺结果，不更新活动结果视图。
- **运行中只读与管理入口交互隔离**：执行期间 `setRunDisabled(true)` 严格禁用会改变运行中任务的操作（来源模式切换、文件、幻灯片数量、指令输入、幻灯片范围、模型配置修改与重复提交）；同时保留设置/历史入口（`btn-open-settings`、`btn-open-history`）与既有结果复制（`btn-copy-result`、`btn-copy-structure-result`）等无冲突只读行为。在 `state.busy` 期间拦截直连服务新增/编辑/删除/模型覆盖保存等变更动作。
- **后台任务完成会话隔离与历史无感查看**：`finishJob` 与 `finishStructureJob` 支持 `targetDocSession` 隔离，终态结果更新至对应演示文稿会话缓存；当用户正在查看历史（`state.historyOpen = true`）时，后台完成仅递增未读角标并提示“请返回查看”，绝不强制跳转覆盖当前历史视图。
- **全量验证结论**：
  - 麒麟 V10 ARM64 / Python 3.8 最终全量后端：`1484 passed / 55 skipped`；本地当前测试树为 `1497 passed / 54 skipped`，唯一额外失败是受限环境内嵌套启动 Chrome，已在沙箱外单独通过同一真实浏览器用例。
  - 正式插件契约共 `268` 项：`267` 项非浏览器用例通过，`1` 项真实浏览器用例在沙箱外通过；PPT 专项 `30/30 passed`（性能诊断与只读交互专项 `8/8 passed`）。
  - `wps-addon` vitest 单元测试：`12/12 passed`，Vite 生产构建成功。
  - 真实 Chrome 下 PPT 任务窗格在 `320px`、`420px` 视口均无横向溢出；真实 WPS 交互仍未复测。

## 当前功能实现：Issue #210 优化 Excel 任务反馈、诊断与智能填写抽取（2026-09-20）

- **PR #222 审查修复**：智能填写 yielding 抽取由整行步进下沉为单元格游标步进，50 列宽表不再等整行完成后才检查 32ms 预算；来源抽取、取消或会话切换失败时保留既有只读预览；可恢复活动任务只在来源冻结与会话复核成功、即将提交 Adapter 时落盘，分片准备期重载不再轮询不存在的后台任务。同步修复测试文件末尾空行门禁。
- **Excel 三类任务毫秒性能诊断扩展**：遵循 ADR-0132 Task 2 与 Issue #210 规格，将既有写作与审查性能诊断扩展至 Excel 三类核心任务（`excel.analysis` 智能分析、`excel.formula_assistant` 公式助手、`excel.smart_fill` 智能填写）。长任务轮询接口与协调器终态诊断对外暴露统一单调毫秒指标（`elapsedMs`、`phaseElapsedMs`、`phaseDurationsMs`、`queueWaitMs`、`metrics`），并保留现有秒级兼容字段；阻塞调用首包耗时严格为 `null`。
- **智能填写即时反馈（杜绝静默点击与白屏等待）**：重构 `runExcelSmartFillAction`，点击后立即同步设置 busy 状态、状态栏和结果卡提示，展示取消按钮，并记录 `clickToFeedbackMs`（<100ms），随后才进入异步分片单元格抽取，杜绝 WPS COM/JSAPI 同步阻塞导致界面无响应。
- **单调时钟分片让出事件循环**：来源抽取（最多 25,000 单元格）由 `extractExcelSmartFillSourcePayloadYielding` 和 `analyzeExcelSmartFillSourceRangeYielding` 驱动，按单调时钟时间预算（默认 32ms，目标 <50ms）分片执行，片段间通过宏任务 `setTimeout(0)` 真正让出事件循环并递增上报进度。公式单元格严格剔除正文与表达式（`displayed = ""`），隐藏/合并单元格严格 fail-closed 拦截。
- **准备期取消响应与工作簿会话核验**：分片循环在每次恢复前核验用户取消标记（`state.smartFillCancelRequested`）和活动工作簿会话一致性。用户取消或切换工作簿时立即抛出安全异常并中止，清理任务槽位与状态，严禁提交后台任务，不调用模型服务，不归档历史，杜绝将旧工作簿数据提交至新工作簿。
- **只读不可写回不变量与测试向下兼容**：智能填写全程保持纯只读 Markdown 预览与复制语义。针对既有单元测试桩（显式 stub `buildExcelSmartFillRequest` 或未注入 yielding 抽取器），实现安全平滑同步回退，保持既有生命周期测试 100% 兼容。
- **全量验证结论**：
  - 本地 Docker Python 3.8 全量后端测试：`1491 passed / 55 skipped`；Excel 性能诊断专项 `5/5 passed`，Excel 后端测试 `139/139 passed`。
  - 审查修复后正式插件全量契约测试：`260/260 passed`（Python 3.8/Node Docker 环境）；Excel 专项 `118/118 passed`，分片抽取专项 `9/9 passed`。
  - `wps-addon` vitest 单元测试：`12/12 passed`，Vite 生产构建成功。
  - Python 3.8 兼容性语法编译 `compileall` 与 `git diff --check` 全部通过。
  - 审查修复未改 Adapter，未复跑后端全量、真实 WPS 或 25,000 单元格真机总耗时基线；自动化分片预算测试不替代真机性能验收。

## 当前功能实现：Issue #209 分片执行 Word 全篇与格式审查抽取（2026-09-20）

- **PR #221 审查修复**：分片调度下沉到单张表的单元格、嵌套表和单段字符格式递归内部，大型选区改走异步段落抽取；默认预算统一为 32ms。全篇与格式审查从准备开始冻结文档会话和编辑信号，在分片、上传与提交边界持续核对；删除生产代码中的测试专用虚拟时钟参数和未使用的 `runChunkedArray` 导出，保留现有按函数切片测试所需的同步回退。
- **Word 全篇与格式审查抽取分片让出事件循环**：遵循 ADR-0132 Task 1 与 Issue #209 规格，针对 Word 长文档在全篇审查（`word.document_review.full`）与确定性格式审查（`word.format_review.deterministic`）抽取阶段容易长时间阻塞 JS 单线程导致 WPS 界面挂起的问题，将段落、表格、图片盘点与格式区段抽取改造为按单调时钟时间预算（默认 32ms，目标 ≤ 50ms）分片执行。在片段之间使用宏任务 `setTimeout(step, 0)` 真正让出事件循环，让 UI 事件（取消点击、状态栏更新、重绘）能够及时响应。
- **分片循环取消检查与编辑信号监测**：在每次分片恢复执行前，严格检查任务取消标志（`state.deterministicFormatReviewCancelRequested` / `state.reviewPreparationCancelled`）、当前活动文档会话一致性（`getActiveDocumentSessionId()`）及文档版本（`revision`）。一旦检测到用户点击取消或文档发生切换，抽取循环立即抛出 `CANCELLED` 异常并安全中断。
- **取消后清理未提交快照与零模型外发**：抽取被取消时，任务窗格在 `catch` 块中立即调用 `discardFullDocumentReviewSnapshot` 或 `discardDeterministicFormatReviewSnapshot` 向 Adapter 发送 `DELETE /word/document-review/snapshots/{snapshot_id}` 或 `DELETE /word/format-review/snapshots/{snapshot_id}`，清理已在 Adapter 登记但未提交的快照，不创建后台审查长任务，不调用模型服务，不消耗 Token。
- **跨运行时哈希与合同绝对保持一致**：分片抽取后得到的数据结构与原同步抽取 100% 等价。全篇审查的两遍哈希、审查字符数、段落与表格结构；格式审查的四项跨运行时权威哈希（`contentSha256`、`structureSha256`、`formatSha256`、`reviewCharacterCount`）、覆盖统计、图片外发门禁与报告合同与分片前完全一致。性能优化不扩大审查范围、不静默截断对象，也不降低信任门禁。
- **测试替身向下兼容与向后兼容**：在 `taskpane.js` 中支持 `extractDeterministicFormatReviewSnapshotYielding` / `extractFullDocumentReviewBodyYielding` 异步流，若测试桩中未注入 yielding 版本，自动回退同步执行，保持既有 20-tick 单测精确兼容。
- **全量验证结论**：
  - 分片抽取专项测试 `formal-plugin-kit/tests/word-review-chunked-extraction.test.js`：12/12 通过，新增覆盖单张大表内部让出、单段格式递归内部让出、大型选区异步抽取、进度单调、会话切换中断和未提交快照 DELETE。
  - 正式插件全量契约测试（含沙箱外真实 Chrome 视口门禁）：246/246 全部通过。
  - `wps-addon` vitest 单元测试：12/12 全部通过，Vite 生产构建成功。
  - 本轮审查修复未改 Adapter，未复跑 Docker/Kylin Python 3.8 全量后端；PR 原提交记录为 1487 passed、54 skipped，不替代本轮目标环境复测。
  - 代码格式与规范：`git diff --check` 通过。

## 当前功能实现：Issue #208 扩展 Word 审查任务性能诊断（2026-09-20）

- **PR #220 审查修复**：三类 Word 审查任务新增独立 `localExtractionMs`，不再以“点击到 Adapter 接收”混代本地抽取；三宿主高级诊断展示近期任务的 `phaseDurationsMs`。格式审查工作流调用补齐成功与异常路径的阻塞 Provider 指标，确定性格式审查按真实语义结果记录 `success`、`not_attempted`、`degraded` 或 `provider_error`；报告读取失败不再伪造首渲染耗时。
- **Word 三类审查任务毫秒性能诊断扩展**：遵循 ADR-0132 Task 6 与 Issue #208 规格，将既有写作任务性能诊断能力扩展至 Word 三类核心审查任务（受限文档审查 `word.document_review`、全文审查 `word.document_review.full`、确定性格式审查 `word.format_review.deterministic`）。
- **秒级与毫秒级耗时指标严格并存**：保持现有秒级字段（`elapsedSeconds`、`phaseElapsedSeconds`、`phaseDurations`）完全向后兼容；同步在长任务轮询接口与终态诊断公开毫秒级指标（`elapsedMs`、`phaseElapsedMs`、`phaseDurationsMs`、`queueWaitMs`、`metrics`）。阶段耗时字典准确记录 `extracting`、`provider_processing`、`parsing`、`chunking`、`aggregating` 等各阶段实际消耗时长，彻底消除估算或伪百分比。
- **阻塞调用首包时间严格置空**：所有阻塞性 Provider 调用（包含受限审查、全文分块与聚合、格式审查语义增强调用）在协调器中显式记录 `providerFirstVisibleMs = None`（JSON 序列化为 `null`），杜绝伪造首包可见时间。
- **受限审查真实上游结果与错误码记录**：受限文档审查（`word.document_review`）在发生上游 Provider 超时、连接失败或受控降级时，准确捕获并记录真实 `providerOutcome`（`provider_timeout` 或 `provider_error`）及标准 `errorCode`（如 `PROVIDER_TIMEOUT`、`PROVIDER_HTTP_ERROR`），终态诊断与轮询响应忠实反映真实 Provider 执行结果。
- **零数据与内容泄露规范**：性能度量指标严格局限于时长、计数（`aiCallCount`、`aiAcceptedCount`、`chunkCount`）、阶段标识与状态码；绝不包含、传输或日志记录任何中间审查问题、合规结论、原始正文、提示词或模型应答内容。
- **前端全链路性能记录与高级诊断展示**：Word 任务窗格在 `state.lastTaskPerformance` 记录三类审查任务全生命周期耗时（点击到本地反馈 `clickToFeedbackMs`、本地抽取 `localExtractionMs`、点击到 Adapter 接受请求 `clickToAdapterAcceptedMs`、完成到首渲染 `completionToFirstRenderMs`）。高级诊断卡片展示 `phaseDurationsMs`、`providerOutcome` 及任务性能摘要，完全兼容既有报告展示、历史归档与会话恢复逻辑。
- **全量验证结论**：
  - 本地 Docker Python 3.8 全量后端测试：`1487 passed / 54 skipped`；审查性能专项 `7/7 passed`。
  - 正式插件非浏览器 Node 契约测试全部通过；真实 Chrome 视口用例本轮未复跑。
  - `wps-addon` vitest 单元测试 `12/12 passed` 且生产构建通过。
  - Python 3.8 兼容扫描 96 个文件、三宿主 `node --check` 与 `git diff --check` 通过。
  - 审查修复后未复跑麒麟 V10、真实 WPS 或真实 Provider；此前结果不替代本轮目标环境验收。

## 当前功能实现：Issue #207 将增量文本预览扩展到智能仿写（2026-09-19）

- **PR #219 审查修复（2026-09-19）**：前端在提交写作任务时按任务与文档会话冻结文档负载，后台乱序完成、模式切换、历史返回及最终写回均恢复并使用所属智能编写结果的提交快照，不再读取可能已被智能仿写覆盖的全局负载；后台完成也不再向当前仿写视图泄漏写回资格。Standalone 写作取消响应的顶层 `message` 改为返回权威任务状态，与 FastAPI 在 `running`、`cancelled`、`completed` 竞态下保持一致。
- **增量文本流式与只读预览扩展至智能仿写**：遵循 ADR-0132 Task 5 与 Issue #207 规格，智能仿写（`word.smart_imitation`）全量复用 `direct_text_stream.py` 直连模型流式调用与解析能力。在直连模型具备 `streamingCapability == "validated"` 且 `AI_WPS_ENABLE_DIRECT_STREAMING=1` 时，发起 `stream: true` 增量生成。
- **只读不可写回不变量全生命周期保持**：智能仿写全程保持纯只读无写回语义。任务窗格在排队、连接中、等待首包、增量流式生成、取消中、已取消、失败以及完成的所有状态下，严格保持 `applyEnabled = false`（“应用”按钮禁用与隐藏），且强制隐藏“修改比对”视图（`hideCompareForSmartImitation()`），杜绝向 Word 文档写回。
- **取消与失败残缺正文保留及零历史归档**：智能仿写被取消或异常中断时，任务窗格保留已接收的只读正文快照供查看与复制；取消与失败任务严格不写入历史记录（`history_store` 零条目），只有成功完成的仿写任务按 `word.smart_imitation` 任务类型归档历史。
- **任务槽位与预览严格会话隔离**：长任务协调器按 `(host, taskType, documentSessionId)` 独立管理任务槽位；`writingJobPreviews` 预览缓存与 `activeWritingJob` 状态按 `taskType::documentSessionId::jobId`（`consumerKey`）严格隔离，智能编写与智能仿写互不干扰、互不抢占槽位与覆盖预览。
- **FastAPI 与 Standalone 接口对等与修复**：修复 Standalone Adapter 缺失取消路由问题，双运行时对等支持 `GET /word/smart-imitation/jobs/{job_id}/events`（长轮询、序号恢复与 snapshot 重置）及 `DELETE /word/smart-imitation/jobs/{job_id}`（直连流式支持 running 取消，阻塞回退保持 queued-only 取消返回 409 `LONG_TASK_NOT_CANCELLABLE`）。
- **全量验证结论**：本地 Docker Python 3.8 全量后端测试 `1478 passed / 55 skipped`，流式、任务与取消专项 `36/36 passed`；正式插件 Node 契约测试 `233/233 passed`；`wps-addon` vitest `12/12 passed` 且生产构建通过；Python 3.8 兼容性扫描 196 文件全部通过；`git diff --check` 通过。

## 当前功能实现：Issue #206 运行中流式任务取消、上游中断与长等待边界（2026-09-19）


- **PR #218 审查修复（2026-09-19）**：协调器为当前流式响应登记一次性取消回调，停止请求会主动 `shutdown` 上游 socket，不再依赖正文继续到达，也不采用会破坏 Python `BufferedReader` 的短 socket timeout 轮询；取消先接受时普通 runner 返回仍收敛为 `cancelled`，且待 50ms flush 的正文在取消后不再发布。streaming→blocking 回退会原子撤销运行中取消能力，30 秒等待提示不再越权显示停止按钮；事件接口降级为状态轮询后仍保留取消/失败的只读部分预览。事件响应新增稳定的 `previewTruncated` 标志并提示 512 KiB 预览上限，5 MiB 响应上限继续公开 `MODEL_RESPONSE_SIZE_LIMIT`。
- **流式任务运行中取消与按需按钮状态**：遵循 ADR-0132 Task 4 与 Issue #206 规格，长任务协调器 `LongTaskCoordinator` 与 `writing_jobs.py` 支持直连流式任务（`streamingCapability == "validated"` 且 `AI_WPS_ENABLE_DIRECT_STREAMING=1`）的运行中取消（`allow_running_cancel=True`）；阻塞任务严格保持排队阶段后不可取消，绝不显示虚假取消按钮。
- **UI 快速响应与上游连接立即切断**：前端任务窗格点击“停止生成”后，在 <100ms 内同步更新为“正在停止”（disabled=true）及“正在停止生成，请稍候...”；协调器立即将任务阶段标记为 `stopping`，`direct_text_stream.py` 在读取循环与行切分循环中通过 `cancel_checker()` 检测中断，抛出 `LongTaskCancelled`，并在 `finally` 块中立即关闭上游 HTTP 响应 socket，立即停止向客户端推送 delta 增量。
- **权威状态竞态裁决与幂等终态**：协调器通过互斥锁严格仲裁停止请求与正常完成提交：若取消请求先被协调器接受，任务终态收敛为 `cancelled`；若模型完整响应已先行提交完成，终态锁定为 `completed`，后续停止请求幂等返回完成状态。同一任务终态仅产生唯一的终态事件和历史记录。
- **残缺正文只读预览、零历史归档与写回禁用**：被取消或中断（中途网络断开、模型错误）的流式任务，终态分别收敛为 `cancelled` 或 `failed`；前端任务窗格保留已接收的正文预览内容（供查看与复制），但严格不写入任务历史（`history_store` 零归档），且严禁赋予智能编写写回（“应用”）权限（`setApplyEnabled(false)`）。中途断开连接不再进行自动阻塞重试。
- **非 SSE/不支持响应的安全单次回退**：仅在首个可见文本 delta 产生之前，若上游返回 400/404/415/422/非 SSE 响应，允许平滑回退至阻塞调用最多一次；一旦产生首个可见 delta，任何后续错误均作为终态 `failed` 处理，杜绝二次调用与双份计费。
- **资源与耗时边界守护**：事件环形缓冲区最大 256 项，预览文本快照最大 512 KiB，模型总响应体最大 5 MiB（超限抛出 `MODEL_RESPONSE_SIZE_LIMIT` 稳定错误码）。Delta 停止延迟 p95 ≤ 500ms，任务槽位本地释放 ≤ 2s。
- **渐进式等待反馈（10s / 30s）与零伪百分比**：10 秒内未收到可见文本时展示“模型响应较慢，请稍候...”，30 秒未收到可见文本时展示“模型后台仍在响应中，请继续等待...”并提供“停止生成”入口；全过程杜绝虚假百分比进度条。首个 delta 到达或终态发生时立即清理等待定时器。
- **审查修复验证结论**：本地 Docker Python 3.8 全量后端测试 `1471 passed / 54 skipped`，取消与流式专项 `69/69 passed`；正式插件 Node 契约测试 `233/233 passed`（真实 Chrome 视口门禁在沙箱外补跑）；`wps-addon` vitest `12/12 passed` 且生产构建通过；Python 3.8 兼容性扫描 196 文件全部通过；`node --check` 与 `git diff --check` 通过。审查修复后未重跑麒麟 V10 ARM64、真实 WPS 或真实模型服务验收。

## 当前功能实现：Issue #205 智能编写文本流式增量渲染与只读预览（2026-09-18）

- **PR #217 审查修复（2026-09-19）**：流式正文改为 64 KiB 有界读取，每次读取前把底层 socket timeout 收缩至剩余 deadline，并在读取后再次校验总时限；按 SSE 空事件边界组装多 `data:` 字段，同时保留脱敏 usage。非 SSE 响应在关闭首连接、累计任务与 trace 诊断中的 Provider attempt 后回退阻塞调用。增量事件只保留 `delta`，完整正文仅保留单份 512 KiB 快照；不足 4 KiB 的首段正文通过独立定时器在 50ms 内发布，UTF-8 上限截断不再产生空事件。任务窗格把首次连接和缺口恢复快照作为对应序号的权威正文，不再重复或遗漏事件环外文本。
- **直连模型流式调用与解析**：遵循 ADR-0132 Task 3 与 Issue #205 规格，新增独立流式解析服务 `direct_text_stream.py`。严格只在 `AI_WPS_ENABLE_DIRECT_STREAMING=1` 且所选直连服务具备已冻结的 `streamingCapability == "validated"` 时向模型服务发起 `stream: true` 请求。在产生任何可见文本前，若模型返回 400/404/415/422/501 或非 SSE 响应，平滑回退至阻塞调用；一旦产生首个可见文本增量，绝不再发起阻塞重试。
- **SSE 增量解析与推理内容过滤**：流式解析器具备跨网络块缓冲与 UTF-8 多字节边界安全拼接能力，兼容多行 `data:` 事件、空事件与 `[DONE]` 终止符。严格过滤并剥离跨分片 `<think>...</think>` 标签及 `reasoning_content` / `reasoning` 字段，确保思考过程绝不进入正文预览与最终交付内容。
- **Adapter 节流聚合与单调发布**：`LongTaskCoordinator` 提供 `publish_text()` 与 `flush()`，以最多每 50ms 或累计 4 KiB 的节流窗口聚合文本增量；维护单调自增 `sequence`、增量内容 `delta`、已消费总字节数 `offset`、首包耗时 `firstVisibleMs`，并将正文快照严格限制在 512 KiB 有界缓冲区内。
- **任务窗格只读纯文本增量渲染**：前端长轮询在接收到 `delta` 事件或 `previewSnapshot` 时，以 `requestAnimationFrame` 驱动只读纯文本更新；严格保持 `white-space: pre-wrap` 的纯文本视图，生成中不解析 Markdown、不进行差分比对、不执行写作规范校验，杜绝卡顿与不完整语义误判。
- **智能跟随滚动与状态恢复**：前端实现距离底部 30px 阈值的智能滚动跟随：生成过程中用户向上滚动查看时锁定当前位置，滚动回底部时自动恢复跟随。窗格关闭重开、模式切换（如切换至文档审查再切回）及文档切换时，从本地状态和最新快照精确恢复当前文档会话的未完结预览。
- **终态平滑交接与边界隔离**：后台任务终态后无缝切换至既有权威结果处理管线（受限 Markdown 渲染、差分展示、写作规范合规检查、活跃结果及历史归档）；严格不增加运行中任务取消 UI 或端点（保留由 Issue #206 独立实现）。
- **审查修复验证**：本地后端 `1461 passed / 54 skipped / 1 deselected`，被排除的组装插件浏览器门禁在沙箱外单独通过，因此合计 `1462` 项通过；正式插件 `233/233`（含沙箱外真实 Chrome 视口）通过，`wps-addon` `12/12` 且生产构建通过，Python 3.8 兼容扫描 196 文件及 `git diff --check` 通过。审查修复后未重跑麒麟 V10 ARM64、真实 WPS 或真实模型服务验收。

## 当前功能实现：Issue #204 直连模型流式能力探针验证与任务快照冻结（2026-09-18）

- **PR #216 审查修复（2026-09-18）**：流式探针改为逐行有界读取，累计响应严格限制为 5 MiB，并以单调时钟限制总等待时间；仅在收到 `[DONE]` 或非空 `finish_reason` 后接受成功，SSE 错误事件、异常结束和连接中断均不再记录 `validated` 或触发阻塞重试。探针正文在任务合同校验前统一剥离跨增量 `<think>` 内容；删除基于实例覆盖 `post_task` 绕过探针的测试感知分支，既有竞态与文档审查测试改为模拟真实 SSE 网络边界。
- **特性开关与前端接口传导**：遵循 ADR-0132 Task 7，新增 `AI_WPS_ENABLE_DIRECT_STREAMING` 特性环境变量与 helper `direct_streaming_enabled()`，默认保持关闭（`0`），仅当显式设为 `"1"` 时启用。FastAPI 与 Standalone 运行时通过 `/config` 端点在 `features.directStreamingEnabled` 中对等暴露。
- **流式能力五元组绑定与状态流转**：`DirectServiceStore` 维护模型流式能力状态（`validated`、`unsupported`、`stale`、`not_checked`），强绑定 `serviceId`、`serviceRevision`、规范化 `serviceBaseUrl`、`apiKeyFingerprint`（SHA-256 前缀）及精确 `modelName`。当服务地址、API Key、版本号或任务所选模型发生任何变更时，旧能力结论立即可靠降级为 `stale`。
- **真实流式探针与不支持时阻塞回退**：复用现有任务选择验证机制（`validate_task_model_selection`），向服务发送携带 `stream: True` 与 `Accept: text/event-stream` 的最小探针调用。当模型支持流式且满足现有任务合同（`_validate_probe_answer`）时，能力标记为 `validated`；当模型不支持流式（返回 400/415/422 或非 SSE 响应体）时，平滑回退至既有阻塞验证调用，校验通过后能力标记为 `unsupported`；当遇到认证失败（401/403）或网络错误时，立即抛出对应异常且绝不记录虚假能力。
- **任务认证快照冻结**：`ProviderClient.resolve_task_auth` 在任务提交时冻结当前的 `streamingCapability` 快照；运行中修改服务配置或轮换 Key 不影响当前执行中任务的既有判定，旧任务依据既有快照和 Key 失效机制安全收敛。
- **零安全泄露与有界存储**：`DirectServiceStore` 对模型流式能力记录实施 50 条上限的 LRU 淘汰清理；存储与调试日志严格禁止保存原始 API Key、提示词正文或模型响应正文，杜绝敏感凭据泄露。普通设置页不增加虚假手动开关，绝不根据厂商或模型名称擅自推断能力。
- **全量验证结论**：本地后端 pytest（组装插件浏览器门禁单独在沙箱外运行）合计 `1426 passed / 54 skipped`；麒麟 V10 ARM64 / Python 3.8 全量为 `1425 passed / 55 skipped`。流式能力专项 `11/11` 通过，覆盖错误事件、异常终止、纯推理内容、5 MiB 上限、总超时和测试注入分支；正式插件 Node 测试继续为 `232/232 passed`，Python 3.8 兼容性扫描 174 个文件全部通过，`git diff --check` 无格式异常。

## 当前功能实现：Issue #203 为智能编写建立可恢复增量任务事件（2026-09-18）

- **PR #215 审查修复（2026-09-18）**：事件终态完成后改为复用现有状态查询取得权威 `result`，避免首个 tracer 不携带正文时丢失生成结果；长轮询消费者按 `taskType/documentSessionId/jobId` 维护版本令牌，旧消费者、跨文档进度和后台终态不再污染当前任务；events 404 优先平滑降级，FastAPI 与 standalone 共用参数归一化并恢复一致的缺失任务 envelope。
- **后台长任务增量事件与非忙等待**：遵循 ADR-0132 与 Issue #203 契约，`LongTaskCoordinator` 为每个任务维护最多 256 项的有界环形事件队列（`_events`）与单调递增 `latestSequence`；`wait_events()` 基于 `threading.Condition` 实现非忙等待与超时唤醒（`waitMs` 上限 25000ms）；客户端请求超出环形缓冲范围时自动返回 `resetRequired=True` 与 `previewSnapshot` 快照，确保断线恢复不丢状态。
- **阶段扩充与首个 Tracer 边界**：阶段枚举扩充 `provider_connecting`、`provider_waiting`、`streaming`、`stopping`；首个 tracer 严格只传输真实阶段与终态事件，绝不提前发布模型正文，严格不改变现有 queued-only 取消语义（正文预览与运行中取消分别归属 #205 与 #206）。
- **FastAPI 与 Standalone 双运行时对等**：对等实现 `GET /word/smart-write/jobs/{job_id}/events` 和 `GET /word/smart-imitation/jobs/{job_id}/events`，统一参数校验、25 秒等待上限、超时空响应信封与 404 错误信封对等性。
- **Word 任务窗格事件消费与平滑降级**：`taskpane.js` 实现 `pollWritingJobEvents`，按文档会话消费阶段推进，终态（完成/取消/失败）统一释放任务槽位并同步结果；当接口返回 404（旧版本 Adapter）或连续 3 次长轮询失败时，平滑降级回退至现有 3 秒状态短轮询，用户无感知。
- **审查修复验证**：本地后端 `1410 passed / 54 skipped`，受沙箱浏览器限制的组装插件门禁单独在沙箱外通过，因此共 `1411` 项通过；麒麟 V10/Python 3.8 为 `1410 passed / 55 skipped`。正式插件 `232/232`（含真实浏览器视口）、`wps-addon` `12/12` 且 Vite 构建通过，Python 3.8 兼容扫描 77 文件及 `git diff --check` 均通过。

## 当前功能实现：Issue #202 建立毫秒级性能诊断（2026-09-17）

- **PR #214 审查修复（2026-09-18）**：指定 `traceId` 的 Provider 诊断查询改为精确命中，未知或已淘汰任务返回空数据，不再回退到全局最近记录；三宿主高级诊断携带当前任务 `traceId`，近期终态任务同时显示任务编号和任务类型。
- **耗时语义修复**：毫秒阶段取整余量归入最后实际执行阶段，轮询状态与终态诊断均满足阶段合计等于总耗时；九类模型任务完整透传执行控制。直连与工作流在非法 JSON、HTTP 错误体、超时、连接失败和响应中断时仅保留已实际观测的阶段，未到达阶段明确为 `null`；超过 4 KiB 或读取中断的错误体不再冒充完整响应。
- **多次调用累计与前端任务隔离**：同一任务的兼容重试、格式降级和智能填写纠正调用累计 `providerAttempts` 及 Provider 阶段耗时，协调器与 trace 诊断不再只保留最后一次。Word 点击、Adapter 接受和首渲染指标按 `jobId/traceId` 关联；首渲染在 DOM 更新后的 `requestAnimationFrame` 记录，帧前切换任务不会回写当前诊断。FastAPI 内外层 503/411/413 均统一记录 `durationMs`。
- **审查修复验证**：本地相关后端 `180/180`、正式插件专项 `3/3`；本地后端 `1403 passed / 54 skipped / 1 deselected`，被排除的组装浏览器门禁单独通过，因此共 `1404` 项通过；麒麟 V10/Python 3.8 为 `1403 passed / 55 skipped`。正式插件 `231/231`（含本地真实 Chrome 320px/420px）、Python 3.8 兼容扫描 77 文件及 `git diff --check` 均通过；独立最终复审为 `Ready to merge: Yes`。
- **毫秒级阶段与耗时暴露**：遵循 ADR-0132 与 Issue #202 验收标准，`LongTaskCoordinator` 在保留现有秒级 `elapsedSeconds`、`phaseElapsedSeconds` 兼容字段的同时，新增毫秒级单调耗时指标 `elapsedMs`、`phaseElapsedMs`、`phaseDurationsMs`（阶段细分耗时字典）和 `queueWaitMs`（排队等待时长）；终态诊断输出与 `/jobs/{id}` 轮询响应完全对齐。
- **直连模型调用耗时分解**：`ProviderClient` 记录阻塞模型调用的完整网络阶段耗时，包括响应头到达 `providerHeadersMs`、完整响应体接收完成 `providerCompleteMs`、JSON 响应解析 `parseMs`；首个可见内容延迟 `providerFirstVisibleMs` 严格记录为 `null`（绝不伪造非流式首包时间）。指标同时记录至长任务协调器与调试记录中。
- **按 traceId 隔离的脱敏诊断**：直连模型调试信息新增支持按 `traceId` 隔离索引（最多保留 50 条），`/provider/debug-last?traceId=...` 端点支持按任务 trace 查询上游调用诊断，消除单槽位竞态；继续严守零用户正文、零提示词、零增量内容、零 API Key、零本地绝对路径的脱敏规范。
- **FastAPI 与 Standalone 行为一致**：Standalone Adapter 的 HTTP 访问日志与 FastAPI 中间件统一记录请求耗时 `durationMs`；公开端点及响应结构保持绝对等价。
- **前端任务窗格性能度量**：Word 任务窗格在 `state.lastTaskPerformance` 记录用户操作全链路毫秒级耗时：点击到本地视觉反馈 `clickToFeedbackMs`、点击到 Adapter 接受请求 `clickToAdapterAcceptedMs`、完成到首渲染 `completionToFirstRenderMs`；高级诊断面板以脱敏方式展示上述端到端指标，并在 Word、Excel、PPT 三大宿主统一规范终态耗时显示格式。
- **验证**：全量后端测试（1386 passed, 54 skipped）、正式插件套件（231 passed）、Python 3.8 兼容性检查（172 文件）、`git diff --check` 全部通过。

## 当前设计：交互文本流式与任务窗性能优化（2026-09-17，待实施）

- 已基于远端 `main` 提交 `50aa6abe4b12` 完成只读性能审计，并与用户确认设计树；当前只新增领域术语、ADR 和实施计划，尚未修改业务代码。
- 决策：保留后台任务及轮询恢复，以毫秒级观测和 WPS COM/JSAPI 分片为 P0；首期只为模型直连的 Word 智能编写、智能仿写提供带序号长轮询增量预览和真实上游响应取消。
- 增量正文仅作内存只读预览，可查看、复制，不进入历史、不写回；工作流平台和结构化任务首期不展示残缺输出。
- 架构决策见 `docs/adr/0132-preserve-background-jobs-while-streaming-interactive-text.md`，可执行任务见 `docs/superpowers/plans/2026-09-17-ai-wps-interactive-streaming-performance-plan.md`。
- 首个候选版以 `AI_WPS_ENABLE_DIRECT_STREAMING=1` 显式启用；麒麟 V10、WPS 12.1.2 真机指标通过前不得改为默认开启。

## 当前修复：Excel 点击反馈与智能填写只读预览（2026-09-17）

- Excel 工作簿会话不再依赖代理对象上的随机属性：已保存路径、未保存窗口句柄及保存/另存为别名共同维护同一打开期身份；同一工作簿的新代理、多窗口和首次保存保持任务归属，重新打开旧路径仍与另存后的工作簿隔离。
- 智能分析、公式助手在异步读取 WPS 选区前，同时更新状态栏和结果卡；取数失败时恢复已有结果与复制文本，没有旧结果时在结果卡显示失败原因。
- 智能填写前端收敛为“来源范围与填写意图 → Markdown 结果预览 → 复制”：移除写入、返回修改、开始新填写、目标绑定、结果编辑勾选和逐项重试入口，不再从正常 UI 调用工作簿写入。
- 智能填写复制结果使用两列制表符文本，模型值中的制表符与换行转为空格，避免粘贴时意外拆分额外单元格；后台旧写回接口仅保留兼容，本轮未删除。
- 验证：本地正式插件 `231/231`（含真实 Chrome）通过；UTM Kylin V10 ARM64 正式插件 `231/231` 通过；`wps-addon` `12/12` 且 Vite 构建通过。

## 当前修复：任务结果回显、Excel 点击反馈与设置页细节（2026-09-16）

- 同一 Preview 版本的不同源码候选不再复用静态资源缓存键：任务窗格、辅助脚本、Ribbon 与 Word 启动页统一使用 `0.26.0-preview.1-<source commit prefix>`，前端诊断显示同一构建身份；交付审计拒绝缺少提交号的缓存身份。
- Word、Excel、PPT 设置页移除“接入选择”叹号，标题与下拉框增加 8px 间距；直连和工作流“新建”统一为紧邻标题的 50×32 紧凑按钮，直连空状态居中，工作流冗余当前配置摘要移除。
- Word“写作规范库”标题与状态增加 6px 间距；Excel 智能分析、公式助手在进入 WPS 取数前立即显示校验反馈，三类 Excel 任务遇到模型配置写操作时不再静默返回。
- 当前源码继续保留上一轮 Word/PPT/Excel 完成结果恢复与安全 Markdown 渲染逻辑；本轮通过提交级缓存隔离确保目标机加载该逻辑，而不是同版本旧脚本。
- UTM 测试机地址更新为 `cloud@192.168.64.3`；该机为新环境，Python 测试虚拟环境位于 `/data/home/cloud/.venvs/ai-wps-test-py38`。
- 验证：UTM Python 3.8/aarch64 全量后端 `1381 passed / 55 skipped`，正式插件 `225/225`，`wps-addon` `12/12` 且 Vite 构建通过，Python 3.8 兼容扫描 82 文件通过；本地真实浏览器 320px/420px 下三宿主无横向溢出，按钮为 50×32、接入间距为 8px。
- 真实 WPS：Word 设置页已核对叹号移除、按钮一致、空状态居中、工作流摘要移除和写作规范间距；Excel 旧覆盖层成功复现“点击状态只写入隐藏节点”，新覆盖层确认加载后 Ribbon 未重新出现，故修复后的 Excel WPS GUI 仍标记为未复测。测试覆盖层已恢复为验证前插件备份。

## 当前修复：活动结果回显与三宿主模型设置收口（2026-09-15）

- Word 写作/格式审查、PPT 结构审查和 Excel 分析/公式助手在任务窗格恢复时若后台已完成，现会把所属文档的终态结果恢复到当前预览；Word 恢复写作结果继续保持只读，不获得写回资格。
- PPT 结构审查的模型原始 Markdown 改走既有安全渲染器；结构化结果仍使用原有结构化 DOM。
- Word、Excel、PPT 设置页移除自定义模型标识控件；默认模型改为服务目录下拉选择。旧自定义模型记录保留后端读取兼容，但不能在新设置页重新保存。
- 最大输出 Token 和上下文容量接受非负整数且不设产品级上限，`0` 或空统一保存为未设置；仍保留输入预算关系校验和具体任务的安全门禁。
- 三宿主统一“刷新”/“验证服务”横向操作、下行小字目录状态和 `aria-live` 验证反馈。
- 验证：正式插件 220/220 通过（含真实 Chrome 视口）；Docker Python 3.8 为 1379 passed / 54 skipped；`wps-addon` 12/12 且 Vite 构建通过；Python 3.8 兼容扫描 96 文件通过。

## 当前修复：共享直连健康误判与三宿主设置页一致性（2026-09-15）

- 健康校验同时识别旧工作流配置与共享直连服务/任务选择；合法 `direct_svc_*` 激活关系不再被误判为 `MODEL_CONFIGURATION_DATA_INVALID`，真实悬空或不匹配引用仍进入恢复模式并保持 fail-closed。
- Word、Excel、PPT 设置页统一系统字体层级、接入选择文案、紧凑“新建”按钮、卡片右上角帮助控件和空状态隐藏；320px/420px 真实浏览器检查无横向溢出。
- 验证：Python 3.8 健康/直连/迁移专项 77 项通过；正式插件 220 项通过（含真实 Chrome）；`wps-addon` 12 项及 Vite 构建通过；Python 3.8 兼容扫描 191 文件通过。

## 当前功能实现：Issue #182 整合迁移、容量、安全与三宿主交付验证（2026-09-14）

- 在最新 `origin/main`（含 Issue #181 迁移合入）上核对父规格 #164：九类任务共享直连、活动结果与只读历史的代码路径已由 #165–#181 落地。
- 公开边界测试锁定一份共享服务绑定九类任务、工作流配置不受影响、被引用服务不可删除，以及九类历史只归档成功结果并剥离 Key/路径/请求头。
- 三宿主契约测试锁定设置首页共享直连单 Key 录入、工作流仍按任务确认 Key，以及结果区历史查看/清空/返回且无写回入口。
- 操作文档、验收清单和 Preview 白名单与最终公开合同对齐：`docs/operations/shared-direct-service.md`、`docs/operations/task-result-lifecycle.md`，并更新 `workflow-profile-management.md`、`packaging/v0260-preview1-delivery.md`、`packaging/v0260-preview1-target-machine-acceptance.md`。
- 验证：Docker Python 3.8 `pytest adapter_service/tests` 为 1363 passed / 56 skipped；正式插件 `node --test formal-plugin-kit/tests/*.test.js` 为 210 passed（哈希合同使用 `AI_WPS_HASH_CONTRACT_PYTHON`）；`wps-addon` vitest 12 passed 且 Vite 构建通过；Python 3.8 兼容扫描 172 文件通过。未完成麒麟 V10 / 真实 WPS 验收，保持 `candidate` / `manual-pending`。

## PR #199 第三轮审查修复（Issue #181，2026-09-14）

- 交付白名单补入 `direct_migration_txn.py`，生命周期测试从组装后的 Adapter 目录实际导入迁移运行时；普通 `config/adapter.json` 布局的恢复会定位到同级 `run/provider_api_keys`。
- 配置启动、健康检查和直连服务读取统一通过可恢复入口；迁移 journal 采用跨进程文件锁、严格路径/引用校验，损坏状态 fail-closed，快照使用 `0600/0700`、哈希 manifest 和 7 天回滚保留期。
- 提交顺序调整为配置原子发布 → committed 快照完整写入 → journal 标记 `committed`；pending 迁移/重建/放弃与常规直连服务写操作统一使用跨进程锁和 `expectedRevision`，失败保留 pending 状态并遵守 5 服务上限。
- legacy 兼容证明缺失、过期或 Key 指纹不匹配时 fail-closed；三宿主显示待人工处理数量；FastAPI 与 standalone 对 pending 不存在统一返回 404。
- 验证：迁移专项 40 项、直连服务及相关后端 94 项中 93 项通过、1 项既有跳过；交付套件 33 项通过；前端直连契约 59 项通过；Python 3.8 兼容扫描 189 个文件通过。完整后端收集仍受本机缺少 `fastapi` 阻断，未安装新依赖。

## PR #199 审查修复 round 2（Issue #181，2026-09-14）

- 迁移快照自包含 JSON 与被引用 Key；`load_config_payload` 在正式配置不可读时先恢复。恢复后 `resolve_task_auth()` 与迁移后服务 ID、Key 指纹一致。
- 复用已有共享服务时播种 `legacyCompatibility`（绑定 URL、Key 指纹、revision、TTL）；401/403 立即撤销 `legacy_compatible`。
- 提交写事务日志；`os._exit` 后启动协调回滚未提交密钥并清理 staging。恢复记录写失败在 `legacyDirectMigrationRecovery.recordWriteFailed` 可见。
- 未消费档案：`GET /provider/direct-services` 返回脱敏 `legacyDirectPending`；`/provider/legacy-direct-pending` 支持列表、迁移、重建、放弃。三宿主任务窗不新增 pending 管理页。
- URL 规范化拒绝 `userinfo@host`。交付生命周期增加 `preview_legacy_direct_migration`（超限、认证解析、截断恢复）。
- 本轮未在 Docker Python 3.8 或麒麟上跑完整交付构建。

## PR #199 审查修复（Issue #181，2026-09-14）

- 已迁移活动任务在目录尚未拉取前以 `legacy_compatible` 保持可运行；`resolve_task_auth()` 不再因空 `modelList` 抛出 `DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE`。
- 不完整草稿逐字段保留有效 URL 或 Key，保持未激活。
- 同任务未消费的旧直连档案写入 `legacyDirectPending`，迁移状态 `pending_manual`，不删除对应配置和 Key。
- 迁移在暂存目录校验后再提交；保留 `.pre-direct-migration` 备份，`BaseException`（含 `SystemExit`）回滚；截断 JSON 可从备份恢复。
- URL 规范化折叠主机名大小写、IDNA 与默认端口；复用已有共享服务时默认模型冲突置空 `defaultModel`。

## 当前功能实现：Issue #181 迁移旧直连配置并收缩旧写入合同（2026-09-13）

- **旧直连配置自动分组与迁移（覆盖全量 9 类任务）**：
  - 遵循 Issue #164 父规格与 ADR-0130，对历史遗留的 `direct_model` 配置按 `(normalized_service_base_url, api_key_fingerprint)` 强分组；
  - 迁移入口全量覆盖 9 类任务（Word 4 类：智能编写、智能仿写、文档审查、格式审查；Excel 3 类：智能分析、公式助手、智能填写；PPT 2 类：智能总结、结构审查）；
  - 任务模型、温度、Token、图片参数（`imageInputMode`）及激活状态完整迁移至对应的 `taskModelSelections`；
  - 缺失 Key 或不完整的旧配置迁移为未激活草稿；同一组内模型标识冲突时保留各任务独立选择并将共享服务 `defaultModel` 置空；
  - 迁移在内存副本与临时目录中执行，经过全量自检与引用验证后原子切换；失败时零副作用回滚；切换成功后安全清理孤立旧 Key 文件；
  - 若形成的共享直连服务超过 5 组，迁移进入受限保护状态（`status = "restricted"`, 错误码 `DIRECT_SERVICE_MIGRATION_LIMIT`），绝不擅自删除或覆盖配置。
- **旧直连写入合同全面收缩与退役**：
  - `POST/PATCH /provider/model-configurations` 及其 API Key 替换、副本创建与外部授权接口严格拒绝 `access_method == "direct_model"`，统一返回 HTTP 400（错误码 `MODEL_CONFIG_DIRECT_WRITE_RETIRED`）；
  - `WorkflowProfileCompatibilityStore` 兼容层严格限定仅访问 `workflow_platform` 配置；
  - Word、Excel、PPT 三大宿主模型配置编辑器（Workflow Profile Editor）全面下线 `direct_model` 选项、模型名输入框及温度/Token 高级配置，直连模型录入与管理统一收敛至共享直连服务管理体系。
- **测试覆盖与质量验证**：
  - 前端：新增 `formal-plugin-kit/tests/direct-model-contract-shrinkage.test.js` 验证三大宿主配置编辑器移除直连输入；回归 Word/Excel/PPT 工作流设置与共享直连服务套件；
  - 后端：新增 `adapter_service/tests/test_direct_service_migration.py` 覆盖 9 类任务迁移、冲突解决、原子回滚、孤立 Key 清理及 5 服务上限受限模式；更新 `test_direct_services.py` 覆盖写入合同退役 400 拦截；
  - 静态检查：`git diff --check` 通过，Python 3.8 py_compile 语法检查通过，受保护路径（`config/adapter.json`、`run/` 等）零触碰。

## 当前功能实现：Issue #180 迁移 Word 文档审查的直连接入（2026-09-13）

- **文档审查共享直连服务收敛**：遵循 Issue #164 父规格、ADR-0128/ADR-0129/ADR-0130，将 Word 宿主下的文档审查任务（`word.document_review`）平滑迁移接入设置页首页的共享模型直连服务，与格式审查（PR #197）、智能编写、智能仿写及 Excel、PPT 直连接入架构保持完全一致；
- **独立参数覆盖与默认继承**：文档审查可绑定任意已配置的共享直连服务，未覆盖模型时自动继承服务级默认模型（`defaultModel`），并支持独立调优 `temperature`（0.0–2.0）、`maxOutputTokens`（1–16384）、`contextWindowTokens`（1000–2000000）及高级手填自定义模型；同时各自保留独立的工作流平台配置；
- **全篇审查前置门禁严格 Fail-Closed**：
  - 限量审查门禁：服务存在、URL 存在、API Key 存在、有效模型存在且模型可用；
  - 全篇审查就绪度门禁：显式输出 Token 必填（`explicit_output_tokens_required`）、显式上下文容量必填（`explicit_context_tokens_required`）、最大输出 Token 必须 >= 2048（`output_tokens_too_small`），全部满足且模型可用时标记为 `ready`；未满足时前端入口明确披露原因并禁用启动；
- **快照认证冻结与 Key 轮换失效**：
  - 全篇审查提交时生成快照 `authIdentity`，严格冻结服务 ID、模型名、Token 参数、服务 `revision` 及 API Key 哈希指纹；
  - 发生 Key 轮换或删除时，通过 `LongTaskCoordinator` 立即失效运行中和排队中的任务，防止失效凭据继续穿透；
- **任务窗格单行紧凑入口与前置预检**：
  - 任务窗格紧凑单行模型配置入口下拉菜单展示共享直连服务，支持即时激活与失败自动回滚；
  - `runDocumentReview` 与 `runFullDocumentReview` 执行前调用 `validateActiveDirectTaskSelection("word.document_review")` 进行服务就绪性前置校验；
- **测试覆盖与质量验证**：
  - 前端：新增 `formal-plugin-kit/tests/word-document-review-direct-service.test.js`（5/5 通过），回归 `word-shared-direct-service.test.js`（15/15 通过）、`word-format-review-direct-service.test.js`（10/10 通过）、全量正式插件套件（192 项非浏览器测试全绿通过）；
  - 后端：新增 `adapter_service/tests/test_word_document_review_direct_service.py` 覆盖继承、参数覆盖、全篇就绪度门禁、认证解析与删除保护；
  - 静态检查：`git diff --check` 通过，Python 3.8 兼容扫描（160 文件）通过，受保护路径零改动。

## PR #197 审查修复（2026-09-13）

- Word 格式审查共享直连服务支持服务默认模型、任务模型和参数覆盖；图片模式默认 `openai_image_url`，可关闭。
- 文本语义未验证或验证失效时，后端不调用模型，仍完成确定性审查并报告 `format_semantic_protocol_not_ready`。前端保留模型目录/配置可用性检查，不因语义验证待完成而阻止确定性任务。
- 格式语义验证绑定服务 ID、规范化完整端点、现有 API Key 指纹、有效模型、温度、输出 Token、上下文容量及图片模式。草稿验证只记录被验证身份，每个任务保留一份待保存草稿记录；保存时原子匹配，不能把草稿 A 的成功写到当前选择 B。失败重验记录失败，验证期间服务身份变化返回 409。
- 图片外发需用户单独授权；普通保存不刷新失效授权。新增任务级 `image-authorization` 和 `validate-image` 接口，FastAPI 与 standalone 共用存储/验证逻辑。任务窗格提供授权、撤销和视觉验证按钮；授权提交携带确认时的服务 revision，配置变化时拒绝旧确认；视觉验证发送合成 PNG，并检查模型返回的八色排列顺序。接口及操作顺序见 `docs/operations/word-format-review-direct-validation.md`。
- 视觉验证记录也绑定完整调用身份，并在落盘前核对当前选择及授权。运行时图片策略拒绝 `stale` 记录，Key 或端点变化后不能沿用旧视觉许可。
- 验证：Docker Python 3.8 直连、格式审查和模型配置相关回归 305 项通过；前端专项 95 项通过（含沙箱外 Chrome 布局测试）；`wps-addon` 单元测试 12 项和 Vite 构建通过；Python 3.8 兼容扫描 167 文件通过；交付源码体验契约测试 6 项通过。新增公开接口用例模拟模型 HTTP 响应并检查实际 PNG 请求，不消耗真实模型费用。
- 本轮未生成发布包，不替代真实 WPS、实际模型服务或麒麟目标机人工验收。

## PR #195 复审修复（2026-09-13）

- PPT 首页与设置页先应用 `/config.taskApiKeys`，再读取任务配置及共享直连服务；配置未完成或读取失败时阻断新任务提交。任务配置视图合并当前服务 ID，激活成功同步接入方式，失败恢复原服务。
- 请求错误保留 HTTP 状态、错误代码、响应数据及 `referencedTasks`；自定义模型保存可复用相同服务和模型的持久化验证结果，服务端仍负责 URL、Key 和模型变化后的失效检查。
- 新增完整 `taskpane.js` 初始化、真实菜单失败回滚、409 响应、重开保存和提交拦截测试。后端测试通过两个 `/ppt/*/jobs` 公开接口提交并轮询到完成，在模型传输边界核对共享服务、Key、模型和任务参数，无真实模型付费调用。
- 本轮 Docker Python 3.8 相关后端测试 96 通过；专项前端测试 21 通过，`wps-addon` 单元测试 12 通过、Vite 构建通过，Python 3.8 兼容扫描 76 个生产文件通过。最终正式插件非浏览器测试 166 通过、0 失败；此前全量运行的 `format-review-issue-cards.test.js` 因 Chrome 启动失败未通过，最终验证排除此浏览器用例。独立复核确认工作流保存后状态刷新及不完整直连配置阻断问题已解决。本轮不替代目标机人工界面验收。

## PR #196 复审修复（2026-09-13）

- Excel 三任务保存直连选择时只调用原子激活接口，删除先行 PUT；激活成功后同步任务的 `activeProfileId`、`accessMethod` 和响应中的 `taskModelSelection`，再加载配置及共享服务，避免刷新恢复旧服务。
- 重开窗格后可复用同任务、同服务、同模型的持久化手填验证状态；服务端继续检查地址、Key 或模型变化后的失效。
- 新增 18 项前端回归测试，执行真实保存、配置加载和共享服务加载函数，覆盖刷新一致性、失败保持、验证复用及不匹配拒绝。新增后端测试核对三任务在缺少服务默认模型时激活失败且完整配置不变。
- 本轮专项前端 30/30、全部 Excel 测试 95/95 通过，JS 语法及 `git diff --check` 通过。使用本地 Python 运行直连服务及模型目录测试，39 通过、2 失败；失败均为模型目录测试导入 API 时缺少 `fastapi`，新增原子失败测试通过。未安装依赖，未执行麒麟或真实 WPS 界面验收。提交前再次复测 Excel 95/95，Python 3.8 兼容扫描 76 文件通过；对源码目录执行交付审计返回 `V0260_MANIFEST_MISSING`，本轮未组装交付包，不能视为交付验收通过。

## 当前功能实现：Issue #178 迁移 Excel 公式助手与智能填写的直连接入（2026-09-13）

- **三任务共享直连服务统一收敛**：遵循 ADR-0128/ADR-0130 与 Issue #164 父规格规范，将 Excel 宿主下的公式助手（`excel.formula_assistant`）与智能填写（`excel.smart_fill`）平滑迁移接入设置页首页的共享模型直连服务（`#excel-task-direct-service-section`），与智能分析（`excel.analysis`）及 Word、PPT 保持完全一致的直连服务交互架构；
- **任务模型覆盖与独立调优**：公式助手与智能填写可绑定任意已配置的共享直连服务，默认继承服务级默认模型（`defaultModel`），并支持任务级覆盖 `modelName`（支持标准目录选择或高级手填自定义模型）、`temperature`（0.0–2.0）、`maxOutputTokens`（1–16384）与 `contextWindowTokens`（1000–2000000），同时各自保留独立的工作流平台配置；
- **任务窗格单行紧凑入口与隐私保护**：紧凑单行模型配置入口展示格式严格遵循 `[状态圆点] 配置名称 · 模型直连 ›`，绝不向界面泄漏具体模型 ID；下拉菜单选项展示服务名称与解析后任务模型，支持即时激活与失败自动回滚；
- **动态标签与独立状态隔离**：设置页「Excel 任务」三选项卡（智能分析、公式助手、智能填写）动态联动直连配置卡片标题（`智能分析接入选择`、`公式助手接入选择`、`智能填写接入选择`）与参数输入，验证与保存请求（`POST /provider/task-model-selections/{taskType}/validate` 及携带完整任务模型选择的 `POST /provider/direct-services/{id}/activate`）精确路由至当前任务，避免状态串扰；
- **就绪门禁与生命周期保护保持**：接入前置就绪门禁（`validateDirectTaskSelectionReadiness`），在目录失效、过期或高级手填未经验证时阻断任务提交；删除保护（`evaluateDirectServiceDelete`）与服务地址变更影响披露（`evaluateDirectServiceUrlImpact`）自动关联披露被引用的表格公式助手与智能填写任务；
- **质量验证**：
  - 前端：`formal-plugin-kit/tests/excel-shared-direct-service.test.js` 12 项测试全绿，全量 Excel 测试 77 项全绿，正式插件套件 171 项测试全绿；
  - 后端：`adapter_service/tests/test_direct_services.py` 23 项测试全绿；
  - 静态检查：`git diff --check` 通过，Python 3.8 语法兼容性检查通过。

更新时间：2026-09-13

当前仓库：`https://github.com/w4yne00/AI-WPS.git`

当前分支：`codex/issue-153-v026-preview-candidate`

当前版本：`v0.26.0-preview.1`

版本规则号：`AI-WPS-WORD-EXCEL-PPT-0.26.0-preview.1`

`v0.26.0-preview.1` 已通过 Issue #153 汇总来源先行智能填写、自动/手工/疑似目录、格式位置问题组和九任务紧凑模型配置入口，并沿用中性 Preview 交付边界。当前自动化候选为 `dist-preview-delivery-kit/ai-wps-delivery-20260922-a0d6f5d-v0260-preview1.tar.gz`（SHA-256：`0de62be125b52420d899220322a9d2a3544fc50184aa1d0baf5d4ed089111631`，源码提交：`a0d6f5d1e772f9bdce2da59e9953918e6d2306dd`），已通过完整回归、Python 3.8 生命周期门禁和发布审计。目标机人工验收绑定 Issue #154，仍保持 `manual-pending`；自动化 `candidate` 不等于真实 WPS、模型或目标机验收通过。上一自动化候选 `dist-preview-delivery-kit/ai-wps-delivery-20260917-e3b896c-v0260-preview1.tar.gz` 已被本轮候选替代，但继续保留原字节供审计追溯。

`v0.25.3-alpha` 是已验收基线：当前唯一自动化候选为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.3-20260826-d1a346b0d7e1301f74b37e692664fd31085ee050`，源码提交为 `d1a346b0d7e1301f74b37e692664fd31085ee050`，归档为 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260826-d1a346b-v0253.tar.gz`，SHA-256 为 `120a2cfd8decd956224c3702721d85846bdaecf91d71b87b31c0f7be1b258cb7`，目标机验收状态为 `target-accepted`（Issue #59 已完成并关闭）。冻结的 `v0.25.2-alpha` 唯一自动化候选仍为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.2-20260825-850871c10a17f03c8a58abd02ca58c2f3fc70fc9`，源码提交为 `850871c10a17f03c8a58abd02ca58c2f3fc70fc9`，归档为 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260825-850871c-v0252.tar.gz`，SHA-256 为 `c5d663d1249147104bee66790fea60f5e15675418a51c0c1a7a0fc028a285a92`，自动化状态为 `candidate`。图像语义补充默认开启与视觉关闭降级保持不变。

冻结的 `v0.25.1-alpha` 唯一自动化候选仍为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`，源码提交为 `d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`，归档为 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz`，SHA-256 为 `ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`，自动化状态为 `candidate`。其直接前任 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-10b251dd52ea6b6c2d60faa9cf0ab37b3ccdc2a5` 已登记为 `rejected`，SHA-256 为 `6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120`，拒绝原因是包内目标机验收记录同时出现当前候选、无当前候选和重复上一被拒绝归档叙述；两份归档均保持原字节。d7a1dd8 不再登记为 0.25.2 的当前候选。

组装 d7a1dd8 归档内的 `docs/v0251-target-machine-acceptance.md` 包含绑定当前候选的生成上下文；源码 `packaging/v0251-target-machine-acceptance.md` 仍是构建前生成器输入模板，保留“当前源树没有活动候选”是其闭合模板契约，不代表组装归档状态。自动化 `candidate` 仍不等于真实 WPS、模型或 Issue #59 目标验收。

历史候选 `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-ccad09f-v0251.tar.gz`（SHA-256：`2c3f8b5004c40fb7271a6afe7e4c8a292acb227b9d3ec08afc7f6b561d413a02`，源码提交：`ccad09fb1d8019da3a40f14610ab3bd75de1ec23`）已确认存在 `word.format_review.snapshot.v2` JS/Python structure/format 哈希契约漂移，登记为 `rejected`，不得继续分发。`e43dc8c` 及更早候选均为 `rejected`。修复报告见 `.superpowers/sdd/2026-08-24-v0251-format-review-hash-contract-fix/task-1-report.md`。

## 当前版本：v0.26.0-preview.1 Issue #153 汇总候选

- **汇总范围**：合入 Issue #146、#149、#150、#151、#152 的用户可见流程与恢复契约，发布边界由 Issue #153 统一审计；
- **九类任务独立模型配置**：Word 4 类（智能编写、智能仿写、文档审查、格式审查）、Excel 3 类（智能分析、公式助手、智能填写）、PPT 2 类（智能总结、结构审查）统一按任务隔离模型配置、API Key 与接入参数；
- **智能填写严格契约**：生成阶段仅接受同一工作表含表头的连续矩形来源（最多 500 个数据行）和必填填写意图，模型请求不含目标地址、工作簿标识、公式或隐藏数据，模型结果严格限定为 `excel.smart_fill.v2` Schema；写入目标在预览之后单独绑定；
- **长任务生命周期**：复用共享长任务协调器，支持 10 秒短轮询、排队取消、运行中协作取消、部分预览、60 分钟 deadline，任务结果仅进程内保留 2 小时；
- **写入门禁与保护**：写回前重新校验工作簿、工作表、地址、原值与保护状态；空白目标默认允许，已有普通文本/数值需二次确认，公式、合并、受保护单元格始终拒绝，`= + - @` 前缀按纯文本字面值安全写入；
- **写入失败补偿**：单元格写入中途失败时逆序恢复本次已改动单元格并校验恢复结果；补偿失败准确列出人工核对地址；不提供撤销（Undo/OnUndo），成功后销毁临时快照并锁定预览；
- **一次性安装断代**：默认安装根 `$TARGET_HOME/ai-wps`，只读检测历史 `$TARGET_HOME/ai-wps-phase1` 并提示人工重装与重新配置，绝不自动迁移、覆盖或删除历史数据；若 18100 仍被历史 Adapter 占用则释放该端口监听进程；
- **构建与审计闭包**：白名单组装、System Prompt 清单、Wheel、第三方许可证、来源 provenance、文件哈希、Python 3.8 兼容性与生命周期门禁全部闭合；
- **状态记录**：当前自动化候选为 `ai-wps-delivery-20260922-a0d6f5d-v0260-preview1.tar.gz`（SHA-256 `0de62be125b52420d899220322a9d2a3544fc50184aa1d0baf5d4ed089111631`，源码提交 `a0d6f5d1e772f9bdce2da59e9953918e6d2306dd`）；目标机验收绑定 Issue #154 并保持 `manual-pending`。

## 当前功能实现：Issue #177 迁移 PPT 任务至共享直连服务

- **共享直连服务架构收敛**：遵循 ADR-0128 与 Issue #164 父规格规范，将 PPT 宿主的两类任务（智能总结 `ppt.slide_assistant` 与结构审查 `ppt.structure_review`）迁移接入设置页首页的共享模型直连服务（`DirectServiceCard`），与 Word、Excel 保持三宿主完全一致的交互与视觉体验；
- **共享服务与独立选型分离**：
  - 共享直连服务统一管理服务地址、单密码输入 API Key（不回显、无确认输入框）与模型目录拉取/刷新，全局上限 5 个；
  - 任务模型配置选项卡（`ppt.slide_assistant` 与 `ppt.structure_review`）各自独立选择直连服务，支持覆盖自定义模型名、温度（Temperature 0.0–2.0）、最大输出 Tokens 及上下文窗口，并保留独立的类 Dify 工作流平台配置；
  - 任务直接接入直连服务保存时，采用原子激活请求（`POST /provider/direct-services/{id}/activate`），携带完整 `taskModelSelection`，避免分步保存产生的状态不一致；
- **任务窗格单行紧凑入口集成**：PPT 智能总结与结构审查主界面的紧凑单行模型配置入口（`#task-model-config-trigger` + `#task-model-config-menu`）无缝追加共享直连服务选项，支持即时激活与失败安全回滚（`rollbackTaskModelConfigSwitch`），且在设置页不同任务标签间保持精准的状态隔离与通告；
- **执行前置就绪门禁（Preflight Gate）**：
  - 在 `submitPptSlideJob`（智能总结）与 `submitStructureReviewJob`（结构审查）提交前，调用 `validateActiveDirectTaskSelection` 进行直连服务完整性门禁检查；
  - 若直连服务未配置、缺少有效模型或已被删除，立即阻断长任务提交，并在状态栏清晰提示具体原因（如“直连服务未就绪，请先在设置中完成配置”），防止无效请求穿透至后端；
- **引用感知与删除保护**：后端 `DirectServiceStore` 汇总 PPT 两项任务的模型选择引用，被引用的直连服务禁止删除（返回 409 `DIRECT_SERVICE_IN_USE`）；前端删除确认弹窗与服务地址修改影响披露（`evaluateDirectServiceUrlImpact`）自动关联“智能总结”与“结构审查”任务显示；
- **测试覆盖与质量验证**：
  - 前端契约测试：新增 `formal-plugin-kit/tests/ppt-shared-direct-service.test.js`（10/10 通过），全量覆盖页面结构、单密码 Key 字段、5 服务上限、任务参数覆盖草稿、紧凑菜单集成、原子激活与失败回滚、预检拦截阻断、删除保护与地址影响提示；
  - 全量正式插件套件：`formal-plugin-kit/tests/*.test.js` 全部 158/158 测试全绿通过，包括跨宿主体验契约、单行紧凑入口契约、视口布局与跨运行时哈希契约；
  - 后端单元测试：`adapter_service/tests/test_direct_services.py` 与 `test_direct_services_api.py` 22 项测试全绿通过；
  - 静态检查：`packaging/check_python38_compatibility.py` 扫描 165 个 Python 文件通过；JS 语法检查通过；`git diff --check` 无空白或冲突警告；不可触碰路径零改动。

## 当前功能实现：Issue #175 保护共享服务修改并执行 Key 轮换失效

- **版本与并发冲突控制**：遵循 ADR-0128 与 ADR-0129，共享直连服务对象暴露 `revision: int`。所有变更操作（更新属性、替换 Key、清除 Key、更新或刷新模型目录、验证服务、删除服务）强制携带 `expectedRevision` 校验。若发生版本冲突，后端返回 409 `DIRECT_SERVICE_REVISION_CONFLICT`；前端拦截冲突并明确提示版本冲突，要求用户刷新后重新编辑，严格禁止前端自动合并字段或盲目覆盖；
- **引用感知与删除保护**：后端 `_sanitize_service` 汇总 `taskModelSelections` 与 `activeModelConfigurations`，在服务对象中暴露 `referencedTasks: string[]`。被任何任务引用的直连服务禁止删除，后端直接返回 409 `DIRECT_SERVICE_IN_USE` 并附带引用任务列表；前端删除弹窗实时校验引用状态，被引用时禁用删除确认按钮并给出直观的中文任务引用警告；
- **服务地址修改影响面披露**：前端直连服务编辑态支持地址变更影响感知（`evaluateDirectServiceUrlImpact`），当编辑在用服务的地址时，实时披露该修改将影响的具体任务名称，提醒用户保存后各任务将立即调用新地址；
- **Key 安全与单输入操作**：保存的 API Key 绝不回显至前端，输入框严格采用 `type="password"`；Key 的更换与清除采用独立的原子操作，清除操作通过独立的 `DELETE /provider/direct-services/{id}/api-key?expectedRevision={rev}` 执行，更换与清除均不保留旧 Key 历史版本；
- **Key 轮换任务失效机制**：
  - `DirectServiceStore` 在 Key 发生替换或清除时，获取被替换旧 Key 的哈希指纹（`api_key_fingerprint`），并通过监听器广播；
  - `LongTaskCoordinator` 提供按 `service_id + old_key_fingerprint + service_revision` 精确失效的接口，并保留失效墓碑以封闭“认证快照已取得但任务尚未提交”的竞态窗口；
  - 引用旧 Key 指纹的排队中任务（`queued`）立即移出队列并标记为不可恢复失败（`DIRECT_SERVICE_KEY_ROTATED`）；
  - 引用旧 Key 指纹的运行中任务（`running`）触发协作取消，对外状态立即转换为 `failed`（错误码 `DIRECT_SERVICE_KEY_ROTATED`，提示用户重新提交）；结果、报告文件与历史记录统一在协调器锁内提交，失效先发生时不产生成功副作用；全文审阅另持久化不可恢复终态，Adapter 重启后仍返回同一错误码；
  - 已完成任务（`completed`）及历史归档（`TaskHistoryStore`）严格不受 Key 轮换影响；新提交任务可正常使用新 Key 成功执行；
- **测试覆盖**：
  - 后端：协调器矩阵测试覆盖 Word 4 类、Excel 3 类、PPT 2 类任务的认证关联与失效分派；Excel 智能分析真实任务入口验证失效先发生时不会写入 `TaskHistoryStore`，全文审阅协议测试验证可恢复任务在显式轮换后跨重启保持 `DIRECT_SERVICE_KEY_ROTATED`，History API 测试验证轮换前已完成历史仍可读取；另覆盖替换 Key、清除 Key、提交竞态与三类模型目录变更接口的 `expectedRevision` 必填契约；
  - 前端：`formal-plugin-kit/tests/direct-service-lifecycle-protection.test.js` 覆盖页面结构、生命周期辅助函数、删除保护、编辑态版本冲突、Key 清除独立调用，并通过真实 `request()` 错误路径验证 `adapterCode`、`code`、`status`、`data` 与 `referencedTasks` 的透传。

## 当前功能实现：Issue #173 扩展 Excel 智能分析与公式助手的活跃结果生命周期与只读历史

- **文档会话槽位隔离**：遵循 Issue #164 父规格与 ADR-0131，为 Excel 智能分析（`excel.analysis`）与公式助手（`excel.formula_assistant`）建立基于 `host::taskType::docSessionId` 的前后端任务槽位隔离。同工作簿同任务进行中时阻断重复提交（分别返回 409 `EXCEL_ANALYSIS_DOCUMENT_TASK_BUSY` 和 `EXCEL_FORMULA_DOCUMENT_TASK_BUSY`），跨工作簿或不同任务间互不阻塞；
- **提交校验与结果保护**：前端在提交前进行选区提取与需求本地校验。校验失败时严格保留当前活跃结果；校验通过并正式向后端发起提交后，立即清空旧活跃结果并进入生成进度状态；若后端提交或执行失败，仅渲染当前失败错误，严格禁止回滚旧活跃结果；
- **多模式切换与活跃结果隔离**：用户在智能分析、公式助手、智能填写与设置模式之间切换时，各任务活跃结果按 `documentSessionId` 独立保存在 `activeAnalysisResultsBySession`、`activeFormulaResultsBySession` 与 `activeSmartFillResultsBySession` 中。切回时精准恢复对应任务在当前工作簿的活跃成果；切换至设置页时隐藏历史记录按钮，在三个 Excel 任务页均正常展示历史入口按钮；
- **未完成任务恢复约束**：页面初始化或模式切回时，仅恢复与当前工作簿 `documentSessionId`、`host` 及 `taskType` 严格匹配且未完成（`queued` / `running`）的长任务；已处于终态（`completed` / `failed` / `cancelled`）的历史任务清除脏缓存，不回填为前台活跃结果；
- **只读成功历史机制**：智能分析与公式助手的成功结果自动归档至 `TaskHistoryStore`，支持通过 `GET /history?taskType=excel.analysis` 及 `GET /history?taskType=excel.formula_assistant` 查看列表与详情、复制文本、单条删除（`DELETE /history/{id}`）与按任务类型清空（`DELETE /history?taskType=...`）。任务窗格统一支持展开查看详情、复制关键成果（分析汇报段落/Markdown 或推荐公式）与删除；
- **最小化元数据与隐私保护**：
  - 智能分析历史仅持久化结构化报告（`overview`, `findings`, `risks`, `actions`）与纯文本汇报段落（`plainText`），严格排除表格选区数据、原始行列数据与本地绝对路径；
  - 公式助手历史仅持久化推荐公式（`primaryFormula`）、备选公式（`alternativeFormula`）、说明（`explanation`）、组件解析（`components`）、引用范围（`referenceRanges`）、发现问题（`issues`）等计算成果，严格排除用户原始需求提示词与选区单元格数据；
  - 超过 5 MiB 单条上限时自动降级跳过持久化并记录中性提示（`historyNotice`），且不增加未读角标计数；
- **向下兼容保证**：现有智能分析 Markdown 报告、汇报段落双视图切换、公式助手模式切换与复制功能完全保持兼容；
- **测试覆盖与 PR #191 Code Review 修复**：
  - **PR #191 首轮审查修复记录**：
    1. *智能填写草稿与锁定状态保持*：新增 `activeSmartFillStatesBySession` 缓存每工作簿草稿修改、排除项、锁定及消耗状态，模式切换或会话同步通过 `rerenderExcelSmartFillPreview()` 恢复，杜绝 `renderExcelSmartFillResult()` 盲目重置；
    2. *分析/公式任务取消槽位释放*：`finishCancelledExcelAnalysis` 与 `finishCancelledExcelFormula` 支持传入 `boundDocSessionId` 释放 `(host, taskType, targetDocSession)` 槽位，杜绝取消后永久占用槽位；
    3. *异步 DOM 污染防护*：智能分析、公式助手与智能填写的轮询、完成、取消与错误回调均通过 `currentMode === expectedMode && currSession === targetDocSession` 门禁，切换工作簿或模式时不篡改当前 DOM；
    4. *历史响应乱序防护*：引入递增 `historyRequestId` 与 `taskType` 严格匹配，抛弃乱序或串流的历史数据；
    5. *恢复前置查询容灾*：网络超时或瞬态错误（非 404/NOT_FOUND）时保留 localStorage 中的活跃任务，禁止静默清除；
    6. *公式助手诊断降级与隐私*：诊断降级结果（`parseDiagnostic`）不入历史库并标注 `historyNotice`；正常入库条目严格由 `primaryFormula` 派生 `copyText`，杜绝用户提示词或原始回显污染；
    7. *并发槽位与忙碌解耦*：移除基于全局 `state.busy` 的粗粒度跨工作簿阻塞，完全收敛至 `isTaskSlotBusy`，并在选区读取前置 `setExcelTaskBusy(true, docSessionId, taskType)`；
    8. *工作簿切换视图同步*：选区监听器 `updateScopeIndicator` 及 `switchMode` 统一触发 `syncActiveSessionView`，切回工作簿即时还原活跃结果；
    9. *统一终态记录与角标抑制*：提取统一的 `recordFinalizedAnalysisResult` 等终态处理，带有 `historyNotice` 的结果严格不递增未读角标计数；
  - 后端：`adapter_service/tests/test_excel_analysis_formula_history.py` 覆盖请求模型、409 槽位忙碌拦截、并发隔离、脱敏历史写入、超限降级、诊断降级不入库、白名单公式文本派生等场景（7/7 测试通过）；
  - 前端：`formal-plugin-kit/tests/excel-analysis-formula-lifecycle.test.js` 覆盖历史卡片只读渲染、本地校验失败保留旧结果、有效提交清理旧结果与锁定槽位、槽位忙碌拦截、跨模式活跃结果隔离、已完成任务恢复清理、智能填写草稿状态保持、取消任务槽位释放、异步 DOM 隔离、乱序历史丢弃、恢复瞬态网络错误保护、跨工作簿并发提交、降级历史角标抑制等场景（首轮记录：20/20 测试通过，全量 Excel 测试 53/53 通过）。
  - **PR #191 复审修复（2026-09-12）**：三条任务链改用 `excelTaskSessions[taskType + "::" + documentSessionId]` 保存任务编号、轮询计时、错误次数与恢复状态，提交、轮询和取消回调固定引用所属会话；通用忙碌函数改名为 `setExcelTaskBusy`，可见性统一由 `isExcelTaskVisible` 判断，等待提示定时器也必须匹配功能与会话。
  - **填写终态会话归属**：提交时保存来源与单项重试上下文；后台完成仅更新所属会话的结果与保留草稿，不从前台读取其他工作簿的目标、草稿、锁定或消耗状态。切回后恢复所属会话来源，再构建新结果预览。
  - **恢复与历史删除**：分析/公式恢复身份校验通过后立即占用槽位；预查询超时保留任务编号和槽位，下次恢复可重试，明确终态或 404/NOT_FOUND 才释放。历史单条删除的成功及失败响应均校验请求序号与任务类型。
  - **本轮验证**：生命周期测试 32/32、全部 Excel 测试 65/65；新增测试覆盖三条真实提交→轮询链跨工作簿并发、超时后阻断再提交及 404 释放、后台填写终态与单项重试隔离、等待提示和历史删除乱序，以及工作簿监听器尚未同步时的终态来源隔离。`wps-addon` 单元测试 12/12，Vite 构建通过。本轮全量正式插件测试 105 通过、12 失败，与原始 PR 的失败集合一致（Word 既有断言、Python 缺少 pydantic、浏览器测试目录权限）。JS 语法检查、Python 3.8 兼容扫描（95 文件）和 `git diff --check` 通过。本轮未修改后端；麒麟测试机 SSH 超时，后端 7/7 属于首轮记录，不作为本轮复测结果。

  - **既有全量失败修复（2026-09-12）**：格式审查恢复测试改为执行完成、失败、取消三种终态，验证只清理所属文档的存储与槽位、不重载旧报告；哈希测试优先采用显式 `AI_WPS_HASH_CONTRACT_PYTHON`，未设置时使用仓库 `.venv`，最后回退 `python3`，Python 子进程通过 `AI_WPS_VAR_DIR` 将历史等运行态数据保存在测试临时目录；浏览器视口测试在独立临时目录保存通信文件，使用参数数组启动 CLI，结束后清理目录。本轮全量正式插件测试 **119/119 通过，0 失败、0 跳过**，包含真实 Chrome 的 320px/420px 检查；Chrome 在允许启动浏览器的沙箱外测试进程运行。该结果取代上一阶段 105 通过、12 失败的状态；本轮没有新增依赖或修改生产逻辑，也不替代麒麟 Python 3.8 真机验证。

## 当前功能实现：Issue #172 扩展 Excel 智能填写的只读历史与活跃结果生命周期

- **文档会话槽位隔离**：遵循 Issue #164 父规格规范，为 Excel 智能填写任务（`excel.smart_fill`）建立基于 `host::taskType::docSessionId` 的前后端任务槽位隔离。同工作簿同任务进行中时阻断重复生成提交（返回 409 `EXCEL_SMART_FILL_DOCUMENT_TASK_BUSY`），跨工作簿互不阻塞；
- **协同取消槽位保持**：协作取消运行中任务时，会话槽位保持锁定以阻断同文档并发提交，直到后台执行 runner 真正退出后才释放槽位；排队中任务取消则立即释放槽位；
- **重新生成与校验门禁**：前端重新生成智能填写时，若本地表头/选区校验失败，严格保留当前活跃结果和预览；本地校验通过并正式发起提交后，立即清理旧活跃结果与会话缓存并进入生成进度状态；
- **非新任务免拦截**：编辑填写项、排除项、选择目标列、返回修改、复制和写回不被认定为新任务，不被槽位拦截；
- **历史视图开闭无损**：打开或收起历史记录抽屉仅切换面板显隐与加载历史列表，严格不重置或重新渲染当前未完成的预览表格与草稿修改；
- **活跃任务跨工作簿隔离**：未完成活跃任务保存、读取与清除按 `documentSessionId` 独立键隔离存储，切换工作簿不发生串读或共享 localStorage 键；
- **未读角标精确过滤**：仅完整成功的归档记录递增未读角标计数，协作取消/部分预览及超过 5 MiB（带 `historyNotice`）的未归档结果严格不增加未读计数；
- **失效预览只读核对**：失效预览继续按既有合同保留只读核对，不被通用清理提前删除；
- **只读成功历史机制**：智能填写成功结果自动记录至 TaskHistoryStore，支持通过 `GET /history?taskType=excel.smart_fill` 查看列表与只读详情、复制文本、单条删除（`DELETE /history/{id}`）与清空（`DELETE /history?taskType=excel.smart_fill`）。任务窗格提供成功历史入口及未读数量角标提示；
- **严格隐私与安全边界**：历史记录仅持久化只读生成值与最小元数据（`schemaVersion: "excel.smart_fill.v2"`, `processedItemCount`, `items: [{itemId, status, valueType, value, sourceRowIndex}]`），严格排除目标写入单元格映射（`targetAddress` / `targetSheetName`）、来源单元格客户可控文本（`sourceRowLabel`）、原始提示词与本地文件路径（仅脱敏保留工作簿显示名）。历史条目严格禁止提供写回工作表、重试或恢复任务提交能力；前端渲染与复制严格基于行号派生只读行标签（`第 X 行`），针对历史缺失 `sourceRowIndex` 提供兜底，杜绝 `第undefined行`。持久化遇到非超限异常时统一记录中性提示（`historyNotice`）并安全抑制未读角标自增；
- **任务会话绑定与恢复校验**：后台任务轮询全程冻结提交时的工作簿文档会话标识（`targetDocSession`），切至其他工作簿时不串染 DOM 且精准释放对应工作簿的后台槽位；页面恢复任务时严格校验存储记录的 `documentSessionId === currentDocSession`、`host === "et"` 及 `taskType === "excel.smart_fill"`，一旦校验不通过立即清除脏存储记录并不予恢复；
- **写入补偿与锁定规则保持**：写入失败补偿、重新选择目标和成功后锁定规则完全保持不变；
- **测试覆盖**：新增后端单元测试 `adapter_service/tests/test_excel_smart_fill_history.py`（9 测试全绿）与前端契约测试 `formal-plugin-kit/tests/excel-smart-fill-result-lifecycle.test.js`（17 测试全绿），全量 Excel 测试（34 测试）与历史测试保持全绿。


- **文档会话槽位隔离**：遵循 Issue #164 统一活跃结果生命周期规范，为 Word 两类写作任务（`word.smart_write`、`word.smart_imitation`）建立基于 `host::taskType::docSessionId` 的前后台任务槽位隔离。同文档同任务进行中时阻断重复提交（返回 409 `WORD_WRITING_DOCUMENT_TASK_BUSY`），跨文档或跨任务互不阻塞；
- **提交与校验行为**：前端提交前表单/选区本地校验失败时，严格保留当前活跃结果视图；校验通过并正式发起新提交后，立即清理旧活跃结果并进入进度状态；
- **新任务失败不回滚**：新发起任务若执行失败，仅在结果区渲染新失败诊断提示，严格禁止回滚或复用上一次成功结果；
- **多模式切换与并发隔离**：用户在智能编写、智能仿写与设置页之间来回切换时，进行中的后台长任务轮询不中断；各模式活跃结果与进度相互独立隔离，切回时精准还原当前任务最新状态；
- **活跃任务恢复约束**：页面初始化仅恢复未完成的长任务（`queued` / `running`），已处于终态（`completed` / `failed`）的旧任务不回填为前台活跃结果；
- **只读成功历史机制**：成功文本结果自动记录至 TaskHistoryStore，支持通过 `GET /history?taskType=...` 查看列表与详情、复制文本、单条删除（`DELETE /history/{id}`）与全量清空（`DELETE /history?taskType=...`）。任务窗格提供顶部历史入口按钮及非打扰红点未读提示；
- **严格隐私与安全保护**：历史记录持久化严格排除用户原始选区（`originalText`）、模型原始提示词（`prompt` / `userInstruction`）与完整本地路径（仅脱敏保留文档显示名），超过 5 MiB 单条上限时自动降级跳过持久化并向用户披露提示；
- **写入与比对契约保持**：现有原文比对、格式预览、纯文本复制与写回应用行为全部保持完整兼容。

## 当前功能实现：Issue #150 Word 迁移至紧凑单行任务模型配置入口

- **四类任务单行紧凑入口**：遵循 ADR-0127 与 Issue #147 契约，将 Word 四类任务页（`word.smart_write`、`word.smart_imitation`、`word.document_review`、`word.format_review`）的原生 `<select>` 与当前状态行替换为单行紧凑入口（`#task-model-config-trigger` + `#task-model-config-menu`）；
- **最小信息披露**：显示格式统一为`[状态圆点] 配置名称 · 接入方式 ›`（接入方式仅为“工作流平台”或“模型直连”），严格不泄露模型标识、API 地址、Key、备注与完整度；
- **即时激活与隔离**：切换后立即激活，保留忙碌门禁与失败回滚；切换失败状态基于 `state.taskModelConfigStatusByTask` 在四类任务间严格隔离，智能编写错误不污染仿写或审查；
- **无障碍键盘交互**：菜单具备 ARIA 角色规范（`menuitemradio` 配合 `aria-checked`，管理项使用 `menuitem`，触发器拥有 `aria-activedescendant`），支持上下方向键在首尾钳制高亮、Enter 选中/管理、Escape 关闭并恢复触发器焦点；
- **配置管理直达**：点击或回车菜单项“管理配置”直接切换至设置页并自动聚焦当前活跃任务选项卡；
- **视觉一致与内容保护**：严格保留 Word 专属主强调色（`#2f6db3`）与几何布局；任务特定内容区提示（如文档审查全篇就绪度）保留在正文区展示；跨宿主契约测试与全量回归测试保持全绿。

## 当前功能实现：Issue #151 PPT 迁移至紧凑单行任务模型配置入口

- **两类任务单行紧凑入口**：将 PPT 幻灯片助手（`ppt.slide_assistant`）与结构审查（`ppt.structure_review`）任务页的原生 `<select>` 与「当前配置」状态行替换为 ADR-0127 单行入口；当前页总结与文档总结继续共享幻灯片助手配置，不新增任务类型；
- **最小信息披露与隔离**：标签只显示`配置名称 · 工作流平台/模型直连`；切换失败记在 `taskModelConfigStatusByTask`，智能总结错误不污染结构审查；忙碌门禁读 PPT 的 `state.busy`；
- **设置导航**：「管理配置」先写入当前任务再 `switchView("settings")`，设置页「设为当前」走 `getSettingsWorkflowTaskType()`，完整配置管理/验证调用/删除保持不变；PPT 强调色 `#d36b2c` / `#b95720` 不变。

## 当前功能实现：Issue #149 格式审查识别手工目录并披露疑似目录

- **多证据手工目录识别与豁免**：在 WPS 端实现 `collectWordManualAndSuspectedTocRegions`，基于 5 类确定性证据（E1 纯文本标题、E2 连续编号条目、E3 点引导符、E4 尾部独立页码、E5 TOC 专用样式），要求 $\ge 3$ 项独立强证据组合（尾部页码 + 引导线/编号 + 标题/样式）识别可靠手工目录，写入 `coverage.tocRegions`（`source: "manual_toc"`），建立目录审查豁免区（跳过字体、字号、段落样式、正文角色或未映射角色问题，并披露略过区域与段落数）；
- **疑似目录防线与降级**：恰好 2 项证据的连续段落区域标记为疑似目录，写入独立契约 `coverage.suspectedTocRegions`（`source: "suspected_toc"`）；审查执行时抑制该区域的正文格式虚假误报，严格不计入已审查或已豁免，保留判定原因枚举；若原覆盖状态为 `complete` 则自动降级为 `partial`，并写入 `coverageReason`；
- **负例防御与语义防线**：普通正文中引用“目录”、普通带数字段落、孤立点线段落严格不豁免；模型返回的 `toc_title` / `toc_entry` 仅作为辅助参考，不能单独建立豁免区；
- **展示与导出独立分列**：任务窗格概览区与导出的 Markdown 报告分列独立展示已略过目录与发现疑似目录，严格禁止合并为“目录无问题”；在无问题但存在疑似目录时给出明确覆盖限制提示。

## 当前修复状态：跨运行时格式审查哈希契约

- JavaScript 上传前与 Python Adapter 信任边界现在按同一固定投影、UTF-16 字符计数、紧凑稳定 JSON 和 UTF-8 SHA-256 计算；Python 继续独立重算四项指标并 fail closed。
- 新增真实 Node→Python 子进程对拍测试，覆盖正文/标题、递归表格与 cell format、图片元数据、空/非空 insufficient reason、WPS 大纲级别及 `😀/🚀/𠮷`；structure/format 篡改均要求 409 且不启动 reviewer/provider。
- `20260824-d7a1dd8` 已在 `packaging/v0251-candidate-status.json` 登记为唯一 `candidate`；候选上下文在组装归档内绑定 d7a1dd8，源码验收文件仍是生成器模板，不替代 Issue #59 目标机验收。

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
- 快照清单记录版本、九类任务配置数量、Key 引用/不可逆 SHA-256 指纹、激活关系、规范条目数量/启用状态、数据库完整性和文件校验值，不记录 Key 明文或服务地址正文；状态、快照目录为 `0700`，文件为 `0600`。
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
- 智能填写：`POST /excel/smart-fill/jobs` 提交后台任务并轮询状态，兼容保留 `POST /excel/smart-fill`，任务类型 `excel.smart_fill`；生成阶段按来源矩形与填写意图先行，最多 500 个来源数据行，结果先按来源行预览，写入目标由后续步骤绑定。
- 设置：智能分析、公式助手与智能填写分别使用独立模型配置和 API Key。

智能分析是只读分析能力：优先读取 Excel 当前选区，无有效选区时回退当前工作表已用范围；前端只提供分析报告预览、汇报段落和复制，不写回单元格，不新增工作表，不生成公式。

公式助手同样只读，但不会回退 `UsedRange`。它采集选区地址、表头、显示文本、有限值类型、已有公式和截断状态；解释模式返回原公式、组件说明、引用范围、发现问题和有依据的修正公式。本地只做不执行的基础语法、引用与兼容风险检查，不设置 `Formula`、不试算、不填充范围、不新建工作表、不修改计算模式，也不提供伪造的写回撤销。

智能填写只读取显式授权的来源矩形；模型只接收不可猜测的条目 ID、来源表头与逐行可见值，不接收目标地址、工作簿标识或公式。结果严格限定为 `excel.smart_fill.v2`，前端提供来源行预览编辑；写入目标只在预览后绑定，并经过同表单列、原值、保护状态、预占与失败补偿门禁。

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
POST   /excel/smart-fill
POST   /excel/smart-fill/jobs
GET    /excel/smart-fill/jobs/{jobId}
DELETE /excel/smart-fill/jobs/{jobId}
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
- 结构审查认中文模板形状名「标题 1 / 标题 3」和「副标题 2」；空的 `Shapes.Title` 与「单击此处编辑母版…」提示词不挡住真实标题；色条上另一个「标题 N」作为副标题。普通文本框仍不得升格为主标题。
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
- `adapter_service/app/api/excel.py`：智能分析、公式助手和智能填写路由。
- `adapter_service/app/api/ppt.py`：PPT 文档文件、智能总结和结构审查后台任务路由。
- `adapter_service/app/services/provider_client.py`：统一 Dify Chat payload、任务级 API Key、脱敏 provider 调试记录，以及 Word/Excel/PPT provider 调用。
- `adapter_service/app/services/excel/analyzer.py`：Excel 表格可用性校验和 provider 调用封装。
- `adapter_service/app/services/excel/formula_checks.py`：公式字符串的只读基础语法、引用和兼容风险检查。
- `adapter_service/app/services/excel/analysis_jobs.py`：智能分析幂等后台任务、运行状态和耗时诊断。
- `adapter_service/app/services/excel/smart_fill.py`、`adapter_service/app/services/excel/smart_fill_jobs.py`：智能填写严格协议、输入预算、Provider 调用、分批任务和取消/部分结果语义。
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
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/`：Excel 专用插件包，包含“智能分析”“公式助手”“智能填写”Ribbon、任务窗格、图标和 manifest。
- `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/`：PPT 专用只读插件包，包含“智能总结”“结构审查”Ribbon、任务窗格、图标和 manifest。
- `formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-smart-imitation.png`：智能仿写 Ribbon 图标。
- `adapter-start-kit/scripts/install_autostart.sh`、`adapter-start-kit/scripts/uninstall_autostart.sh`、`adapter-start-kit/docs/autostart-guide.md`：麒麟 V10 目标机 systemd 开机自启动安装、卸载和运维说明。
- `config/adapter.example.json`：默认 `enterprise-dify-chat`、`/chat-messages`、四个 Word 任务、三个 Excel 任务和两个 PPT 任务的 `taskApiKeyRefs`。
- `docs/operations/dify-smart-write-workflow.md`：智能编写 Dify 配置手册。
- `docs/operations/dify-smart-imitation-workflow.md`：智能仿写 Dify 配置手册。
- `docs/operations/dify-document-review-workflow.md`：文档审查 Dify 配置手册。
- `docs/operations/dify-format-review-workflow.md`：格式审查 Dify 配置手册。
- `docs/operations/dify-excel-analysis-workflow.md`：Excel“智能分析”Dify 配置手册。
- `docs/operations/model-excel-smart-fill-contract.md`、`docs/operations/workflow-platform-excel-smart-fill.md`：Excel“智能填写”模型协议、工作流配置和写回边界。
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

`v0.25.1-alpha` 已将 `20260816`、`20260822-275099e`、`20260822-4ff1862`、`20260822-afc5470`、`20260822-385a251`、`20260822-e43dc8c`、`20260824-ccad09f`、`20260824-2e7a3e6`、`20260824-5318d4b`、`20260824-799adf9`、`20260824-afe109c`、`20260824-f953c58` 和 `20260824-10b251d` 登记为 `rejected`；当前唯一自动化候选为 `20260824-d7a1dd8`。d7a1dd8 的完整 sourceCommit 为 `d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`，candidateBuildId 为 `AI-WPS-P1-WORD-EXCEL-PPT-0.25.1-20260824-d7a1dd8ef4bd595c0e8611fdfffcf696eebe57f0`，归档为 `ai-wps-phase1-delivery-20260824-d7a1dd8-v0251.tar.gz`，SHA-256 为 `ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`；自动化状态为 `candidate`，目标验收仍为 `manual-pending`（Issue #59）。其直接前任 `10b251d` 的完整 sourceCommit 为 `10b251dd52ea6b6c2d60faa9cf0ab37b3ccdc2a5`，归档 SHA-256 为 `6949e76f929e092f6c4658a9498f9fd4a483260bee5d62d91e72b18009309120`，拒绝原因为包内目标机验收记录同时出现当前候选、无当前候选和重复上一被拒绝归档叙述；两份归档均保持不可变。`f953c58` 及更早历史归档不得修改。

历史候选源码 `ccad09fb1d8019da3a40f14610ab3bd75de1ec23` 曾修复格式审查批次级块 ID 范围、直连模型输出能力、空最终正文诊断、旧工作流重复迁移及运行时快照误判，但其跨运行时 structure/format 哈希契约仍有阻断缺陷，因此归档已拒绝。本轮又发现目标机验收审计/测试在缺失必测第 8 或第 9 行时未 fail closed，并在 `f953c58` 冻结归档中复现 heading-only 与 format-outline-only 兼容输入的 outline fallback JS/Python 哈希漂移；`f953c58` 归档冻结为 rejected，修复后已由 d7a1dd8 重新构建并形成当前唯一 candidate。

```bash
AI_WPS_V0250_BASELINE_ARCHIVE=<v0.25.0-alpha archive> \
AI_WPS_V0251_PREVIOUS_CANDIDATE_ARCHIVE=dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260824-10b251d-v0251.tar.gz \
DATE_TAG=20260824 PYTHON_BIN=/mnt/ai-wps-test-venv/bin/python PYTHON38_BIN=/mnt/ai-wps-test-venv/bin/python \
bash packaging/build_v0251_delivery_kit.sh
```

当前可复核结果：

- Sol/high 核心结论为 `CLEAN FOR BUILD`；核心 focused 为 `199 passed, 1 skipped`，当前源码 Adapter 全量测试为 `874 passed, 95 skipped`。
- v0.25.1 交付/prepare/audit focused 为 `87 passed`（`test_v0251_delivery.py`），协议/交付 focused 合计 `137 passed, 5 skipped`，正式插件契约为 `28/28`；这些自动化证据仍不替代目标机验收。
- Kylin 构建运行时为 Node `v22.23.2`、Python `3.8.10`；source provenance 为 `246`，Python 3.8 兼容扫描为 `82` 个生产文件。
- 公开 format-review API、`characterCount`、`contentSha256`、`structureSha256`、`formatSha256` 四个哈希键，以及 runtime/lifecycle/install/upgrade/rollback/deleted-workflow-profile gates 均通过；本地 checksum 与最终 candidate audit 均通过。
- d7a1dd8 归档保持原始字节，SHA-256 为 `ec318db4ffbda499c24aa6fb50958628cc4eaa030b22389bbf29cd783b1adbf6`；`10b251d` 和 `f953c58` 归档也保持原始字节，不得替代当前 candidate 或改写历史。
- 上述 v0.25.1 验证记录属于历史候选状态；后续 `v0.25.3-alpha` 已完成 Issue #59 目标机验收，状态为 `target-accepted`。当前 `v0.26.0-preview.1` 仍须单独完成目标机验收。

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
