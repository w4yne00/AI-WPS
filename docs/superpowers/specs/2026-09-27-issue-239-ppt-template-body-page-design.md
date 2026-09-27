# PPT：用固定模板生成并追加一张正文页设计规格 (Issue #239)

- 日期：2026-09-27
- 状态：已确认，待编制计划
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#239、#229（Parent）、#238（Prerequisite: 逐页大纲生成与确认）、#240（Subsequent: 完成四类页面与整套内容填充）
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Issue #238 中，AI-WPS 已经为 PPT 宿主成功建立了独立资料管理仓储（`PptMaterialStore`）、逐页大纲生成、出处追溯与显式确认门禁（`confirmedOutline` / `hasConfirmedOutline()`）。

Issue #239 是将大纲真正转化为演示文稿实体的第一步关键里程碑：
1. **取得实际固定模板**：不再使用自造空白或不可控排版，基于用户提供的真实 PPT 模板（`PPT模板.pptx`），精准识别母版中的正文页版式与占位符几何坐标；
2. **从已确认大纲选一页生成高精正文与讲稿**：根据用户已确认的逐页大纲，由用户选定其中某一页，调用独立的 `ppt.template_page` 模型任务，生成契合该页主题的结构化标题、3~4 个展开要点以及专供演讲者使用的讲稿备注；
3. **出处核对与预览确认门禁**：在窗格呈现只读预览，清晰标注各要点引用的 DOCX 原始出处；用户通过显式二次确认弹窗（`window.confirm`）核对后方可写入；
4. **演示文稿末尾安全追加可编辑正文页**：在当前活动演示文稿末尾（第 N+1 页）新增一张正文页，仅填充约定的标题、正文及备注位置，保持文稿现有既有页面 100% 不变；写入后的标题、正文与备注在目标 WPS 中完全可编辑；
5. **排版容纳量严防溢出（Fail-Closed）**：内容超出模板正文框容量时，严格阻止写入并显式提示，严禁静默截断文字，严禁无限缩小字号破坏可读性；
6. **逆向补偿回滚与重试防重**：在写入中途发生任何异常（如部分填充失败）时，立即删除新增的不完整幻灯片，恢复原样；成功写入后记录状态，重试或重复点击不重复追加。

---

## 2. 真实模板与占位符约定规格

### 2.1 模板元数据与版式定义

本票采用用户实际提供的正式模板文件：
- 模板路径：`/Users/wayne/Desktop/企业 AI 安全运营就绪度参考架构/PPT模板.pptx`
- 仓库测试对照副本：`formal-plugin-kit/tests/fixtures/PPT模板.pptx`
- 画布规格：16:9 宽屏（13.33" × 7.5"，对应 12,192,000 × 6,858,000 EMU）
- 目标正文页母版版式：`slideLayout3.xml`，版式名称为 **`"标题和内容"`**（英文通常对应 `Title and Content`）

### 2.2 占位符几何与映射契约

在 `slideLayout3.xml` 及对应的幻灯片实例中，严格定位以下约定的占位符：

| 占位符用途 | 形状名称 / 标识 | 占位符类型 (`ph.type`) | 几何坐标 (x, y) | 尺寸 (cx, cy) | 写入内容与格式要求 |
|---|---|---|---|---|---|
| **正文页标题** | `标题 1` | `title` (`ppPlaceholderTitle`) | (0.92", 1.94") | 11.50" × 1.45" | 纯文本标题，单行或最多两行，保持母版字体与字号 |
| **正文内容要点** | `内容占位符 2` | `body` (`ppPlaceholderBody`, `idx=1`) | (0.92", 3.49") | 11.50" × 3.27" | 3~4 个独立段落，每段设项目符号（Bullet），段落间保留间距 |
| **演讲备注/讲稿** | `备注占位符 4` | `body` (`ppPlaceholderBody`, `idx=3`) | NotesPage | NotesPage 标准 | 写入 `Slide.NotesPage.Shapes` 备注框，为连贯完整的口语化演讲讲稿 |

**现有页面保护规则**：
- 模板原有幻灯片共 6 页（封面、目录、3 个过渡章节、封底）；
- 新正文页必须追加到当前演示文稿末尾：`targetIndex = ActivePresentation.Slides.Count + 1`；
- 严禁修改、删除或覆盖第 1 至第 N 张现有幻灯片中的任何形状和文字。

---

## 3. 排版容纳量防御规范（Anti-Overflow Defense）

### 3.1 物理约束分析
- 正文占位符高度为 3.27 英寸（约 235 磅/pt）；
- 正文默认字号为 20pt/18pt，项目符号段落行高约为 26~28pt；
- 在不自动缩小字号（Auto-fit shrink disabled）且不溢出容器的前提下，该容器最大可容纳 **8 行文本**（折行后累计）。

