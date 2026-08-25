import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
    ModelConfigurationError,
    ModelConfigurationStore,
    WorkflowProfileCompatibilityStore,
    normalize_service_base_url,
)


class ModelConfigurationStoreTests(unittest.TestCase):
    def _store(self, root: Path) -> ModelConfigurationStore:
        config_path = root / "adapter.json"
        if not config_path.exists():
            config_path.write_text("{}\n", encoding="utf-8")
        return ModelConfigurationStore(config_path, root / "provider_api_keys")

    def test_migrates_workflow_profile_in_place_and_preserves_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_dir = root / "provider_api_keys"
            key_dir.mkdir()
            key_path = key_dir / "workflow_existing"
            key_path.write_text("secret\n", encoding="utf-8")
            config_path = root / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "providerBaseUrl": "http://1.1.1.1:1111/one-api/v1",
                        "workflowProfiles": {
                            "profile_existing": {
                                "id": "profile_existing",
                                "taskType": "word.smart_write",
                                "name": "生产版",
                                "note": "原备注",
                                "apiKeyRef": "workflow_existing",
                            }
                        },
                        "activeWorkflowProfiles": {
                            "word.smart_write": "profile_existing"
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = ModelConfigurationStore(config_path, key_dir)

            first = store.list_for_task("word.smart_write")
            second = store.list_for_task("word.smart_write")

            self.assertEqual(first, second)
            self.assertEqual(first["activeConfigurationId"], "profile_existing")
            item = first["configurations"][0]
            self.assertEqual(item["accessMethod"], ACCESS_WORKFLOW_PLATFORM)
            self.assertEqual(item["serviceBaseUrl"], "http://1.1.1.1:1111/one-api/v1")
            self.assertTrue(item["keyConfigured"])
            self.assertEqual(key_path.read_text(encoding="utf-8").strip(), "secret")

    def test_deleted_migrated_workflow_configuration_does_not_reappear(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_dir = root / "provider_api_keys"
            key_dir.mkdir()
            (key_dir / "workflow_existing").write_text("secret\n", encoding="utf-8")
            config_path = root / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "providerBaseUrl": "https://workflow.example/v1",
                        "workflowProfiles": {
                            "profile_existing": {
                                "id": "profile_existing",
                                "taskType": "word.smart_write",
                                "name": "旧工作流",
                                "apiKeyRef": "workflow_existing",
                            }
                        },
                        "activeWorkflowProfiles": {
                            "word.smart_write": "profile_existing"
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = ModelConfigurationStore(config_path, key_dir)
            store.list_for_task("word.smart_write")
            direct = store.create_configuration(
                "word.smart_write",
                "直连配置",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="glm-5.2",
            )
            store.replace_api_key(direct["id"], "direct-secret")
            store.activate_configuration(direct["id"])

            deleted = store.delete_configuration("profile_existing")
            restarted = ModelConfigurationStore(config_path, key_dir).list_for_task(
                "word.smart_write"
            )
            persisted = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(
                [item["id"] for item in deleted["configurations"]], [direct["id"]]
            )
            self.assertEqual(
                [item["id"] for item in restarted["configurations"]], [direct["id"]]
            )
            self.assertTrue(persisted["migrationState"]["workflowProfilesImported"])
            self.assertFalse((key_dir / "workflow_existing").exists())

    def test_direct_configuration_requires_model_and_key_before_activation(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "excel.analysis", "直连", ACCESS_DIRECT_MODEL
            )
            self.assertFalse(configuration["complete"])
            with self.assertRaises(ModelConfigurationError):
                store.activate_configuration(configuration["id"])

            configuration = store.update_configuration(
                configuration["id"],
                name="直连",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="http://1.1.1.1:1111/one-api/v1/chat/completions",
                model_name="deepseek-v4-flash",
            )
            store.replace_api_key(configuration["id"], "direct-secret")
            active = store.activate_configuration(configuration["id"])

            self.assertEqual(active["activeConfigurationId"], configuration["id"])
            resolved = store.get_active_configuration("excel.analysis", include_secret=True)
            self.assertEqual(resolved["serviceBaseUrl"], "http://1.1.1.1:1111/one-api/v1")
            self.assertEqual(resolved["apiKey"], "direct-secret")

    def test_method_switch_drops_old_key_and_direct_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            direct = store.create_configuration(
                "word.smart_write",
                "切换测试",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="glm-5.2",
                temperature=0.2,
            )
            direct = store.replace_api_key(direct["id"], "old-secret")
            old_ref = direct["apiKeyRef"]

            platform = store.update_configuration(
                direct["id"],
                name="切换测试",
                access_method=ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://workflow.example/v1",
            )

            self.assertFalse(platform["keyConfigured"])
            self.assertEqual(platform["modelName"], "")
            self.assertIsNone(platform["temperature"])
            self.assertFalse((store.key_dir / old_ref).exists())

    def test_copy_is_limited_to_same_host_and_copies_secret_independently(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            source = store.create_configuration(
                "word.smart_write",
                "生产版",
                ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://workflow.example/v1",
            )
            source = store.replace_api_key(source["id"], "secret")
            copied = store.copy_configuration(source["id"], "word.document_review")
            self.assertNotEqual(source["apiKeyRef"], copied["apiKeyRef"])
            self.assertTrue(copied["keyConfigured"])
            with self.assertRaises(ModelConfigurationError):
                store.copy_configuration(source["id"], "excel.analysis")

    def test_normalize_service_url_rejects_query_and_strips_known_path(self) -> None:
        self.assertEqual(
            normalize_service_base_url(" http://host:1111/one-api/v1/chat/completions/ "),
            "http://host:1111/one-api/v1",
        )
        with self.assertRaises(ModelConfigurationError):
            normalize_service_base_url("https://host/v1?key=secret")

    def test_format_semantic_readiness_is_stale_after_configuration_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "word.format_review",
                "格式协议",
                ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://workflow.example/v1",
            )
            configuration = store.replace_api_key(configuration["id"], "secret")
            self.assertEqual(
                configuration["formatSemanticReadiness"]["code"],
                "validation_required",
            )

            ready = store.record_format_semantic_validation(
                configuration["id"],
                {
                    "success": True,
                    "protocolVersion": "format_semantics.v1",
                    "operations": {
                        "classify_role": True,
                        "associate_caption": True,
                        "suggest_table_caption": True,
                        "suggest_figure_caption": True,
                    },
                },
            )
            self.assertEqual(ready["formatSemanticReadiness"]["code"], "ready")

            changed = store.update_configuration(
                configuration["id"],
                name="格式协议",
                access_method=ACCESS_WORKFLOW_PLATFORM,
                service_base_url="https://workflow-2.example/v1",
            )
            self.assertEqual(
                changed["formatSemanticReadiness"]["code"],
                "validation_required",
            )
            self.assertTrue(changed["formatSemanticValidation"]["stale"])

    def test_direct_format_validation_is_ready_until_key_or_protocol_inputs_change(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "word.format_review",
                "直连格式协议",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="format-role-model",
                max_output_tokens=1024,
                context_window_tokens=40000,
            )
            configuration = store.replace_api_key(configuration["id"], "secret")
            validated = store.record_format_semantic_validation(
                configuration["id"],
                {
                    "success": True,
                    "protocolVersion": "format_semantics.v1",
                    "operations": {"classify_role": True},
                },
            )
            self.assertEqual(validated["formatSemanticReadiness"]["code"], "ready")

            changed = store.replace_api_key(configuration["id"], "new-secret")
            self.assertGreater(changed["configVersion"], validated["configVersion"])
            self.assertTrue(changed["formatSemanticValidation"]["stale"])
            self.assertEqual(
                changed["formatSemanticReadiness"]["code"], "validation_required"
            )

    def test_image_semantics_save_binds_and_host_change_stales_until_next_save(self) -> None:
        with TemporaryDirectory() as tmp:
            store = self._store(Path(tmp))
            configuration = store.create_configuration(
                "word.format_review",
                "图片门禁",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://vision.example/v1",
                model_name="vision-1",
            )
            self.assertEqual(configuration["imageInputMode"], "openai_image_url")
            saved = store.replace_api_key(configuration["id"], "secret")
            self.assertTrue(saved["imageExternalAuthorization"]["authorized"])
            self.assertEqual(
                saved["imageSemanticReadiness"]["code"],
                "validation_required",
            )
            validated = store.record_image_semantic_validation(
                saved["id"], {"validated": True}
            )
            self.assertTrue(validated["imageSemanticReadiness"]["ready"])

            changed = store.update_configuration(
                validated["id"],
                name="图片门禁",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://other-vision.example/v1",
                model_name="vision-1",
                image_input_mode="openai_image_url",
            )
            self.assertTrue(changed["imageExternalAuthorization"]["stale"])
            self.assertTrue(changed["imageSemanticValidation"]["stale"])
            self.assertEqual(
                changed["imageSemanticReadiness"]["code"],
                "authorization_required",
            )

    def test_image_semantics_migration_keeps_explicit_off_and_drops_acceptance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "formatReview": {
                            "imageSemantics": {
                                "enabled": False,
                                "wpsAcceptanceConfirmed": True,
                                "configVersion": 1,
                            }
                        },
                        "modelConfigurations": {
                            "legacy": {
                                "id": "legacy",
                                "taskType": "word.format_review",
                                "accessMethod": ACCESS_DIRECT_MODEL,
                                "serviceBaseUrl": "https://vision.example/v1",
                                "modelName": "vision-1",
                                "apiKeyRef": "legacy-key",
                                "configVersion": 1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            ModelConfigurationStore(config_path, root / "provider_api_keys").list_for_task(
                "word.format_review"
            )
            migrated = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertFalse(migrated["formatReview"]["imageSemantics"]["enabled"])
            self.assertNotIn(
                "wpsAcceptanceConfirmed",
                migrated["formatReview"]["imageSemantics"],
            )
            self.assertEqual(
                migrated["modelConfigurations"]["legacy"]["imageInputMode"],
                "disabled",
            )
            self.assertIsNone(
                migrated["modelConfigurations"]["legacy"][
                    "imageExternalAuthorization"
                ]
            )
            self.assertIsNone(
                migrated["modelConfigurations"]["legacy"]["imageSemanticValidation"]
            )

    def test_legacy_workflow_facade_writes_the_new_configuration_store(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text(
                json.dumps({"providerBaseUrl": "https://workflow.example/v1"}),
                encoding="utf-8",
            )
            key_dir = root / "provider_api_keys"
            facade = WorkflowProfileCompatibilityStore(config_path, key_dir)

            profile = facade.create_profile(
                "word.smart_write", "兼容配置", "legacy-secret", activate=True
            )

            model_data = ModelConfigurationStore(config_path, key_dir).list_for_task(
                "word.smart_write"
            )
            self.assertEqual(model_data["activeConfigurationId"], profile["id"])
            self.assertEqual(model_data["configurations"][0]["accessMethod"], ACCESS_WORKFLOW_PLATFORM)
            self.assertEqual(
                model_data["configurations"][0]["serviceBaseUrl"],
                "https://workflow.example/v1",
            )

    def test_legacy_workflow_facade_cannot_expose_direct_model_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self._store(root)
            direct = store.create_configuration(
                "word.smart_write",
                "直连配置",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="glm-5.2",
            )
            store.replace_api_key(direct["id"], "direct-secret")
            store.activate_configuration(direct["id"])

            facade = WorkflowProfileCompatibilityStore(
                store.config_path, store.key_dir
            )
            data = facade.list_for_task("word.smart_write")

            self.assertEqual(data["profileCount"], 0)
            self.assertEqual(data["activeProfileId"], "")


if __name__ == "__main__":
    unittest.main()
