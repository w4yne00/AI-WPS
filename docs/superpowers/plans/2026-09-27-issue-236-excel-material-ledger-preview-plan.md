# Excel：从资料生成任务台账预览实施计划 (Issue #236)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Excel 宿主中实现从 DOCX 资料生成任务台账预览的功能，支持主动导入或跨文档复用资料并保持工作簿独立副本，按自定义或选区表头提取一行一项可独立跟踪的工作，留空并提示缺项，提示疑似重复不擅自合并，侧栏展示出处，预览阶段严格不修改任何单元格。

**Architecture:**
1. 后端构建 `ExcelMaterialStore`，在 `$AI_WPS_STATE_DIR/excel_materials/` 建立当前工作簿的独立持久化资料目录，并提供全局资料源发现（`reusable-sources`）与原子克隆（`clone-from-source`），实现单向解耦。
2. 建立 `excel.material_ledger` 长任务处理器，基于提示词约束和片段提取器，按自定义表头提取结构化台账，严谨校验片段出处、缺项与疑似重复。
3. 双运行时（FastAPI 与 Standalone）对等暴露资料管理与台账生成、轮询和取消接口。
4. 正式插件 (`wps-ai-assistant-et_1.0.0`) 新增「任务台账」Ribbon 入口与 `material-ledger.js` 控制器，支持表头自定义/选区读取、资料管理/复用、表格只读预览、缺项高亮、重复提示气泡、出处抽屉以及 TSV 复制，全流程严格 0 单元格写入。

**Tech Stack:** Python 3.8, FastAPI, Pydantic, Node.js (`node --test`), WPS JSAPI/HTML/CSS.

