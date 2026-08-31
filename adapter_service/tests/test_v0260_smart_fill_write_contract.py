import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "packaging/audit_v0260_preview1_delivery.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_v0260_preview1_delivery", AUDIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_audit_rejects_plugin_without_smart_fill_write_contract(tmp_path):
    module = _load_audit()
    plugin = tmp_path / "packages/wps-ai-assistant-et_1.0.0"
    plugin.mkdir(parents=True)
    (plugin / "ribbon.xml").write_text(
        '<button id="btnAiExcelSmartFill" label="智能填写"/>',
        encoding="utf-8",
    )
    (plugin / "taskpane.html").write_text(
        "<button>生成预览</button>",
        encoding="utf-8",
    )
    (plugin / "taskpane.js").write_text(
        "function render() { return 'preview'; }",
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "packages/adapter-start-kit/adapter_service/system_prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "excel-smart-fill.md").write_text(
        "schemaVersion excel.smart_fill.v1",
        encoding="utf-8",
    )

    with pytest.raises(module.DeliveryFailure) as error_info:
        module.audit_smart_fill_write_contract(tmp_path)
    assert "SMART_FILL_WRITE" in str(error_info.value)


def test_preview_audit_rejects_undo_promise_in_excel_plugin(tmp_path):
    module = _load_audit()
    plugin = tmp_path / "packages/wps-ai-assistant-et_1.0.0"
    plugin.mkdir(parents=True)
    (plugin / "ribbon.xml").write_text(
        '<button id="btnAiExcelSmartFill" label="智能填写"/>',
        encoding="utf-8",
    )
    (plugin / "taskpane.html").write_text(
        "<button>生成预览</button><button>写入内容</button><button>撤销</button>",
        encoding="utf-8",
    )
    (plugin / "taskpane.js").write_text(
        "consumeExcelSmartFillPreview(); buildExcelSmartFillReadonlyPreview();",
        encoding="utf-8",
    )
    (plugin / "taskpane-helpers.js").write_text(
        "function foo() {}",
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "packages/adapter-start-kit/adapter_service/system_prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "excel-smart-fill.md").write_text(
        "schemaVersion excel.smart_fill.v1",
        encoding="utf-8",
    )

    with pytest.raises(module.DeliveryFailure) as error_info:
        module.audit_smart_fill_write_contract(tmp_path)
    assert "SMART_FILL_UNDO" in str(error_info.value)


def test_preview_audit_rejects_plugin_without_compensation_contract(tmp_path):
    module = _load_audit()
    plugin = tmp_path / "packages/wps-ai-assistant-et_1.0.0"
    plugin.mkdir(parents=True)
    (plugin / "ribbon.xml").write_text(
        '<button id="btnAiExcelSmartFill" label="智能填写"/>',
        encoding="utf-8",
    )
    (plugin / "taskpane.html").write_text(
        "<button>生成预览</button><button>写入内容</button>",
        encoding="utf-8",
    )
    (plugin / "taskpane.js").write_text(
        "buildExcelSmartFillReadonlyPreview(); finalizeExcelSmartFillWriteSuccess(); "
        "buildExcelSmartFillDefaultSource(); describeExcelSmartFillHostCell(); "
        "writeExcelSmartFillCells(); COMPENSATION_FAILED; COMPENSATION_SUCCEEDED; 内部故障处理;",
        encoding="utf-8",
    )
    (plugin / "taskpane-helpers.js").write_text(
        "function foo() {}",
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "packages/adapter-start-kit/adapter_service/system_prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "excel-smart-fill.md").write_text(
        "schemaVersion excel.smart_fill.v1",
        encoding="utf-8",
    )

    with pytest.raises(module.DeliveryFailure) as error_info:
        module.audit_smart_fill_write_contract(tmp_path)
    assert "SMART_FILL_COMPENSATION_CONTRACT_MISSING" in str(error_info.value)


def test_source_tree_excel_plugin_satisfies_single_cell_write_contract():
    module = _load_audit()
    module.audit_smart_fill_write_contract(
        ROOT,
        plugin_root=ROOT / "formal-plugin-kit/wps-ai-assistant-et_1.0.0",
        prompt_path=ROOT / "adapter_service/system_prompts/excel-smart-fill.md",
    )
