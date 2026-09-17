# AI-WPS 交互文本流式与任务窗性能优化实施计划

> **状态：** 设计已确认，待实施。
>
> **执行要求：** 实施时使用测试驱动开发；每项任务先建立可复现红灯，再做最小实现。完成前使用 `verification-before-completion`，不得以静态检查替代真实 Python、Node、交付构建和麒麟 WPS 验收。

## 目标

在不破坏后台任务、幂等提交、文档会话隔离、重开续查、历史结果和 FastAPI/standalone 双运行时的前提下：

1. 为全部模型任务补齐毫秒级性能观测，能区分本地抽取、排队、模型连接、首个可见内容、完整响应、解析和前端首渲染；
2. 消除 Excel 智能填写、Word 全篇审查和格式审查中的主要同步 WPS COM/JSAPI 长任务；
3. 首期为模型直连的 Word 智能编写和智能仿写提供可恢复的增量文本预览与运行中取消；
4. 保留工作流平台、结构化任务和不支持流式的模型服务现有阻塞任务语义；
5. 在麒麟 V10、WPS 12.1.2 上以确定的 p50/p95/p99 指标验证收益和回归。

**架构决策：** [ADR-0132](../../adr/0132-preserve-background-jobs-while-streaming-interactive-text.md)

## 模块与接口

本计划建立三个深模块，调用方和测试只跨各自接口，不直接理解 SSE 分帧、事件缓存或 DOM 节流细节。

### 1. 后台任务执行控制模块

**Seam：** `LongTaskCoordinator` 向任务 runner 传入的可调用执行控制对象。

**Interface：**

- `control(phase)`：保持现有阶段回调兼容；
- `control.publish_text(text)`：追加正式正文增量；
- `control.record_metric(name, milliseconds)`：记录受控毫秒指标；
- `control.cancel_requested()`：读取原子取消状态。

**Implementation：** 阶段记账、单调序号、五十毫秒或四 KiB 合并、预览快照、事件环、长轮询条件变量、终态清理及先提交者获胜的竞态语义全部隐藏在协调器内部。

### 2. 直连增量文本模块

**Seam：** `ProviderClient` 执行 OpenAI-compatible 交互文本请求的位置。

**Interface：** 输入已经解析的任务认证、请求体、执行控制和超时，返回与现有非流式路径相同的规范化最终响应。

**Implementation：** 隐藏 urllib 读取、UTF-8 跨块解码、SSE 分帧、`data:` 事件、`[DONE]`、正式 `content` 提取、推理与 think 过滤、五 MiB 上限、取消关闭、首包/首个可见内容计时和仅在正文到达前允许的阻塞回退。

### 3. Word 增量预览控制模块

**Seam：** Word 任务窗格启动或恢复智能编写、智能仿写任务的位置。

**Interface：** `start(jobIdentity)`、`resume(afterSequence)`、`stop()`、`dispose()`；模块只向结果区发布纯文本预览状态，终态仍交给现有结果渲染路径。

**Implementation：** 隐藏二十五秒长轮询、连续序号、快照重置、三次错误降级、五十毫秒 DOM 节流、滚动跟随和跨模式/文档会话隔离。

## 全局约束

- 不新增第三方依赖；Python 生产代码保持 Python 3.8 兼容，插件保持现有 WPS WebView/ES5 兼容范围。
- 不修改或提交 `config/adapter.json`、`run/`、历史归档、交付产物或本地审查文件。
- 不增加共享任务并发，不改变默认 `2 running + 8 queued`、交互任务公平调度或现有任务 TTL。
- 不让 WPS 直接连接模型服务，不把任务提交 POST 改成长连接。
- 不为工作流平台、Excel、PPT、文档审查或格式审查展示残缺模型 JSON。
- 增量文本不写磁盘、不进入历史、不用于写回；失败和取消任务继续不归档。
- 不改造旧 `wps-addon` 原型；正式前端权威源为 `formal-plugin-kit`。
- 不把前端停止读取描述成模型后台一定停止计费；只承诺 Adapter 已关闭当前响应并释放本地任务槽。

