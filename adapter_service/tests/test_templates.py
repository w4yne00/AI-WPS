from pathlib import Path

from app.services.template_loader import TemplateLoader


def test_template_loader_returns_general_template() -> None:
    template_root = (
        Path(__file__).resolve().parents[2] / "templates"
    )
    loader = TemplateLoader(str(template_root))

    templates = loader.list_templates()

    assert any(item["id"] == "general-office" for item in templates)
    assert any(item["id"] == "technical-file-format-requirements" for item in templates)
    assert not any(item["id"] == "rules" for item in templates)
