# Excel Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Excel workflow, "Excel 智能分析", with read-only analysis of selected range or active worksheet used range, model-backed structured and plain report output, host-separated Word/Excel Ribbon entries, and one combined delivery package.

**Architecture:** Add a new `/excel/analysis` adapter API and `excel.analysis` provider task while preserving existing Word routes. Add an Excel-specific WPS `et` add-in package with only `Excel 智能分析` and `设置`, sharing the same task pane/settings code style and adapter configuration. Package both Word and Excel add-ins into one installer that overwrites older Word-only installs while preserving runtime API URL and API keys.

**Tech Stack:** WPS JS/HTML add-ins for Linux WPS Writer and Spreadsheets, Python FastAPI adapter with standalone fallback, Pydantic request/response models, enterprise Dify-compatible `/chat-messages`, Node static smoke tests, Python `unittest`, existing bash packaging scripts.

---

## Scope Notes

- Implement `docs/superpowers/specs/2026-06-26-excel-analysis-design.md`.
- Do not change Word Smart Write, Smart Imitation, Document Review, Format Review, or any Word writeback behavior.
- Excel Analysis first version is read-only: no cell writeback, no new worksheet, no formula modification, no chart or pivot generation.
- Target release version: `0.15.0-alpha`.
- Target rule number: `AI-WPS-P1-WORD-EXCEL-0.15.0-20260626`.
- Current working tree contains historical delivery package noise. Do not revert or stage unrelated package deletions or untracked old tarballs.

## File Structure

Create:

- `adapter_service/app/api/excel.py`: Excel FastAPI routes.
- `adapter_service/app/services/excel/__init__.py`: Excel service package marker.
- `adapter_service/app/services/excel/analyzer.py`: Excel analysis validation, local summaries, provider call, fallback shaping.
- `adapter_service/tests/test_excel_analysis.py`: service-level and parser tests.
- `docs/operations/dify-excel-analysis-workflow.md`: operations guide for the Excel analysis model workflow.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/`: Excel-specific add-in folder.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`: Excel-only Ribbon.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js`: Excel-only Ribbon action map.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json`: Excel add-in manifest.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html`: Excel add-in entry page.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`: Excel task pane page, copied from current task pane and reduced to Excel Analysis + Settings.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`: Excel task pane behavior.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`: shared visual style copy for Excel package.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`: shared safe rendering helpers copy for Excel package.
- `formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/`: Excel icon assets.

Modify:

- `adapter_service/app/core/models.py`: add Excel request/response models.
- `adapter_service/app/main.py`: include Excel router and map validation debug task type.
- `adapter_service/app/services/provider_client.py`: add `excel.analysis` task status, prompt builder, parser, provider method.
- `adapter_service/standalone_adapter.py`: add standalone `/excel/analysis`.
- `adapter_service/tests/test_enterprise_provider.py`: provider prompt/task-key tests.
- `adapter_service/tests/test_review_mode_contract.py`: task key ordering and route diagnostics tests.
- `adapter_service/tests/test_health.py`: version assertion.
- `adapter_service/tests/test_packaging_scripts.py`: dual add-in and publish.xml packaging tests.
- `config/adapter.example.json`: add `excel.analysis`.
- `formal-plugin-kit/tests/layout-smoke.test.js`: assert Word package stays Word-only and Excel package is Excel-only.
- `phase1-delivery-kit/wps-jsaddons/publish.xml`: include both `wps` and `et` add-in entries.
- `phase1-delivery-kit/installer/install_phase1.sh`: install both add-in folders and merge both publish entries while preserving other add-ins.
- `packaging/build_phase1_delivery_kit.sh`: package both add-in folders and Excel Dify guide.
- Version-bearing files: `README.md`, `README-ZH.md`, `docs/codex-handoff.md`, `adapter_service/app/api/health.py`, `adapter_service/app/main.py`, `adapter_service/app/services/provider_client.py`, `adapter_service/standalone_adapter.py`, `adapter-start-kit/scripts/start_uvicorn_adapter.sh`, Word and Excel manifests/taskpane cache tokens/ribbon build tokens, version-related tests.

## Task 1: Excel Models, Provider Contract, And Parsing

**Files:**
- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/tests/test_review_mode_contract.py`
- Modify: `config/adapter.example.json`

- [ ] **Step 1: Write failing provider and model tests**

Add imports in `adapter_service/tests/test_enterprise_provider.py`:

```python
from app.core.models import ExcelAnalysisRequest
from app.services.provider_client import build_excel_analysis_prompt, parse_excel_analysis_answer
```

Add these tests to `EnterpriseProviderTests`:

```python
def test_excel_analysis_request_accepts_table_payload(self):
    request = ExcelAnalysisRequest.parse_obj(
        {
            "workbookId": "analysis.xlsx",
            "scene": "excel",
            "scope": {
                "type": "selection",
                "sheetName": "经营数据",
                "address": "A1:D4",
            },
            "table": {
                "headers": ["月份", "部门", "金额", "状态"],
                "rows": [
                    ["2026-01", "市场部", "120000", "已完成"],
                    ["2026-02", "市场部", "98000", "进行中"],
                ],
                "rowCount": 2,
                "columnCount": 4,
                "truncated": False,
            },
            "options": {"analysisRequirement": "关注金额变化和异常项。"},
        }
    )

    self.assertEqual(request.scene, "excel")
    self.assertEqual(request.scope.sheet_name, "经营数据")
    self.assertEqual(request.scope.address, "A1:D4")
    self.assertEqual(request.table.headers[0], "月份")
    self.assertEqual(request.options.analysis_requirement, "关注金额变化和异常项。")
```

```python
def test_build_excel_analysis_prompt_includes_range_headers_requirement_and_constraints(self):
    request = ExcelAnalysisRequest.parse_obj(
        {
            "workbookId": "analysis.xlsx",
            "scene": "excel",
            "scope": {"type": "usedRange", "sheetName": "Sheet1", "address": "A1:C3"},
            "table": {
                "headers": ["项目", "金额", "状态"],
                "rows": [["项目A", "100", "正常"], ["项目B", "300", "异常"]],
                "rowCount": 2,
                "columnCount": 3,
                "truncated": True,
            },
            "options": {"analysisRequirement": "生成经营分析。"},
        }
    )

    prompt = build_excel_analysis_prompt(request)

    self.assertIn("企业表格数据分析助手", prompt)
    self.assertIn("工作表：Sheet1", prompt)
    self.assertIn("范围：A1:C3", prompt)
    self.assertIn("项目, 金额, 状态", prompt)
    self.assertIn("生成经营分析", prompt)
    self.assertIn("数据已截断", prompt)
    self.assertIn("不要声称已经修改单元格", prompt)
    self.assertIn("只基于表格数据", prompt)
```

```python
def test_parse_excel_analysis_answer_accepts_json_and_falls_back_to_text(self):
    parsed = parse_excel_analysis_answer(
        """
        ```json
        {
          "structuredReport": {
            "overview": "共 2 行数据。",
            "findings": ["金额集中在项目B。"],
            "risks": ["项目B状态异常。"],
            "actions": ["建议核查项目B。"]
          },
          "plainText": "本表显示项目B金额较高且状态异常，建议优先核查。"
        }
        ```
        """
    )

    self.assertEqual(parsed["structuredReport"]["overview"], "共 2 行数据。")
    self.assertEqual(parsed["structuredReport"]["findings"], ["金额集中在项目B。"])
    self.assertIn("项目B金额较高", parsed["plainText"])

    fallback = parse_excel_analysis_answer("### 分析结果\n项目B存在异常，建议核查。")
    self.assertIn("模型后台已返回表格分析结果", fallback["structuredReport"]["overview"])
    self.assertEqual(fallback["structuredReport"]["findings"], [])
    self.assertIn("项目B存在异常", fallback["plainText"])
```