---

## Task 1：建立毫秒级任务性能基线

**Files:**

- Modify: `adapter_service/app/services/long_task_coordinator.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/tests/test_long_task_coordinator.py`
- Modify: `adapter_service/tests/test_direct_model_provider.py`
- Modify: `formal-plugin-kit/tests/long-task-diagnostics.test.js`

**Interface：** 保留现有秒级字段，新增 `elapsedMs`、`phaseElapsedMs`、`phaseDurationsMs`、`queueWaitMs`；模型性能使用 `providerHeadersMs`、`providerFirstVisibleMs`、`providerCompleteMs`、`parseMs`，不可把 HTTP 头到达误称为首 Token。

- [ ] 写红灯测试，证明当前任务状态没有毫秒字段、阻塞模型调用不能区分连接与完整响应、HTTP 日志没有 duration。
- [ ] 在协调器中只使用 `time.monotonic()` 计算持续时间；墙钟只用于展示时间戳。
- [ ] 所有任务记录排队和阶段毫秒值；阻塞任务的 `providerFirstVisibleMs` 明确为 `null`，不能伪造。
- [ ] 将 Provider 指标按 `traceId/jobId` 关联到任务，禁止继续依赖进程级 `_LAST_PROVIDER_DEBUG` 作为性能证据。
- [ ] `/provider/route-diagnostics` 和三宿主高级诊断只展示耗时、长度、计数和错误码，不展示正文、delta、提示词、Key 或完整路径。
- [ ] 为前端点击反馈和首渲染增加 `performance.now()` 测量，只保留当前任务内存值和人工导出值。

**Focused verification:**

```bash
PYTHONPATH=adapter_service /data/home/cloud/.venvs/ai-wps-test-py38/bin/python -m pytest -q \
  adapter_service/tests/test_long_task_coordinator.py \
  adapter_service/tests/test_direct_model_provider.py
node --test formal-plugin-kit/tests/long-task-diagnostics.test.js
```

---

## Task 2：修复 Excel 智能填写点击反馈和分片抽取

**Files:**

- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Create: `formal-plugin-kit/tests/excel-smart-fill-performance.test.js`
- Modify: `formal-plugin-kit/tests/excel-smart-fill-result-lifecycle.test.js`

**Interface：** 智能填写来源抽取返回与现有 `buildExcelSmartFillRequest()` 相同的数据合同，但通过 Promise 分片完成，支持进度和取消，不把中间行暴露为任务结果。

- [ ] 写红灯测试：点击后必须先设置 busy、状态栏和结果卡，再访问任何 WPS 单元格属性。
- [ ] 用可控假时钟建立 25,000 单元格场景，断言每个同步片段不超过五十毫秒，并在片段间让出事件循环。
- [ ] 把同步 `buildExcelSmartFillRequest()` 拆为校验、分片读取、冻结请求三个内部阶段；保持公式、隐藏、合并、来源范围和 500 行合同不变。
- [ ] 在分片之间检查取消和文档会话，切换工作簿后不得把旧来源提交到新工作簿。
- [ ] 保持失败时旧结果不回滚、正常 UI 不调用写回接口的当前边界。

**Focused verification:**

```bash
node --test \
  formal-plugin-kit/tests/excel-smart-fill-performance.test.js \
  formal-plugin-kit/tests/excel-smart-fill-result-lifecycle.test.js \
  formal-plugin-kit/tests/excel-smart-fill-source-first.test.js
```

---

## Task 3：把 Word 全篇审查和格式审查抽取改为可中断分片

**Files:**

- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/tests/word-full-document-review.test.js`
- Modify: `formal-plugin-kit/tests/deterministic-format-review.test.js`
- Modify: `formal-plugin-kit/tests/word-format-review-result-lifecycle.test.js`

**Interface：** 两类抽取仍产生完全相同的快照、计数和哈希合同；分片调度只改变执行方式，不改变审查范围、第二遍校验或信任门禁。

- [ ] 写红灯测试，证明当前 `setTimeout(0)` 只延迟整次同步扫描，不能在扫描内部重绘或取消。
- [ ] 将段落、表格、格式区段和图片盘点按单调时钟预算分片；每片目标不超过五十毫秒，而不是只按固定对象数量切片。
- [ ] 每片结束校验取消、文档会话和编辑信号；取消后清理未提交快照。
- [ ] 第一遍和第二遍继续使用同一规范化投影，四项哈希及覆盖统计必须与改造前一致。
- [ ] 加入大文档假对象测试，断言事件循环获得控制、进度单调、取消后不提交后台任务。

**Focused verification:**

```bash
AI_WPS_HASH_CONTRACT_PYTHON=/data/home/cloud/.venvs/ai-wps-test-py38/bin/python \
node --test \
  formal-plugin-kit/tests/word-full-document-review.test.js \
  formal-plugin-kit/tests/deterministic-format-review.test.js \
  formal-plugin-kit/tests/format-review-hash-contract.test.js \
  formal-plugin-kit/tests/word-format-review-result-lifecycle.test.js
```

---

## Task 4：缩小 PPT 运行时禁用范围

**Files:**

- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/workflow-settings-ppt.test.js`
- Modify: `formal-plugin-kit/tests/ppt-active-result-history.test.js`

- [ ] 写红灯测试，锁定生成期间历史、复制已有结果和非冲突导航仍可用。
- [ ] 将 `setRunDisabled()` 收缩为任务提交与来源修改控件门禁，不禁用历史和只读查看入口。
- [ ] 保持模型配置修改、来源切换和同一文档重复任务仍被阻止。
- [ ] 验证后台完成时只更新所属文档会话，不把用户从历史视图强制切回。

---

## Task 5：深化后台任务执行控制与增量事件存储

**Files:**

- Modify: `adapter_service/app/services/long_task_coordinator.py`
- Modify: `adapter_service/tests/test_long_task_coordinator.py`
- Modify: `adapter_service/tests/test_word_writing_jobs.py`

- [ ] 先为执行控制 Interface、连续序号、二十五秒等待、首次快照、事件缺口重置、256 项事件环和 512KiB 预览上限写红灯测试。
- [ ] 新增 `provider_connecting`、`provider_waiting`、`streaming`、`stopping` 公共阶段；阻塞回退继续使用 `provider_processing`。
- [ ] 实现五十毫秒或四 KiB 的正文合并发布；心跳和阶段事件不计入首个可见内容。
- [ ] `wait_events()` 使用协调器条件变量，不采用忙轮询；终态、取消和清理必须唤醒等待者。
- [ ] 修改当前取消竞态：取消请求先在锁内被接受时，后到达的 runner 结果不能覆盖为成功；完整结果已经提交时，DELETE 返回完成状态。
- [ ] 失败或取消保留纯文本预览到现有终态 TTL，但 `_complete_success_locked()` 只有成功终态才能调用历史提交器。
- [ ] 事件与性能诊断不得包含任务请求、认证、原始提示词或未过滤推理内容。

**Focused verification:**

```bash
PYTHONPATH=adapter_service /data/home/cloud/.venvs/ai-wps-test-py38/bin/python -m pytest -q \
  adapter_service/tests/test_long_task_coordinator.py \
  adapter_service/tests/test_word_writing_jobs.py
```

---

## Task 6：实现 OpenAI-compatible 直连增量文本模块

**Files:**

- Create: `adapter_service/app/services/direct_text_stream.py`
- Create: `adapter_service/tests/test_direct_text_stream.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_direct_model_provider.py`

