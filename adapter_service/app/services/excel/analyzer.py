from copy import deepcopy
from typing import Callable, Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelAnalysisRequest
from app.services.provider_client import ProviderClient


class ExcelAnalyzer:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver("excel.analysis"))
        except Exception as exc:
            raise AdapterError(
                "EXCEL_ANALYSIS_AUTH_SNAPSHOT_FAILED",
                "智能分析工作流配置暂时无法读取，请检查设置后重试。",
                status_code=503,
            ) from exc

    def analyze(
        self,
        request: ExcelAnalysisRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if progress_callback:
            progress_callback("preparing")
        if not self._has_usable_table(request):
            raise AdapterError(
                "EXCEL_ANALYSIS_TABLE_REQUIRED",
                "未读取到可分析的表格数据，请先选择表格区域或确认当前工作表存在数据。",
                status_code=400,
            )
        if progress_callback:
            progress_callback("provider_processing")
        provider_kwargs = {}
        if task_auth is not None:
            provider_kwargs["task_auth"] = task_auth
        if progress_callback is not None:
            provider_kwargs["progress_callback"] = progress_callback
        provider_result = self.provider_client.excel_analysis(
            request,
            trace_id=trace_id,
            **provider_kwargs
        )
        return {
            "structuredReport": provider_result["structuredReport"],
            "plainText": provider_result.get("plainText", ""),
            "provider": provider_result.get("provider", "mock"),
        }

    def _has_usable_table(self, request: ExcelAnalysisRequest) -> bool:
        if request.table.headers:
            return True
        return any(any(str(cell).strip() for cell in row) for row in request.table.rows)
