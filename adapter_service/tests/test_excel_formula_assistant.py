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
    from app.core.config import AppSettings
    from app.core.errors import AdapterError
    from app.core.models import ExcelFormulaAssistantRequest
    from app.services.excel.formula_assistant import ExcelFormulaAssistant
    from app.services.excel.formula_assistant_jobs import ExcelFormulaAssistantJobStore
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.provider_client import ProviderClient, parse_excel_formula_answer


def parse_formula_request(payload):
    if hasattr(ExcelFormulaAssistantRequest, "model_validate"):
        return ExcelFormulaAssistantRequest.model_validate(payload)
    return ExcelFormulaAssistantRequest.parse_obj(payload)


def dump_formula_request(request):
    if hasattr(request, "model_dump"):
        return request.model_dump(by_alias=True)
    return request.dict(by_alias=True)


class RecordingFormulaProvider:
    def __init__(self):
        self.calls = []
        self.current_auth = {
            "workflowProfileId": "profile-formula-a",
            "apiKey": "secret-formula-a",
        }

    def resolve_task_auth(self, task_type):
        self.resolved_task_type = task_type
        return deepcopy(self.current_auth)

    def excel_formula_assistant(
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
            "primaryFormula": "=SUM(B2:B3)",
            "suggestedTarget": "B4",
            "explanation": "汇总 B2 至 B3 的金额。",
            "assumptions": ["首行为表头。"],
            "compatibilityNotes": ["SUM 可用于当前 WPS 版本。"],
            "copyText": "=AVERAGE(B2:B3)",
            "provider": "enterprise-dify-chat/task-file",
        }


