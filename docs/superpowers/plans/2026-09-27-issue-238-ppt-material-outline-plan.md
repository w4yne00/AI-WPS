# PPT：根据资料生成并确认逐页大纲实施计划 (Issue #238)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PPT 宿主中实现从 DOCX 资料生成并确认逐页大纲的功能：支持主动导入或跨宿主复用资料并保持演示文稿独立副本，按指定的汇报对象和页数生成带结构化角色、依据和缺项的逐页大纲，提供显式大纲确认门禁（作为后续内容生成的前置条件），全流程保持幻灯片纯只读。

**Architecture:**
1. 后端构建 `PptMaterialStore`，在 `$AI_WPS_STATE_DIR/ppt_materials/` 建立当前演示文稿的独立持久化资料目录，并与 Word/Excel 共同注册到 `GET /materials/reusable-sources` 实现全局资料源发现与单向原子克隆（`clone-from-source`）。
2. 建立 `ppt.material_outline` 长任务协调器，结合专属系统提示词，按汇报对象（`audience`）和页数（`slideCount`）提取结构化逐页大纲（`ppt.material_outline.v1`），严谨校验页面角色、页数一致性、片段出处与缺项。
3. 双运行时（FastAPI 与 Standalone）对等暴露资料管理与大纲任务接口（提交、轮询、取消、冲突检测）。
4. 正式插件 (`wps-ai-assistant-wpp_1.0.0`) 新增「资料大纲」Ribbon 入口与独立 `material-outline.js` 控制器，支持资料管理/复用、参数配置、逐页大纲渲染、出处侧栏抽屉、以及显式大纲确认状态机（`unconfirmed` -> `confirmed` -> `needs_reconfirmation`），全流程严格 0 幻灯片写入。

**Tech Stack:** Python 3.8, FastAPI, Pydantic, Node.js (`node --test`), WPS JSAPI/HTML/CSS.

