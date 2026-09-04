# 格式审查：识别手工目录与披露疑似目录设计规格 (Issue #149)

- 日期：2026-09-04
- 状态：已确认，待实施
- 目标版本：`v0.26.0` Preview 当前版本线
- 相关决策：ADR-0126、Issue #143、Issue #145
- 相关基线规格：`docs/superpowers/specs/2026-09-01-v0260-smart-fill-format-review-experience-redesign-spec.md`

## 1. 背景与目标

在 PR #155（Issue #145）中，系统已经实现了对 WPS 自动目录（`TablesOfContents` 集合及 `wdFieldTOC` 字段）的识别与格式审查豁免。然而在内网公文与技术文件实际场景中，大量文档使用“纯手工排版目录”，即由人工输入的目录标题、条目编号、点引导符和尾部页码组成，未绑定任何 Word/WPS 内部字段对象。

如果将手工目录视作普通正文，会产生大量针对字体、字号、正文行距、首行缩进及 `role_mapping` 的虚假违规警报；但如果仅根据“目录”二字或单一格式外观简单豁免，又极易造成正文审查盲区，且把未经验证的模型输出作为唯一豁免证据更会打破确定性规则的安全边界。

本规格交付：
1. **可靠手工目录识别与豁免**：基于多项相互独立的确定性强证据组合（$\ge 3$ 项），建立包含标题、条目与页码的完整目录豁免区，不产生正文与角色映射问题，并在覆盖摘要中明确披露已略过数量；
2. **疑似目录披露与部分覆盖**：对具备部分目录特征（恰好 2 项证据）但证据不足以确信的连续段落区域标记为疑似目录，不产生正文虚假问题，不计为已审查或已豁免，并在结构化报告中披露无法判定原因，将整体覆盖状态置为部分（`partial`）；
3. **负例防御与模型辅助边界**：普通正文中提及“目录”、带页码的普通段落、孤立点线装饰段落不得被错误豁免；模型语义角色（`toc_title` / `toc_entry`）仅能作为辅助证据，不得单独将内容移出格式审查范围；
4. **前端与报告信息披露隔离**：任务窗格与导出报告（Markdown / JSON）分别列出已豁免目录与疑似目录，严格禁止将两者合并成“目录无问题”。

---

## 2. 强证据提取与判定算法（JS 插件层）

在 `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js` 与对应宿主插件中实现确定性证据提取与区域判定。

### 2.1 五类相互独立的确定性强证据

对文档正文段落进行扫描，为每个候选段落提取以下 5 类确定性事实证据：

1. **E1 - 目录标题（Title）**：
   - 段落纯文本经去除空格与标点后严格匹配：`/^(?:目\s*录|contents|table\s+of\s+contents)$/i`；
   - 长度限制：$\le 20$ 个字符，不包含多句正文；
   - 样式/大纲辅助：若具有 `Heading`、`Title` 样式或 `outlineLevel > 0` 可增强置信度，但以文本内容为准；
2. **E2 - 连续编号条目（Numbered Entries）**：
   - 区域内连续 $\ge 2$ 个段落开头符合层级标题或列表编号规范：
     - 中文大写编号：`一、`、`二、`、`（一）`、`（二）`；
     - 阿拉伯数字层级：`1.`、`1.1`、`1.1.1`、`1 ` 等；
     - 章节点前缀：`第[一二三四五六七八九十0-9]+[章节篇部分]`、`附录\s*[A-Z0-9]`；
3. **E3 - 点引导符/引导线（Dot Leader）**：
   - 段落文本中包含连续点号或制表符引导特征：
     - 连续 3 个及以上点号：`\.{3,}`；
     - 连续 2 个及以上省略号或居中点：`[…···]{2,}` 或 `[._\-—]{4,}`；
     - 制表符分隔符后跟引导符：`\t[\.…·]+`；
4. **E4 - 尾部独立页码（Trailing Page Number）**：
   - 段落修剪尾部空白后，以阿拉伯数字（`\d{1,4}`）或小写罗马数字（`[ivxldcm]{1,8}`）结尾；
   - 尾部数字与前方文字之间有明确分隔（如制表符 `\t`、空格 `\s+` 或点引导符 E3）；
   - 排除带有单位的普通正文数字（如 `3000元`、`100%`、`12月`、`20台` 等）；
5. **E5 - 专用目录样式/缩进（TOC Style / Indentation）**：
   - 段落样式名称匹配目录专用样式：`/^(?:toc\s*\d+|目录\s*\d+)$/i`；
   - 或段落具有明确的大纲层级结构与级联悬挂缩进。

### 2.2 区域连续性探测与边界收敛

