import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.direct_services import DirectServiceStore, DirectServiceError


class ManualModelInputStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_path = root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        key_dir = root / "provider_api_keys"
        self.store = DirectServiceStore(config_path=self.config_path, key_dir=key_dir)

        # Create a test service
        created = self.store.create_service(
            name="Test Service",
            service_base_url="https://api.example.com/v1",
            api_key="sk-test-key-123456",
            default_model="",
        )
        self.service_id = created["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_and_list_custom_models(self) -> None:
        res1 = self.store.add_custom_model(self.service_id, "my-deepseek-v3")
        self.assertIn("my-deepseek-v3", res1.get("customModels", []))

        res2 = self.store.add_custom_model(self.service_id, "  my-custom-qwen  ")
        self.assertEqual(res2.get("customModels"), ["my-deepseek-v3", "my-custom-qwen"])

        # Duplicate should not be re-added
        res3 = self.store.add_custom_model(self.service_id, "my-deepseek-v3")
        self.assertEqual(res3.get("customModels"), ["my-deepseek-v3", "my-custom-qwen"])

        # Empty model name should raise DirectServiceError
        with self.assertRaises(DirectServiceError) as ctx:
            self.store.add_custom_model(self.service_id, "   ")
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_MODEL_REQUIRED")

    def test_delete_custom_model_cascades_smooth_reset(self) -> None:
        self.store.add_custom_model(self.service_id, "custom-m1")
        self.store.add_custom_model(self.service_id, "custom-m2")

        # Set custom-m1 as defaultModel
        self.store.update_service(
            service_id=self.service_id,
            expected_revision=1,
            name="Test Service",
            service_base_url="https://api.example.com/v1",
            default_model="custom-m1",
        )

        # Set custom-m1 as word.smart_write task model
        self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="custom-m1",
            custom_model=True,
        )

        # Set custom-m2 as excel.smart_fill task model
        self.store.update_task_model_selection(
            task_type="excel.smart_fill",
            service_id=self.service_id,
            model_name="custom-m2",
            custom_model=True,
        )

        # Delete custom-m1
        del_res = self.store.delete_custom_model(self.service_id, "custom-m1")
        self.assertEqual(del_res.get("customModels"), ["custom-m2"])

        # Check default_model is smoothly reset to empty string
        svc = self.store.get_service(self.service_id)
        self.assertEqual(svc.get("defaultModel"), "")

        # Check word.smart_write was smoothly reset to inherit default
        selections = self.store.list_task_model_selections().get("selections", {})
        word_sel = selections.get("word.smart_write", {})
        self.assertEqual(word_sel.get("modelName"), "")
        self.assertFalse(word_sel.get("customModel"))
        self.assertFalse(word_sel.get("customModelValidated"))

        # Check excel.smart_fill still keeps custom-m2
        excel_sel = selections.get("excel.smart_fill", {})
        self.assertEqual(excel_sel.get("modelName"), "custom-m2")
        self.assertTrue(excel_sel.get("customModel"))

    def test_deleting_default_custom_model_rejects_stale_service_update(self) -> None:
        self.store.add_custom_model(self.service_id, "custom-default")
        edited = self.store.update_service(
            self.service_id,
            name="Test Service",
            expected_revision=1,
            service_base_url="https://api.example.com/v1",
            default_model="custom-default",
        )

        deleted = self.store.delete_custom_model(self.service_id, "custom-default")

        with self.assertRaises(DirectServiceError) as ctx:
            self.store.update_service(
                self.service_id,
                name="Stale Editor",
                expected_revision=edited["revision"],
                service_base_url="https://api.example.com/v1",
                default_model="custom-default",
            )
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")
        self.assertEqual(deleted["revision"], 3)
        self.assertEqual(self.store.get_service(self.service_id)["defaultModel"], "")
        refreshed = self.store.update_service(
            self.service_id,
            name="Refreshed Editor",
            expected_revision=deleted["revision"],
            service_base_url="https://api.example.com/v1",
            default_model="",
        )
        self.assertEqual(refreshed["revision"], 4)

    def test_custom_model_allowed_when_catalog_is_usable(self) -> None:
        # Mock catalog as usableForSelection
        svc = self.store.get_service(self.service_id)
        payload, _ = self.store._load_with_legacy_direct_migration()
        raw_svc = payload["directServices"][self.service_id]
        raw_svc["modelList"] = ["catalog-model-a", "catalog-model-b"]
        raw_svc["modelListFetchedAt"] = "2026-10-15T12:00:00Z"
        from app.services.direct_services import save_config_payload
        save_config_payload(payload, self.config_path)

        # Now catalog is usableForSelection. Saving custom_model should NOT raise DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED
        record = self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="my-custom-unlisted",
            custom_model=True,
        )
        self.assertEqual(record["modelName"], "my-custom-unlisted")
        self.assertTrue(record["customModel"])

        # It should also automatically add to service's customModels
        updated_svc = self.store.get_service(self.service_id)
        self.assertIn("my-custom-unlisted", updated_svc.get("customModels", []))

    def test_unverified_custom_model_is_available_for_selection(self) -> None:
        record = self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="unverified-custom",
            custom_model=True,
        )
        # Should not raise DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED
        svc = self.store.get_service(self.service_id)
        # _ensure_task_model_ready should pass
        self.store._ensure_task_model_ready(
            task_type="word.smart_write",
            service_id=self.service_id,
            service=svc,
            selection=record,
            effective_model="unverified-custom",
        )

        selections = self.store.list_task_model_selections().get("selections", {})
        word_sel = selections.get("word.smart_write", {})
        self.assertTrue(word_sel.get("modelAvailable"))
        self.assertEqual(word_sel.get("modelAvailability"), "available")
        self.assertFalse(word_sel.get("customModelValidated"))


class ManualModelInputApiAndClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "adapter.json"
        self.config_path.write_text("{}\n", encoding="utf-8")
        self.key_dir = self.root / "provider_api_keys"
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self.store = DirectServiceStore(config_path=self.config_path, key_dir=self.key_dir)

        created = self.store.create_service(
            name="API Test Service",
            service_base_url="https://api.example.com/v1",
            api_key="sk-test-api-key-12345",
            default_model="",
        )
        self.service_id = created["id"]

        import standalone_adapter
        self.standalone = standalone_adapter
        self._orig_store = standalone_adapter.DirectServiceStore
        self._orig_model_store = standalone_adapter.ModelConfigurationStore

        def store_factory():
            return DirectServiceStore(config_path=self.config_path, key_dir=self.key_dir)

        from app.services.model_configurations import ModelConfigurationStore
        def model_store_factory():
            return ModelConfigurationStore(config_path=self.config_path, key_dir=self.key_dir)

        standalone_adapter.DirectServiceStore = store_factory
        standalone_adapter.ModelConfigurationStore = model_store_factory

    def tearDown(self) -> None:
        self.standalone.DirectServiceStore = self._orig_store
        self.standalone.ModelConfigurationStore = self._orig_model_store
        self.temp_dir.cleanup()

    def _invoke_standalone(self, method: str, path: str, body: dict = None):
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
        handler.send_error = lambda code, message=None: writes.append((code, {"message": message}))
        handler._write = lambda code, payload: writes.append((code, payload))
        handler._write_bytes = lambda code, data, content_type: writes.append((code, data))

        if method == "POST":
            handler.do_POST()
        elif method == "DELETE":
            handler.do_DELETE()
        elif method == "GET":
            handler.do_GET()
        return writes[0] if writes else (500, None)

    def test_fastapi_and_standalone_custom_models_endpoints(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.api.provider.get_direct_service_store", return_value=self.store):
            client = TestClient(app)

            # 1. FastAPI POST custom-models
            post_res = client.post(
                f"/provider/direct-services/{self.service_id}/custom-models",
                json={"modelName": "fastapi-custom-1"},
            )
            self.assertEqual(post_res.status_code, 200, post_res.text)
            self.assertIn("fastapi-custom-1", post_res.json()["data"]["directService"]["customModels"])

            # 2. FastAPI DELETE custom-models/{model_name}
            del_res = client.delete(
                f"/provider/direct-services/{self.service_id}/custom-models/fastapi-custom-1"
            )
            self.assertEqual(del_res.status_code, 200, del_res.text)
            self.assertNotIn("fastapi-custom-1", del_res.json()["data"]["directService"]["customModels"])

        # 3. Standalone POST custom-models
        status, body = self._invoke_standalone(
            "POST",
            f"/provider/direct-services/{self.service_id}/custom-models",
            {"modelName": "standalone-custom-1"},
        )
        self.assertEqual(status, 200, body)
        self.assertIn("standalone-custom-1", body["data"]["directService"]["customModels"])

        # 4. Standalone DELETE custom-models/{model_name}
        status, body = self._invoke_standalone(
            "DELETE",
            f"/provider/direct-services/{self.service_id}/custom-models/standalone-custom-1",
        )
        self.assertEqual(status, 200, body)
        self.assertNotIn("standalone-custom-1", body["data"]["directService"]["customModels"])

    def test_both_runtimes_delete_custom_model_with_encoded_slash(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        path = f"/provider/direct-services/{self.service_id}/custom-models/org%2Fmodel"
        for runtime, previous_revision, deleted_revision in (("fastapi", 1, 3), ("standalone", 3, 5)):
            with self.subTest(runtime=runtime):
                self.store.add_custom_model(self.service_id, "org/model")
                self.store.add_custom_model(self.service_id, "keep-model")
                self.store.update_service(
                    self.service_id,
                    name="API Test Service",
                    expected_revision=previous_revision,
                    service_base_url="https://api.example.com/v1",
                    default_model="org/model",
                )
                if runtime == "fastapi":
                    with patch("app.api.provider.get_direct_service_store", return_value=self.store):
                        response = TestClient(app).delete(path)
                    status, body = response.status_code, response.json()
                else:
                    status, body = self._invoke_standalone("DELETE", path)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["data"]["directService"]["customModels"], ["keep-model"])
                self.assertEqual(body["data"]["directService"]["defaultModel"], "")
                self.assertEqual(body["data"]["directService"]["revision"], deleted_revision)
                self.assertEqual(self.store.get_service(self.service_id)["customModels"], ["keep-model"])

    def test_fastapi_custom_model_delete_rejects_stale_revision(self) -> None:
        self._assert_custom_model_delete_rejects_stale_revision("fastapi")

    def test_standalone_custom_model_delete_rejects_stale_revision(self) -> None:
        self._assert_custom_model_delete_rejects_stale_revision("standalone")

    def _assert_custom_model_delete_rejects_stale_revision(self, runtime: str) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        self.store.add_custom_model(self.service_id, "org/model")
        other_host = DirectServiceStore(config_path=self.config_path, key_dir=self.key_dir)
        updated = other_host.update_service(
            self.service_id,
            name="Other Host Service",
            expected_revision=1,
            service_base_url="https://other-host.example.com/v1",
            default_model="org/model",
        )
        path = f"/provider/direct-services/{self.service_id}/custom-models/org%2Fmodel"
        for revision, expected_status in ((1, 409), (2, 200)):
            request_path = f"{path}?expectedRevision={revision}"
            if runtime == "fastapi":
                with patch("app.api.provider.get_direct_service_store", return_value=self.store):
                    response = TestClient(app).delete(request_path)
                status, body = response.status_code, response.json()
            else:
                status, body = self._invoke_standalone("DELETE", request_path)
            self.assertEqual(status, expected_status, body)
            if revision == 1:
                self.assertEqual(other_host.get_service(self.service_id), updated)
            else:
                deleted = body["data"]["directService"]
                self.assertEqual(deleted["revision"], 3)
                self.assertEqual(deleted["customModels"], [])
                self.assertEqual(deleted["defaultModel"], "")
                self.assertEqual(deleted["name"], "Other Host Service")
                self.assertEqual(deleted["serviceBaseUrl"], "https://other-host.example.com/v1")

    def test_provider_client_executes_unverified_custom_model(self) -> None:
        from app.core.config import AppSettings
        from app.services.model_configurations import ModelConfigurationStore
        from app.services.provider_client import ProviderClient

        # Setup unverified custom model selection
        self.store.update_task_model_selection(
            task_type="word.smart_write",
            service_id=self.service_id,
            model_name="my-unverified-llm",
            custom_model=True,
            custom_model_validated=False,
        )
        self.store.activate_direct_service(self.service_id, "word.smart_write")

        provider_client = ProviderClient(
            settings=AppSettings(),
            model_configuration_store=ModelConfigurationStore(
                config_path=self.config_path, key_dir=self.key_dir
            ),
            direct_service_store=self.store,
        )

        # resolve_task_auth should NOT raise DIRECT_SERVICE_CUSTOM_MODEL_UNVERIFIED
        task_auth = provider_client.resolve_task_auth("word.smart_write")
        self.assertEqual(task_auth["modelName"], "my-unverified-llm")
        self.assertEqual(task_auth["modelConfigurationId"], self.service_id)

        # validate_direct_service_task should also NOT raise DIRECT_SERVICE_CUSTOM_MODEL_NOT_ALLOWED even if catalog present
        payload, _ = self.store._load_with_legacy_direct_migration()
        raw_svc = payload["directServices"][self.service_id]
        raw_svc["modelList"] = ["catalog-1", "catalog-2"]
        raw_svc["modelListFetchedAt"] = "2026-10-15T12:00:00Z"
        from app.services.direct_services import save_config_payload
        save_config_payload(payload, self.config_path)

        # Mock urllib request for test execution
        with patch("app.services.provider_client.urllib_request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Type": "application/json"}
            mock_resp.read.return_value = json.dumps({
                "choices": [{"message": {"content": "Generated text"}}],
                "usage": {"completion_tokens": 10, "prompt_tokens": 10, "total_tokens": 20},
            }).encode("utf-8")
            mock_url.return_value = mock_resp
            mock_url.return_value.__enter__.return_value = mock_resp


            result = provider_client.validate_task_model_selection(
                "word.smart_write",
                {
                    "serviceId": self.service_id,
                    "customModel": True,
                    "modelName": "my-unverified-llm",
                },
                trace_id="trace-test-validate",
            )
            self.assertEqual(result["modelName"], "my-unverified-llm")
            self.assertTrue(result["customModelValidated"])