### 3.2 容纳量门禁规则（Fail-Closed）
1. **要点数量上限**：最多 4 个要点（`maxKeyPoints = 4`），最少 2 个要点；
2. **总字数与折行预算上限**：
   - 累计中文字符数（含标点）不得超过 **260 汉字**；
   - 单个要点建议 30~60 汉字；
   - 估算折行数：`estimatedLines = sum(ceil(len(point) / 36))`（在 11.5" 宽容器中每行约排 34~38 个 20pt 汉字），要求 `estimatedLines <= 8`；
3. **超限拒绝机制**：
   - 若生成的正文要点或用户编辑后的内容超过 260 字或折行数大于 8 行，前端写入按钮被拦截，抛出 `OVERFLOW_PREVENTED` 错误；
   - 窗格呈现醒目警示：“⚠️ 生成内容超出模板占位符容纳容量（当前估算 X 行 / Y 字，容量上限 8 行 / 260 字）；已阻止写入，以防止内容截断或字号缩小，请精简要点后再写入”。

---

## 4. 后端模型任务与协调器架构 (`ppt.template_page`)

### 4.1 任务注册与提示词模板
- 注册任务类型：`ppt.template_page`
- 系统提示词文件：`adapter_service/system_prompts/ppt-template-page.md`
- 角色定义：将 PPT 逐页大纲中的某一页要点，结合参考资料原始片段，扩充为结构清晰的幻灯片正文和演讲者讲稿。要求：
  - 提炼精炼标题（不超过 20 字）；
  - 提炼 3~4 个层级分明、论述充分的正文要点；
  - 编写连贯、自然的演讲备注讲稿（150~300 字）；
  - 严格依据提供的 `fragmentIds`，不捏造数据，资料未提及内容列入 `missingItems`。

### 4.2 数据契约与接口定义

#### 1. 提交生成任务
`POST /ppt/template-page/jobs`
- 请求体限制：64 KiB 上限；
- 请求体结构：
  ```json
  {
    "documentSessionId": "sess_ppt_12345",
    "clientJobId": "job_page_67890",
    "pageIndex": 3,
    "pageRole": "content",
    "outlineTitle": "总体架构设计",
    "outlineKeyPoints": ["分层解耦", "安全可控", "弹性伸缩"],
    "outlineFragmentIds": [1, 2],
    "instruction": "重点强调安全合规与自主可控",
    "userFacts": "系统需通过等保三级认证",
    "maxKeyPoints": 4
  }
  ```

#### 2. 查询任务状态
`GET /ppt/template-page/jobs/{job_id}?documentSessionId={sessionId}`
- 统一返回单调毫秒级诊断指标（`elapsedMs`、`phaseDurationsMs`、`queueWaitMs`）；
- 终态结果对象契约（`schemaVersion: "ppt.template_page.v1"`）：
  ```json
  {
    "schemaVersion": "ppt.template_page.v1",
    "pageIndex": 3,
    "pageRole": "content",
    "title": "总体架构设计与核心技术原则",
    "keyPoints": [
      "分层解耦：采用业务域服务化解耦架构，支撑各模块独立演进与灰度发布",
      "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
      "弹性伸缩：基于动态容器编排与流量调度，保障突发高并发场景平稳可用"
    ],
    "speakerNotes": "各位领导，本页展示的是系统总体架构设计。我们严格遵循分层解耦、安全可控与弹性伸缩三大原则，既确保了架构的灵活性，又满足了国家信息安全等级保护三级的硬性合规要求...",
    "fragmentIds": [1, 2],
    "sources": [
      {
        "fragmentId": 1,
        "materialId": "mat_1",
        "fileName": "项目总体建设方案.docx",
        "chapter": "第一章 架构设计",
        "text": "系统总体架构采用分层解耦设计..."
      }
    ],
    "missingItems": [],
    "estimatedLines": 5,
    "totalCharacters": 158,
    "basisMaterials": [
      {
        "materialId": "mat_1",
        "fileName": "项目总体建设方案.docx",
        "updatedAt": "2026-09-27T10:15:00Z"
      }
    ],
    "generatedAt": "2026-09-27T12:30:00Z"
  }
  ```

#### 3. 取消任务
`POST /ppt/template-page/jobs/{job_id}/cancel`
- 传入 `documentSessionId`，中断后台轮询，释放活跃锁，不产生可写草稿。

