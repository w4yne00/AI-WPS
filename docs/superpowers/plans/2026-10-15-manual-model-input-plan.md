# 三宿主：支持手填默认模型及功能模型实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Word、PPT、Excel 三宿主中实现共享直连服务默认模型及各功能任务模型的手填输入与历史管理，支持即时增删手填模型与平滑重置，彻底解除目录限制与强制测试调用门禁。

**Architecture:** 
后端在 `DirectServiceStore` 中引入 `customModels` 持久化列表，提供即时增删轻量 API，并在删除在用模型时执行跨任务平滑重置；解除 `DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED` 与测试调用阻断，允许未验证模型执行任务；前端在三宿主任务窗格的模型选择下拉框中常驻手填入口，展开基于 Apple Design（Inset Grouped / Capsule 胶囊卡片）风格的手填模型管理面板，实现即时添加、单项删除与联动选用。

**Tech Stack:** Python 3.8、FastAPI、Starlette、Pydantic v2、Standalone HTTP Adapter；WPS JS/HTML/CSS、Node.js 契约测试。

**Spec:** `docs/superpowers/specs/2026-10-15-manual-model-input-design.md`

## Global Constraints

- 后端必须严格兼容 Python 3.8（ARM64 Kylin V10 SP1 与 Linux/macOS）。
- 前端兼容 WPS 内嵌 Chromium/CEF 内核，不引入外部第三方重量级库。
- 不得修改或提交 `config/adapter.json`、`run/`、`.scratch/` 等本地运行态数据。
- FastAPI 与 Standalone 双运行时接口行为与数据响应严格对齐。
- 遵循测试驱动开发（TDD）：每个任务先写失败测试，验证失败原因，再写实现代码，回归确保全部通过。
- 严禁静默切换模型：实际调用或测试调用失败必须向用户准确返回真实报错原因。

## Review Focus

1. **已删除手填模型正在被引用**：删除该模型后，引用的服务 `defaultModel` 清空为 `""`，任务选择的 `modelName` 置空且 `customModel` 设为 `False`，不阻断任务窗格正常运行。
2. **目录不可用或包含权限错误**：手填模型依然可以正常录入、保存和执行任务；实际请求必须携带用户填写的确切 `modelName`。
3. **目录正常可用且包含大量模型**：手填入口依然常驻可用，不再抛出 `DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED` 异常。
4. **多宿主并发保存任务手填模型**：任务保存时自动增量去重追加至 `customModels`，避免覆盖其他宿主已录入的模型。
5. **未验证模型直接执行任务**：未经测试调用的模型允许直接执行任务，不再因 `DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED` 报错拦截。

---

### Task 1: 后端数据模型与服务层手填模型管理 (DirectServiceStore)

**Files:**
- Modify: `adapter_service/app/services/direct_services.py`
- Test: `adapter_service/tests/test_issue257_manual_model_input.py`

**Interfaces:**
- Consumes: `load_config_payload`, `save_config_payload`, `DirectServiceError`
- Produces: 
  - `DirectServiceStore.add_custom_model(service_id: str, model_name: str) -> dict`
  - `DirectServiceStore.delete_custom_model(service_id: str, model_name: str) -> dict`
  - `DirectServiceStore._model_availability(...) -> Tuple[str, bool, str]`（解除 `custom_model` 必须已验证及目录可用的阻断）

- [ ] **Step 1: 编写失败的单元测试**
  在 `adapter_service/tests/test_issue257_manual_model_input.py` 中编写针对 `add_custom_model`、`delete_custom_model`（含平滑重置级联）以及解除目录可用限制与未验证限制的测试用例：
  - `test_add_and_list_custom_models`: 验证可成功向服务追加手填模型并自动去重；
  - `test_delete_custom_model_cascades_smooth_reset`: 验证删除手填模型后，若其为 `defaultModel` 则置空；若有 `taskModelSelections` 正在使用该模型，平滑重置为继承状态；
  - `test_custom_model_allowed_when_catalog_is_usable`: 验证目录完全可用时，保存和查询手填模型不会触发 `DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED`；
  - `test_unverified_custom_model_is_available_for_selection`: 验证未测试调用的手填模型状态为 `modelAvailable: True`，可正常保存并设为当前。

