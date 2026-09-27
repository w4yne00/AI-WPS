# Word：资料跨次复用、更新与移除实施计划 (Issue #235)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Word 资料集的本地持久化跨次复用、主动更新/替换与移除物理清理、未保存与另存为文档身份隔离与迁移、长任务运行中并发互斥（409）、草稿依据状态追踪（`updated` / `removed`）及写入安全熔断。

**Architecture:** 在 Adapter 状态目录（`AI_WPS_STATE_DIR/word_materials/<doc_identity>/`）建立独立持久化存储，保存 DOCX 副本、`manifest.json` 与 `catalog_cache.json`；提供 `PUT /word/materials/{id}` 与 `DELETE /word/materials/{id}` 及 `POST /word/materials/bind-document`；长任务协调器对运行中任务加持前置互斥门禁；前端草稿固化 `basisMaterials` 快照并动态判定依据有效性，依据变更时熔断禁用“写入选区/光标”，完全保留只读查看与“复制正文”。

**Tech Stack:** Python 3.8 / FastAPI / Pydantic / docx_security (Adapter), Vanilla JS / WPS JSAPI / Node.js test runner (Formal Plugin Kit), Docker (Python 3.8 test runner).

**Spec:** `docs/superpowers/specs/2026-09-27-issue-235-word-material-reuse-update-remove-design.md`

## Global Constraints

- 资料份数上限：单文档会话最多 5 份 DOCX，超限返回 HTTP 400 `MATERIAL_COUNT_OVER_LIMIT`；
- 累计文字上限：单文档会话累计最多 100,000 Unicode 可读字符，超限返回 HTTP 413 `MATERIAL_TEXT_OVER_LIMIT`；
- 展开表格单元格上限：累计最多 100,000 单元格，超限返回 HTTP 413 `MATERIAL_TABLE_OVER_LIMIT`；
- 请求体大小门禁：普通接口 64 KiB 上限；上传/更新 DOCX 接口最大支持 20 MiB 数据包（`DOCX_MAX_PACKAGE_BYTES`）；
- 存储物理隔离：资料持久化完全独立于通用输出历史（`TaskHistoryStore`），不向历史写入任何资料明文；
- 运行中并发互斥：生成任务在 `queued` 或 `running` 阶段时，更新/移除/导入请求返回 HTTP 409 `MATERIAL_COMPOSER_BUSY`；
- 依据失效熔断：草稿所引资料被更新或移除时，草稿标为 `updated` 或 `removed`，“写入选区/插入光标”按钮禁用，仅保留查看和复制；
- 双运行时对等：FastAPI 与 Standalone 对等提供所有新增及修改接口。

## Review Focus

1. **未保存文档另存为迁移覆盖**：用户在未保存文档中导入资料并生成草稿，随后保存到已有资料集的目标路径，系统返回 409 拒绝静默覆盖，保护原文档资料不被篡改；
2. **更新替换字数超限时的状态守恒**：当更新替换的文件导致总字数超过 100,000 字时，系统返回 413 并严格保留原有 DOCX 副本和目录结构，不产生破损或空目录；
3. **已生成草稿出处与已移除资料一致性**：资料被移除后，已生成草稿的出处标注保持原样展示（带失效警示条），但禁止任何写回操作，且后续生成章节无法再引用已移除资料；
4. **服务重启后片段编号与引用匹配**：重启 Adapter 或新服务实例恢复持久化目录后，片段 `fragmentId` 保持一致，后续生成的引用出处能正确索引到原文件名和章节；
5. **迟到的旧资料更新响应覆盖新导入**：前端窗格为更新请求引入单调序号，迟到的更新失败或成功响应不可覆盖后续发生的新导入或新文档状态。

---

### Task 1: 资料持久化存储仓储（`WordMaterialStore`）与跨次恢复

**Files:**
- Modify: `adapter_service/app/services/word/material_import.py:30-205`
- Test: `adapter_service/tests/test_word_material_import.py`

**Interfaces:**
- Consumes: `resolve_runtime_paths()` from `app.core.runtime_paths`, `validate_docx_bytes` from `app.services.ppt.docx_security`
- Produces: `WordMaterialStore` class with `save_material()`, `get_catalog()`, `load_material()`, `bind_document()`

