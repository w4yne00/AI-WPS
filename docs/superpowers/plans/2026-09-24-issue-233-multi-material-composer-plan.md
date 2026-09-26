# Word：支持多份长资料编写章节实施计划 (Issue #233)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现从最多 5 份、合计十万字 DOCX 资料中分段梳理可读内容、建立会话资料目录并在后续章节复用、确定性提取相关原文片段、分阶段可取消生成草稿及多出处核对展示。

**Architecture:** 在 Adapter 建立基于 `documentSessionId` 的 `MaterialCatalog`，在内存中管理多文件大纲（TOC）与片段映射并执行 5 份与 10 万字硬门禁；当资料规模超出模型输入预算时，通过大纲结构与词法加权的确定性原文提取器筛选原文片段填满预算；通过 `LongTaskCoordinator` 推进 `preparing` → `extracting` → `provider_processing` → `parsing` 阶段，提供运行中即时取消与零写回防护；任务窗格展示多文件状态、折叠目录、跨章节复用与多文件来源侧栏。

**Tech Stack:** Python 3.8 / FastAPI / Pydantic / xml.etree.ElementTree, JavaScript ES5 / DOM / Node.js test runner, Vite / Vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-issue-233-multi-material-composer-design.md`

## Global Constraints

- Python 3.8 语法兼容（不得使用 `match/case`、内置泛型 `list[str]` 等 3.9+ 特性）。
- 单会话最多 5 份 DOCX，第 6 份拒绝返回 400 `MATERIAL_COUNT_OVER_LIMIT`。
- 多文件累计可读字符数上限为 100,000 字（统计口径 `unicode_codepoints_of_extracted_readable_text`），超限拒绝返回 413 `MATERIAL_TEXT_OVER_LIMIT`，绝对不静默截断。
- 累计展开单元格上限 100,000，单表最大列宽 256 列（`MATERIAL_TABLE_OVER_LIMIT`）。
- 生成依据必须是真实原文片段，严禁使用模型摘要伪造引文；正文必须保留真实的 `fragmentId` 引用，缺项约定为 `〔待补充：具体信息〕`。
- 取消与失败的任务严格不产生可写结果（`result = null`），前端严格禁用写回（`apply`）。
- FastAPI 与 Standalone 双适配器端点行为、错误码和返回信封完全对齐，POST 端点执行 64 KiB 上限。
- 保持既有单份资料 `materialId` 接口向后兼容。

## Review Focus

1. **第 6 份资料拒绝且不污染已有资料集**：导入 5 份合法文件后，第 6 份文件触发 `MATERIAL_COUNT_OVER_LIMIT`，已有 5 份文件的目录与字数统计保持完整无损。
2. **两份文件合计刚好超过 100,000 字**：第一份 60,000 字成功导入，第二份 40,001 字导入时被拒绝且整体目录回滚至第一份状态，无截断、无部分写入。
3. **超出模型 Token 预算时纯净原文入选**：十万字资料超预算时，提取器仅按章节与要求筛选真实片段，送入模型的每个片段均保留真实原文与唯一编号，无中间摘要。
4. **提取或模型调用中途取消不遗留残缺结果**：运行中取消立即关闭 socket，返回 `cancelled`，查询时 `result` 严格为 `null`，且调用 `applyText` 被硬性拦截。
5. **跨章节复用时不重复解析**：同一文档会话下，编写完成第一章后，第二章任务提交无需传递文件内容，直接根据 `documentSessionId` 命中已构建的目录。

---

### Task 1: 多资料限额、累加导入与会话目录（`material_import.py`）

**Files:**
- Modify: `adapter_service/app/services/word/material_import.py`
- Test: `adapter_service/tests/test_word_material_import.py`

**Interfaces:**
- Consumes: `validate_docx_bytes`, `DocxSecurityError`, `AdapterError`
- Produces:
  - `WordMaterialImportService.import_material(request: dict) -> dict`（支持单文件追加进会话目录，返回单文件详情与合并 `catalogSummary`）
  - `WordMaterialImportService.get_catalog(document_session_id: str) -> dict`
  - `WordMaterialImportService.get_session_catalog(document_session_id: str) -> dict`
  - Constants: `MATERIAL_IMPORT_MAX_DOCUMENTS = 5`, `MATERIAL_IMPORT_MAX_READABLE_CHARACTERS = 100000`

- [ ] **Step 1: 编写多文件限额、累加导入与目录聚合的失败测试**

在 `adapter_service/tests/test_word_material_import.py` 中添加测试：
```python
def test_multi_material_count_limit_rejected():
    service = WordMaterialImportService()
    session_id = "doc-test-count"
    valid_docx_b64 = _create_minimal_docx_b64("测试内容")
    for i in range(5):
        service.import_material({
            "fileName": f"doc_{i}.docx",
            "contentBase64": valid_docx_b64,
            "documentSessionId": session_id,
        })
    with pytest.raises(AdapterError) as exc_info:
        service.import_material({
            "fileName": "doc_6.docx",
            "contentBase64": valid_docx_b64,
            "documentSessionId": session_id,
        })
    assert exc_info.value.code == "MATERIAL_COUNT_OVER_LIMIT"
    assert exc_info.value.status_code == 400
    catalog = service.get_catalog(session_id)
    assert catalog["totalDocuments"] == 5