### 4.3 协调器设计 (`PptTemplatePageCoordinator`)
- 位于 `adapter_service/app/services/ppt/template_page.py`；
- 在提交前校验当前会话的 `PptMaterialStore`，召回关联的原始资料片段；
- 维护 `jobs` 字典，支持同一 `clientJobId` 幂等查询；
- 双运行时对等支持：在 `app/api/ppt.py` 与 `standalone_adapter.py` 对等暴露。

---

## 5. 插件前端控制器与 WPS 写入规格

### 5.1 模块划分与生命周期 (`template-body-page.js`)
在 `formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/` 下新增 `template-body-page.js`：
1. **大纲前置门禁核验**：
   - 依赖 `materialOutline.hasConfirmedOutline()`；
   - 若未确认或大纲失效，隐藏/禁用正文页生成模块，并显示“请先生成并确认逐页大纲”；
2. **选择待生成页面**：
   - 从 `materialOutline.getConfirmedOutline().slides` 中提取候选页列表（重点标记 `pageRole === 'content'` 的页面）；
   - 用户选择其中一页后，展示该页的原有要点与写作要求；
3. **提交与只读预览渲染**：
   - 提交后台长任务，显示阶段文字（排队中 -> 分析资料 -> 正在生成正文与讲稿 -> 校验排版容量）；
   - 完成后渲染结果卡片：可编辑的标题输入框、要点列表（附带出处高亮标签）、讲稿备注文本框、容量统计（X 字 / Y 行）、以及复制按钮；
4. **依据失效熔断保护**：
   - 监听资料变更事件（`onMaterialsChanged`）与大纲变更事件；
   - 若依据资料被更新/删除或大纲被修改，已生成的正文页结果标记为 `stale`，禁用写入按钮。

### 5.2 WPS JSAPI 幻灯片写入与逆向回滚算法

写入函数 `appendTemplateBodySlide(targetDocSession, pageData, options)`：

```javascript
// 核心写入流程伪代码
async function appendTemplateBodySlide(targetDocSession, pageData, options) {
  // 1. 会话一致性门禁
  var activeSession = getActivePresentationSessionId();
  if (activeSession !== targetDocSession) {
    throw new Error("SESSION_MISMATCH: 当前活动演示文稿已变更，已暂停写入");
  }

  // 2. 重复写入防御（幂等性）
  if (pageData.writtenSlideIndex) {
    throw new Error("ALREADY_WRITTEN: 该正文页已于 " + pageData.writtenAt + " 追加至第 " + pageData.writtenSlideIndex + " 页，不可重复追加");
  }

  // 3. 排版容纳量检查 (Fail-Closed)
  var capacity = evaluateSlideTextCapacity(pageData.keyPoints);
  if (capacity.isOverflow) {
    throw new Error("OVERFLOW_PREVENTED: 内容超出模板占位符容纳容量（估算 " + capacity.estimatedLines + " 行，上限 8 行），已阻止写入");
  }

  // 4. 获取目标版式（"标题和内容"）
  var pres = wps.WppApplication().ActivePresentation;
  var customLayout = findCustomLayout(pres, "标题和内容");
  if (!customLayout) {
    throw new Error("LAYOUT_NOT_FOUND: 当前演示文稿母版中未找到【标题和内容】版式，请使用约定模板");
  }

  // 5. 记录初始页数
  var initialSlideCount = pres.Slides.Count;
  var targetSlideIndex = initialSlideCount + 1;
  var newlyAddedSlide = null;

  try {
    // 6. 追加空白版式页到末尾
    newlyAddedSlide = pres.Slides.AddSlide(targetSlideIndex, customLayout);

    // 7. 写入标题 (保持母版格式)
    var titleShape = findPlaceholderShape(newlyAddedSlide, "title", "标题 1");
    if (titleShape && titleShape.TextFrame) {
      titleShape.TextFrame.TextRange.Text = pageData.title;
    }

    // 8. 写入正文要点 (逐行设置段落与项目符号)
    var bodyShape = findPlaceholderShape(newlyAddedSlide, "body", "内容占位符 2");
    if (bodyShape && bodyShape.TextFrame) {
      writeBulletPoints(bodyShape.TextFrame.TextRange, pageData.keyPoints);
    }

    // 9. 写入演讲备注
    if (newlyAddedSlide.NotesPage) {
      var notesShape = findNotesBodyShape(newlyAddedSlide.NotesPage);
      if (notesShape && notesShape.TextFrame) {
        notesShape.TextFrame.TextRange.Text = pageData.speakerNotes || "";
      }
    }

    // 10. 标记成功
    pageData.writtenSlideIndex = targetSlideIndex;
    pageData.writtenAt = new Date().toISOString();
    return { success: true, slideIndex: targetSlideIndex };

  } catch (writeError) {
    // 11. 逆向补偿回滚 (Reverse Compensation Rollback)
    if (newlyAddedSlide) {
      try {
        newlyAddedSlide.Delete();
      } catch (deleteError) {
        throw new Error("COMPENSATION_FAILED: 追加写入失败且删除新增页失败，错误：" + writeError.message);
      }
    }
    throw new Error("COMPENSATION_SUCCEEDED: 写入遇到异常，已成功回滚并移除新增页面，原演示文稿保持不变。原因：" + writeError.message);
  }
}
```

