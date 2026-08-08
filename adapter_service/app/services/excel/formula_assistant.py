from copy import deepcopy
from typing import Callable, Dict, Optional

from app.core.errors import AdapterError
from app.core.models import ExcelFormulaAssistantRequest
from app.services.excel.formula_checks import inspect_formula
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
        mode = request.options.mode
        if mode == "generate" and not request.options.requirement.strip():
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
        original_formula = self._first_selected_formula(request)
        if mode == "explain" and not original_formula:
            raise AdapterError(
                "EXCEL_FORMULA_TO_EXPLAIN_REQUIRED",
                "解释排错模式需要选区中包含已有公式，请先选中公式单元格。",
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
        alternative_formula = result.get("alternativeFormula", "")
        if alternative_formula == primary_formula:
            alternative_formula = ""
        checked_formula = primary_formula
        return {
            "mode": mode,
            "originalFormula": original_formula if mode == "explain" else "",
            "primaryFormula": primary_formula,
            "alternativeFormula": alternative_formula,
            "suggestedTarget": result.get("suggestedTarget", ""),
            "explanation": result.get("explanation", ""),
            "components": result.get("components", []),
            "referenceRanges": result.get("referenceRanges", []),
            "issues": result.get("issues", []),
            "assumptions": result.get("assumptions", []),
            "compatibilityNotes": result.get("compatibilityNotes", []),
            "localCheck": inspect_formula(
                checked_formula,
                selection_address=request.selection.address,
            ) if checked_formula else {
                "status": "risks",
                "summary": "未找到可执行基础检查的公式",
                "checkedFormula": "",
                "risks": [],
            },
            "rawFinalResult": result.get("rawFinalResult", ""),
            "parseDiagnostic": result.get("parseDiagnostic", ""),
            "copyText": (
                result.get("copyText", "")
                if result.get("parseDiagnostic")
                else primary_formula
            ),
            "provider": result.get("provider", "mock"),
        }

    @staticmethod
    def _first_selected_formula(request: ExcelFormulaAssistantRequest) -> str:
        for row in request.selection.cells:
            for cell in row:
                formula = cell.formula.strip()
                if formula:
                    return formula
        return ""

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