def test_multi_material_cumulative_text_limit_rejected():
    service = WordMaterialImportService()
    session_id = "doc-test-cumulative-text"
    text_60k = "中" * 60000
    text_45k = "华" * 45000
    b64_60k = _create_minimal_docx_b64(text_60k)
    b64_45k = _create_minimal_docx_b64(text_45k)
    service.import_material({
        "fileName": "part1.docx",
        "contentBase64": b64_60k,
        "documentSessionId": session_id,
    })
    with pytest.raises(AdapterError) as exc_info:
        service.import_material({
            "fileName": "part2.docx",
            "contentBase64": b64_45k,
            "documentSessionId": session_id,
        })
    assert exc_info.value.code == "MATERIAL_TEXT_OVER_LIMIT"
    assert exc_info.value.status_code == 413
    catalog = service.get_catalog(session_id)
    assert catalog["totalCharacters"] == 60000
    assert catalog["totalDocuments"] == 1

def test_multi_material_catalog_aggregation_and_toc():
    service = WordMaterialImportService()
    session_id = "doc-test-toc"
    docx_1 = _create_docx_with_headings_b64([("第一章 总则", "正文1")])
    docx_2 = _create_docx_with_headings_b64([("第二章 建设方案", "正文2")])
    res1 = service.import_material({
        "fileName": "file1.docx",
        "contentBase64": docx_1,
        "documentSessionId": session_id,
    })
    res2 = service.import_material({
        "fileName": "file2.docx",
        "contentBase64": docx_2,
        "documentSessionId": session_id,
    })
    catalog = service.get_catalog(session_id)
    assert catalog["totalDocuments"] == 2
    assert len(catalog["documents"]) == 2
    assert any(item["sectionTitle"] == "第一章 总则" for item in catalog["toc"])
    assert any(item["sectionTitle"] == "第二章 建设方案" for item in catalog["toc"])
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_import.py -k "multi_material"`
预期：FAIL（`MATERIAL_COUNT_OVER_LIMIT` 未定义，`get_catalog` 未实现）

- [ ] **Step 3: 实现 `material_import.py` 多文件与目录模型**

在 `adapter_service/app/services/word/material_import.py` 中：
- 定义常量 `MATERIAL_IMPORT_MAX_DOCUMENTS = 5`；
- 在 `WordMaterialImportService` 中维护 `self._session_catalogs: Dict[str, dict]`；
- 在 `import_material` 中检查会话文件数是否达到 5，检查新文件字数加上已有字数是否超过 100,000 字；
- 累计并更新会话目录，合并 `toc`，在返回值中暴露 `catalogSummary`；
- 实现 `get_catalog(document_session_id: str)` 与 `get_session_catalog(document_session_id: str)`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_import.py`
预期：PASS（所有单文件与多文件导入测试通过）

- [ ] **Step 5: 提交更改**

```bash
git add adapter_service/app/services/word/material_import.py adapter_service/tests/test_word_material_import.py
git commit -m "feat(word): support multi-material limit and session catalog aggregation (#233)"
```

---

### Task 2: 确定性原文提取算法与预算装箱（`material_composer.py`）

**Files:**
- Modify: `adapter_service/app/services/word/material_composer.py`
- Test: `adapter_service/tests/test_word_material_composer.py`

