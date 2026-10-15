import importlib.util
import json
import time
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.models import (
        ExcelAnalysisRequest,
        ExcelFormulaAssistantRequest,
        ExcelFormulaSelection,
        ExcelFormulaOptions,
        ExcelSmartFillRequest,
    )
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.excel.analyzer import ExcelAnalyzer
    from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
    from app.services.excel.formula_assistant import ExcelFormulaAssistant
    from app.services.excel.formula_assistant_jobs import ExcelFormulaAssistantJobStore
    from app.services.excel.smart_fill import ExcelSmartFill
    from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore


class MockAnalyzer(ExcelAnalyzer):
    def __init__(self):
        self.call_count = 0
        self.provider_client = None

    def analyze(self, request, trace_id, task_auth=None, progress_callback=None):
        self.call_count += 1
        return {
            "structuredReport": {
                "overview": f"分析运行 #{self.call_count}",
                "findings": ["发现1"],
                "risks": [],
                "actions": [],
            },
            "plainText": f"分析运行 #{self.call_count}",
        }


class MockFormulaAssistant(ExcelFormulaAssistant):
    def __init__(self):
        self.call_count = 0
        self.provider_client = None

    def generate(self, request, trace_id, task_auth=None, progress_callback=None):
        self.call_count += 1
        return {
            "mode": "generate",
            "primaryFormula": f"=SUM(A1:A{self.call_count})",
            "explanation": f"公式计算 #{self.call_count}",
        }


class MockSmartFill(ExcelSmartFill):
    def __init__(self):
        self.call_count = 0
        self.provider_client = None

    def fill_batch(self, batch, trace_id, progress_callback=None, **kwargs):
        self.call_count += 1
        return {
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": f"填充值 #{self.call_count}",
                    "confidence": 0.95,
                    "reasoning": "根据前两列生成",
                }
                for item in batch.items
            ],
            "provider": "mock",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required")