- [ ] **Step 2: 在 Kylin V10 上运行测试验证失败**
  运行：`ssh cloud@192.168.64.3 'cd /data/home/cloud/AI-WPS-kylin-test && PATH=/data/home/cloud/.venvs/ai-wps-test-py38/bin:$PATH PYTHONPATH=adapter_service /data/home/cloud/.venvs/ai-wps-test-py38/bin/python -m pytest -q adapter_service/tests/test_issue257_manual_model_input.py'`
  预期：FAIL（`add_custom_model` 不存在，目录可用时仍报错）。

- [ ] **Step 3: 实现 `direct_services.py` 中的手填模型方法与解耦逻辑**
  - 在服务定义解析与序列化中确保 `customModels: List[str]` 字段存在（默认 `[]`）；
  - 实现 `add_custom_model(service_id: str, model_name: str) -> dict`：校验非空合法性，去重追加至 `service["customModels"]`，原子写入；
  - 实现 `delete_custom_model(service_id: str, model_name: str) -> dict`：从 `service["customModels"]` 移除；若 `service.get("defaultModel") == model_name`，置为 `""`；遍历所有 `taskModelSelections`，若 `sel.get("serviceId") == service_id and sel.get("modelName") == model_name`，重置为 `modelName = "", customModel = False, customModelValidated = False`；
  - 移除 `_model_availability` 和 `_ensure_task_model_ready` 中对 `custom_model and not custom_validated` 和 `catalog_usable` 的阻断异常；
  - 在 `save_task_model_selection` 中，若 `is_custom` 且 `clean_model` 有效，自动追加至该服务的 `customModels` 清单。

- [ ] **Step 4: 同步代码并运行测试验证通过**
  同步至 Kylin 并运行：`test_issue257_manual_model_input.py`。
  预期：PASS。

- [ ] **Step 5: 提交本任务修改**
  ```bash
  git add adapter_service/app/services/direct_services.py adapter_service/tests/test_issue257_manual_model_input.py
  git commit -m "feat: support customModels management and unblock manual models in DirectServiceStore"
  ```

---

### Task 2: 双运行时 REST 路由 (FastAPI & Standalone) 与 ProviderClient 执行支持

**Files:**
- Modify: `adapter_service/app/api/direct_services.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_issue257_manual_model_input.py`

**Interfaces:**
- Consumes: `DirectServiceStore.add_custom_model`, `DirectServiceStore.delete_custom_model`
- Produces: 
  - `POST /provider/direct-services/{service_id}/custom-models` (FastAPI & Standalone)
  - `DELETE /provider/direct-services/{service_id}/custom-models/{model_name}` (FastAPI & Standalone)
  - `ProviderClient.post_task` 支持未验证的手填模型正常发起真实调用

- [ ] **Step 1: 编写失败的端点与执行测试**
  在 `test_issue257_manual_model_input.py` 中新增端点测试与 ProviderClient 任务执行测试：
  - `test_fastapi_and_standalone_custom_models_endpoints`: 分别通过 `TestClient` 和 Standalone HTTP 请求调用 `POST` 和 `DELETE` 端点，断言状态码与响应体对等；
  - `test_provider_client_executes_unverified_custom_model`: 验证 `ProviderClient.post_task` 在使用未验证手填模型时，不抛出 `DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED`，真实请求体中的 `model` 字段为保存的手填模型 ID。

- [ ] **Step 2: 运行测试验证失败**
  运行：`test_issue257_manual_model_input.py`
  预期：FAIL（404 Not Found 或 `DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED` 报错）。

