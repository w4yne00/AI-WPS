import json
import threading
import time

import pytest

from app.core import models
from app.core.errors import AdapterError
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
from app.services.long_task_coordinator import LongTaskCoordinator


def _item_id(n):
    return "sf_{:032x}".format(n)


def _request_payload(item_count=2, client_job_id="smart-fill-jobs-001"):
    return {
        "workbookId": "book-1",
        "scene": "excel",
        "clientJobId": client_job_id,
        "items": [
            {
                "itemId": "sf_{:032x}".format(index + 1),
                "sourceRowIndex": index + 1,
                "sourceRowLabel": "第 {0} 行".format(index + 2),
            }
            for index in range(item_count)
        ],
        "source": {
            "sheetName": "客户表",
            "address": "A1:C{0}".format(item_count + 1),
            "headers": ["名称", "类别", "说明"],
            "rows": [["甲", "A", "第一项"] for _ in range(item_count)],
            "rowCount": item_count,
            "columnCount": 3,
            "truncated": False,
        },
        "userInstruction": "根据来源表补齐标签。",
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
            "schemaVersion": "excel.smart_fill.v2",
            "items": [
                {
                    "itemId": item.item_id,
                    "status": "completed",
                    "valueType": "text",
                    "value": "填充值",
                }
                for item in request.items
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


def test_queued_job_cancellation_is_immediate_and_does_not_call_provider():
    provider = _BatchProvider(block=True)
    coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
    store = ExcelSmartFillJobStore(provider, coordinator)

    first_req = models.ExcelSmartFillRequest(
        **_request_payload(item_count=2, client_job_id="smart-fill-slot-occupant")
    )
    first_job = store.start(first_req, trace_id="trace-occupant")
    assert provider.started.wait(1)

    second_req = models.ExcelSmartFillRequest(
        **_request_payload(item_count=2, client_job_id="smart-fill-queued-cancel")
    )
    second_job = store.start(second_req, trace_id="trace-queued")
    assert second_job["status"] == "queued"

    # Cancel queued job immediately
    cancelled = store.cancel(second_job["jobId"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["canCancel"] is False
    assert cancelled["cancelRequested"] is False

    # Release first job
    provider.release.set()
    _wait_terminal(store, first_job["jobId"])

    # Verify second job terminal state without provider calls
    second_term = store.get(second_job["jobId"])
    assert second_term["status"] == "cancelled"
    assert len(provider.calls) == 1
    assert provider.calls[0].client_job_id == "smart-fill-slot-occupant"


def test_multi_batch_cancellation_preserves_completed_batches_and_marks_remaining_unprocessed():
    calls = []
    second_batch_started = threading.Event()
    release_second_batch = threading.Event()

    class MultiBatchCancellingProvider:
        def snapshot_task_auth(self):
            return {"contextWindowTokens": 128000, "maxOutputTokens": 128000}

        def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None):
            calls.append(request)
            if len(calls) == 2:
                second_batch_started.set()
                if not release_second_batch.wait(2):
                    raise RuntimeError("test provider release timeout")
            return {
                "schemaVersion": "excel.smart_fill.v2",
                "items": [
                    {
                        "itemId": item.item_id,
                        "status": "completed",
                        "valueType": "text",
                        "value": "批次生成-{0}".format(item.item_id),
                    }
                    for item in request.items
                ],
                "provider": "test-multibatch",
            }

    provider = MultiBatchCancellingProvider()
    store = ExcelSmartFillJobStore(
        provider, LongTaskCoordinator(max_running=1, max_queued=2)
    )
    request = models.ExcelSmartFillRequest(
        **_request_payload(item_count=101, client_job_id="smart-fill-mb-cancel")
    )
    accepted = store.start(request, trace_id="trace-mb-cancel")
    assert second_batch_started.wait(1)

    # Cancel while second batch is running
    requested = store.cancel(accepted["jobId"])
    assert requested["cancelRequested"] is True

    release_second_batch.set()
    terminal = _wait_terminal(store, accepted["jobId"])
    assert terminal["status"] == "cancelled"
    assert terminal["result"]["partial"] is True
    assert terminal["result"]["stopReason"] == "cancelled"
    assert len(calls) == 2  # Batch 1 (50 items) and Batch 2 (50 items) were processed; Batch 3 (1 item) was cancelled before start
    items = terminal["result"]["items"]
    assert len(items) == 101
    assert items[0]["status"] == "completed"
    assert items[0]["value"] == "批次生成-{0}".format(_item_id(1))
    assert items[99]["status"] == "completed"
    assert items[99]["value"] == "批次生成-{0}".format(_item_id(100))
    assert items[100]["status"] == "unprocessed"
    assert items[100]["value"] == ""


def test_multi_batch_deadline_exceeded_preserves_completed_batches_and_marks_remaining_unprocessed():
    now = [0.0]

    def clock():
        return now[0]

    class SteppingClockProvider:
        def __init__(self):
            self.calls = []

        def snapshot_task_auth(self):
            return {"contextWindowTokens": 128000, "maxOutputTokens": 128000}

        def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None, timeout_seconds=None, deadline_monotonic=None, clock=None):
            self.calls.append(request)
            # Advance clock by 3601 seconds on first batch completion
            now[0] += 3601.0
            return {
                "schemaVersion": "excel.smart_fill.v2",
                "items": [
                    {
                        "itemId": item.item_id,
                        "status": "completed",
                        "valueType": "text",
                        "value": "超时前完成-{0}".format(item.item_id),
                    }
                    for item in request.items
                ],
                "provider": "test-stepping",
            }

    provider = SteppingClockProvider()
    coordinator = LongTaskCoordinator(
        max_running=1,
        max_queued=2,
        monotonic_clock=clock,
        wall_clock=clock,
    )
    store = ExcelSmartFillJobStore(provider, coordinator, clock=clock)
    request = models.ExcelSmartFillRequest(
        **_request_payload(item_count=101, client_job_id="smart-fill-mb-timeout")
    )
    accepted = store.start(request, trace_id="trace-mb-timeout")
    terminal = _wait_terminal(store, accepted["jobId"])

    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "EXCEL_SMART_FILL_DEADLINE_EXCEEDED"
    assert terminal["result"]["partial"] is True
    assert terminal["result"]["stopReason"] == "timeout"
    assert len(provider.calls) == 1
    items = terminal["result"]["items"]
    assert len(items) == 101
    assert items[0]["status"] == "completed"
    assert items[0]["value"] == "超时前完成-{0}".format(_item_id(1))
    assert items[49]["status"] == "completed"
    assert items[50]["status"] == "unprocessed"
    assert items[100]["status"] == "unprocessed"


def test_provider_error_on_second_batch_preserves_first_batch_results():
    calls = []

    class FailingSecondBatchProvider:
        def snapshot_task_auth(self):
            return {"contextWindowTokens": 128000, "maxOutputTokens": 128000}

        def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None, timeout_seconds=None, deadline_monotonic=None, clock=None):
            calls.append(request)
            if len(calls) == 2:
                raise AdapterError(
                    "PROVIDER_TIMEOUT",
                    "模型服务超时。",
                    status_code=504,
                )
            return {
                "schemaVersion": "excel.smart_fill.v2",
                "items": [
                    {
                        "itemId": item.item_id,
                        "status": "completed",
                        "valueType": "text",
                        "value": "批次1-{0}".format(item.item_id),
                    }
                    for item in request.items
                ],
                "provider": "test-fail2",
            }

    provider = FailingSecondBatchProvider()
    coordinator = LongTaskCoordinator(max_running=1, max_queued=2)
    store = ExcelSmartFillJobStore(provider, coordinator)
    request = models.ExcelSmartFillRequest(
        **_request_payload(item_count=100, client_job_id="smart-fill-fail2-001")
    )
    accepted = store.start(request, trace_id="trace-fail2")
    terminal = _wait_terminal(store, accepted["jobId"])

    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "PROVIDER_TIMEOUT"
    assert terminal["result"]["partial"] is True
    assert terminal["result"]["stopReason"] == "timeout"
    assert len(calls) == 2
    items = terminal["result"]["items"]
    assert len(items) == 100
    assert items[0]["status"] == "completed"
    assert items[49]["status"] == "completed"
    assert items[50]["status"] == "unprocessed"
    assert items[99]["status"] == "unprocessed"


def test_fair_scheduling_between_continuation_and_queued_tasks():
    execution_order = []

    class TracingProvider:
        def __init__(self):
            self.task_a_step1_done = threading.Event()
            self.task_b_step1_start = threading.Event()
            self.task_b_step1_done = threading.Event()

        def snapshot_task_auth(self):
            return {"contextWindowTokens": 128000, "maxOutputTokens": 128000}

        def fill_batch(self, request, trace_id, task_auth=None, progress_callback=None, timeout_seconds=None, deadline_monotonic=None, clock=None):
            client_id = request.client_job_id
            batch_item_0 = request.items[0].item_id
            execution_order.append((client_id, batch_item_0))
            if client_id == "job-task-a" and batch_item_0 == _item_id(1):
                self.task_a_step1_done.set()
                # Wait for task B to finish before task A batch 2 runs
                self.task_b_step1_start.wait(2)
            elif client_id == "job-task-b":
                self.task_b_step1_start.set()
            return {
                "schemaVersion": "excel.smart_fill.v2",
                "items": [
                    {
                        "itemId": item.item_id,
                        "status": "completed",
                        "valueType": "text",
                        "value": "v",
                    }
                    for item in request.items
                ],
                "provider": "test-fair",
            }

    provider = TracingProvider()
    coordinator = LongTaskCoordinator(max_running=1, max_queued=4)
    store = ExcelSmartFillJobStore(provider, coordinator)

    req_a = models.ExcelSmartFillRequest(
        **_request_payload(item_count=100, client_job_id="job-task-a")
    )
    req_b = models.ExcelSmartFillRequest(
        **_request_payload(item_count=10, client_job_id="job-task-b")
    )

    job_a = store.start(req_a, trace_id="trace-a")
    assert provider.task_a_step1_done.wait(2)
    # Queue task B while task A is yielding/continuing
    job_b = store.start(req_b, trace_id="trace-b")

    _wait_terminal(store, job_b["jobId"])
    _wait_terminal(store, job_a["jobId"])

    # Execution order should interleave: Task A batch 1 -> Task B batch 1 -> Task A batch 2
    assert len(execution_order) == 3
    assert execution_order[0] == ("job-task-a", _item_id(1))
    assert execution_order[1] == ("job-task-b", _item_id(1))
    assert execution_order[2] == ("job-task-a", _item_id(51))
