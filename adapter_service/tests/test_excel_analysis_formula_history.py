import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    import pydantic
except ImportError:
    class _PydanticShim:
        class BaseModel:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
                    snake = "".join(["_" + c.lower() if c.isupper() else c for c in k]).lstrip("_")
                    setattr(self, snake, v)
            @classmethod
            def parse_obj(cls, d):
                return cls(**d)
            @classmethod
            def model_validate(cls, d):
                return cls(**d)
            def dict(self, *a, **k):
                def _to_dict(v):
                    if isinstance(v, _PydanticShim.BaseModel):
                        return v.dict(*a, **k)
                    elif isinstance(v, list):
                        return [_to_dict(x) for x in v]
                    elif isinstance(v, dict):
                        return {key: _to_dict(val) for key, val in v.items()}
                    return v
                return {key: _to_dict(val) for key, val in self.__dict__.items() if not key.startswith("_")}
            def copy(self, deep=True):
                from copy import deepcopy
                return deepcopy(self)
        @staticmethod
        def Field(*a, **k):
            default = k.get("default", None)
            if default is None and "default_factory" in k:
                return k["default_factory"]()
            return default
        StrictBool = bool
        StrictInt = int
        StrictStr = str
        @staticmethod
        def root_validator(*a, **k):
            return lambda fn: fn
        @staticmethod
        def validator(*a, **k):
            return lambda fn: fn

    import importlib.machinery
    pyd = types.ModuleType("pydantic")
    pyd.__spec__ = importlib.machinery.ModuleSpec("pydantic", None)
    for attr in dir(_PydanticShim):
        if not attr.startswith("__"):
            setattr(pyd, attr, getattr(_PydanticShim, attr))
    sys.modules["pydantic"] = pyd

from app.core.errors import AdapterError
from app.core.models import (
    ExcelAnalysisOptions,
    ExcelAnalysisRequest,
    ExcelAnalysisScope,
    ExcelAnalysisTable,
    ExcelFormulaAssistantRequest,
    ExcelFormulaOptions,
    ExcelFormulaSelection,
)
from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
from app.services.excel.formula_assistant_jobs import ExcelFormulaAssistantJobStore
from app.services.direct_services import DirectServiceStore
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryError, TaskHistoryStore