```python
def test_excel_analysis_uses_independent_task_type_and_task_key(self):
    class CapturingProviderClient(ProviderClient):
        def __init__(self):
            super().__init__(AppSettings())
            self.calls = []

        def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
            return True

        def post_task(self, task_type, trace_id, input_data, query, timeout_seconds=None):
            self.calls.append(
                {
                    "taskType": task_type,
                    "traceId": trace_id,
                    "inputData": input_data,
                    "query": query,
                    "timeoutSeconds": timeout_seconds,
                }
            )
            return {
                "answer": '{"structuredReport":{"overview":"概览","findings":["发现"],"risks":[],"actions":["建议"]},"plainText":"汇报段落"}'
            }

    request = ExcelAnalysisRequest.parse_obj(
        {
            "workbookId": "analysis.xlsx",
            "scene": "excel",
            "scope": {"type": "selection", "sheetName": "Sheet1", "address": "A1:B2"},
            "table": {
                "headers": ["名称", "金额"],
                "rows": [["A", "1"]],
                "rowCount": 1,
                "columnCount": 2,
                "truncated": False,
            },
            "options": {"analysisRequirement": "生成简要分析。"},
        }
    )
    provider = CapturingProviderClient()

    result = provider.excel_analysis(request, trace_id="trace-excel-analysis")

    self.assertEqual(provider.calls[0]["taskType"], "excel.analysis")
    self.assertIn("生成简要分析", provider.calls[0]["query"])
    self.assertEqual(result["plainText"], "汇报段落")
```

Update `adapter_service/tests/test_review_mode_contract.py` task list expectations:

```python
self.assertEqual(
    list(status.keys()),
    [
        "word.smart_write",
        "word.smart_imitation",
        "word.document_review",
        "word.format_review",
        "excel.analysis",
    ],
)
self.assertEqual(status["excel.analysis"]["apiKeyRef"], "excel_analysis")
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_review_mode_contract -v
```

Expected result:

```text
ERROR because ExcelAnalysisRequest, build_excel_analysis_prompt, parse_excel_analysis_answer, and ProviderClient.excel_analysis do not exist yet.
```

- [ ] **Step 3: Add Excel models**

In `adapter_service/app/core/models.py`, add these models after `WordDocumentRequest`:

```python
class ExcelAnalysisScope(BaseModel):
    scope_type: Literal["selection", "usedRange"] = Field(default="selection", alias="type")
    sheet_name: str = Field(default="", alias="sheetName")
    address: str = ""

    @validator("scope_type", pre=True, always=True)
    def coerce_scope_type(cls, value):
        return value if value in {"selection", "usedRange"} else "selection"

    @validator("sheet_name", "address", pre=True, always=True)
    def coerce_scope_text(cls, value):
        return _safe_str(value)


class ExcelAnalysisTable(BaseModel):
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    row_count: int = Field(default=0, alias="rowCount")
    column_count: int = Field(default=0, alias="columnCount")
    truncated: bool = False

    @validator("headers", pre=True, always=True)
    def coerce_headers(cls, value):
        if not isinstance(value, list):
            return []
        return [_safe_str(item) for item in value]

    @validator("rows", pre=True, always=True)
    def coerce_rows(cls, value):
        if not isinstance(value, list):
            return []
        normalized = []
        for row in value:
            if isinstance(row, list):
                normalized.append([_safe_str(cell) for cell in row])
        return normalized

    @validator("row_count", "column_count", pre=True, always=True)
    def coerce_counts(cls, value):
        return _safe_int(value) or 0

    @validator("truncated", pre=True, always=True)
    def coerce_truncated(cls, value):
        return bool(_safe_bool(value))


class ExcelAnalysisOptions(BaseModel):
    analysis_requirement: str = Field(default="", alias="analysisRequirement")

    @validator("analysis_requirement", pre=True, always=True)
    def coerce_requirement(cls, value):
        return _safe_str(value)


class ExcelAnalysisRequest(BaseModel):
    workbook_id: str = Field(default="active-workbook", alias="workbookId")
    scene: Literal["excel"] = "excel"
    scope: ExcelAnalysisScope = Field(default_factory=ExcelAnalysisScope)
    table: ExcelAnalysisTable = Field(default_factory=ExcelAnalysisTable)
    options: ExcelAnalysisOptions = Field(default_factory=ExcelAnalysisOptions)

    @validator("workbook_id", pre=True, always=True)
    def coerce_workbook_id(cls, value):
        return _safe_str(value, "active-workbook") or "active-workbook"

    @validator("scene", pre=True, always=True)
    def coerce_excel_scene(cls, value):
        return "excel"


class ExcelStructuredReport(BaseModel):
    overview: str = ""
    findings: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)


class ExcelAnalysisResponseData(BaseModel):
    structured_report: ExcelStructuredReport = Field(alias="structuredReport")
    plain_text: str = Field(default="", alias="plainText")
    provider: str = "mock"
```

- [ ] **Step 4: Add provider prompt, parser, task key, and method**

In `adapter_service/app/services/provider_client.py`, add:

```python
def _provider_safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _json_from_markdown_or_text(text: str) -> Dict:
    stripped = strip_think_tags(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    candidate = fenced.group(1) if fenced else stripped
    return json.loads(candidate)
```

If a similar helper already exists, use one helper and keep both document review and Excel parsing tests green.

Add:

```python
def build_excel_analysis_prompt(request: ExcelAnalysisRequest) -> str:
    headers = ", ".join(request.table.headers) if request.table.headers else "未识别到表头"
    sample_lines = []
    for row in request.table.rows[:30]:
        sample_lines.append(" | ".join(_provider_safe_str(cell) for cell in row))
    sample_text = "\n".join(sample_lines) if sample_lines else "无可用样本行。"
    requirement = request.options.analysis_requirement.strip() or "请基于表格数据生成通用分析报告。"
    truncated_text = "是，数据已截断，只能基于样本和统计信息分析。" if request.table.truncated else "否。"
    return "\n".join(
        [
            "你是企业表格数据分析助手。",
            "请基于用户提交的 WPS 表格数据生成中文分析报告。",
            "",
            "工作簿：{0}".format(request.workbook_id),
            "工作表：{0}".format(request.scope.sheet_name or "未命名工作表"),
            "范围：{0}".format(request.scope.address or "未识别"),
            "范围类型：{0}".format("选区" if request.scope.scope_type == "selection" else "当前工作表已用区域"),
            "行数：{0}".format(request.table.row_count),
            "列数：{0}".format(request.table.column_count),
            "数据已截断：{0}".format(truncated_text),
            "表头：{0}".format(headers),
            "",
            "用户分析要求：",
            requirement,
            "",
            "样本数据：",
            sample_text,
            "",
            "输出要求：",
            "1. 只基于表格数据和用户分析要求，不编造不存在的事实、原因、结论或数据。",
            "2. 默认输出一个 JSON 对象，字段为 structuredReport 和 plainText。",
            "3. structuredReport 包含 overview、findings、risks、actions。",
            "4. findings、risks、actions 均为字符串数组。",
            "5. plainText 为可直接复制到 Word 或 PPT 的中文汇报段落。",
            "6. 如果数据已截断，必须说明分析基于有限样本。",
            "7. 不要输出公式，不要声称已经修改单元格，不要要求前端自动写回 Excel。",
        ]
    )
```

Add:

```python
def parse_excel_analysis_answer(answer: str) -> Dict:
    cleaned = strip_think_tags(answer or "").strip()
    try:
        parsed = _json_from_markdown_or_text(cleaned)
        report = parsed.get("structuredReport") or parsed.get("structured_report") or {}
        return {
            "structuredReport": {
                "overview": _provider_safe_str(report.get("overview")),
                "findings": [str(item) for item in report.get("findings", []) if str(item).strip()],
                "risks": [str(item) for item in report.get("risks", []) if str(item).strip()],
                "actions": [str(item) for item in report.get("actions", []) if str(item).strip()],
            },
            "plainText": _provider_safe_str(parsed.get("plainText") or parsed.get("plain_text") or cleaned),
        }
    except Exception:
        return {
            "structuredReport": {
                "overview": "模型后台已返回表格分析结果，但未按结构化 JSON 输出。",
                "findings": [],
                "risks": [],
                "actions": [],
            },
            "plainText": cleaned,
        }
```

Extend `build_task_api_key_status`:

```python
("excel.analysis", "Excel 智能分析"),
```

Add provider method:

```python
def excel_analysis(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
    prompt = build_excel_analysis_prompt(request)
    task_type = "excel.analysis"
    if not self.is_task_configured(task_type):
        logger.info("traceId=%s provider=mock task=excel.analysis", trace_id)
        self.record_unconfigured_debug(task_type, trace_id, prompt)
        return {
            "structuredReport": {
                "overview": "已读取 {0} 行、{1} 列表格数据。".format(
                    request.table.row_count,
                    request.table.column_count,
                ),
                "findings": ["请配置 Excel 智能分析模型后台后获取完整分析。"],
                "risks": [],
                "actions": ["在设置页保存 excel.analysis 的任务级 API Key。"],
            },
            "plainText": "已读取表格数据。请配置 Excel 智能分析模型后台后生成正式分析报告。",
            "provider": "mock",
            "prompt": prompt,
        }

    body = self.post_task(task_type, trace_id, {}, prompt)
    parsed = parse_excel_analysis_answer(extract_answer(body))
    logger.info("traceId=%s provider=enterprise-dify-chat task=excel.analysis", trace_id)
    return {
        **parsed,
        "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
        "prompt": prompt,
        "conversationId": body.get("conversation_id", ""),
        "messageId": body.get("message_id", ""),
    }
```

Add `excel.analysis` to `config/adapter.example.json`:

```json
"excel.analysis": "excel_analysis"
```

- [ ] **Step 5: Run provider tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_review_mode_contract -v
```

Expected result:

```text
OK
```

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add adapter_service/app/core/models.py adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_provider.py adapter_service/tests/test_review_mode_contract.py config/adapter.example.json
git commit -m "feat: add excel analysis provider contract"
```

## Task 2: Excel Service, FastAPI Route, And Standalone Route

**Files:**
- Create: `adapter_service/app/api/excel.py`
- Create: `adapter_service/app/services/excel/__init__.py`
- Create: `adapter_service/app/services/excel/analyzer.py`
- Create: `adapter_service/tests/test_excel_analysis.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`

- [ ] **Step 1: Write failing service tests**

Create `adapter_service/tests/test_excel_analysis.py`:

```python
import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import ExcelAnalysisRequest
    from app.services.excel.analyzer import ExcelAnalyzer


def parse_excel_request(payload):
    if hasattr(ExcelAnalysisRequest, "model_validate"):
        return ExcelAnalysisRequest.model_validate(payload)
    return ExcelAnalysisRequest.parse_obj(payload)


class RecordingExcelProvider:
    def __init__(self):
        self.calls = []

    def excel_analysis(self, request, trace_id):
        self.calls.append({"request": request, "traceId": trace_id})
        return {
            "structuredReport": {
                "overview": "共 2 行、3 列。",
                "findings": ["金额集中在项目B。"],
                "risks": ["项目B状态异常。"],
                "actions": ["建议核查项目B。"],
            },
            "plainText": "本表显示项目B金额较高且状态异常，建议优先核查。",
            "provider": "enterprise-dify-chat/task-file",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for excel analysis tests")
class ExcelAnalysisTests(unittest.TestCase):
    def _request(self, headers=None, rows=None, requirement="关注异常。"):
        return parse_excel_request(
            {
                "workbookId": "analysis.xlsx",
                "scene": "excel",
                "scope": {"type": "selection", "sheetName": "Sheet1", "address": "A1:C3"},
                "table": {
                    "headers": headers if headers is not None else ["项目", "金额", "状态"],
                    "rows": rows if rows is not None else [["项目A", "100", "正常"], ["项目B", "300", "异常"]],
                    "rowCount": 2,
                    "columnCount": 3,
                    "truncated": False,
                },
                "options": {"analysisRequirement": requirement},
            }
        )

    def test_excel_analysis_sends_request_to_provider(self):
        provider = RecordingExcelProvider()
        result = ExcelAnalyzer(provider_client=provider).analyze(self._request(), trace_id="trace-excel")

        self.assertEqual(provider.calls[0]["traceId"], "trace-excel")
        self.assertEqual(provider.calls[0]["request"].scope.sheet_name, "Sheet1")
        self.assertEqual(result["structuredReport"]["overview"], "共 2 行、3 列。")
        self.assertEqual(result["plainText"], "本表显示项目B金额较高且状态异常，建议优先核查。")
        self.assertEqual(result["provider"], "enterprise-dify-chat/task-file")

    def test_excel_analysis_requires_usable_table(self):
        analyzer = ExcelAnalyzer(provider_client=RecordingExcelProvider())

        with self.assertRaises(AdapterError) as missing_table:
            analyzer.analyze(self._request(headers=[], rows=[]), trace_id="trace-empty")

        self.assertEqual(missing_table.exception.code, "EXCEL_ANALYSIS_TABLE_REQUIRED")
        self.assertIn("未读取到可分析的表格数据", missing_table.exception.message)

    def test_excel_analysis_allows_empty_requirement(self):
        provider = RecordingExcelProvider()

        result = ExcelAnalyzer(provider_client=provider).analyze(
            self._request(requirement=""),
            trace_id="trace-empty-requirement",
        )

        self.assertEqual(result["structuredReport"]["findings"], ["金额集中在项目B。"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing service tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_excel_analysis -v
```

Expected result:

```text
ERROR because app.services.excel.analyzer does not exist yet.
```

- [ ] **Step 3: Implement ExcelAnalyzer service**

Create `adapter_service/app/services/excel/__init__.py` as an empty file.

Create `adapter_service/app/services/excel/analyzer.py`:

```python
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelAnalysisRequest
from app.services.provider_client import ProviderClient


class ExcelAnalyzer:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def analyze(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        if not self._has_usable_table(request):
            raise AdapterError(
                "EXCEL_ANALYSIS_TABLE_REQUIRED",
                "未读取到可分析的表格数据，请先选择表格区域或确认当前工作表存在数据。",
                status_code=400,
            )
        provider_result = self.provider_client.excel_analysis(request, trace_id=trace_id)
        return {
            "structuredReport": provider_result["structuredReport"],
            "plainText": provider_result.get("plainText", ""),
            "provider": provider_result.get("provider", "mock"),
        }

    def _has_usable_table(self, request: ExcelAnalysisRequest) -> bool:
        if request.table.headers:
            return True
        return any(any(str(cell).strip() for cell in row) for row in request.table.rows)
```

- [ ] **Step 4: Add FastAPI route and main registration**

Create `adapter_service/app/api/excel.py`:

```python
from fastapi import APIRouter

from app.core.logging import get_logger
from app.core.models import ExcelAnalysisRequest, ExcelAnalysisResponseData
from app.core.tracing import new_trace_id
from app.services.excel.analyzer import ExcelAnalyzer

router = APIRouter()
excel_analyzer = ExcelAnalyzer()
logger = get_logger(__name__)


@router.post("/excel/analysis")
def excel_analysis(request: ExcelAnalysisRequest) -> dict:
    trace_id = new_trace_id("excel-analysis")
    analysis = excel_analyzer.analyze(request, trace_id=trace_id)
    payload = ExcelAnalysisResponseData(**analysis)
    logger.info(
        "traceId=%s task=excel.analysis sheet=%s rows=%s columns=%s",
        trace_id,
        request.scope.sheet_name,
        request.table.row_count,
        request.table.column_count,
    )
    return {
        "success": True,
        "traceId": trace_id,
        "taskType": "excel.analysis",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
```

