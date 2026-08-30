import threading

import pytest

from app.api import excel as excel_api
from app.main import app
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
from app.services.long_task_coordinator import LongTaskCoordinator


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

    def fill_batch(self, request, trace_id, progress_callback=None):
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
