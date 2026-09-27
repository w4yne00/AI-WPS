# PPT：根据资料生成并确认逐页大纲设计规格 (Issue #238)

- 日期：2026-09-27
- 状态：已确认，待编制计划
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#238、#229（Parent）、#234（Prerequisite）、#235（Prerequisite）、#239（Subsequent: 用固定模板生成并追加正文页）
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Parent Issue #229 以及前置 Issue #234、#235、#236、#237 中，AI-WPS 已经先后为 Word 与 Excel 建立了成熟的多资料导入、持久化仓储（`WordMaterialStore` / `ExcelMaterialStore`）、跨宿主复用克隆、事实冲突裁决以及受控内容生成机制。

在 PPT（演示文稿）宿主中：
1. **现有功能仅限既有幻灯片总结与审查**：目前 PPT 插件支持 `ppt.slide_assistant`（单页/全篇智能总结）与 `ppt.structure_review`（结构审查），但均以当前演示文稿内部已存在的形状和文字为处理对象，**完全缺乏从外部长篇 DOCX 方案/立项/汇报资料中提取结构化演示大纲的能力**；
2. **缺乏跨宿主资料复用与演示文稿独立资料集**：用户在 Word 中起草的技术方案或在 Excel 中编制的项目台账资料，无法在 PPT 中被主动复用为演示文稿依据，导致反复上传或信息脱节；
3. **缺乏逐页大纲生成与依据追溯**：根据资料编写 PPT 时，容易出现脱离资料捏造论据、章节逻辑混乱、页数失控以及重点遗漏；需要结合汇报对象与目标页数，先产出结构清晰、出处可查、缺项明确的逐页大纲；
4. **缺乏内容填充前置确认门禁**：生成完整幻灯片内容（Issue #239）耗时较长且排版成本高，若大纲未经用户确认即开始生成，会造成严重的算力浪费与不符合预期的返工。必须建立显式的“大纲查看与确认”门禁机制，未经确认严禁进入内容填充，修改大纲后需重新确认。

本规格依据 Issue #238 验收标准，为 PPT 插件及 Adapter 建立“根据资料生成并确认逐页大纲”的端到端技术规范。本票严格聚焦于**资料管理、汇报对象/页数配置、逐页大纲生成、依据与缺项展示、以及大纲确认门禁**，**本票保持幻灯片纯只读，调用幻灯片写入 API 的次数严格为 0**，向幻灯片模板填充内容由后续 Issue #239 承载。

---

## 2. 核心架构原则与不变量

1. **演示文稿独立资料集原则（物理隔离）**：
   - 支持在 PPT 中主动上传导入 DOCX 资料，或从系统已有来源（Word 方案文档、Excel 工作簿或其他 PPT 文档）中主动复用资料；
   - 跨文档复用必须由用户主动触发。一旦复用，系统在当前演示文稿专属存储目录（`ppt_materials/`）下**原子克隆**一套完全独立的资料副本（包含文件、大纲与片段缓存）；
   - **单向解耦**：当前演示文稿对克隆资料集的任何更新、替换或删除，绝不反向影响原文档；原文档后续无论做任何修改或删除，当前演示文稿资料集绝不自动跟随变更，不建立共享全知知识库。
2. **逐页大纲原子结构原则（结构化与角色分工）**：
   - 大纲按“页”为单位进行原子分解，严格契约化每一页的元数据：
     - 序号与角色：明确 `pageIndex`（从 1 开始）与 `pageRole`（如 `cover` 封面页、`agenda` 目录页、`transition` 过渡页、`content` 正文要点页、`summary` 总结页、`backcover` 封底页）；
     - 标题与要点：明确 `title` 与 `keyPoints`（清晰扼要的论述要点，杜绝大段无结构正文）；
     - 依据与缺项：绑定 `fragmentIds` 与还原出的 `sources`（文件名、章节、原文），并在资料依据不足时显式记录 `missingItems`。
