import re
from typing import Dict, Optional

from app.core.models import ExcelFormulaAssistantRequest
from app.services.excel.formula_assistant import ExcelFormulaAssistant
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.provider_client import EXCEL_FORMULA_ASSISTANT_TIMEOUT_SECONDS


CLIENT_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
RUNNING_MESSAGE = "模型后台正在处理公式任务，adapter 会继续等待结果。"
SAFE_ERROR_STATUSES = {
    "EXCEL_FORMULA_REQUIREMENT_REQUIRED": 400,
    "EXCEL_FORMULA_SELECTION_REQUIRED": 400,
    "EXCEL_FORMULA_SELECTION_TOO_LARGE": 400,
    "EXCEL_FORMULA_TO_EXPLAIN_REQUIRED": 400,
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


class ExcelFormulaAssistantJobStore:
    def __init__(
        self,
        assistant: Optional[ExcelFormulaAssistant] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
    ) -> None:
        self.assistant = assistant or ExcelFormulaAssistant()
        self.coordinator = coordinator or get_long_task_coordinator()

    def start(self, request: ExcelFormulaAssistantRequest, trace_id: str) -> Dict:
        job_id = normalize_client_job_id(getattr(request, "client_job_id", "")) or trace_id
        existing = self.coordinator.get(
            job_id, task_type="excel.formula_assistant"
        )
        if existing is not None:
            return existing
        snapshot_task_auth = getattr(self.assistant, "snapshot_task_auth", None)
        task_auth = snapshot_task_auth() if callable(snapshot_task_auth) else None
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type="excel.formula_assistant",
            runner=self._run,
            snapshot={"request": request, "taskAuth": task_auth},
            failure_code="EXCEL_FORMULA_JOB_FAILED",
            failure_message="公式助手后台任务执行失败，请稍后重试或查看最近一次任务诊断。",
            public_metadata={
                "runningMessage": RUNNING_MESSAGE,
                "providerTimeoutSeconds": EXCEL_FORMULA_ASSISTANT_TIMEOUT_SECONDS,
            },
            safe_failure_codes=set(SAFE_ERROR_STATUSES),
        )

    def get(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.get(job_id, task_type="excel.formula_assistant")

    def cancel(self, job_id: str) -> Optional[Dict]:
        return self.coordinator.cancel(job_id, task_type="excel.formula_assistant")

    def _run(self, snapshot: Dict, progress) -> Dict:
        kwargs = {"progress_callback": progress}
        if snapshot.get("taskAuth") is not None:
            kwargs["task_auth"] = snapshot["taskAuth"]
        return self.assistant.generate(
            snapshot["request"],
            trace_id=snapshot.get("traceId", "") or "",
            **kwargs
        )
