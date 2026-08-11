import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["version"], "0.23.1-alpha")
        self.assertIn("providerBaseUrlConfigured", data)
        self.assertIn("taskRouteConfiguredCount", data)
        self.assertIn("providerAuthSource", data)

    def test_live_health_does_not_read_business_subsystems(self) -> None:
        client = TestClient(app)

        with patch(
            "app.api.health.get_health_snapshot",
            side_effect=AssertionError("liveness must not read business data"),
            create=True,
        ):
            response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "live")

    def test_ready_and_aggregate_report_degraded_writing_policy_without_leaks(self) -> None:
        class BrokenWritingPolicyStore:
            error_code = "writing_policy_io_error"

            def summary(self):
                raise OSError("secret-key at /private/runtime/writing-policy.db")

        class BrokenWritingPolicyService:
            store = BrokenWritingPolicyStore()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ), patch(
                "app.services.health.get_writing_policy_service",
                return_value=BrokenWritingPolicyService(),
            ):
                client = TestClient(app)
                ready_response = client.get("/health/ready")
                aggregate_response = client.get("/health")

        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["data"]["status"], "degraded")
        self.assertEqual(aggregate_response.status_code, 200)
        data = aggregate_response.json()["data"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["subsystems"]["writingPolicies"]["status"], "degraded")
        self.assertEqual(
            data["subsystems"]["writingPolicies"]["errorCode"],
            "WRITING_POLICY_IO_ERROR",
        )
        serialized = json.dumps(aggregate_response.json(), ensure_ascii=False)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("/private/runtime", serialized)

    def test_recovery_health_returns_503_ready_and_blocks_unsafe_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(
                '{"modelConfigurations": {"broken": ',
                encoding="utf-8",
            )
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ):
                client = TestClient(app)
                live_response = client.get("/health/live")
                ready_response = client.get("/health/ready")
                aggregate_response = client.get("/health")
                mutation_response = client.post(
                    "/provider/base-url",
                    json={"baseUrl": "https://should-not-write.example.test"},
                )
                task_response = client.post("/excel/analysis/jobs", json={})

        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(ready_response.status_code, 503)
        self.assertEqual(ready_response.json()["data"]["status"], "recovery")
        self.assertEqual(aggregate_response.status_code, 200)
        data = aggregate_response.json()["data"]
        self.assertEqual(data["status"], "recovery")
        self.assertFalse(data["operationPolicy"]["configurationMutationsAllowed"])
        self.assertFalse(data["operationPolicy"]["modelTasksAllowed"])
        self.assertEqual(mutation_response.status_code, 503)
        self.assertEqual(
            mutation_response.json()["errors"][0]["code"],
            "ADAPTER_RECOVERY_MODE",
        )
        self.assertEqual(task_response.status_code, 503)
        serialized = json.dumps(aggregate_response.json(), ensure_ascii=False)
        self.assertNotIn(str(config_path), serialized)

    def test_invalid_task_route_enters_recovery_without_exposing_route_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "taskRoutes": {
                            "excel.analysis": {
                                "path": "/v1/workflows/run\nprivate-token",
                                "apiKeyRef": "analysis-key",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ):
                client = TestClient(app)
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "recovery")
        self.assertEqual(data["subsystems"]["taskRoutes"]["status"], "recovery")
        self.assertEqual(
            data["subsystems"]["taskRoutes"]["errorCode"],
            "TASK_ROUTE_DATA_INVALID",
        )
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("analysis-key", serialized)

    def test_recovery_health_redacts_model_key_refs_and_provider_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "providerName": "secret-provider-/private/runtime",
                        "providerType": "secret-provider-type",
                        "modelConfigurations": {
                            "broken": {
                                "id": "broken",
                                "taskType": "word.smart_write",
                                "apiKeyRef": "../../secret-key-ref",
                            }
                        },
                        "activeModelConfigurations": {
                            "word.smart_write": "broken"
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ):
                client = TestClient(app)
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "recovery")
        self.assertEqual(data["providerType"], "unknown")
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn("secret-provider", serialized)
        self.assertNotIn("secret-key-ref", serialized)
        self.assertNotIn("/private/runtime", serialized)
        self.assertNotIn("apiKeyRef", serialized)

    def test_degraded_writing_policy_is_read_only_while_core_remains_ready(self) -> None:
        class BrokenWritingPolicyStore:
            error_code = "writing_policy_data_corrupt"

            def summary(self):
                raise RuntimeError("corrupt")

        class BrokenWritingPolicyService:
            store = BrokenWritingPolicyStore()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ), patch(
                "app.services.health.get_writing_policy_service",
                return_value=BrokenWritingPolicyService(),
            ):
                client = TestClient(app)
                response = client.post("/writing-policies/items", json={})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["errors"][0]["code"],
            "WRITING_POLICY_READ_ONLY",
        )
