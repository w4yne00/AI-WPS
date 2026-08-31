import importlib.util
import json
import threading
import unittest
from io import BytesIO

import pytest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
    from app.services.long_task_coordinator import LongTaskCoordinator

if HAS_PYDANTIC and HAS_FASTAPI:
    from app.api import excel as excel_api
    from app.main import app


def _payload(client_job_id="smart-fill-api-001"):
    return {
        "workbookId": "synthetic-workbook",
        "scene": "excel",
        "clientJobId": client_job_id,
        "target": {
            "sheetName": "Sheet1",
            "address": "D2:D3",
            "columnHeader": "分类",
            "items": [
                {
                    "itemId": "synthetic-item-001",
                    "address": "D2",
                    "row": 2,
                    "column": 4,
                    "originalValue": "",
                    "originalValueType": "blank",
                    "originalFormula": "",
                    "isFormula": False,
                    "isMerged": False,
                    "isProtected": False,
                    "isHidden": False,
                    "snapshotHash": "00000000",
                },
                {
                    "itemId": "synthetic-item-002",
                    "address": "D3",
                    "row": 3,
                    "column": 4,
                    "originalValue": "",
                    "originalValueType": "blank",
                    "originalFormula": "",
                    "isFormula": False,
                    "isMerged": False,
                    "isProtected": False,
                    "isHidden": False,
                    "snapshotHash": "00000000",
                },
            ],
        },
        "source": {
            "sheetName": "Sheet1",
            "address": "A1:C3",
            "snapshotHash": "00000000",
            "headers": ["名称", "说明", "规则"],
            "rows": [["甲", "第一项", "A"], ["乙", "第二项", "B"]],
            "rowCount": 2,
            "columnCount": 3,
            "truncated": False,
        },
        "userInstruction": "根据来源上下文填写分类。",
    }


class _ApiProvider:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def snapshot_task_auth(self):
        return {"providerBaseUrl": "https://model.example", "apiKey": "secret"}

    def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None):
        self.calls += 1
        self.started.set()
        if progress_callback:
            progress_callback("provider_processing")
        if not self.release.wait(timeout=2):
            raise RuntimeError("test provider release timeout")
        return {
            "schemaVersion": "excel.smart_fill.v1",
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": "合成标签",
                }
                for item in request.target.items
            ],
            "provider": "test",
        }


@pytest.mark.skipif(not (HAS_FASTAPI and HAS_PYDANTIC), reason="fastapi and pydantic required")
@pytest.mark.parametrize("method", ["get", "delete"])
def test_fastapi_missing_smart_fill_job_has_interrupted_envelope(method):
    from fastapi.testclient import TestClient

    response = getattr(TestClient(app), method)(
        "/excel/smart-fill/jobs/missing-smart-fill?resume=1"
    )

    assert response.status_code == 404
    body = response.json()
    assert body["taskType"] == "excel.smart_fill"
    assert body["errors"][0]["code"] == "EXCEL_SMART_FILL_JOB_INTERRUPTED"