- [ ] 先写表驱动红灯测试：SSE 行拆包、UTF-8 字符跨块、多个 `data:` 行、空事件、`[DONE]`、usage 尾包、`finish_reason`、HTTP 错误、首包断开、中途断开和超时。
- [ ] 增加 `reasoning_content`、工具调用、心跳及 `<think>` 标签跨块过滤测试；只有正式 `content` 触发 `publish_text()` 和首个可见内容计时。
- [ ] 增加五 MiB 完整响应、512KiB 增量预览和恶意无限事件测试，超限必须使用稳定错误码并关闭响应。
- [ ] 增加取消测试：执行控制返回取消后关闭 response，不再发布 delta，并返回携带部分预览的受控取消。
- [ ] 实现 `stream=true` 请求、规范化终态响应和现有 `extract_answer()` 可消费的结果合同。
- [ ] 仅当明确的 400/404/415/422 等“不支持流式”响应发生在任何正文之前时，返回可回退分类；中途断线和已产生正文的错误禁止重试。
- [ ] 不记录原始 SSE、delta、响应正文或 Authorization；脱敏诊断只记录状态、字节数、事件数和耗时。

---

## Task 7：持久化模型流式能力验证

**Files:**

- Modify: `adapter_service/app/core/features.py`
- Modify: `adapter_service/app/api/config.py`
- Modify: `adapter_service/app/services/direct_services.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/api/provider.py`
- Modify: `adapter_service/tests/test_direct_services_api.py`
- Modify: `adapter_service/tests/test_direct_service_model_catalog_contract.py`
- Modify: `adapter_service/tests/test_direct_model_provider.py`

**Interface：** 任务选择公开 `streamingCapability`，状态为 `validated/unsupported/stale/not_checked`；能力绑定服务 ID、服务 revision、规范化地址、API Key 指纹和精确模型标识。

- [ ] 写红灯测试：地址、Key、revision 或模型任一变化时旧能力必须变为 stale，不能继续开启流式。
- [ ] 为 `AI_WPS_ENABLE_DIRECT_STREAMING` 增加默认关闭的 feature helper，并通过 `/config.features.directStreamingEnabled` 明确传给正式前端。
- [ ] 复用“任务验证”操作执行最小真实流式探针，披露可能产生费用；验证正文必须满足现有任务合同。
- [ ] 在 `DirectServiceStore` 中保存有界的模型流式能力记录，不保存 Key、响应正文或完整提示词。
- [ ] 任务认证快照冻结能力结论；运行中修改服务只影响后续任务，Key 轮换继续使旧任务失效。
- [ ] 不允许通过模型名称或厂商名称推断能力，不增加普通设置页手动开关。

---

## Task 8：接入智能编写、智能仿写与真实运行中取消

**Files:**

- Modify: `adapter_service/app/services/word/writing_jobs.py`
- Modify: `adapter_service/app/services/word/rewriter.py`
- Modify: `adapter_service/app/services/word/smart_imitator.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_word_writing_jobs.py`
- Modify: `adapter_service/tests/test_rewriter_modes.py`

- [ ] 写红灯测试：只有 feature 开启且认证快照能力为 validated 时走增量模块；其余情况走现有阻塞路径。
- [ ] 让两个写作任务将同一个执行控制对象传到 ProviderClient，不在中间模块复制事件缓存或取消状态。
- [ ] 流式任务启用 `allow_running_cancel=True`；阻塞回退任务仍只允许取消排队，不显示虚假的运行中停止能力。
- [ ] 成功终态继续执行现有写作规范检查、对照、结果隔离和历史归档，最终正文必须与增量拼接结果逐字一致。
- [ ] 取消或失败只返回纯文本部分预览和 `partial=true`，不执行历史提交器，不提供写回资格。
- [ ] 正文前明确不支持流式时最多回退一次；断言只产生一个成功结果和一条历史记录。

---

## Task 9：提供 FastAPI 与 standalone 对等的增量事件接口

**Files:**

- Modify: `adapter_service/app/api/word.py`
- Modify: `adapter_service/standalone_adapter.py`
- Create: `adapter_service/tests/test_word_writing_events_api.py`
- Modify: `adapter_service/tests/test_writing_policy_api.py`
- Modify: `adapter_service/tests/test_issue182_public_boundary.py`

