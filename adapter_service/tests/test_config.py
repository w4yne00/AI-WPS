from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

from app.core.config import load_settings

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.config import (
        ImageSemanticSettingsRequest,
        get_image_semantic_settings,
        update_image_semantic_settings,
    )


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
    def test_image_semantics_api_defaults_on_without_wps_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "adapter.json"
            with patch(
                "app.api.config.default_config_path", return_value=config_path
            ):
                self.assertTrue(get_image_semantic_settings()["data"]["enabled"])
                self.assertNotIn(
                    "wpsAcceptanceConfirmed",
                    get_image_semantic_settings()["data"],
                )
                disabled = update_image_semantic_settings(
                    ImageSemanticSettingsRequest(enabled=False)
                )
                enabled = update_image_semantic_settings(
                    ImageSemanticSettingsRequest(enabled=True)
                )

            self.assertFalse(disabled["data"]["enabled"])
            self.assertTrue(enabled["data"]["enabled"])
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(persisted["formatReview"]["imageSemantics"]["enabled"])
            self.assertNotIn(
                "wpsAcceptanceConfirmed",
                persisted["formatReview"]["imageSemantics"],
            )

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
                "excel.formula_assistant",
                "ppt.slide_assistant",
                "ppt.structure_review",
            ],
        )
        self.assertEqual(data["providerChatPath"], "/chat-messages")
        self.assertEqual(data["taskRouteConfiguredCount"], 0)
        self.assertIn("taskRoutes", data)
        self.assertEqual(data["taskRoutes"], {})

    def test_route_diagnostics_exposes_sanitized_long_task_capacity(self) -> None:
        client = TestClient(app)

        response = client.get("/provider/route-diagnostics")

        self.assertEqual(response.status_code, 200)
        coordinator = response.json()["data"]["longTaskCoordinator"]
        self.assertEqual(coordinator["maxRunning"], 2)
        self.assertEqual(coordinator["maxQueued"], 8)
        self.assertEqual(coordinator["terminalTtlSeconds"], 7200)
        self.assertEqual(coordinator["maxTerminalJobs"], 50)
        self.assertIn("recentTerminalJobs", coordinator)
        self.assertNotIn("apiKey", str(coordinator))
