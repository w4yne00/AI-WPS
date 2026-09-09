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
    from app.core.errors import AdapterError
    from app.api.provider import (
        DirectServiceApiKeyRequest,
        DirectServiceCreateRequest,
        DirectServiceUpdateRequest,
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


@unittest.skipUnless(
    HAS_API_DEPS, "fastapi and pydantic are required for direct services API tests"
)
class DirectServicesApiTests(unittest.TestCase):
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

                # 6. Replace API key
                keyed = replace_direct_service_api_key(
                    service_id,
                    DirectServiceApiKeyRequest(apiKey="sk-api-test-secret"),
                )
                self.assertTrue(keyed["success"])
                self.assertTrue(keyed["data"]["directService"]["keyConfigured"])
                self.assertEqual(keyed["data"]["directService"]["revision"], 3)

                # 7. Clear API key
                cleared = clear_direct_service_api_key(service_id)
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

                # 10. Delete in-use service raises 409
                with self.assertRaises(AdapterError) as ctx:
                    delete_direct_service(service_id)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")

                # 11. Unbind and delete
                update_task_model_selection_route(
                    "word.smart_write",
                    TaskModelSelectionUpdateRequest(serviceId=""),
                )
                deleted = delete_direct_service(service_id)
                self.assertTrue(deleted["success"])
                self.assertEqual(deleted["data"]["directServiceCount"], 0)


if __name__ == "__main__":
    unittest.main()
