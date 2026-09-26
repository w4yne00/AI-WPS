# Word：支持多份长资料编写章节设计规格 (Issue #233)

- 日期：2026-09-24
- 状态：已确认，待实施
- 目标版本：`v0.26.0` Preview 当前版本线
- 关联 Issue：#233、#229（Parent）、#231（Prerequisite）、#232
- 关联决策：ADR-0117、ADR-0131、ADR-0132

---

## 1. 背景与目标

在 Issue #231 中，系统实现了单份可容纳于单次模型输入 DOCX 资料的章节草稿生成与引用核对；在 Issue #232 中，实现了确认后将草稿插入光标或替换选区的受控写入机制。

在实际政企业务场景中，撰写技术方案、实施大纲、工作报告时，通常需要综合参考多份参考资料（例如：项目招标文件、前期立项可研、行业规范、历史会议纪要等），文字规模可达数万乃至接近十万字。此类场景面临如下核心挑战：
1. **输入容量与安全超限**：单份或多份资料接近十万字时，远超大多数模型单次调用的安全上下文预算；系统既不能静默截断资料造成事实断章取义，也不能无边界接收导致服务器内存或网络崩溃。
2. **多资料目录梳理与跨章节复用**：多次生成不同章节时，若每次都让用户重新选择、上传并解析所有文件，将带来极差的用户体验和不必要的计算开销；必须在当前文档会话中建立可复用的资料目录与片段索引。
3. **真实原文追溯性与依据防伪**：生成内容必须严格以提取出的**真实原文片段**为依据，严禁通过模型中间摘要伪造引文出处；出处必须能够清晰追溯到源文件名、章节及原文。
4. **长耗时执行与取消安全性**：从多份长资料中提取原文并生成草稿耗时较长，系统必须分段展示清晰的执行阶段，支持用户运行中随时取消；且取消或失败的任务**绝对不产生任何可写结果**。

本规格依据 Issue #233 验收标准，为 Word 任务窗格及 Adapter 建立完整的“多份长资料章节编写”架构与实施规范。

---

## 2. 容量门禁、多资料管理与目录模型

### 2.1 容量与安全门禁

所有输入在进入处理流水线前，严格执行以下前置校验：
1. **文件数量上限**：单文档会话（`documentSessionId`）内最多支持 **5 份** DOCX 文件。
   - 若尝试导入第 6 份文件，立即返回 HTTP 400 `MATERIAL_COUNT_OVER_LIMIT`，错误信息明确说明上限，不破坏已有文件。
2. **累计可读文字上限**：多份资料累计可读字数上限为 **100,000 字**（按已锁定的 `unicode_codepoints_of_extracted_readable_text` 统计口径）。
   - 若单份或累计字数超过 100,000 字，立即返回 HTTP 413 `MATERIAL_TEXT_OVER_LIMIT`，错误信息明确说明“超过本阶段实施参数上限，已拒绝导入，未截断内容”。**绝对不静默截断**。
3. **既有安全与结构防卫**：
   - 每份文件独立经过 `validate_docx_bytes` 安全检查（包大小、解压比、XML 实体炸弹防御）；
   - 累计表格列数上限 256 列，累计展开单元格上限 100,000 个（`MATERIAL_TABLE_OVER_LIMIT`）。

### 2.2 会话资料目录（`MaterialCatalog`）结构

在 Adapter 内存中，以 `documentSessionId` 维护会话级资料目录：

```python
class MaterialCatalog:
    document_session_id: str
    documents: List[MaterialDocumentSummary]  # 各文件元数据 (materialId, fileName, characterCount, importedAt 等)
    toc: List[CatalogTocEntry]                # 汇总层级大纲
    fragments: Dict[str, MaterialFragment]    # 全局片段字典，以 fragmentId 为索引
    limits: CatalogLimitsSummary              # 当前份数、累计字数、参数说明
```

- **`CatalogTocEntry`（大纲项）**：
  - `fileId` / `materialId`：所属资料标识；
  - `fileName`：所属文件名；
  - `headingLevel`：标题层级（1~6）；
  - `sectionTitle`：标题纯文本；
  - `blockId`：对应的块标识；
  - `fragmentIds`：属于该章节下属的片段 ID 列表。
