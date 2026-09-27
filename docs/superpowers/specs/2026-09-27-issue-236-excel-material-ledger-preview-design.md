# Excel：从资料生成任务台账预览设计规格 (Issue #236)

- 日期：2026-09-27
- 状态：已确认，待编制计划
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#236、#229（Parent）、#234（Prerequisite）、#235（Prerequisite）、#237（Subsequent）
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Parent Issue #229 与 Issue #235 中，AI-WPS 已经为 Word 建立了完备的多资料导入、持久化仓储（`WordMaterialStore`）、目录汇总、事实冲突裁决以及草稿生成机制。

然而，在 Excel 宿主中：
1. **仅有单元格智能填写，缺乏资料台账能力**：现有 Excel 功能（智能分析、公式助手、智能填写）均基于工作表已用范围或小范围选区，无法从长篇方案、招标文件或立项报告等外部 DOCX 资料中直接提取结构化任务台账；
2. **缺乏跨文档/跨宿主资料复用**：用户在 Word 中起草方案导入的成套资料，无法在 Excel 中被主动复用生成配套任务清单，导致重复上传；
3. **缺乏台账粒度事实核验与重复控制**：传统直接生成表格容易出现多项任务混淆、虚构完成时间或责任部门、以及擅自合并相似工作导致任务遗漏等问题。

本规格依据 Issue #236 验收标准，为 Excel 插件及 Adapter 建立“从资料生成任务台账预览”的端到端技术规范。本票严格聚焦于**资料管理、表头映射、台账提取与只读预览呈现**，**预览阶段不修改任何单元格**，写入单元格由后续 Issue #237 承载。

---

## 2. 核心架构原则与不变量

1. **工作簿独立资料集原则（物理隔离）**：
   - 支持在 Excel 中主动上传导入 DOCX 资料，或主动从系统已有文档（如 Word 方案文档或其他工作簿）中复用资料；
   - 跨文档复用必须由用户主动触发。一旦复用，系统在当前工作簿专属存储目录下**原子克隆**一套完全独立的资料副本（包含文件、大纲与片段缓存）；
   - **单向解耦**：当前工作簿对克隆资料集的任何更新、替换或删除，绝不反向影响原文档；原文档后续无论做任何修改或删除，当前工作簿资料集绝不自动跟随变更，不建立共享全知知识库。
2. **一行一项可独立跟踪原则（原子粒度）**：
   - 模型提取必须保证任务粒度原子化，每一行代表一项可明确分配、跟踪与验收的独立工作，严禁把多项杂糅成单行。
3. **缺项留空与疑似重复仅提示原则（真实性防御）**：
   - **缺项留空**：若某项工作的责任部门、时间或交付物在资料原文中未提及，该字段必须输出空字符串，在结果中标记为 `missingFields`，并在界面用弱灰提示，严禁编造占位符或假时间；
   - **疑似重复仅提示**：若从不同资料或段落中提取出工作事项高度重叠的条目，系统只在结果中标注 `isDuplicate: true` 与 `duplicateReason`，在界面呈现警示气泡，**绝对不擅自合并或删除任何条目**。
4. **全链路可追溯性**：
   - 每一行台账必须绑定其事实来源的 `fragmentIds`，经 Adapter 服务端校验后回填对应的原始文件名、章节及原文片段。
5. **只读预览不变量（Issue #236 边界）**：
   - 本票所有操作仅限于窗格内的只读 HTML 表格展示、缺项标识、重复提醒与文本/TSV 复制，**全流程调用工作表写入 API 的次数严格为 0**。

---

## 3. 存储架构与资料管理 API

### 3.1 独立持久化存储目录 (`excel_materials`)

在 Adapter 的持久化根目录下设立独立的 `excel_materials` 目录：

```text
$AI_WPS_STATE_DIR/excel_materials/
└── <document_identity_hash>/
    ├── manifest.json                  # 资料清单、总字数、总文档数元数据
    ├── catalog_cache.json             # 大纲章节树与原文片段索引
    └── files/                         # 安全校验后的 DOCX 文件副本
        ├── mat_xxxx.docx
        └── mat_yyyy.docx
```

### 3.2 跨宿主/跨文档资料复用与克隆接口

