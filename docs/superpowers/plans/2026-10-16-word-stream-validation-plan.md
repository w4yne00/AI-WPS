# Word 智能编写、智能仿写：自动验证并默认流式预览实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Word 智能编写与仿写中移除独立“验证调用”按钮，实现目录模型保存前自动验证流式能力并激活、手填模型即刻保存并后台非阻塞探测，有效记录精准复用与防重探测，未验证或不支持模型平滑回退普通调用。

**Architecture:**
后端在 `ProviderClient` 中补充流式能力记录精准复用与在途探测并发去重逻辑，确保有效记录免重复请求、探测过程线程安全；前端在 Word 任务窗格设置区中根据任务类型隐藏智能编写与仿写的独立验证按钮，在保存并设为当前动作中按目录与手填模型区分前置阻塞验证与后置非阻塞探测流程，状态与错误精准反馈且绝不撤销手填模型保存或影响其他任务与宿主。

**Tech Stack:** Python 3.8、FastAPI、Starlette、Pydantic v2、Standalone HTTP Adapter；WPS JS/HTML/CSS、Node.js 契约测试。

**Spec:** `docs/superpowers/specs/2026-10-16-word-stream-validation-design.md`

## Global Constraints

- 后端严格兼容 Python 3.8（ARM64 Kylin V10 SP1 与通用 Linux/macOS）。
- 前端兼容 WPS 内嵌 Chromium/CEF 内核，轻量原生 JS/CSS，零新引入外部依赖。
- 不得修改或提交 `config/adapter.json`、`run/`、`.scratch/` 等本地运行态数据。
- FastAPI 与 Standalone 双运行时接口行为与数据响应严格对齐。
- 遵循测试驱动开发（TDD）：每个任务先写失败测试，验证失败原因，再写实现代码，回归确保全部通过。
- 严禁静默切换模型：实际调用或测试调用失败必须向用户准确返回真实报错原因。
- 探测通过仅影响之后提交的新任务，不改变进行中任务的传输方式或其执行快照；已有真实任务不为探测暂停。

## Review Focus

1. **有效流式记录精准复用**：已验证（`validated`）或已明确不支持（`unsupported`）的模型配置在服务修订、地址、Key 指纹与模型名均未变时直接复用，不发起真实网络探测。
2. **在途探测并发去重**：同一服务的同一模型多次并发触发验证时，共用在途探测，避免重复发送扣费请求。
3. **目录模型验证失败保护**：目录模型保存时若验证请求报错（鉴权失败、连接超时或模型错误），严禁调用激活接口，保留原选择和草稿，如实显示失败原因。
4. **手填模型后台探测失败不撤销**：手填模型保存激活后后台探测失败，仅更新流式状态为未支持，严禁撤销已激活的配置，且后续任务可继续以阻塞调用正常执行。
5. **任务与宿主隔离性**：Word 格式审查、文档审查以及 Excel、PPT 宿主保留原有的独立“验证调用”按钮与验证行为，不受智能编写改造干扰。

---