- **`MaterialFragment`（片段模型）**：
  - `fragmentId`：全局唯一片段编号；
  - `text`：不可篡改的原文纯文本；
  - `blockId`：所属块标识；
  - `source`：包含 `fileName`、`section`、`bodyPath`、`part`、`blockIndex`。

### 2.3 资料跨章节复用与累加导入机制

1. **累加导入（Incremental Import）**：
   - 用户可一次性或多次选择 DOCX 导入。
   - `POST /word/materials` 接收到相同 `documentSessionId` 的请求时，若当前份数 $< 5$ 且累计字数 $+ \text{newCount} \le 100,000$，将新文件解析并入当前会话的 `MaterialCatalog`。
2. **目录跨章节复用**：
   - 建立好的目录在当前文档会话生命周期内常驻。
   - 用户撰写完“第一章”后，继续提交“第二章”任务，只需携带当前 `documentSessionId`，后端直接复用内存中已索引的 `MaterialCatalog`，无需重新传输文件或重新解析。
3. **会话隔离与生命周期**：
   - 切换活动文档时，前端自动绑定新文档的 `documentSessionId`，拉取对应文档的资料集与草稿状态；
   - Adapter 重启后，会话目录失效，系统提示用户重新导入，不产生静默空指针或虚假成功。

---

## 3. 长资料原文提取算法与模型预算

### 3.1 模型上下文预算判定

长任务执行前，调用 `direct_model_input_budget(contextWindowTokens, maxOutputTokens)` 获取当前配置模型可安全接收的输入 Token 上限 $B_{\text{input}}$：
1. **预算充足分支**：若全量片段的估算 Token 总量 $\le B_{\text{input}}$，直接将全部原始片段作为参考资料提供给模型；
2. **超预算提取分支**：若全量片段超过预算（十万字典型约为 12~15 万 Token），触发本地确定性**相关原文提取器**。

### 3.2 确定性相关原文提取算法（Deterministic Excerpt Extractor）

算法严格遵循“**生成依据必须为真实原文，绝不以模型摘要代替原文**”的铁律：

```
输入：sectionTitle（章节标题）, instruction（要求）, catalog（目录）, budget（Token预算）
输出：selected_fragments（按物理出现顺序重排的原始片段列表）
```

1. **大纲标题命中加权（Heading Match）**：
   - 对 `sectionTitle` 提取分词与短语，与 `catalog.toc` 中各级标题比对；
   - 标题命中的章节，其下属全部段落与表格片段获得高优先级权重（权重加成 $W_{\text{toc}} = 3.0$）；
2. **词法相关性评分（Lexical Match）**：
   - 对 `sectionTitle` 与 `instruction` 进行词频特征提取，构建查询特征项；
   - 遍历各片段文本，计算词频命中密度得分 $S_{\text{lexical}}$；表格行内容独立计算；
3. **上下文连续性窗口保持（Context Continuity）**：
   - 对综合得分最高的片段（Top-K），自动将其前后相邻的 1~2 个上下文片段（同一章节内部）赋予继承得分，确保进入模型的段落不是单句破碎文字，保留上下文论述结构；
4. **贪心装箱与物理保序（Greedy Packing & Physical Ordering）**：
   - 综合得分排序后，按贪心策略依次装入候选集，直至累计 Token 达到安全阈值（$0.85 \times B_{\text{input}}$，预留系统提示词与输入信封空间）；
   - 将选出的片段集**按原始在文档中的物理出现先后顺序重新排列**，保持原文语义展开逻辑；
5. **纯正原文约束**：
   - 送入模型提示词的每个片段，其内容必须是 DOCX 原文字符串，不得经过任何预改写或总结，保留原始 `fragmentId`。

### 3.3 模型输出信封与缺项规范

模型系统提示词（`adapter_service/system_prompts/word-material-composer.md`）严格规定输出格式：

```json
{
  "paragraphs": [
    {
      "text": "正文内容...〔待补充：具体缺项〕",
      "fragmentIds": ["frag-1", "frag-2"],
      "missingItems": ["具体缺项"]
    }
  ]
}
```

- **真实出处强制核验**：
  - 后端在解析模型结果时，校验段落中引用的每一个 `fragmentId` 必须属于本次提取并送给模型的原始片段集合；
  - 段落没有有效出处（`fragmentIds` 为空）且未声明 `missingItems` 时，判定为模型胡编，立即抛出 `MATERIAL_COMPOSER_INVALID_RESULT`（502）并拒绝展示；
  - 存在缺项时，正文自动规范化为约定的 `〔待补充：...〕` 标记。

