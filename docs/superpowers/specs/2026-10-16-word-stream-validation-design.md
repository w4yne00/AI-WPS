# Word 智能编写、智能仿写：自动验证并默认流式预览设计规范

## 1. 意图与背景 (Intent and The Why)

在当前的 AI-WPS Word 任务设置中，用户配置直连模型后，若希望启用增量流式文本预览，需要先手动在任务参数区点击“验证调用”按钮，通过模型连通性与流式探针测试后，才能在后续任务中享受流式打字效果。这种体验存在以下痛点：
1. **多余的手动操作步骤**：智能编写与智能仿写作为 Word 中最常用的自然语言文本生成场景，用户在选好模型后必须额外点击一次“验证调用”并等待几秒，然后再点击“保存并设为当前”，流程割裂；
2. **手填模型与目录模型的验证语义不一致**：根据 ADR-0128 及 Issue #257，手填模型支持免预先测试保存与任务执行；而目录模型则需要确保流式契约有效。若用户直接保存，未能自动完成必要的能力探测，导致原本支持流式的模型因缺少 `validated` 状态而降级为普通阻塞调用。

本功能旨在为 Word 智能编写 (`word.smart_write`) 和智能仿写 (`word.smart_imitation`) 消除独立“验证调用”按钮，在用户点击“保存并设为当前”时：
- 对**目录模型**（含继承目录服务默认模型）：前置自动执行流式能力验证，验证通过后原子保存激活；失败则保留原配置和草稿，并向用户展示明确原因；
- 对**手填模型**（含继承手填服务默认模型）：先本地校验并立即保存激活，不阻塞用户操作或任务提交；后台自动触发非阻塞的流式能力探测，探测失败仅更新流式状态，绝不撤销已保存的选择；未取得有效流式结果前使用普通调用安全执行任务。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **移除独立按钮**：在 Word 智能编写和智能仿写设置中移除独立的“验证调用”按钮，将验证过程与“保存并设为当前”动作无缝融合，明确告知用户会实际请求模型并显示准确阶段状态。
2. **双轨验证流**：
   - **目录模型（含继承目录默认值）**：先自动验证流式能力，成功后保存激活；验证失败（鉴权、连接、协议等）保留原任务选择和草稿，显示真实原因。
   - **手填模型（含继承手填默认值）**：先本地校验、保存和激活，再自动进行后台非阻塞探测；探测失败只更新能力状态（如 `unsupported`），不撤销已保存选择。未取得流式能力前使用普通调用执行任务，不伪造验证成功。
3. **能力记录精确复用与防重探测**：
   - 按服务修订、服务地址、API Key 指纹和精确模型名复用有效流式能力记录（`validated` / `unsupported`）；
   - 仅在缺失或失效（`not_checked` / `stale`）时才触发真实探测；
   - 对同一配置并发探测自动去重，不重复启动在途请求；
   - 严禁根据模型名称推断流式能力。
4. **进行中任务与快照隔离**：
   - 探测结果仅对新提交任务生效，不改变进行中任务的传输模式或执行快照；
   - 已有真实任务不因探测暂停。
5. **双运行时一致性与范围约束**：
   - FastAPI 与 Standalone Adapter 行为严格一致；
   - 其他 Word 功能（如文档审查、格式审查）以及 Excel、PPT 宿主保留现有独立验证调用机制，不扩展自动探测或文本流式预览。

### 非目标 (Non-Goals)
1. 不为共享服务保存（新建/编辑直连服务卡片）引入级联遍历探测；
2. 不扩展 Word 文档审查、格式审查或 Excel/PPT 的流式预览；
3. 不新增独立的验证后台守护进程或复杂调度系统。

### 反目标 (Anti-Goals)
1. **严禁静默回退或篡改选择**：手填模型探测失败时，严禁撤销用户的模型选择，更严禁静默切换至其他服务或模型；
2. **严禁阻断手填任务执行**：手填模型即使未完成探测或探测失败，依然允许作为普通阻塞调用正常执行实际任务；
3. **严禁伪造流式成功**：未收到合法流式增量或未完成校验时，严禁标为 `validated`；
4. **严禁影响其他宿主与任务**：保证修改严格收敛于 Word 智能编写与仿写，不破坏已有契约。

---

## 3. 约束条件 (Constraints)

1. **环境与兼容性**：
   - 后端严格兼容 Python 3.8（ARM64 Kylin V10 SP1 与 Linux/macOS）；
   - 前端兼容 WPS 内嵌 Chromium/CEF 内核，轻量纯 JS，零新引入外部依赖；
   - 不修改或提交 `config/adapter.json`、`run/`、`.scratch/` 等本地运行态数据。
2. **测试驱动开发 (TDD)**：
   - 所有前后端新增与修改逻辑必须先编写失败测试，确认失败原因符合预期后再编写实现代码；
   - Kylin V10 上 Python 全量 pytest 与插件 Node 契约测试全量通过；
   - `git diff --check` 0 警告，Python 3.8 兼容性检查通过。

