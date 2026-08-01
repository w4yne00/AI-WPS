import importlib.util
import json
import threading
import time
import unittest
from copy import deepcopy
from io import BytesIO

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import ExcelAnalysisRequest
    from app.services.excel.analyzer import ExcelAnalyzer
    from app.services.long_task_coordinator import LongTaskCoordinator

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
        self.current_auth = {
            "workflowProfileId": "profile-excel-a",
            "apiKey": "secret-excel-a",
        }

    def resolve_task_auth(self, task_type):
        self.resolved_task_type = task_type
        return deepcopy(self.current_auth)

    def excel_analysis(
        self,
        request,
        trace_id,
        task_auth=None,
        progress_callback=None,
    ):
        self.calls.append(
            {
                "request": request,
                "traceId": trace_id,
                "taskAuth": task_auth,
            }
        )
        if progress_callback:
            progress_callback("parsing")
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

    def analyze(self, request, trace_id, task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        self.calls.append({"request": request, "traceId": trace_id})
        if progress_callback:
            progress_callback("parsing")
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

    def analyze(self, request, trace_id, task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        if progress_callback:
            progress_callback("parsing")
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


class SnapshotExcelAnalyzer:
    def __init__(self):
        self.current_auth = {
            "workflowProfileId": "profile-excel-a",
            "apiKey": "secret-excel-a",
        }
        self.snapshot_count = 0
        self.calls = []

    def snapshot_task_auth(self):
        self.snapshot_count += 1
        return deepcopy(self.current_auth)

    def analyze(self, request, trace_id, task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        self.calls.append(
            {
                "request": request,
                "traceId": trace_id,
                "taskAuth": task_auth,
            }
        )
        if progress_callback:
            progress_callback("parsing")
        return {
            "structuredReport": {
                "overview": "快照分析完成。",
                "findings": [],
                "risks": [],
                "actions": [],
            },
            "plainText": "快照分析完成。",
            "provider": "snapshot-test",
        }


def wait_for_excel_job(store, job_id, expected="completed", timeout=2):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest = store.get(job_id)
        if latest and latest["status"] == expected:
            return latest
        time.sleep(0.01)
    raise AssertionError(
        "excel job {0} did not reach {1}; latest={2}".format(
            job_id, expected, latest
        )
    )


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

    def test_excel_analysis_freezes_task_auth_and_reports_real_phases(self):
        provider = RecordingExcelProvider()
        analyzer = ExcelAnalyzer(provider_client=provider)
        task_auth = analyzer.snapshot_task_auth()
        provider.current_auth.update(
            workflowProfileId="profile-excel-b",
            apiKey="secret-excel-b",
        )
        phases = []

        analyzer.analyze(
            self._request(),
            trace_id="trace-excel-phases",
            task_auth=task_auth,
            progress_callback=phases.append,
        )

        self.assertEqual(provider.resolved_task_type, "excel.analysis")
        self.assertEqual(
            provider.calls[0]["taskAuth"]["workflowProfileId"],
            "profile-excel-a",
        )
        self.assertEqual(provider.calls[0]["taskAuth"]["apiKey"], "secret-excel-a")
        self.assertEqual(
            phases,
            ["preparing", "provider_processing", "parsing"],
        )

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

    def test_excel_jobs_share_global_fifo_capacity_and_freeze_queued_input(self):
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        analyzer = SnapshotExcelAnalyzer()

        def blocking_word_runner(snapshot, progress):
            blocker_started.set()
            release_blocker.wait(timeout=2)
            return {"summary": "word completed"}

        coordinator.submit(
            job_id="client-word-running",
            trace_id="trace-word-running",
            task_type="word.document_review",
            runner=blocking_word_runner,
            snapshot={},
            failure_code="DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="文档审查后台任务执行失败。",
        )
        self.assertTrue(blocker_started.wait(timeout=1))

        store = ExcelAnalysisJobStore(analyzer=analyzer, coordinator=coordinator)
        request = self._request(client_job_id="client-excel-shared-queue")
        queued = store.start(request, trace_id="trace-excel-shared-first")
        request.table.rows[0][0] = "提交后修改"
        analyzer.current_auth.update(
            workflowProfileId="profile-excel-b",
            apiKey="secret-excel-b",
        )
        duplicate = store.start(request, trace_id="trace-excel-shared-second")

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["phase"], "queued")
        self.assertEqual(queued["queuePosition"], 1)
        self.assertTrue(queued["canCancel"])
        self.assertEqual(duplicate["traceId"], "trace-excel-shared-first")
        self.assertEqual(analyzer.calls, [])
        self.assertEqual(analyzer.snapshot_count, 1)
        self.assertNotIn("secret-excel-a", json.dumps(queued, ensure_ascii=False))

        release_blocker.set()
        completed = wait_for_excel_job(store, "client-excel-shared-queue")

        self.assertEqual(completed["phase"], "completed")
        self.assertIn("provider_processing", completed["phaseDurations"])
        self.assertIn("parsing", completed["phaseDurations"])
        self.assertEqual(len(analyzer.calls), 1)
        self.assertEqual(
            analyzer.calls[0]["request"].table.rows[0][0],
            "项目A",
        )
        self.assertEqual(
            analyzer.calls[0]["taskAuth"]["workflowProfileId"],
            "profile-excel-a",
        )
        self.assertEqual(
            analyzer.calls[0]["taskAuth"]["apiKey"],
            "secret-excel-a",
        )
        self.assertNotIn(
            "secret-excel-a",
            json.dumps(completed, ensure_ascii=False),
        )

    def test_excel_job_identity_is_namespaced_from_other_task_types(self):
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
        word_started = threading.Event()
        release_word = threading.Event()

        def blocking_word_runner(snapshot, progress):
            word_started.set()
            release_word.wait(timeout=2)
            return {"summary": "word completed"}

        coordinator.submit(
            job_id="client-shared-visible-id",
            trace_id="trace-word-same-id",
            task_type="word.document_review",
            runner=blocking_word_runner,
            snapshot={},
            failure_code="DOCUMENT_REVIEW_JOB_FAILED",
            failure_message="文档审查后台任务执行失败。",
        )
        self.assertTrue(word_started.wait(timeout=1))
        store = ExcelAnalysisJobStore(
            analyzer=SnapshotExcelAnalyzer(),
            coordinator=coordinator,
        )

        excel_job = store.start(
            self._request(client_job_id="client-shared-visible-id"),
            trace_id="trace-excel-same-id",
        )
        cancelled = store.cancel("client-shared-visible-id")
        word_job = coordinator.get(
            "client-shared-visible-id",
            task_type="word.document_review",
        )

        self.assertEqual(excel_job["traceId"], "trace-excel-same-id")
        self.assertEqual(excel_job["status"], "queued")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(word_job["traceId"], "trace-word-same-id")
        self.assertEqual(word_job["status"], "running")
        release_word.set()

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for route contract tests")
    def test_fastapi_excel_jobs_report_shared_queue_and_chinese_capacity_error(self):
        from app.main import app
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
        from fastapi.testclient import TestClient

        analyzer = BlockingExcelAnalyzer()
        store = ExcelAnalysisJobStore(
            analyzer=analyzer,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )
        original_store = excel_api.excel_analysis_jobs
        excel_api.excel_analysis_jobs = store
        client = TestClient(app)
        try:
            running = client.post(
                "/excel/analysis/jobs",
                json=dump_excel_request(
                    self._request(client_job_id="client-fastapi-excel-running")
                ),
            )
            self.assertTrue(analyzer.started.wait(timeout=1))
            queued = client.post(
                "/excel/analysis/jobs",
                json=dump_excel_request(
                    self._request(client_job_id="client-fastapi-excel-queued")
                ),
            )
            full = client.post(
                "/excel/analysis/jobs",
                json=dump_excel_request(
                    self._request(client_job_id="client-fastapi-excel-full")
                ),
            )
            sync_full = client.post(
                "/excel/analysis",
                json=dump_excel_request(
                    self._request(client_job_id="client-fastapi-excel-sync-full")
                ),
            )
            cancelled = client.delete(
                "/excel/analysis/jobs/client-fastapi-excel-queued"
            )
            running_cancel = client.delete(
                "/excel/analysis/jobs/client-fastapi-excel-running"
            )
            interrupted = client.get(
                "/excel/analysis/jobs/client-fastapi-excel-missing?resume=1"
            )
        finally:
            analyzer.release.set()
            excel_api.excel_analysis_jobs = original_store

        self.assertEqual(running.status_code, 200)
        self.assertEqual(running.json()["data"]["status"], "running")
        self.assertEqual(queued.json()["data"]["status"], "queued")
        self.assertEqual(queued.json()["data"]["queuePosition"], 1)
        self.assertEqual(full.status_code, 429)
        self.assertEqual(full.json()["errors"][0]["code"], "LONG_TASK_QUEUE_FULL")
        self.assertIn("排队已满", full.json()["message"])
        self.assertEqual(sync_full.status_code, 429)
        self.assertEqual(
            sync_full.json()["errors"][0]["code"], "LONG_TASK_QUEUE_FULL"
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["message"], "cancelled")
        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
        self.assertEqual(running_cancel.status_code, 409)
        self.assertEqual(running_cancel.json()["taskType"], "excel.analysis")
        self.assertEqual(
            running_cancel.json()["errors"][0]["code"],
            "LONG_TASK_NOT_CANCELLABLE",
        )
        self.assertEqual(interrupted.status_code, 404)
        self.assertEqual(
            interrupted.json()["errors"][0]["code"],
            "EXCEL_ANALYSIS_JOB_INTERRUPTED",
        )
        self.assertIn("adapter 重启", interrupted.json()["message"])
        self.assertEqual(interrupted.json()["data"]["status"], "failed")

    def test_standalone_excel_job_routes_match_queue_capacity_and_cancel_contract(self):
        import standalone_adapter
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

        analyzer = BlockingExcelAnalyzer()
        store = ExcelAnalysisJobStore(
            analyzer=analyzer,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=1),
        )
        original_store = standalone_adapter.EXCEL_ANALYSIS_JOB_STORE
        standalone_adapter.EXCEL_ANALYSIS_JOB_STORE = store

        def invoke(method, path, payload=None):
            raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            captured = {}
            handler = object.__new__(standalone_adapter.Handler)
            handler.path = path
            handler.headers = {"Content-Length": str(len(raw))}
            handler.rfile = BytesIO(raw)
            handler._write = lambda status, body: captured.update(
                status=status, body=body
            )
            getattr(handler, method)()
            return captured

        try:
            running = invoke(
                "do_POST",
                "/excel/analysis/jobs",
                dump_excel_request(
                    self._request(client_job_id="client-standalone-excel-running")
                ),
            )
            self.assertTrue(analyzer.started.wait(timeout=1))
            queued = invoke(
                "do_POST",
                "/excel/analysis/jobs",
                dump_excel_request(
                    self._request(client_job_id="client-standalone-excel-queued")
                ),
            )
            full = invoke(
                "do_POST",
                "/excel/analysis/jobs",
                dump_excel_request(
                    self._request(client_job_id="client-standalone-excel-full")
                ),
            )
            sync_full = invoke(
                "do_POST",
                "/excel/analysis",
                dump_excel_request(
                    self._request(client_job_id="client-standalone-excel-sync-full")
                ),
            )
            cancelled = invoke(
                "do_DELETE",
                "/excel/analysis/jobs/client-standalone-excel-queued",
            )
            invalid = invoke(
                "do_POST",
                "/excel/analysis/jobs",
                {"table": "invalid-table-shape"},
            )
            interrupted = invoke(
                "do_GET",
                "/excel/analysis/jobs/client-standalone-excel-missing?resume=1",
            )
        finally:
            analyzer.release.set()
            standalone_adapter.EXCEL_ANALYSIS_JOB_STORE = original_store

        self.assertEqual(running["body"]["data"]["status"], "running")
        self.assertEqual(queued["body"]["data"]["status"], "queued")
        self.assertEqual(full["status"], 429)
        self.assertEqual(
            full["body"]["errors"][0]["code"],
            "LONG_TASK_QUEUE_FULL",
        )
        self.assertIn("排队已满", full["body"]["message"])
        self.assertEqual(sync_full["status"], 429)
        self.assertEqual(
            sync_full["body"]["errors"][0]["code"],
            "LONG_TASK_QUEUE_FULL",
        )
        self.assertEqual(cancelled["status"], 200)
        self.assertEqual(cancelled["body"]["message"], "cancelled")
        self.assertEqual(cancelled["body"]["data"]["status"], "cancelled")
        self.assertEqual(invalid["status"], 422)
        self.assertEqual(invalid["body"]["taskType"], "excel.analysis")
        self.assertEqual(
            invalid["body"]["errors"][0]["code"],
            "REQUEST_VALIDATION_FAILED",
        )
        self.assertEqual(interrupted["status"], 404)
        self.assertEqual(
            interrupted["body"]["errors"][0]["code"],
            "EXCEL_ANALYSIS_JOB_INTERRUPTED",
        )
        self.assertIn("adapter 重启", interrupted["body"]["message"])

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for excel route tests")
    def test_fastapi_route_returns_excel_analysis_envelope(self):
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore

        analyzer = RecordingExcelAnalyzer()
        original_store = excel_api.excel_analysis_jobs
        excel_api.excel_analysis_jobs = ExcelAnalysisJobStore(
            analyzer=analyzer,
            coordinator=LongTaskCoordinator(),
        )
        try:
            response = excel_api.excel_analysis(self._request())
        finally:
            excel_api.excel_analysis_jobs = original_store

        self.assertTrue(response["success"])
        self.assertEqual(response["taskType"], "excel.analysis")
        self.assertEqual(response["message"], "completed")
        self.assertEqual(response["data"]["structuredReport"]["overview"], "路由概览")
        self.assertEqual(response["data"]["plainText"], "路由纯文本")
        self.assertEqual(response["errors"], [])

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for excel route tests")
    def test_sync_routes_preserve_safe_business_validation_error(self):
        import standalone_adapter
        from app.main import app
        from app.services.excel.analysis_jobs import ExcelAnalysisJobStore
        from fastapi.testclient import TestClient

        payload = dump_excel_request(
            self._request(client_job_id="client-sync-empty-table-fastapi")
        )
        payload["table"]["headers"] = []
        payload["table"]["rows"] = []
        payload["table"]["rowCount"] = 0
        store = ExcelAnalysisJobStore(
            analyzer=ExcelAnalyzer(),
            coordinator=LongTaskCoordinator(),
        )
        original_fastapi_store = excel_api.excel_analysis_jobs
        original_standalone_store = standalone_adapter.EXCEL_ANALYSIS_JOB_STORE
        excel_api.excel_analysis_jobs = store
        standalone_adapter.EXCEL_ANALYSIS_JOB_STORE = store

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/excel/analysis"
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(
            status=status, body=body
        )
        try:
            fastapi_response = TestClient(app).post("/excel/analysis", json=payload)
            handler.do_POST()
        finally:
            excel_api.excel_analysis_jobs = original_fastapi_store
            standalone_adapter.EXCEL_ANALYSIS_JOB_STORE = original_standalone_store

        self.assertEqual(fastapi_response.status_code, 400)
        self.assertEqual(captured["status"], 400)
        self.assertEqual(
            fastapi_response.json()["errors"][0]["code"],
            "EXCEL_ANALYSIS_TABLE_REQUIRED",
        )
        self.assertEqual(
            captured["body"]["errors"][0]["code"],
            "EXCEL_ANALYSIS_TABLE_REQUIRED",
        )

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