class BlockingFormulaAssistant:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def snapshot_task_auth(self):
        return {
            "workflowProfileId": "profile-formula-a",
            "apiKey": "secret-formula-a",
        }

    def generate(self, request, trace_id, task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        if progress_callback:
            progress_callback("parsing")
        return {
            "primaryFormula": "=SUM(B2:B3)",
            "suggestedTarget": "B4",
            "explanation": "汇总金额。",
            "assumptions": [],
            "compatibilityNotes": [],
            "copyText": "=SUM(B2:B3)",
            "provider": "job-test",
        }


def wait_for_job(store, job_id, expected="completed", timeout=2):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest = store.get(job_id)
        if latest and latest["status"] == expected:
            return latest
        time.sleep(0.01)
    raise AssertionError(
        "formula job {0} did not reach {1}; latest={2}".format(
            job_id, expected, latest
        )
    )


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for formula assistant tests")
class ExcelFormulaAssistantTests(unittest.TestCase):
    def _request(self, requirement="汇总金额。", client_job_id=""):
        return parse_formula_request(
            {
                "workbookId": "formula.xlsx",
                "scene": "excel",
                "clientJobId": client_job_id,
                "selection": {
                    "sheetName": "Sheet1",
                    "address": "$A$1:$C$3",
                    "headers": ["项目", "金额", "状态"],
                    "rowCount": 3,
                    "columnCount": 3,
                    "truncated": False,
                    "cells": [
                        [
                            {"address": "$A$1", "text": "项目", "valueType": "text", "formula": ""},
                            {"address": "$B$1", "text": "金额", "valueType": "text", "formula": ""},
                            {"address": "$C$1", "text": "状态", "valueType": "text", "formula": ""},
                        ],
                        [
                            {"address": "$A$2", "text": "项目A", "valueType": "text", "formula": ""},
                            {"address": "$B$2", "text": "100", "valueType": "number", "formula": ""},
                            {"address": "$C$2", "text": "正常", "valueType": "text", "formula": ""},
                        ],
                        [
                            {"address": "$A$3", "text": "项目B", "valueType": "text", "formula": ""},
                            {"address": "$B$3", "text": "300", "valueType": "formula", "formula": "=100+200"},
                            {"address": "$C$3", "text": "异常", "valueType": "text", "formula": ""},
                        ],
                    ],
                },
                "options": {"requirement": requirement},
            }
        )

    def test_formula_generation_uses_independent_task_and_structured_result(self):
        provider = RecordingFormulaProvider()
        assistant = ExcelFormulaAssistant(provider_client=provider)
        task_auth = assistant.snapshot_task_auth()

        result = assistant.generate(
            self._request(),
            trace_id="trace-formula",
            task_auth=task_auth,
        )

        self.assertEqual(provider.resolved_task_type, "excel.formula_assistant")
        self.assertEqual(provider.calls[0]["traceId"], "trace-formula")
        self.assertEqual(
            provider.calls[0]["request"].selection.cells[2][1].formula,
            "=100+200",
        )
        self.assertEqual(result["primaryFormula"], "=SUM(B2:B3)")
        self.assertEqual(result["suggestedTarget"], "B4")
        self.assertEqual(result["copyText"], "=SUM(B2:B3)")

    def test_formula_generation_requires_requirement_and_explicit_selection(self):
        assistant = ExcelFormulaAssistant(provider_client=RecordingFormulaProvider())

        with self.assertRaises(AdapterError) as missing_requirement:
            assistant.generate(
                self._request(requirement=""),
                trace_id="trace-formula-requirement",
            )
        self.assertEqual(
            missing_requirement.exception.code,
            "EXCEL_FORMULA_REQUIREMENT_REQUIRED",
        )

        request = self._request()
        request.selection.address = ""
        request.selection.cells = []
        with self.assertRaises(AdapterError) as missing_selection:
            assistant.generate(request, trace_id="trace-formula-selection")
        self.assertEqual(
            missing_selection.exception.code,
            "EXCEL_FORMULA_SELECTION_REQUIRED",
        )

    def test_formula_generation_rejects_context_larger_than_capture_budget(self):
        assistant = ExcelFormulaAssistant(provider_client=RecordingFormulaProvider())
        request = self._request()
        request.selection.cells = request.selection.cells * 11

        with self.assertRaises(AdapterError) as oversized:
            assistant.generate(request, trace_id="trace-formula-oversized")

        self.assertEqual(oversized.exception.code, "EXCEL_FORMULA_SELECTION_TOO_LARGE")

    def test_formula_generation_derives_truncation_from_original_dimensions(self):
        provider = RecordingFormulaProvider()
        assistant = ExcelFormulaAssistant(provider_client=provider)
        request = self._request()
        request.selection.row_count = 31
        request.selection.truncated = False

        assistant.generate(request, trace_id="trace-formula-derived-truncation")

        self.assertTrue(provider.calls[0]["request"].selection.truncated)

    def test_structured_provider_answer_only_accepts_one_executable_formula(self):
        valid = parse_excel_formula_answer(
            '{"primaryFormula":"=SUM(B2:B3)","compatibilityNotes":[]}'
        )
        missing_equals = parse_excel_formula_answer(
            '{"primaryFormula":"SUM(B2:B3)","compatibilityNotes":[]}'
        )
        multiple_lines = parse_excel_formula_answer(
            '{"primaryFormula":"=SUM(B2:B3)\\n=AVERAGE(B2:B3)",'
            '"compatibilityNotes":[]}'
        )

        self.assertEqual(valid["primaryFormula"], "=SUM(B2:B3)")
        self.assertEqual(valid["copyText"], "=SUM(B2:B3)")
        self.assertEqual(missing_equals["primaryFormula"], "")
        self.assertEqual(missing_equals["copyText"], "")
        self.assertEqual(multiple_lines["primaryFormula"], "")
        self.assertTrue(missing_equals["compatibilityNotes"])

    def test_provider_uses_formula_task_timeout_and_filters_think_output(self):
        class CapturingProviderClient(ProviderClient):
            def __init__(self):
                super().__init__(
                    AppSettings(
                        provider_base_url="http://provider.example/v1",
                        task_api_key_refs={"excel.formula_assistant": "formula"},
                    )
                )
                self.posted = None

            def is_task_configured(self, task_type):
                return True

            def get_auth_source_for_task(self, task_type):
                return "task-file"

            def post_task(
                self,
                task_type,
                trace_id,
                input_data,
                query,
                timeout_seconds=None,
            ):
                self.posted = {
                    "taskType": task_type,
                    "traceId": trace_id,
                    "input": input_data,
                    "query": query,
                    "timeoutSeconds": timeout_seconds,
                }
                return {
                    "answer": (
                        '<think>internal chain</think>{"primaryFormula":"=SUM(B2:B3)",'
                        '"suggestedTarget":"B4","explanation":"汇总金额",'
                        '"assumptions":[],"compatibilityNotes":["WPS 可用"]}'
                    )
                }

        provider = CapturingProviderClient()
        result = provider.excel_formula_assistant(
            self._request(),
            trace_id="trace-formula-provider",
        )

        self.assertEqual(provider.posted["taskType"], "excel.formula_assistant")
        self.assertEqual(provider.posted["timeoutSeconds"], 1800)
        self.assertIn("$B$3", provider.posted["query"])
        self.assertIn("=100+200", provider.posted["query"])
        self.assertNotIn("internal chain", str(result))
        self.assertEqual(result["primaryFormula"], "=SUM(B2:B3)")

    def test_formula_jobs_use_shared_queue_and_only_queued_jobs_cancel(self):
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)

        def blocking_analysis(snapshot, progress):
            blocker_started.set()
            release_blocker.wait(timeout=2)
            return {"plainText": "analysis completed"}

        coordinator.submit(
            job_id="client-analysis-running",
            trace_id="trace-analysis-running",
            task_type="excel.analysis",
            runner=blocking_analysis,
            snapshot={},
            failure_code="EXCEL_ANALYSIS_JOB_FAILED",
            failure_message="智能分析后台任务执行失败。",
        )
        self.assertTrue(blocker_started.wait(timeout=1))

        assistant = BlockingFormulaAssistant()
        store = ExcelFormulaAssistantJobStore(
            assistant=assistant,
            coordinator=coordinator,
        )
        request = self._request(client_job_id="client-formula-queued")
        queued = store.start(request, trace_id="trace-formula-queued")
        duplicate = store.start(request, trace_id="trace-formula-duplicate")

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["queuePosition"], 1)
        self.assertTrue(queued["canCancel"])
        self.assertEqual(duplicate["traceId"], "trace-formula-queued")
        self.assertNotIn("secret-formula-a", str(queued))

        cancelled = store.cancel("client-formula-queued")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(assistant.call_count, 0)
        release_blocker.set()

    def test_formula_job_reports_real_phases_and_single_provider_call(self):
        assistant = BlockingFormulaAssistant()
        store = ExcelFormulaAssistantJobStore(
            assistant=assistant,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
        )
        request = self._request(client_job_id="client-formula-running")

        running = store.start(request, trace_id="trace-formula-running")
        self.assertTrue(assistant.started.wait(timeout=1))
        duplicate = store.start(request, trace_id="trace-formula-duplicate")
        self.assertEqual(running["jobId"], "client-formula-running")
        self.assertEqual(duplicate["traceId"], "trace-formula-running")
        self.assertFalse(duplicate["canCancel"])

        with self.assertRaises(AdapterError) as running_cancel:
            store.cancel("client-formula-running")
        self.assertEqual(running_cancel.exception.code, "LONG_TASK_NOT_CANCELLABLE")

        assistant.release.set()
        completed = wait_for_job(store, "client-formula-running")
        self.assertEqual(assistant.call_count, 1)
        self.assertEqual(completed["result"]["primaryFormula"], "=SUM(B2:B3)")
        self.assertIn("provider_processing", completed["phaseDurations"])
        self.assertIn("parsing", completed["phaseDurations"])

    @unittest.skipUnless(HAS_FASTAPI, "fastapi is required for formula route tests")
    def test_fastapi_formula_job_routes_use_independent_envelope(self):
        from app.api import excel as excel_api
        from app.main import app
        from fastapi.testclient import TestClient

        assistant = BlockingFormulaAssistant()
        store = ExcelFormulaAssistantJobStore(
            assistant=assistant,
            coordinator=LongTaskCoordinator(max_running=1, max_queued=2),
        )
        original_store = excel_api.excel_formula_assistant_jobs
        excel_api.excel_formula_assistant_jobs = store
        client = TestClient(app)
        try:
            submitted = client.post(
                "/excel/formula-assistant/jobs",
                json=dump_formula_request(
                    self._request(client_job_id="client-fastapi-formula-running")
                ),
            )
            self.assertTrue(assistant.started.wait(timeout=1))
            polled = client.get(
                "/excel/formula-assistant/jobs/client-fastapi-formula-running"
            )
            interrupted = client.get(
                "/excel/formula-assistant/jobs/client-fastapi-formula-missing?resume=1"
            )
        finally:
            assistant.release.set()
            excel_api.excel_formula_assistant_jobs = original_store

        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["taskType"], "excel.formula_assistant")
        self.assertEqual(polled.json()["data"]["status"], "running")
        self.assertEqual(interrupted.status_code, 404)
        self.assertEqual(
            interrupted.json()["errors"][0]["code"],
            "EXCEL_FORMULA_JOB_INTERRUPTED",
        )

    def test_standalone_formula_job_routes_support_polling_and_queued_cancel(self):
        import standalone_adapter

        blocker_started = threading.Event()
        release_blocker = threading.Event()
        coordinator = LongTaskCoordinator(max_running=1, max_queued=2)

        def blocking_analysis(snapshot, progress):
            blocker_started.set()
            release_blocker.wait(timeout=2)
            return {"plainText": "analysis completed"}

        coordinator.submit(
            job_id="client-standalone-analysis-running",
            trace_id="trace-standalone-analysis-running",
            task_type="excel.analysis",
            runner=blocking_analysis,
            snapshot={},
            failure_code="EXCEL_ANALYSIS_JOB_FAILED",
            failure_message="智能分析后台任务执行失败。",
        )
        self.assertTrue(blocker_started.wait(timeout=1))
        store = ExcelFormulaAssistantJobStore(
            assistant=BlockingFormulaAssistant(),
            coordinator=coordinator,
        )
        original_store = standalone_adapter.EXCEL_FORMULA_ASSISTANT_JOB_STORE
        standalone_adapter.EXCEL_FORMULA_ASSISTANT_JOB_STORE = store

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
            submitted = invoke(
                "do_POST",
                "/excel/formula-assistant/jobs",
                dump_formula_request(
                    self._request(client_job_id="client-standalone-formula-queued")
                ),
            )
            polled = invoke(
                "do_GET",
                "/excel/formula-assistant/jobs/client-standalone-formula-queued",
            )
            cancelled = invoke(
                "do_DELETE",
                "/excel/formula-assistant/jobs/client-standalone-formula-queued",
            )
            interrupted = invoke(
                "do_GET",
                "/excel/formula-assistant/jobs/client-standalone-formula-missing?resume=1",
            )
        finally:
            release_blocker.set()
            standalone_adapter.EXCEL_FORMULA_ASSISTANT_JOB_STORE = original_store

        self.assertEqual(submitted["status"], 200)
        self.assertEqual(submitted["body"]["taskType"], "excel.formula_assistant")
        self.assertEqual(submitted["body"]["data"]["status"], "queued")
        self.assertEqual(polled["body"]["data"]["queuePosition"], 1)
        self.assertEqual(cancelled["body"]["data"]["status"], "cancelled")
        self.assertEqual(interrupted["status"], 404)
        self.assertEqual(
            interrupted["body"]["errors"][0]["code"],
            "EXCEL_FORMULA_JOB_INTERRUPTED",
        )


if __name__ == "__main__":
    unittest.main()