### Task 1: 后端流式能力记录复用与在途探测去重 (ProviderClient)

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_issue262_stream_validation.py`

**Interfaces:**
- Consumes: `DirectServiceStore.get_task_model_selection`, `DirectServiceStore.record_streaming_capability`, `DirectServiceStore._evaluate_streaming_capability`
- Produces:
  - `ProviderClient.validate_task_model_selection`: 增加缓存有效记录复用与 `_in_flight_streaming_probes` 并发去重

- [x] **Step 1: 编写失败的单元测试**
  在 `adapter_service/tests/test_issue262_stream_validation.py` 中编写能力复用与去重测试：
  - `test_validate_task_model_selection_reuses_valid_streaming_capability`: 验证当 `DirectServiceStore` 中已存在匹配且未失效的 `validated` 记录时，不调用 `urllib.request.urlopen`，直接返回 `taskCallPerformed=False` 与 `streamingCapability="validated"`；
  - `test_validate_task_model_selection_reuses_unsupported_capability`: 验证已记录为 `unsupported` 的有效记录同样复用，不重新发起网络请求；
  - `test_validate_task_model_selection_reprobes_when_stale_or_missing`: 验证当服务修订或 Key 指纹变更变为 `stale` 或 `not_checked` 时，重新发起真实网络探测；
  - `test_validate_task_model_selection_deduplicates_in_flight_probes`: 模拟并发调用同一配置的验证，断言实际网络请求只发出一次。

- [x] **Step 2: 运行测试验证失败**
  运行：`PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/pytest -v adapter_service/tests/test_issue262_stream_validation.py`
  预期：FAIL（目前总是发起网络请求，缺少复用与去重逻辑）。

- [x] **Step 3: 在 `provider_client.py` 中实现能力复用与去重**
  - 在 `ProviderClient.__init__` 中初始化 `self._in_flight_streaming_probes = set()` 及 `self._streaming_probe_lock = threading.Lock()`；
  - 在 `validate_task_model_selection` 处理 `word.smart_write` / `word.smart_imitation` 前：
    - 查询现有 `streamingCapability` 判定：若存在且 `status in {"validated", "unsupported"}`，检查绑定指纹匹配，若匹配则直接返回复用结果（设置 `taskCallPerformed: False`）；
    - 若需要探测，获取探针锁并检查 `probe_key = f"{service_id}::{model_name}"` 是否已在 `_in_flight_streaming_probes` 中；
    - 执行探测并在 `finally` 中从 `_in_flight_streaming_probes` 移除该 key。

- [x] **Step 4: 运行测试验证通过**
  运行：`PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/pytest -v adapter_service/tests/test_issue262_stream_validation.py`
  预期：PASS。

- [x] **Step 5: 提交本任务修改**
  ```bash
  git add adapter_service/app/services/provider_client.py adapter_service/tests/test_issue262_stream_validation.py
  git commit -m "feat(adapter): support streaming capability reuse and in-flight probe deduplication"
  ```

---

### Task 2: Word 前端任务窗格按钮隔离与自动验证保存流 (taskpane.js / html)

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/issue262-word-stream-validation.test.js`

**Interfaces:**
- Consumes: `renderTaskModelSelectionSection`, `saveTaskModelSelection`, `getTaskModelSelectionDraft`
- Produces:
  - `renderTaskModelSelectionSection`: 针对 `word.smart_write` 和 `word.smart_imitation` 隐藏独立“验证调用”按钮，调整费用提示
  - `saveTaskModelSelection`:
    - 目录模型：先调用 `validate`，成功后再调用 `activate`；失败时保留草稿与原选择并回显错误
    - 手填模型：本地校验后立即调用 `activate` 设为当前，随后触发后台非阻塞 `validate` 探测；探测失败仅更新提示与流式状态，不撤销激活
  - 保留 `word.format_review` 与 `word.document_review` 及其他宿主的独立按钮

- [x] **Step 1: 编写失败的前端契约与行为测试**
  在 `formal-plugin-kit/tests/issue262-word-stream-validation.test.js` 中编写测试用例：
  - `test_word_smart_write_and_imitation_hides_validate_button`: 渲染 smart_write 和 smart_imitation 时，`btn-validate-task-model-selection` 必须 `hidden = true`；渲染 format_review 或 document_review 时保持 `hidden = false`；
  - `test_catalog_model_save_validates_first_and_aborts_on_failure`: 目录模型点击保存时，先请求 `/validate`；若返回 400/500 或网络错误，断言未发起 `/activate` 请求，保留当前选择和草稿，并向状态节点输出具体错误；
  - `test_catalog_model_save_activates_after_successful_validation`: 目录模型在 `/validate` 成功后才发起 `/activate` 请求，激活成功后正确刷新配置并显示成功信息；
  - `test_manual_model_save_activates_immediately_and_probes_in_background`: 手填模型点击保存时，立即发起 `/activate` 请求；随后在后台异步发起 `/validate` 探测；
  - `test_manual_model_background_probe_failure_retains_saved_selection`: 后台探测失败时，已激活的配置依然保留在 `state.taskModelSelections` 中，不被回滚或撤销，并在状态节点提示将使用普通调用；
  - `test_other_hosts_and_review_tasks_unaffected`: 检查 Excel、PPT 以及 Word 审查任务的独立验证按钮和保存流程未被破坏。

- [x] **Step 2: 运行测试验证失败**
  运行：`PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" node --test formal-plugin-kit/tests/issue262-word-stream-validation.test.js`
  预期：FAIL（按钮尚未隐藏，saveTaskModelSelection 尚未拆分目录前置验证与手填后台探测）。

