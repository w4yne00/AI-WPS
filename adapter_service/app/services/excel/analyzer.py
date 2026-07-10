from typing import Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelAnalysisRequest
from app.services.provider_client import ProviderClient


class ExcelAnalyzer:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def analyze(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        if not self._has_usable_table(request):
            raise AdapterError(
                "EXCEL_ANALYSIS_TABLE_REQUIRED",
                "未读取到可分析的表格数据，请先选择表格区域或确认当前工作表存在数据。",
                status_code=400,
            )
        provider_result = self.provider_client.excel_analysis(request, trace_id=trace_id)
        return {
            "structuredReport": provider_result["structuredReport"],
            "plainText": provider_result.get("plainText", ""),
            "provider": provider_result.get("provider", "mock"),
        }

    def _has_usable_table(self, request: ExcelAnalysisRequest) -> bool:
        if request.table.headers:
            return True
        return any(any(str(cell).strip() for cell in row) for row in request.table.rows)
