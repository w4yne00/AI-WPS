import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

from app.core.errors import AdapterError
from app.core.models import ExcelAnalysisRequest
from app.services.direct_services import (
    DIRECT_SERVICE_SCHEMA_VERSION,
    TASK_MODEL_SELECTION_SCHEMA_VERSION,
    DirectServiceError,
    DirectServiceStore,
)
from app.services.model_configurations import ModelConfigurationStore
from app.services.provider_client import ACCESS_DIRECT_MODEL, ACCESS_WORKFLOW_PLATFORM, ProviderClient


class TracerExcelDirectServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "adapter.json"
        self.api_key_dir = self.root / "provider_api_keys"
        self.api_key_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.direct_store = DirectServiceStore(self.config_path, self.api_key_dir)
        self.model_store = ModelConfigurationStore(self.config_path, self.api_key_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_single_api_key_lifecycle_without_plaintext_echo(self) -> None:
        """Requirement: New service only requires single API Key; never echoed in plain text."""
        service = self.direct_store.create_service(
            name="共享网关",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.assertEqual(service["revision"], 1)
        self.assertFalse(service["keyConfigured"])
        self.assertNotIn("apiKey", service)

        # Save single key
        updated = self.direct_store.replace_api_key(
            service["id"], "sk-single-secret-key-12345", expected_revision=1
        )
        self.assertTrue(updated["keyConfigured"])
        self.assertNotIn("apiKey", updated)
        self.assertEqual(updated["revision"], 2)

        # Get service without secret must never return apiKey
        sanitized = self.direct_store.get_service(service["id"], include_secret=False)
        self.assertNotIn("apiKey", sanitized)

        # Internal get with secret reads from isolated key file
        internal = self.direct_store.get_service(service["id"], include_secret=True)
        self.assertEqual(internal["apiKey"], "sk-single-secret-key-12345")

    def test_refresh_models_success(self) -> None:
        """Requirement: Read remote model catalog, update modelList, modelListFetchedAt, and revision."""
        service = self.direct_store.create_service(
            name="模型目录测试服务",
            service_base_url="https://api.openai.com/v1",
            default_model="",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test", expected_revision=1)

        mock_models_response = json.dumps({
            "object": "list",
            "data": [
                {"id": "gpt-4o", "object": "model"},
                {"id": "gpt-4o-mini", "object": "model"},
                {"id": "text-embedding-3-small", "object": "model"}
            ]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_models_response
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            refreshed = self.direct_store.refresh_models(service["id"], expected_revision=2)

        self.assertEqual(refreshed["revision"], 3)
        self.assertEqual(refreshed["modelList"], ["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"])
        self.assertTrue(refreshed["modelListFetchedAt"])
        self.assertFalse(self.direct_store.is_model_list_expired(refreshed))

    def test_refresh_models_handles_errors(self) -> None:
        """Requirement: 401 -> auth failed, 404 -> models unavailable, timeout -> timeout, network -> unreachable."""
        service = self.direct_store.create_service(
            name="错误测试服务",
            service_base_url="https://api.openai.com/v1",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test", expected_revision=1)

        # 401 Unauthorized
        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 401, "Unauthorized", {}, None)):
            with self.assertRaises(DirectServiceError) as ctx:
                self.direct_store.refresh_models(service["id"], expected_revision=2)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_AUTH_FAILED")

        # 404 Not Found
        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 404, "Not Found", {}, None)):
            with self.assertRaises(DirectServiceError) as ctx:
                self.direct_store.refresh_models(service["id"], expected_revision=2)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_MODELS_UNAVAILABLE")

        # Timeout
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(DirectServiceError) as ctx:
                self.direct_store.refresh_models(service["id"], expected_revision=2)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_TIMEOUT")

        # URLError / unreachable
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaises(DirectServiceError) as ctx:
                self.direct_store.refresh_models(service["id"], expected_revision=2)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_UNREACHABLE")

    def test_refresh_failure_preserves_valid_unexpired_cache(self) -> None:
        """Requirement: 24-hour cache; refresh failure preserves existing cache."""
        service = self.direct_store.create_service(
            name="缓存测试服务",
            service_base_url="https://api.openai.com/v1",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test", expected_revision=1)

        # Initial successful fetch
        mock_models_response = json.dumps({
            "data": [{"id": "model-a"}, {"id": "model-b"}]
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_models_response
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            refreshed = self.direct_store.refresh_models(service["id"], expected_revision=2)
        self.assertEqual(refreshed["modelList"], ["model-a", "model-b"])

        # Subsequent fetch fails with network error
        with patch("urllib.request.urlopen", side_effect=URLError("down")):
            with self.assertRaises(DirectServiceError):
                self.direct_store.refresh_models(service["id"], expected_revision=3)

        # Existing service still retains cached models
        current = self.direct_store.get_service(service["id"])
        self.assertEqual(current["modelList"], ["model-a", "model-b"])
        self.assertFalse(self.direct_store.is_model_list_expired(current))

    def test_excel_analysis_inherits_default_model_and_can_override(self) -> None:
        """Requirement: excel.analysis inherits defaultModel or saves custom model and parameters."""
        service = self.direct_store.create_service(
            name="企业服务",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test", expected_revision=1)

        # Bind excel.analysis without modelName -> inherits default_model
        sel = self.direct_store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="",
            temperature=0.3,
            max_output_tokens=3000,
        )
        self.assertEqual(sel["serviceId"], service["id"])
        self.assertEqual(sel["modelName"], "")
        self.assertEqual(sel["effectiveModel"], "gpt-4o")
        self.assertEqual(sel["temperature"], 0.3)
        self.assertEqual(sel["maxOutputTokens"], 3000)

        # Override modelName
        sel_custom = self.direct_store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="deepseek-chat",
            custom_model=True,
        )
        self.assertEqual(sel_custom["modelName"], "deepseek-chat")
        self.assertEqual(sel_custom["effectiveModel"], "deepseek-chat")
        self.assertTrue(sel_custom["customModel"])

    def test_activate_direct_service_and_resolve_task_auth(self) -> None:
        """Requirement: Activate direct service for excel.analysis; ProviderClient resolves it."""
        service = self.direct_store.create_service(
            name="直连服务A",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test-secret-42", expected_revision=1)

        # Activate direct service for excel.analysis
        self.direct_store.activate_direct_service(service["id"], "excel.analysis")

        client = ProviderClient(
            model_configuration_store=self.model_store,
        )
        client.direct_service_store = self.direct_store

        auth = client.resolve_task_auth("excel.analysis")
        self.assertEqual(auth["accessMethod"], ACCESS_DIRECT_MODEL)
        self.assertEqual(auth["providerBaseUrl"], "https://api.openai.com/v1")
        self.assertEqual(auth["providerChatPath"], "/chat/completions")
        self.assertEqual(auth["modelName"], "gpt-4o")
        self.assertEqual(auth["apiKey"], "sk-test-secret-42")
        self.assertEqual(auth["modelConfigurationName"], "直连服务A")

    def test_model_disappeared_from_catalog_blocks_new_task(self) -> None:
        """Requirement: If model disappears from new catalog, new task is blocked."""
        service = self.direct_store.create_service(
            name="变更目录服务",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.direct_store.replace_api_key(service["id"], "sk-test", expected_revision=1)
        self.direct_store.update_model_list(service["id"], ["gpt-4o", "gpt-4o-mini"], expected_revision=2)

        # Bind excel.analysis with gpt-4o
        self.direct_store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="gpt-4o",
            custom_model=False,
        )
        self.direct_store.activate_direct_service(service["id"], "excel.analysis")

        client = ProviderClient(model_configuration_store=self.model_store)
        client.direct_service_store = self.direct_store

        # Initially valid
        auth = client.resolve_task_auth("excel.analysis")
        self.assertEqual(auth["modelName"], "gpt-4o")

        # Now catalog refreshes and gpt-4o is gone!
        self.direct_store.update_model_list(service["id"], ["gpt-4o-mini"], expected_revision=3)

        # Resolving task auth now blocks with DIRECT_SERVICE_MODEL_DISAPPEARED
        with self.assertRaises(AdapterError) as ctx:
            client.resolve_task_auth("excel.analysis")
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_MODEL_DISAPPEARED")

    def test_end_to_end_excel_analysis_with_shared_direct_service(self) -> None:
        """Requirement: Full excel.analysis call runs against OpenAI-compatible chat completions."""
        service = self.direct_store.create_service(
            name="企业直连网关",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.direct_store.replace_api_key(service["id"], "sk-live-test", expected_revision=1)
        self.direct_store.activate_direct_service(service["id"], "excel.analysis")

        client = ProviderClient(model_configuration_store=self.model_store)
        client.direct_service_store = self.direct_store

        req = ExcelAnalysisRequest(
            table={
                "headers": ["部门", "支出"],
                "rows": [["研发", "10000"], ["市场", "5000"]],
                "rowCount": 2,
                "columnCount": 2,
            }
        )

        mock_chat_completion = json.dumps({
            "id": "chatcmpl-123",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "structuredReport": {
                            "overview": "研发支出占比最高。",
                            "findings": ["研发支出10000"],
                            "risks": ["预算偏紧"],
                            "actions": ["优化支出结构"]
                        },
                        "plainText": "研发支出占比最高。"
                    })
                },
                "finish_reason": "stop"
            }]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_chat_completion
        mock_resp.getheader.return_value = "application/json"
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = client.excel_analysis(req, trace_id="trace_excel_tracer_1")

        self.assertIn("structuredReport", result)
        self.assertIn("研发支出占比最高", result["structuredReport"]["overview"])
        self.assertEqual(result["provider"], "企业直连网关 · 模型直连 · gpt-4o")

        # Verify outgoing request target URL
        called_req = mock_urlopen.call_args[0][0]
        self.assertEqual(called_req.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(called_req.headers["Authorization"], "Bearer sk-live-test")

    @unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for direct services API tests")
    def test_fastapi_endpoints_refresh_activate_and_validate(self) -> None:
        from app.api.provider import (
            refresh_direct_service_models,
            activate_direct_service_route,
            validate_task_model_selection_route,
            DirectServiceRefreshRequest,
            DirectServiceActivateRequest,
            TaskModelSelectionValidateRequest,
        )

        service = self.direct_store.create_service(
            name="API服务",
            service_base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        self.direct_store.replace_api_key(service["id"], "sk-api-test", expected_revision=1)

        with patch("app.api.provider.get_direct_service_store", return_value=self.direct_store), \
             patch("app.api.provider.get_model_configuration_store", return_value=self.model_store):

            # 1. Refresh models
            mock_models_resp = MagicMock()
            mock_models_resp.read.return_value = json.dumps({
                "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
            }).encode("utf-8")
            mock_models_resp.__enter__.return_value = mock_models_resp

            with patch("urllib.request.urlopen", return_value=mock_models_resp):
                refreshed = refresh_direct_service_models(
                    service["id"], DirectServiceRefreshRequest(expected_revision=2)
                )
            self.assertTrue(refreshed["success"])
            self.assertEqual(refreshed["data"]["directService"]["modelList"], ["gpt-4o", "gpt-4o-mini"])

            # 2. Activate for excel.analysis
            act_res = activate_direct_service_route(
                service["id"], DirectServiceActivateRequest(task_type="excel.analysis")
            )
            self.assertTrue(act_res["success"])
            self.assertEqual(act_res["data"]["activeConfigurationId"], service["id"])

            # 3. Validate task model selection
            mock_probe_resp = MagicMock()
            mock_probe_resp.read.return_value = json.dumps({
                "id": "chatcmpl-probe",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({
                            "overview": "概述",
                            "findings": [],
                            "risks": [],
                            "actions": []
                        })
                    },
                    "finish_reason": "stop"
                }]
            }).encode("utf-8")
            mock_probe_resp.__enter__.return_value = mock_probe_resp

            with patch("urllib.request.urlopen", return_value=mock_probe_resp):
                val_res = validate_task_model_selection_route(
                    "excel.analysis",
                    TaskModelSelectionValidateRequest(
                        service_id=service["id"],
                        model_name="gpt-4o",
                    )
                )
            self.assertTrue(val_res["success"])
            self.assertEqual(val_res["data"]["modelName"], "gpt-4o")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone adapter tests")
class StandaloneTracerExcelDirectServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        import standalone_adapter

        self.standalone = standalone_adapter
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "adapter.json"
        self.api_key_dir = Path(self.temp_dir.name) / "keys"
        self.api_key_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text("{}\n", encoding="utf-8")

        self._orig_store = standalone_adapter.DirectServiceStore
        self._orig_model_store = standalone_adapter.ModelConfigurationStore

        def store_factory():
            return DirectServiceStore(
                config_path=self.config_path, api_key_dir=self.api_key_dir
            )

        def model_store_factory():
            return ModelConfigurationStore(
                config_path=self.config_path, key_dir=self.api_key_dir
            )

        standalone_adapter.DirectServiceStore = store_factory
        standalone_adapter.ModelConfigurationStore = model_store_factory

    def tearDown(self) -> None:
        self.standalone.DirectServiceStore = self._orig_store
        self.standalone.ModelConfigurationStore = self._orig_model_store
        self.temp_dir.cleanup()

    def _invoke(self, method: str, path: str, body: dict = None) -> dict:
        from io import BytesIO

        writes = []
        handler = object.__new__(self.standalone.Handler)
        handler.path = path
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        raw = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler.close_connection = False
        handler._reject_operation_block = lambda m, p: False
        handler._reject_writing_policy_route_or_method = lambda m, p: False
        handler.send_error = lambda code, message=None: writes.append(
            (code, {"message": message})
        )

        def mock_write(code, resp_body=None, **kwargs):
            writes.append((code, resp_body))

        handler._write = mock_write
        getattr(handler, method)()
        status, resp_body = writes[-1] if writes else (None, None)
        return {"status": status, "body": resp_body, "writes": writes}

    def test_standalone_refresh_models_activate_and_validate(self) -> None:
        # Create service
        res = self._invoke(
            "do_POST",
            "/provider/direct-services",
            {
                "name": "测试独立直连",
                "serviceBaseUrl": "https://api.openai.com/v1",
                "defaultModel": "gpt-4o",
            },
        )
        self.assertEqual(res["status"], 200)
        service_id = res["body"]["data"]["directService"]["id"]

        # Set API key
        self._invoke(
            "do_POST",
            f"/provider/direct-services/{service_id}/api-key",
            {"apiKey": "sk-standalone-test", "expectedRevision": 1},
        )

        # Refresh models
        mock_models_resp = MagicMock()
        mock_models_resp.read.return_value = json.dumps({
            "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
        }).encode("utf-8")
        mock_models_resp.__enter__.return_value = mock_models_resp

        with patch("urllib.request.urlopen", return_value=mock_models_resp):
            ref_res = self._invoke(
                "do_POST",
                f"/provider/direct-services/{service_id}/refresh-models",
                {"expectedRevision": 2},
            )
        self.assertEqual(ref_res["status"], 200)
        self.assertEqual(ref_res["body"]["data"]["directService"]["modelList"], ["gpt-4o", "gpt-4o-mini"])

        # Activate for excel.analysis
        act_res = self._invoke(
            "do_POST",
            f"/provider/direct-services/{service_id}/activate",
            {"taskType": "excel.analysis"},
        )
        self.assertEqual(act_res["status"], 200)
        self.assertEqual(act_res["body"]["data"]["activeConfigurationId"], service_id)

        # Validate task model selection
        mock_probe_resp = MagicMock()
        mock_probe_resp.read.return_value = json.dumps({
            "id": "chatcmpl-probe-2",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "overview": "概述",
                        "findings": [],
                        "risks": [],
                        "actions": []
                    })
                },
                "finish_reason": "stop"
            }]
        }).encode("utf-8")
        mock_probe_resp.__enter__.return_value = mock_probe_resp

        with patch("urllib.request.urlopen", return_value=mock_probe_resp):
            val_res = self._invoke(
                "do_POST",
                "/provider/task-model-selections/excel.analysis/validate",
                {"serviceId": service_id, "modelName": "gpt-4o"},
            )
        self.assertEqual(val_res["status"], 200)
        self.assertEqual(val_res["body"]["data"]["modelName"], "gpt-4o")


if __name__ == "__main__":
    unittest.main()