---

## 4. 后台长任务分段阶段、取消与双运行时接口

### 4.1 任务阶段推进与语义

长任务由 `LongTaskCoordinator` 统一管理，执行过程中推进并上报如下阶段：

| 阶段标识 (`phase`) | 用户感知标签 (`phaseLabel`) | 核心行为 |
| :--- | :--- | :--- |
| `preparing` | 正在校验任务与资料... | 检查入参格式、核验会话目录、解析模型配置与鉴权 |
| `extracting` | 正在检索与章节相关的资料原文... | 计算模型预算，执行确定性大纲与词法加权原文片段提取 |
| `provider_processing` | 正在依据原文编写章节草稿... | 发起上游 LLM 调用，记录网络耗时，挂载取消回调 |
| `parsing` | 正在核对草稿出处与待补充项... | 校验段落 JSON、核对 fragmentIds 真实性、关联文件名与引文 |

### 4.2 运行中取消与失败防护硬性门禁

1. **取消即时中断**：
   - 任务在 `extracting` 或 `provider_processing` 状态时，用户均可点击“停止生成”；
   - 协调器立即置为 `stopping`，通过取消回调主动关闭底层 HTTP Socket 连接，终态收敛为 `cancelled`；
2. **不可写回硬保证（Writeback Guard）**：
   - 终态为 `cancelled`、`failed` 时，`result` 严格为 `null`；
   - 前端任务窗格在任何非 `succeeded` 状态下，严禁赋予“插入/替换”按钮可点击状态；`apply` 方法调用时执行硬性防御，抛出明确错误并拒绝写入文档。

### 4.3 双运行时接口规范（FastAPI 与 Standalone 对等）

#### 1. `POST /word/materials`
- **请求体（最大 64 KiB JSON，文件内容 Base64 承载）**：
  ```json
  {
    "fileName": "立项可研报告.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "contentBase64": "...",
    "documentSessionId": "doc-session-123"
  }
  ```
- **成功响应（200 OK）**：
  返回当前文档会话的资料集汇总及当前文件的读取视图：
  ```json
  {
    "success": true,
    "traceId": "mat_abc123",
    "taskType": "word.material_composer",
    "data": {
      "materialId": "mat_abc123",
      "fileName": "立项可研报告.docx",
      "documentSessionId": "doc-session-123",
      "catalogSummary": {
        "totalDocuments": 2,
        "totalCharacters": 45000,
        "documents": [ ... ],
        "toc": [ ... ]
      },
      "disclosure": "本次只读取正文、标题、列表和表格文字...",
      "limits": { ... }
    }
  }
  ```

#### 2. `GET /word/materials/catalog?documentSessionId=...`
- **语义**：任务窗格重开或切回文档时，查询当前会话已建立的目录和资料概览，无需重新上传文件。

#### 3. `POST /word/material-composer/jobs`
- **请求体**：
  ```json
  {
    "documentSessionId": "doc-session-123",
    "clientJobId": "composer-1727140000-xyz",
    "sectionTitle": "第三章 系统总体架构设计",
    "instruction": "根据可研中的总体架构原则编写，列出核心子系统及职责",
    "materialIds": ["mat_1", "mat_2"]
  }
  ```
  *注：`materialIds` 为可选字段；若缺省则默认采用当前会话全部已导入资料；向后兼容旧的 `materialId` 字符串入参。*
- **响应**：标准信封，返回 `jobId`、`status`（`queued`/`running`）、`phase`。

#### 4. `GET /word/material-composer/jobs/{job_id}?documentSessionId=...`
- 恢复查询任务状态、阶段与结果。

#### 5. `POST /word/material-composer/jobs/{job_id}/cancel`
- 接收 `documentSessionId`，中断任务并释放资源。

---

## 5. 任务窗格前端交互与出处呈现

### 5.1 界面布局与交互流

1. **资料集状态区**：
   - 顶部状态栏：“已导入 2/5 份资料，合计 45,000/100,000 字”；
   - “添加资料”按钮：支持选择新 `.docx` 文件追加导入；达到 5 份或 10 万字时禁用；
   - “资料目录”折叠面板：展开展示多份文件归纳出的章节树，可点击某标题快速填入“章节名称”；