**Interface：**

```text
GET /word/smart-write/jobs/{jobId}/events?afterSequence=N&waitMs=25000
GET /word/smart-imitation/jobs/{jobId}/events?afterSequence=N&waitMs=25000
```

响应包含 `latestSequence`、有序 `events`、必要时的 `previewSnapshot`、`resetRequired` 和当前终态；`waitMs` 限制在 `0..25000`。

- [ ] 先写 FastAPI/standalone 参数、404、等待唤醒、快照重置、终态和脱敏等价测试。
- [ ] 两个 Adapter 只做传输适配，不复制事件排序、缓存和竞态逻辑。
- [ ] DELETE 对已验证流式任务调用 `request_cancel()`；对阻塞任务保留现有 queued-only 错误。
- [ ] standalone 返回普通 JSON 长轮询响应，不实现 chunked SSE；连接断开不取消后台任务。
- [ ] 保留原 GET job 状态接口，旧前端和降级路径不受影响。

---

## Task 10：实现 Word 增量预览、停止和降级交互

**Files:**

- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Create: `formal-plugin-kit/tests/word-writing-streaming.test.js`
- Modify: `formal-plugin-kit/tests/word-writing-jobs.test.js`
- Modify: `formal-plugin-kit/tests/word-active-result-history.test.js`
- Modify: `formal-plugin-kit/tests/taskpane-result-views.test.js`

- [ ] 先写红灯测试：首个 snapshot、连续 delta、事件缺口 reset、跨文档隔离、模式切换恢复、三次错误降级和终态替换。
- [ ] 生成中只使用 `textContent` 更新纯文本，不运行 Markdown、对照或写作检查；最多五十毫秒合并一次 DOM 更新。
- [ ] 用户位于底部时跟随生成；用户向上滚动后保持位置，回到底部后恢复跟随。
- [ ] 10 秒无可见内容显示“模型响应较慢”；30 秒显示“继续等待”和条件允许时的“停止生成”，不显示百分比。
- [ ] 点击停止后 100ms 内显示“正在停止”；只有 Adapter 返回 cancelled 才显示已停止，completed/failed 按真实终态展示。
- [ ] 取消和失败的部分文本只提供复制；智能编写的“应用”按钮保持禁用，历史入口不新增记录。
- [ ] 接口缺失或连续三次事件查询失败时停止事件控制模块，回到现有三秒 `pollWritingJob()`；后台任务和恢复记录保持不变。
- [ ] 增量任务完成时复用现有 `completeWritingJob()`，确保正式 Markdown、对照、写作检查、只读恢复和历史视图语义不分叉。

**Focused verification:**

```bash
node --test \
  formal-plugin-kit/tests/word-writing-streaming.test.js \
  formal-plugin-kit/tests/word-writing-jobs.test.js \
  formal-plugin-kit/tests/word-active-result-history.test.js \
  formal-plugin-kit/tests/taskpane-result-views.test.js
```

---

## Task 11：交付白名单、运维文档与验收模板

**Files:**

- Modify: `packaging/delivery-sources-v0260-preview1.json`
- Modify: `adapter_service/tests/test_v0260_preview1_delivery.py`
- Modify: `packaging/v0260-preview1-delivery.md`
- Modify: `packaging/v0260-preview1-target-machine-acceptance.md`
- Modify: `docs/operations/runtime-config.md`
- Modify: `docs/codex-handoff.md`

- [ ] 将新增 Python 生产模块加入显式交付白名单，并锁定正式 Word 插件包含增量前端代码，`wps-addon` 不新增对应实现。
- [ ] 运维文档说明 feature flag、能力验证、阻塞降级、取消边界和诊断字段。
- [ ] 验收模板增加每个试点任务、每个模型组合至少三十次的 blocking/streaming 对照，记录 p50/p95/p99 和原始测试时间。
- [ ] 明确首个候选版不能仅凭自动测试把功能标为默认开启；真实麒麟 WPS 验收前保持显式 feature flag。
- [ ] 更新 handoff 时只记录已完成事实、真实测试输出和仍未完成的真机项目。