1. **区域生长规则**：
   - 若检测到 E1 标题段落，尝试向下吸纳后续连续出现的条目段落；
   - 若无显式 E1 标题段落，但连续出现 $\ge 2$ 个具备条目特征（E2/E3/E4/E5）的段落，同样形成候选区域；
   - 候选区域段落索引必须严格连续（例如 `[2, 3, 4, 5]`）。若中间出现不具备任何目录特征且字数 $> 30$ 的普通长正文段落，则该区域终止；
2. **三档判定门槛**：
   - **可靠手工目录（Manual TOC）**：
     - 区域整体满足**至少 3 项独立强证据**；
     - 且必须包含：尾部独立页码（E4）+ [点引导符（E3）或连续编号条目（E2）] + [目录标题（E1）或目录专用样式（E5）]；
     - 判定结果：写入 `coverage.tocRegions`，设置 `source = "manual_toc"`，`regionId = "manual-toc-{N}"`；
   - **疑似目录（Suspected TOC）**：
     - 连续 $\ge 2$ 个段落，满足**恰好 2 项独立强证据**（例如：仅有连续编号+尾部页码，无引导线且无目录标题；或仅有“目录”标题且后跟带引导点段落但无页码）；
     - 判定结果：写入 `coverage.suspectedTocRegions`，设置 `source = "suspected_toc"`，`regionId = "suspected-toc-{N}"`，并携带无法判定原因 `reason = "insufficient_evidence:..."`；
   - **普通正文（Normal Body）**：
     - 满足 $\le 1$ 项证据的段落，不形成任何目录区域，保留在常规正文审查列表中。

### 2.3 负例防御准则

- **正文内引用目录**：“请参阅第三章目录中的详细说明”——E1 不满足（非纯标题短文本），无连续条目，保持正文；
- **普通正文带有尾部数字**：“本项目预计总投资 5000 万元，预计建设周期 12”——无点引导符，无 TOC 样式，不满足连续条目组合，保持正文；
- **孤立点线装饰**：“------------------------”——无页码，无条目编号，保持正文；
- **单独出现的“目录”文字**：仅满足 E1（1项证据），缺少后续连续条目与页码，严格不产生豁免，保持正文并参与后续审查（但不作为正文产生异常样式报错，交由未映射或常规规则按普通标题处理）。

---

## 3. Python Adapter 协议与审查执行设计

### 3.1 快照协议校验（`deterministic_format_review.py`）

在 `WordFormatReviewService._normalize_coverage` 中扩展快照校验：

1. **`coverage.tocRegions` 校验**：
   - 允许的 `source` 扩展为：`{"tables_of_contents", "field", "auto_toc", "manual_toc"}`；
   - `paragraphIndexes` 保持严格的正整数列表、有限数量（$\le 500$）校验；
   - `startParagraphIndex` 与 `endParagraphIndex` 保持范围一致性校验；
2. **`coverage.suspectedTocRegions` 校验**（新增）：
   - 类型为列表，长度 $\le 64$；
   - 每个元素必须是字典，`source` 必须为 `"suspected_toc"`；
   - 必须包含合法的 `paragraphIndexes`（$\ge 1$ 个正整数，$\le 500$ 项）；
   - `startParagraphIndex` 与 `endParagraphIndex` 边界合法；
   - `reason` 为字符串（长度 $\le 120$），记录无法判定的具体原因枚举或描述；
   - 若校验失败，严格抛出 `AdapterError("DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID", ...)`。

### 3.2 规则隔离与覆盖状态流转（`format_reviewer.py`）

1. **双映射提取**：
   - 从 `coverage.tocRegions` 提取 `exemption_map`（包含自动目录与可靠手工目录）：
     - 角色映射为 `toc_title`（若为标题索引）或 `toc_entry`；
     - 审查执行时，跳过这些段落的字体、字号、段落样式、行距、缩进以及 `structure.role_mapping` 问题；
     - 计入 `summary.exemptedTocRegionCount` 与 `summary.exemptedTocParagraphCount`；
     - 生成摘要：`summary.tocExemptionSummary = "已识别并略过目录：{X} 个区域，共 {Y} 段"`；
   - 从 `coverage.suspectedTocRegions` 提取 `suspected_map`：
     - 审查执行时，**过滤掉**由这些段落产生的正文格式问题（避免产生字体、字号、样式的虚假误报）；
     - **严格不计入** `exemptedTocRegionCount` 和 `exemptedTocParagraphCount`，不标记为已审查，不计入合格率分母；
     - 计入 `summary.suspectedTocRegionCount` 与 `summary.suspectedTocParagraphCount`；
     - 生成摘要：`summary.suspectedTocSummary = "发现疑似目录：{M} 个区域，共 {N} 段（证据不足，未审查未豁免）"`；