@pytest.mark.skipif(not (HAS_FASTAPI and HAS_PYDANTIC), reason="fastapi and pydantic required")
def test_fastapi_smart_fill_job_routes_support_submit_poll_and_cooperative_cancel():
    from fastapi.testclient import TestClient

    provider = _ApiProvider()
    store = ExcelSmartFillJobStore(
        provider,
        LongTaskCoordinator(max_running=1, max_queued=2),
    )
    original_store = excel_api.excel_smart_fill_jobs
    excel_api.excel_smart_fill_jobs = store
    client = TestClient(app)
    try:
        submitted = client.post(
            "/excel/smart-fill/jobs",
            json=_payload("smart-fill-api-running"),
        )
        assert submitted.status_code == 200
        assert submitted.json()["taskType"] == "excel.smart_fill"
        assert provider.started.wait(timeout=1)

        running = client.get("/excel/smart-fill/jobs/smart-fill-api-running")
        assert running.status_code == 200
        assert running.json()["data"]["status"] == "running"
        assert "request" not in str(running.json())
        assert "第一项" not in str(running.json())

        cancelled = client.delete("/excel/smart-fill/jobs/smart-fill-api-running")
        assert cancelled.status_code == 200
        assert cancelled.json()["message"] == "cancel_requested"
        assert cancelled.json()["data"]["cancelRequested"] is True

        provider.release.set()
        terminal = store.coordinator.wait(
            "smart-fill-api-running", task_type="excel.smart_fill"
        )
        assert terminal["status"] == "cancelled"
        assert terminal["result"]["partial"] is True
        assert terminal["result"]["stopReason"] == "cancelled"
    finally:
        provider.release.set()
        excel_api.excel_smart_fill_jobs = original_store


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone smart fill tests")
class StandaloneSmartFillApiTestCase(unittest.TestCase):
    def setUp(self):
        import standalone_adapter

        self.provider = _ApiProvider()
        self.store = ExcelSmartFillJobStore(
            self.provider,
            LongTaskCoordinator(max_running=1, max_queued=2),
        )
        self.original_store = standalone_adapter.EXCEL_SMART_FILL_JOB_STORE
        standalone_adapter.EXCEL_SMART_FILL_JOB_STORE = self.store

    def tearDown(self):
        import standalone_adapter

        self.provider.release.set()
        standalone_adapter.EXCEL_SMART_FILL_JOB_STORE = self.original_store

    def _invoke(self, method, path, payload=None, headers=None):
        import standalone_adapter

        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = path
        req_headers = {"Content-Length": str(len(raw))}
        if headers:
            req_headers.update(headers)
        handler.headers = req_headers
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(
            status=status, body=body
        )
        getattr(handler, method)()
        return captured

    def test_standalone_smart_fill_job_submit_poll_and_cooperative_cancel(self):
        # 1. Submit job
        submitted = self._invoke("do_POST", "/excel/smart-fill/jobs", _payload("standalone-smart-fill-001"))
        self.assertEqual(submitted["status"], 200)
        self.assertEqual(submitted["body"]["taskType"], "excel.smart_fill")
        self.assertEqual(submitted["body"]["message"], "accepted")
        self.assertTrue(self.provider.started.wait(timeout=1))

        # 2. Query running job
        running = self._invoke("do_GET", "/excel/smart-fill/jobs/standalone-smart-fill-001")
        self.assertEqual(running["status"], 200)
        self.assertEqual(running["body"]["data"]["status"], "running")
        self.assertNotIn("request", json.dumps(running["body"], ensure_ascii=False))
        self.assertNotIn("第一项", json.dumps(running["body"], ensure_ascii=False))

        # 3. Request cancel
        cancelled = self._invoke("do_DELETE", "/excel/smart-fill/jobs/standalone-smart-fill-001")
        self.assertEqual(cancelled["status"], 200)
        self.assertEqual(cancelled["body"]["message"], "cancel_requested")
        self.assertTrue(cancelled["body"]["data"]["cancelRequested"])

        # 4. Finish provider and verify terminal cancelled state with partial preview
        self.provider.release.set()
        terminal = self.store.coordinator.wait(
            "standalone-smart-fill-001", task_type="excel.smart_fill"
        )
        self.assertEqual(terminal["status"], "cancelled")
        self.assertTrue(terminal["result"]["partial"])
        self.assertEqual(terminal["result"]["stopReason"], "cancelled")
        self.assertEqual(len(terminal["result"]["items"]), 2)

    def test_standalone_missing_smart_fill_job_has_interrupted_envelope_on_resume(self):
        get_res = self._invoke("do_GET", "/excel/smart-fill/jobs/missing-smart-fill?resume=1")
        self.assertEqual(get_res["status"], 404)
        self.assertEqual(get_res["body"]["taskType"], "excel.smart_fill")
        self.assertEqual(get_res["body"]["errors"][0]["code"], "EXCEL_SMART_FILL_JOB_INTERRUPTED")

        del_res = self._invoke("do_DELETE", "/excel/smart-fill/jobs/missing-smart-fill?resume=1")
        self.assertEqual(del_res["status"], 404)
        self.assertEqual(del_res["body"]["taskType"], "excel.smart_fill")
        self.assertEqual(del_res["body"]["errors"][0]["code"], "EXCEL_SMART_FILL_JOB_INTERRUPTED")

    def test_standalone_missing_smart_fill_job_has_not_found_envelope_without_resume(self):
        get_res = self._invoke("do_GET", "/excel/smart-fill/jobs/missing-smart-fill")
        self.assertEqual(get_res["status"], 404)
        self.assertEqual(get_res["body"]["taskType"], "excel.smart_fill")
        self.assertEqual(get_res["body"]["errors"][0]["code"], "EXCEL_SMART_FILL_JOB_NOT_FOUND")

        del_res = self._invoke("do_DELETE", "/excel/smart-fill/jobs/missing-smart-fill")
        self.assertEqual(del_res["status"], 404)
        self.assertEqual(del_res["body"]["taskType"], "excel.smart_fill")
        self.assertEqual(del_res["body"]["errors"][0]["code"], "EXCEL_SMART_FILL_JOB_NOT_FOUND")

    def test_standalone_oversized_payload_returns_413(self):
        oversized_headers = {"Content-Length": str(3 * 1024 * 1024)}
        res = self._invoke("do_POST", "/excel/smart-fill/jobs", {}, headers=oversized_headers)
        self.assertEqual(res["status"], 413)
        self.assertEqual(res["body"]["errors"][0]["code"], "EXCEL_SMART_FILL_REQUEST_TOO_LARGE")