**Interfaces:**
- Consumes: `MaterialCatalog`, `direct_model_input_budget`, `_estimate_direct_tokens`
- Produces: `extract_relevant_fragments(catalog: dict, section_title: str, instruction: str, max_tokens: int) -> List[dict]`

- [ ] **Step 1: 编写确定性原文提取算法的失败测试**

在 `adapter_service/tests/test_word_material_composer.py` 中增加提取器专项测试：
```python
def test_extract_relevant_fragments_within_budget_returns_all():
    catalog = _build_mock_catalog_with_fragments([
        {"fragmentId": "f1", "text": "普通正文A", "blockId": "b1", "section": "第一章"},
        {"fragmentId": "f2", "text": "普通正文B", "blockId": "b2", "section": "第二章"},
    ])
    selected = extract_relevant_fragments(catalog, "第一章", "要求A", max_tokens=10000)
    assert len(selected) == 2
    assert [f["fragmentId"] for f in selected] == ["f1", "f2"]

def test_extract_relevant_fragments_over_budget_prioritizes_matching_heading_and_keywords():
    # 构造大量片段使其远超小 budget
    fragments = []
    for i in range(100):
        fragments.append({
            "fragmentId": f"f_norm_{i}",
            "text": f"不相关的正文段落文字内容序号{i} " * 10,
            "blockId": f"b_norm_{i}",
            "section": "无关章节"
        })
    fragments.append({
        "fragmentId": "f_target_1",
        "text": "本章节重点说明系统总体架构与业务子系统的划分原则。",
        "blockId": "b_target_1",
        "section": "第三章 总体架构设计"
    })
    fragments.append({
        "fragmentId": "f_target_2",
        "text": "系统总体架构包括数据中台、业务中台以及应用微服务集群。",
        "blockId": "b_target_2",
        "section": "第三章 总体架构设计"
    })
    catalog = _build_mock_catalog_with_fragments(fragments, toc=[
        {"sectionTitle": "无关章节", "startFragmentId": "f_norm_0", "endFragmentId": "f_norm_99"},
        {"sectionTitle": "第三章 总体架构设计", "startFragmentId": "f_target_1", "endFragmentId": "f_target_2"}
    ])
    # 限制预算只能容纳 2~3 个片段
    selected = extract_relevant_fragments(catalog, "总体架构", "列出总体架构与子系统", max_tokens=300)
    selected_ids = [f["fragmentId"] for f in selected]
    assert "f_target_1" in selected_ids
    assert "f_target_2" in selected_ids
    # 验证选出的片段为原始文本，且在结果中保持物理顺序
    assert all(isinstance(f["text"], str) and not f["text"].startswith("摘要：") for f in selected)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer.py -k "extract_relevant"`
预期：FAIL（`extract_relevant_fragments` 未定义）

- [ ] **Step 3: 实现 `extract_relevant_fragments` 算法**

在 `adapter_service/app/services/word/material_composer.py` 中：
- 实现分词/词频特征提取辅助函数；
- 计算标题匹配分（$W_{\text{toc}}$）与正文/表格词法相关性分；
- 计算上下文邻近继承分；
- 按得分排序后贪心选择片段直到达到 `max_tokens`（$0.85 \times \text{budget}$）；
- 将选出片段按原始在目录中的全局顺序重排；
- 确保输出项 100% 为原始片段对象。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer.py -k "extract_relevant"`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add adapter_service/app/services/word/material_composer.py adapter_service/tests/test_word_material_composer.py
git commit -m "feat(word): implement deterministic fragment extraction and budget packing (#233)"
```

---

### Task 3: 调度器分阶段执行、运行中取消与跨章节复用（`material_composer.py`）

**Files:**
- Modify: `adapter_service/app/services/word/material_composer.py`
- Test: `adapter_service/tests/test_word_material_composer.py`

**Interfaces:**
- Consumes: `MaterialComposerJobs`, `LongTaskCoordinator`, `SystemPromptStore`
- Produces:
  - `MaterialComposerJobs.start(payload: dict, trace_id: str) -> dict`（支持 `materialIds` 与会话目录直接复用）
  - 执行阶段：`preparing` → `extracting` → `provider_processing` → `parsing`
  - 终态防御：`cancelled` / `failed` 状态下 `result = None`

- [ ] **Step 1: 编写分阶段、运行中取消及跨章节复用的失败测试**

