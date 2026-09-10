import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    import pydantic
except ImportError:
    class _PydanticShim:
        class BaseModel:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
                    snake = "".join(["_" + c.lower() if c.isupper() else c for c in k]).lstrip("_")
                    setattr(self, snake, v)
            @classmethod
            def parse_obj(cls, d):
                return cls(**d)
            @classmethod
            def model_validate(cls, d):
                return cls(**d)
            def dict(self, *a, **k):
                def _to_dict(v):
                    if isinstance(v, _PydanticShim.BaseModel):
                        return v.dict(*a, **k)
                    elif isinstance(v, list):
                        return [_to_dict(x) for x in v]
                    elif isinstance(v, dict):
                        return {key: _to_dict(val) for key, val in v.items()}
                    return v
                return {key: _to_dict(val) for key, val in self.__dict__.items() if not key.startswith("_")}
            def copy(self, deep=True):
                from copy import deepcopy
                return deepcopy(self)
        @staticmethod
        def Field(*a, **k):
            default = k.get("default", None)
            if default is None and "default_factory" in k:
                return k["default_factory"]()
            return default
        StrictBool = bool
        StrictInt = int
        StrictStr = str
        @staticmethod
        def root_validator(*a, **k):
            return lambda fn: fn
        @staticmethod
        def validator(*a, **k):
            return lambda fn: fn

    pyd = types.ModuleType("pydantic")
    for attr in dir(_PydanticShim):
        if not attr.startswith("__"):
            setattr(pyd, attr, getattr(_PydanticShim, attr))
    sys.modules["pydantic"] = pyd

from app.core.errors import AdapterError
from app.core.models import (
    ExcelSmartFillItem,
    ExcelSmartFillRequest,
    ExcelSmartFillSource,
)
from app.services.excel.smart_fill_jobs import ExcelSmartFillJobStore
from app.services.long_task_coordinator import LongTaskCoordinator
from app.services.task_history import TaskHistoryError, TaskHistoryStore


