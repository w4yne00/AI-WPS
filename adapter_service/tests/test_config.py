from pathlib import Path
import importlib.util
import tempfile
import unittest

from app.core.config import load_settings

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app


def test_load_settings_reads_example_file(tmp_path: Path) -> None:
    config_file = tmp_path / "adapter.json"
    config_file.write_text(
        '{"servicePort": 18100, "difyBaseUrl": "http://intranet"}',
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.service_port == 18100
    assert settings.dify_base_url == "http://intranet"


def test_load_settings_defaults_timeout_for_slow_model_backend(tmp_path: Path) -> None:
    config_file = tmp_path / "adapter.json"
    config_file.write_text("{}", encoding="utf-8")

    settings = load_settings(config_file)

    assert settings.timeout_seconds == 75


class ConfigSettingsTests(unittest.TestCase):
    def test_load_settings_defaults_timeout_for_slow_model_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "adapter.json"
            config_file.write_text("{}", encoding="utf-8")

            settings = load_settings(config_file)

        self.assertEqual(settings.timeout_seconds, 75)


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class ConfigApiTests(unittest.TestCase):
    def test_config_exposes_unified_provider_status_and_empty_routes(self) -> None:
        client = TestClient(app)

        response = client.get("/config")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        data = body["data"]
        self.assertIn("providerBaseUrlConfigured", data)
        self.assertIn("providerAuthSource", data)
        self.assertIn("taskApiKeys", data)
        self.assertEqual(
            list(data["taskApiKeys"].keys()),
            [
                "word.smart_write",
                "word.smart_imitation",
                "word.document_review",
                "word.format_review",
                "excel.analysis",
                "ppt.slide_assistant",
            ],
        )
        self.assertEqual(data["providerChatPath"], "/chat-messages")
        self.assertEqual(data["taskRouteConfiguredCount"], 0)
        self.assertIn("taskRoutes", data)
        self.assertEqual(data["taskRoutes"], {})