**Spec:** [docs/superpowers/specs/2026-09-27-issue-238-ppt-material-outline-design.md](file:///Users/wayne/Documents/New%20project/AI-WPS/.worktrees/issue-238-ppt-material-outline/docs/superpowers/specs/2026-09-27-issue-238-ppt-material-outline-design.md)

## Global Constraints

- Python 3.8 语法兼容，严禁使用 3.9+ 特性（如 `list[str]`、`dict[str, Any]`、`str.removeprefix` 等）。
- 资料安全上限：单会话最多 5 份 DOCX、累计 100,000 Unicode 可读字符、每表最多 256 列、累计 100,000 展开单元格。
- 请求体上限：除上传文件 Base64 解码流外，所有 POST/PUT 请求体严格执行 64 KiB 门禁。
- 独立资料生命周期：跨宿主复用必须是原子克隆，演示文稿后续任何更新或删除不得污染或改变原来源文档。
- 纯只读保证：全生命周期严禁调用任何新增幻灯片、修改形状或写入文本的 COM/JSAPI 接口。
- 不可触碰文件：`config/adapter.json`、`run/`、`.scratch/` 等本地审查及临时文件不得提交。

## Review Focus

1. **跨宿主复用后的独立性**：在 PPT 中复用 Word 或 Excel 资料后，在 PPT 中更新或删除单份资料，原 Word/Excel 资料目录中的文件与元数据必须完好无损；反之原文档修改资料，PPT 端绝不自动变更。
2. **汇报对象与页数严格对齐**：用户指定生成 N 页（如 6 页），模型与校验器返回的 `slides` 数组长度必须严格等于 N，且各页角色合理（如第 1 页为 `cover`，末页为 `summary`/`backcover`），页数不匹配时拒绝入库。
3. **缺项与虚假出处防御**：资料未提及的重要信息必须记录在对应页的 `missingItems` 中；每页引用的 `fragmentIds` 必须真实存在于资料库中，虚假出处 fail-closed 拦截。
4. **大纲确认门禁契约 (Gate for #239)**：未经用户显式确认的大纲，门禁检查 `hasConfirmedOutline()` 严格返回 `false`；用户微调大纲标题/要点、修改参数或资料更新后，状态自动降级为 `needs_reconfirmation`。
5. **只读保证**：即便用户在窗格中完成全套大纲生成、审阅、出处查看、编辑与确认，WPS 幻灯片写入接口调用计数严格为 0。

---

### Task 1: 提示词与逐页大纲响应协议 (`ppt.material_outline`)

**Files:**
- Create: `adapter_service/system_prompts/ppt-material-outline.md`
- Modify: `adapter_service/system_prompts/manifest.json`
- Modify: `adapter_service/app/services/provider_client.py:2780-2810`
- Modify: `adapter_service/app/services/workflow_profiles.py:13-26`
- Test: `adapter_service/tests/test_ppt_material_outline_prompt.py`

**Interfaces:**
- Produces: `TASK_TYPE = 'ppt.material_outline'`, `SystemPromptStore.get_prompt("ppt.material_outline")`
- Schema: 顶层 `schemaVersion: "ppt.material_outline.v1"`, `slides: [{"pageIndex": int, "pageRole": str, "title": str, "keyPoints": [str], "missingItems": [str], "fragmentIds": [int]}]`

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_material_outline_prompt.py
import pytest
from app.services.system_prompts import SystemPromptStore
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS

def test_ppt_material_outline_prompt_registered():
    store = SystemPromptStore()
    prompt = store.get_prompt("ppt.material_outline")
    assert prompt is not None
    assert "ppt.material_outline.v1" in prompt
    assert "汇报对象" in prompt
    assert "页数" in prompt
    assert "pageRole" in prompt
    assert "missingItems" in prompt

def test_ppt_material_outline_in_supported_tasks():
    assert "ppt.material_outline" in SUPPORTED_WORKFLOW_TASKS
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline_prompt.py`
预期：FAIL with "SystemPromptNotFoundError" 或 AssertionError

- [ ] **Step 3: 编写最小实现**

1. 在 `adapter_service/system_prompts/manifest.json` 中注册 `ppt.material_outline`；
2. 创建 `adapter_service/system_prompts/ppt-material-outline.md`，定义大纲生成规则、页面角色（`cover`、`agenda`、`transition`、`content`、`summary`、`backcover`）、页数对应约束、依据引用及缺项规范；
3. 在 `adapter_service/app/services/provider_client.py` 的 `tasks` 列表中追加 `("ppt.material_outline", "逐页大纲")`；
4. 在 `adapter_service/app/services/workflow_profiles.py` 的 `SUPPORTED_WORKFLOW_TASKS` 中追加 `"ppt.material_outline"`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline_prompt.py`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/system_prompts/ adapter_service/app/services/provider_client.py adapter_service/app/services/workflow_profiles.py adapter_service/tests/test_ppt_material_outline_prompt.py
git commit -m "feat(ppt): register ppt.material_outline prompt and task type"
```

---

### Task 2: PPT 资料仓储与跨宿主原子克隆 (`PptMaterialStore`)

**Files:**
- Create: `adapter_service/app/services/ppt/material_store.py`
- Modify: `adapter_service/app/services/excel/material_store.py:60-75, 120-150`
- Test: `adapter_service/tests/test_ppt_material_import.py`

**Interfaces:**
- Produces:
  - `PptMaterialStore`:
    - `list_reusable_sources() -> List[dict]`
    - `clone_from_source(source_session_id: str, target_session_id: str, target_doc_identity: str) -> dict`
    - `import_material(...) -> dict`
    - `update_material(...) -> dict`
    - `delete_material(...) -> dict`
    - `get_catalog(session_id: str) -> dict`
    - `bind_document(...) -> dict`
- Invariants: 克隆为深复制独立副本，PPT 端的更新/删除 100% 不影响原 Word/Excel/PPT 目录。

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_material_import.py
import pytest
from app.services.ppt.material_store import PptMaterialStore
from app.services.word.material_import import WordMaterialStore

def test_ppt_material_store_import_and_clone(tmp_path):
    word_dir = tmp_path / "word"
    ppt_dir = tmp_path / "ppt"
    word_store = WordMaterialStore(base_dir=word_dir)
    ppt_store = PptMaterialStore(base_dir=ppt_dir, word_base_dir=word_dir)
    
    # 验证初始为空
    sources = ppt_store.list_reusable_sources()
    assert isinstance(sources, list)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_import.py`
预期：FAIL with "ModuleNotFoundError" (`app.services.ppt.material_store`)

- [ ] **Step 3: 编写 `PptMaterialStore` 最小实现**

在 `adapter_service/app/services/ppt/material_store.py` 中实现：
1. 继承/复用成熟的资料导入、解码校验、容量计算逻辑（5 份 / 10 万字安全门禁）；
2. 聚合扫描 `word_materials`、`excel_materials` 与 `ppt_materials` 返回全局可复用来源；
3. 原子克隆源目录文件与大纲元数据至目标演示文稿专属目录；
4. 单份资料原子更新（`update_material`）与物理清理（`delete_material`）；
5. 演示文稿忙状态检查（活跃 `ppt.material_outline` 任务时返回 409 `MATERIAL_COMPOSER_BUSY`）；
6. 同步让 `ExcelMaterialStore` 的 `list_reusable_sources` 识别 `ppt_materials`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_import.py`
预期：PASS（涵盖上传、容量限制、三端跨宿主克隆、独立更新与移除）

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/ppt/material_store.py adapter_service/app/services/excel/material_store.py adapter_service/tests/test_ppt_material_import.py
git commit -m "feat(ppt): add PptMaterialStore with cross-host material cloning"
```

---

### Task 3: 逐页大纲生成长任务协调器 (`PptMaterialOutlineCoordinator`)

**Files:**
- Create: `adapter_service/app/services/ppt/material_outline.py`
- Test: `adapter_service/tests/test_ppt_material_outline.py`

**Interfaces:**
- Consumes: `PptMaterialStore`, `SystemPromptStore`, `ProviderClient`, `LongTaskCoordinator`
- Produces: `PptMaterialOutlineCoordinator`:
  - `detect_conflicts(document_session_id: str, user_facts: str) -> List[dict]`
  - `submit_job(payload: dict, trace_id: str) -> dict`
  - `query_job(job_id: str, document_session_id: str) -> dict`
  - `cancel_job(job_id: str, document_session_id: str) -> dict`

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_material_outline.py
import pytest
from app.services.ppt.material_outline import PptMaterialOutlineCoordinator
from app.services.ppt.material_store import PptMaterialStore

def test_ppt_material_outline_submission_and_validation(tmp_path):
    store = PptMaterialStore(base_dir=tmp_path / "ppt")
    coordinator = PptMaterialOutlineCoordinator(store=store)
    # 验证参数校验：缺少 session_id 拒绝
    with pytest.raises(Exception):
        coordinator.submit_job({})
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline.py`
预期：FAIL with "ModuleNotFoundError" (`app.services.ppt.material_outline`)

- [ ] **Step 3: 编写 `PptMaterialOutlineCoordinator` 最小实现**

1. 请求校验：`documentSessionId`、`clientJobId`（幂等重试）、`audience`、`slideCount`（4~20 范围）、`userFacts`、`conflictResolutions`、64 KiB 上限；
2. 构造用户提示词：注入汇报对象、目标页数、写作重点、用户事实、冲突裁决与已召回事实片段；
3. 模型调用与输入 Token 预算核验（超限返回 413 `MODEL_INPUT_OVER_BUDGET`）；
4. 结构化大纲解析与强校验：
   - 必须为 `ppt.material_outline.v1` 协议；
   - 校验 `slides` 长度必须严格等于用户指定的 `slideCount`；
   - 校验各页 `pageRole` 属于已知合法枚举；
   - 校验每页引用的 `fragmentIds`，反查并填充出处信息（文件名、章节、原文片段）；
   - 保留每页的 `missingItems`；
5. 结果快照中记录 `basisMaterials`（资料 ID、文件名、生成时的 `updatedAt` 时间戳）与 `generatedAt`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline.py`
预期：PASS（涵盖大纲生成、页数严格校验、片段反查、长任务取消与恢复）

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/ppt/material_outline.py adapter_service/tests/test_ppt_material_outline.py
git commit -m "feat(ppt): add PptMaterialOutlineCoordinator for page outline generation"
```

---

### Task 4: API 路由与双运行时对等支持 (FastAPI & Standalone)

**Files:**
- Modify: `adapter_service/app/api/ppt.py`
- Modify: `adapter_service/app/main.py:220-225, 595-635`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_ppt_material_outline_api.py`

**Interfaces:**
- Endpoints (FastAPI & Standalone):
  - `POST /ppt/materials/import`
  - `POST /ppt/materials/clone-from-source`
  - `GET /ppt/materials/catalog`
  - `PUT /ppt/materials/{material_id}`
  - `DELETE /ppt/materials/{material_id}`
  - `POST /ppt/materials/bind-document`
  - `GET/POST /ppt/material-outline/conflicts`
  - `POST /ppt/material-outline/jobs`
  - `GET /ppt/material-outline/jobs/{job_id}`
  - `POST /ppt/material-outline/jobs/{job_id}/cancel`

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_material_outline_api.py
import pytest
from starlette.testclient import TestClient
from app.main import app

def test_ppt_material_endpoints_exist():
    client = TestClient(app)
    res = client.get("/ppt/materials/catalog?documentSessionId=test")
    assert res.status_code == 200
    res_jobs = client.post("/ppt/material-outline/jobs", json={})
    assert res_jobs.status_code == 422
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline_api.py`
预期：FAIL with 404 Not Found

- [ ] **Step 3: 编写 API 路由与双运行时实现**

1. 在 `adapter_service/app/api/ppt.py` 中挂载 PPT 资料与大纲相关路由，注入 `ppt_material_store` 与 `ppt_material_outline`；
2. 在 `adapter_service/app/main.py` 的 `_task_type_from_path` 中映射 `/ppt/material-outline/` 与 `/ppt/materials/`；
3. 在 `adapter_service/standalone_adapter.py` 中对等实现 `do_GET`、`do_POST`、`do_PUT`、`do_DELETE` 的路由分发与统一信封封装。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_material_outline_api.py`
预期：PASS（FastAPI 与 Standalone 双运行时全套路由测试通过）

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/api/ppt.py adapter_service/app/main.py adapter_service/standalone_adapter.py adapter_service/tests/test_ppt_material_outline_api.py
git commit -m "feat(ppt): expose ppt materials and outline endpoints in dual runtimes"
```

---

### Task 5: PPT 插件独立控制器与大纲确认门禁 (`material-outline.js`)

**Files:**
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/material-outline.js`
- Test: `formal-plugin-kit/tests/ppt-material-outline.test.js`

**Interfaces:**
- Produces: `window.createMaterialOutline` / `module.exports`:
  - `stateFor(sessionId)`
  - `submit()`
  - `cancel()`
  - `poll()`
  - `confirmOutline()`: 冻结当前大纲至 `confirmedOutline`
  - `updateSlideTitle(pageIndex, newTitle)`
  - `updateSlideKeyPoints(pageIndex, keyPoints)`
  - `hasConfirmedOutline()`: 确认门禁检查接口（`boolean`）
  - `getConfirmedOutline()`: 获取已确认大纲快照

- [ ] **Step 1: 编写失败测试**

```javascript
// formal-plugin-kit/tests/ppt-material-outline.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { createMaterialOutline } = require("../wps-ai-assistant-wpp_1.0.0/material-outline.js");

test("material outline controller manages outline and confirmation gate", () => {
  const controller = createMaterialOutline();
  assert.equal(controller.hasConfirmedOutline(), false);
});
```

- [ ] **Step 2: 运行测试验证失败**

运行：`node --test formal-plugin-kit/tests/ppt-material-outline.test.js`
预期：FAIL with "Cannot find module"

- [ ] **Step 3: 编写 `material-outline.js` 最小实现**

1. 会话隔离状态存储（`stateFor(sessionId)`）；
2. 资料条带与复用管理（`importMaterial`、`cloneFromSource`、`deleteMaterial`、`updateMaterial`）；
3. 参数校验：`audience`、`slideCount`（4~20，默认 8）；
4. 任务提交、各阶段中文提示（排队、准备、生成、校验）、取消与自动轮询；
5. **大纲确认门禁状态机**：
   - 生成大纲后默认为 `unconfirmed`，`hasConfirmedOutline() === false`；
   - 调用 `confirmOutline()`：记录 `confirmedOutline` 快照与确认时间戳，状态置为 `confirmed`，`hasConfirmedOutline() === true`；
   - 用户编辑任意标题/要点，或资料发生更新/移除（依据失效）：状态自动置为 `needs_reconfirmation`，`hasConfirmedOutline() === false`；
6. 文本与 Markdown/TSV 导出复制。

- [ ] **Step 4: 运行测试验证通过**

运行：`node --test formal-plugin-kit/tests/ppt-material-outline.test.js`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/material-outline.js formal-plugin-kit/tests/ppt-material-outline.test.js
git commit -m "feat(ppt): add material-outline.js controller with confirmation gate"
```

---

### Task 6: PPT 功能区与任务窗格集成与只读保证

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.xml`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/ppt-material-outline.test.js`

**Interfaces:**
- Ribbon: `<button id="btnAiPptMaterialOutline" label="资料大纲" ...>`
- Mode: `pptMaterialOutline`
- Invariant: PPT 写入接口（`Presentation.Slides.Add` 等）在全交互过程中调用严格为 0。

- [ ] **Step 1: 编写失败测试**

在 `formal-plugin-kit/tests/ppt-material-outline.test.js` 中增加测试用例：
1. 验证 Ribbon 按钮定义与模式映射 `pptMaterialOutline`；
2. 验证 Taskpane DOM 包含资料条带、参数输入、大纲列表、出处抽屉与确认操作栏；
3. 验证点击「确认大纲」的界面响应与门禁就绪提示；
4. **只读保证测试**：断言整个大纲生成与确认流程中，WPS 幻灯片写入 API 调用次数严格为 0。

- [ ] **Step 2: 运行测试验证失败**

运行：`node --test formal-plugin-kit/tests/ppt-material-outline.test.js`
预期：FAIL with assertion error (DOM elements or mode missing)

- [ ] **Step 3: 编写界面与集成代码**

1. 在 `ribbon.xml` 增设「资料大纲」按钮；
2. 在 `ribbon.js` 的 `resolveMode` 映射 `btnAiPptMaterialOutline -> "pptMaterialOutline"`；
3. 在 `taskpane.html` 增设 `#ppt-material-outline-options` 容器与 `#outline-result-section`；
4. 在 `taskpane.css` 增加卡片排版、Badge 样式、黄色缺项警示与底部常驻确认栏样式；
5. 在 `taskpane.js` 中引入 `material-outline.js` 并绑定模式切换与渲染钩子。

- [ ] **Step 4: 运行测试验证通过**

运行：`node --test formal-plugin-kit/tests/ppt-material-outline.test.js`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ formal-plugin-kit/tests/ppt-material-outline.test.js
git commit -m "feat(ppt): integrate material outline UI into taskpane and ribbon"
```

---

### Task 7: 全量回归、交付门禁与只读验证

**Files:**
- Test: `formal-plugin-kit/tests/ppt-*.test.js`
- Test: `formal-plugin-kit/tests/excel-material-ledger.test.js`
- Test: `adapter_service/tests/test_ppt_*.py`
- Test: `adapter_service/tests/test_excel_material_*.py`

- [ ] **Step 1: 运行后端全量相关测试**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_ppt_*.py adapter_service/tests/test_excel_material_*.py`
预期：PASS

- [ ] **Step 2: 运行插件全量相关契约测试**

运行：`node --test formal-plugin-kit/tests/ppt-*.test.js formal-plugin-kit/tests/excel-material-ledger.test.js`
预期：PASS

- [ ] **Step 3: 语法编译与差异检查**

运行：
```bash
python3 -m compileall adapter_service/app
git diff --check
```
预期：0 语法错误，0 格式/空白警告。

- [ ] **Step 4: 更新 Codex Handoff 文档**

在 [docs/codex-handoff.md](file:///Users/wayne/Documents/New%20project/AI-WPS/docs/codex-handoff.md) 顶部记录 Issue #238 的实现总结、核心架构与自检结论。

- [ ] **Step 5: 提交代码**

```bash
git add docs/codex-handoff.md
git commit -m "docs: update codex handoff for issue 238 ppt material outline"
```