class MockExcelSmartFill:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.snapshot_calls = 0

    def snapshot_task_auth(self):
        self.snapshot_calls += 1
        return {
            "serviceName": "智能填写直连服务",
            "modelName": "smart-fill-model-v1",
            "accessMethod": "direct_model",
            "modelConfigurationId": "cfg-sf-1",
            "modelConfigurationName": "智能填写配置",
        }

    def fill_batch(self, request, trace_id="", task_auth=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback("chunking")
        if self.delay > 0:
            time.sleep(self.delay)
        items = []
        for item in request.items:
            items.append({
                "itemId": item.item_id,
                "status": "completed",
                "valueType": "text",
                "value": f"生成的_{item.source_row_label or item.item_id}",
            })
        return {
            "schemaVersion": "excel.smart_fill.v2",
            "items": items,
            "provider": "smart-fill-model-v1",
        }


def make_test_smart_fill_request(
    workbook_id="wb-1",
    client_job_id="sf-client-job-001",
    doc_session="doc_session_1",
    doc_name="工作簿1.xlsx",
    host="et",
):
    source = ExcelSmartFillSource(
        sheetName="Sheet1",
        address="A1:B3",
        snapshotHash="abcdef0123456789",
        headers=["姓名", "部门"],
        rows=[["张三", "技术部"], ["李四", "市场部"]],
        rowCount=2,
        columnCount=2,
    )
    items = [
        ExcelSmartFillItem(itemId="sf_0123456789abcdef0123456789abcdef", sourceRowIndex=1, sourceRowLabel="张三"),
        ExcelSmartFillItem(itemId="sf_abcdef0123456789abcdef0123456789", sourceRowIndex=2, sourceRowLabel="李四"),
    ]
    return ExcelSmartFillRequest(
        workbookId=workbook_id,
        clientJobId=client_job_id,
        documentSessionId=doc_session,
        documentDisplayName=doc_name,
        host=host,
        items=items,
        source=source,
        userInstruction="生成人员编号",
    )


class ExcelSmartFillHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name) / "history"
        self.history_store = TaskHistoryStore(history_dir=self.history_dir)
        self.coordinator = LongTaskCoordinator(
            max_running=2,
            max_queued=8,
            terminal_ttl_seconds=3600,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_request_model_accepts_document_session_and_display_name(self):
        req = make_test_smart_fill_request(
            doc_session="doc_session_custom",
            doc_name="年度报表.xlsx",
            host="et",
        )
        self.assertEqual(getattr(req, "document_session_id", ""), "doc_session_custom")
        self.assertEqual(getattr(req, "document_display_name", ""), "年度报表.xlsx")
        self.assertEqual(getattr(req, "host", ""), "et")

    def test_active_task_slot_guard_rejects_duplicate_concurrent_task(self):
        assistant = MockExcelSmartFill(delay=0.2)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        req1 = make_test_smart_fill_request(
            client_job_id="job-sf-session-001",
            doc_session="session_et_alpha",
        )
        req2 = make_test_smart_fill_request(
            client_job_id="job-sf-session-002",
            doc_session="session_et_alpha",
        )

        job1 = store.start(req1, trace_id="trace-1")
        self.assertIn(job1.get("status"), {"queued", "running"})

        # Submitting second task for same doc session must raise 409 EXCEL_SMART_FILL_DOCUMENT_TASK_BUSY
        with self.assertRaises(AdapterError) as ctx:
            store.start(req2, trace_id="trace-2")
        self.assertEqual(ctx.exception.code, "EXCEL_SMART_FILL_DOCUMENT_TASK_BUSY")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_active_task_slot_allows_different_document_sessions(self):
        assistant = MockExcelSmartFill(delay=0.2)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        req1 = make_test_smart_fill_request(
            client_job_id="job-sf-diff-001",
            doc_session="session_et_one",
        )
        req2 = make_test_smart_fill_request(
            client_job_id="job-sf-diff-002",
            doc_session="session_et_two",
        )

        job1 = store.start(req1, trace_id="trace-1")
        job2 = store.start(req2, trace_id="trace-2")
        self.assertIn(job1.get("status"), {"queued", "running"})
        self.assertIn(job2.get("status"), {"queued", "running"})

    def test_active_task_slot_released_on_completion(self):
        assistant = MockExcelSmartFill(delay=0.01)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        with patch("app.services.excel.smart_fill_jobs.get_task_history_store", return_value=self.history_store):
            req1 = make_test_smart_fill_request(
                client_job_id="job-sf-comp-001",
                doc_session="session_et_comp",
            )
            store.start(req1, trace_id="trace-1")

            # Wait for job1 to complete
            for _ in range(50):
                job = store.get("job-sf-comp-001")
                if job and job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.02)

            self.assertEqual(job.get("status"), "completed")

            # Slot must be released: new task for same doc session should succeed
            req2 = make_test_smart_fill_request(
                client_job_id="job-sf-comp-002",
                doc_session="session_et_comp",
            )
            job2 = store.start(req2, trace_id="trace-2")
            self.assertIn(job2.get("status"), {"queued", "running"})

    def test_active_task_slot_released_on_cancellation(self):
        assistant = MockExcelSmartFill(delay=0.5)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        req1 = make_test_smart_fill_request(
            client_job_id="job-sf-cancel-001",
            doc_session="session_et_cancel",
        )
        store.start(req1, trace_id="trace-1")
        cancelled = store.cancel("job-sf-cancel-001")
        self.assertIsNotNone(cancelled)

        # Slot must be released so next submission on same session is accepted
        req2 = make_test_smart_fill_request(
            client_job_id="job-sf-cancel-002",
            doc_session="session_et_cancel",
        )
        job2 = store.start(req2, trace_id="trace-2")
        self.assertIn(job2.get("status"), {"queued", "running"})

    def test_record_success_persists_read_only_history(self):
        assistant = MockExcelSmartFill(delay=0.01)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        with patch("app.services.excel.smart_fill_jobs.get_task_history_store", return_value=self.history_store):
            req = make_test_smart_fill_request(
                client_job_id="job-sf-hist-001",
                doc_session="session_et_hist",
                doc_name="员工表.xlsx",
            )
            store.start(req, trace_id="trace-hist-1")

            for _ in range(50):
                job = store.get("job-sf-hist-001")
                if job and job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.02)

            self.assertEqual(job.get("status"), "completed")

            # Verify history store has recorded the success
            entries = self.history_store.list_history("excel.smart_fill")
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["taskType"], "excel.smart_fill")
            self.assertEqual(entry["jobId"], "job-sf-hist-001")
            self.assertEqual(entry["documentDisplayName"], "员工表.xlsx")
            self.assertEqual(entry["serviceName"], "智能填写直连服务")
            self.assertEqual(entry["modelName"], "smart-fill-model-v1")

            # Check archived result structure: only read-only values, NO target mapping
            res = entry["result"]
            self.assertEqual(res["schemaVersion"], "excel.smart_fill.v2")
            self.assertEqual(res["processedItemCount"], 2)
            self.assertIn("items", res)
            self.assertEqual(len(res["items"]), 2)
            self.assertEqual(res["items"][0]["value"], "生成的_张三")
            self.assertEqual(res["items"][1]["value"], "生成的_李四")

            # Crucial: NO targetAddress, targetColumn, or userInstruction in archived result
            self.assertNotIn("targetAddress", res)
            self.assertNotIn("targetColumn", res)
            self.assertNotIn("userInstruction", res)

    def test_history_entry_too_large_handled_gracefully(self):
        assistant = MockExcelSmartFill(delay=0.01)
        store = ExcelSmartFillJobStore(smart_fill=assistant, coordinator=self.coordinator)

        def mock_record_success(**kwargs):
            raise TaskHistoryError("HISTORY_ENTRY_TOO_LARGE", "单条超过 5 MiB")

        with patch("app.services.excel.smart_fill_jobs.get_task_history_store") as mock_get_store:
            mock_store = mock_get_store.return_value
            mock_store.record_success.side_effect = mock_record_success

            req = make_test_smart_fill_request(
                client_job_id="job-sf-large-001",
                doc_session="session_et_large",
            )
            store.start(req, trace_id="trace-large-1")

            for _ in range(50):
                job = store.get("job-sf-large-001")
                if job and job.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.02)

            self.assertEqual(job.get("status"), "completed")
            result = job.get("result", {})
            self.assertEqual(result.get("historyNotice"), "任务结果超过 5 MiB，未写入历史记录。")


if __name__ == "__main__":
    unittest.main()
