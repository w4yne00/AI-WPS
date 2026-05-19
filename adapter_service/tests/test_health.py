import importlib.util
import unittest

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class HealthApiTests(unittest.TestCase):
    def test_health_returns_service_metadata(self) -> None:
        client = TestClient(app)
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)

        body = response.json()
        data = body["data"]
        self.assertTrue(body["success"])
        self.assertEqual(data["service"], "wps-ai-adapter")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], "0.11.2-alpha")
        self.assertIn("providerBaseUrlConfigured", data)
        self.assertIn("taskRouteConfiguredCount", data)
        self.assertIn("providerAuthSource", data)