3. **真实性与冲突遵从原则**：
   - 严禁捏造大纲要点或凭空编造论据；
   - 资料中未提及的关键事实（如未提及具体完成时间、未提及预算金额等），必须在 `missingItems` 中标明，绝不编造假数字；
   - 若资料间存在事实冲突，通过冲突裁决机制（`conflictResolutions`）由用户手动取舍，系统严格遵从用户选择，不得按文件时间自动覆盖。
4. **大纲确认门禁原则（Core Gate for Issue #239）**：
   - 生成大纲后默认处于 `unconfirmed` 状态；
   - 窗格提供逐页大纲审阅、微调与显式「确认大纲」操作，确认后记录带有时间戳和指纹的 `confirmedOutline` 快照；
   - **硬性门禁**：未经确认的大纲，严格拦截、禁止进入后续模板内容填充流程；
   - **失效熔断**：若用户修改了大纲文本、调整了生成参数，或底层依据资料发生了更新/移除，大纲确认状态立即置为 `needs_reconfirmation`，必须重新确认后方可重新放行。
5. **幻灯片只读不变量（Issue #238 边界）**：
   - 本票所有操作仅限于窗格内的资料管理、参数输入、逐页大纲渲染、出处侧栏查看、TSV/纯文本复制以及确认状态记录；
   - **全流程调用 PPT 幻灯片、形状、文本框写入 API 的次数严格为 0**。
6. **既有任务无干扰原则**：
   - 不改变现有 `ppt.slide_assistant`（智能总结）与 `ppt.structure_review`（结构审查）的任何功能、性能诊断与自动化测试。

---

## 3. 存储架构与资料管理 API

### 3.1 独立持久化存储目录 (`ppt_materials`)

在 Adapter 的持久化根目录下设立独立的 `ppt_materials` 目录：

```text
$AI_WPS_STATE_DIR/ppt_materials/
└── <document_identity_hash>/
    ├── manifest.json                  # 资料清单、总字数、总文档数元数据
    ├── catalog_cache.json             # 大纲章节树与原文片段索引
    └── files/                         # 安全校验后的 DOCX 文件副本
        ├── mat_xxxx.docx
        └── mat_yyyy.docx
```

### 3.2 跨宿主资料复用与克隆接口

1. **列出可复用资料源（三宿主聚合）**：
   - `GET /materials/reusable-sources`（双运行时对等提供）；
   - 统一扫描系统中已存在的所有合法资料目录：`word_materials`、`excel_materials` 与 `ppt_materials`；
   - 返回统一的来源列表：
     ```json
     {
       "sources": [
         {
           "sourceSessionId": "sess_word_12345",
           "documentIdentity": "full:/Users/wayne/docs/项目总体建设方案.docx",
           "displayName": "项目总体建设方案.docx",
           "host": "word",
           "totalDocuments": 3,
           "totalCharacters": 48200,
           "updatedAt": "2026-09-27T10:15:00Z"
         },
         {
           "sourceSessionId": "sess_excel_67890",
           "documentIdentity": "full:/Users/wayne/sheets/项目任务跟踪表.xlsx",
           "displayName": "项目任务跟踪表.xlsx",
           "host": "excel",
           "totalDocuments": 1,
           "totalCharacters": 15300,
           "updatedAt": "2026-09-27T11:20:00Z"
         }
       ]
     }
     ```
2. **克隆资料至当前演示文稿**：
   - `POST /ppt/materials/clone-from-source`
   - 入参：
     ```json
     {
       "sourceSessionId": "sess_word_12345",
       "targetDocumentSessionId": "sess_ppt_99999",
       "targetDocumentIdentity": "full:/Users/wayne/slides/项目阶段汇报.pptx"
     }
     ```
   - 行为：
     - 在锁保护下校验源目录存在且无并发写；
     - 创建目标演示文稿专属目录，原子复制 `files/`、`manifest.json` 与 `catalog_cache.json`；
     - 重置目标 `manifest.json` 中的 `documentIdentity`、`documentSessionId` 与时间戳；
     - 返回当前演示文稿的资料目录摘要（`catalogSummary`）。

### 3.3 资料生命周期接口（与 Word/Excel 对等）