Modify `adapter_service/app/main.py`:

```python
from app.api.excel import router as excel_router
```

and after `app.include_router(word_router)`:

```python
app.include_router(excel_router)
```

Extend `_task_type_from_path`:

```python
"/excel/analysis": "excel.analysis",
```

- [ ] **Step 5: Add standalone route**

Modify `adapter_service/standalone_adapter.py` imports:

```python
from app.core.models import ExcelAnalysisRequest, ExcelAnalysisResponseData
from app.services.excel.analyzer import ExcelAnalyzer
```

Add helper:

```python
def parse_excel_request(payload):
    if hasattr(ExcelAnalysisRequest, "model_validate"):
        return ExcelAnalysisRequest.model_validate(payload)
    return ExcelAnalysisRequest.parse_obj(payload)


def excel_analysis(payload):
    request = parse_excel_request(payload)
    data = ExcelAnalyzer().analyze(request, trace_id="standalone-excel-analysis")
    if hasattr(ExcelAnalysisResponseData, "model_validate"):
        return ExcelAnalysisResponseData.model_validate(data).model_dump(by_alias=True)
    return ExcelAnalysisResponseData(**data).dict(by_alias=True)
```

In `do_POST`, before the Word route checks complete:

```python
if path == "/excel/analysis":
    self._write(200, envelope("standalone-excel-analysis", "excel.analysis", excel_analysis(payload)))
    return
```

- [ ] **Step 6: Run service tests and compile checks**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_excel_analysis -v
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/app/api/excel.py adapter_service/app/services/excel/analyzer.py adapter_service/app/main.py adapter_service/standalone_adapter.py
```

Expected result:

```text
OK
```

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add adapter_service/app/api/excel.py adapter_service/app/services/excel/__init__.py adapter_service/app/services/excel/analyzer.py adapter_service/tests/test_excel_analysis.py adapter_service/app/main.py adapter_service/standalone_adapter.py
git commit -m "feat: add excel analysis adapter route"
```

## Task 3: Excel Task Pane Mode And Read-Only Result Views

**Files:**
- Create/modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html`
- Create/modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js`
- Create/modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`
- Create/modify: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js`
- Test: `formal-plugin-kit/tests/layout-smoke.test.js`

- [ ] **Step 1: Write failing static assertions for Excel task pane**

In `formal-plugin-kit/tests/layout-smoke.test.js`, add reads:

```js
const excelHtml = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html",
  "utf8"
);
const excelJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js",
  "utf8"
);
const excelCss = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css",
  "utf8"
);
```

Add assertions:

```js
assert.ok(excelHtml.includes("Excel 智能分析"));
assert.ok(excelHtml.includes('id="excel-analysis-options"'));
assert.ok(excelHtml.includes('id="excel-analysis-requirement"'));
assert.ok(excelHtml.includes('id="excel-range-summary"'));
assert.ok(excelHtml.includes('id="btn-run-primary"'));
assert.ok(excelHtml.includes('id="btn-copy-result"'));
assert.ok(!excelHtml.includes('id="write-action"'));
assert.ok(!excelHtml.includes('id="btn-apply"'));
assert.ok(!excelHtml.includes("文档审查"));
assert.ok(!excelHtml.includes("格式审查"));

assert.ok(excelJs.includes("excelAnalysis"));
assert.ok(excelJs.includes("/excel/analysis"));
assert.ok(excelJs.includes("runExcelAnalysisAction"));
assert.ok(excelJs.includes("extractExcelRange"));
assert.ok(excelJs.includes("analysisRequirement"));
assert.ok(excelJs.includes("structuredReport"));
assert.ok(excelJs.includes("plainText"));
assert.ok(excelJs.includes('{ taskType: "excel.analysis", label: "Excel 智能分析" }'));
assert.ok(!excelJs.includes("applyRewrite"));
assert.ok(!excelJs.includes("tryApplyFormattedRewrite"));
assert.ok(!excelJs.includes("/word/document-review"));

assert.ok(excelCss.includes("excel-range-summary"));
```

- [ ] **Step 2: Run failing frontend smoke test**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
```

Expected result:

```text
AssertionError or ENOENT because the Excel task pane files do not exist yet.
```

- [ ] **Step 3: Create Excel task pane files from the current visual system**

Copy existing shared assets:

```bash
mkdir -p formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets
cp formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css
cp formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js
cp formal-plugin-kit/wps-ai-assistant_1.0.0/assets/ai-assistant-32.png formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/ai-assistant-32.png
cp formal-plugin-kit/wps-ai-assistant_1.0.0/assets/icon-settings.png formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-settings.png
```

Then create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html` with the existing header/settings structure and only Excel controls:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>WPS AI 助理 - Excel 智能分析</title>
    <link rel="stylesheet" href="./taskpane.css?v=0.15.0-alpha" />
  </head>
  <body>
    <div class="app" data-task-mode="excelAnalysis">
      <header class="header">
        <div class="header-copy">
          <p class="eyebrow">WPS AI 助理</p>
          <h1 id="task-title">Excel 智能分析</h1>
        </div>
        <div id="top-toolbox" class="header-actions">
          <div id="health-indicator" class="badge badge-warn">检测中</div>
        </div>
      </header>
      <section id="home-view" class="view active">
        <section id="scope-strip" class="scope-strip">
          <span class="scope-pill-label">识别范围</span>
          <strong id="scope-line">未检测</strong>
        </section>
        <section class="controls glass-card">
          <div id="excel-analysis-options" class="mode-block">
            <div id="excel-range-summary" class="excel-range-summary">等待读取表格范围。</div>
            <label class="field" for="excel-analysis-requirement">
              <span>分析要求</span>
              <textarea id="excel-analysis-requirement" rows="4" placeholder="例如：生成经营分析，关注异常波动和后续建议。"></textarea>
            </label>
          </div>
          <div class="button-cluster action-bar">
            <button id="btn-run-primary" type="button">生成分析报告</button>
          </div>
          <div id="status-line" class="sr-only">等待操作。</div>
        </section>
        <section class="panel result-panel glass-card">
          <div class="panel-head">
            <button id="btn-copy-result" class="ghost-action copy-button" type="button" title="复制结果" aria-label="复制结果">复制</button>
            <div>
              <h2>结果预览</h2>
              <div id="result-view-switch" class="result-view-switch" hidden>
                <button type="button" id="btn-result-preview" class="view-switch-button active" aria-pressed="true">分析报告</button>
                <button type="button" id="btn-result-plain" class="view-switch-button" aria-pressed="false">汇报段落</button>
              </div>
            </div>
          </div>
          <div id="result-output" class="markdown-output">等待运行。</div>
        </section>
      </section>
      <section id="settings-view" class="view">
        <section class="settings-shell glass-card">
          <section id="connection-settings-section" class="settings-group">
            <section class="settings-card">
              <div id="provider-summary-card" class="provider-summary">
                <div class="provider-main">
                  <span id="provider-current-badge" class="provider-badge">当前</span>
                  <h4 id="provider-summary-name">星辰 API</h4>
                  <p id="provider-summary-type">企业大模型服务</p>
                  <p id="provider-summary-url">未检测到服务地址</p>
                  <p id="provider-auth-line">统一密钥：未配置</p>
                </div>
                <div class="provider-side">
                  <button id="btn-edit-provider" class="ghost-action mini-button" type="button">编辑</button>
                </div>
              </div>
              <div id="provider-edit-view" class="provider-editor" hidden>
                <label class="field"><span>模型提供商名称</span><input id="provider-name" type="text" placeholder="例如：星辰 API" /></label>
                <label class="field"><span>大模型 API URL</span><input id="provider-base-url" type="text" placeholder="例如：https://aibot.example.com/v1" /></label>
                <label class="field"><span>统一模型 API Key</span><input id="provider-api-key" type="password" placeholder="粘贴统一模型 API Key" /></label>
                <div class="button-row settings-actions">
                  <button id="btn-save-provider-url" type="button">保存地址</button>
                  <button id="btn-save-api-key" type="button">保存密钥</button>
                  <button id="btn-clear-api-key" class="ghost-action" type="button">清除密钥</button>
                  <button id="btn-refresh" class="ghost-action" type="button">刷新配置</button>
                  <button id="btn-back-provider-summary" class="ghost-action" type="button">完成</button>
                </div>
              </div>
            </section>
            <section class="settings-card">
              <div class="settings-card-head"><h4>任务级 API Key</h4><p>Excel 智能分析可使用独立模型后台密钥。</p></div>
              <div id="task-api-key-list" class="task-api-key-list"></div>
            </section>
          </section>
          <section id="diagnostics-section" class="settings-group">
            <section id="last-task-diagnostics-card" class="settings-card diagnostics-card">
              <div class="settings-card-head"><h4>最近一次任务诊断</h4><p>用于排查模型接口、任务密钥和 adapter 状态。</p></div>
              <pre id="last-task-diagnostics-output">未检测。</pre>
              <div class="button-row settings-actions">
                <button id="btn-refresh-diagnostics" type="button">刷新诊断</button>
                <button id="btn-copy-diagnostics" class="ghost-action" type="button">复制诊断</button>
              </div>
            </section>
          </section>
        </section>
      </section>
      <footer><span>Trace</span><code id="trace-line">未检测</code><span>前端版本</span><code id="frontend-version-line">0.15.0-alpha</code></footer>
    </div>
    <script src="./taskpane-helpers.js?v=0.15.0-alpha"></script>
    <script src="./taskpane.js?v=0.15.0-alpha"></script>
  </body>