---

## 4. 用户交互与前端设计 (UI & Interaction Design)

### 4.1 按钮显示逻辑
- 在 Word 任务模型设置区（`renderTaskModelSelectionSection`）：
  - 当 `currentTask === "word.smart_write" || currentTask === "word.smart_imitation"` 时：
    - `#btn-validate-task-model-selection` 隐藏（`hidden = true`）；
    - 提示文案与状态展示调整：
      - 若所选为目录模型（或继承目录默认值）：文案提示“保存将自动验证流式能力（会真实请求模型，可能产生费用）”；
      - 若所选为手填模型（或继承手填默认值）：文案提示“保存将立即设为当前并在后台探测流式能力（未完成前使用普通调用）”；
  - 当 `currentTask` 为 `word.format_review` 或 `word.document_review` 时：
    - `#btn-validate-task-model-selection` 保持可见（`hidden = false`），行为维持原有逻辑。

### 4.2 保存按钮执行流 (`saveTaskModelSelection`)
在用户点击 `#btn-save-task-model-selection`（“保存并设为当前”）时：
1. **参数提取与本地校验**：
   - 检查 `serviceId` 是否有效；
   - 执行 `validateTaskModelSelectionDraft`，不合法时提示错误并阻断。
2. **模型来源判定**：
   - 判断当前所选模型是“目录模型”还是“手填模型”：
     - 若 `draft.modelName` 明确填写：根据其是否在 `service.customModels` 中（或 `draft.customModel === true`）判断；
     - 若 `draft.modelName === ""`（继承默认）：根据 `service.defaultModel` 是否为手填模型判断。
3. **分支 A：目录模型自动验证并保存**：
   - 状态显示：“正在验证调用并检测流式能力（会真实请求模型，可能产生费用）...”；
   - 调用 `POST /provider/task-model-selections/{taskType}/validate`（携带 draft 参数）；
   - 若验证失败（HTTP 4xx/5xx、超时、模型报错等）：
     - 终止保存；
     - 状态显示：“验证失败，未保存配置：{具体错误信息}”；
     - 用户草稿保持未改动，不调用 `/activate`。
   - 若验证成功：
     - 调用 `POST /provider/direct-services/{serviceId}/activate`；
     - 激活成功后，刷新列表与配置；
     - 状态显示：“已验证流式能力并设为当前。”
4. **分支 B：手填模型直接保存并后台探测**：
   - 先调用 `POST /provider/direct-services/{serviceId}/activate`；
   - 激活成功后，立即更新界面为当前选用，并提示“已保存并设为当前，正在后台探测流式能力...”；
   - 发起非阻塞后台请求调用 `POST /provider/task-model-selections/{taskType}/validate`：
     - 若成功：若当前仍处在同一服务与模型，更新流式能力状态为 `validated`，提示“已保存并设为当前（流式能力已确认）。”；
     - 若失败：不撤销激活！更新状态提示“已保存并设为当前（流式探测未通过，将使用普通调用）。”，流式能力记录为 `unsupported`。

---

## 5. 后端逻辑与存储设计 (Backend Architecture & Storage)

### 5.1 能力记录复用与去重 (`ProviderClient.validate_task_model_selection`)
- 在进入网络调用前，查询 `direct_service_store.get_task_model_selection(task_type)["streamingCapability"]`：
  - 检查记录中的 `status` 是否为 `validated` 或 `unsupported`；
  - 核对当前 `serviceRevision`、`serviceBaseUrl`、`apiKeyFingerprint` 以及 `modelName` 是否完全一致；
  - 若完全一致且未失效（不是 `stale` / `not_checked`）：
    - **直接复用现有记录**，无需向模型发送探测 HTTP 请求；
    - 返回 `success: True`, `streamingCapability: existing_status`, `taskCallPerformed: False`。
- **并发探测去重**：
  - 使用全局线程锁保护 `_in_flight_streaming_probes: Set[str]`；
  - 键规则为 `f"{service_id}::{model_name}"`；
  - 若已有相同配置正在探测中，后续相同请求等待其完成或安全复用其探测结果，避免重复发起扣费请求。

### 5.2 任务执行快照与流式决策 (`writing_jobs.py` & `provider_client.py`)
- Word 智能编写与仿写创建任务时：
  - 检查 `task_auth` 快照中的 `streamingCapability`；
  - 若 `streamingCapability.status == "validated"` 且 `AI_WPS_ENABLE_DIRECT_STREAMING` 未被显式关闭（!= "0"）：
    - 采用增量长轮询文本流式传输；
  - 若为 `unsupported`、`not_checked` 或探测失败：
    - 采用稳定普通阻塞任务调用；
  - 任务执行期间快照固定，后台探测状态的变更不改变已启动任务的执行模式。