- `POST /ppt/materials/import`：上传单个 DOCX，强校验安全上限（单会话最多 5 份文件、100,000 Unicode 可读字符、256 表格列、100,000 展开单元格）；
- `PUT /ppt/materials/{material_id}`：单份资料原子替换，重新计算容量配额，超限拒绝且保留原资料；
- `DELETE /ppt/materials/{material_id}`：物理移除指定资料，同步清理大纲与原文索引；
- `GET /ppt/materials/catalog?documentSessionId=...`：查询当前演示文稿资料大纲与清单；
- `POST /ppt/materials/bind-document`：在演示文稿首次保存或另存为新文件时，原子迁移资料目录；
- **并发互斥门禁**：当当前会话存在活跃的 `ppt.material_outline` 任务时，更新或移除资料统一返回 409 `MATERIAL_COMPOSER_BUSY`。

---

## 4. 逐页大纲生成长任务 (`ppt.material_outline`)

### 4.1 任务定义与系统提示词

- **任务标识**：`ppt.material_outline`
- **系统提示词文件**：`adapter_service/system_prompts/ppt-material-outline.md`
- **规则要点**：
  1. 接收输入：
     - 汇报对象 `audience`（如“公司高管/领导层”、“技术专家/架构评审”、“客户代表/业务骨干”）；
     - 预定页数 `slideCount`（通常为 4~20 页正整数）；
     - 重点要求 `instruction`（篇幅、侧重点、风格）；
     - 用户补充事实 `userFacts`；
     - 事实冲突裁决 `conflictResolutions`；
     - 已召回的 DOCX 事实片段。
  2. 输出规范（严格契约化 JSON）：
     ```json
     {
       "schemaVersion": "ppt.material_outline.v1",
       "audience": "公司高管汇报",
       "slideCount": 6,
       "instruction": "重点汇报一期成果与二期投入规划",
       "slides": [
         {
           "pageIndex": 1,
           "pageRole": "cover",
           "title": "新一代业务系统阶段成果与规划汇报",
           "keyPoints": [
             "汇报主题与核心目标",
             "汇报部门与日期"
           ],
           "missingItems": [],
           "fragmentIds": [1]
         },
         {
           "pageIndex": 2,
           "pageRole": "agenda",
           "title": "汇报目录",
           "keyPoints": [
             "项目背景与建设目标",
             "一期核心成果与上线成效",
             "二期建设计划与资源预算",
             "需协调解决的关键事项"
           ],
           "missingItems": [],
           "fragmentIds": [1, 2]
         },
         {
           "pageIndex": 3,
           "pageRole": "content",
           "title": "一期建设核心成果与落地成效",
           "keyPoints": [
             "三大业务模块全面上线运行，覆盖 12 个业务网点",
             "系统日均处理请求超过 50 万笔，零重大故障",
             "业务办理平均耗时由 15 分钟降至 3 分钟"
           ],
           "missingItems": [],
           "fragmentIds": [3, 4]
         },
         {
           "pageIndex": 4,
           "pageRole": "content",
           "title": "二期建设规划与投资预算",
           "keyPoints": [
             "二期建设重点：移动端扩展与智能风控引擎",
             "工期规划：预计 2027 年 6 月完成初验"
           ],
           "missingItems": [
             "二期总投资预算未在参考资料中明确提及"
           ],
           "fragmentIds": [5]
         },
         {
           "pageIndex": 5,
           "pageRole": "summary",
           "title": "工作总结与建议",
           "keyPoints": [
             "阶段总结：一期指标全部达成，成效显著",
             "推进建议：尽快启动二期立项审批与资源调配"
           ],
           "missingItems": [],
           "fragmentIds": [5, 6]
         },
         {
           "pageIndex": 6,
           "pageRole": "backcover",
           "title": "感谢聆听，请批评指正",
           "keyPoints": [
             "Q&A 交流环节"
           ],
           "missingItems": [],
           "fragmentIds": []
         }
       ]
     }
     ```
  3. 结构与事实约束：
     - 输出页数必须严格等于用户指定的 `slideCount`；
     - 每一页必须赋予合理的 `pageRole`（`cover`、`agenda`、`transition`、`content`、`summary`、`backcover`）；
     - 每一页的要点必须在 `fragmentIds` 中引用真实片段，经服务端校验后回填原始文件名、章节及原文；
     - 未被资料提及的关键事实，在 `missingItems` 中标明，杜绝臆造。

