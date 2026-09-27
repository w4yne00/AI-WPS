# PPT：用固定模板生成并追加一张正文页实施计划 (Issue #239)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 取得一套实际使用的固定模板，根据已确认大纲选一页生成标题、要点和讲稿，预览确认后追加一张可编辑正文页，验证目标 WPS 模板写入可行性与逆向补偿回滚。

**Architecture:** 
- 后端注册 `ppt.template_page` 任务与提示词，基于 `PptMaterialStore` 关联召回出处，由 `PptTemplatePageCoordinator` 调度并提供双运行时接口；
- 前端控制器 `template-body-page.js` 依赖逐页大纲确认门禁（`hasConfirmedOutline()`），选择单页生成结构化正文与讲稿，实施严苛的排版容纳量防御（Fail-Closed，不截断、不缩字号）；
- 通过 WPS JSAPI 定位固定模板 `slideLayout3.xml`（"标题和内容"）版式，在演示文稿末尾新增页面并分别填充标题、要点项目符号与演讲备注，发生异常时执行 `slide.Delete()` 逆向回滚，重试防重。

**Tech Stack:** Python 3.8, FastAPI, Pydantic, Node.js (Node:test), WPS JSAPI / COM, Vanilla JavaScript (ES5 for plugin runtime).

**Spec:** [docs/superpowers/specs/2026-09-27-issue-239-ppt-template-body-page-design.md](file:///Users/wayne/Documents/New%20project/AI-WPS/.worktrees/issue-239-ppt-template-body-page/docs/superpowers/specs/2026-09-27-issue-239-ppt-template-body-page-design.md)

## Global Constraints

- Python 3.8 兼容性，不得使用 3.9+ 特性；
- 插件端运行环境兼顾 ES5 严格模式，避免高级现代语法导致宿主 JS 引擎报错；
- 请求体最大限制 64 KiB；
- 严禁修改 `wps-addon` 旧原型；
- 不破坏现有 PPT 智能总结、结构审查与逐页大纲生成的任何既有功能与测试；
- 严格保持现有演示文稿前 N 张幻灯片 100% 不变，新页只能追加在文稿末尾；
- 内容超容时严格阻止写入，绝不静默截断文字，绝不无限缩小字号；
- 发生部分写入异常时严格逆向补偿（删除新增页），绝不遗留残缺半成品页面。

## Review Focus

1. **大纲未确认或资料已变更时尝试生成正文页**：必须严格拦截，提示“请先确认逐页大纲”；
2. **正文要点超出模板文本框容纳上限（>260 字或 >8 行）**：必须阻止写入并抛出 `OVERFLOW_PREVENTED`，绝不静默截断或缩小字号；
3. **活动演示文稿在生成后被切换或重命名**：必须拦截写入并提示 `SESSION_MISMATCH`，防止将新页错写进其他演示文稿；
4. **同一正文页成功写入后重复点击写入**：必须拦截并提示 `ALREADY_WRITTEN`，保证幂等性；
5. **在创建幻灯片后填充正文或备注中途抛出异常**：必须触发逆向回滚删除刚刚新增的页面（`slide.Delete()`），总页数恢复原样，并报告 `COMPENSATION_SUCCEEDED`。

---

### Task 1: 注册 `ppt.template_page` 任务类型、提示词与模型契约

**Files:**
- Create: `adapter_service/system_prompts/ppt-template-page.md`
- Modify: `adapter_service/system_prompts/manifest.json`
- Modify: `adapter_service/app/services/workflow_profiles.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Test: `adapter_service/tests/test_ppt_template_page_prompt.py`

**Interfaces:**
- Consumes: `adapter_service/system_prompts/` 提示词装载机制
- Produces: 任务标识 `ppt.template_page`，模型返回包含 `title`、`keyPoints` (数组)、`speakerNotes`、`fragmentIds`、`missingItems` 的 JSON 格式规范。

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_template_page_prompt.py
from pathlib import Path
import json

def test_ppt_template_page_prompt_manifest_and_file():
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "system_prompts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "ppt.template_page" in manifest
    
    prompt_file = root / "system_prompts" / manifest["ppt.template_page"]
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "keyPoints" in content
    assert "speakerNotes" in content
    assert "fragmentIds" in content
    assert "missingItems" in content
    assert "260" in content or "字数" in content
```

- [ ] **Step 2: 运行测试验证失败**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page_prompt.py"
```
Expected: FAIL with `AssertionError: assert 'ppt.template_page' in manifest`

- [ ] **Step 3: 编写提示词与配置注册**

1. 创建 `adapter_service/system_prompts/ppt-template-page.md`：
规范角色为专业演示文稿内容策划与演讲助手，接收大纲单页信息与资料片段，输出包含 `title` (精炼标题，不超过20字)、`keyPoints` (3~4个展开论点，每个包含核心论点与简短阐述，总字数不超过240字)、`speakerNotes` (演讲讲稿，口语化，150~300字)、`fragmentIds`、`missingItems` 的 JSON。
2. 更新 `manifest.json`：`"ppt.template_page": "ppt-template-page.md"`
3. 更新 `workflow_profiles.py` 与 `provider_client.py` 注册 `ppt.template_page` 任务类型。

- [ ] **Step 4: 运行测试验证通过**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page_prompt.py"
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/system_prompts/ adapter_service/app/services/ adapter_service/tests/test_ppt_template_page_prompt.py
git commit -m "feat(ppt): register ppt.template_page prompt and task type"
```

---

### Task 2: 实现 `PptTemplatePageCoordinator` 长任务协调器

**Files:**
- Create: `adapter_service/app/services/ppt/template_page.py`
- Test: `adapter_service/tests/test_ppt_template_page.py`

**Interfaces:**
- Consumes: `PptMaterialStore.get_catalog()`, `PptMaterialStore.get_relevant_fragments()`
- Produces: `PptTemplatePageCoordinator` 类，包含 `submit_job()`, `get_job()`, `cancel_job()`, 结果携带 `schemaVersion: "ppt.template_page.v1"`, `estimatedLines`, `totalCharacters`, `sources`, `basisMaterials`。

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_template_page.py
import pytest
from app.services.ppt.template_page import PptTemplatePageCoordinator, evaluate_template_page_capacity
from app.services.ppt.material_store import PptMaterialStore

def test_evaluate_template_page_capacity():
    points = ["要点一：简明扼要", "要点二：论据充分", "要点三：符合规范"]
    res = evaluate_template_page_capacity(points)
    assert res["is_overflow"] is False
    assert res["total_characters"] > 0
    assert res["estimated_lines"] <= 8

    # Overflow test
    long_points = ["非常非常长的文本" * 20] * 5
    res_overflow = evaluate_template_page_capacity(long_points)
    assert res_overflow["is_overflow"] is True

def test_ppt_template_page_coordinator_lifecycle(tmp_path):
    store = PptMaterialStore(tmp_path)
    coord = PptTemplatePageCoordinator(material_store=store)
    
    req = {
        "documentSessionId": "sess_1",
        "clientJobId": "cjob_1",
        "pageIndex": 3,
        "pageRole": "content",
        "outlineTitle": "总体架构设计",
        "outlineKeyPoints": ["分层解耦", "安全可控"],
        "outlineFragmentIds": [],
        "instruction": "注重合规",
        "userFacts": "",
        "maxKeyPoints": 4
    }
    job = coord.submit_job(req)
    assert job["jobId"]
    assert job["status"] in ("queued", "running", "completed")
```

- [ ] **Step 2: 运行测试验证失败**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page.py"
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ppt.template_page'`

- [ ] **Step 3: 实现 `PptTemplatePageCoordinator`**

在 `adapter_service/app/services/ppt/template_page.py` 中实现：
1. `evaluate_template_page_capacity(key_points)`：
   - 计算字数：`total_chars = sum(len(p) for p in key_points)`
   - 估算行数：`estimated_lines = sum(max(1, (len(p) + 35) // 36) for p in key_points)`
   - `is_overflow = len(key_points) > 4 or total_chars > 260 or estimated_lines > 8`
2. `PptTemplatePageCoordinator`：
   - 维护线程安全 `_jobs` 与 `_active_sessions` 互斥；
   - 提取资料出处片段并校验片段真实性；
   - 模拟/调用 Provider 并解析返回的 JSON 对象；
   - 组装带 `schemaVersion: "ppt.template_page.v1"`, `estimatedLines`, `totalCharacters`, `sources`, `basisMaterials` 的规范响应；
   - 支持同一 `clientJobId` 请求幂等返回；
   - 支持取消与毫秒级单调耗时指标采集。

- [ ] **Step 4: 运行测试验证通过**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page.py"
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/services/ppt/template_page.py adapter_service/tests/test_ppt_template_page.py
git commit -m "feat(ppt): add PptTemplatePageCoordinator for template body page generation"
```

---

### Task 3: 双运行时 API 端点实现 (FastAPI & Standalone)

**Files:**
- Modify: `adapter_service/app/api/ppt.py`
- Modify: `adapter_service/standalone_adapter.py`
- Test: `adapter_service/tests/test_ppt_template_page_api.py`

**Interfaces:**
- Consumes: `PptTemplatePageCoordinator`
- Produces: 
  - `POST /ppt/template-page/jobs`
  - `GET /ppt/template-page/jobs/{job_id}`
  - `POST /ppt/template-page/jobs/{job_id}/cancel`

- [ ] **Step 1: 编写失败测试**

```python
# adapter_service/tests/test_ppt_template_page_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_fastapi_ppt_template_page_endpoints():
    client = TestClient(app)
    req = {
        "documentSessionId": "sess_test",
        "clientJobId": "cjob_api_1",
        "pageIndex": 2,
        "pageRole": "content",
        "outlineTitle": "核心业务流程",
        "outlineKeyPoints": ["流程自动化", "审计可溯"],
        "outlineFragmentIds": []
    }
    resp = client.post("/ppt/template-page/jobs", json=req)
    assert resp.status_code == 200
    data = resp.json()
    assert "jobId" in data
    job_id = data["jobId"]
    
    # Query job
    resp_get = client.get(f"/ppt/template-page/jobs/{job_id}?documentSessionId=sess_test")
    assert resp_get.status_code == 200
    assert resp_get.json()["jobId"] == job_id

    # Cancel job
    resp_cancel = client.post(f"/ppt/template-page/jobs/{job_id}/cancel", json={"documentSessionId": "sess_test"})
    assert resp_cancel.status_code == 200
```

- [ ] **Step 2: 运行测试验证失败**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page_api.py"
```
Expected: FAIL with 404 Not Found on `/ppt/template-page/jobs`

- [ ] **Step 3: 在 FastAPI 与 Standalone 实现路由**

1. 在 `adapter_service/app/api/ppt.py` 中引入协调器单例，添加上述 3 个路由，设置 64 KiB 上限；
2. 在 `adapter_service/standalone_adapter.py` 中以纯 Python 标准库 HTTP 服务器实现对等路由，保证无依赖单文件适配器可用。

- [ ] **Step 4: 运行测试验证通过**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests/test_ppt_template_page_api.py"
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add adapter_service/app/api/ppt.py adapter_service/standalone_adapter.py adapter_service/tests/test_ppt_template_page_api.py
git commit -m "feat(ppt): add dual-runtime API routes for ppt template page jobs"
```

---

### Task 4: 前端控制器与排版容纳量防御 (`template-body-page.js`)

**Files:**
- Create: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/template-body-page.js`
- Test: `formal-plugin-kit/tests/ppt-template-body-page.test.js`

**Interfaces:**
- Consumes: `materialOutline.hasConfirmedOutline()`, `materialOutline.getConfirmedOutline()`
- Produces: `createTemplateBodyPageController(options)`，包含 `selectPage()`, `submit()`, `poll()`, `cancel()`, `evaluateCapacity()`, `formatMarkdown()`, `copyResult()`。

- [ ] **Step 1: 编写失败测试**

```javascript
// formal-plugin-kit/tests/ppt-template-body-page.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { createTemplateBodyPageController, evaluateSlideTextCapacity } = require("../wps-ai-assistant-wpp_1.0.0/template-body-page.js");

test("evaluateSlideTextCapacity: accepts normal points and rejects overflow", () => {
  const normalPoints = [
    "分层解耦：采用业务域服务化解耦架构，支撑各模块独立演进与灰度发布",
    "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范"
  ];
  const normalCap = evaluateSlideTextCapacity(normalPoints);
  assert.equal(normalCap.isOverflow, false);
  assert.ok(normalCap.estimatedLines <= 8);

  const overflowPoints = [
    "长文本内容".repeat(30),
    "第二条超长文本内容".repeat(30)
  ];
  const overCap = evaluateSlideTextCapacity(overflowPoints);
  assert.equal(overCap.isOverflow, true);
  assert.ok(overCap.totalCharacters > 260);
});

test("createTemplateBodyPageController requires confirmed outline gate", () => {
  let outlineConfirmed = false;
  const mockOutline = {
    hasConfirmedOutline: () => outlineConfirmed,
    getConfirmedOutline: () => ({ slides: [{ pageIndex: 1, title: "封面", pageRole: "cover" }, { pageIndex: 2, title: "正文", pageRole: "content", keyPoints: ["要点A"] }] })
  };
  const ctrl = createTemplateBodyPageController({
    getMaterialOutline: () => mockOutline,
    request: async () => ({ jobId: "job_1" })
  });

  assert.equal(ctrl.canGenerate(), false);
  assert.equal(ctrl.getAvailablePages().length, 0);

  outlineConfirmed = true;
  assert.equal(ctrl.canGenerate(), true);
  assert.equal(ctrl.getAvailablePages().length, 2);
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: FAIL with `Cannot find module '../wps-ai-assistant-wpp_1.0.0/template-body-page.js'`

- [ ] **Step 3: 实现 `template-body-page.js` 前端控制器核心逻辑**

在 `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/template-body-page.js` 中实现：
1. 模块导出（UMD 包装，兼容 CommonJS 与浏览器全局对象）；
2. `evaluateSlideTextCapacity(keyPoints)` 严密计算：字数上限 260 字，折行上限 8 行，要点数上限 4 条；
3. `createTemplateBodyPageController`：
   - 检查 `getMaterialOutline().hasConfirmedOutline()` 门禁；
   - 提取可选页面（标记角色与标题）；
   - 管理当前选中页状态与编辑参数；
   - 提交后台任务、轮询阶段、取消与持久化缓存；
   - 只读预览渲染与 Markdown 纯文本导出。

- [ ] **Step 4: 运行测试验证通过**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/template-body-page.js formal-plugin-kit/tests/ppt-template-body-page.test.js
git commit -m "feat(ppt): add template body page controller with capacity overflow defense"
```

---

### Task 5: WPS 幻灯片追加写入、占位符定位与逆向补偿回滚

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/template-body-page.js`
- Test: `formal-plugin-kit/tests/ppt-template-body-page.test.js`

**Interfaces:**
- Consumes: WPS JSAPI / COM `wps.WppApplication().ActivePresentation`
- Produces: `appendTemplateBodySlide(targetDocSession, pageData, options)`
- Error Codes: `SESSION_MISMATCH`, `ALREADY_WRITTEN`, `OVERFLOW_PREVENTED`, `LAYOUT_NOT_FOUND`, `COMPENSATION_SUCCEEDED`, `COMPENSATION_FAILED`

- [ ] **Step 1: 编写失败测试**

```javascript
// formal-plugin-kit/tests/ppt-template-body-page.test.js (新增写入与回滚测试用例)
test("appendTemplateBodySlide appends at end and fills title, body, notes", async () => {
  // Mock WPS presentation with 6 slides
  const slides = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }, { id: 6 }];
  const mockCustomLayout = { name: "标题和内容" };
  const mockPres = {
    Slides: {
      get Count() { return slides.length; },
      AddSlide(index, layout) {
        assert.equal(index, 7); // appended at end
        assert.equal(layout.name, "标题和内容");
        const newSlide = {
          id: 7,
          Shapes: [
            { Name: "标题 1", Type: "ppPlaceholderTitle", TextFrame: { TextRange: { Text: "" } } },
            { Name: "内容占位符 2", Type: "ppPlaceholderBody", TextFrame: { TextRange: { Text: "", Paragraphs: [] } } }
          ],
          NotesPage: {
            Shapes: [
              { Name: "备注占位符 4", Type: "ppPlaceholderBody", TextFrame: { TextRange: { Text: "" } } }
            ]
          },
          Delete() {
            const idx = slides.indexOf(newSlide);
            if (idx >= 0) slides.splice(idx, 1);
          }
        };
        slides.push(newSlide);
        return newSlide;
      }
    },
    CustomLayouts: {
      Item(key) {
        if (key === "标题和内容" || key === 3) return mockCustomLayout;
        return null;
      }
    }
  };

  const pageData = {
    title: "新架构正文页",
    keyPoints: ["要点一：高内聚", "要点二：低耦合"],
    speakerNotes: "各位领导好，本页阐述..."
  };

  const result = await appendTemplateBodySlide("sess_test", pageData, {
    getActivePresentation: () => mockPres,
    getSessionId: () => "sess_test"
  });

  assert.equal(result.success, true);
  assert.equal(slides.length, 7);
  assert.equal(slides[6].Shapes[0].TextFrame.TextRange.Text, "新架构正文页");
  assert.equal(slides[6].NotesPage.Shapes[0].TextFrame.TextRange.Text, "各位领导好，本页阐述...");
  assert.equal(pageData.writtenSlideIndex, 7);
});

