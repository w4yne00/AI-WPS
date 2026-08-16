import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.services.workflow_profiles import WorkflowProfileStore

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from app.core.errors import AdapterError
    from app.api.provider import (
        ModelConfigurationCreateRequest,
        ModelConfigurationImageAuthorizationRequest,
        WorkflowProfileApiKeyRequest,
        WorkflowProfileCreateRequest,
        WorkflowProfileUpdateRequest,
        activate_workflow_profile,
        create_workflow_profile,
        delete_provider_task_api_key,
        delete_workflow_profile,
        get_workflow_profiles,
        replace_workflow_profile_api_key,
        save_provider_task_api_key,
        update_workflow_profile,
        ProviderTaskApiKeyRequest,
        create_model_configuration,
        set_model_configuration_image_authorization,
        validate_model_configuration,
    )
    from app.services.model_configurations import (
        ACCESS_DIRECT_MODEL,
        ModelConfigurationStore,
    )


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for workflow profile API tests")
class WorkflowProfileApiTests(unittest.TestCase):
    def _store(self, root: Path) -> WorkflowProfileStore:
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        return WorkflowProfileStore(config_path, root / "provider_api_keys")

    def test_model_image_authorization_route_is_bound_to_explicit_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            with patch("app.api.provider.get_model_configuration_store", return_value=store):
                created = create_model_configuration(
                    ModelConfigurationCreateRequest(
                        taskType="word.format_review",
                        name="视觉配置",
                        accessMethod=ACCESS_DIRECT_MODEL,
                        serviceBaseUrl="https://vision.example/v1",
                        modelName="vision-1",
                        imageInputMode="openai_image_url",
                    )
                )
                configuration_id = created["data"]["configuration"]["id"]
                authorized = set_model_configuration_image_authorization(
                    configuration_id,
                    ModelConfigurationImageAuthorizationRequest(authorized=True),
                )

            self.assertEqual(
                authorized["data"]["configuration"]["imageSemanticReadiness"]["code"],
                "validation_required",
            )

    def test_direct_format_validation_returns_identity_without_activation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            created = store.create_configuration(
                "word.format_review",
                "直连格式验证",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="format-role-model",
                max_output_tokens=1024,
                context_window_tokens=40000,
            )
            store.replace_api_key(created["id"], "format-secret")
            validation = {
                "success": True,
                "taskType": "word.format_review",
                "configurationId": created["id"],
                "configurationName": "直连格式验证",
                "configurationRevision": 2,
                "isCurrent": False,
                "currentConfigurationId": "",
                "currentConfigurationName": "",
                "accessMethod": ACCESS_DIRECT_MODEL,
                "modelName": "format-role-model",
                "promptVersion": "format_semantics.v1",
                "formatSemanticValidation": {
                    "success": True,
                    "protocolVersion": "format_semantics.v1",
                    "operations": {"classify_role": True},
                },
            }
            with patch("app.api.provider.get_model_configuration_store", return_value=store), patch(
                "app.api.provider.ProviderClient.validate_model_configuration",
                return_value=validation,
            ):
                result = validate_model_configuration(created["id"])

            data = result["data"]
            self.assertEqual(data["configurationId"], created["id"])
            self.assertEqual(data["configurationName"], "直连格式验证")
            self.assertEqual(data["configurationRevision"], 2)
            self.assertFalse(data["isCurrent"])
            self.assertEqual(data["currentConfigurationId"], "")
            self.assertEqual(
                store.list_for_task("word.format_review")["activeConfigurationId"], ""
            )
            self.assertTrue(data["configuration"]["lastValidation"]["success"])
            self.assertTrue(data["configuration"]["formatSemanticValidation"]["success"])

    def test_direct_format_validation_persists_safe_contract_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            created = store.create_configuration(
                "word.format_review",
                "失败格式验证",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="format-role-model",
                max_output_tokens=1024,
                context_window_tokens=40000,
            )
            with patch("app.api.provider.get_model_configuration_store", return_value=store), patch(
                "app.api.provider.ProviderClient.validate_model_configuration",
                side_effect=AdapterError(
                    "FORMAT_SEMANTIC_BINDING_INVALID",
                    "格式语义响应未绑定当前格式快照。",
                    status_code=502,
                ),
            ):
                with self.assertRaises(AdapterError) as raised:
                    validate_model_configuration(created["id"])

            self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_BINDING_INVALID")
            configuration = store.get_configuration(created["id"])
            self.assertFalse(configuration["lastValidation"]["success"])
            self.assertEqual(
                configuration["lastValidation"]["errorCode"],
                "FORMAT_SEMANTIC_BINDING_INVALID",
            )
            self.assertFalse(configuration["formatSemanticValidation"]["success"])
            self.assertEqual(
                configuration["formatSemanticValidation"]["errorCode"],
                "FORMAT_SEMANTIC_BINDING_INVALID",
            )

    def test_crud_routes_return_sanitized_profile_data(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                created = create_workflow_profile(
                    WorkflowProfileCreateRequest(
                        taskType="word.smart_write",
                        name="稳定版",
                        apiKey="app-secret",
                        note="生产",
                        activate=True,
                    )
                )
                profile = created["data"]["profile"]
                listed = get_workflow_profiles(task_type="word.smart_write")
                updated = update_workflow_profile(
                    profile["id"], WorkflowProfileUpdateRequest(name="正式版", note="当前生产")
                )
                replaced = replace_workflow_profile_api_key(
                    profile["id"], WorkflowProfileApiKeyRequest(apiKey="app-replaced")
                )

            self.assertEqual(listed["data"]["profileCount"], 1)
            self.assertEqual(updated["data"]["profile"]["name"], "正式版")
            self.assertTrue(replaced["data"]["profile"]["keyConfigured"])
            self.assertNotIn("app-secret", str(created))
            self.assertNotIn("app-replaced", str(replaced))

    def test_activate_and_delete_routes_enforce_active_profile_protection(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            active = store.create_profile("word.format_review", "当前版", "app-one", activate=True)
            inactive = store.create_profile("word.format_review", "候选版", "app-two")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                activated = activate_workflow_profile(inactive["id"])
                deleted = delete_workflow_profile(active["id"])
                with self.assertRaises(AdapterError) as raised:
                    delete_workflow_profile(inactive["id"])

            self.assertEqual(activated["data"]["activeProfileId"], inactive["id"])
            self.assertEqual(deleted["data"]["profileCount"], 1)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("先切换", raised.exception.message)

    def test_duplicate_name_maps_to_http_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            store.create_profile("excel.analysis", "生产版", "app-one")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                with self.assertRaises(AdapterError) as raised:
                    create_workflow_profile(
                        WorkflowProfileCreateRequest(
                            taskType="excel.analysis", name="生产版", apiKey="app-two"
                        )
                    )

            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("名称已存在", raised.exception.message)

    def test_legacy_task_key_routes_update_only_current_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            historical = store.create_profile("word.document_review", "历史版", "app-old")
            with patch("app.api.provider.get_workflow_profile_store", return_value=store):
                saved = save_provider_task_api_key(
                    ProviderTaskApiKeyRequest(
                        taskType="word.document_review",
                        apiKey="app-current",
                        apiKeyRef="document_review_current",
                    )
                )
                cleared = delete_provider_task_api_key("word.document_review")

            self.assertEqual(saved["data"]["activeProfileName"], "当前配置")
            self.assertFalse(cleared["data"]["taskKeyConfigured"])
            self.assertTrue((store.key_dir / historical["apiKeyRef"]).exists())


if __name__ == "__main__":
    unittest.main()