class MockAnalyzer:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.snapshot_calls = 0

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "serviceName": "智能分析直连服务",
            "modelName": "analysis-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-analysis-1",
            "modelConfigurationName": "智能分析配置",
        }

    def analyze(self, request, trace_id="", task_auth=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback("generating")
        if self.delay > 0:
            time.sleep(self.delay)
        return {
            "structuredReport": {
                "overview": "数据总体趋势良好",
                "findings": ["Q1增长20%", "成本下降5%"],
                "risks": ["供应链不确定性"],
                "actions": ["扩大生产储备"],
            },
            "plainText": "根据表格数据，Q1增长20%，成本下降5%，总体趋势良好。",
            "provider": "mock",
        }


class MockFormulaAssistant:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.snapshot_calls = 0

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "serviceName": "公式助手直连服务",
            "modelName": "formula-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-formula-1",
            "modelConfigurationName": "公式助手配置",
        }

    def generate(self, request, trace_id="", task_auth=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback("generating")
        if self.delay > 0:
            time.sleep(self.delay)
        return {
            "mode": getattr(request.options, "mode", "generate") or "generate",
            "originalFormula": "",
            "primaryFormula": "=SUM(B2:B10)",
            "alternativeFormula": "=SUMIF(A2:A10, \">0\", B2:B10)",
            "suggestedTarget": "B11",
            "explanation": "计算B2到B10单元格的合计。",
            "components": ["SUM: 求和函数", "B2:B10: 求和数值范围"],
            "referenceRanges": ["B2:B10"],
            "issues": [],
            "assumptions": ["B2:B10均为数值类型"],
            "compatibilityNotes": ["支持所有Excel与WPS版本"],
            "localCheck": {"status": "passed", "summary": "语法正常"},
            "rawFinalResult": "=SUM(B2:B10)",
            "parseDiagnostic": "",
            "copyText": "=SUM(B2:B10)",
            "provider": "mock",
        }


class TestExcelAnalysisFormulaHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.history_dir = Path(self.tmp_dir.name) / "history"
        self.history_store = TaskHistoryStore(history_dir=self.history_dir)
        self.coordinator = LongTaskCoordinator(
            max_running=4,
            max_queued=8,
            terminal_ttl_seconds=3600,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_excel_analysis_request_model_attributes(self):
        req = ExcelAnalysisRequest(
            workbook_id="wb-test",
            client_job_id="job-analysis-001",
            document_session_id="session-analysis-1",
            document_display_name="财务报表.xlsx",
            host="et",
            scope=ExcelAnalysisScope(sheet_name="Sheet1", range_address="A1:C10"),
            table=ExcelAnalysisTable(headers=["日期", "项目", "金额"], rows=[["2026-01-01", "收入", "1000"]]),
            options=ExcelAnalysisOptions(requirement="分析利润走势"),
        )
        self.assertEqual(req.document_session_id, "session-analysis-1")
        self.assertEqual(req.document_display_name, "财务报表.xlsx")
        self.assertEqual(req.host, "et")

    @patch("app.services.excel.analysis_jobs.get_task_history_store")
    def test_key_rotation_suppresses_real_analysis_history_commit(
        self, mock_get_history
    ):
        service_id = "direct_svc_analysis_history"
        service_revision = 11
        old_fp = DirectServiceStore.api_key_fingerprint("sk-analysis-old")
        started = threading.Event()
        release = threading.Event()

        class BlockingAnalyzer(MockAnalyzer):
            def snapshot_task_auth(self):
                auth = super().snapshot_task_auth()
                auth.update(
                    {
                        "directService": {
                            "id": service_id,
                            "revision": service_revision,
                        },
                        "apiKeyFingerprint": old_fp,
                    }
                )
                return auth

            def analyze(self, *args, **kwargs):
                started.set()
                release.wait(timeout=2)
                return super().analyze(*args, **kwargs)

        mock_get_history.return_value = self.history_store
        store = ExcelAnalysisJobStore(
            analyzer=BlockingAnalyzer(), coordinator=self.coordinator
        )
        request = ExcelAnalysisRequest(
            workbookId="wb-rotation",
            clientJobId="job-analysis-rotation",
            documentSessionId="doc-analysis-rotation",
            documentDisplayName="轮换分析.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["A"], rows=[["1"]]),
        )

        store.start(request, "trace-analysis-rotation")
        self.assertTrue(started.wait(timeout=1))
        self.coordinator.invalidate_by_auth(
            service_id,
            old_fp,
            service_revision=service_revision,
        )
        release.set()
        terminal = self.coordinator.wait(
            "job-analysis-rotation", task_type="excel.analysis"
        )
        for _ in range(100):
            if self.coordinator.diagnostics()["runningCount"] == 0:
                break
            time.sleep(0.01)

        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(
            terminal["error"]["code"], "DIRECT_SERVICE_KEY_ROTATED"
        )
        self.assertEqual(
            self.history_store.list_history(task_type="excel.analysis"), []
        )

    def test_excel_formula_request_model_attributes(self):
        req = ExcelFormulaAssistantRequest(
            workbook_id="wb-test",
            client_job_id="job-formula-001",
            document_session_id="session-formula-1",
            document_display_name="工资表.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="B2:B10", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="计算总和"),
        )
        self.assertEqual(req.document_session_id, "session-formula-1")
        self.assertEqual(req.document_display_name, "工资表.xlsx")
        self.assertEqual(req.host, "et")

    @patch("app.services.excel.analysis_jobs.get_task_history_store")
    def test_excel_analysis_slot_busy_guard_and_history_recording(self, mock_get_history):
        mock_get_history.return_value = self.history_store
        analyzer = MockAnalyzer(delay=0.1)
        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=self.coordinator)

        req1 = ExcelAnalysisRequest(
            workbook_id="wb-1",
            client_job_id="job-ana-001",
            document_session_id="doc-session-A",
            document_display_name="/path/to/私密路径/报表A.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["A", "B"], rows=[["1", "2"]]),
        )
        started1 = store.start(req1, "trace-ana-1")
        self.assertEqual(started1["jobId"], "job-ana-001")

        # 1. Duplicate submission in same doc session must be blocked with 409
        req1_dup = ExcelAnalysisRequest(
            workbook_id="wb-1",
            client_job_id="job-ana-002",
            document_session_id="doc-session-A",
            document_display_name="报表A.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["A", "B"], rows=[["1", "2"]]),
        )
        with self.assertRaises(AdapterError) as ctx:
            store.start(req1_dup, "trace-ana-2")
        self.assertEqual(ctx.exception.code, "EXCEL_ANALYSIS_DOCUMENT_TASK_BUSY")
        self.assertEqual(ctx.exception.status_code, 409)

        # 2. Concurrent submission in different doc session is permitted
        req2 = ExcelAnalysisRequest(
            workbook_id="wb-2",
            client_job_id="job-ana-003",
            document_session_id="doc-session-B",
            document_display_name="报表B.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["X", "Y"], rows=[["3", "4"]]),
        )
        started2 = store.start(req2, "trace-ana-3")
        self.assertEqual(started2["jobId"], "job-ana-003")

        # 3. Wait for job1 to complete
        for _ in range(50):
            job1 = store.get("job-ana-001")
            if job1 and job1.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(job1.get("status"), "completed")

        # 4. History is recorded with minimal metadata and path sanitized
        entries = self.history_store.list_history(task_type="excel.analysis")
        job1_entries = [e for e in entries if e["jobId"] == "job-ana-001"]
        self.assertEqual(len(job1_entries), 1)
        entry = job1_entries[0]
        self.assertEqual(entry["taskType"], "excel.analysis")
        self.assertEqual(entry["jobId"], "job-ana-001")
        self.assertEqual(entry["documentDisplayName"], "报表A.xlsx")
        self.assertEqual(entry["serviceName"], "智能分析直连服务")
        self.assertEqual(entry["modelName"], "analysis-model-v1")
        # Ensure selection table data is NOT saved in history
        history_str = str(entry)
        self.assertNotIn("headers", history_str)
        self.assertNotIn("/path/to/私密路径", history_str)
        self.assertIn("overview", entry["result"]["structuredReport"])
        self.assertIn("plainText", entry["result"])

        # 5. After completion, slot is released and new job in session A is allowed
        req1_next = ExcelAnalysisRequest(
            workbook_id="wb-1",
            client_job_id="job-ana-004",
            document_session_id="doc-session-A",
            document_display_name="报表A.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["A", "B"], rows=[["1", "2"]]),
        )
        started_next = store.start(req1_next, "trace-ana-4")
        self.assertEqual(started_next["jobId"], "job-ana-004")

        # Wait for remaining jobs so no background thread escapes mock
        for _ in range(50):
            j2 = store.get("job-ana-003")
            j4 = store.get("job-ana-004")
            if j2 and j2.get("status") == "completed" and j4 and j4.get("status") == "completed":
                break
            time.sleep(0.02)

    @patch("app.services.excel.formula_assistant_jobs.get_task_history_store")
    def test_excel_formula_slot_busy_guard_and_history_recording(self, mock_get_history):
        mock_get_history.return_value = self.history_store
        assistant = MockFormulaAssistant(delay=0.1)
        store = ExcelFormulaAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req1 = ExcelFormulaAssistantRequest(
            workbook_id="wb-1",
            client_job_id="job-form-001",
            document_session_id="doc-session-FA",
            document_display_name="/secret/dir/公式A.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="A1:A5", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="计算总和"),
        )
        started1 = store.start(req1, "trace-form-1")
        self.assertEqual(started1["jobId"], "job-form-001")

        # 1. Duplicate submission in same doc session must be blocked with 409
        req1_dup = ExcelFormulaAssistantRequest(
            workbook_id="wb-1",
            client_job_id="job-form-002",
            document_session_id="doc-session-FA",
            document_display_name="公式A.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="A1:A5", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="计算总和"),
        )
        with self.assertRaises(AdapterError) as ctx:
            store.start(req1_dup, "trace-form-2")
        self.assertEqual(ctx.exception.code, "EXCEL_FORMULA_DOCUMENT_TASK_BUSY")
        self.assertEqual(ctx.exception.status_code, 409)

        # 2. Wait for job1 to complete
        for _ in range(50):
            job1 = store.get("job-form-001")
            if job1 and job1.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(job1.get("status"), "completed")

        # 3. History is recorded with minimal metadata
        entries = self.history_store.list_history(task_type="excel.formula_assistant")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["taskType"], "excel.formula_assistant")
        self.assertEqual(entry["jobId"], "job-form-001")
        self.assertEqual(entry["documentDisplayName"], "公式A.xlsx")
        self.assertEqual(entry["serviceName"], "公式助手直连服务")
        self.assertEqual(entry["modelName"], "formula-model-v1")
        # Ensure user requirement (prompt) and selection details are excluded
        history_str = str(entry)
        self.assertNotIn("计算总和", history_str)
        self.assertNotIn("A1:A5", history_str)
        self.assertNotIn("/secret/dir", history_str)
        self.assertEqual(entry["result"]["primaryFormula"], "=SUM(B2:B10)")
        self.assertEqual(entry["result"]["mode"], "generate")

        # 4. Slot is released after completion
        req1_next = ExcelFormulaAssistantRequest(
            workbook_id="wb-1",
            client_job_id="job-form-003",
            document_session_id="doc-session-FA",
            document_display_name="公式A.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="A1:A5", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="求均值"),
        )
        started_next = store.start(req1_next, "trace-form-3")
        self.assertEqual(started_next["jobId"], "job-form-003")

        for _ in range(50):
            j3 = store.get("job-form-003")
            if j3 and j3.get("status") == "completed":
                break
            time.sleep(0.02)

    @patch("app.services.excel.analysis_jobs.get_task_history_store")
    def test_excel_analysis_history_too_large_notice(self, mock_get_history):
        class OverflowHistoryStore:
            def record_success(self, **kwargs):
                raise TaskHistoryError("HISTORY_ENTRY_TOO_LARGE", "entry too large")
        mock_get_history.return_value = OverflowHistoryStore()

        analyzer = MockAnalyzer(delay=0.0)
        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=self.coordinator)
        req = ExcelAnalysisRequest(
            workbook_id="wb-1",
            client_job_id="job-overflow-001",
            document_session_id="doc-overflow",
            document_display_name="大表.xlsx",
            host="et",
            table=ExcelAnalysisTable(headers=["A"], rows=[["1"]]),
        )
        store.start(req, "trace-overflow")
        for _ in range(50):
            job = store.get("job-overflow-001")
            if job and job.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(job.get("status"), "completed")
        self.assertIn("historyNotice", job.get("result", {}))
    @patch("app.services.excel.formula_assistant_jobs.get_task_history_store")
    def test_excel_formula_history_diagnostic_degradation_not_archived(self, mock_get_history):
        mock_get_history.return_value = self.history_store
        class DegradedAssistant:
            def generate(self, *args, **kwargs):
                return {
                    "mode": "generate",
                    "primaryFormula": "=SUM(A1:A5)",
                    "alternativeFormula": "",
                    "suggestedTarget": "",
                    "explanation": "原始文本包含用户输入及回显",
                    "components": [],
                    "referenceRanges": [],
                    "issues": [],
                    "assumptions": [],
                    "compatibilityNotes": ["未按 JSON 输出"],
                    "rawFinalResult": "原始文本包含用户输入及回显",
                    "parseDiagnostic": "模型后台最终结果未按结构化 JSON 输出",
                    "copyText": "原始文本包含用户输入及回显",
                }

        degraded_assistant = DegradedAssistant()
        store = ExcelFormulaAssistantJobStore(assistant=degraded_assistant, coordinator=self.coordinator)
        req = ExcelFormulaAssistantRequest(
            workbook_id="wb-1",
            client_job_id="job-form-degraded-001",
            document_session_id="doc-degraded",
            document_display_name="降级.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="A1:A5", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="求和"),
        )
        store.start(req, "trace-degraded")
        for _ in range(50):
            job = store.get("job-form-degraded-001")
            if job and job.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(job.get("status"), "completed")
        self.assertEqual(job["result"].get("historyNotice"), "诊断降级结果未保存至历史记录。")
        history = self.history_store.list_history(task_type="excel.formula_assistant")
        self.assertEqual(len(history), 0)

    @patch("app.services.excel.formula_assistant_jobs.get_task_history_store")
    def test_excel_formula_history_copy_text_whitelisted(self, mock_get_history):
        mock_get_history.return_value = self.history_store
        class NormalAssistant:
            def generate(self, *args, **kwargs):
                return {
                    "mode": "generate",
                    "primaryFormula": "=AVERAGE(B2:B10)",
                    "alternativeFormula": "",
                    "suggestedTarget": "",
                    "explanation": "计算平均值",
                    "components": [{"label": "AVERAGE", "description": "平均值"}],
                    "referenceRanges": ["B2:B10"],
                    "issues": [],
                    "assumptions": [],
                    "compatibilityNotes": [],
                    "rawFinalResult": "",
                    "parseDiagnostic": "",
                    "copyText": "带有原始输入的非白名单文本",
                }

        assistant = NormalAssistant()
        store = ExcelFormulaAssistantJobStore(assistant=assistant, coordinator=self.coordinator)
        req = ExcelFormulaAssistantRequest(
            workbook_id="wb-1",
            client_job_id="job-form-clean-001",
            document_session_id="doc-clean",
            document_display_name="正常.xlsx",
            host="et",
            selection=ExcelFormulaSelection(address="B2:B10", sheet_name="Sheet1"),
            options=ExcelFormulaOptions(mode="generate", requirement="求均值"),
        )
        store.start(req, "trace-clean")
        for _ in range(50):
            job = store.get("job-form-clean-001")
            if job and job.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(job.get("status"), "completed")
        self.assertNotIn("historyNotice", job["result"])
        history = self.history_store.list_history(task_type="excel.formula_assistant")
        self.assertEqual(len(history), 1)
        archived = history[0]["result"]
        self.assertEqual(archived["copyText"], "=AVERAGE(B2:B10)")
        self.assertEqual(archived["primaryFormula"], "=AVERAGE(B2:B10)")


if __name__ == "__main__":
    unittest.main()
