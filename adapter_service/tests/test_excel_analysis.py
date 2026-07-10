import importlib.util
import threading
import time
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import ExcelAnalysisRequest
    from app.services.excel.analyzer import ExcelAnalyzer

if HAS_PYDANTIC and HAS_FASTAPI:
    from app.api import excel as excel_api


def parse_excel_request(payload):
    if hasattr(ExcelAnalysisRequest, "model_validate"):
        return ExcelAnalysisRequest.model_validate(payload)
    return ExcelAnalysisRequest.parse_obj(payload)


def dump_excel_request(request):
    if hasattr(request, "model_dump"):
        return request.model_dump(by_alias=True)
    return request.dict(by_alias=True)


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


class RecordingExcelAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, request, trace_id):
        self.calls.append({"request": request, "traceId": trace_id})
        return {
            "structuredReport": {
                "overview": "路由概览",
                "findings": ["路由发现"],
                "risks": [],
                "actions": ["路由建议"],
            },
            "plainText": "路由纯文本",
            "provider": "route-test",
        }


class BlockingExcelAnalyzer:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def analyze(self, request, trace_id):
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {
            "structuredReport": {
                "overview": "后台分析完成。",
                "findings": [],
                "risks": [],
                "actions": [],
            },
            "plainText": "后台分析完成。",
            "provider": "job-test",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for excel analysis tests")
class ExcelAnalysisTests(unittest.TestCase):
    def _request(self, headers=None, rows=None, requirement="关注异常。", client_job_id=""):
        return parse_excel_request(
            {
                "workbookId": "analysis.xlsx",
                "scene": "excel",
                "clientJobId": client_job_id,
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

    def test_excel_analysis_job_store_is_idempotent_and_completes_in_background(self):
        self.assertIsNotNone(
            importlib.util.find_spec("app.services.excel.analysis_jobs"),
            "Excel 智能分析需要后台任务存储，避免前台长连接超时。",
        )
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

        analyzer = BlockingExcelAnalyzer()
        store = ExcelAnalysisJobStore(analyzer=analyzer)
        request = self._request(client_job_id="client-excel-analysis-recovery")

        started = store.start(request, trace_id="trace-excel-first")
        duplicate = store.start(request, trace_id="trace-excel-second")

        self.assertEqual(started["jobId"], "client-excel-analysis-recovery")
        self.assertEqual(duplicate["traceId"], "trace-excel-first")
        self.assertEqual(duplicate["status"], "running")
        self.assertEqual(duplicate["providerTimeoutSeconds"], 1800)
        self.assertIn("模型后台", duplicate["runningMessage"])
        self.assertTrue(analyzer.started.wait(timeout=1))
        self.assertEqual(analyzer.call_count, 1)

        analyzer.release.set()
        completed = None
        for _ in range(50):
            completed = store.get("client-excel-analysis-recovery")
            if completed and completed["status"] == "completed":
                break
            time.sleep(0.02)

        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["plainText"], "后台分析完成。")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for excel route tests")
    def test_fastapi_route_returns_excel_analysis_envelope(self):
        analyzer = RecordingExcelAnalyzer()
        original_analyzer = excel_api.excel_analyzer
        excel_api.excel_analyzer = analyzer
        try:
            response = excel_api.excel_analysis(self._request())
        finally:
            excel_api.excel_analyzer = original_analyzer

        self.assertTrue(response["success"])
        self.assertEqual(response["taskType"], "excel.analysis")
        self.assertEqual(response["message"], "completed")
        self.assertEqual(response["data"]["structuredReport"]["overview"], "路由概览")
        self.assertEqual(response["data"]["plainText"], "路由纯文本")
        self.assertEqual(response["errors"], [])

    def test_standalone_excel_analysis_returns_response_data(self):
        import standalone_adapter

        class FakeStandaloneAnalyzer:
            def analyze(self, request, trace_id):
                self.request = request
                self.trace_id = trace_id
                return {
                    "structuredReport": {
                        "overview": "standalone 概览",
                        "findings": ["standalone 发现"],
                        "risks": [],
                        "actions": ["standalone 建议"],
                    },
                    "plainText": "standalone 纯文本",
                    "provider": "standalone-test",
                }

        original_analyzer = standalone_adapter.ExcelAnalyzer
        standalone_adapter.ExcelAnalyzer = FakeStandaloneAnalyzer
        try:
            result = standalone_adapter.excel_analysis(dump_excel_request(self._request()))
        finally:
            standalone_adapter.ExcelAnalyzer = original_analyzer

        self.assertEqual(result["structuredReport"]["overview"], "standalone 概览")
        self.assertEqual(result["plainText"], "standalone 纯文本")
        self.assertEqual(result["provider"], "standalone-test")


if __name__ == "__main__":
    unittest.main()