- [ ] **Step 1: 编写持久化存储与跨次恢复的失败测试**

在 `adapter_service/tests/test_word_material_import.py` 中添加测试用例：
```python
def test_word_material_store_persists_and_restores_catalog_across_instances(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    session_id = "doc_session_persist_1"
    doc_bytes = _create_test_docx("第一章 概述\n项目总预算为500万元人民币。")
    b64 = base64.b64encode(doc_bytes).decode("ascii")

    # Instance 1
    service1 = WordMaterialImportService(state_dir=state_dir)
    res1 = service1.import_material({
        "fileName": "立项.docx",
        "contentBase64": b64,
        "documentSessionId": session_id,
        "documentIdentity": "full:/path/to/project.docx",
    })
    mat_id = res1["materialId"]
    assert res1["catalogSummary"]["totalDocuments"] == 1

    # Instance 2 pointing to same state_dir
    service2 = WordMaterialImportService(state_dir=state_dir)
    cat2 = service2.get_catalog(session_id)
    assert cat2["totalDocuments"] == 1
    assert cat2["documents"][0]["materialId"] == mat_id
    assert cat2["documents"][0]["fileName"] == "立项.docx"
    assert len(cat2["toc"]) >= 1
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_import.py -k test_word_material_store_persists_and_restores_catalog_across_instances"`
预期：FAIL（`WordMaterialImportService.__init__() got an unexpected keyword argument 'state_dir'`）

- [ ] **Step 3: 实现 `WordMaterialStore` 与持久化目录读写逻辑**

在 `adapter_service/app/services/word/material_import.py` 中：
1. 实现 `class WordMaterialStore`：
   - 构造参数 `base_dir: Optional[Path] = None`（默认为 `resolve_runtime_paths().state_dir / "word_materials"`）；
   - `_resolve_dir(doc_identity, session_id)` 计算目录路径；
   - `save_material(session_id, doc_identity, material_id, file_name, raw_docx_bytes, reading)`：保存 `files/{material_id}.docx`、更新 `manifest.json` 与 `catalog_cache.json`；
   - `get_catalog(session_id)`：优先读内存，无则从磁盘对应目录反序列化恢复；
   - `view_material(material_id)`：恢复对应资料详情；
2. 改造 `WordMaterialImportService`：
   - 接收可选 `state_dir: Optional[Path] = None` 并初始化 `self._store = WordMaterialStore(base_dir=state_dir)`；
   - `import_material` 成功后调用 `self._store.save_material`，确保 DOCX 副本与抽取元数据安全落盘。

- [ ] **Step 4: 运行测试以验证通过**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_import.py -k test_word_material_store_persists_and_restores_catalog_across_instances"`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/word/material_import.py adapter_service/tests/test_word_material_import.py
git commit -m "feat(word): implement persistent material storage across service instances"
```

---

### Task 2: 主动更新（`update_material`）与移除（`delete_material`）及配额重算

**Files:**
- Modify: `adapter_service/app/services/word/material_import.py`
- Test: `adapter_service/tests/test_word_material_import.py`

**Interfaces:**
- Consumes: `validate_docx_bytes` from `app.services.ppt.docx_security`, `WordMaterialStore`
- Produces: `WordMaterialImportService.update_material()`, `WordMaterialImportService.delete_material()`

- [ ] **Step 1: 编写更新与移除生命周期的失败测试**

在 `adapter_service/tests/test_word_material_import.py` 中添加用例：
```python
def test_word_material_update_and_remove_lifecycle(tmp_path):
    service = WordMaterialImportService(state_dir=tmp_path / "state")
    session_id = "doc_session_upd_1"
    doc1 = _create_test_docx("第一章\n原始文本内容一百字。")
    res1 = service.import_material({
        "fileName": "doc1.docx",
        "contentBase64": base64.b64encode(doc1).decode("ascii"),
        "documentSessionId": session_id
    })
    mid = res1["materialId"]
    orig_chars = res1["catalogSummary"]["totalCharacters"]

    # 1. Update with new docx
    doc2 = _create_test_docx("第一章\n更新后的文本内容两百字，包含新增细节。")
    upd_res = service.update_material(mid, {
        "fileName": "doc1_v2.docx",
        "contentBase64": base64.b64encode(doc2).decode("ascii"),
        "documentSessionId": session_id
    })
    assert upd_res["materialId"] == mid
    assert upd_res["fileName"] == "doc1_v2.docx"
    assert upd_res["catalogSummary"]["totalDocuments"] == 1
    assert upd_res["catalogSummary"]["totalCharacters"] > orig_chars
    assert "updatedAt" in upd_res

    # 2. Delete material
    del_res = service.delete_material(mid, document_session_id=session_id)
    assert del_res["totalDocuments"] == 0
    assert del_res["totalCharacters"] == 0

    # 3. Check 404 after delete
    with pytest.raises(AdapterError) as exc_info:
        service.view_material(mid)
    assert exc_info.value.code == "MATERIAL_NOT_FOUND"
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_import.py -k test_word_material_update_and_remove_lifecycle"`
预期：FAIL（`AttributeError: 'WordMaterialImportService' object has no attribute 'update_material'`）

