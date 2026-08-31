import re
import time
from copy import deepcopy
from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelSmartFillRequest
from app.services.excel.smart_fill import (
    MAX_ITEMS_PER_BATCH,
    MAX_ITEMS_PER_TASK,
    ExcelSmartFill,
    calculate_smart_fill_batch_size,
    slice_smart_fill_batch,
    smart_fill_request_fingerprint,
    validate_smart_fill_result_limits,
    validate_smart_fill_request_limits,
)
from app.services.long_task_coordinator import (
    LongTaskCancelled,
    LongTaskContinuation,
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import EXCEL_SMART_FILL_TIMEOUT_SECONDS


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
TOTAL_TIMEOUT_SECONDS = 60 * 60
RESULT_RETENTION_SECONDS = 2 * 60 * 60
RUNNING_MESSAGE = "模型后台正在处理智能填写，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_SMART_FILL_TARGET_SHAPE_INVALID": 400,
    "EXCEL_SMART_FILL_CROSS_SHEET": 400,
    "EXCEL_SMART_FILL_INSTRUCTION_REQUIRED": 400,
    "EXCEL_SMART_FILL_TARGET_UNSAFE": 409,
    "EXCEL_SMART_FILL_BATCH_TOO_LARGE": 400,
    "EXCEL_SMART_FILL_ITEMS_TOO_MANY": 400,
    "EXCEL_SMART_FILL_INSTRUCTION_TOO_LONG": 400,
    "EXCEL_SMART_FILL_SOURCE_TRUNCATED": 400,
    "EXCEL_SMART_FILL_SOURCE_SHAPE_INVALID": 400,
    "EXCEL_SMART_FILL_CELL_TEXT_TOO_LONG": 400,
    "EXCEL_SMART_FILL_TEXT_TOO_LARGE": 400,
    "EXCEL_SMART_FILL_REQUEST_TOO_LARGE": 413,
    "EXCEL_SMART_FILL_CONTEXT_TOO_LARGE": 400,
    "EXCEL_SMART_FILL_JOB_ID_CONFLICT": 409,
    "EXCEL_SMART_FILL_RESULT_TOO_LARGE": 502,
    "EXCEL_SMART_FILL_DEADLINE_EXCEEDED": 504,
    "EXCEL_SMART_FILL_AUTH_SNAPSHOT_FAILED": 503,
    "MODEL_CONFIG_INCOMPLETE": 400,
    "MODEL_FINAL_CONTENT_MISSING": 502,
    "MODEL_RESULT_INVALID": 502,
    "PROVIDER_AUTH_FAILED": 401,
    "PROVIDER_UNREACHABLE": 502,
    "PROVIDER_TIMEOUT": 504,
    "PROVIDER_MID_STREAM_DISCONNECT": 502,
    "DIFY_AUTH_FAILED": 401,
    "DIFY_UNREACHABLE": 502,
    "DIFY_TIMEOUT": 504,
}


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