**Spec:** [docs/superpowers/specs/2026-09-27-issue-236-excel-material-ledger-preview-design.md](file:///Users/wayne/Documents/New%20project/AI-WPS/.worktrees/issue-236-excel-material-ledger-preview/docs/superpowers/specs/2026-09-27-issue-236-excel-material-ledger-preview-design.md)

## Global Constraints

- Python 3.8 语法兼容，严禁使用 3.9+ 特性（如 `list[str]`、`dict[str, Any]`、`str.removeprefix` 等）。
- 资料安全上限：单会话最多 5 份 DOCX、累计 100,000 Unicode 可读字符、每表最多 256 列、累计 100,000 展开单元格。
- 请求体上限：除上传文件 Base64 解码流外，所有 POST/PUT 请求体严格执行 64 KiB 门禁。
- 独立资料生命周期：复用必须是原子克隆，工作簿后续任何更新或删除不得污染或改变原来源文档。
- 纯只读预览：全生命周期严禁调用任何写入工作表或单元格的 COM/JSAPI 接口。
- 不可触碰文件：`config/adapter.json`、`run/`、`.scratch/` 等本地审查及临时文件不得提交。

## Review Focus

1. **跨文档复用后的独立性**：在 Excel 中复用 Word 文档资料后，在 Excel 中更新或删除单份资料，原 Word 资料目录中的文件和大纲必须完好无损；原 Word 文档修改资料，Excel 也绝不自动变更。
2. **表头字段映射与缺项保护**：当资料未提及某列（如“完成时间”）时，模型和校验器必须输出空字符串，绝不能填充虚假日期或“暂无/TBD”等字符串，界面正确展示缺项标签。
3. **疑似重复不合并**：提取中遇到语义高度重叠的事项，模型与系统必须标明 `isDuplicate: true` 与 `duplicateReason`，同时完整保留两行数据，绝对不擅自合并或丢弃任何一行。
4. **出处真实性防御**：台账中的每一行绑定的 `fragmentIds` 必须真实存在于资料库中；若出现伪造或失效的 `fragmentId`，必须 fail-closed 拦截并提示出处校验失败。
5. **只读保证**：即便用户在预览界面完成全套操作（生成、滚动、展开出处、复制 TSV、重开恢复），WPS 表格写入接口调用计数严格为 0。

---

### Task 1: 提示词与模型响应校验协议 (`excel.material_ledger`)

**Files:**
- Create: `adapter_service/system_prompts/excel-material-ledger.md`
- Modify: `adapter_service/system_prompts/manifest.json`
- Test: `adapter_service/tests/test_excel_material_ledger_prompt.py`

**Interfaces:**
- Produces: `TASK_TYPE = 'excel.material_ledger'`, `SystemPromptStore.get_prompt("excel.material_ledger")`
- Schema: 顶层 `schemaVersion: "excel.material_ledger.v1"`, `rows: [{"values": {...}, "missingFields": [...], "isDuplicate": bool, "duplicateOfIndex": int|null, "duplicateReason": str, "fragmentIds": [int]}]`

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_excel_material_ledger_prompt.py
import pytest
from app.services.system_prompts import SystemPromptStore

def test_excel_material_ledger_prompt_registered():
    store = SystemPromptStore()
    prompt = store.get_prompt("excel.material_ledger")
    assert prompt is not None
    assert "excel.material_ledger.v1" in prompt
    assert "一行一项" in prompt
    assert "缺项" in prompt
    assert "疑似重复" in prompt
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger_prompt.py`
预期：FAIL with "SystemPromptNotFoundError" 或 prompt is None

- [ ] **Step 3: 编写最小实现**

在 `adapter_service/system_prompts/manifest.json` 中注册 `excel.material_ledger`；
创建 `adapter_service/system_prompts/excel-material-ledger.md`，规定任务台账提取规则、字段映射、缺项留空标记、疑似重复识别（不合并）及 JSON 响应规范。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger_prompt.py`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/system_prompts/ adapter_service/tests/test_excel_material_ledger_prompt.py
git commit -m "feat(excel): add system prompt and schema for excel material ledger"
```

---

### Task 2: Excel 资料仓储与跨文档原子克隆 (`ExcelMaterialStore`)

**Files:**
- Create: `adapter_service/app/services/excel/material_store.py`
- Test: `adapter_service/tests/test_excel_material_import.py`

**Interfaces:**
- Produces:
  - `ExcelMaterialStore`:
    - `list_reusable_sources() -> List[dict]`
    - `clone_from_source(source_session_id: str, target_session_id: str, target_doc_identity: str) -> dict`
    - `import_material(...) -> dict`
    - `update_material(...) -> dict`
    - `delete_material(...) -> dict`
    - `get_catalog(session_id: str) -> dict`
    - `bind_document(...) -> dict`
- Invariants: 克隆后修改目标（update/delete）原来源文件与 manifest 100% 不受影响。

- [ ] **Step 1: 编写失败测试**

测试涵盖：
1. 资料直接上传与 5 份 / 10 万字容量门禁；
2. 列出全局可复用来源（发现 Word 与 Excel 已导入的资料）；
3. 跨文档克隆资料集形成独立副本；
4. 修改/删除 Excel 资料，原 Word 资料目录不受任何影响（物理隔离断言）；
5. 首次保存/另存为原子绑定 `bind_document`。

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_import.py`
预期：FAIL with "ModuleNotFoundError" 或 "ImportError"

- [ ] **Step 3: 编写 `ExcelMaterialStore` 最小实现**

在 `adapter_service/app/services/excel/material_store.py` 中实现：
- 独立的持久化目录 `$AI_WPS_STATE_DIR/excel_materials/`；
- `list_reusable_sources`：扫描 `word_materials` 与 `excel_materials`，提取合法 session 与清单信息；
- `clone_from_source`：在互斥锁保护下深度拷贝 source 目录所有 DOCX 原始文件及 JSON，重置目标 session/identity，确保完全物理隔离；
- `import_material`、`update_material`、`delete_material`：复用 `validate_docx_bytes` 与容量门禁算法，进行原子更新与物理清理；
- `bind_document`：支持文档另存为迁移。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_import.py`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/excel/material_store.py adapter_service/tests/test_excel_material_import.py
git commit -m "feat(excel): add ExcelMaterialStore with cross-document cloning and material management"
```

---

### Task 3: 台账生成引擎与长任务协调器 (`excel.material_ledger`)

**Files:**
- Create: `adapter_service/app/services/excel/material_ledger.py`
- Test: `adapter_service/tests/test_excel_material_ledger.py`

**Interfaces:**
- Produces:
  - `ExcelMaterialLedgerCoordinator`:
    - `submit_job(payload: dict) -> dict`
    - `query_job(job_id: str, document_session_id: str) -> dict`
    - `cancel_job(job_id: str, document_session_id: str) -> dict`
    - `detect_conflicts(document_session_id: str, user_facts: str) -> list`
- Validations:
  - 检查 `fragmentIds` 真实归属；
  - 强制留空缺项（空字符串）并计入 `missingFields`；
  - 重复项保留并标明 `isDuplicate: true, duplicateOfIndex, duplicateReason`，严禁合并；
  - 记录 `basisMaterials` 与 `generatedAt`。

- [ ] **Step 1: 编写失败测试**

测试涵盖：
1. 传入自定义表头（`["工作事项", "责任部门", "完成时间", "交付物验收"]`），模型输出台账并正确映射字段；
2. 缺失字段在 values 中留空并返回在 `missingFields` 数组中；
3. 疑似重复条目保留两行，标明 `isDuplicate: true` 及重复原因，不合并；
4. 虚假或失效 `fragmentIds` 被拦截报错；
5. 任务并发互斥（生成中拒绝修改资料）、任务取消与幂等重试。

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger.py`
预期：FAIL

- [ ] **Step 3: 编写 `ExcelMaterialLedgerCoordinator` 最小实现**

在 `adapter_service/app/services/excel/material_ledger.py` 中实现：
- 结合表头与用户要求提取相关资料片段；
- 构造提示词并调用 Provider 模型服务；
- 严格解析并校验模型 JSON，提取台账行、缺项、重复检测；
- 绑定出处原文，组装完整的结果信封；
- 挂载至 `LongTaskCoordinator`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger.py`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/excel/material_ledger.py adapter_service/tests/test_excel_material_ledger.py
git commit -m "feat(excel): add material ledger extraction engine and coordinator"
```

---

### Task 4: 双运行时 API 路由与接口对等 (FastAPI & Standalone)

**Files:**
- Modify: `adapter_service/app/api/excel.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_excel_material_ledger_api.py`

**Interfaces:**
- Endpoints:
  - `GET /materials/reusable-sources`
  - `POST /excel/materials/clone-from-source`
  - `POST /excel/materials/import`
  - `PUT /excel/materials/{material_id}`
  - `DELETE /excel/materials/{material_id}`
  - `GET /excel/materials/catalog`
  - `POST /excel/materials/bind-document`
  - `GET /excel/material-ledger/conflicts`
  - `POST /excel/material-ledger/jobs`
  - `GET /excel/material-ledger/jobs/{job_id}`
  - `POST /excel/material-ledger/jobs/{job_id}/cancel`

- [ ] **Step 1: 编写失败测试**

测试双运行时对等：
1. FastAPI 测试客户端调用上述全套接口；
2. Standalone Adapter 测试客户端调用上述全套接口；
3. 校验 64 KiB 门禁、409 并发冲突、状态轮询与取消。

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger_api.py`
预期：FAIL with 404 / route not found

- [ ] **Step 3: 编写路由与处理器**

在 `adapter_service/app/api/excel.py` 与 `adapter_service/standalone_adapter.py` 中注册上述路由，接入 `ExcelMaterialStore` 与 `ExcelMaterialLedgerCoordinator`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_material_ledger_api.py`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/api/excel.py adapter_service/standalone_adapter.py adapter_service/tests/test_excel_material_ledger_api.py
git commit -m "feat(excel): add dual-runtime API endpoints for excel material ledger"
```

---

### Task 5: Excel 插件功能区与任务窗格交互 (`formal-plugin-kit`)

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/material-ledger.js`
- Modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Create: `formal-plugin-kit/tests/excel-material-ledger.test.js`

**Interfaces:**
- Produces:
  - Ribbon: `btnAiExcelLedger` -> mode `excelLedger`
  - Helpers: `helpers.readSelectionHeaders(app)` 读取选区行
  - Module: `createMaterialLedgerController(options)`
  - UI: 表头标签增删与选区填充、资料导入/复用、长任务进度提示、只读表格渲染、缺项高亮、重复气泡、出处抽屉、TSV 复制
- Invariant: 单元格写操作计数为 0。

- [ ] **Step 1: 编写失败测试**

测试涵盖：
1. Ribbon 模式分发到 `excelLedger`；
2. 推荐表头呈现，用户添加/删除自定义表头，点击选区读取自动填充表头；
3. 资料列表展示、导入文件、拉取复用源并克隆；
4. 任务提交、进度阶段显示（中文“正在提取台账...”）、取消操作；
5. 结果表格渲染：
   - 验证表格结构；
   - 验证缺项单元格渲染 `〔缺项〕` 弱灰标记；
   - 验证疑似重复行渲染警示气泡并包含比对原因，行不被合并；
   - 验证点击出处展开侧栏原文；
   - 验证复制 TSV 功能生成正确的制表符分隔内容；
6. **只读保证断言**：跟踪测试期间 mock 的 WPS JSAPI，断言写入 API 调用次数严格为 0；
7. 文档切换与重开恢复。

- [ ] **Step 2: 运行测试验证失败**

运行：`node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
预期：FAIL

- [ ] **Step 3: 实现前端模块与界面组件**

- 在 `ribbon.xml` 与 `ribbon.js` 注册 `btnAiExcelLedger`；
- 在 `taskpane.html` 增设 `excel-ledger-options` 与专属结果表格容器；
- 在 `material-ledger.js` 中构建完备的台账控制器（状态机、网络交互、DOM 渲染、出处侧栏、复制处理）；
- 在 `taskpane-helpers.js` 中增加安全读取选区表头的辅助函数。

- [ ] **Step 4: 运行测试验证通过**

运行：`node --test formal-plugin-kit/tests/excel-material-ledger.test.js`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/
git commit -m "feat(excel): add ribbon button, taskpane UI and ledger controller for formal plugin"
```

---

### Task 6: 全量回归验证、静态扫描与交付交接更新

**Files:**
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: 运行全量后端测试**

```bash
PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_excel_*.py adapter_service/tests/test_word_material_*.py
```
预期：全部通过。

- [ ] **Step 2: 运行正式插件全量测试**

```bash
node --test formal-plugin-kit/tests/excel-*.test.js formal-plugin-kit/tests/word-material-*.test.js
```
预期：全部通过。

- [ ] **Step 3: 语法编译与格式扫描**

```bash
python3 -m compileall -q adapter_service/
git diff --check
```
预期：0 错误，0 警告。

- [ ] **Step 4: 更新交接文档并提交**

在 `docs/codex-handoff.md` 记录 Issue #236 的功能实现、独立资料集克隆机制、表头映射与缺项/重复防御规则以及验证结论。

```bash
git add docs/codex-handoff.md
git commit -m "docs: record completion of issue 236 in codex-handoff"
```