</html>
```

- [ ] **Step 4: Implement Excel task pane JavaScript**

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js` with focused Excel behavior. Use this skeleton and keep it free of Word writeback functions:

```js
(function () {
  var ADAPTER_BASE_URL = "http://127.0.0.1:18100";
  var FRONTEND_BUILD_VERSION = "0.15.0-alpha";
  var helpers = window.WpsAiAssistantHelpers || {};
  var EXCEL_EXTRACTION_OPTIONS = {
    maxRows: 120,
    maxColumns: 30,
    maxCellTextLength: 120,
    maxTotalTextLength: 20000
  };
  var TASK_API_KEY_DEFS = [
    { taskType: "excel.analysis", label: "Excel 智能分析" }
  ];
  var state = {
    currentMode: "excelAnalysis",
    traceId: "",
    copyText: "",
    diagnosticsCopyText: "",
    analysisRequirement: "",
    analysisResult: null,
    resultViewMode: "preview",
    latestExcelPayload: null,
    providerName: "未检测",
    providerBaseUrl: "",
    providerAuthSource: "none",
    taskApiKeys: {}
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setStatus(message) {
    byId("status-line").textContent = message || "";
  }

  function setTrace(traceId) {
    state.traceId = traceId || "";
    byId("trace-line").textContent = traceId || "未检测";
  }

  function setResult(markdown, copyText) {
    state.copyText = copyText || markdown || "";
    if (helpers.renderMarkdown) {
      byId("result-output").innerHTML = helpers.renderMarkdown(markdown || "");
    } else {
      byId("result-output").textContent = markdown || "";
    }
  }

  function setPlainResult(text, copyText) {
    state.copyText = copyText || text || "";
    byId("result-output").textContent = text || "";
  }

  function request(path, payload) {
    var options = { method: payload ? "POST" : "GET" };
    if (payload) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(payload);
    }
    return fetch(ADAPTER_BASE_URL + path, options).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) {
          throw new Error(body.message || "请求失败");
        }
        return body;
      });
    });
  }

  function getEtApplication() {
    return window.Application || window.wps || {};
  }

  function safeText(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return String(value).replace(/\r/g, "").trim();
  }

  function readRangeMatrix(range) {
    var values = [];
    var rows = range && (range.Rows || range.rows);
    var columns = range && (range.Columns || range.columns);
    var rowCount = Number(rows && (rows.Count || rows.count)) || 0;
    var columnCount = Number(columns && (columns.Count || columns.count)) || 0;
    var r;
    var c;
    var cell;
    if (!range || !range.Cells || !rowCount || !columnCount) {
      return { rows: [], rowCount: 0, columnCount: 0 };
    }
    for (r = 1; r <= Math.min(rowCount, EXCEL_EXTRACTION_OPTIONS.maxRows); r += 1) {
      var row = [];
      for (c = 1; c <= Math.min(columnCount, EXCEL_EXTRACTION_OPTIONS.maxColumns); c += 1) {
        try {
          cell = range.Cells.Item ? range.Cells.Item(r, c) : range.Cells(r, c);
          row.push(safeText(cell && (cell.Text || cell.Value2 || cell.Value)));
        } catch (error) {
          row.push("");
        }
      }
      values.push(row);
    }
    return {
      rows: values,
      rowCount: rowCount,
      columnCount: columnCount
    };
  }

  function normalizeMatrix(matrix) {
    var rows = matrix.rows || [];
    var headers = rows.length ? rows[0].map(function (cell, index) {
      return cell || "列" + (index + 1);
    }) : [];
    var bodyRows = rows.slice(1);
    return {
      headers: headers,
      rows: bodyRows,
      rowCount: Math.max(matrix.rowCount - 1, bodyRows.length),
      columnCount: matrix.columnCount,
      truncated: matrix.rowCount > EXCEL_EXTRACTION_OPTIONS.maxRows ||
        matrix.columnCount > EXCEL_EXTRACTION_OPTIONS.maxColumns
    };
  }

  function extractExcelRange() {
    var app = getEtApplication();
    var workbook = app.ActiveWorkbook || app.activeWorkbook || {};
    var sheet = app.ActiveSheet || app.activeSheet || {};
    var range = app.Selection || app.selection || null;
    var scopeType = "selection";
    var matrix;
    if (!range || !range.Cells) {
      range = sheet.UsedRange || sheet.usedRange || null;
      scopeType = "usedRange";
    }
    matrix = readRangeMatrix(range);
    if (!matrix.rowCount || !matrix.columnCount) {
      range = sheet.UsedRange || sheet.usedRange || null;
      scopeType = "usedRange";
      matrix = readRangeMatrix(range);
    }
    var table = normalizeMatrix(matrix);
    return {
      workbookId: safeText(workbook.Name || workbook.name || "active-workbook"),
      scene: "excel",
      scope: {
        type: scopeType,
        sheetName: safeText(sheet.Name || sheet.name || "Sheet1"),
        address: safeText(range && (range.Address || range.address || ""))
      },
      table: table,
      options: {
        analysisRequirement: state.analysisRequirement
      }
    };
  }

  function renderExcelAnalysisResult(data) {
    var report = data.structuredReport || {};
    var markdown = [
      "## 数据概览",
      report.overview || "未返回数据概览。",
      "",
      "## 关键发现",
      (report.findings || []).map(function (item) { return "- " + item; }).join("\n") || "- 未返回关键发现。",
      "",
      "## 风险异常",
      (report.risks || []).map(function (item) { return "- " + item; }).join("\n") || "- 未返回风险异常。",
      "",
      "## 建议动作",
      (report.actions || []).map(function (item) { return "- " + item; }).join("\n") || "- 未返回建议动作。"
    ].join("\n");
    state.analysisResult = data;
    state.resultViewMode = "preview";
    byId("result-view-switch").hidden = false;
    setResult(markdown, data.plainText || markdown);
  }

  function runExcelAnalysisAction() {
    state.analysisRequirement = safeText(byId("excel-analysis-requirement").value);
    setStatus("正在读取 Excel 表格范围...");
    setPlainResult("正在读取 Excel 表格范围，请稍候。");
    setTimeout(function () {
      try {
        state.latestExcelPayload = extractExcelRange();
        byId("excel-range-summary").textContent = [
          state.latestExcelPayload.scope.sheetName,
          state.latestExcelPayload.scope.address || "未识别地址",
          state.latestExcelPayload.table.rowCount + " 行",
          state.latestExcelPayload.table.columnCount + " 列"
        ].join(" / ");
      } catch (error) {
        setStatus("读取 Excel 表格失败：" + error.message);
        setResult("读取 Excel 表格失败：" + error.message);
        return;
      }
      setStatus("正在提交 Excel 智能分析请求...");
      setPlainResult("正在等待模型后台生成分析报告。");
      request("/excel/analysis", state.latestExcelPayload)
        .then(function (body) {
          setTrace(body.traceId);
          renderExcelAnalysisResult(body.data || {});
          setStatus("Excel 智能分析报告已生成。");
        })
        .catch(function (error) {
          setStatus("生成失败：" + error.message);
          setResult(error.message);
        });
    }, 0);
  }

  function setResultViewMode(mode) {
    state.resultViewMode = mode;
    if (!state.analysisResult) {
      return;
    }
    if (mode === "plain") {
      setPlainResult(state.analysisResult.plainText || "", state.analysisResult.plainText || "");
      return;
    }
    renderExcelAnalysisResult(state.analysisResult);
  }

  function bindEvents() {
    byId("btn-run-primary").addEventListener("click", runExcelAnalysisAction);
    byId("excel-analysis-requirement").addEventListener("input", function (event) {
      state.analysisRequirement = event.target.value;
    });
    byId("btn-result-preview").addEventListener("click", function () { setResultViewMode("preview"); });
    byId("btn-result-plain").addEventListener("click", function () { setResultViewMode("plain"); });
    byId("btn-copy-result").addEventListener("click", function () {
      var text = state.copyText || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
      }
      setStatus(text ? "结果已复制。" : "暂无可复制的内容。");
    });
  }

  function init() {
    byId("frontend-version-line").textContent = FRONTEND_BUILD_VERSION;
    bindEvents();
    setStatus("等待操作。");
  }

  init();
}());
```