- [x] **Step 3: 实现 taskpane.html 与 taskpane.js 改造**
  - 在 `renderTaskModelSelectionSection` 中：
    - 获取 `validateBtn = byId("word-task-validate-button")`（或 `#btn-validate-task-model-selection`）；
    - 若 `currentTask === "word.smart_write" || currentTask === "word.smart_imitation"`，设 `validateBtn.hidden = true`，更新费用提示文案明确保存会自动验证；
    - 否则设 `validateBtn.hidden = false`；
  - 在 `saveTaskModelSelection` 中：
    - 若为智能编写或智能仿写：
      - 判断所选模型是目录模型还是手填模型（含继承服务默认值的场景）；
      - **目录模型分支**：设置 busy 状态，提示“正在验证调用并检测流式能力...”，调用 `/provider/task-model-selections/{taskType}/validate`；若失败，显示错误并解除 busy，保留现场；若成功，继续调用原激活链路并保存；
      - **手填模型分支**：本地校验后立即调用 `/activate` 激活，激活成功后提示“已保存并设为当前，正在后台探测流式能力...”，触发后台异步探测，探测完成后更新流式状态，失败绝不回滚已保存选择。

- [x] **Step 4: 运行测试验证通过**
  运行：`PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" node --test formal-plugin-kit/tests/issue262-word-stream-validation.test.js`
  预期：PASS。

- [x] **Step 5: 提交本任务修改**
  ```bash
  git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/tests/issue262-word-stream-validation.test.js
  git commit -m "feat(plugin): auto-validate catalog models and background-probe manual models in Word writing tasks"
  ```

---

### Task 3: 任务执行流式回退与双运行时接口一致性验证

**Files:**
- Modify: `adapter_service/app/services/word/writing_jobs.py` (如有必要)
- Modify: `adapter_service/standalone_adapter.py` (如有必要)
- Test: `adapter_service/tests/test_issue262_stream_validation.py`
- Test: `formal-plugin-kit/tests/issue262-word-stream-validation.test.js`

**Interfaces:**
- Consumes: `word.smart_write` / `word.smart_imitation` 任务提交逻辑与增量预览事件
- Produces:
  - 验证有效流式能力开启增量预览，未验证或不支持模型平滑回退普通阻塞调用
  - FastAPI 与 Standalone 双运行时行为严格一致

- [ ] **Step 1: 编写任务执行流式回退与双运行时集成测试**
  - 在 `test_issue262_stream_validation.py` 中增加：
    - `test_smart_write_uses_streaming_when_capability_validated`: 当能力为 `validated` 时启动增量流式生成；
    - `test_smart_write_uses_blocking_when_capability_unsupported_or_not_checked`: 当能力为 `unsupported` 或 `not_checked`（手填未完成探测）时，以普通调用安全执行，不报错阻断；
    - `test_fastapi_and_standalone_parity_for_validation_and_streaming`: 验证 FastAPI 与 Standalone 运行时下验证端点和能力查询的完全对等。

- [ ] **Step 2: 运行测试验证**
  运行：`PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/pytest -v adapter_service/tests/test_issue262_stream_validation.py`
  预期：PASS（或根据缺失细节调整代码直至通过）。

- [ ] **Step 3: 提交本任务修改**
  ```bash
  git add adapter_service/ tests
  git commit -m "test(adapter): verify streaming fallback and dual-runtime parity for Word tasks"
  ```

---

### Task 4: 规范同步、全量回归与 Handoff 记录

**Files:**
- Modify: `docs/adr/0128-share-direct-model-services-across-hosts.md`
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: 更新 ADR-0128 文档**
  协调 ADR-0128 中关于手填模型与任务验证的约定：明确 Word 智能编写与智能仿写确认模型时自动处理验证，目录模型保存前自动验证流式能力，手填模型即刻保存并后台探测流式能力，未完成验证前使用普通调用。

- [ ] **Step 2: 执行全量本地契约与兼容性测试**
  - `PATH="/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH" node --test formal-plugin-kit/tests/*.test.js`
  - `git diff --check`
  - Python 3.8 兼容性检查

- [ ] **Step 3: 在 Kylin V10 ARM64 环境执行全量后端 pytest**
  - 通过 SSH 在 Kylin 虚拟机中运行：
    `ssh cloud@192.168.64.3 'cd /data/home/cloud/AI-WPS-kylin-test && git status && ...'`
  - 确保全量后端测试通过（0 failed）。

- [ ] **Step 4: 更新 `docs/codex-handoff.md`**
  记录 Issue #262 的改动背景、基准提交、新增测试结果与未验证边界。

- [ ] **Step 5: 提交最终文档**
  ```bash
  git add docs/adr/0128-share-direct-model-services-across-hosts.md docs/codex-handoff.md docs/superpowers/
  git commit -m "docs: update ADR-0128 and record handoff for issue #262"
  ```