2. **章节草稿编写区**：
   - 章节标题输入框（`material-section-title`）；
   - 编写要求输入框（`material-instruction`）；
   - “开始编写”按钮（`btn-material-generate`）；
   - 运行中展示当前细分阶段进度提示及“停止生成”按钮（`btn-material-cancel`）；
3. **草稿与多文件出处结果展示**：
   - 正文按段落垂直排版；
   - 每一段右侧或下方配置**出处侧栏**，明确标明：
     - `文件名`（如 `项目可行性研究.docx`）；
     - `章节路径`（如 `第二章 建设目标 / 2.1 业务架构`）；
     - `原文引用`（带引号的原文片段内容）；
     - 若有缺项，以橙色醒目标注“待补充：具体内容”。
4. **受控写入按钮**：
   - “复制正文”：将纯文本草稿复制到剪贴板；
   - “插入到文档”：仅在 `succeeded` 且有有效结果时可用，严禁在未完成、失败或取消态触发。

---

## 6. 测试与质量验证方案

### 6.1 TDD 驱动的自动化测试矩阵

测试严格贯穿公开端点、长任务状态流与前端窗格契约：

1. **容量门禁与限额测试 (`test_word_material_import.py`)**：
   - 连续导入 1~5 份文件，验证目录大纲合并正确；
   - 尝试导入第 6 份文件，断言抛出 `MATERIAL_COUNT_OVER_LIMIT`（400）；
   - 构造单份或多份累计超过 100,000 字符的测试文件，断言拒绝并返回 `MATERIAL_TEXT_OVER_LIMIT`（413），断言无截断；
   - 验证跨文件累计表格单元格超过 100,000 门禁；
2. **目录构建与跨章节复用测试 (`test_word_material_composer.py`)**：
   - 验证建立目录后，发起“第一章”任务成功生成；
   - 保持同一会话，不重新导入资料，直接发起“第二章”任务，断言直接复用已有目录并生成成功；
   - 验证跨文档会话完全隔离，文档 A 的目录绝不被文档 B 访问；
3. **确定性原文提取算法测试**：
   - 小资料场景（总 Token < 预算）：断言全部原始片段送入模型；
   - 长资料场景（总字数接近十万字超预算）：断言根据 `sectionTitle` 正确召回命中章节的原始片段，送入内容 Token 紧贴预算但严格不超限；
   - 纯正原文断言：断言送入模型的每个片段均有真实 `fragmentId` 且文本与原 DOCX 一致，无中间生成摘要；
4. **长任务生命周期与取消防护测试**：
   - 验证 `preparing` → `extracting` → `provider_processing` → `parsing` 完整阶段转换；
   - 验证在 `extracting` 和 `provider_processing` 期间发起取消，任务立即收敛为 `cancelled`；
   - 断言取消或失败任务的返回体中 `result` 严格为 `null`，前端契约测试验证写入动作被拦截；
5. **正式插件行为测试 (`formal-plugin-kit/tests/word-material-composer*.test.js`)**：
   - 多文件目录展示与统计字数计算渲染；
   - 段落出处跨文件展示；
   - 窗格重开与切换会话恢复；
   - 失败和取消下禁止写入；
6. **双运行时端点一致性测试**：
   - 验证 FastAPI 与 Standalone Adapter 对 `/word/materials`、`/word/materials/catalog`、`/word/material-composer/jobs` 的入参校验、状态码和信封完全等价。

### 6.2 真实样例核对与耗时度量规范（验收标准 4 & 5）

1. **事实核对真实测试套**：
   - 准备 1~5 份合计接近十万字的真实 DOCX 测试文档；
   - 事先由人工标注分散在正文和多个复杂表格中的核心必需事实与出处；
   - 运行真实模型测试，核对生成草稿采用的正确性及引文出处精确度；
2. **耗时度量与分别报告**：
   - 分别记录“首次梳理耗时（多文件解析与目录索引）”和“后续生成耗时（片段提取、LLM 往返与出处解析）”；
   - 真实输出各阶段实际耗时数据，绝不虚构性能达标阈值；
   - 受控模型测试（Mock）与真实模型质量验证结论分别独立报告。
