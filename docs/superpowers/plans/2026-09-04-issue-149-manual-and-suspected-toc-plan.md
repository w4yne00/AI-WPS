# 格式审查：识别手工目录与披露疑似目录实施计划 (Issue #149)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付手工目录与疑似目录的端到端识别与格式审查处理：通过 $\ge 3$ 项独立确定性强证据识别可靠手工目录并建立审查豁免区；证据不足（2 项证据）的连续区域标记为疑似目录，不产生正文问题，不计为已审查或已豁免，并在结构化报告中披露原因，将覆盖状态置为部分（`partial`）；任务窗格与导出报告分别列出已豁免与疑似目录。

**Architecture:**
- **JS 插件抽取层**：抽取 5 类确定性强证据（E1 标题、E2 编号条目、E3 点引导符、E4 独立页码、E5 TOC 专用样式），连续扫描段落探测区域并根据证据数量分级：$\ge 3$ 项强证据判定为 `manual_toc`（输出至 `coverage.tocRegions`）；恰好 2 项判定为 `suspected_toc`（输出至 `coverage.suspectedTocRegions`）；$\le 1$ 项作为普通正文。
- **Python Adapter 服务层**：校验 `manual_toc` 与 `suspectedTocRegions` 协议；`manual_toc` 完全豁免格式与未映射角色问题并统计略过数量；`suspectedTocRegions` 过滤正文规则问题避免误报，但不进入豁免统计，自动将覆盖状态置为 `partial` 并记录原因说明；模型语义角色仅作辅助记录，不能单独建立豁免。
- **展现与报告层**：任务窗格与 Markdown/JSON 导出报告独立列出“已识别并略过目录”与“发现疑似目录”，禁止合并为“目录无问题”。

**Tech Stack:** Python 3.8/FastAPI/Pydantic, WPS JS 插件 (taskpane-helpers.js), Node.js 测试套件, Pytest。

**Spec:** `docs/superpowers/specs/2026-09-04-issue-149-manual-and-suspected-toc-design.md`

## Global Constraints

- 快照协议版本维持 `word.format_review.snapshot.v2`；
- 单独出现“目录”文字、单一样式或模型判断不能单独建立目录审查豁免区；
- 疑似目录不产生正文问题，不计为已审查，不计为已豁免；
- 存在疑似目录时覆盖状态必须为 `partial`，任务页与导出报告必须独立分行展示已豁免与疑似目录；
- 本仓库 Word 插件权威源为 `formal-plugin-kit/wps-ai-assistant_1.0.0`。

---

### Task 1: Python Adapter 快照协议校验支持 `manual_toc` 与 `suspectedTocRegions`

**Files:**
- Create: `adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
- Modify: `adapter_service/app/services/word/deterministic_format_review.py:2510-2567`

**Interfaces:**
- Consumes: `word.format_review.snapshot.v2` coverage payload
- Produces: Normalized `coverage.tocRegions` (allowing `source == "manual_toc"`), `coverage.suspectedTocRegions` (with `regionId`, `source == "suspected_toc"`, `paragraphIndexes`, `startParagraphIndex`, `endParagraphIndex`, `reason`)

- [ ] **Step 1: Write the failing test**

```python
# adapter_service/tests/test_format_review_manual_and_suspected_toc.py
import unittest
import importlib.util

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.deterministic_format_review import WordFormatReviewService, AdapterError


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for format review tests")
class ManualAndSuspectedTocValidationTests(unittest.TestCase):
    def test_normalizes_manual_toc_and_suspected_toc_in_coverage(self):
        service = WordFormatReviewService()
        raw_coverage = {
            "tocRegions": [
                {
                    "regionId": "manual-toc-1",
                    "source": "manual_toc",
                    "startParagraphIndex": 2,
                    "endParagraphIndex": 4,
                    "paragraphIndexes": [2, 3, 4],
                    "titleParagraphIndex": 2,
                }
            ],
            "suspectedTocRegions": [
                {
                    "regionId": "suspected-toc-1",
                    "source": "suspected_toc",
                    "startParagraphIndex": 6,
                    "endParagraphIndex": 8,
                    "paragraphIndexes": [6, 7, 8],
                    "reason": "insufficient_evidence:missing_dot_leader_and_title",
                }
            ]
        }
        normalized = service._normalize_coverage(raw_coverage)
        self.assertEqual(len(normalized["tocRegions"]), 1)
        self.assertEqual(normalized["tocRegions"][0]["source"], "manual_toc")
        self.assertEqual(len(normalized["suspectedTocRegions"]), 1)
        self.assertEqual(normalized["suspectedTocRegions"][0]["source"], "suspected_toc")
        self.assertEqual(normalized["suspectedTocRegions"][0]["regionId"], "suspected-toc-1")

    def test_rejects_invalid_suspected_toc_source_or_indexes(self):
        service = WordFormatReviewService()
        with self.assertRaises(AdapterError):
            service._normalize_coverage({
                "suspectedTocRegions": [{"source": "invalid_source", "paragraphIndexes": [1, 2]}]
            })
        with self.assertRaises(AdapterError):
            service._normalize_coverage({
                "suspectedTocRegions": [{"source": "suspected_toc", "paragraphIndexes": [-1]}]
            })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
