from pathlib import Path

from app.core.config import load_settings


def test_load_settings_reads_example_file(tmp_path: Path) -> None:
    config_file = tmp_path / "adapter.json"
    config_file.write_text(
        '{"servicePort": 18100, "difyBaseUrl": "http://intranet"}',
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.service_port == 18100
    assert settings.dify_base_url == "http://intranet"
