from pathlib import Path
import importlib.util
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


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class ConfigApiTests(unittest.TestCase):
    def test_config_exposes_route_counts_without_global_auth_source(self) -> None:
        client = TestClient(app)

        response = client.get("/config")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        data = body["data"]
        self.assertIn("providerBaseUrlConfigured", data)
        self.assertIn("taskRouteConfiguredCount", data)
        self.assertIn("taskRoutes", data)
        self.assertNotIn("providerAuthSource", data)