在 `adapter_service/tests/test_word_material_composer.py` 中：
```python
def test_material_composer_reuses_catalog_across_chapters():
    # 模拟在同一 session 下，先生成第一章，再生成第二章
    # 断言第二次请求直接利用同一 catalog 生成成功
    pass

def test_material_composer_reports_all_four_phases():
    # 跟踪 progress 回调，验证依次上报 preparing -> extracting -> provider_processing -> parsing
    pass

def test_material_composer_cancellation_during_extraction_and_provider():
    # 在 extracting 或 provider_processing 时调用 coordinator.request_cancel
    # 验证最终 job 状态为 cancelled，result 严格为 None
    pass

def test_material_composer_output_validation_rejects_hallucinated_sources():
    # 模拟模型返回了不存在于本次提取片段的 fragmentId
    # 断言抛出 MATERIAL_COMPOSER_INVALID_RESULT 并安全失败
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer.py -k "reuses_catalog or four_phases or cancellation"`
预期：FAIL

- [ ] **Step 3: 改造 `MaterialComposerJobs` 调度流程与出处校验**

在 `adapter_service/app/services/word/material_composer.py` 中：
- `start()` 支持根据 `documentSessionId` 直接获取会话目录，支持可选 `materialIds` 或向后兼容单 `materialId`；
- 在 `_run()` 中分步调用 `progress('preparing')`、`progress('extracting')`，调用 `extract_relevant_fragments` 形成输入集并计算 Token；
- `progress('provider_processing')` 调用模型，设置 cancel 监听；
- `progress('parsing')` 严格校验模型返回的 `fragmentIds` 属于提取集；
- 格式化输出带出处的正文与 `missingItems`。

- [ ] **Step 4: 运行测试验证通过**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add adapter_service/app/services/word/material_composer.py adapter_service/tests/test_word_material_composer.py
git commit -m "feat(word): add phased coordinator execution and catalog reuse (#233)"
```

---

### Task 4: FastAPI 与 Standalone 双适配器端点对齐（`word.py` & `standalone_adapter.py`）

**Files:**
- Modify: `adapter_service/app/api/word.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_word_material_composer.py`
- Test: `adapter_service/tests/test_word_material_import.py`

**Interfaces:**
- Produces:
  - `GET /word/materials/catalog?documentSessionId=...`
  - `POST /word/materials`（返回合并目录）
  - `POST /word/material-composer/jobs`（支持 `materialIds` 数组与 64 KiB 门禁）

- [ ] **Step 1: 编写双运行时端点请求与 64 KiB 门禁的失败测试**

```python
def test_fastapi_and_standalone_catalog_endpoint_parity():
    # 使用 TestClient 分别测试 /word/materials/catalog
    pass

def test_material_composer_request_body_size_limit():
    # 超过 64 KiB 请求体返回 413
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer.py -k "endpoint_parity"`
预期：FAIL（端点 404）

- [ ] **Step 3: 在 `word.py` 和 `standalone_adapter.py` 补充路由与校验**

- 注册 `GET /word/materials/catalog`；
- 更新 `POST /word/material-composer/jobs` 的解析逻辑；
- 在 `standalone_adapter.py` 相应位置对齐路径匹配与信封组装。

- [ ] **Step 4: 运行全量后端测试验证通过**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests/test_word_material_composer*.py adapter_service/tests/test_word_material_import*.py`
预期：PASS（所有相关接口测试通过）

- [ ] **Step 5: 提交更改**

```bash
git add adapter_service/app/api/word.py adapter_service/standalone_adapter.py adapter_service/tests/
git commit -m "feat(word): achieve dual-runtime API parity for material catalog and jobs (#233)"
```

---

### Task 5: 任务窗格多资料交互、跨章节复用与多出处呈现（前端）

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/material-import.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/material-composer.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/word-material-composer.test.js`
- Test: `formal-plugin-kit/tests/word-material-pane.test.js`

**Interfaces:**
- Consumes: `createMaterialComposer`, `renderMaterialComposer`, `submitMaterialImport`
- Produces:
  - 多资料状态维护（`materials: []`, `totalCharacters: 0`）
  - 目录展示与跨章节复用（`start()` 复用当前已导入目录）
  - 出处侧栏跨文件呈现（`fileName / section / fragmentId` + `quote`）
  - 运行中取消与写回禁用（`apply` 在未完成/失败/取消态抛错）

- [ ] **Step 1: 编写多文件交互、目录跨章节复用及写回防护的失败测试**

在 `formal-plugin-kit/tests/word-material-composer.test.js` 中增加：
```javascript
test('taskpane accumulates up to 5 materials and renders combined character count', async () => {
  // 验证添加多份资料后，状态展示 "已导入 N/5 份资料，合计 X/100,000 字"
});