- [ ] **Step 3: 实现 `update_material` 与 `delete_material` 方法**

在 `adapter_service/app/services/word/material_import.py` 中：
1. `update_material(material_id: str, request: dict) -> dict`：
   - 提取 `documentSessionId`，校验资料是否存在；
   - 校验新 DOCX 安全与解包；
   - 动态计算新字数与新表格单元格数，检查 `total - old + new` 是否超出 100,000 字与 100,000 单元格上限；若超限抛出对应 `AdapterError`（413），原文件不变；
   - 覆写磁盘副本 `files/{material_id}.docx`；
   - 重新抽取 blocks 与 fragments，保留原 `materialId`，更新 `updatedAt` 时间戳；
   - 原子刷新 `manifest.json` 与 `catalog_cache.json`，返回更新后的资料视图与目录摘要；
2. `delete_material(material_id: str, document_session_id: str) -> dict`：
   - 校验资料归属；若不存在抛出 404 `MATERIAL_NOT_FOUND`；
   - 物理删除 `files/{material_id}.docx`；
   - 在 `manifest.json` 和 `catalog_cache.json` 中物理剔除属于 `material_id` 的所有条目，扣减字数和单元格统计；
   - 返回清理后的 `catalogSummary`。

- [ ] **Step 4: 运行测试以验证通过**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_import.py -k test_word_material_update_and_remove_lifecycle"`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/word/material_import.py adapter_service/tests/test_word_material_import.py
git commit -m "feat(word): implement material update, delete, and capacity recalculation"
```

---

### Task 3: 运行中并发互斥门禁（409 `MATERIAL_COMPOSER_BUSY`）与草稿依据快照

**Files:**
- Modify: `adapter_service/app/services/word/material_composer.py`
- Modify: `adapter_service/app/services/word/material_import.py`
- Test: `adapter_service/tests/test_word_material_composer.py`

**Interfaces:**
- Consumes: `LongTaskCoordinator` active job query
- Produces: 409 `MATERIAL_COMPOSER_BUSY` on mutation while job is running, `basisMaterials` on completed result

- [ ] **Step 1: 编写运行中互斥门禁与草稿依据快照的失败测试**

在 `adapter_service/tests/test_word_material_composer.py` 中添加用例：
```python
def test_material_composer_concurrency_mutex_and_basis_snapshot(tmp_path):
    # Verify that attempting to import, update or delete materials while a job is running returns 409
    ...
    # Verify that completed job result includes basisMaterials array with materialId and updatedAt
    ...
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_composer.py -k test_material_composer_concurrency_mutex_and_basis_snapshot"`
预期：FAIL

- [ ] **Step 3: 在 `material_import.py` 与 `material_composer.py` 植入互斥门禁与依据快照**

