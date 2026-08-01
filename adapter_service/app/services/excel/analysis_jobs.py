import re
from typing import Dict, Optional

from app.core.models import ExcelAnalysisRequest
from app.services.excel.analyzer import ExcelAnalyzer
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import EXCEL_ANALYSIS_TIMEOUT_SECONDS


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理智能分析，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_ANALYSIS_TABLE_REQUIRED": 400,
    "PROVIDER_AUTH_FAILED": 401,
    "PROVIDER_UNREACHABLE": 502,
    "PROVIDER_TIMEOUT": 504,
    "DIFY_AUTH_FAILED": 401,
    "DIFY_UNREACHABLE": 502,
    "DIFY_TIMEOUT": 504,
}


def normalize_client_job_id(value: str) -> str:
    text = str(value or "").strip()
    if CLIENT_JOB_ID_PATTERN.match(text):
        return text
    return ""


class ExcelAnalysisJobStore:
    def __init__(
        self,
        analyzer: Optional[ExcelAnalyzer] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.analyzer = analyzer or ExcelAnalyzer()
        self.coordinator = coordinator or get_long_task_coordinator()

    def start(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        existing = self.coordinator.get(job_id, task_type="excel.analysis")
        if existing is not None:
            return existing
        snapshot_task_auth = getattr(self.analyzer, "snapshot_task_auth", None)
        task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type="excel.analysis",
            runner=self._run,
            snapshot={"request": request, "taskAuth": task_auth},
            failure_code="EXCEL_ANALYSIS_JOB_FAILED",
            failure_message="智能分析后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
            public_metadata={
                "runningMessage": RUNNING_MESSAGE,
                "providerTimeoutSeconds": EXCEL_ANALYSIS_TIMEOUT_SECONDS,
            },
            safe_failure_codes=set(SAFE_ERROR_STATUSES),
        )

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="excel.analysis")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="excel.analysis")

    def run_sync(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        job = self.start(request, trace_id)
        return self.coordinator.wait_result(
            job["jobId"],
            task_type="excel.analysis",
            not_found_code="EXCEL_ANALYSIS_JOB_NOT_FOUND",
            not_found_message="智能分析后台任务不存在或已过期。",
            cancelled_message="排队中的智能分析任务已取消。",
            failure_code="EXCEL_ANALYSIS_JOB_FAILED",
            failure_message="智能分析后台任务执行失败。",
            safe_error_statuses=SAFE_ERROR_STATUSES,
        )

    def _run(self, snapshot: Dict, progress) -> Dict:
        analyzer_kwargs = {"progress_callback": progress}
        if snapshot.get("taskAuth") is not None:
            analyzer_kwargs["task_auth"] = snapshot["taskAuth"]
        return self.analyzer.analyze(
            snapshot["request"],
            trace_id=snapshot.get("traceId", "") or "",
            **analyzer_kwargs
        )