class TestExcelRegenerateTasks(unittest.TestCase):
    def setUp(self):
        self.coordinator = LongTaskCoordinator()

    def test_excel_analysis_regenerate_creates_new_job_and_executes(self):
        analyzer = MockAnalyzer()
        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=self.coordinator)

        req_payload = {
            "workbookId": "wb-test",
            "documentSessionId": "session-analysis-1",
            "documentDisplayName": "测试表.xlsx",
            "host": "et",
            "table": {"headers": ["A", "B"], "rows": [["1", "2"]]},
        }

        # 1. First run with client_job_id="job_ana_001"
        req1 = ExcelAnalysisRequest(**req_payload, clientJobId="job_ana_001")
        job1 = store.start(req1, "trace-1")
        self.assertEqual(job1["jobId"], "job_ana_001")

        # Wait for job1 to complete
        for _ in range(50):
            j = store.get("job_ana_001")
            if j and j.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j["status"], "completed")
        self.assertEqual(analyzer.call_count, 1)
        self.assertEqual(j["result"]["plainText"], "分析运行 #1")

        # 2. Idempotent retry with same client_job_id="job_ana_001"
        req_retry = ExcelAnalysisRequest(**req_payload, clientJobId="job_ana_001")
        job_retry = store.start(req_retry, "trace-retry")
        self.assertEqual(job_retry["jobId"], "job_ana_001")
        self.assertEqual(job_retry["status"], "completed")
        self.assertEqual(analyzer.call_count, 1)  # No duplicate execution!

        # 3. Regenerate with identical data but new client_job_id="job_ana_002"
        req2 = ExcelAnalysisRequest(**req_payload, clientJobId="job_ana_002")
        job2 = store.start(req2, "trace-2")
        self.assertEqual(job2["jobId"], "job_ana_002")

        for _ in range(50):
            j2 = store.get("job_ana_002")
            if j2 and j2.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j2["status"], "completed")
        self.assertEqual(analyzer.call_count, 2)  # Re-executed!
        self.assertEqual(j2["result"]["plainText"], "分析运行 #2")

    def test_excel_formula_regenerate_creates_new_job_and_executes(self):
        assistant = MockFormulaAssistant()
        store = ExcelFormulaAssistantJobStore(assistant=assistant, coordinator=self.coordinator)

        req_payload = {
            "workbookId": "wb-test",
            "documentSessionId": "session-formula-1",
            "documentDisplayName": "公式表.xlsx",
            "host": "et",
            "selection": ExcelFormulaSelection(address="A1:A5", sheetName="Sheet1"),
            "options": ExcelFormulaOptions(mode="generate", requirement="计算总额"),
        }

        # 1. First run with client_job_id="job_form_001"
        req1 = ExcelFormulaAssistantRequest(**req_payload, clientJobId="job_form_001")
        job1 = store.start(req1, "trace-form-1")
        self.assertEqual(job1["jobId"], "job_form_001")

        for _ in range(50):
            j = store.get("job_form_001")
            if j and j.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j["status"], "completed")
        self.assertEqual(assistant.call_count, 1)
        self.assertEqual(j["result"]["primaryFormula"], "=SUM(A1:A1)")

        # 2. Idempotent retry with same client_job_id="job_form_001"
        req_retry = ExcelFormulaAssistantRequest(**req_payload, clientJobId="job_form_001")
        job_retry = store.start(req_retry, "trace-retry")
        self.assertEqual(job_retry["jobId"], "job_form_001")
        self.assertEqual(assistant.call_count, 1)

        # 3. Regenerate with identical data but new client_job_id="job_form_002"
        req2 = ExcelFormulaAssistantRequest(**req_payload, clientJobId="job_form_002")
        job2 = store.start(req2, "trace-form-2")
        self.assertEqual(job2["jobId"], "job_form_002")

        for _ in range(50):
            j2 = store.get("job_form_002")
            if j2 and j2.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j2["status"], "completed")
        self.assertEqual(assistant.call_count, 2)
        self.assertEqual(j2["result"]["primaryFormula"], "=SUM(A1:A2)")

    def test_excel_smart_fill_regenerate_creates_new_job_and_executes(self):
        smart_fill = MockSmartFill()
        store = ExcelSmartFillJobStore(smart_fill=smart_fill, coordinator=self.coordinator)

        req_payload = {
            "workbookId": "wb-test",
            "documentSessionId": "session-fill-1",
            "documentDisplayName": "填充表.xlsx",
            "host": "et",
            "items": [
                {
                    "itemId": "sf_00000000000000000000000000000001",
                    "sourceRowIndex": 1,
                    "sourceRowLabel": "第 2 行",
                }
            ],
            "source": {
                "sheetName": "Sheet1",
                "address": "A1:C2",
                "headers": ["A", "B", "C"],
                "rows": [["1", "2", "3"]],
                "rowCount": 1,
                "columnCount": 3,
                "truncated": False,
            },
            "userInstruction": "补齐分类",
        }

        # 1. First run
        req1 = ExcelSmartFillRequest(**req_payload, clientJobId="job_fill_001")
        job1 = store.start(req1, "trace-fill-1")
        self.assertEqual(job1["jobId"], "job_fill_001")

        for _ in range(50):
            j = store.get("job_fill_001")
            if j and j.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j["status"], "completed")
        self.assertEqual(smart_fill.call_count, 1)

        # 2. Idempotent retry
        req_retry = ExcelSmartFillRequest(**req_payload, clientJobId="job_fill_001")
        job_retry = store.start(req_retry, "trace-retry")
        self.assertEqual(job_retry["jobId"], "job_fill_001")
        self.assertEqual(smart_fill.call_count, 1)

        # 3. Regenerate with new clientJobId
        req2 = ExcelSmartFillRequest(**req_payload, clientJobId="job_fill_002")
        job2 = store.start(req2, "trace-fill-2")
        self.assertEqual(job2["jobId"], "job_fill_002")

        for _ in range(50):
            j2 = store.get("job_fill_002")
            if j2 and j2.get("status") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(j2["status"], "completed")
        self.assertEqual(smart_fill.call_count, 2)


if __name__ == "__main__":
    unittest.main()