1. 在 `WordMaterialImportService` 中注入 `coordinator` 检查逻辑，或者在 `import_material`、`update_material`、`delete_material` 前置检查当前 `documentSessionId` 是否有活跃的 `word.material_composer` 任务；若有，抛出 `AdapterError("MATERIAL_COMPOSER_BUSY", "章节草稿正在生成中，请等待完成或取消任务后再更新/移除资料。", status_code=409)`；
2. 在 `MaterialComposerJobs.start()` 与 `_run()` 中：
   - 提取当前快照目录中各资料的 `{ "materialId": mid, "fileName": name, "updatedAt": ts }`；
   - 在任务终态交付的 `result` 字典中添加 `basisMaterials` 列表与 `generatedAt` ISO 时间戳。

- [ ] **Step 4: 运行测试以验证通过**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_composer.py -k test_material_composer_concurrency_mutex_and_basis_snapshot"`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/word/material_composer.py adapter_service/app/services/word/material_import.py adapter_service/tests/test_word_material_composer.py
git commit -m "feat(word): guard material mutations with 409 busy check and record basis snapshot"
```

---

### Task 4: 双运行时接口对等实现（`PUT`、`DELETE`、`bind-document`）

**Files:**
- Modify: `adapter_service/app/api/word.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_word_material_composer.py`

**Interfaces:**
- Produces: HTTP endpoints for FastAPI & Standalone:
  - `PUT /word/materials/{material_id}`
  - `DELETE /word/materials/{material_id}`
  - `POST /word/materials/bind-document`

- [ ] **Step 1: 编写双运行时 HTTP 路由对等测试**

在 `adapter_service/tests/test_word_material_composer.py` 中添加端点测试：
```python
def test_word_material_api_endpoint_parity_for_update_delete_and_bind(client):
    # Test PUT /word/materials/{material_id}
    # Test DELETE /word/materials/{material_id}
    # Test POST /word/materials/bind-document
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_composer.py -k test_word_material_api_endpoint_parity"`
预期：FAIL（404 or 405 Method Not Allowed）

- [ ] **Step 3: 在 `word.py` 与 `standalone_adapter.py` 增补路由与参数校验**

1. 在 `adapter_service/app/api/word.py` 中：
   - 增加 `@router.put("/word/materials/{material_id}")`
   - 增加 `@router.delete("/word/materials/{material_id}")`
   - 增加 `@router.post("/word/materials/bind-document")`
2. 在 `adapter_service/standalone_adapter.py` 中：
   - 在 `do_PUT` 分支增加 `/word/materials/<material_id>` 解析与调用；
   - 在 `do_DELETE` 分支增加 `/word/materials/<material_id>` 解析与调用；
   - 在 `do_POST` 分支增加 `/word/materials/bind-document` 解析与调用；
   - 统一 64 KiB 请求体校验（非二进制上传字段）与统一错误信封输出。

- [ ] **Step 4: 运行测试以验证通过**

运行：
`docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_word_material_composer.py -k test_word_material_api_endpoint_parity"`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/api/word.py adapter_service/standalone_adapter.py adapter_service/tests/test_word_material_composer.py
git commit -m "feat(word): implement update, delete, and bind endpoints in fastapi and standalone adapter"
```

---

### Task 5: 前端任务窗格依据状态判定、写入熔断与目录交互

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/material-composer.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Test: `formal-plugin-kit/tests/word-material-composer.test.js`
- Test: `formal-plugin-kit/tests/word-material-pane.test.js`

**Interfaces:**
- Produces: `evaluateBasisStatus()`, warning badge rendering in `renderMaterialComposer()`, `apply` fuse in `material-composer.js`, "更新"/"移除" buttons in catalog view.

- [ ] **Step 1: 编写依据状态追踪、写入熔断及目录操作的前端测试**

在 `formal-plugin-kit/tests/word-material-composer.test.js` 中添加用例：
```javascript
test('evaluates basis status as updated when referenced material has newer updatedAt', () => {
  // Setup composer with completed result having basisMaterials
  // Update catalog material with newer updatedAt
  // Assert basisStatus is 'updated'
  // Assert render displays '⚠️ 参考资料已更新，当前草稿依据已变更'
  // Assert applyText throws error and apply button is disabled
  // Assert copy button is still enabled
});

