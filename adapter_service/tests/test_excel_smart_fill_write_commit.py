import importlib.util
import threading
import unittest

import pytest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_PYDANTIC:
    from app.core.errors import AdapterError
    from app.core.models import ExcelSmartFillRequest
    from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
    from app.services.long_task_coordinator import LongTaskCoordinator

if HAS_PYDANTIC and HAS_FASTAPI:
    from app.api import excel as excel_api
    from app.main import app


def _payload(client_job_id="smart-fill-write-commit-001"):
    return {
        "workbookId": "synthetic-workbook",
        "scene": "excel",
        "clientJobId": client_job_id,
        "items": [
            {
                "itemId": "sf_{:032x}".format(1),
                "sourceRowIndex": 1,
                "sourceRowLabel": "第 2 行",
            },
            {
                "itemId": "sf_{:032x}".format(2),
                "sourceRowIndex": 2,
                "sourceRowLabel": "第 3 行",
            },
        ],
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


def _commit_body():
    return {
        "resultRevision": 1,
        "sourceSnapshotHash": "00000000",
        "workbookId": "synthetic-workbook",
        "targetAddress": "$D$2:$D$3",
        "itemCount": 2,
    }


class _ImmediateProvider:
    def snapshot_task_auth(self):
        return {"providerBaseUrl": "https://model.example", "apiKey": "secret"}

    def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None):
        if progress_callback:
            progress_callback("provider_processing")
        return {
            "schemaVersion": "excel.smart_fill.v2",
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": "合成标签",
                }
                for item in request.items
            ],
            "provider": "test",
        }


class _BlockingProvider:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def snapshot_task_auth(self):
        return {"providerBaseUrl": "https://model.example", "apiKey": "secret"}

    def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None):
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test provider release timeout")
        return {
            "schemaVersion": "excel.smart_fill.v2",
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": "合成标签",
                }
                for item in request.items
            ],
            "provider": "test",
        }


@pytest.mark.skipif(not HAS_PYDANTIC, reason="pydantic required")
def test_job_store_rejects_duplicate_write_commit_for_same_preview():
    store = ExcelSmartFillJobStore(
        _ImmediateProvider(),
        LongTaskCoordinator(max_running=1, max_queued=2),
    )
    request = ExcelSmartFillRequest.parse_obj(_payload("write-commit-store-001"))
    job = store.start(request, trace_id="trace-write-commit-001")
    terminal = store.coordinator.wait(job["jobId"], task_type="excel.smart_fill")
    assert terminal["status"] == "completed"

    first = store.commit_write(job["jobId"], _commit_body())
    assert first["writeCommitted"] is True
    assert first["resultRevision"] == 1

    public = store.get(job["jobId"])
    assert public["writeCommitted"] is True

    with pytest.raises(AdapterError) as error_info:
        store.commit_write(job["jobId"], _commit_body())
    assert error_info.value.code == "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED"
    assert error_info.value.status_code == 409


@pytest.mark.skipif(not HAS_PYDANTIC, reason="pydantic required")
def test_job_store_rejects_write_commit_before_job_completes():
    provider = _BlockingProvider()
    store = ExcelSmartFillJobStore(
        provider,
        LongTaskCoordinator(max_running=1, max_queued=2),
    )
    request = ExcelSmartFillRequest.parse_obj(_payload("write-commit-running-001"))
    job = store.start(request, trace_id="trace-write-running")
    assert provider.started.wait(timeout=1)
    try:
        with pytest.raises(AdapterError) as error_info:
            store.commit_write(job["jobId"], _commit_body())
        assert error_info.value.code == "EXCEL_SMART_FILL_WRITE_NOT_READY"
    finally:
        provider.release.set()


@pytest.mark.skipif(not (HAS_FASTAPI and HAS_PYDANTIC), reason="fastapi and pydantic required")
def test_fastapi_write_commit_is_public_and_idempotent_fail_closed():
    from fastapi.testclient import TestClient

    store = ExcelSmartFillJobStore(
        _ImmediateProvider(),
        LongTaskCoordinator(max_running=1, max_queued=2),
    )
    original_store = excel_api.excel_smart_fill_jobs
    excel_api.excel_smart_fill_jobs = store
    client = TestClient(app)
    try:
        submitted = client.post(
            "/excel/smart-fill/jobs",
            json=_payload("write-commit-api-001"),
        )
        assert submitted.status_code == 200
        job_id = submitted.json()["data"]["jobId"]
        store.coordinator.wait(job_id, task_type="excel.smart_fill")

        first = client.post(
            "/excel/smart-fill/jobs/{}/write-commits".format(job_id),
            json=_commit_body(),
        )
        assert first.status_code == 200
        assert first.json()["taskType"] == "excel.smart_fill"
        assert first.json()["data"]["writeCommitted"] is True

        duplicate = client.post(
            "/excel/smart-fill/jobs/{}/write-commits".format(job_id),
            json=_commit_body(),
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["errors"][0]["code"] == "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED"
    finally:
        excel_api.excel_smart_fill_jobs = original_store


if __name__ == "__main__":
    unittest.main()