Expected: FAIL with `DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID` (because `"manual_toc"` is rejected by `source not in {"tables_of_contents", "field", "auto_toc"}` and `suspectedTocRegions` is not yet parsed).

- [ ] **Step 3: Write minimal implementation in `deterministic_format_review.py`**

Modify `_normalize_coverage` in `adapter_service/app/services/word/deterministic_format_review.py`:
1. Extend `AUTO_TOC_SOURCES` check for `tocRegions` to accept `"manual_toc"`:
   `if source not in {"tables_of_contents", "field", "auto_toc", "manual_toc"}:`
2. Add normalization for `suspectedTocRegions`:
```python
        suspected_regions = value.get("suspectedTocRegions")
        if suspected_regions is not None:
            if not isinstance(suspected_regions, list) or len(suspected_regions) > 64:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                    "疑似目录区域统计格式无效。",
                )
            normalized_suspected = []
            for item in suspected_regions:
                if not isinstance(item, dict):
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                        "疑似目录区域格式无效。",
                    )
                source = str(item.get("source") or "").strip()
                if source != "suspected_toc":
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                        "疑似目录区域来源不受支持。",
                    )
                raw_indexes = item.get("paragraphIndexes")
                if not isinstance(raw_indexes, list) or not raw_indexes or len(raw_indexes) > 500:
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                        "疑似目录区域必须包含有限段落序号。",
                    )
                indexes = []
                for raw_index in raw_indexes:
                    if type(raw_index) is not int or raw_index <= 0:
                        raise AdapterError(
                            "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                            "疑似目录段落序号必须是正整数。",
                        )
                    if raw_index not in indexes:
                        indexes.append(raw_index)
                raw_start = item.get("startParagraphIndex")
                raw_end = item.get("endParagraphIndex")
                start_idx = raw_start if type(raw_start) is int else indexes[0]
                end_idx = raw_end if type(raw_end) is int else indexes[-1]
                if start_idx <= 0 or end_idx <= 0 or start_idx > end_idx:
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                        "疑似目录区域边界无效。",
                    )
                normalized_suspected.append({
                    "regionId": str(item.get("regionId") or "suspected-toc-{0}".format(len(normalized_suspected) + 1))[:64],
                    "source": "suspected_toc",
                    "startParagraphIndex": start_idx,
                    "endParagraphIndex": end_idx,
                    "paragraphIndexes": indexes,
                    **({"reason": str(item["reason"])[:120]} if item.get("reason") else {}),
                })
            if normalized_suspected:
                result["suspectedTocRegions"] = normalized_suspected
```
3. In `_normalize_snapshot_structure`: copy `suspectedTocRegions` from `source_coverage` if present.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapter_service/app/services/word/deterministic_format_review.py adapter_service/tests/test_format_review_manual_and_suspected_toc.py
git commit -m "feat(word): support manual_toc and suspectedTocRegions in format review coverage validation"
```

---

### Task 2: Python Adapter 审查执行隔离（`exemption_map` 与 `suspected_map`、部分覆盖状态机与模型辅助隔离）

**Files:**
- Modify: `adapter_service/app/services/word/format_reviewer.py:80-140, 300-340, 385-420`
- Modify: `adapter_service/app/services/word/deterministic_format_review.py:1659-1665`
- Test: `adapter_service/tests/test_format_review_manual_and_suspected_toc.py`

**Interfaces:**
- Consumes: `collect_auto_toc_exemption(structure)` (to be expanded to `collect_toc_regions(structure)`)
- Produces:
  - `exemption_map`: paragraphs in `manual_toc` or auto TOC; suppresses all format and role mapping issues; counted in `exemptedTocRegionCount` and `exemptedTocParagraphCount`; generates `tocExemptionSummary`.
  - `suspected_map`: paragraphs in `suspectedTocRegions`; suppresses body format issues (no false positives); not counted in `exemptedTocParagraphCount`; generates `suspectedTocSummary`; triggers `coverageStatus = "partial"`.
  - Model role isolation: model returning `toc_title` / `toc_entry` without deterministic coverage evidence does not exempt paragraphs.

- [ ] **Step 1: Write the failing test**

In `adapter_service/tests/test_format_review_manual_and_suspected_toc.py`:
- Test manual TOC region does not emit format or unmapped role issues and is counted as exempted.
- Test suspected TOC region does not emit body formatting issues, is NOT counted as exempted, produces `suspectedTocSummary`, and sets `coverageStatus = "partial"`.
- Test model-only `toc_entry` without snapshot TOC structure cannot exempt paragraph.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
Expected: FAIL (because `format_reviewer.py` currently only recognizes `AUTO_TOC_SOURCES` and has no `suspected_map` / `suspectedTocSummary`).

- [ ] **Step 3: Write minimal implementation**

In `adapter_service/app/services/word/format_reviewer.py`:
1. Expand `AUTO_TOC_SOURCES = {"tables_of_contents", "field", "auto_toc", "manual_toc"}`
2. Add helper `format_suspected_toc_summary(region_count, paragraph_count)`:
   `return "发现疑似目录：{0} 个区域，共 {1} 段（证据不足，未审查未豁免）".format(region_count, paragraph_count)`
3. Add helper `collect_suspected_toc(structure)` returning `suspected_map: Dict[int, Dict]` and `suspected_regions: List[Dict]`.
4. In `review()` and `_review_paragraphs()`:
   - Filter `issues = [issue for issue in issues if issue.paragraph_index not in exemption_map and issue.paragraph_index not in suspected_map]`
   - Exclude `suspected_map` from `_paragraphs_for_review`:
     `if paragraph.index in exemption_map or paragraph.index in suspected_map: continue`
   - In `summary`:
     ```python
     if accepted_suspected_regions:
         summary["suspectedTocRegionCount"] = len(accepted_suspected_regions)
         summary["suspectedTocParagraphCount"] = len(suspected_map)
         summary["suspectedTocSummary"] = format_suspected_toc_summary(
             len(accepted_suspected_regions), len(suspected_map)
         )
         summary["coverageStatus"] = "partial"
         summary["coverageReason"] = "存在疑似目录区域，因证据不足未纳入审查与豁免范围"
     ```
5. In `deterministic_format_review.py`: in `_summarize_report`, copy `suspectedTocRegionCount`, `suspectedTocParagraphCount`, and `suspectedTocSummary` into `coverage` if present.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapter_service/app/services/word/format_reviewer.py adapter_service/app/services/word/deterministic_format_review.py adapter_service/tests/test_format_review_manual_and_suspected_toc.py
git commit -m "feat(word): implement manual toc exemption, suspected toc suppression, and partial coverage in format reviewer"
```