- [ ] **Step 3: 实现双运行时端点与 ProviderClient 解绑**
  - 在 `adapter_service/app/api/direct_services.py` 中增加路由：
    - `@router.post("/direct-services/{service_id}/custom-models")`
    - `@router.delete("/direct-services/{service_id}/custom-models/{model_name}")`
  - 在 `adapter_service/standalone_adapter.py` 的请求分发中增加上述两条路由的处理；
  - 在 `adapter_service/app/services/provider_client.py` 中移除 `DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED` 和 `DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED` 的拦截代码，保留有效模型名称检查和凭据指纹检查。

- [ ] **Step 4: 运行测试验证通过**
  同步至 Kylin 并运行：`test_issue257_manual_model_input.py`。
  预期：PASS。

- [ ] **Step 5: 提交本任务修改**
  ```bash
  git add adapter_service/app/api/direct_services.py adapter_service/standalone_adapter.py adapter_service/app/services/provider_client.py adapter_service/tests/test_issue257_manual_model_input.py
  git commit -m "feat: expose custom-models endpoints and support unverified task execution"
  ```

---

### Task 3: Word 插件手填模型下拉选项与 Apple Design 管理面板

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Create: `formal-plugin-kit/tests/issue257-manual-model-input.test.js`

**Interfaces:**
- Consumes: 后端 `GET /provider/direct-services`, `POST/DELETE /provider/direct-services/{id}/custom-models`
- Produces: 
  - `renderModelOptionsWithCustom(selectElement, catalogModels, customModels, currentModel, isDefaultModelSelect)`
  - `.custom-models-panel` 组件与交互（展开/折叠、添加、删除、平滑重置）

- [ ] **Step 1: 编写失败的前端契约测试**
  创建 `formal-plugin-kit/tests/issue257-manual-model-input.test.js`：
  - 测试下拉框渲染包含目录模型、已存手填模型与「输入 / 管理手填模型」（`value="__manual__"`）；
  - 测试选择「输入 / 管理手填模型」时管理面板展开；选择目录模型时管理面板收起；
  - 测试在管理面板中添加新模型触发即时 POST 请求并刷新清单；
  - 测试在管理面板中点击删除触发即时 DELETE 请求，并在被删除模型为当前选中模型时平滑回退为继承服务默认。

- [ ] **Step 2: 运行前端契约测试验证失败**
  运行：`node --test formal-plugin-kit/tests/issue257-manual-model-input.test.js`
  预期：FAIL。

- [ ] **Step 3: 实现 Word 插件 UI 与交互**
  - 在 `taskpane.html` 中：为直连服务编辑卡片和任务模型选择区域分别加入 `.custom-models-panel` 容器模板；
  - 在 `taskpane.css` 中：按照 Apple Design 规范添加 Inset Grouped 样式、Capsule 药丸标签样式、删除按钮悬浮微红及 `:active { transform: scale(0.96); }` 物理动效；
  - 在 `taskpane-helpers.js` 中：更新 `validateActiveDirectTaskSelection`，允许未测试的手填模型通过就绪校验；
  - 在 `taskpane.js` 中：实现下拉框手填模型分组与 `__manual__` 选项渲染，绑定展开/收起事件，实现即时添加与删除网络请求，并在删除当前模型时自动重置。

- [ ] **Step 4: 运行前端契约测试验证通过**
  运行：`node --test formal-plugin-kit/tests/issue257-manual-model-input.test.js`
  预期：PASS。

- [ ] **Step 5: 提交本任务修改**
  ```bash
  git add formal-plugin-kit/wps-ai-assistant_1.0.0/ formal-plugin-kit/tests/issue257-manual-model-input.test.js
  git commit -m "feat(word): implement Apple-designed custom models management panel"
  ```

---

