import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.services.direct_services import (
    DirectServiceError,
    DirectServiceStore,
)

HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic") is not None
)

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from pydantic import ValidationError

    from app.main import app
    from app.core.errors import AdapterError
    from app.core.config import AppSettings
    from app.api.provider import (
        DirectServiceApiKeyRequest,
        DirectServiceCreateRequest,
        DirectServiceModelListUpdateRequest,
        DirectServiceRefreshRequest,
        DirectServiceUpdateRequest,
        DirectServiceValidateRequest,
        TaskModelSelectionUpdateRequest,
        clear_direct_service_api_key,
        create_direct_service,
        delete_direct_service,
        get_direct_service,
        get_direct_services,
        get_task_model_selection,
        get_task_model_selections,
        replace_direct_service_api_key,
        update_direct_service,
        update_task_model_selection_route,
    )
    from app.services.model_configurations import ModelConfigurationStore
    from app.services.provider_client import ProviderClient
    from app.services.word.rewriter import WordRewriter
    from app.services.word.smart_imitator import WordSmartImitator


@unittest.skipUnless(
    HAS_API_DEPS, "fastapi and pydantic are required for direct services API tests"
)
class DirectServicesApiTests(unittest.TestCase):
    def test_word_writing_tasks_resolve_atomic_selections_from_public_api(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            key_dir = root / "provider_api_keys"
            store = DirectServiceStore(config_path, key_dir)

            with patch(
                "app.api.provider.get_direct_service_store", return_value=store
            ):
                client = TestClient(app)
                created = client.post(
                    "/provider/direct-services",
                    json={
                        "name": "Word 共享直连",
                        "serviceBaseUrl": "https://api.example.com/v1",
                        "defaultModel": "shared-default",
                    },
                )
                self.assertEqual(created.status_code, 200)
                service_id = created.json()["data"]["directService"]["id"]
                store.replace_api_key(service_id, "sk-word-shared", expected_revision=1)
                store.update_model_list(
                    service_id,
                    ["shared-default", "write-model", "imitation-model"],
                    expected_revision=2,
                    trusted=True,
                )

                task_payloads = {
                    "word.smart_write": {
                        "serviceId": service_id,
                        "modelName": "write-model",
                        "temperature": 0.3,
                        "maxOutputTokens": 2048,
                        "contextWindowTokens": 32000,
                        "customModel": False,
                    },
                    "word.smart_imitation": {
                        "serviceId": service_id,
                        "modelName": "imitation-model",
                        "temperature": 0.6,
                        "maxOutputTokens": 4096,
                        "contextWindowTokens": 64000,
                        "customModel": False,
                    },
                }
                for task_type, selection in task_payloads.items():
                    response = client.post(
                        "/provider/direct-services/{0}/activate".format(service_id),
                        json={
                            "taskType": task_type,
                            "taskModelSelection": selection,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.json()["data"]["taskModelSelection"]["modelName"],
                        selection["modelName"],
                    )

            provider_client = ProviderClient(
                settings=AppSettings(),
                model_configuration_store=ModelConfigurationStore(
                    config_path=config_path, key_dir=key_dir
                ),
                direct_service_store=store,
            )
            write_auth = WordRewriter(
                provider_client=provider_client
            ).snapshot_task_auth()
            imitation_auth = WordSmartImitator(
                provider_client=provider_client
            ).snapshot_task_auth()

            self.assertEqual(write_auth["modelConfigurationId"], service_id)
            self.assertEqual(write_auth["modelName"], "write-model")
            self.assertEqual(write_auth["temperature"], 0.3)
            self.assertEqual(imitation_auth["modelConfigurationId"], service_id)
            self.assertEqual(imitation_auth["modelName"], "imitation-model")
            self.assertEqual(imitation_auth["temperature"], 0.6)

    def test_model_mutation_requests_require_expected_revision(self) -> None:
        for request_type, payload in (
            (DirectServiceModelListUpdateRequest, {"modelList": ["gpt-4o"]}),
            (DirectServiceRefreshRequest, {}),
            (DirectServiceValidateRequest, {}),
        ):
            with self.assertRaises(ValidationError):
                request_type(**payload)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = DirectServiceStore(config_path, root / "provider_api_keys")
            service = store.create_service(
                name="API 版本必填测试",
                service_base_url="https://api.example.com/v1",
            )
            with patch(
                "app.api.provider.get_direct_service_store", return_value=store
            ):
                client = TestClient(app)
                for action, payload in (
                    ("models", {"modelList": ["gpt-4o"]}),
                    ("refresh-models", {}),
                    ("validate", {}),
                ):
                    response = client.post(
                        "/provider/direct-services/{0}/{1}".format(
                            service["id"], action
                        ),
                        json=payload,
                    )
                    self.assertEqual(response.status_code, 422)
            self.assertEqual(store.get_service(service["id"])["revision"], 1)

    def test_direct_services_and_task_model_selection_api_routes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = DirectServiceStore(config_path, root / "provider_api_keys")

            with patch(
                "app.api.provider.get_direct_service_store", return_value=store
            ):
                # 1. Initial list
                init_list = get_direct_services()
                self.assertTrue(init_list["success"])
                self.assertEqual(init_list["data"]["directServiceCount"], 0)

                # 2. Create service
                created = create_direct_service(
                    DirectServiceCreateRequest(
                        name="API测试直连服务",
                        serviceBaseUrl="https://api.openai.com/v1/chat/completions",
                        defaultModel="gpt-4o",
                    )
                )
                self.assertTrue(created["success"])
                service_id = created["data"]["directService"]["id"]
                self.assertEqual(
                    created["data"]["directService"]["serviceBaseUrl"],
                    "https://api.openai.com/v1",
                )
                self.assertEqual(created["data"]["directService"]["revision"], 1)
                self.assertEqual(
                    created["data"]["directService"]["schemaVersion"],
                    "provider.direct_service.v1",
                )

                # Invalid URL raises 400
                with self.assertRaises(AdapterError) as ctx:
                    create_direct_service(
                        DirectServiceCreateRequest(
                            name="非法URL服务",
                            serviceBaseUrl="ftp://invalid.example.com",
                            defaultModel="gpt-4o",
                        )
                    )
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_URL_INVALID")

                # 3. Get single service
                got = get_direct_service(service_id)
                self.assertTrue(got["success"])
                self.assertEqual(got["data"]["directService"]["id"], service_id)

                # 4. Update service (revision check)
                updated = update_direct_service(
                    service_id,
                    DirectServiceUpdateRequest(
                        name="API测试直连服务-改名",
                        serviceBaseUrl="https://api-v2.openai.com/v1",
                        defaultModel="gpt-4o-mini",
                        expectedRevision=1,
                    ),
                )
                self.assertTrue(updated["success"])
                self.assertEqual(updated["data"]["directService"]["revision"], 2)
                self.assertEqual(
                    updated["data"]["directService"]["name"], "API测试直连服务-改名"
                )

                # 5. Outdated revision returns 409
                with self.assertRaises(AdapterError) as ctx:
                    update_direct_service(
                        service_id,
                        DirectServiceUpdateRequest(
                            name="再次改名",
                            expectedRevision=1,
                        ),
                    )
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

                # 6. Replace API key with conflict check
                with self.assertRaises(AdapterError) as ctx:
                    replace_direct_service_api_key(
                        service_id,
                        DirectServiceApiKeyRequest(
                            apiKey="sk-api-test-secret",
                            expectedRevision=999,
                        ),
                    )
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

                keyed = replace_direct_service_api_key(
                    service_id,
                    DirectServiceApiKeyRequest(
                        apiKey="sk-api-test-secret",
                        expectedRevision=2,
                    ),
                )
                self.assertTrue(keyed["success"])
                self.assertTrue(keyed["data"]["directService"]["keyConfigured"])
                self.assertEqual(keyed["data"]["directService"]["revision"], 3)

                # 7. Clear API key with conflict check
                with self.assertRaises(AdapterError) as ctx:
                    clear_direct_service_api_key(service_id, expected_revision=999)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

                cleared = clear_direct_service_api_key(service_id, expected_revision=3)
                self.assertTrue(cleared["success"])
                self.assertFalse(cleared["data"]["directService"]["keyConfigured"])
                self.assertEqual(cleared["data"]["directService"]["revision"], 4)

                # 8. Task model selection list
                selections = get_task_model_selections()
                self.assertTrue(selections["success"])
                self.assertEqual(
                    len(selections["data"]["taskModelSelections"]), 9
                )

                # 9. Update task model selection
                sel_updated = update_task_model_selection_route(
                    "word.smart_write",
                    TaskModelSelectionUpdateRequest(
                        serviceId=service_id,
                        modelName="",
                        temperature=0.7,
                    ),
                )
                self.assertTrue(sel_updated["success"])
                self.assertEqual(
                    sel_updated["data"]["taskModelSelection"]["serviceId"],
                    service_id,
                )
                self.assertEqual(
                    sel_updated["data"]["taskModelSelection"]["effectiveModel"],
                    "gpt-4o-mini",
                )
                self.assertEqual(
                    sel_updated["data"]["taskModelSelection"]["schemaVersion"],
                    "provider.task_model_selection.v1",
                )

                # 10. Delete in-use service raises 409
                with self.assertRaises(AdapterError) as ctx:
                    delete_direct_service(service_id, expected_revision=4)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")

                # 11. Unbind and delete (with revision conflict check)
                update_task_model_selection_route(
                    "word.smart_write",
                    TaskModelSelectionUpdateRequest(serviceId=""),
                )
                with self.assertRaises(AdapterError) as ctx:
                    delete_direct_service(service_id, expected_revision=999)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

                deleted = delete_direct_service(service_id, expected_revision=4)
                self.assertTrue(deleted["success"])
                self.assertEqual(deleted["data"]["directServiceCount"], 0)


if __name__ == "__main__":
    unittest.main()