---

### Task 3: JS 插件层特征证据提取器与多证据组合判定算法

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js:4045-4210, 4290-4310`
- Create: `formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`

**Interfaces:**
- Consumes: WPS document Paragraphs and document structure
- Produces:
  - `collectWordManualAndSuspectedTocRegions(document)` (integrated into `collectFormatReviewCoverage`):
    - `coverage.tocRegions`: includes `manual_toc` regions with $\ge 3$ strong independent evidences;
    - `coverage.suspectedTocRegions`: includes `suspected_toc` regions with 2 strong evidences;
    - Negative cases: normal text referencing "目录", normal paragraphs ending with numbers, isolated lines without TOC characteristics produce neither.

- [ ] **Step 1: Write the failing test**

```javascript
// formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js
const assert = require("assert");
const path = require("path");
const { wordRoot } = require("./support/plugin-roots");
const helpers = require(path.join(wordRoot, "taskpane-helpers.js"));

function para(index, text, styleName) {
  return {
    ParagraphIndex: index,
    paragraphIndex: index,
    Text: text,
    text: text,
    StyleName: styleName || "Normal",
    styleName: styleName || "Normal",
    Range: { paragraphIndex: index, ParagraphIndex: index, Text: text }
  };
}

function testIdentifiesReliableManualTocWithTitleEntriesAndDots() {
  const document = {
    Paragraphs: [
      para(1, "总体方案", "Title"),
      para(2, "目录", "Heading 1"),
      para(3, "一、概述...........................1", "Normal"),
      para(4, "二、建设目标.......................5", "Normal"),
      para(5, "三、总体架构.......................12", "Normal"),
      para(6, "正文第一章 概述")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 1);
  assert.strictEqual(result.manualTocRegions[0].source, "manual_toc");
  assert.deepStrictEqual(result.manualTocRegions[0].paragraphIndexes, [2, 3, 4, 5]);
  assert.strictEqual(result.manualTocRegions[0].titleParagraphIndex, 2);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}

function testIdentifiesSuspectedTocWhenEvidenceInsufficient() {
  // Only 2 evidences: numbered entries + trailing numbers, but no dot leaders and no title
  const document = {
    Paragraphs: [
      para(1, "一、概述 1"),
      para(2, "二、目标 5"),
      para(3, "正文内容")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 1);
  assert.strictEqual(result.suspectedTocRegions[0].source, "suspected_toc");
  assert.deepStrictEqual(result.suspectedTocRegions[0].paragraphIndexes, [1, 2]);
}

function testNegativeCasesDoNotProduceTocRegions() {
  const document = {
    Paragraphs: [
      para(1, "本规范请参见详细目录中的说明。"),
      para(2, "项目采购清单第 1 项合计 3000 元。"),
      para(3, "----------------------------------"),
      para(4, "普通正文段落。")
    ]
  };
  const result = helpers.collectWordManualAndSuspectedTocRegions(document);
  assert.strictEqual(result.manualTocRegions.length, 0);
  assert.strictEqual(result.suspectedTocRegions.length, 0);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`
Expected: FAIL with `helpers.collectWordManualAndSuspectedTocRegions is not a function`.

- [ ] **Step 3: Write minimal implementation in `taskpane-helpers.js`**

1. Implement `extractParagraphTocEvidence(text, styleName)`:
   - `isTitle`: `/^(?:目\s*录|contents|table\s+of\s+contents)$/i.test(normalizedText) && normalizedText.length <= 20`
   - `hasNumber`: `/^(?:第[0-9一二三四五六七八九十]+[章节篇部分]|(?:[0-9]+(?:\.[0-9]+)*|[一二三四五六七八九十]+|[（(][0-9一二三四五六七八九十]+[)）])(?:\s*、|\s*[\.．]|\s+)|附录\s*[A-Z0-9])/i.test(text.trim())`
   - `hasDots`: `/(?:\.{3,}|[…···]{2,}|[._\-—]{4,}|\t[\.…·]+)/.test(text)`
   - `hasPage`: `/(?:[\t\s]+|\.{2,}|[…·]{2,})(\d{1,4}|[ivxldcm]{1,8})$/i.test(text.trim()) && !/[元%月台套个份本项篇条次户只辆箱包袋张顶座件]$/.test(text.trim())`
   - `hasTocStyle`: `/^(?:toc\s*\d+|目录\s*\d+)$/i.test(styleName || "")`
2. Implement `collectWordManualAndSuspectedTocRegions(document)`:
   - Detect continuous blocks of paragraphs with potential TOC characteristics;
   - Evaluate region evidence:
     - `evCount`: count of independent evidences across the region (E1 title, E2 numbered entries, E3 dot leaders, E4 trailing pages, E5 TOC style);
     - Reliable manual TOC: `evCount >= 3 && hasPage && (hasDots || hasNumber) && (hasTitle || hasTocStyle)`;
     - Suspected TOC: `evCount === 2 && paragraphs.length >= 2`;
     - Filter out regions overlapping with already recognized `auto_toc` regions.
3. Integrate into `collectFormatReviewCoverage`:
   - Append `manualTocRegions` to `coverage.tocRegions`;
   - If `suspectedTocRegions.length > 0`, set `coverage.suspectedTocRegions = suspectedTocRegions`.
4. Export function on `helpers` / `window`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js
git commit -m "feat(word): implement manual toc and suspected toc evidence detection in plugin helpers"
```

---

### Task 4: UI 任务窗格与导出报告（Markdown / JSON）分列展现

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js:2835-2855, 3170-3185`
- Modify: `adapter_service/app/services/word/deterministic_format_review.py:1460-1465`
- Test: `formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`
- Test: `adapter_service/tests/test_format_review_manual_and_suspected_toc.py`

**Interfaces:**
- Consumes: `summary.tocExemptionSummary`, `summary.suspectedTocSummary`, `summary.coverageStatus == "partial"`
- Produces:
  - Taskpane previewText displays separate lines for exempted and suspected TOC.
  - Markdown report displays separate lines and explains partial coverage.
  - Prohibition of combining into "目录无问题".

- [ ] **Step 1: Write the failing test**

Add tests to `format-review-manual-and-suspected-toc.test.js`:
```javascript
function testPresentsSeparateExemptedAndSuspectedTocInTaskpane() {
  const view = helpers.presentDeterministicFormatReviewIssueView({
    summary: {
      coverageStatus: "partial",
      tocExemptionSummary: "已识别并略过目录：1 个区域，共 18 段",
      suspectedTocSummary: "发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）"
    },
    issues: []
  });
  assert.ok(view.previewText.includes("已识别并略过目录：1 个区域，共 18 段"));
  assert.ok(view.previewText.includes("发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）"));
  assert.ok(view.previewText.includes("覆盖状态：部分"));
  assert.ok(!view.previewText.includes("目录无问题"));
}

function testRendersSeparateTocLinesInReadableMarkdownReport() {
  const markdown = helpers.renderReadableDeterministicFormatReview({
    summary: {
      coverageStatus: "partial",
      executionStatus: "completed",
      complianceStatus: "passed",
      tocExemptionSummary: "已识别并略过目录：1 个区域，共 18 段",
      suspectedTocSummary: "发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）"
    },
    issues: []
  });
  assert.ok(markdown.includes("已识别并略过目录：1 个区域，共 18 段"));
  assert.ok(markdown.includes("发现疑似目录：1 个区域，共 4 段（证据不足，未审查未豁免）"));
  assert.ok(markdown.includes("覆盖状态：部分"));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`
Expected: FAIL (because `suspectedTocSummary` is not yet rendered).

- [ ] **Step 3: Write minimal implementation**

1. In `taskpane-helpers.js`:
   - In `presentDeterministicFormatReviewIssueView`:
     - Read `suspectedTocSummary` and insert after `tocExemptionSummary` in `previewLines`;
     - If `summary.coverageStatus === "partial"` and `issues.length === 0`, update empty message to note that zero issues does not equal full compliance due to partial coverage.
   - In `renderReadableDeterministicFormatReview`:
     - If `summary.suspectedTocSummary`, add `- ` + `summary.suspectedTocSummary`.
     - Add warning note about suspected TOC when `summary.suspectedTocSummary` is present.
2. In `adapter_service/app/services/word/deterministic_format_review.py`:
   - In `_render_readable_report_markdown`:
     - Include `summary.suspectedTocSummary` if present.

- [ ] **Step 4: Run test to verify it passes**

Run: `node formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js`
Run: `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_manual_and_suspected_toc.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js adapter_service/app/services/word/deterministic_format_review.py formal-plugin-kit/tests/format-review-manual-and-suspected-toc.test.js adapter_service/tests/test_format_review_manual_and_suspected_toc.py
git commit -m "feat(word): display separate exempted and suspected toc lines in taskpane and markdown reports"
```

---

### Task 5: 交付闭包、交付文档更新与完整全量回归

**Files:**
- Modify: `docs/codex-handoff.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: Update documentation and glossary**
  - Update `CONTEXT.md`:
    - Refine `目录审查豁免区` definition to include reliable manual TOC identified through $\ge 3$ independent strong evidences.
    - Add `疑似目录区域` definition (consecutive area with partial evidence, not reviewed, not exempted, causing partial coverage).
  - Update `docs/codex-handoff.md` with Issue #149 implementation status and boundaries.

- [ ] **Step 2: Run all regression suites**
  - Run all Node tests:
    `for file in formal-plugin-kit/tests/*.test.js; do node "$file" || exit 1; done`
  - Run Python compileall:
    `python3 -m compileall -q adapter_service/app`
  - Run Python tests:
    `PYTHONPATH=adapter_service python3 -m pytest -q adapter_service/tests/test_format_review_*.py`
  - Run git diff check:
    `git diff --check`

- [ ] **Step 3: Commit**

```bash
git add docs/codex-handoff.md CONTEXT.md
git commit -m "docs: record manual and suspected toc implementation in handoff and context"
```