### Task 4: Excel 与 PPT 插件对齐手填模型面板 (Three Hosts Parity)

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/issue257-manual-model-input.test.js`

**Interfaces:**
- Consumes: Word 插件中已验证的面板模板与状态机模式
- Produces: Excel 与 PPT 插件对等具备手填模型管理能力

- [ ] **Step 1: 在契约测试中加入 Excel 与 PPT 测试用例**
  扩展 `formal-plugin-kit/tests/issue257-manual-model-input.test.js`，加入针对 Excel (`wps-ai-assistant-et_1.0.0`) 和 PPT (`wps-ai-assistant-wpp_1.0.0`) 的面板展开、即时添加、单项删除与平滑回退测试断言。

- [ ] **Step 2: 运行测试验证失败**
  运行：`node --test formal-plugin-kit/tests/issue257-manual-model-input.test.js`
  预期：Excel 与 PPT 对应的测试用例 FAIL。

- [ ] **Step 3: 将 Word 插件的实现模式移植并适配到 ET 与 WPP**
  - 同步更新 ET 的 `taskpane.html`、`taskpane.css`、`taskpane-helpers.js` 与 `taskpane.js`；
  - 同步更新 WPP 的 `taskpane.html`、`taskpane.css`、`taskpane-helpers.js` 与 `taskpane.js`；
  - 确保三宿主交互体验、元素命名与行为契约 100% 对齐。

- [ ] **Step 4: 运行前端契约测试验证通过**
  运行：`node --test formal-plugin-kit/tests/issue257-manual-model-input.test.js`
  预期：Word、Excel、PPT 全部通过。

- [ ] **Step 5: 提交本任务修改**
  ```bash
  git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/ formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ formal-plugin-kit/tests/issue257-manual-model-input.test.js
  git commit -m "feat(et,wpp): align manual model input management across Excel and PPT"
  ```

---

### Task 5: ADR-0128 同步更新与全量系统回归 (Delivery Verification)

**Files:**
- Modify: `docs/adr/0128-share-direct-model-services-across-hosts.md`
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: 更新 ADR-0128 架构决策记录**
  在 `docs/adr/0128-share-direct-model-services-across-hosts.md` 中：
  - 更新关于手填模型必须先通过验证调用才能生效的陈旧规定；
  - 补充手填模型清单（`customModels`）常驻可用、即时增删管理及删除在用模型时的平滑重置规则。

- [ ] **Step 2: 运行前端全部契约测试与原型测试**
  在工作区运行：
  - `node --test formal-plugin-kit/tests/*.test.js`（验证全部插件契约无退化）
  - `npm --prefix wps-addon test` 与 `npm --prefix wps-addon run build`

- [ ] **Step 3: 在 Kylin V10 ARM64 上运行全量后端测试**
  同步最新代码到 Kylin V10，并运行：
  - `ssh cloud@192.168.64.3 'cd /data/home/cloud/AI-WPS-kylin-test && PATH=/data/home/cloud/.venvs/ai-wps-test-py38/bin:/data/home/cloud/.local/bin:$PATH PYTHONPATH=adapter_service /data/home/cloud/.venvs/ai-wps-test-py38/bin/python -m pytest -q adapter_service/tests'`
  预期：1800+ 项测试全绿，0 失败。

- [ ] **Step 4: 运行交付兼容性扫描与 Git 差异检查**
  在工作区运行：
  - `python3 packaging/check_python38_compatibility.py`
  - `git diff --check`
  预期：0 语法兼容性错误，0 格式/空白警告。

- [ ] **Step 5: 更新 `docs/codex-handoff.md` 并提交完成记录**
  记录 Issue #257 开发过程、全量测试数据与未验证项（真实模型扣费及真实 WPS GUI 渲染需人工验收）。
  ```bash
  git add docs/adr/0128-share-direct-model-services-across-hosts.md docs/codex-handoff.md
  git commit -m "docs: update ADR-0128 and record handoff for issue #257"
  ```
