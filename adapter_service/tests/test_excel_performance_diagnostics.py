import os
import tempfile
import unittest
from unittest.mock import MagicMock

from app.core.errors import AdapterError, ProviderTimeoutError
from app.core.models import (
    ExcelAnalysisRequest,
    ExcelFormulaAssistantRequest,
    ExcelSmartFillRequest,
)
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
from app.services.excel.formula_assistant import ExcelFormulaAssistant
from app.services.excel.formula_assistant_jobs import ExcelFormulaAssistantJobStore
from app.services.excel.smart_fill import ExcelSmartFill
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore


class ExcelPerformanceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = LongTaskCoordinator()
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_history_dir = os.environ.get("AI_WPS_TASK_HISTORY_DIR")
        os.environ["AI_WPS_TASK_HISTORY_DIR"] = os.path.join(self.temp_dir.name, "history")

    def tearDown(self):
        self.temp_dir.cleanup()
        if self._old_history_dir is None:
            os.environ.pop("AI_WPS_TASK_HISTORY_DIR", None)
        else:
            os.environ["AI_WPS_TASK_HISTORY_DIR"] = self._old_history_dir

    def test_excel_analysis_success_records_millisecond_metrics_and_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_excel_analysis(request, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 110,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 420,
                    "parseMs": 12,
                })
            if progress_callback:
                progress_callback("parsing")
            return {
                "structuredReport": {
                    "overview": "数据分析正常",
                    "findings": ["发现1"],
                    "risks": [],
                    "actions": ["动作1"],
                },
                "plainText": "分析报告正文",
                "provider": "direct-model",
            }

        fake_provider_client.excel_analysis.side_effect = fake_excel_analysis

        analyzer = ExcelAnalyzer(provider_client=fake_provider_client)
        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=self.coordinator)

        req = ExcelAnalysisRequest.parse_obj({
            "table": {
                "headers": ["月份", "销售额"],
                "rows": [["1月", "100"], ["2月", "200"]],
                "rowCount": 2,
                "columnCount": 2,
            },
            "scope": {"sheet_name": "Sheet1", "address": "A1:B3"},
            "clientJobId": "excel-analysis-perf-1",
        })

        res = store.start(req, trace_id="trace-ea-perf-1")
        self.assertEqual(res["jobId"], "excel-analysis-perf-1")

        completed = self.coordinator.wait("excel-analysis-perf-1", task_type="excel.analysis")
        self.assertEqual(completed["status"], "completed")

        # 毫秒级总耗时与阶段耗时
        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseElapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)
        # 秒级兼容字段保留
        self.assertIn("elapsedSeconds", completed)
        self.assertIn("phaseElapsedSeconds", completed)
        self.assertIn("phaseDurations", completed)

        # 真实阶段记录
        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)

        # 阻塞调用首包时间为 None
        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 110)
        self.assertEqual(metrics.get("providerCompleteMs"), 420)
        self.assertEqual(metrics.get("parseMs"), 12)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")

        # 终态诊断
        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "excel-analysis-perf-1"][0]
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "success")
        self.assertEqual(recent.get("errorCode"), "")
        self.assertIn("phaseDurationsMs", recent)

    def test_excel_analysis_timeout_records_real_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_timeout(request, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 200,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": None,
                    "parseMs": None,
                })
            raise ProviderTimeoutError("智能分析请求超时。")

        fake_provider_client.excel_analysis.side_effect = fake_timeout

        analyzer = ExcelAnalyzer(provider_client=fake_provider_client)
        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=self.coordinator)

        req = ExcelAnalysisRequest.parse_obj({
            "table": {
                "headers": ["月份", "销售额"],
                "rows": [["1月", "100"]],
                "rowCount": 1,
                "columnCount": 2,
            },
            "scope": {"sheet_name": "Sheet1", "address": "A1:B2"},
            "clientJobId": "excel-analysis-timeout-1",
        })

        store.start(req, trace_id="trace-ea-timeout-1")
        completed = self.coordinator.wait("excel-analysis-timeout-1", task_type="excel.analysis")
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["metrics"].get("providerOutcome"), "provider_timeout")
        self.assertEqual(completed.get("providerOutcome"), "provider_timeout")

        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "excel-analysis-timeout-1"][0]
        self.assertEqual(recent.get("providerOutcome"), "provider_timeout")
        self.assertEqual(recent.get("errorCode"), "PROVIDER_TIMEOUT")

    def test_excel_formula_assistant_success_records_millisecond_metrics_and_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        def fake_formula(request, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 95,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 350,
                    "parseMs": 10,
                })
            if progress_callback:
                progress_callback("parsing")
            return {
                "mode": "generate",
                "originalFormula": "",
                "primaryFormula": "=SUM(B2:B10)",
                "alternativeFormula": "",
                "suggestedTarget": "B11",
                "explanation": "求和公式",
                "components": [],
                "referenceRanges": ["B2:B10"],
                "issues": [],
                "assumptions": [],
                "compatibilityNotes": [],
                "provider": "direct-model",
            }

        fake_provider_client.excel_formula_assistant.side_effect = fake_formula

        assistant = ExcelFormulaAssistant(provider_client=fake_provider_client)
        store = ExcelFormulaAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req = ExcelFormulaAssistantRequest.parse_obj({
            "selection": {
                "sheetName": "Sheet1",
                "address": "B2:B3",
                "rowCount": 2,
                "columnCount": 1,
                "headers": ["金额"],
                "cells": [
                    [{"address": "B2", "text": "10", "valueType": "number"}],
                    [{"address": "B3", "text": "20", "valueType": "number"}],
                ],
                "sample_rows": [["10"], ["20"]],
                "truncated": False,
            },
            "options": {
                "mode": "generate",
                "requirement": "求总和",
            },
            "clientJobId": "excel-formula-perf-1",
        })

        res = store.start(req, trace_id="trace-ef-perf-1")
        self.assertEqual(res["jobId"], "excel-formula-perf-1")

        completed = self.coordinator.wait("excel-formula-perf-1", task_type="excel.formula_assistant")
        self.assertEqual(completed["status"], "completed")

        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseElapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)
        self.assertIn("elapsedSeconds", completed)

        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerHeadersMs"), 95)
        self.assertEqual(metrics.get("providerCompleteMs"), 350)
        self.assertEqual(metrics.get("parseMs"), 10)
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")

        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "excel-formula-perf-1"][0]
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "success")
        self.assertEqual(recent.get("errorCode"), "")

    def test_excel_formula_assistant_error_records_real_provider_outcome(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
        }

        def fake_error(request, trace_id, **kwargs):
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 50,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": None,
                    "parseMs": None,
                })
            raise AdapterError("PROVIDER_AUTH_FAILED", "认证失败", status_code=401)

        fake_provider_client.excel_formula_assistant.side_effect = fake_error

        assistant = ExcelFormulaAssistant(provider_client=fake_provider_client)
        store = ExcelFormulaAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req = ExcelFormulaAssistantRequest.parse_obj({
            "selection": {
                "sheetName": "Sheet1",
                "address": "B2:B3",
                "rowCount": 2,
                "columnCount": 1,
                "headers": ["金额"],
                "cells": [
                    [{"address": "B2", "text": "10", "valueType": "number"}],
                    [{"address": "B3", "text": "20", "valueType": "number"}],
                ],
                "sample_rows": [["10"]],
                "truncated": False,
            },
            "options": {
                "mode": "generate",
                "requirement": "求和",
            },
            "clientJobId": "excel-formula-err-1",
        })

        store.start(req, trace_id="trace-ef-err-1")
        completed = self.coordinator.wait("excel-formula-err-1", task_type="excel.formula_assistant")
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["metrics"].get("providerOutcome"), "provider_error")
        self.assertEqual(completed.get("providerOutcome"), "provider_error")

        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "excel-formula-err-1"][0]
        self.assertEqual(recent.get("providerOutcome"), "provider_error")
        self.assertEqual(recent.get("errorCode"), "PROVIDER_AUTH_FAILED")

    def test_excel_smart_fill_multi_batch_accumulates_metrics_and_records_aggregating(self):
        fake_provider_client = MagicMock()
        fake_provider_client.is_task_configured.return_value = True
        fake_provider_client.resolve_task_auth.return_value = {
            "accessMethod": "direct_model",
            "providerBaseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "modelName": "test-model",
            "streamingCapability": "unsupported",
        }

        call_count = [0]

        def fake_fill_batch(request, trace_id, **kwargs):
            call_count[0] += 1
            progress_callback = kwargs.get("progress_callback")
            if progress_callback and hasattr(progress_callback, "record_provider_attempt"):
                progress_callback.record_provider_attempt({
                    "providerHeadersMs": 50,
                    "providerFirstVisibleMs": None,
                    "providerCompleteMs": 200,
                    "parseMs": 10,
                })
            if progress_callback:
                progress_callback("parsing")
            return {
                "schemaVersion": "excel.smart_fill.v2",
                "items": [
                    {
                        "itemId": item.item_id,
                        "status": "completed",
                        "valueType": "text",
                        "value": f"填写_{item.item_id}",
                    }
                    for item in request.items
                ],
                "provider": "direct-model",
            }

        fake_provider_client.excel_smart_fill.side_effect = fake_fill_batch

        smart_fill = ExcelSmartFill(provider_client=fake_provider_client)
        store = ExcelSmartFillJobStore(smart_fill=smart_fill, coordinator=self.coordinator)

        # 4 items -> splits into 2 batches (2 + 2) based on default output token budget
        items = [{"itemId": f"sf_{i:032x}", "sourceRowIndex": i + 1} for i in range(4)]
        req = ExcelSmartFillRequest.parse_obj({
            "workbookId": "wb-1",
            "source": {
                "sheetName": "Sheet1",
                "address": "A1:B5",
                "headers": ["姓名", "部门"],
                "rows": [["张三", "技术"]] * 4,
                "rowCount": 4,
                "columnCount": 2,
            },
            "items": items,
            "userInstruction": "填写工号",
            "clientJobId": "excel-smart-fill-perf-1",
        })

        res = store.start(req, trace_id="trace-sf-perf-1")
        self.assertEqual(res["jobId"], "excel-smart-fill-perf-1")

        completed = self.coordinator.wait("excel-smart-fill-perf-1", task_type="excel.smart_fill")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(call_count[0], 2)

        self.assertIn("elapsedMs", completed)
        self.assertIn("phaseElapsedMs", completed)
        self.assertIn("phaseDurationsMs", completed)
        self.assertIn("queueWaitMs", completed)
        self.assertIn("elapsedSeconds", completed)

        phase_durations_ms = completed["phaseDurationsMs"]
        self.assertIn("chunking", phase_durations_ms)
        self.assertIn("preparing", phase_durations_ms)
        self.assertIn("provider_processing", phase_durations_ms)
        self.assertIn("parsing", phase_durations_ms)
        self.assertIn("aggregating", phase_durations_ms)

        metrics = completed["metrics"]
        self.assertEqual(metrics.get("providerAttempts"), 2)
        self.assertEqual(metrics.get("providerHeadersMs"), 100)  # 50 + 50
        self.assertEqual(metrics.get("providerCompleteMs"), 400)  # 200 + 200
        self.assertEqual(metrics.get("parseMs"), 20)  # 10 + 10
        self.assertIsNone(metrics.get("providerFirstVisibleMs"))
        self.assertEqual(metrics.get("providerOutcome"), "success")
        self.assertEqual(completed.get("providerOutcome"), "success")

        diagnostics = self.coordinator.diagnostics()
        recent = [j for j in diagnostics["recentTerminalJobs"] if j["jobId"] == "excel-smart-fill-perf-1"][0]
        self.assertEqual(recent["status"], "completed")
        self.assertEqual(recent.get("providerOutcome"), "success")
        self.assertEqual(recent.get("errorCode"), "")