1. **列出可复用资料源**：
   - `GET /materials/reusable-sources`（双运行时对等提供）
   - 扫描当前系统中所有合法的资料目录（包括 `word_materials` 与 `excel_materials`）；
   - 返回：
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
         }
       ]
     }
     ```
2. **克隆资料至当前工作簿**：
   - `POST /excel/materials/clone-from-source`
   - 入参：
     ```json
     {
       "sourceSessionId": "sess_word_12345",
       "targetDocumentSessionId": "sess_excel_67890",
       "targetDocumentIdentity": "full:/Users/wayne/sheets/项目任务跟踪表.xlsx"
     }
     ```
   - 行为：
     - 在锁保护下校验源目录存在且无并发写；
     - 创建目标工作簿专属目录，深度复制 `files/`、`manifest.json` 与 `catalog_cache.json`；
     - 重置目标 `manifest.json` 中的 `documentIdentity`、`documentSessionId` 与时间戳；
     - 返回当前工作簿的资料目录摘要（`catalogSummary`）。

### 3.3 资料生命周期接口（与 Word 对等支持）

- `POST /excel/materials/import`：上传单个 DOCX，更新限额（最多 5 份、100,000 字、256 列、100,000 展开单元格）；
- `PUT /excel/materials/{material_id}`：单份资料原子替换，容量重新校验，超限拒绝且不破坏原资料；
- `DELETE /excel/materials/{material_id}`：物理移除指定资料，扣减字数，释放配额；
- `GET /excel/materials/catalog?documentSessionId=...`：查询当前工作簿资料大纲与清单；
- `POST /excel/materials/bind-document`：在工作簿首次保存或另存为新文件时，原子迁移资料目录。

---

## 4. 台账生成长任务 (`excel.material_ledger`)

### 4.1 任务定义与系统提示词

- 任务标识：`excel.material_ledger`
- 系统提示词文件：`adapter_service/system_prompts/excel-material-ledger.md`
- 规则要点：
  1. 接收输入：表头列定义 `headers`、用户提取要求 `instruction`、用户补充事实 `userFacts`、冲突取舍 `conflictResolutions`、以及已召回的 DOCX 事实片段；
  2. 输出 JSON 对象：
     ```json
     {
       "schemaVersion": "excel.material_ledger.v1",
       "rows": [
         {
           "values": {
             "工作事项": "总体架构设计与方案定稿",
             "责任部门": "技术委员会",
             "完成时间": "2026年11月15日",
             "交付物验收": "《总体技术架构规范》"
           },
           "missingFields": [],
           "isDuplicate": false,
           "duplicateOfIndex": null,
           "duplicateReason": "",
           "fragmentIds": [1, 2]
         }
       ]
     }
     ```
  3. 事实核查要求：
     - 每一行必须绑定合法的 `fragmentIds`；
     - 未被资料提及的列一律为空字符串 `""`，并在 `missingFields` 数组中记录；
     - 重复检测：若某行与此前已提取的行在工作事项上高度重合，置 `isDuplicate: true`，记录 `duplicateOfIndex` 和 `duplicateReason`，但仍保留该行输出，严禁擅自合并。

### 4.2 任务接口规范

1. **提交任务**：
   - `POST /excel/material-ledger/jobs`
   - 请求体限制：64 KiB（遵循既有安全上限）；
   - 入参：
     ```json
     {
       "documentSessionId": "sess_excel_67890",
       "clientJobId": "client_uuid_xxxx",
       "headers": ["工作事项", "责任部门", "完成时间", "交付物验收"],
       "instruction": "重点梳理一期工程中的各系统交付要求",
       "userFacts": "一期预算由信息化部直接监督",
       "conflictResolutions": []
     }
     ```
   - 互斥检查：若当前工作簿正在生成或资料正在变更，返回 HTTP 409 `MATERIAL_COMPOSER_BUSY`。
2. **查询任务进度与结果**：
   - `GET /excel/material-ledger/jobs/{job_id}?documentSessionId=...`
   - 返回标准长任务信封（`queued` / `running` / `completed` / `failed` / `cancelled`），包含阶段（`preparing` -> `provider_processing` -> `parsing`）及终态结果。
3. **取消任务**：
   - `POST /excel/material-ledger/jobs/{job_id}/cancel`
   - 入参携带 `documentSessionId`，中断执行并释放协调器槽位。

---

## 5. 前端插件与任务窗格交互规范 (`wps-ai-assistant-et_1.0.0`)

### 5.1 功能区与模式定义

- 在 `ribbon.xml` 中新增「任务台账」按钮：
  ```xml
  <button id="btnAiExcelLedger" label="任务台账" size="large" getImage="GetImage" onAction="OnAction" />
  ```
- 在 `ribbon.js` 的 `resolveMode` 中映射 `btnAiExcelLedger -> "excelLedger"`。
- 在 `taskpane.html` 中新增对应模式容器 `<div id="excel-ledger-options" class="mode-block" hidden>` 与专属结果面板。

### 5.2 窗格功能区块设计

1. **资料管理卡片 (Material Strip)**：
   - 汇总统计：展示“已导入 X/5 份资料，合计 Y/100,000 字”；
   - 动作：提供「导入新资料」文件选择框，以及「复用已有资料」下拉按钮；
   - 资料列表：卡片展示每份 DOCX 名称、字数，提供「更新」与「移除」按钮；
   - 依据变更告警：若生成台账后依据资料被替换或删除，动态展示“依据资料已更新/移除”黄色警示横幅。
2. **表头设置与映射区 (Header Configuration)**：
   - 默认推荐表头：`工作事项`、`责任部门`、`完成时间`、`交付物验收`；
   - 动态标签组（Tag List）：用户可点击标签删除，或在输入框输入后回车添加自定义列名；
   - 快捷动作按钮：「从当前选区读取表头」—— 调用 `Selection` 读取当前活动行单元格文本，自动填入表头标签组。
3. **补充事实与要求区**：
   - `userFacts` 独立文本域：供用户输入权威补充事实；
   - `instruction` 文本域：供用户输入提取侧重点；
   - 冲突确认区：若检测到资料间存在事实冲突，以单选卡片呈现供用户手动裁决。
4. **结果只读预览面板 (Result Preview)**：
   - **HTML 表格视图**：根据配置的表头动态渲染表格列；
   - **缺项标灰**：空单元格渲染为带 `class="empty-cell"` 的占位符（如 `〔缺项〕`），不显示伪造内容；
   - **疑似重复提示**：重复行带有醒目的黄色警示标识 `[疑似重复]`，鼠标悬浮或点击可查看“疑似与第 X 行重复：<原因>”；
   - **出处展示**：点击任意行，可在侧栏抽屉中展开该行台账对应的原始 DOCX 文件、所属章节以及具体的物理原文引用；
   - **复制工具**：提供「复制表格 (TSV)」按钮与「复制纯文本」按钮，全程无任何写单元格动作。

---

## 6. 验证与门禁标准

### 6.1 后端自动化验证 (Python 3.8)

1. `test_excel_material_import.py`：
   - 覆盖 Excel 资料上传、超限校验（5 份 / 10 万字 / 256 列 / 10 万单元格）；
   - 覆盖跨文档资料克隆：验证克隆后资料完全独立，修改目标资料原文档不受影响；
   - 覆盖资料主动更新、移除清理与另存为文档重新绑定。
2. `test_excel_material_ledger.py`：
   - 覆盖自定义表头映射、一行一项提取验证；
   - 覆盖缺项留空断言、疑似重复行保留不合并断言；
   - 覆盖出处片段反查与虚假片段拒绝拦截；
   - 覆盖长任务生命周期（提交、轮询、取消、重开幂等恢复）。

### 6.2 插件契约自动化验证 (Node.js)

`formal-plugin-kit/tests/excel-material-ledger.test.js`：
1. 验证表头自定义编辑与选区一键读取；
2. 验证资料导入与复用已有资料克隆交互；
3. 验证任务提交、各阶段中文提示及取消；
4. 验证结果表格渲染、缺项高亮、重复提示气泡、出处侧栏展开；
5. **只读保证核对**：断言整个生成与预览交互生命周期内，WPS 表格写入接口调用次数严格为 0；
6. 验证会话隔离与重开窗格恢复。

---

## 7. 交付与不破坏原则

- 不修改 `wps-addon` 旧原型；
- 不破坏现有 Excel 智能分析、公式助手、智能填写的既有行为与测试；
- 遵循 Python 3.8 兼容性规范与 `git diff --check`。