test("appendTemplateBodySlide rolls back and deletes slide if write fails midway", async () => {
  const slides = [{ id: 1 }, { id: 2 }];
  let deleted = false;
  const mockPres = {
    Slides: {
      get Count() { return slides.length; },
      AddSlide(index, layout) {
        const newSlide = {
          id: 3,
          Shapes: [
            { Name: "标题 1", Type: "ppPlaceholderTitle", get TextFrame() { throw new Error("COM Fault on TextFrame"); } }
          ],
          Delete() {
            deleted = true;
            slides.pop();
          }
        };
        slides.push(newSlide);
        return newSlide;
      }
    },
    CustomLayouts: { Item: () => ({ name: "标题和内容" }) }
  };

  const pageData = { title: "失败测试", keyPoints: ["要点"], speakerNotes: "" };
  await assert.rejects(
    async () => {
      await appendTemplateBodySlide("sess_test", pageData, {
        getActivePresentation: () => mockPres,
        getSessionId: () => "sess_test"
      });
    },
    (err) => {
      assert.match(err.message, /COMPENSATION_SUCCEEDED/);
      assert.equal(deleted, true);
      assert.equal(slides.length, 2); // preserved original slides
      return true;
    }
  );
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: FAIL with `ReferenceError: appendTemplateBodySlide is not defined`

- [ ] **Step 3: 实现 `appendTemplateBodySlide` 与定位占位符逻辑**

在 `template-body-page.js` 中完整实现：
1. `findCustomLayout(pres, name)`：安全遍历 `pres.CustomLayouts` 匹配 `"标题和内容"`，若无则尝试索引或母版匹配；
2. `findPlaceholderShape(slide, expectedType, expectedName)`：先按名称匹配 `标题 1` / `内容占位符 2`，后备按占位符类型；
3. `writeBulletPoints(textRange, points)`：逐条写入要点并设置项目符号；
4. 逆向回滚：在 `catch` 块中立即调用 `newlyAddedSlide.Delete()`，核验初始页数恢复，包装标准异常码抛出。

- [ ] **Step 4: 运行测试验证通过**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/template-body-page.js formal-plugin-kit/tests/ppt-template-body-page.test.js
git commit -m "feat(ppt): implement appendTemplateBodySlide with placeholder filling and reverse compensation"
```

---

### Task 6: 任务窗格 UI 挂载、大纲联动与用户显式二次确认弹窗

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js`
- Test: `formal-plugin-kit/tests/ppt-template-body-page.test.js`

**Interfaces:**
- Consumes: `materialOutline.confirmOutline()`, `ensureTemplateBodyPage()`, `window.confirm`
- Produces: 任务窗格中 `#ppt-template-body-page-section`，包含大纲页选择下拉框、生成按钮、预览卡片、容量统计与“确认追加到幻灯片”按钮。

- [ ] **Step 1: 编写窗格集成契约测试**

```javascript
// formal-plugin-kit/tests/ppt-template-body-page.test.js (新增 DOM 交互与确认测试)
test("taskpane UI: renders page selection and calls window.confirm before appending", async () => {
  // Test DOM binding and window.confirm gate
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: FAIL

- [ ] **Step 3: 编写 HTML/CSS 与 Taskpane JS 事件绑定**

1. 在 `taskpane.html` 中新增正文页生成卡片区域；
2. 在 `taskpane.css` 中添加正文页预览、出处徽标、讲稿折叠与容量警示样式；
3. 在 `taskpane.js` 中引入 `ensureTemplateBodyPage()`，监听大纲确认事件与单页选择，实现显式 `window.confirm` 对话框，并在确认后执行追加写入。

- [ ] **Step 4: 运行测试验证通过**

```bash
node --test formal-plugin-kit/tests/ppt-template-body-page.test.js
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js formal-plugin-kit/tests/ppt-template-body-page.test.js
git commit -m "feat(ppt): integrate template body page generation into taskpane with confirmation dialog"
```

---

### Task 7: 全量测试验证、交付白名单审计与文档归档

**Files:**
- Modify: `packaging/delivery-sources-v0260-preview1.json`
- Modify: `packaging/audit_v0260_preview1_delivery.py`
- Modify: `docs/codex-handoff.md`
- Test: 全量单元测试与交付审计

- [ ] **Step 1: 运行全量前端契约测试**

```bash
node --test formal-plugin-kit/tests/*.test.js
```
Expected: ALL PASS

- [ ] **Step 2: 运行全量后端测试**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest bash -c "PYTHONPATH=adapter_service pytest -q adapter_service/tests"
```
Expected: ALL PASS

- [ ] **Step 3: 执行 Python 3.8 语法编译与差异检查**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace ai-wps-test-runner:latest python -m compileall adapter_service/
git diff --check
```
Expected: 0 errors, 0 warnings

- [ ] **Step 4: 更新交付白名单与审计**

将 `template_page.py`、`ppt-template-page.md`、`template-body-page.js` 纳入 `packaging/delivery-sources-v0260-preview1.json`，运行交付审计用例。

- [ ] **Step 5: 更新 `docs/codex-handoff.md` 并提交**

记录 Issue #239 的实现细节、模板与占位符约定、容纳量拦截与回滚验证结论。

```bash
git add packaging/ docs/codex-handoff.md
git commit -m "docs: update codex handoff and delivery sources for issue 239 ppt template body page"
```
