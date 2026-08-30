import json
import threading
import time

import pytest

from app.core import models
from app.core.errors import AdapterError
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
from app.services.long_task_coordinator import LongTaskCoordinator


def _request_payload(item_count=2, client_job_id="smart-fill-jobs-001"):
    return {
        "workbookId": "book-1",
        "scene": "excel",
        "clientJobId": client_job_id,
        "target": {
            "sheetName": "目标",
            "address": "D2:D{0}".format(item_count + 1),
            "columnHeader": "标签",
            "items": [
                {
                    "itemId": "item-{0:03d}".format(index),
                    "address": "D{0}".format(index + 2),
                    "row": index + 2,
                    "column": 4,
                    "originalValue": "",
                    "originalValueType": "blank",
                    "isFormula": False,
                }
                for index in range(item_count)
            ],
        },
        "source": {
            "sheetName": "目标",
            "address": "A1:C{0}".format(item_count + 1),
            "headers": ["名称", "类别", "说明"],
            "rows": [["甲", "A", "第一项"] for _ in range(item_count)],
            "rowCount": item_count,
            "columnCount": 3,
            "truncated": False,
        },
        "userInstruction": "根据来源表补齐目标列。",
    }


class _BatchProvider:
    def __init__(self, block=False):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block

    def snapshot_task_auth(self):
        return {"providerBaseUrl": "https://model.example", "apiKey": "secret"}

    def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None):
        self.calls.append(request)
        self.started.set()
        if progress_callback:
            progress_callback("provider_processing")
        if self.block:
            if not self.release.wait(2):
                raise RuntimeError("test provider release timeout")
        return {
            "schemaVersion": "excel.smart_fill.v1",
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": "填充值",
                }
                for item in request.target.items
            ],
            "provider": "test",
        }


def _wait_terminal(store, job_id):
    terminal = store.coordinator.wait(job_id, task_type="excel.smart_fill")
    assert terminal is not None
    return terminal


def test_job_public_metadata_does_not_expose_request_source_or_result_values():
    provider = _BatchProvider()
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    request = models.ExcelSmartFillRequest(**_request_payload())
    public = store.start(request, trace_id="trace-smart-fill-public")

    assert "request" not in json.dumps(public, ensure_ascii=False)
    assert "第一项" not in json.dumps(public, ensure_ascii=False)
    terminal = _wait_terminal(store, public["jobId"])
    assert terminal["status"] == "completed"
    assert terminal["result"]["items"][0]["value"] == "填充值"


def test_running_cancel_is_cooperative_and_keeps_a_partial_preview():
    provider = _BatchProvider(block=True)
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    request = models.ExcelSmartFillRequest(
        **_request_payload(item_count=51, client_job_id="smart-fill-cancel-001")
    )
    accepted = store.start(request, trace_id="trace-smart-fill-cancel")
    assert provider.started.wait(1)

    requested = store.cancel(accepted["jobId"])
    assert requested["status"] == "running"
    assert requested["cancelRequested"] is True
    assert requested["canCancel"] is False

    provider.release.set()
    terminal = _wait_terminal(store, accepted["jobId"])
    assert terminal["status"] == "cancelled"
    assert terminal["result"]["partial"] is True
    assert terminal["result"]["stopReason"] == "cancelled"
    assert len(provider.calls) == 1


def test_deadline_keeps_unprocessed_items_as_explicit_partial_preview(monkeypatch):
    from app.services.excel import smart_fill_jobs as jobs_module

    monkeypatch.setattr(jobs_module, "TOTAL_TIMEOUT_SECONDS", 0)
    provider = _BatchProvider()
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    request = models.ExcelSmartFillRequest(
        **_request_payload(item_count=2, client_job_id="smart-fill-deadline-001")
    )
    accepted = store.start(request, trace_id="trace-smart-fill-deadline")
    terminal = _wait_terminal(store, accepted["jobId"])

    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "EXCEL_SMART_FILL_DEADLINE_EXCEEDED"
    assert terminal["result"]["partial"] is True
    assert terminal["result"]["stopReason"] == "timeout"
    assert provider.calls == []


def test_duplicate_client_job_id_is_idempotent_and_calls_provider_once():
    provider = _BatchProvider()
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    request = models.ExcelSmartFillRequest(
        **_request_payload(client_job_id="smart-fill-idempotent-001")
    )
    first = store.start(request, trace_id="trace-smart-fill-one")
    second = store.start(request, trace_id="trace-smart-fill-two")
    terminal = _wait_terminal(store, first["jobId"])

    assert second["jobId"] == first["jobId"]
    assert second["traceId"] == first["traceId"]
    assert terminal["status"] == "completed"
    assert len(provider.calls) == 1


def test_duplicate_client_job_id_rejects_a_different_request():
    provider = _BatchProvider()
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    first_request = models.ExcelSmartFillRequest(
        **_request_payload(client_job_id="smart-fill-idempotent-conflict")
    )
    second_payload = _request_payload(client_job_id="smart-fill-idempotent-conflict")
    second_payload["userInstruction"] = "改用另一条业务规则。"
    second_request = models.ExcelSmartFillRequest(**second_payload)

    first = store.start(first_request, trace_id="trace-smart-fill-conflict-one")
    with pytest.raises(AdapterError) as exc_info:
        store.start(second_request, trace_id="trace-smart-fill-conflict-two")

    assert exc_info.value.code == "EXCEL_SMART_FILL_JOB_ID_CONFLICT"
    assert _wait_terminal(store, first["jobId"])["status"] == "completed"
    assert len(provider.calls) == 1


def test_expired_terminal_jobs_are_not_resumable():
    now = [0.0]

    def clock():
        return now[0]

    provider = _BatchProvider()
    coordinator = LongTaskCoordinator(
        max_running=1,
        max_queued=2,
        terminal_ttl_seconds=10,
        monotonic_clock=clock,
        wall_clock=clock,
    )
    store = ExcelSmartFillJobStore(provider, coordinator, clock=clock)
    request = models.ExcelSmartFillRequest(
        **_request_payload(client_job_id="smart-fill-ttl-001")
    )
    accepted = store.start(request, trace_id="trace-smart-fill-ttl")
    _wait_terminal(store, accepted["jobId"])
    now[0] = 11.0

    assert store.get(accepted["jobId"]) is None
