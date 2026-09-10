import math
import re
import threading
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
from app.services.task_history import TaskHistoryError, get_task_history_store


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
TOTAL_TIMEOUT_SECONDS = 60 * 60
RESULT_RETENTION_SECONDS = 2 * 60 * 60
RUNNING_MESSAGE = "模型后台正在处理智能填写，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_SMART_FILL_TARGET_SHAPE_INVALID": 400,
    "EXCEL_SMART_FILL_CROSS_SHEET": 400,
    "EXCEL_SMART_FILL_INSTRUCTION_REQUIRED": 400,
    "EXCEL_SMART_FILL_TARGET_UNSAFE": 409,
    "EXCEL_SMART_FILL_DOCUMENT_TASK_BUSY": 409,
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
    "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED": 409,
    "EXCEL_SMART_FILL_WRITE_NOT_READY": 409,
    "EXCEL_SMART_FILL_WRITE_IDENTITY_MISMATCH": 409,
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
        self._write_commits = {}
        self._job_write_identity = {}
        self._write_lock = threading.Lock()
        self._submission_lock = threading.Lock()
        self._active_doc_sessions = {}

    def start(self, request: ExcelSmartFillRequest, trace_id: str) -> Dict:
        self._purge_expired_write_state()
        validate_smart_fill_request_limits(request)
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        request_fingerprint = smart_fill_request_fingerprint(request)
        doc_session = str(getattr(request, "document_session_id", "") or "").strip()
        host = str(getattr(request, "host", "") or "et").strip()
        doc_name = str(
            getattr(request, "document_display_name", "")
            or getattr(request, "workbook_id", "")
            or "工作簿.xlsx"
        ).strip()
        task_type = "excel.smart_fill"

        with self._submission_lock:
            existing = self.coordinator.get(job_id, task_type=task_type)
            if existing is not None:
                stored_fingerprint = self.coordinator.get_request_fingerprint(
                    job_id, task_type=task_type
                )
                if stored_fingerprint and stored_fingerprint != request_fingerprint:
                    raise AdapterError(
                        "EXCEL_SMART_FILL_JOB_ID_CONFLICT",
                        "相同任务编号已绑定其他智能填写请求，请使用新的任务编号。",
                        status_code=409,
                    )
                self._remember_write_identity(job_id, request)
                return existing

            # Document session active slot guard: reject duplicate concurrent task in same document session
            if doc_session:
                slot_key = (host, task_type, doc_session)
                active_job_id = self._active_doc_sessions.get(slot_key)
                if active_job_id:
                    active_job = self.coordinator.get(active_job_id, task_type=task_type)
                    if active_job and active_job.get("status") in {"queued", "running"}:
                        if active_job_id != job_id:
                            raise AdapterError(
                                "EXCEL_SMART_FILL_DOCUMENT_TASK_BUSY",
                                "当前工作簿已存在进行中的智能填写任务，请等待其完成。",
                                status_code=409,
                            )
                    else:
                        self._active_doc_sessions.pop(slot_key, None)

            snapshot_task_auth = getattr(self.smart_fill, "snapshot_task_auth", None)
            task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
            total_items = len(request.items)
            initial_batch_size = calculate_smart_fill_batch_size(
                request,
                start_index=0,
                task_auth=task_auth,
            )
            total_batches = max(1, math.ceil(total_items / max(1, initial_batch_size)))
            retention_seconds = getattr(self.coordinator, "terminal_ttl_seconds", RESULT_RETENTION_SECONDS)
            self._remember_write_identity(job_id, request)
            submitted = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=task_type,
                runner=self._run,
                snapshot={
                    "jobId": job_id,
                    "traceId": trace_id,
                    "request": deepcopy(request),
                    "taskAuth": task_auth,
                    "nextIndex": 0,
                    "results": [],
                    "batchCount": 0,
                    "currentBatch": 1,
                    "totalBatches": total_batches,
                    "startedAtMonotonic": self.clock(),
                    "host": host,
                    "documentSessionId": doc_session,
                    "documentDisplayName": doc_name,
                },
                failure_code="EXCEL_SMART_FILL_JOB_FAILED",
                failure_message="智能填写后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
                public_metadata={
                    "runningMessage": RUNNING_MESSAGE,
                    "providerTimeoutSeconds": EXCEL_SMART_FILL_TIMEOUT_SECONDS,
                    "totalTimeoutSeconds": TOTAL_TIMEOUT_SECONDS,
                    "resultRetentionSeconds": retention_seconds,
                    "maxItems": MAX_ITEMS_PER_TASK,
                    "batchSize": MAX_ITEMS_PER_BATCH,
                    "currentBatch": 1,
                    "totalBatches": total_batches,
                    "completedBatchCount": 0,
                },
                safe_failure_codes=set(SAFE_ERROR_STATUSES),
                request_fingerprint=request_fingerprint,
                request_conflict_code="EXCEL_SMART_FILL_JOB_ID_CONFLICT",
                request_conflict_message="相同任务编号已绑定其他智能填写请求，请使用新的任务编号。",
                allow_running_cancel=True,
            )
            if doc_session:
                self._active_doc_sessions[(host, task_type, doc_session)] = job_id
            return submitted

    def _remember_write_identity(self, job_id: str, request: ExcelSmartFillRequest) -> None:
        source = getattr(request, "source", None)
        self._job_write_identity[job_id] = {
            "workbookId": str(getattr(request, "workbook_id", "") or ""),
            "sourceSnapshotHash": str(getattr(source, "snapshot_hash", "") or ""),
        }

    def _purge_expired_write_state(self) -> None:
        tracked = set(self._write_commits) | set(self._job_write_identity)
        if not tracked:
            return
        stale = []
        for job_id in tracked:
            if self.coordinator.get(job_id, task_type="excel.smart_fill") is None:
                stale.append(job_id)
        if not stale:
            return
        with self._write_lock:
            for job_id in stale:
                self._write_commits.pop(job_id, None)
                self._job_write_identity.pop(job_id, None)

    @staticmethod
    def _job_has_writable_preview(job: Dict) -> bool:
        status = str((job or {}).get("status") or "")
        if status == "completed":
            return True
        if status not in ("cancelled", "failed"):
            return False
        result = (job or {}).get("result") or {}
        items = result.get("items") or []
        return any(
            isinstance(item, dict) and item.get("status") == "completed"
            for item in items
        )

    def get(self, job_id: str) -> Optional[Dict]:
        self._purge_expired_write_state()
        job = self.coordinator.get(job_id, task_type="excel.smart_fill")
        if job is None:
            with self._write_lock:
                self._write_commits.pop(job_id, None)
                self._job_write_identity.pop(job_id, None)
            return None
        public = dict(job)
        commit = self._write_commits.get(job_id)
        if commit:
            if commit.get("writeCommitted"):
                public["writeCommitted"] = True
                public["writeResultRevision"] = commit.get("resultRevision")
            elif commit.get("writeReserved"):
                public["writeReserved"] = True
        return public

    def commit_write(self, job_id: str, payload) -> Dict:
        self._purge_expired_write_state()
        job = self.coordinator.get(job_id, task_type="excel.smart_fill")
        if job is None:
            raise AdapterError(
                "EXCEL_SMART_FILL_JOB_NOT_FOUND",
                "智能填写后台任务不存在或已过期。",
                status_code=404,
            )
        if not self._job_has_writable_preview(job):
            raise AdapterError(
                "EXCEL_SMART_FILL_WRITE_NOT_READY",
                "智能填写预览尚未完成，不能提交写入。",
                status_code=409,
            )
        body = payload or {}
        if hasattr(payload, "dict"):
            body = payload.dict(by_alias=True)
        elif hasattr(payload, "model_dump"):
            body = payload.model_dump(by_alias=True)
        workbook_id = str(body.get("workbookId") or body.get("workbook_id") or "")
        source_hash = str(body.get("sourceSnapshotHash") or body.get("source_snapshot_hash") or "")
        stage = str(body.get("stage") or "confirm").strip().lower()
        if stage not in ("reserve", "confirm", "release"):
            stage = "confirm"
        with self._write_lock:
            existing = self._write_commits.get(job_id)
            identity = self._job_write_identity.get(job_id) or {}
            expected_workbook = str(identity.get("workbookId") or "")
            expected_hash = str(identity.get("sourceSnapshotHash") or "")
            if (expected_workbook and workbook_id and expected_workbook != workbook_id) or (
                expected_hash and source_hash and expected_hash != source_hash
            ):
                raise AdapterError(
                    "EXCEL_SMART_FILL_WRITE_IDENTITY_MISMATCH",
                    "写入提交与当前预览任务的工作簿或来源快照不一致。",
                    status_code=409,
                )
            if stage == "release":
                if existing and existing.get("writeCommitted"):
                    raise AdapterError(
                        "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED",
                        "同一预览不能重复提交写入。",
                        status_code=409,
                    )
                self._write_commits.pop(job_id, None)
                return {"writeReserved": False, "writeCommitted": False}
            if existing and existing.get("writeCommitted"):
                raise AdapterError(
                    "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED",
                    "同一预览不能重复提交写入。",
                    status_code=409,
                )
            if stage == "reserve":
                if existing and existing.get("writeReserved"):
                    raise AdapterError(
                        "EXCEL_SMART_FILL_WRITE_ALREADY_COMMITTED",
                        "同一预览不能重复提交写入。",
                        status_code=409,
                    )
                record = {
                    "writeReserved": True,
                    "writeCommitted": False,
                    "resultRevision": int(body.get("resultRevision") or body.get("result_revision") or 1),
                    "sourceSnapshotHash": source_hash,
                    "workbookId": workbook_id,
                    "targetAddress": str(body.get("targetAddress") or body.get("target_address") or ""),
                    "itemCount": int(body.get("itemCount") or body.get("item_count") or 0),
                }
                self._write_commits[job_id] = record
                return record
            record = {
                "writeReserved": True,
                "writeCommitted": True,
                "resultRevision": int(body.get("resultRevision") or body.get("result_revision") or 1),
                "sourceSnapshotHash": source_hash,
                "workbookId": workbook_id,
                "targetAddress": str(body.get("targetAddress") or body.get("target_address") or ""),
                "itemCount": int(body.get("itemCount") or body.get("item_count") or 0),
            }
            self._write_commits[job_id] = record
            return record

    def cancel(self, job_id: str) -> Optional[Dict]:
        job = self.coordinator.request_cancel(job_id, task_type="excel.smart_fill")
        with self._submission_lock:
            for key, val in list(self._active_doc_sessions.items()):
                if val == job_id:
                    self._active_doc_sessions.pop(key, None)
        return job

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
        try:
            return self._run_internal(snapshot, progress)
        except Exception:
            doc_session = str(snapshot.get("documentSessionId") or "")
            host = str(snapshot.get("host") or "et")
            if doc_session:
                with self._submission_lock:
                    slot_key = (host, "excel.smart_fill", doc_session)
                    if self._active_doc_sessions.get(slot_key) == snapshot.get("jobId"):
                        self._active_doc_sessions.pop(slot_key, None)
            raise

    def _run_internal(self, snapshot: Dict, progress) -> Dict:
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
        if not batch.items:
            raise AdapterError(
                "EXCEL_SMART_FILL_JOB_FAILED",
                "智能填写任务没有可处理的目标单元格。",
                status_code=400,
            )
        if progress:
            progress("chunking")

        started = float(snapshot.get("startedAtMonotonic", self.clock()))
        now_mono = self.clock()
        remaining_total = max(0.0, TOTAL_TIMEOUT_SECONDS - (now_mono - started))
        if remaining_total <= 0:
            error = AdapterError(
                "EXCEL_SMART_FILL_DEADLINE_EXCEEDED",
                "智能填写任务超过 60 分钟总处理时限。",
                status_code=504,
            )
            error.partial_result = self._partial_result(
                snapshot, snapshot.get("results", []), "timeout"
            )
            raise error

        provider_timeout = min(EXCEL_SMART_FILL_TIMEOUT_SECONDS, remaining_total)
        if provider_timeout <= 0:
            error = AdapterError(
                "EXCEL_SMART_FILL_DEADLINE_EXCEEDED",
                "智能填写任务超过 60 分钟总处理时限。",
                status_code=504,
            )
            error.partial_result = self._partial_result(
                snapshot, snapshot.get("results", []), "timeout"
            )
            raise error

        provider_kwargs = {
            "timeout_seconds": provider_timeout,
            "deadline_monotonic": started + TOTAL_TIMEOUT_SECONDS,
            "clock": self.clock,
        }
        if snapshot.get("taskAuth") is not None:
            provider_kwargs["task_auth"] = snapshot["taskAuth"]

        try:
            try:
                result = self.smart_fill.fill_batch(
                    batch,
                    trace_id=snapshot.get("traceId", "") or "",
                    progress_callback=progress,
                    **provider_kwargs
                )
            except TypeError as err:
                if "unexpected keyword argument" in str(err):
                    safe_kwargs = {
                        k: v for k, v in provider_kwargs.items()
                        if k in {"task_auth", "progress_callback"}
                    }
                    result = self.smart_fill.fill_batch(
                        batch,
                        trace_id=snapshot.get("traceId", "") or "",
                        progress_callback=progress,
                        **safe_kwargs
                    )
                else:
                    raise
        except Exception as error:
            if isinstance(error, AdapterError) and getattr(error, "partial_result", None) is None:
                stop_reason = (
                    "timeout"
                    if "TIMEOUT" in getattr(error, "code", "").upper()
                    or getattr(error, "status_code", None) == 504
                    else "failed"
                )
                error.partial_result = self._partial_result(
                    snapshot, snapshot.get("results", []), stop_reason
                )
            raise

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
        next_index = start + len(batch.items)
        batch_count = int(snapshot.get("batchCount", 0)) + 1
        total_items = len(request.items)
        total_batches = max(batch_count + 1, math.ceil(total_items / max(1, batch_size)))
        if next_index < total_items:
            continuation = {
                **snapshot,
                "nextIndex": next_index,
                "results": combined,
                "batchCount": batch_count,
                "currentBatch": batch_count + 1,
                "totalBatches": total_batches,
                "provider": result.get("provider", ""),
            }
            return LongTaskContinuation(continuation, phase="chunking")
        self._raise_if_deadline_exceeded(
            {**snapshot, "results": combined, "batchCount": batch_count}
        )
        processed_result = {
            "schemaVersion": "excel.smart_fill.v2",
            "items": combined,
            "provider": result.get("provider", ""),
            "processedItemCount": len(combined),
            "batchCount": batch_count,
            "totalBatches": batch_count,
        }
        try:
            req = snapshot.get("request")
            doc_name = (
                snapshot.get("documentDisplayName")
                or getattr(req, "document_display_name", "")
                or getattr(req, "workbook_id", "")
                or "工作簿.xlsx"
            )
            auth = snapshot.get("taskAuth") or {}
            service_name = auth.get("serviceName") or auth.get("providerName") or "模型服务"
            model_name = auth.get("modelName") or result.get("provider") or "model"
            job_id = str(snapshot.get("jobId") or snapshot.get("traceId") or "")

            archived_items = [
                {
                    "itemId": item.get("itemId"),
                    "status": item.get("status"),
                    "valueType": item.get("valueType", "text"),
                    "value": item.get("value", ""),
                    "sourceRowIndex": item.get("sourceRowIndex"),
                    "sourceRowLabel": item.get("sourceRowLabel", ""),
                }
                for item in combined
                if isinstance(item, dict)
            ]
            archived_result = {
                "schemaVersion": "excel.smart_fill.v2",
                "processedItemCount": len(archived_items),
                "items": archived_items,
                "totalBatches": batch_count,
            }
            get_task_history_store().record_success(
                task_type="excel.smart_fill",
                job_id=job_id,
                result=archived_result,
                document_display_name=doc_name,
                service_name=service_name,
                model_name=model_name,
            )
        except TaskHistoryError as exc:
            if exc.code == "HISTORY_ENTRY_TOO_LARGE":
                processed_result["historyNotice"] = "任务结果超过 5 MiB，未写入历史记录。"
        except Exception:
            pass

        doc_session = str(snapshot.get("documentSessionId") or "")
        host = str(snapshot.get("host") or "et")
        if doc_session:
            with self._submission_lock:
                slot_key = (host, "excel.smart_fill", doc_session)
                if self._active_doc_sessions.get(slot_key) == snapshot.get("jobId"):
                    self._active_doc_sessions.pop(slot_key, None)

        return processed_result

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
            for item in request.items:
                if item.item_id in seen:
                    continue
                existing.append(
                    {
                        "itemId": item.item_id,
                        "status": "unprocessed",
                        "valueType": "text",
                        "value": "",
                    }
                )
        return {
            "schemaVersion": "excel.smart_fill.v2",
            "items": existing,
            "provider": str(snapshot.get("provider", "")),
            "processedItemCount": len(seen),
            "batchCount": int(snapshot.get("batchCount", 0)),
            "partial": True,
            "stopReason": stop_reason,
        }