class ExcelSmartFillJobStore:
    def __init__(
        self,
        smart_fill: Optional[ExcelSmartFill] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
        clock=time.monotonic,
    ) -> None:
        self.smart_fill = smart_fill or ExcelSmartFill()
        self.coordinator = coordinator or get_long_task_coordinator()
        self.clock = clock

    def start(self, request: ExcelSmartFillRequest, trace_id: str) -> Dict:
        validate_smart_fill_request_limits(request)
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        request_fingerprint = smart_fill_request_fingerprint(request)
        existing = self.coordinator.get(job_id, task_type="excel.smart_fill")
        if existing is not None:
            stored_fingerprint = self.coordinator.get_request_fingerprint(
                job_id, task_type="excel.smart_fill"
            )
            if stored_fingerprint and stored_fingerprint != request_fingerprint:
                raise AdapterError(
                    "EXCEL_SMART_FILL_JOB_ID_CONFLICT",
                    "相同任务编号已绑定其他智能填写请求，请使用新的任务编号。",
                    status_code=409,
                )
            return existing
        snapshot_task_auth = getattr(self.smart_fill, "snapshot_task_auth", None)
        task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type="excel.smart_fill",
            runner=self._run,
            snapshot={
                "jobId": job_id,
                "traceId": trace_id,
                "request": deepcopy(request),
                "taskAuth": task_auth,
                "nextIndex": 0,
                "results": [],
                "batchCount": 0,
                "startedAtMonotonic": self.clock(),
            },
            failure_code="EXCEL_SMART_FILL_JOB_FAILED",
            failure_message="智能填写后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
            public_metadata={
                "runningMessage": RUNNING_MESSAGE,
                "providerTimeoutSeconds": EXCEL_SMART_FILL_TIMEOUT_SECONDS,
                "totalTimeoutSeconds": TOTAL_TIMEOUT_SECONDS,
                "resultRetentionSeconds": RESULT_RETENTION_SECONDS,
                "maxItems": MAX_ITEMS_PER_TASK,
                "batchSize": MAX_ITEMS_PER_BATCH,
            },
            safe_failure_codes=set(SAFE_ERROR_STATUSES),
            request_fingerprint=request_fingerprint,
            request_conflict_code="EXCEL_SMART_FILL_JOB_ID_CONFLICT",
            request_conflict_message="相同任务编号已绑定其他智能填写请求，请使用新的任务编号。",
            allow_running_cancel=True,
        )

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="excel.smart_fill")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.request_cancel(job_id, task_type="excel.smart_fill")

    def run_sync(self, request: ExcelSmartFillRequest, trace_id: str) -> Dict:
        job = self.start(request, trace_id)
        return self.coordinator.wait_result(
            job["jobId"],
            task_type="excel.smart_fill",
            not_found_code="EXCEL_SMART_FILL_JOB_NOT_FOUND",
            not_found_message="智能填写后台任务不存在或已过期。",
            cancelled_message="智能填写任务已取消。",
            failure_code="EXCEL_SMART_FILL_JOB_FAILED",
            failure_message="智能填写后台任务执行失败。",
            safe_error_statuses=SAFE_ERROR_STATUSES,
        )

    def _run(self, snapshot: Dict, progress) -> Dict:
        self._raise_if_deadline_exceeded(snapshot)
        if self.coordinator.is_cancel_requested(
            snapshot["jobId"], task_type="excel.smart_fill"
        ):
            raise LongTaskCancelled(
                self._partial_result(snapshot, snapshot.get("results", []), "cancelled")
            )
        request = snapshot["request"]
        start = int(snapshot.get("nextIndex", 0))
        batch_size = calculate_smart_fill_batch_size(
            request,
            start_index=start,
            task_auth=snapshot.get("taskAuth"),
        )
        batch = slice_smart_fill_batch(request, start, batch_size)
        if not batch.target.items:
            raise AdapterError(
                "EXCEL_SMART_FILL_JOB_FAILED",
                "智能填写任务没有可处理的目标单元格。",
                status_code=400,
            )
        if progress:
            progress("chunking")
        provider_kwargs = {}
        if snapshot.get("taskAuth") is not None:
            provider_kwargs["task_auth"] = snapshot["taskAuth"]
        result = self.smart_fill.fill_batch(
            batch,
            trace_id=snapshot.get("traceId", "") or "",
            progress_callback=progress,
            **provider_kwargs
        )
        combined = list(snapshot.get("results", [])) + list(result["items"])
        if self.coordinator.is_cancel_requested(
            snapshot["jobId"], task_type="excel.smart_fill"
        ):
            raise LongTaskCancelled(
                self._partial_result(snapshot, combined, "cancelled")
            )
        try:
            validate_smart_fill_result_limits({"items": combined})
        except AdapterError as error:
            if error.code != "EXCEL_SMART_FILL_RESULT_TOO_LARGE":
                error.partial_result = self._partial_result(
                    snapshot, combined, "failed"
                )
            raise
        next_index = start + len(batch.target.items)
        batch_count = int(snapshot.get("batchCount", 0)) + 1
        if next_index < len(request.target.items):
            continuation = {
                **snapshot,
                "nextIndex": next_index,
                "results": combined,
                "batchCount": batch_count,
                "provider": result.get("provider", ""),
            }
            return LongTaskContinuation(continuation, phase="chunking")
        self._raise_if_deadline_exceeded(
            {**snapshot, "results": combined, "batchCount": batch_count}
        )
        return {
            "schemaVersion": "excel.smart_fill.v1",
            "items": combined,
            "provider": result.get("provider", ""),
            "processedItemCount": len(combined),
            "batchCount": batch_count,
        }

    def _raise_if_deadline_exceeded(self, snapshot: Dict) -> None:
        started = float(snapshot.get("startedAtMonotonic", self.clock()))
        if self.clock() - started >= TOTAL_TIMEOUT_SECONDS:
            error = AdapterError(
                "EXCEL_SMART_FILL_DEADLINE_EXCEEDED",
                "智能填写任务超过 60 分钟总处理时限。",
                status_code=504,
            )
            error.partial_result = self._partial_result(
                snapshot, snapshot.get("results", []), "timeout"
            )
            raise error

    @staticmethod
    def _partial_result(snapshot: Dict, results, stop_reason: str) -> Dict:
        request = snapshot.get("request")
        existing = list(results or [])
        seen = {
            item.get("itemId")
            for item in existing
            if isinstance(item, dict) and item.get("itemId")
        }
        if request is not None:
            for item in request.target.items:
                if item.item_id in seen:
                    continue
                existing.append(
                    {
                        "itemId": item.item_id,
                        "status": "insufficient_information",
                        "valueType": "text",
                        "value": "",
                    }
                )
        return {
            "schemaVersion": "excel.smart_fill.v1",
            "items": existing,
            "provider": str(snapshot.get("provider", "")),
            "processedItemCount": len(seen),
            "batchCount": int(snapshot.get("batchCount", 0)),
            "partial": True,
            "stopReason": stop_reason,
        }