test('evaluates basis status as removed when referenced material is deleted from catalog', () => {
  // Remove referenced material from catalog
  // Assert basisStatus is 'removed'
  // Assert render displays '⚠️ 所引参考资料已被移除，当前草稿依据已失效'
  // Assert applyText throws error and apply button is disabled
});
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`node --test formal-plugin-kit/tests/word-material-composer.test.js`
预期：FAIL（asserts fail on basisStatus / badge rendering）

- [ ] **Step 3: 实现前端依据状态判定、写入熔断与目录交互**

1. 在 `material-composer.js` 中：
   - 增加 `evaluateBasisStatus(s)`：
     - 若无 `s.result` 或无 `s.result.basisMaterials`，返回 `'current'`；
     - 检查 `s.result.basisMaterials` 中是否存在未在当前 `s.catalogSummary.documents` 中的资料；若是，返回 `'removed'`；
     - 检查是否存在当前 `doc.updatedAt > basis.updatedAt`；若是，返回 `'updated'`；
     - 否则返回 `'current'`；
   - 在 `renderMaterialComposer()` 中：
     - 在结果顶部如果 `basisStatus === 'updated'` 或 `'removed'`，插入警示条 `<div class="material-composer-basis-warning">...</div>`；
     - 在资料目录每项增加 `[更新]` 与 `[移除]` 按钮，绑定回调 `onUpdateMaterial(materialId)` 与 `onDeleteMaterial(materialId)`；
     - 在 `view.busy || active(view)` 期间将更新与移除按钮置灰禁用；
   - 在 `apply()` 方法中：
     - 如果 `evaluateBasisStatus(s) !== 'current'`，抛出错误并暂停写入，提示重新生成；
2. 在 `taskpane.js` 中：
   - 增加 `handleMaterialUpdate(materialId, file)` 与 `handleMaterialDelete(materialId)`；
   - `renderMaterialComposerView` 适配 `btn-material-apply` 在依据异常时的禁用逻辑；
   - 保持 `btn-material-copy` 始终可用。

- [ ] **Step 4: 运行测试以验证通过**

运行：
`node --test formal-plugin-kit/tests/word-material-composer.test.js`
`node --test formal-plugin-kit/tests/word-material-pane.test.js`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/material-composer.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/tests/word-material-composer.test.js formal-plugin-kit/tests/word-material-pane.test.js
git commit -m "feat(word): implement draft basis status tracking, apply fuse, and catalog update/remove UI"
```

---

### Task 6: 多文档隔离、另存为迁移与端到端回归闭环

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/word-material-composer.test.js`
- Test: `adapter_service/tests/test_word_material_composer.py`

**Interfaces:**
- Produces: Document switch & Save-As identity transition handling in plugin, end-to-end integration tests.

- [ ] **Step 1: 编写多文档隔离与另存为迁移的端到端测试**

在 `formal-plugin-kit/tests/word-material-composer.test.js` 中添加多文档隔离与另存为迁移测试：
```javascript
test('switching documents isolates material catalog and prevents cross-document pollution', () => { ... });
test('save-as migration transitions unsaved material session to saved document identity safely', () => { ... });
```

- [ ] **Step 2: 运行测试以验证失败**

运行：
`node --test formal-plugin-kit/tests/word-material-composer.test.js`
预期：FAIL

- [ ] **Step 3: 完善前端多文档切换与另存为迁移逻辑**

1. 在 `taskpane.js` 中检测文档保存事件或路径变更，调用 `bind-document` 接口完成迁移；
2. 切换活动文档时，确保 `syncMaterialComposerSession()` 彻底隔离各文档状态。

- [ ] **Step 4: 运行全量后端、前端及构建检查**

```bash
# 1. 前端测试
node --test formal-plugin-kit/tests/word-material-*.test.js

# 2. 原型构建与测试
cd wps-addon && npm test && npm run build && cd ..

# 3. 后端全量测试 (Docker Python 3.8)
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests"

# 4. Python 3.8 兼容性语法扫描
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest python -m compileall adapter_service/

# 5. 代码格式检查
git diff --check
```
预期：全部 PASS，0 失败，0 告警。

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/ adapter_service/
git commit -m "feat(word): complete multi-document isolation, save-as migration and end-to-end verification (Issue #235)"
```
