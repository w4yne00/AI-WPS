import json
from pathlib import Path

from app.services.template_loader import TemplateLoader
from app.services.word.format_rule_pack import FormatRulePackError, FormatRulePackLoader


def test_template_loader_returns_only_the_active_rule_pack() -> None:
    template_root = (
        Path(__file__).resolve().parents[2] / "templates"
    )
    loader = TemplateLoader(str(template_root))

    templates = loader.list_templates()

    assert templates == [
        {
            "id": "technical-document-template-rules",
            "name": "技术文档模板规则",
            "path": str(
                Path(__file__).resolve().parents[2]
                / "adapter_service/format_rule_packs/technical-document-template-rules.v1.0.0.json"
            ),
        }
    ]


def test_template_loader_fails_closed_when_the_active_pack_is_unavailable(tmp_path) -> None:
    loader = TemplateLoader(rule_pack_loader=FormatRulePackLoader(tmp_path))

    try:
        loader.list_templates()
    except FormatRulePackError:
        return
    assert False, "missing active rule pack must not produce a template fallback"


def test_historical_template_boundary_is_explicitly_inactive() -> None:
    manifest = Path(__file__).resolve().parents[2] / "templates/history/inactive/manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["status"] == "inactive"
    assert {item["id"] for item in payload["assets"]} >= {
        "general-office",
        "technical-file-format-requirements",
    }
    assert all(item["status"] == "inactive" for item in payload["assets"])
