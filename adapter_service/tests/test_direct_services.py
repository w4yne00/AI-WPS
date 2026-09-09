import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

from app.services.direct_services import (
    MAX_DIRECT_SERVICES,
    DirectServiceError,
    DirectServiceStore,
)


class DirectServiceStoreTests(unittest.TestCase):
    def _store(self, root: Path) -> DirectServiceStore:
        config_path = root / "adapter.json"
        if not config_path.exists():
            config_path.write_text("{}\n", encoding="utf-8")
        return DirectServiceStore(config_path, root / "provider_api_keys")

    def test_create_and_list_direct_service(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="企业直连网关",
                service_base_url="https://api.openai.com/v1/chat/completions",
                default_model="gpt-4o",
            )
            self.assertTrue(service["id"].startswith("direct_svc_"))
            self.assertEqual(service["name"], "企业直连网关")
            # Strips suffix /chat/completions
            self.assertEqual(service["serviceBaseUrl"], "https://api.openai.com/v1")
            self.assertEqual(service["defaultModel"], "gpt-4o")
            self.assertEqual(service["revision"], 1)
            self.assertFalse(service["keyConfigured"])
            self.assertNotIn("apiKey", service)

            result = store.list_services()
            self.assertEqual(result["directServiceCount"], 1)
            self.assertEqual(result["directServices"][0]["id"], service["id"])

    def test_enforces_max_five_direct_services(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            for i in range(MAX_DIRECT_SERVICES):
                store.create_service(
                    name=f"服务-{i + 1}",
                    service_base_url=f"https://api{i + 1}.example.com/v1",
                )

            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service(
                    name="超额服务",
                    service_base_url="https://api6.example.com/v1",
                )
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_LIMIT")

    def test_validates_service_name_uniqueness_and_length(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            store.create_service(name="唯一服务", service_base_url="https://api.example.com/v1")

            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service(name="唯一服务", service_base_url="https://api2.example.com/v1")
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_NAME_DUPLICATE")

            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service(name="a" * 41, service_base_url="https://api.example.com/v1")
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_NAME_INVALID")

            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service(name="", service_base_url="https://api.example.com/v1")
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_NAME_INVALID")

    def test_api_key_lifecycle_and_security(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            service = store.create_service(
                name="Key测试服务", service_base_url="https://api.example.com/v1"
            )
            key_dir = root / "provider_api_keys"

            # Verify schemaVersion
            self.assertEqual(service["schemaVersion"], "provider.direct_service.v1")

            # Missing revision should fail
            with self.assertRaises(DirectServiceError) as ctx:
                store.replace_api_key(service["id"], "sk-fail", expected_revision=None)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_REQUIRED")

            # Replace API Key with expected_revision=1
            updated = store.replace_api_key(
                service["id"], "sk-secret-token-123", expected_revision=1
            )
            self.assertTrue(updated["keyConfigured"])
            self.assertEqual(updated["revision"], 2)
            self.assertEqual(updated["schemaVersion"], "provider.direct_service.v1")
            self.assertNotIn("apiKey", updated)

            # Check file and directory permissions on POSIX
            key_file = key_dir / f"direct_service_{service['id']}"
            self.assertTrue(key_file.exists())
            self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "sk-secret-token-123")
            self.assertEqual(oct(key_file.stat().st_mode & 0o777), oct(0o600))
            self.assertEqual(oct(key_dir.stat().st_mode & 0o777), oct(0o700))

            # Read with include_secret
            with_secret = store.get_service(service["id"], include_secret=True)
            self.assertEqual(with_secret["apiKey"], "sk-secret-token-123")

            # Clear API Key with expected_revision=2
            cleared = store.clear_api_key(service["id"], expected_revision=2)
            self.assertFalse(cleared["keyConfigured"])
            self.assertEqual(cleared["revision"], 3)
            self.assertEqual(cleared["schemaVersion"], "provider.direct_service.v1")
            self.assertFalse(key_file.exists())

    def test_optimistic_concurrency_revision_check(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="并发测试", service_base_url="https://api.example.com/v1"
            )
            self.assertEqual(service["revision"], 1)

            # Successful update with correct expected_revision
            updated = store.update_service(
                service["id"],
                name="并发测试-改名",
                service_base_url="https://api-new.example.com/v1",
                expected_revision=1,
            )
            self.assertEqual(updated["revision"], 2)
            self.assertEqual(updated["name"], "并发测试-改名")

            # Outdated expected_revision should raise DIRECT_SERVICE_REVISION_CONFLICT
            with self.assertRaises(DirectServiceError) as ctx:
                store.update_service(
                    service["id"],
                    name="冲突改名",
                    service_base_url="https://api-conflict.example.com/v1",
                    expected_revision=1,
                )
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

            # Key replacement with wrong expected_revision should also fail
            with self.assertRaises(DirectServiceError) as ctx:
                store.replace_api_key(service["id"], "sk-new", expected_revision=1)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_REVISION_CONFLICT")

    def test_delete_service_checks_references_and_cleans_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            service = store.create_service(
                name="删除测试", service_base_url="https://api.example.com/v1"
            )
            store.replace_api_key(service["id"], "secret-to-delete", expected_revision=1)
            key_file = root / "provider_api_keys" / f"direct_service_{service['id']}"
            self.assertTrue(key_file.exists())

            # Bind to task model selection
            store.update_task_model_selection(
                task_type="word.smart_write",
                service_id=service["id"],
                model_name="custom-model",
            )

            # Deletion should be protected
            with self.assertRaises(DirectServiceError) as ctx:
                store.delete_service(service["id"], expected_revision=2)
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")
            self.assertIn("word.smart_write", ctx.exception.referenced_tasks)

            # Unbind
            store.update_task_model_selection(
                task_type="word.smart_write",
                service_id="",
            )

            # Now deletion succeeds with expected_revision=2
            deleted = store.delete_service(service["id"], expected_revision=2)
            self.assertEqual(deleted["directServiceCount"], 0)
            self.assertEqual(deleted["schemaVersion"], "provider.direct_service.v1")
            self.assertFalse(key_file.exists())

    def test_task_model_selection_lifecycle_and_default_model_inheritance(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service(
                name="共享网关",
                service_base_url="https://api.example.com/v1",
                default_model="qwen-max",
            )

            # Initial list returns all 9 tasks with empty serviceId
            initial = store.list_task_model_selections()
            self.assertEqual(len(initial["taskModelSelections"]), 9)
            write_sel = next(
                item for item in initial["taskModelSelections"]
                if item["taskType"] == "word.smart_write"
            )
            self.assertEqual(write_sel["serviceId"], "")
            self.assertEqual(write_sel["effectiveModel"], "")

            # Bind word.smart_write without model_name -> inherits default_model
            bound = store.update_task_model_selection(
                task_type="word.smart_write",
                service_id=service["id"],
                model_name="",
                temperature=0.5,
                max_output_tokens=2048,
            )
            self.assertEqual(bound["serviceId"], service["id"])
            self.assertEqual(bound["modelName"], "")
            self.assertEqual(bound["effectiveModel"], "qwen-max")
            self.assertEqual(bound["temperature"], 0.5)
            self.assertEqual(bound["maxOutputTokens"], 2048)

            # Override model_name -> uses overridden model
            overridden = store.update_task_model_selection(
                task_type="word.smart_write",
                service_id=service["id"],
                model_name="qwen-plus",
            )
            self.assertEqual(overridden["modelName"], "qwen-plus")
            self.assertEqual(overridden["effectiveModel"], "qwen-plus")

            # Filter by host
            word_selections = store.list_task_model_selections(host="word")
            self.assertEqual(len(word_selections["taskModelSelections"]), 4)
            excel_selections = store.list_task_model_selections(host="excel")
            self.assertEqual(len(excel_selections["taskModelSelections"]), 3)
            ppt_selections = store.list_task_model_selections(host="ppt")
            self.assertEqual(len(ppt_selections["taskModelSelections"]), 2)

    def test_task_model_selection_validates_task_and_service_and_params(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            with self.assertRaises(DirectServiceError) as ctx:
                store.update_task_model_selection(
                    task_type="invalid.task",
                    service_id="",
                )
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_TASK_UNSUPPORTED")

            with self.assertRaises(DirectServiceError) as ctx:
                store.update_task_model_selection(
                    task_type="word.smart_write",
                    service_id="non-existent-id",
                )
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_NOT_FOUND")

            with self.assertRaises(DirectServiceError) as ctx:
                store.update_task_model_selection(
                    task_type="word.smart_write",
                    service_id="",
                    temperature=3.5,
                )
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_PARAM_INVALID")

    def test_url_normalization_raises_direct_service_error(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service("测试URL", service_base_url="ftp://invalid.example.com")
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_URL_INVALID")

            with self.assertRaises(DirectServiceError) as ctx:
                store.create_service("测试URL2", service_base_url="https://user:pass@invalid.example.com")
            self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_URL_INVALID")

    def test_atomic_key_rollback_on_config_save_failure(self) -> None:
        from unittest.mock import patch
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            service = store.create_service("原子性测试", service_base_url="https://api.example.com/v1")
            store.replace_api_key(service["id"], "initial-key", expected_revision=1)
            key_file = root / "provider_api_keys" / f"direct_service_{service['id']}"
            self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "initial-key")

            # Mock save_config_payload to fail when updating key
            with patch("app.services.direct_services.save_config_payload", side_effect=OSError("Disk full")):
                with self.assertRaises(OSError):
                    store.replace_api_key(service["id"], "failed-new-key", expected_revision=2)

            # Prior key must be restored
            self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "initial-key")

            # Test rollback on clear_api_key failure
            with patch("app.services.direct_services.save_config_payload", side_effect=OSError("Disk full")):
                with self.assertRaises(OSError):
                    store.clear_api_key(service["id"], expected_revision=2)

            # Prior key must still exist
            self.assertTrue(key_file.exists())
            self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "initial-key")

    def test_custom_model_validation_defense(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            service = store.create_service("模型校验防御", service_base_url="https://api.example.com/v1")

            # Client passing customModelValidated=True must be ignored
            sel = store.update_task_model_selection(
                task_type="word.smart_write",
                service_id=service["id"],
                model_name="custom-unverified",
                custom_model=True,
                custom_model_validated=True,
            )
            self.assertFalse(sel["customModelValidated"])
            self.assertTrue(sel["customModel"])
            self.assertEqual(sel["schemaVersion"], "provider.task_model_selection.v1")


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone adapter tests")
class StandaloneDirectServiceHandlerTests(unittest.TestCase):
    def setUp(self):
        import standalone_adapter

        self.standalone = standalone_adapter
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "adapter.json"
        self.api_key_dir = Path(self.temp_dir.name) / "keys"
        self.api_key_dir.mkdir(parents=True, exist_ok=True)

        from app.services.model_configurations import ModelConfigurationStore

        self._orig_store = standalone_adapter.DirectServiceStore
        self._orig_model_store = standalone_adapter.ModelConfigurationStore

        # Create a store bound to temp paths
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

    def tearDown(self):
        self.standalone.DirectServiceStore = self._orig_store
        self.standalone.ModelConfigurationStore = self._orig_model_store
        self.temp_dir.cleanup()

    def _invoke(self, method, path, body=None):
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
        handler._write = lambda status, payload: writes.append((status, payload))
        handler._write_bytes = lambda status, payload, headers=None: writes.append(
            (status, json.loads(payload.decode("utf-8")) if payload else {})
        )
        getattr(handler, method)()
        status, resp_body = writes[-1] if writes else (None, None)
        return {"status": status, "body": resp_body, "writes": writes}

    def test_standalone_direct_service_lifecycle(self) -> None:
        # 1. List services initially empty
        res = self._invoke("do_GET", "/provider/direct-services")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["body"]["data"]["directServices"], [])
        self.assertEqual(res["body"]["data"]["directServiceCount"], 0)
        self.assertEqual(res["body"]["data"]["schemaVersion"], "provider.direct_service.v1")

        # 2. Create service via POST
        res = self._invoke(
            "do_POST",
            "/provider/direct-services",
            {
                "name": "DeepSeek API",
                "serviceBaseUrl": "https://api.deepseek.com/v1",
                "defaultModel": "deepseek-chat",
            },
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        svc = res["body"]["data"]["directService"]
        service_id = svc["id"]
        self.assertEqual(svc["name"], "DeepSeek API")
        self.assertEqual(svc["serviceBaseUrl"], "https://api.deepseek.com/v1")
        self.assertEqual(svc["defaultModel"], "deepseek-chat")
        self.assertEqual(svc["revision"], 1)
        self.assertEqual(svc["schemaVersion"], "provider.direct_service.v1")

        # 3. Get single service
        res = self._invoke("do_GET", f"/provider/direct-services/{service_id}")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["body"]["data"]["directService"]["id"], service_id)

        # 4. Set API key
        res = self._invoke(
            "do_POST",
            f"/provider/direct-services/{service_id}/api-key",
            {"apiKey": "sk-secret-12345", "expectedRevision": 1},
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertTrue(res["body"]["data"]["directService"]["keyConfigured"])
        self.assertEqual(res["body"]["data"]["directService"]["revision"], 2)

        # 5. Update service with PATCH
        res = self._invoke(
            "do_PATCH",
            f"/provider/direct-services/{service_id}",
            {
                "name": "DeepSeek Renamed",
                "expectedRevision": 2,
                "serviceBaseUrl": "https://api.deepseek.com/v1",
                "defaultModel": "deepseek-reasoner",
            },
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["body"]["data"]["directService"]["name"], "DeepSeek Renamed")
        self.assertEqual(res["body"]["data"]["directService"]["defaultModel"], "deepseek-reasoner")
        self.assertEqual(res["body"]["data"]["directService"]["revision"], 3)

        # 6. Update models cache (increments revision to 4)
        res = self._invoke(
            "do_POST",
            f"/provider/direct-services/{service_id}/models",
            {
                "modelList": ["deepseek-chat", "deepseek-reasoner"],
                "expectedRevision": 3,
            },
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(
            res["body"]["data"]["directService"]["modelList"],
            ["deepseek-chat", "deepseek-reasoner"],
        )
        self.assertEqual(res["body"]["data"]["directService"]["revision"], 4)

        # 7. Update task model selection
        res = self._invoke(
            "do_PUT",
            "/provider/task-model-selections/word.smart_write",
            {
                "serviceId": service_id,
                "modelName": "deepseek-reasoner",
                "temperature": 0.5,
                "maxOutputTokens": 4096,
            },
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        sel = res["body"]["data"]["taskModelSelection"]
        self.assertEqual(sel["serviceId"], service_id)
        self.assertEqual(sel["effectiveModel"], "deepseek-reasoner")
        self.assertEqual(sel["temperature"], 0.5)
        self.assertEqual(sel["schemaVersion"], "provider.task_model_selection.v1")

        # 8. List selections
        res = self._invoke("do_GET", "/provider/task-model-selections?taskType=word.smart_write")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(len(res["body"]["data"]["taskModelSelections"]), 1)
        self.assertEqual(res["body"]["data"]["taskModelSelections"][0]["serviceName"], "DeepSeek Renamed")

        # 9. Try deleting service while in use -> should return 409 with referencedTasks
        res = self._invoke("do_DELETE", f"/provider/direct-services/{service_id}?expectedRevision=4")
        self.assertEqual(res["status"], 409)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["body"]["errors"][0]["code"], "DIRECT_SERVICE_IN_USE")
        self.assertIn("word.smart_write", res["body"]["errors"][0]["referencedTasks"])

        # 10. Clear task selection
        res = self._invoke(
            "do_PUT",
            "/provider/task-model-selections/word.smart_write",
            {"serviceId": ""},
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)

        # 11. Clear API key with expectedRevision=4 -> increments revision to 5
        res = self._invoke(
            "do_DELETE",
            f"/provider/direct-services/{service_id}/api-key?expectedRevision=4",
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertFalse(res["body"]["data"]["directService"]["keyConfigured"])
        self.assertEqual(res["body"]["data"]["directService"]["revision"], 5)

        # 12. Delete service successfully with expectedRevision=5
        res = self._invoke("do_DELETE", f"/provider/direct-services/{service_id}?expectedRevision=5")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["body"]["data"]["directServices"], [])
        self.assertEqual(res["body"]["data"]["directServiceCount"], 0)

    def test_standalone_model_configuration_patch_does_not_fall_through_to_404(self) -> None:
        """Regression test for Critical 1: PATCH model-configurations must return 200 and not fall through to 404."""
        from app.services.model_configurations import ModelConfigurationStore

        model_store = ModelConfigurationStore(
            config_path=self.config_path, key_dir=self.api_key_dir
        )
        cfg = model_store.create_configuration(
            task_type="word.smart_write",
            name="既有编写配置",
            access_method="direct_model",
            service_base_url="https://api.openai.com/v1",
            model_name="gpt-4o",
        )
        cfg_id = cfg["id"]

        # Call PATCH on model-configurations
        res = self._invoke(
            "do_PATCH",
            f"/provider/model-configurations/{cfg_id}",
            {"name": "修改后的编写配置"},
        )
        # Must write exactly once with 200, NEVER followed by a 404
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["writes"]), 1)
        self.assertEqual(res["writes"][0][0], 200)
        self.assertEqual(
            res["body"]["data"]["configuration"]["name"], "修改后的编写配置"
        )

    def test_standalone_writing_policy_put_does_not_fall_through_to_501(self) -> None:
        """Regression test for Critical 2: PUT writing-policy must return response and not fall through to 501."""
        # Dispatching PUT /writing-policies/preset-overrides/{entry_id}
        res = self._invoke(
            "do_PUT",
            "/writing-policies/preset-overrides/rule-preset-1",
            {"enabled": True},
        )
        # Must not write 501
        self.assertNotEqual(res["status"], 501)
        self.assertEqual(len(res["writes"]), 1)

    def test_standalone_direct_service_invalid_url_returns_400(self) -> None:
        """Regression test for Important 1: Invalid URL must return 400 instead of 500."""
        res = self._invoke(
            "do_POST",
            "/provider/direct-services",
            {
                "name": "非法URL服务",
                "serviceBaseUrl": "ftp://not-supported",
                "defaultModel": "gpt-4o",
            },
        )
        self.assertEqual(res["status"], 400)
        self.assertEqual(len(res["writes"]), 1)
    def test_direct_service_atomic_create_with_api_key(self) -> None:
        """Atomic direct service creation with API key configured in one shot."""
        res = self._invoke(
            "do_POST",
            "/provider/direct-services",
            {
                "name": "原子创建直连服务",
                "serviceBaseUrl": "https://api.openai.com/v1",
                "defaultModel": "gpt-4o",
                "apiKey": "sk-atomic-key-123",
            },
        )
        self.assertEqual(res["status"], 200)
        svc = res["body"]["data"]["directService"]
        self.assertEqual(svc["name"], "原子创建直连服务")
        self.assertTrue(svc["keyConfigured"])
        self.assertEqual(svc["revision"], 1)

    def test_activate_direct_service_requires_effective_model(self) -> None:
        """Activating direct service without defaultModel and without task model selection must fail."""
        res = self._invoke(
            "do_POST",
            "/provider/direct-services",
            {
                "name": "无模型直连服务",
                "serviceBaseUrl": "https://api.openai.com/v1",
                "defaultModel": "",
                "apiKey": "sk-test-key",
            },
        )
        self.assertEqual(res["status"], 200)
        svc_id = res["body"]["data"]["directService"]["id"]

        # Activate on excel.analysis without setting modelName -> must fail with 400 DIRECT_SERVICE_MODEL_REQUIRED
        res = self._invoke(
            "do_POST",
            f"/provider/direct-services/{svc_id}/activate",
            {"taskType": "excel.analysis"},
        )
        self.assertEqual(res["status"], 400)
        self.assertEqual(res["body"]["errors"][0]["code"], "DIRECT_SERVICE_MODEL_REQUIRED")

    def test_list_task_model_selections_returns_selections_dict(self) -> None:
        """Listing task model selections must provide both array and dict mapping."""
        res = self._invoke("do_GET", "/provider/task-model-selections?host=excel")
        self.assertEqual(res["status"], 200)
        data = res["body"]["data"]
        self.assertIn("taskModelSelections", data)
        self.assertIn("selections", data)
        self.assertIn("excel.analysis", data["selections"])
        self.assertEqual(data["selections"]["excel.analysis"]["taskType"], "excel.analysis")


if __name__ == "__main__":
    unittest.main()