### 4.2 任务接口规范

1. **事实冲突检测**：
   - `GET/POST /ppt/material-outline/conflicts`
   - 分析当前资料与 `userFacts` 中的时间、金额、工期与责任差异，返回可供用户勾选裁决的冲突项。
2. **提交生成任务**：
   - `POST /ppt/material-outline/jobs`
   - 请求体限制：64 KiB；
   - 入参：
     ```json
     {
       "documentSessionId": "sess_ppt_99999",
       "clientJobId": "job_uuid_xxxx",
       "audience": "公司高管汇报",
       "slideCount": 6,
       "instruction": "重点汇报一期成果与二期投入规划",
       "userFacts": "二期资金已完成内部预审",
       "conflictResolutions": []
     }
     ```
   - 互斥检查：同一演示文稿在途生成互斥（409 `MATERIAL_COMPOSER_BUSY`）；同一 `clientJobId` 支持幂等恢复。
3. **查询任务进度与结果**：
   - `GET /ppt/material-outline/jobs/{job_id}?documentSessionId=...`
   - 返回标准长任务信封（`queued` -> `preparing` -> `provider_processing` -> `parsing` -> `completed` / `failed` / `cancelled`），包含阶段耗时指标（`phaseDurationsMs`）与终态大纲。
4. **取消任务**：
   - `POST /ppt/material-outline/jobs/{job_id}/cancel`
   - 携带 `documentSessionId`，中断执行，释放槽位，不产生可确认大纲。

---

## 5. 前端插件与任务窗格交互规范 (`wps-ai-assistant-wpp_1.0.0`)

### 5.1 功能区与模式定义

- 在 `ribbon.xml` 中新增「资料大纲」按钮：
  ```xml
  <button id="btnAiPptMaterialOutline" label="资料大纲" size="large" getImage="GetImage" onAction="OnAction" />
  ```
- 在 `ribbon.js` 的 `resolveMode` 中映射 `btnAiPptMaterialOutline -> "pptMaterialOutline"`。
- 在 `taskpane.html` 中新增模式容器 `<div id="ppt-material-outline-options" class="mode-block" hidden>` 与专属大纲审阅/确认面板。

### 5.2 独立控制器模块设计 (`material-outline.js`)

参照 Excel `material-ledger.js` 的成熟设计模式，在 PPT 插件中建立独立的 `material-outline.js`：
1. **状态管理（按 `documentSessionId` 隔离）**：
   - 资料状态：`catalogSummary`、`catalogLabel`、`reusableSources`；
   - 输入参数：`audience`（默认推荐列表或自定义）、`slideCount`（4~20 步进器/输入框，默认 8）、`instruction`、`userFacts`、`conflicts`、`conflictResolutions`；
   - 任务状态：`jobId`、`status`、`phase`、`busy`；
   - 结果与大纲确认状态：
     - `result`：当前生成的大纲对象；
     - `confirmationStatus`：`unconfirmed`（未确认）| `confirmed`（已确认）| `needs_reconfirmation`（需重新确认）；
     - `confirmedOutline`：用户显式确认后持久化的快照（包含版本、时间戳与大纲内容）；
     - `activeDrawerPageIndex`：当前展开出处的页面索引。

### 5.3 窗格功能区块与交互流程

1. **资料管理卡片 (Material Strip)**：
   - 统计展示：“已添加 X/5 份资料，合计 Y/100,000 字”；
   - 动作：提供「导入 DOCX」与「复用已有资料」下拉菜单；
   - 列表：展示已导入资料名称与删除按钮；
   - 依据失效警示：若生成后资料被修改或移除，激活黄色警示，大纲确认状态强制转为 `needs_reconfirmation`。
