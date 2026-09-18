import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.health import (
    _CoreHealthError,
    _validate_model_configuration_data,
)

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import FullDocumentReviewBodyLimitMiddleware, app


class HealthValidationTests(unittest.TestCase):
    def test_active_direct_service_is_accepted_by_core_health_validation(
        self,
    ) -> None:
        task_type = "word.smart_write"
        service_id = "direct_svc_primary"
        _validate_model_configuration_data(
            {
                "modelConfigurations": {},
                "directServices": {
                    service_id: {
                        "id": service_id,
                        "name": "Primary",
                        "serviceBaseUrl": "https://api.example.test/v1",
                        "defaultModel": "model-a",
                    }
                },
                "taskModelSelections": {
                    task_type: {
                        "serviceId": service_id,
                        "modelName": "model-a",
                    }
                },
                "activeModelConfigurations": {task_type: service_id},
            }
        )

    def test_active_direct_service_rejects_a_missing_task_selection(self) -> None:
        task_type = "word.smart_write"
        service_id = "direct_svc_primary"
        with self.assertRaisesRegex(_CoreHealthError, "active direct service selection"):
            _validate_model_configuration_data(
                {
                    "modelConfigurations": {},
                    "directServices": {
                        service_id: {
                            "id": service_id,
                            "name": "Primary",
                            "serviceBaseUrl": "https://api.example.test/v1",
                            "defaultModel": "model-a",
                        }
                    },
                    "taskModelSelections": {},
                    "activeModelConfigurations": {task_type: service_id},
                }
            )


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

    def test_http_request_logs_duration_ms(self) -> None:
        client = TestClient(app)
        with patch("app.main.logger.info") as mock_info:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            logged_formats = [call.args[0] for call in mock_info.call_args_list if call.args]
            self.assertTrue(
                any("durationMs=%s" in fmt or "durationMs=" in fmt for fmt in logged_formats),
                "HTTP request log format must include durationMs=%s",
            )

    def test_http_request_logs_duration_ms_for_early_rejection(self) -> None:
        client = TestClient(app)
        with patch("app.main.logger.info") as mock_info:
            response = client.post(
                "/ppt/document-files",
                content=b"",
                headers={"Content-Length": "0"},
            )

        self.assertEqual(response.status_code, 411)
        matching_calls = [
            call
            for call in mock_info.call_args_list
            if call.args and "durationMs=%s" in call.args[0]
        ]
        self.assertEqual(len(matching_calls), 1)
        self.assertEqual(matching_calls[0].args[4], 411)

    def test_outer_body_limit_declared_rejection_logs_duration_ms(self) -> None:
        client = TestClient(app)
        with patch("app.main.logger.info") as mock_info:
            response = client.post(
                "/word/document-review/full/jobs",
                content=b"{}",
                headers={"Content-Length": str(2 * 1024 * 1024 + 1)},
            )

        self.assertEqual(response.status_code, 413)
        matching_calls = [
            call
            for call in mock_info.call_args_list
            if call.args and "durationMs=%s" in call.args[0]
        ]
        self.assertEqual(len(matching_calls), 1)
        self.assertEqual(matching_calls[0].args[4], 413)

    def test_outer_body_limit_streaming_rejection_logs_duration_ms(self) -> None:
        async def inner_app(_scope, _receive, _send):
            raise AssertionError("oversized body must not reach inner app")

        middleware = FullDocumentReviewBodyLimitMiddleware(inner_app, max_bytes=4)
        messages = [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
        sent = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/word/document-review/full/jobs",
            "headers": [(b"x-trace-id", b"trace-stream-limit")],
        }
        with patch("app.main.logger.info") as mock_info:
            asyncio.run(middleware(scope, receive, send))

        self.assertEqual(sent[0]["status"], 413)
        matching_calls = [
            call
            for call in mock_info.call_args_list
            if call.args and "durationMs=%s" in call.args[0]
        ]
        self.assertEqual(len(matching_calls), 1)
        self.assertEqual(matching_calls[0].args[4], 413)

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
        self.assertFalse(data["operationPolicy"]["writingPolicyMutationsAllowed"])
        self.assertEqual(mutation_response.status_code, 503)
        self.assertEqual(
            mutation_response.json()["errors"][0]["code"],
            "ADAPTER_RECOVERY_MODE",
        )
        self.assertEqual(task_response.status_code, 503)
        serialized = json.dumps(aggregate_response.json(), ensure_ascii=False)
        self.assertNotIn(str(config_path), serialized)

    def test_active_direct_service_is_valid_model_configuration_state(self) -> None:
        task_type = "word.smart_write"
        service_id = "direct_svc_primary"
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "modelConfigurations": {},
                        "directServices": {
                            service_id: {
                                "id": service_id,
                                "name": "Primary",
                                "serviceBaseUrl": "https://api.example.test/v1",
                                "defaultModel": "model-a",
                            }
                        },
                        "taskModelSelections": {
                            task_type: {
                                "serviceId": service_id,
                                "modelName": "model-a",
                            }
                        },
                        "activeModelConfigurations": {
                            task_type: service_id,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ):
                response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["subsystems"]["modelConfigurations"]["status"], "ready")
        self.assertTrue(data["operationPolicy"]["configurationMutationsAllowed"])
        self.assertTrue(data["operationPolicy"]["modelTasksAllowed"])

    def test_active_direct_service_requires_matching_task_selection(self) -> None:
        task_type = "word.smart_write"
        service_id = "direct_svc_primary"
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "modelConfigurations": {},
                        "directServices": {
                            service_id: {
                                "id": service_id,
                                "name": "Primary",
                                "serviceBaseUrl": "https://api.example.test/v1",
                                "defaultModel": "model-a",
                            }
                        },
                        "taskModelSelections": {},
                        "activeModelConfigurations": {
                            task_type: service_id,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "app.services.health.default_config_path",
                return_value=config_path,
            ):
                response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "recovery")
        self.assertEqual(
            data["subsystems"]["modelConfigurations"]["errorCode"],
            "MODEL_CONFIGURATION_DATA_INVALID",
        )

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