---

## Task 12：完整验证与发布裁决

### 12.1 本地与麒麟自动化

在 Kylin V10 使用当前文档记录的虚拟环境解释器：

```bash
cd /data/home/cloud/AI-WPS-kylin-test
PYTHONPATH=adapter_service \
  /data/home/cloud/.venvs/ai-wps-test-py38/bin/python -m pytest -q adapter_service/tests

PATH=/data/home/cloud/.local/bin:$PATH \
  node --test formal-plugin-kit/tests/*.test.js

cd /data/home/cloud/AI-WPS-kylin-test/wps-addon
PATH=/data/home/cloud/.local/bin:$PATH npm test
PATH=/data/home/cloud/.local/bin:$PATH npm run build
```

执行交付与兼容门禁：

```bash
bash packaging/build_v0251_delivery_kit.sh
bash packaging/build_v0260_preview1_delivery_kit.sh
git diff --check
```

### 12.2 假模型确定性性能场景

- [ ] TTFT 分别为 2.5s、10s、30s，每 50ms 发布一个碎片，总时长 35s；验证 `firstRender - providerFirstVisible`。
- [ ] UTF-8 中文字符和 `<think>` 标签跨网络块；验证无乱码、无推理泄露。
- [ ] 正文前不支持流式；验证只回退一次 blocking。
- [ ] 正文后断线；验证 failed、部分预览可复制、零自动重试、零历史。
- [ ] 生成中停止；验证不再发布增量、终态唯一、槽位释放。
- [ ] 2 running + 8 queued；验证第 11 个任务 300ms 内返回 429，交互公平性不回归。

### 12.3 麒麟 V10 / WPS 12.1.2 指标

- 点击到明确反馈：p95 ≤100ms，p99 ≤200ms，零次静默点击；
- 模型首个可见内容到前端首渲染：p95 ≤150ms；
- 10s/30s 渐进提示误差不超过 ±0.5s；
- 点击停止到 UI 确认：≤100ms；
- Adapter 停止继续发布增量：p95 ≤500ms；
- 本地运行槽释放：≤2s；
- streaming 完整生成时间 p95 不得比相同模型、相同输入的 blocking 基线恶化超过 10%；
- COM/JSAPI 分片单次主线程长任务 <50ms，总抽取时间相对现状增加不超过 10%；
- 320px/420px 任务窗格无横向溢出，停止按钮、状态和增量预览可访问。

若供应商模型自身 `providerFirstVisibleMs` 接近完整生成时间，记录为模型或输入瓶颈，不把它伪报为前端流式失败；若本地增量附加延迟超标，则候选不得默认启用。

## 回滚路径

1. 设置 `AI_WPS_ENABLE_DIRECT_STREAMING=0`，后续任务立即回到现有阻塞调用和三秒状态轮询；
2. 已提交任务继续使用认证和能力快照，不在运行中切换协议；
3. 增量事件接口缺失时正式前端自动回退现有状态查询；
4. 新增能力验证字段由旧版本忽略，不要求破坏性配置迁移；
5. 不删除旧 GET/DELETE 路由、阻塞 Provider 路径或既有结果渲染路径，直至流式候选完成目标机验收。

## 完成标准

- 三个深模块的 Interface 均有直接合同测试，调用方测试不依赖内部 SSE、缓存或 DOM 节流实现；
- 全量 Python、正式插件、`wps-addon`、Python 3.8 扫描、交付构建和审计全部通过；
- FastAPI 与 standalone 的提交、事件、取消、终态和错误 envelope 对等；
- 两个试点任务满足真机性能指标，结构化任务和工作流平台行为无变化；
- 增量文本、推理内容、用户正文、Key 和本地路径不进入日志或持久化性能数据；
- `docs/codex-handoff.md`、运维文档和验收记录与真实完成状态一致。