test('chapter generation reuses existing catalog without re-uploading on subsequent section', async () => {
  // 验证在同一 documentSessionId 下，完成一次编写后，第二次调用 start() 能够直接以现有目录为基础发起
});

test('render displays multi-file source citations with accurate quotes', () => {
  // 验证不同段落引用不同源文件时的侧栏渲染
});

test('cancelled or failed task strictly rejects applyText and shows friendly error', async () => {
  // 验证取消或失败时，applyText 抛出明确异常，不允许写入 Word
});
```

- [ ] **Step 2: 运行插件测试验证失败**

运行：`cd .worktrees/issue-233-multi-material-composer && node --test formal-plugin-kit/tests/word-material-composer*.test.js`
预期：FAIL

- [ ] **Step 3: 改造前端 `material-composer.js`、`material-import.js` 和 `taskpane.js`**

- `material-import.js`：支持多文件选择，上报进度与汇总统计；
- `material-composer.js`：状态中存储当前会话目录大纲与多文件清单；`start()` 组装 `materialIds` 与会话标识；`renderMaterialComposer` 强化出处侧栏；
- `taskpane.js`：绑定多文件追加事件与目录折叠交互，严格门禁 `applyMaterialComposerResult`。

- [ ] **Step 4: 运行插件测试验证通过**

运行：`cd .worktrees/issue-233-multi-material-composer && PATH=/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH node --test formal-plugin-kit/tests/word-material*.test.js`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/ formal-plugin-kit/tests/
git commit -m "feat(word): support multi-material UI catalog reuse and source sidebars (#233)"
```

---

### Task 6: 真实十万字样例核对、实际耗时度量与全量门禁

**Files:**
- Create: `adapter_service/tests/test_word_material_benchmark.py`
- Modify: `docs/codex-handoff.md`
- Test: 全量后端与前端测试套件

**Interfaces:**
- Produces:
  - 预标注正文与表格事实的近十万字真实/拟真测试文档生成与出处核对
  - 首次梳理与后续章节生成的真实耗时度量输出（不造假阈值）
  - 完整 Python 3.8 兼容性与交付审计

- [ ] **Step 1: 编写多份长资料（接近十万字）事实与表格核对基准测试**

在 `adapter_service/tests/test_word_material_benchmark.py` 中：
- 构建 5 份总字数达 90,000+ 字的 DOCX 样例，其中包含预先标注的 5 处正文事实与 3 处表格数据；
- 运行流程，验证：
  1. 梳理耗时并真实记录；
  2. 提取器准确召回目标事实所在段落与表格行；
  3. 生成草稿完整保留出处并准确覆盖预标注事实；
  4. 记录后续章节生成的实际耗时；
- 受控模型与真实模型结果分别标记。

- [ ] **Step 2: 运行基准测试并记录真实耗时数据**

运行：`PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q -s adapter_service/tests/test_word_material_benchmark.py`
预期：PASS，并在标准输出打印真实首次梳理耗时与后续生成耗时。

- [ ] **Step 3: 运行全量后端、前端及构建检查**

```bash
# 1. 插件测试
PATH=/Users/waynesmini/Documents/AI-WPS/.venv/bin:$PATH node --test formal-plugin-kit/tests/*.test.js

# 2. 原型测试与构建
cd wps-addon && npm test && npm run build && cd ..

# 3. 后端本地全量测试
PYTHONPATH=adapter_service /Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m pytest -q adapter_service/tests

# 4. Python 3.8 语法兼容性扫描
/Users/waynesmini/Documents/AI-WPS/.venv/bin/python -m compileall adapter_service/

# 5. Git diff 检查
git diff --check
```

- [ ] **Step 4: 更新 handoff 文档与提交**

更新 `docs/codex-handoff.md`，记录 Issue #233 的实施成果、真实耗时与验证结论。
```bash
git add adapter_service/tests/ docs/codex-handoff.md
git commit -m "test(word): add 100k material facts benchmark and update handoff (#233)"
```