2. **覆盖状态（Coverage Status）自动流转**：
   - 当 `suspectedTocRegionCount > 0` 且原 `coverageStatus` 为 `"complete"` 时：
     - 自动降级为 `coverageStatus = "partial"`（部分覆盖）；
     - `summary.coverageReason = "存在无法判定的疑似目录区域，未纳入正式审查或豁免"`；
3. **模型辅助角色防线**：
   - 若模型返回某一未豁免段落的分类为 `toc_title` 或 `toc_entry`：
     - 不得单独将该段落转移至 `exemption_map`；
     - 模型结果仅记录在 AI 语义诊断 `aiDiagnostics` 中；
     - 保证只有确定性强证据（自动目录或 $\ge 3$ 项手工特征）才能真正建立豁免。

---

## 4. UI 任务窗格与导出报告展现

### 4.1 任务窗格概览（`presentDeterministicFormatReviewIssueView`）

- 顶部概览区域独立展示状态与目录行：
  ```text
  覆盖状态：部分
  已识别并略过目录：1 个区域，共 18 段
  发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）
  问题数量：0
  ```
- 若不存在已豁免目录或疑似目录，对应行不展示；
- 严格禁止将已豁免目录与疑似目录合并显示为单行或“目录无问题”；
- 零问题提示：
  - 当无问题且存在疑似目录时，清晰提示：“当前筛选范围未发现需要调整的格式问题。因存在疑似目录，覆盖状态为‘部分’，零问题不代表文档完全合规。”

### 4.2 Markdown 报告导出（`renderReadableDeterministicFormatReview`）

在 Markdown 格式报告的头部元数据列表中：
```markdown
# 格式审查报告

- 审查状态：已完成
- 合规结论：待人工核对
- 覆盖状态：部分
- 语义增强：已增强
- 审查依据：技术文件格式规范
- 规则版本：v1.0.0
- 问题数量：0
- 已识别并略过目录：1 个区域，共 18 段
- 发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）
- 提示说明：文档中包含证据不足的疑似目录区域，已避免正文格式误报，但未建立审查豁免，请人工核验。
```

### 4.3 JSON 导出结构

在导出 JSON 的 `summary` 和 `coverage` 节点中，完整保留：
- `exemptedTocRegionCount`: 整数
- `exemptedTocParagraphCount`: 整数
- `tocExemptionSummary`: 字符串
- `suspectedTocRegionCount`: 整数
- `suspectedTocParagraphCount`: 整数
- `suspectedTocSummary`: 字符串
- `coverage.tocRegions`: 包含 `manual_toc` 对象的数组
- `coverage.suspectedTocRegions`: 包含疑似区域详情及原因的数组

---

## 5. 测试计划（遵循 TDD 铁律）

### 5.1 Node.js 插件契约测试（`formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`）
1. 包含标题、连续编号、点引导符与尾部页码的标准手工目录：正确识别为 `manual_toc` 区域并进入 `coverage.tocRegions`；
2. 无标题但包含 TOC 样式、点引导符与页码的手工目录：正确识别为 `manual_toc`；
3. 仅有编号与页码但无点引导符且无标题的连续段落：正确识别为 `suspectedTocRegions`，标记对应原因；
4. 仅有“目录”二字且后跟点引导符但无明确页码的段落：正确识别为 `suspectedTocRegions`；
5. 普通正文引用“目录”、普通带数字段落、孤立点线段落：严格不生成任何 `tocRegions` 或 `suspectedTocRegions`；
6. 任务窗格视图解析与 Markdown 导出：正确呈现独立的豁免行与疑似行，部分覆盖状态及提示文案正确。

### 5.2 Python Adapter 单元与集成测试（`adapter_service/tests/test_format_review_manual_and_suspected_toc.py`）
1. 快照协议校验：测试 `manual_toc` 与 `suspected_toc` 合法输入通过，非法 source 或字段类型报错；
2. 手工目录审查执行：`manual_toc` 区域内段落不报字体、字号、段落样式或 `structure.role_mapping` 问题，正确统计豁免数量；
3. 疑似目录审查执行：`suspected_toc` 区域内段落不报正文问题，但 `exemptedTocRegionCount` 为 0，`suspectedTocRegionCount` 正确，`coverageStatus` 变为 `partial`；
4. 模型辅助角色隔离：模型单独返回 `toc_title` 或 `toc_entry` 时，无确定性证据依然不予豁免；
5. 负例回归：普通正文、标题、图表题注、附录和注释的正常规则检测不受影响。

### 5.3 交付审计与全量回归
- 运行所有 Node 插件测试（`formal-plugin-kit/tests/*.test.js`）；
- 运行 Python 格式审查测试；
- 检查 `git diff --check`。
