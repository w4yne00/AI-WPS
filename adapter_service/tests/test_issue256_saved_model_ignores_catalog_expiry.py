import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import ExcelAnalysisRequest
from app.services.direct_services import DirectServiceStore
from app.services.model_configurations import ModelConfigurationStore
from app.services.provider_client import ProviderClient


def _chat_response(text: str) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(
        {
            "id": "chatcmpl-256",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "structuredReport": {
                                    "overview": text,
                                    "findings": [],
                                    "risks": [],
                                    "actions": [],
                                },
                                "plainText": text,
                            }
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode("utf-8")
    response.getheader.return_value = "application/json"
    response.__enter__.return_value = response
    return response


class SavedModelIgnoresCatalogExpiryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        key_dir = root / "provider_api_keys"
        self.store = DirectServiceStore(config_path=self.config_path, key_dir=key_dir)
        self.model_store = ModelConfigurationStore(
            config_path=self.config_path, key_dir=key_dir
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _saved_override(self) -> dict:
        service = self.store.create_service(
            name="已保存模型",
            service_base_url="https://api.example.com/v1",
            default_model="gpt-4o",
            api_key="sk-saved",
        )
        expired_at = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat().replace("+00:00", "Z")
        self.store.update_model_list(
            service["id"],
            ["gpt-4o"],
            expected_revision=service["revision"],
            fetched_at=expired_at,
        )
        self.store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="glm-kept",
            temperature=0,
        )
        return service

    def test_expired_catalog_still_calls_saved_function_model(self) -> None:
        service = self._saved_override()
        self.store.activate_direct_service(service["id"], "excel.analysis")

        client = ProviderClient(
            model_configuration_store=self.model_store,
            direct_service_store=self.store,
        )
        request = ExcelAnalysisRequest(
            table={
                "headers": ["部门"],
                "rows": [["研发"]],
                "rowCount": 1,
                "columnCount": 1,
            }
        )
        with patch(
            "urllib.request.urlopen", return_value=_chat_response("已调用")
        ) as urlopen:
            result = client.excel_analysis(request, trace_id="trace-issue-256")

        self.assertEqual(result["structuredReport"]["overview"], "已调用")
        called = urlopen.call_args[0][0]
        payload = json.loads(called.data.decode("utf-8"))
        self.assertEqual(payload["model"], "glm-kept")
        self.assertEqual(
            self.store.get_service(service["id"])["defaultModel"], "gpt-4o"
        )
        self.assertEqual(
            self.store.get_task_model_selection("excel.analysis")["modelName"],
            "glm-kept",
        )

    def test_expired_catalog_validation_calls_saved_model(self) -> None:
        service = self._saved_override()
        self.store.activate_direct_service(service["id"], "excel.analysis")
        client = ProviderClient(
            model_configuration_store=self.model_store,
            direct_service_store=self.store,
        )
        with patch(
            "urllib.request.urlopen", return_value=_chat_response("已验证")
        ) as urlopen:
            client.validate_task_model_selection(
                "excel.analysis",
                {"serviceId": service["id"], "modelName": "glm-kept"},
                "trace-issue-256-validate",
            )

        self.assertGreaterEqual(urlopen.call_count, 1)
        payload = json.loads(urlopen.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "glm-kept")

    def test_fastapi_and_standalone_validate_expired_catalog_with_saved_model(self) -> None:
        from io import BytesIO
        import standalone_adapter
        from app.api.provider import (
            TaskModelSelectionValidateRequest,
            validate_task_model_selection_route,
        )

        service = self._saved_override()
        self.store.activate_direct_service(service["id"], "excel.analysis")
        chat = _chat_response("已验证")

        with patch("app.api.provider.get_direct_service_store", return_value=self.store), patch(
            "app.api.provider.get_model_configuration_store", return_value=self.model_store
        ), patch("urllib.request.urlopen", return_value=chat) as urlopen:
            validated = validate_task_model_selection_route(
                "excel.analysis",
                TaskModelSelectionValidateRequest(
                    serviceId=service["id"], modelName="glm-kept"
                ),
            )
        self.assertEqual(validated["data"]["taskCallPerformed"], True)
        self.assertEqual(
            json.loads(urlopen.call_args[0][0].data.decode("utf-8"))["model"],
            "glm-kept",
        )

        raw = json.dumps({"serviceId": service["id"], "modelName": "glm-kept"}).encode("utf-8")
        writes = []
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = "/provider/task-model-selections/excel.analysis/validate"
        handler.command = "POST"
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler.close_connection = False
        handler._reject_operation_block = lambda method, path: False
        handler._reject_writing_policy_route_or_method = lambda method, path: False
        handler._write = lambda status, payload: writes.append((status, payload))
        handler.send_error = lambda code, message=None: writes.append((code, message))

        with patch.object(standalone_adapter, "DirectServiceStore", return_value=self.store), patch.object(
            standalone_adapter, "ModelConfigurationStore", return_value=self.model_store
        ), patch("urllib.request.urlopen", return_value=chat) as standalone_open:
            handler.do_POST()

        self.assertEqual(writes[-1][0], 200)
        self.assertEqual(
            json.loads(standalone_open.call_args[0][0].data.decode("utf-8"))["model"],
            "glm-kept",
        )
