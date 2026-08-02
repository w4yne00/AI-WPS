from copy import deepcopy
from typing import Callable, Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelFormulaAssistantRequest
from app.services.provider_client import ProviderClient


class ExcelFormulaAssistant:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver("excel.formula_assistant"))
        except Exception as exc:
            raise AdapterError(
                "EXCEL_FORMULA_AUTH_SNAPSHOT_FAILED",
                "公式助手工作流配置暂时无法读取，请检查设置后重试。",
                status_code=503,
            ) from exc

    def generate(
        self,
        request: ExcelFormulaAssistantRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if progress_callback:
            progress_callback("preparing")
        if not request.options.requirement.strip():
            raise AdapterError(
                "EXCEL_FORMULA_REQUIREMENT_REQUIRED",
                "请填写需要计算的内容。",
                status_code=400,
            )
        if not self._has_explicit_selection(request):
            raise AdapterError(
                "EXCEL_FORMULA_SELECTION_REQUIRED",
                "未读取到明确选区，请先框选相关表格范围。公式助手不会读取已用范围。",
                status_code=400,
            )
        if not self._selection_within_capture_budget(request):
            raise AdapterError(
                "EXCEL_FORMULA_SELECTION_TOO_LARGE",
                "选区上下文超过 30 行 × 20 列的读取上限，请重新框选后再试。",
                status_code=400,
            )
        self._derive_truncation_state(request)
        if progress_callback:
            progress_callback("provider_processing")
        provider_kwargs = {}
        if task_auth is not None:
            provider_kwargs["task_auth"] = task_auth
        if progress_callback is not None:
            provider_kwargs["progress_callback"] = progress_callback
        result = self.provider_client.excel_formula_assistant(
            request,
            trace_id=trace_id,
            **provider_kwargs
        )
        primary_formula = result.get("primaryFormula", "")
        return {
            "primaryFormula": primary_formula,
            "suggestedTarget": result.get("suggestedTarget", ""),
            "explanation": result.get("explanation", ""),
            "assumptions": result.get("assumptions", []),
            "compatibilityNotes": result.get("compatibilityNotes", []),
            "copyText": primary_formula,
            "provider": result.get("provider", "mock"),
        }

    @staticmethod
    def _has_explicit_selection(request: ExcelFormulaAssistantRequest) -> bool:
        selection = request.selection
        if not selection.address.strip() or not selection.row_count or not selection.column_count:
            return False
        return any(
            cell.text.strip() or cell.formula.strip()
            for row in selection.cells
            for cell in row
        )

    @staticmethod
    def _selection_within_capture_budget(
        request: ExcelFormulaAssistantRequest,
    ) -> bool:
        selection = request.selection
        return (
            len(selection.cells) <= 30
            and len(selection.headers) <= 20
            and all(len(row) <= 20 for row in selection.cells)
        )

    @staticmethod
    def _derive_truncation_state(request: ExcelFormulaAssistantRequest) -> None:
        selection = request.selection
        captured_rows = len(selection.cells)
        captured_columns = max(
            [len(row) for row in selection.cells] or [len(selection.headers)]
        )
        selection.truncated = bool(
            selection.truncated
            or selection.row_count > captured_rows
            or selection.column_count > captured_columns
        )