2. **大纲生成参数配置**：
   - **汇报对象 (`audience`)**：提供常用预设（公司高管、技术团队、客户代表、全员大会）与自定义文本输入；
   - **预定页数 (`slideCount`)**：数值输入控件（范围限制为 3~30，默认 8 页）；
   - **重点要求 (`instruction`)** 与 **用户补充事实 (`userFacts`)**；
   - **事实冲突裁决区**：若检测到冲突，以单选卡片形式呈现供用户手动裁决。
3. **逐页大纲审阅面板 (Outline Review Panel)**：
   - 列表展示每一页的大纲卡片：
     - 顶部：页码 Badge（如 `P.1`）、页面角色标签（如 `[封面页]`、`[目录页]`、`[正文页]`、`[总结页]`）；
     - 标题：展示页面标题，允许用户直接在输入框中微调；
     - 内容要点：列表展示核心论述点；
     - 缺项警示：若该页存在缺项，标黄显示 `〔待补充：xxx〕`；
     - 出处抽屉：点击「查看依据」，侧栏展开该页所依据的 DOCX 文件名、章节及原文高亮片段。
4. **大纲确认门禁交互（Core Gate）**：
   - 面板底部常驻大纲确认栏：
     - 未确认时：展示警示文本“⚠️ 逐页大纲尚未确认，确认后方可进行后续幻灯片内容生成”，并提供醒目的「确认大纲」按钮；
     - 用户点击「确认大纲」后：
       - 冻结当前大纲快照至 `confirmedOutline`；
       - 状态更新为“✅ 逐页大纲已确认（共 X 页）”；
       - 对外暴露 `hasConfirmedOutline()` 校验接口（供后续 Issue #239 的“用模板生成正文页”作为前置门禁调用）；
     - 若用户修改了大纲标题/要点，或重新修改了参数/资料，状态自动变为“⚠️ 大纲已发生变更，请重新确认”，清空已确认标记。
   - 工具按钮：提供「复制大纲文本」与「复制大纲表格」功能，方便用户手动导出。

---

## 6. 验证与门禁标准

### 6.1 后端自动化验证 (Python 3.8)

1. `test_ppt_material_import.py`：
   - 覆盖 PPT 资料上传、安全校验（5 份 / 10 万字 / 256 列 / 10 万单元格）；
   - 覆盖跨宿主克隆：从 Word、Excel 资料克隆到 PPT 专属目录，修改 PPT 资料不影响源端；
   - 覆盖资料单份更新、物理移除、容量重算与文档另存为会话重新绑定。
2. `test_ppt_material_outline.py`：
   - 覆盖汇报对象与页数映射，严格校验返回页数与角色标签；
   - 覆盖片段出处回填、虚假出处拒绝拦截与缺项保留；
   - 覆盖长任务生命周期（提交、排队、分阶段耗时、取消中断、重开查询恢复）。
3. `test_ppt_material_outline_api.py`：
   - 验证 FastAPI 与 Standalone 双运行时所有路由对等可用。

### 6.2 插件契约自动化验证 (Node.js)

`formal-plugin-kit/tests/ppt-material-outline.test.js`：
1. 验证资料导入与复用已有资料交互；
2. 验证汇报对象与页数配置输入校验；
3. 验证任务提交、阶段流转、取消与结果展示；
4. 验证逐页大纲卡片渲染、角色标签、缺项标黄与出处展开；
5. **确认门禁契约验证**：
   - 初始状态严格为未确认，门禁检查返回 `false`；
   - 点击确认后更新为已确认，持久化快照，门禁检查返回 `true`；
   - 编辑大纲或更新资料后门禁自动降级，要求重新确认；
6. **只读保证核对**：断言整个大纲生成、审阅与确认全生命周期中，WPS 幻灯片写入接口调用次数严格为 0；
7. 验证多演示文稿会话隔离与重开窗格状态恢复。

---

## 7. 交付与不破坏原则

- 不修改 `wps-addon` 旧原型；
- 不破坏现有 PPT 智能总结（`ppt.slide_assistant`）与结构审查（`ppt.structure_review`）的既有行为与测试；
- 遵循 Python 3.8 兼容性规范与 `git diff --check`。
