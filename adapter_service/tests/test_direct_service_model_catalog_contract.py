import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from app.core.errors import AdapterError
from app.services.direct_services import DirectServiceError, DirectServiceStore
from app.services.provider_client import ProviderClient


class DirectServiceModelCatalogContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.store = DirectServiceStore(
            config_path=self.config_path,
            key_dir=root / "provider_api_keys",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _response(payload: dict) -> MagicMock:
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        return response

    def _service(self, name: str = "目录合同服务") -> dict:
        return self.store.create_service(
            name=name,
            service_base_url="https://api.example.com/v1",
            default_model="gpt-4o",
            api_key="sk-catalog-test",
        )

    def test_successful_catalog_exposes_cache_state_and_expiration(self) -> None:
        service = self._service()
        response = self._response({"data": [{"id": "gpt-4o"}]})

        with patch("urllib.request.urlopen", return_value=response):
            refreshed = self.store.refresh_models(service["id"], expected_revision=1)

        catalog = refreshed["modelCatalog"]
        self.assertEqual(catalog["status"], "available")
        self.assertEqual(catalog["cacheStatus"], "valid")
        self.assertEqual(catalog["fetchStatus"], "success")
        self.assertEqual(catalog["models"], ["gpt-4o"])
        self.assertTrue(catalog["fetchedAt"])
        self.assertTrue(catalog["expiresAt"])
        self.assertIsNone(catalog["lastError"])

        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(days=1, seconds=1)
        ).isoformat().replace("+00:00", "Z")
        expired = self.store.update_model_list(
            service["id"],
            ["gpt-4o"],
            expected_revision=2,
            fetched_at=old_timestamp,
        )
        self.assertEqual(expired["modelCatalog"]["status"], "expired")
        self.assertEqual(expired["modelCatalog"]["cacheStatus"], "expired")
        self.assertTrue(expired["modelCatalog"]["manualModelAllowed"])

    def test_refresh_failure_preserves_valid_cache_and_records_error(self) -> None:
        service = self._service()
        response = self._response({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})

        with patch("urllib.request.urlopen", return_value=response):
            self.store.refresh_models(service["id"], expected_revision=1)

        with patch(
            "urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with self.assertRaises(DirectServiceError) as context:
                self.store.refresh_models(service["id"], expected_revision=2)

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_UNREACHABLE")
        current = self.store.get_service(service["id"])
        self.assertEqual(current["modelList"], ["gpt-4o", "gpt-4o-mini"])
        self.assertEqual(current["modelCatalog"]["cacheStatus"], "valid")
        self.assertEqual(current["modelCatalog"]["fetchStatus"], "error")
        self.assertEqual(
            current["modelCatalog"]["lastError"]["code"],
            "DIRECT_SERVICE_UNREACHABLE",
        )

        rotated = self.store.replace_api_key(
            service["id"], "sk-catalog-rotated", expected_revision=2
        )
        self.assertEqual(rotated["modelList"], ["gpt-4o", "gpt-4o-mini"])
        self.assertEqual(rotated["modelCatalog"]["cacheStatus"], "invalidated")
        self.assertFalse(rotated["modelCatalog"]["usableForSelection"])

        self.store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="gpt-4o",
        )
        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("invalidated catalog must block before task call"),
        ):
            with self.assertRaises(AdapterError) as context:
                client.validate_task_model_selection(
                    "excel.analysis",
                    {
                        "serviceId": service["id"],
                        "modelName": "gpt-4o",
                        "customModel": False,
                    },
                    "trace-invalidated-catalog",
                )
        self.assertEqual(
            context.exception.code, "DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE"
        )

    def test_malformed_catalog_response_is_rejected(self) -> None:
        service = self._service()
        response = self._response({"data": {"id": "not-a-list"}})

        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(DirectServiceError) as context:
                self.store.refresh_models(service["id"], expected_revision=1)

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_MODELS_PARSE_FAILED")
        current = self.store.get_service(service["id"])
        self.assertEqual(current["modelCatalog"]["cacheStatus"], "empty")
        self.assertEqual(
            current["modelCatalog"]["lastError"]["code"],
            "DIRECT_SERVICE_MODELS_PARSE_FAILED",
        )

    def test_client_submitted_model_list_is_not_trusted_as_catalog(self) -> None:
        from app.api.provider import (
            DirectServiceModelListUpdateRequest,
            update_direct_service_models,
        )

        service = self._service("客户端目录输入服务")
        with patch(
            "app.api.provider.get_direct_service_store",
            return_value=self.store,
        ):
            result = update_direct_service_models(
                service["id"],
                DirectServiceModelListUpdateRequest(
                    modelList=["attacker-supplied-model"],
                    expectedRevision=1,
                ),
            )

        submitted = result["data"]["directService"]
        self.assertEqual(submitted["modelList"], ["attacker-supplied-model"])
        self.assertFalse(submitted["modelListTrusted"])
        self.assertEqual(submitted["modelListSource"], "client")
        self.assertEqual(submitted["modelCatalog"]["cacheStatus"], "untrusted")
        self.assertFalse(submitted["modelCatalog"]["usableForSelection"])

        self.store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="attacker-supplied-model",
        )
        with self.assertRaises(DirectServiceError) as context:
            self.store.activate_direct_service(service["id"], "excel.analysis")
        self.assertEqual(
            context.exception.code,
            "DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE",
        )

    def test_catalog_not_attempted_blocks_default_model_activation(self) -> None:
        service = self._service("未获取目录服务")

        with self.assertRaises(DirectServiceError) as context:
            self.store.activate_direct_service(service["id"], "excel.analysis")

        self.assertEqual(
            context.exception.code,
            "DIRECT_SERVICE_MODEL_CATALOG_UNAVAILABLE",
        )

    def test_refresh_without_revision_cannot_write_after_configuration_change(self) -> None:
        service = self._service("刷新竞态服务")
        response = self._response({"data": [{"id": "stale-model"}]})

        def delayed_urlopen(*_args, **_kwargs):
            self.store.update_service(
                service["id"],
                name="刷新竞态服务",
                service_base_url="https://changed.example.com/v1",
                default_model="gpt-4o",
                expected_revision=1,
            )
            return response

        with patch("urllib.request.urlopen", side_effect=delayed_urlopen):
            with self.assertRaises(DirectServiceError) as context:
                self.store.refresh_models(service["id"])

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")
        current = self.store.get_service(service["id"])
        self.assertEqual(current["serviceBaseUrl"], "https://changed.example.com/v1")
        self.assertEqual(current["modelList"], [])
        self.assertFalse(current["modelCatalog"]["usableForSelection"])

    def test_custom_validation_marker_rejects_rotated_key_snapshot(self) -> None:
        service = self._service("验证竞态服务")
        snapshot = self.store.get_service(service["id"], include_secret=True)
        self.store.replace_api_key(
            service["id"], "sk-rotated", expected_revision=1
        )

        with self.assertRaises(DirectServiceError) as context:
            self.store.mark_custom_model_validated(
                "excel.analysis",
                service["id"],
                "manual-model",
                expected_service_base_url=snapshot["serviceBaseUrl"],
                expected_api_key_fingerprint=DirectServiceStore.api_key_fingerprint(
                    snapshot["apiKey"]
                ),
            )

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_CONFIG_CHANGED")

    def test_task_validation_does_not_record_after_key_rotation_during_call(self) -> None:
        service = self._service("任务验证竞态服务")
        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )
        response_body = {
            "answer": json.dumps(
                {
                    "overview": "概述",
                    "findings": [],
                    "risks": [],
                    "actions": [],
                },
                ensure_ascii=False,
            )
        }

        def rotate_key_then_return(*_args, **_kwargs):
            self.store.replace_api_key(
                service["id"], "sk-rotated-during-validation", expected_revision=1
            )
            return response_body

        with patch.object(client, "post_task", side_effect=rotate_key_then_return):
            with self.assertRaises(DirectServiceError) as context:
                client.validate_task_model_selection(
                    "excel.analysis",
                    {
                        "serviceId": service["id"],
                        "modelName": "manual-model",
                        "customModel": True,
                    },
                    "trace-key-rotation-during-validation",
                )

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_CONFIG_CHANGED")
        self.assertFalse(
            self.store.is_custom_model_validated(
                "excel.analysis", service["id"], "manual-model"
            )
        )

    def test_catalog_model_count_limit_is_enforced(self) -> None:
        service = self._service("目录数量限制服务")
        response = self._response(
            {
                "data": [
                    {"id": "model-{0}".format(index)}
                    for index in range(1001)
                ]
            }
        )

        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(DirectServiceError) as context:
                self.store.refresh_models(service["id"], expected_revision=1)

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_MODELS_LIMIT")

    def test_auth_failure_and_timeout_are_recorded_without_catalog_data(self) -> None:
        auth_service = self._service("认证失败服务")
        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 401, "Unauthorized", {}, None),
        ):
            with self.assertRaises(DirectServiceError) as auth_context:
                self.store.refresh_models(auth_service["id"], expected_revision=1)
        self.assertEqual(auth_context.exception.code, "DIRECT_SERVICE_AUTH_FAILED")
        auth_current = self.store.get_service(auth_service["id"])
        self.assertEqual(
            auth_current["modelCatalog"]["lastError"]["code"],
            "DIRECT_SERVICE_AUTH_FAILED",
        )

        timeout_service = self._service("超时服务")
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(DirectServiceError) as timeout_context:
                self.store.refresh_models(timeout_service["id"], expected_revision=1)
        self.assertEqual(timeout_context.exception.code, "DIRECT_SERVICE_TIMEOUT")
        timeout_current = self.store.get_service(timeout_service["id"])
        self.assertEqual(
            timeout_current["modelCatalog"]["lastError"]["code"],
            "DIRECT_SERVICE_TIMEOUT",
        )

    def test_service_validation_is_separate_and_no_catalog_leaves_auth_unverified(self) -> None:
        service = self._service()

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(None, 404, "Not Found", {}, None),
        ) as urlopen:
            result = self.store.validate_service(service["id"], expected_revision=1)

        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(result["success"])
        self.assertEqual(result["validationScope"], "service")
        self.assertTrue(result["reachable"])
        self.assertIsNone(result["authenticated"])
        self.assertFalse(result["authenticationVerified"])
        self.assertFalse(result["taskCallPerformed"])
        self.assertFalse(result["mayIncurModelCost"])
        self.assertFalse(result["modelCatalogAvailable"])
        self.assertTrue(result["manualModelAllowed"])

        malformed_service = self._service("目录格式错误服务")
        malformed_response = self._response({"data": {"unexpected": True}})
        with patch("urllib.request.urlopen", return_value=malformed_response):
            malformed_result = self.store.validate_service(
                malformed_service["id"], expected_revision=1
            )
        self.assertTrue(malformed_result["success"])
        self.assertTrue(malformed_result["reachable"])
        self.assertTrue(malformed_result["authenticated"])
        self.assertFalse(malformed_result["taskCallPerformed"])
        self.assertEqual(
            malformed_result["modelCatalogFetchError"]["code"],
            "DIRECT_SERVICE_MODELS_PARSE_FAILED",
        )
        self.assertTrue(malformed_result["manualModelAllowed"])

    def test_save_and_replace_key_trigger_catalog_refresh(self) -> None:
        from app.api.provider import (
            DirectServiceApiKeyRequest,
            DirectServiceCreateRequest,
            DirectServiceUpdateRequest,
            create_direct_service,
            replace_direct_service_api_key,
            update_direct_service,
        )

        with patch(
            "app.api.provider.get_direct_service_store",
            return_value=self.store,
        ), patch(
            "urllib.request.urlopen",
            return_value=self._response({"data": [{"id": "gpt-4o"}]}),
        ) as urlopen:
            created = create_direct_service(
                DirectServiceCreateRequest(
                    name="API自动刷新服务",
                    serviceBaseUrl="https://api.example.com/v1",
                    defaultModel="gpt-4o",
                    apiKey="sk-first",
                )
            )
            service = created["data"]["directService"]
            self.assertEqual(service["modelList"], ["gpt-4o"])

            updated = update_direct_service(
                service["id"],
                DirectServiceUpdateRequest(
                    name="API自动刷新服务",
                    serviceBaseUrl="https://api-new.example.com/v1",
                    defaultModel="gpt-4o",
                    expectedRevision=2,
                ),
            )
            self.assertEqual(updated["data"]["directService"]["modelList"], ["gpt-4o"])

            replaced = replace_direct_service_api_key(
                service["id"],
                DirectServiceApiKeyRequest(
                    apiKey="sk-second",
                    expectedRevision=4,
                ),
            )
            self.assertEqual(replaced["data"]["directService"]["modelList"], ["gpt-4o"])

        self.assertEqual(urlopen.call_count, 3)

    def test_disappeared_model_is_marked_unavailable_in_selection(self) -> None:
        service = self._service()
        first = self.store.update_model_list(
            service["id"], ["gpt-4o"], expected_revision=1
        )
        self.store.update_task_model_selection(
            "excel.analysis",
            service_id=service["id"],
            model_name="gpt-4o",
        )
        missing = self.store.update_model_list(
            service["id"], ["gpt-4o-mini"], expected_revision=first["revision"]
        )

        selection = self.store.get_task_model_selection("excel.analysis")
        self.assertEqual(selection["modelAvailability"], "unavailable")
        self.assertFalse(selection["modelAvailable"])
        self.assertEqual(selection["modelUnavailableReason"], "disappeared")
        self.assertEqual(missing["modelCatalog"]["status"], "available")

    def test_manual_model_requires_unavailable_catalog_and_successful_task_validation(self) -> None:
        listed = self._service("目录可用服务")
        self.store.update_model_list(listed["id"], ["gpt-4o"], expected_revision=1)
        with self.assertRaises(DirectServiceError) as context:
            self.store.update_task_model_selection(
                "excel.analysis",
                service_id=listed["id"],
                model_name="manual-model",
                custom_model=True,
            )
        self.assertEqual(
            context.exception.code,
            "DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED",
        )

        manual = self._service("无目录手填服务")
        draft = self.store.update_task_model_selection(
            "excel.analysis",
            service_id=manual["id"],
            model_name="manual-model",
            custom_model=True,
            custom_model_validated=True,
        )
        self.assertFalse(draft["customModelValidated"])
        with self.assertRaises(DirectServiceError) as context:
            self.store.activate_direct_service(manual["id"], "excel.analysis")
        self.assertEqual(
            context.exception.code,
            "DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED",
        )

        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )
        probe_response = self._response(
            {
                "id": "chatcmpl-validation",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "overview": "概述",
                                    "findings": [],
                                    "risks": [],
                                    "actions": [],
                                },
                                ensure_ascii=False,
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )
        with patch("urllib.request.urlopen", return_value=probe_response):
            validation = client.validate_task_model_selection(
                "excel.analysis",
                {
                    "serviceId": manual["id"],
                    "modelName": "manual-model",
                    "customModel": True,
                },
                "trace-manual-validation",
            )

        self.assertEqual(validation["validationScope"], "task")
        self.assertTrue(validation["taskContractValidated"])
        self.assertTrue(validation["mayIncurModelCost"])
        saved = self.store.update_task_model_selection(
            "excel.analysis",
            service_id=manual["id"],
            model_name="manual-model",
            custom_model=True,
            custom_model_validated=True,
        )
        self.assertTrue(saved["customModelValidated"])
        activated = self.store.activate_direct_service(manual["id"], "excel.analysis")
        self.assertEqual(activated["activeConfigurationId"], manual["id"])

        empty_catalog = self.store.update_model_list(
            manual["id"], [], expected_revision=1
        )
        preserved_validation = self.store.get_task_model_selection("excel.analysis")
        self.assertTrue(preserved_validation["customModelValidated"])

        catalog_after_validation = self.store.update_model_list(
            manual["id"], ["manual-model"], expected_revision=empty_catalog["revision"]
        )
        self.assertEqual(catalog_after_validation["modelCatalog"]["status"], "available")
        unavailable_manual = self.store.get_task_model_selection("excel.analysis")
        self.assertFalse(unavailable_manual["modelAvailable"])
        self.assertEqual(unavailable_manual["modelUnavailableReason"], "catalog_usable")

    def test_task_contract_failure_does_not_mark_manual_model_validated(self) -> None:
        service = self._service("任务合同失败服务")
        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )
        invalid_response = self._response(
            {
                "id": "chatcmpl-invalid-validation",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "不是 JSON 合同"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
        with patch("urllib.request.urlopen", return_value=invalid_response):
            with self.assertRaises(AdapterError):
                client.validate_task_model_selection(
                    "excel.smart_fill",
                    {
                        "serviceId": service["id"],
                        "modelName": "manual-model",
                        "customModel": True,
                    },
                    "trace-invalid-validation",
                )

        self.store.update_task_model_selection(
            "excel.smart_fill",
            service_id=service["id"],
            model_name="manual-model",
            custom_model=True,
        )
        self.assertFalse(
            self.store.get_task_model_selection("excel.smart_fill")["customModelValidated"]
        )

    def test_formula_probe_fallback_does_not_mark_manual_model_validated(self) -> None:
        service = self._service("公式任务合同失败服务")
        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )
        refusal_response = self._response(
            {
                "id": "chatcmpl-formula-refusal",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I cannot return a formula or comply with this task.",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )

        with patch("urllib.request.urlopen", return_value=refusal_response):
            with self.assertRaises(AdapterError) as context:
                client.validate_task_model_selection(
                    "excel.formula_assistant",
                    {
                        "serviceId": service["id"],
                        "modelName": "manual-model",
                        "customModel": True,
                    },
                    "trace-formula-refusal",
                )

        self.assertEqual(context.exception.code, "MODEL_RESULT_INVALID")
        self.assertFalse(
            self.store.is_custom_model_validated(
                "excel.formula_assistant", service["id"], "manual-model"
            )
        )

    def test_custom_task_validation_requires_explicit_model_name(self) -> None:
        service = self._service("手填模型名称校验服务")
        client = ProviderClient(
            model_configuration_store=None,
            direct_service_store=self.store,
        )

        with self.assertRaises(AdapterError) as context:
            client.validate_task_model_selection(
                "excel.analysis",
                {
                    "serviceId": service["id"],
                    "modelName": "",
                    "customModel": True,
                },
                "trace-custom-model-name-required",
            )

        self.assertEqual(context.exception.code, "DIRECT_SERVICE_MODEL_REQUIRED")


if __name__ == "__main__":
    unittest.main()