### 5.3 用户显式确认交互 (Window Confirm)
在点击窗格「确认追加到幻灯片」按钮时：
```javascript
var confirmMessage = "请核对写入目标与内容：\n\n" +
  "• 演示文稿：" + activePresName + "\n" +
  "• 追加位置：文稿末尾（第 " + (initialCount + 1) + " 页）\n" +
  "• 采用版式：固定模板【标题和内容】\n" +
  "• 页面标题：" + pageData.title + "\n" +
  "• 要点数量：" + pageData.keyPoints.length + " 个要点（估算 " + capacity.estimatedLines + " 行）\n\n" +
  "确认将该正文页追加写入当前文稿吗？现有页面将保持不变。";

if (!window.confirm(confirmMessage)) {
  setStatus("已取消写入，演示文稿未发生任何变动。");
  return;
}
```

---

## 6. 测试与验证标准

### 6.1 后端自动化验证 (Python 3.8 / Pytest)
1. `test_ppt_template_page_prompt.py`：
   - 验证提示词模板完整性，禁止包含未声明字段；
   - 验证单页生成、要点提炼与演讲备注格式规范。
2. `test_ppt_template_page.py`：
   - 覆盖 `PptTemplatePageCoordinator` 核心逻辑；
   - 验证从 `PptMaterialStore` 关联召回出处片段；
   - 验证虚假出处拦截与 `missingItems` 保留；
   - 验证长任务生命周期（排队、执行、取消、毫秒诊断）。
3. `test_ppt_template_page_api.py`：
   - 验证 FastAPI 与 Standalone 双运行时所有路由对等一致；
   - 验证 64 KiB 请求上限与 422 输入校验。

### 6.2 插件契约与行为测试 (Node.js)
`formal-plugin-kit/tests/ppt-template-body-page.test.js`：
1. **前置门禁断言**：大纲未确认时，正文页生成模块严格处于不可用状态；大纲确认后激活；
2. **大纲单页选择与输入传递**：验证选定第 N 页后能正确提取该页标题、要点与出处；
3. **容纳量溢出防护拦截**：构造超长文本（>260 字或 >8 行），断言 `evaluateSlideTextCapacity` 返回溢出，写入动作被拦截并弹出标准告警；
4. **末尾追加与占位符填充测试**：
   - Mock WPS JSAPI 环境，断言在文稿末尾（`Count + 1`）新增页面；
   - 断言第 1 至第 N 张现有幻灯片未被修改；
   - 断言正确使用 `"标题和内容"` 版式；
   - 断言标题、正文项目符号、备注框内容写入正确；
5. **逆向补偿回滚测试**：在正文或备注写入时模拟抛出 COM 异常，断言触发 `slide.Delete()`，演示文稿总页数恢复为初始值，返回 `COMPENSATION_SUCCEEDED`；
6. **幂等性与重试防重测试**：成功写入后，再次触发写入被拦截，报错 `ALREADY_WRITTEN`；
7. **会话隔离与切换保护**：生成期间切换演示文稿，点击写入被拦截，报错 `SESSION_MISMATCH`。

### 6.3 麒麟 V10 / WPS 真机验证
- 依据 `docs/operations/kylin-v10-test-environment.md` 进行真机验证；
- 在真实 WPS 中打开 `PPT模板.pptx`，通过插件生成正文页并追加写入；
- 真实核验追加的幻灯片中标题、正文项目符号、演讲备注均为原生可编辑文本，无错位、无字号无限缩小、现有幻灯片无变动；
- 如因真机环境暂不可达，按规范在交付与回归记录中如实报告 `manual-pending`，不得以自动化模拟伪造真机完成。

---

## 7. 交付边界与不破坏原则

1. 不修改 `wps-addon` 旧原型；
2. 不破坏既有 PPT 智能总结（`ppt.slide_assistant`）、结构审查（`ppt.structure_review`）与逐页大纲生成（`ppt.material_outline`）；
3. 遵循 Python 3.8 语法兼容性，`git diff --check` 0 警告，严格遵循交付白名单机制。