For settings, copy the current provider/settings helpers from `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js` into the Excel task pane and keep only the functions needed by the Excel settings HTML:

```text
setProviderLine
setProviderAuthLine
showProviderEditor
hideProviderEditor
refreshConfig
saveProviderBaseUrl
saveProviderApiKey
clearProviderApiKey
renderTaskApiKeyList
saveTaskApiKey
clearTaskApiKey
refreshDiagnostics
copyDiagnostics
describeFetchError
readAdapterJson
setAdapterUnavailableState
```

After copying, make these Excel-specific adjustments:

```js
var TASK_API_KEY_DEFS = [
  { taskType: "excel.analysis", label: "Excel 智能分析" }
];
```

```js
byId("btn-save-provider-url").addEventListener("click", saveProviderBaseUrl);
byId("btn-save-api-key").addEventListener("click", saveProviderApiKey);
byId("btn-clear-api-key").addEventListener("click", clearProviderApiKey);
byId("btn-refresh").addEventListener("click", refreshConfig);
byId("btn-edit-provider").addEventListener("click", showProviderEditor);
byId("btn-back-provider-summary").addEventListener("click", hideProviderEditor);
byId("btn-refresh-diagnostics").addEventListener("click", refreshDiagnostics);
byId("btn-copy-diagnostics").addEventListener("click", copyDiagnostics);
```

Do not copy these Word-only functions into `wps-ai-assistant-et_1.0.0/taskpane.js`:

```text
applyRewrite
tryApplyFormattedRewrite
buildMarkdownWritebackBlocks
runSmartWriteAction
runSmartImitationAction
runDocumentReview
runFormatReview
extractDocument
```

- [ ] **Step 5: Add Excel-specific CSS**

Append to `formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css`:

```css
.excel-range-summary {
  border: 1px solid rgba(42, 111, 151, 0.18);
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.72);
  color: #24556f;
  font-size: 13px;
  line-height: 1.5;
}

#excel-analysis-options textarea {
  min-height: 108px;
  resize: vertical;
}
```

- [ ] **Step 6: Run frontend static tests**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
```

Expected result:

```text
layout smoke tests passed
```

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: add excel analysis task pane"
```

## Task 4: Excel Host Add-in Ribbon And Dual Publish Entries

**Files:**
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js`
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json`
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html`
- Create: `formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png`
- Modify: `phase1-delivery-kit/wps-jsaddons/publish.xml`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`
- Modify: `adapter_service/tests/test_packaging_scripts.py`

- [ ] **Step 1: Write failing Ribbon and package assertions**

Add to `formal-plugin-kit/tests/layout-smoke.test.js`:

```js
const excelRibbon = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml",
  "utf8"
);
const excelRibbonJs = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js",
  "utf8"
);
const excelManifest = fs.readFileSync(
  "formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json",
  "utf8"
);

assert.ok(excelManifest.includes('"name": "wps-ai-assistant-et"'));
assert.ok(excelManifest.includes('"version": "0.15.0-alpha"'));
assert.ok(excelRibbon.includes('label="WPS AI 助理"'));
assert.ok(excelRibbon.includes('label="表格分析"'));
assert.ok(excelRibbon.includes('id="btnAiExcelAnalysis"'));
assert.ok(excelRibbon.includes('label="Excel 智能分析"'));
assert.ok(excelRibbon.includes('id="btnAiSettings"'));
assert.ok(excelRibbon.includes('label="设置"'));
assert.ok(!excelRibbon.includes('label="智能编写"'));
assert.ok(!excelRibbon.includes('label="文档审查"'));
assert.ok(excelRibbonJs.includes('btnAiExcelAnalysis: "excelAnalysis"'));
assert.ok(excelRibbonJs.includes('btnAiSettings: "settings"'));
assert.ok(excelRibbonJs.includes('btnAiExcelAnalysis: "assets/icon-excel-analysis.png"'));
assert.ok(excelRibbonJs.includes('build=0.15.0-alpha'));
assert.ok(fs.existsSync("formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png"));
```

In `adapter_service/tests/test_packaging_scripts.py`, add:

```python
def test_phase1_publish_xml_contains_word_and_excel_addins(self) -> None:
    publish_xml = (ROOT / "phase1-delivery-kit/wps-jsaddons/publish.xml").read_text(encoding="utf-8")

    self.assertIn('name="wps-ai-assistant"', publish_xml)
    self.assertIn('type="wps"', publish_xml)
    self.assertIn('name="wps-ai-assistant-et"', publish_xml)
    self.assertIn('type="et"', publish_xml)


def test_excel_addin_contains_only_excel_ribbon_entries(self) -> None:
    ribbon = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml").read_text(encoding="utf-8")
    ribbon_js = (ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js").read_text(encoding="utf-8")

    self.assertIn('label="Excel 智能分析"', ribbon)
    self.assertIn('label="设置"', ribbon)
    self.assertNotIn('label="智能编写"', ribbon)
    self.assertNotIn('label="文档审查"', ribbon)
    self.assertIn("btnAiExcelAnalysis", ribbon_js)
    self.assertIn("icon-excel-analysis.png", ribbon_js)
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected result:

```text
Assertions fail because Excel Ribbon, manifest, icon, and publish.xml entries do not exist yet.
```

- [ ] **Step 3: Create Excel add-in manifest and entry**

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json`:

```json
{
  "name": "wps-ai-assistant-et",
  "version": "0.15.0-alpha",
  "description": "AI-WPS Excel analysis assistant",
  "icons": {
    "32": "assets/ai-assistant-32.png"
  },
  "entry": "index.html"
}
```

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>WPS AI 助理 - Excel</title>
  </head>
  <body>
    <script src="./ribbon.js?v=0.15.0-alpha"></script>
  </body>
</html>
```

- [ ] **Step 4: Create Excel Ribbon XML and JS**

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml`:

```xml
<customUI xmlns="http://schemas.microsoft.com/office/2006/01/customui" onLoad="OnAddinLoad">
  <ribbon startFromScratch="false">
    <tabs>
      <tab id="wpsAiAssistantExcelTab" label="WPS AI 助理">
        <group id="wpsAiAssistantExcelGroup" label="表格分析">
          <button id="btnAiExcelAnalysis" label="Excel 智能分析" size="large" getImage="GetImage" onAction="OnAction" />
          <button id="btnAiSettings" label="设置" size="large" getImage="GetImage" onAction="OnAction" />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>
```

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js`:

```js
function OnAddinLoad(ribbonUI) {
  if (typeof window.Application.ribbonUI !== "object") {
    window.Application.ribbonUI = ribbonUI;
  }
  if (typeof window.Application.Enum !== "object" && typeof WPS_Enum !== "undefined") {
    window.Application.Enum = WPS_Enum;
  }
  return true;
}

function resolveMode(controlId) {
  var modeMap = {
    btnAiExcelAnalysis: "excelAnalysis",
    btnAiSettings: "settings"
  };
  return modeMap[controlId] || "excelAnalysis";
}

var ribbonIconMap = {
  btnAiExcelAnalysis: "assets/icon-excel-analysis.png",
  btnAiSettings: "assets/icon-settings.png"
};

function GetImage(control) {
  var controlId = control && (control.Id || control.id);
  return ribbonIconMap[controlId] || "assets/ai-assistant-32.png";
}

function closeCurrentTaskPane() {
  var current = window.Application.WpsAiAssistantTaskPane;
  if (!current) {
    return;
  }
  try {
    current.Visible = false;
  } catch (error) {
  }
}

function OnAction(control) {
  try {
    var mode = resolveMode(control.Id || control.id);
    var url = location.href.replace(/[^\/]*$/, "");
    closeCurrentTaskPane();
    var taskPane = window.Application.CreateTaskPane(
      url + "taskpane.html?mode=" + encodeURIComponent(mode) + "&build=0.15.0-alpha"
    );
    window.Application.WpsAiAssistantTaskPane = taskPane;
    taskPane.Visible = true;
  } catch (error) {
    window.Application.confirm("错误：" + error.message);
  }
  return true;
}
```

- [ ] **Step 5: Create Excel icon asset**

Create `formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png` as a 32x32 transparent PNG matching the current icon family:

- blue/gray treatment
- table grid with a small analysis line or spark mark
- no runtime dependency

Verify:

```bash
file formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png
sips -g pixelWidth -g pixelHeight formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png
```

Expected result:

```text
PNG image data, 32 x 32
pixelWidth: 32
pixelHeight: 32
```

- [ ] **Step 6: Update publish.xml**

Replace `phase1-delivery-kit/wps-jsaddons/publish.xml` with:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<jsplugins>
  <jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>
  <jsplugin name="wps-ai-assistant-et" url="file://" type="et" enable="enable_dev" version="1.0.0"/>
</jsplugins>
```

- [ ] **Step 7: Run Ribbon/package tests**

Run:

```bash
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js
```

Expected result:

```text
layout smoke tests passed
OK
```

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.xml formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/assets/icon-excel-analysis.png phase1-delivery-kit/wps-jsaddons/publish.xml formal-plugin-kit/tests/layout-smoke.test.js adapter_service/tests/test_packaging_scripts.py
git commit -m "feat: add excel host ribbon package"
```

## Task 5: Installer, Packaging, Operations Docs, Version Bump, And Delivery

**Files:**
- Create: `docs/operations/dify-excel-analysis-workflow.md`
- Modify: `packaging/build_phase1_delivery_kit.sh`
- Modify: `phase1-delivery-kit/installer/install_phase1.sh`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `README.md`
- Modify: `README-ZH.md`
- Modify: `docs/codex-handoff.md`
- Modify: all version-bearing files listed in File Structure
- Modify: version and packaging tests
- Create: `dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260626.tar.gz`

- [ ] **Step 1: Write failing packaging assertions**

In `adapter_service/tests/test_packaging_scripts.py`, add:

```python
def test_phase1_packaging_includes_excel_addin_and_workflow_doc(self) -> None:
    script = (ROOT / "packaging/build_phase1_delivery_kit.sh").read_text(encoding="utf-8")

    self.assertIn("wps-ai-assistant-et_1.0.0", script)
    self.assertIn("dify-excel-analysis-workflow.md", script)


def test_phase1_installer_installs_word_and_excel_addins(self) -> None:
    script = (ROOT / "phase1-delivery-kit/installer/install_phase1.sh").read_text(encoding="utf-8")

    self.assertIn("WORD_PLUGIN_NAME=\"wps-ai-assistant_1.0.0\"", script)
    self.assertIn("EXCEL_PLUGIN_NAME=\"wps-ai-assistant-et_1.0.0\"", script)
    self.assertIn('name="wps-ai-assistant-et"', script)
    self.assertIn('type="et"', script)
    self.assertIn("preserve_adapter_runtime_config", script)
    self.assertIn("restore_adapter_runtime_config", script)
```

- [ ] **Step 2: Run failing packaging tests**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest adapter_service.tests.test_packaging_scripts -v
```

Expected result:

```text
FAIL because packaging and installer scripts do not yet include Excel add-in deployment.
```

- [ ] **Step 3: Update packaging script**

Modify `packaging/build_phase1_delivery_kit.sh` variables:

```bash
WORD_FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant_1.0.0"
EXCEL_FORMAL_SRC="$ROOT_DIR/formal-plugin-kit/wps-ai-assistant-et_1.0.0"
```

Replace the single add-in copy:

```bash
cp -R "$WORD_FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant_1.0.0"
cp -R "$EXCEL_FORMAL_SRC" "$TMP_DIR/packages/wps-ai-assistant-et_1.0.0"
```

Add operations doc copy:

```bash
cp "$ROOT_DIR/docs/operations/dify-excel-analysis-workflow.md" "$TMP_DIR/docs/operations/"
```

- [ ] **Step 4: Update installer for dual add-ins**

Modify `phase1-delivery-kit/installer/install_phase1.sh` variables:

```bash
WORD_PLUGIN_NAME="wps-ai-assistant_1.0.0"
EXCEL_PLUGIN_NAME="wps-ai-assistant-et_1.0.0"
WORD_PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$WORD_PLUGIN_NAME"
EXCEL_PLUGIN_SOURCE="$DELIVERY_ROOT/packages/$EXCEL_PLUGIN_NAME"
```

Replace `install_wps_plugin()` with:

```bash
install_wps_plugin() {
  [ -d "$WORD_PLUGIN_SOURCE" ] || fail "word_plugin_source_missing"
  [ -d "$EXCEL_PLUGIN_SOURCE" ] || fail "excel_plugin_source_missing"
  [ -f "$PUBLISH_SOURCE" ] || fail "publish_xml_missing"

  mkdir -p "$WPS_JSADDONS_DIR"
  copy_dir "$WORD_PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$WORD_PLUGIN_NAME"
  copy_dir "$EXCEL_PLUGIN_SOURCE" "$WPS_JSADDONS_DIR/$EXCEL_PLUGIN_NAME"

  if [ -f "$WPS_JSADDONS_DIR/publish.xml" ]; then
    cp "$WPS_JSADDONS_DIR/publish.xml" "$WPS_JSADDONS_DIR/publish.xml.bak.$(date '+%Y%m%d%H%M%S')"
    {
      printf '%s\n' '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      printf '%s\n' '<jsplugins>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant" url="file://" type="wps" enable="enable_dev" version="1.0.0"/>'
      printf '%s\n' '  <jsplugin name="wps-ai-assistant-et" url="file://" type="et" enable="enable_dev" version="1.0.0"/>'
      grep '<jsplugin ' "$WPS_JSADDONS_DIR/publish.xml" \
        | grep -v 'name="wps-ai-assistant"' \
        | grep -v 'name="wps-ai-assistant-et"' || true
      printf '%s\n' '</jsplugins>'
    } > "$WPS_JSADDONS_DIR/publish.xml.tmp"
    mv "$WPS_JSADDONS_DIR/publish.xml.tmp" "$WPS_JSADDONS_DIR/publish.xml"
  else
    cp "$PUBLISH_SOURCE" "$WPS_JSADDONS_DIR/publish.xml"
  fi

  log "word_plugin_installed=$WPS_JSADDONS_DIR/$WORD_PLUGIN_NAME"
  log "excel_plugin_installed=$WPS_JSADDONS_DIR/$EXCEL_PLUGIN_NAME"
  log "publish_xml_installed=$WPS_JSADDONS_DIR/publish.xml"
}
```

- [ ] **Step 5: Create Excel Dify operations doc**

Create `docs/operations/dify-excel-analysis-workflow.md`:

```markdown
# Excel 智能分析 Dify 工作流配置

适用任务：`excel.analysis`

适用版本：`v0.15.0-alpha` 及以上

推荐任务级 API Key 引用：`excel_analysis`

## 输入约定

adapter 会把完整提示词放入 Dify `/chat-messages` 的顶层 `query` 和 `inputs.query`。Dify 工作流应直接把 `query` 传给 LLM 节点。

提示词内包含工作簿、工作表、范围地址、行列数、表头、样本行、是否截断和用户分析要求。

## 输出约定

推荐输出 JSON：

```json
{
  "structuredReport": {
    "overview": "数据概览",
    "findings": ["关键发现"],
    "risks": ["风险异常"],
    "actions": ["建议动作"]
  },
  "plainText": "可直接复制到 Word 或 PPT 的汇报段落。"
}
```

不要输出公式，不要声称已经修改 Excel 单元格。

## 建议模型参数

建议温度在 `0.2` 到 `0.4` 之间。分析类任务应优先稳定、克制、少编造。

## 排查

在 WPS 设置页查看“最近一次任务诊断”，确认 `taskType=excel.analysis`，并确认任务级 API Key 命中 `excel_analysis`。
```

- [ ] **Step 6: Bump versions to 0.15.0-alpha**

Update these files from `0.14.0-alpha` to `0.15.0-alpha`:

```text
README.md
README-ZH.md
docs/codex-handoff.md
adapter_service/app/api/health.py
adapter_service/app/main.py
adapter_service/app/services/provider_client.py
adapter_service/standalone_adapter.py
adapter-start-kit/scripts/start_uvicorn_adapter.sh
adapter_service/tests/test_health.py
adapter_service/tests/test_packaging_scripts.py
adapter_service/tests/test_review_mode_contract.py
formal-plugin-kit/tests/layout-smoke.test.js
formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json
formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html
formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json
formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html
formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js
phase1-delivery-kit/README.md
```

Update rule number in README and handoff:

```text
AI-WPS-P1-WORD-EXCEL-0.15.0-20260626
```

- [ ] **Step 7: Update README and handoff**

Add README changelog row:

```markdown
| `v0.15.0-alpha` | Adds the first Excel workflow, Excel 智能分析, with an Excel-only `et` add-in entry, read-only selected-range or used-range analysis, independent `excel.analysis` model task, structured report and plain paragraph views, and one installer that deploys both Word and Excel add-ins while preserving runtime configuration |
```

In `docs/codex-handoff.md`, update:

- current version and package
- current route list with `POST /excel/analysis`
- current Ribbon state with Word-only and Excel-only host separation
- protected logic with Excel read-only/no-writeback boundary
- key files list with Excel analyzer and Excel add-in package
- testing results and final package SHA after packaging

- [ ] **Step 8: Run full verification**

Run:

```bash
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover adapter_service/tests -v
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/layout-smoke.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node formal-plugin-kit/tests/taskpane-helpers.test.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane-helpers.js
/Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js
PYTHONPATH=adapter_service /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m py_compile adapter_service/standalone_adapter.py adapter_service/app/api/word.py adapter_service/app/api/excel.py adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/app/services/excel/analyzer.py adapter_service/app/core/models.py
git diff --check
```

Expected result:

```text
Python unittest OK with existing FastAPI-related skips.
Node smoke and helper tests pass.
All syntax and diff checks pass.
```

- [ ] **Step 9: Build delivery package and verify contents**

Run:

```bash
DATE_TAG=20260626 bash packaging/build_phase1_delivery_kit.sh
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260626.tar.gz
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260626.tar.gz | rg 'wps-ai-assistant-et_1.0.0|dify-excel-analysis-workflow.md|excel.py|analyzer.py|icon-excel-analysis.png|publish.xml'
tar -xOf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260626.tar.gz ai-wps-phase1-delivery-20260626/wps-jsaddons/publish.xml | rg 'type="wps"|type="et"|wps-ai-assistant-et'
```

Expected result:

```text
The package contains both Word and Excel add-ins, Excel operations doc, Excel adapter route/service, Excel icon, and publish.xml with wps and et entries.
```

- [ ] **Step 10: Update handoff package SHA**

Copy the SHA from Step 9 into `docs/codex-handoff.md`.

- [ ] **Step 11: Commit Task 5**

Run:

```bash
git add README.md README-ZH.md docs/codex-handoff.md docs/operations/dify-excel-analysis-workflow.md adapter_service/app/api/health.py adapter_service/app/main.py adapter_service/app/services/provider_client.py adapter_service/standalone_adapter.py adapter-start-kit/scripts/start_uvicorn_adapter.sh adapter_service/tests/test_health.py adapter_service/tests/test_packaging_scripts.py adapter_service/tests/test_review_mode_contract.py formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js packaging/build_phase1_delivery_kit.sh phase1-delivery-kit/installer/install_phase1.sh phase1-delivery-kit/README.md phase1-delivery-kit/wps-jsaddons/publish.xml dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260626.tar.gz
git commit -m "chore: release excel analysis alpha"
```

## Final Verification Checklist

- [ ] Word opens with Word-only Ribbon actions and Settings.
- [ ] Excel opens with Excel 智能分析 and Settings only.
- [ ] `POST /excel/analysis` works through FastAPI and standalone adapter.
- [ ] `excel.analysis` appears in task API key settings and provider diagnostics.
- [ ] Excel selected range is preferred over used range.
- [ ] Empty selection falls back to active worksheet used range.
- [ ] Oversized ranges are bounded and marked as truncated.
- [ ] Excel result preview shows 数据概览、关键发现、风险异常、建议动作.
- [ ] Excel plain report paragraph view is copyable.
- [ ] Excel task pane has no writeback button or writeback code path.
- [ ] Word Smart Write, Smart Imitation, Document Review, and Format Review still pass existing tests.
- [ ] Installer deploys both add-in folders in one delivery package.
- [ ] Installer publish.xml contains both `type="wps"` and `type="et"`.
- [ ] Installer preserves target-machine API URL and API keys.
- [ ] Delivery package contains Excel Dify guide and Excel add-in icon.
- [ ] `docs/codex-handoff.md` contains final package SHA.
