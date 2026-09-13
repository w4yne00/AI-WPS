import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
if HAS_PYDANTIC:
    from app.services.provider_client import ProviderClient

from app.services.model_configurations import ACCESS_DIRECT_MODEL
from app.services.direct_services import (
    DIRECT_SERVICE_SCHEMA_VERSION,
    DirectServiceError,
    DirectServiceStore,
)


class WordFormatReviewDirectServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "adapter.json"
        self.key_dir = Path(self.tmp.name) / "keys"
        self.store = DirectServiceStore(self.config_path, self.key_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_service(self, name="通用大模型服务", default_model="gpt-4o", base_url="https://api.openai.com/v1", api_key="sk-test-secret"):
        svc = self.store.create_service(
            name=name,
            service_base_url=base_url,
            default_model=default_model,
        )
        self.store.replace_api_key(svc["id"], api_key, expected_revision=svc["revision"])
        self.store.update_model_list(
            svc["id"],
            ["gpt-4o", "gpt-4o-mini", "vision-model-1"],
            expected_revision=svc["revision"] + 1,
        )
        return self.store.get_service(svc["id"], include_secret=True)

    def test_format_review_selection_defaults_and_model_inheritance(self):
        """测试格式审查选择直连服务时，默认继承服务模型与图片模式 openai_image_url。"""
        svc = self._create_service()
        selection = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
        )
        self.assertEqual(selection["taskType"], "word.format_review")
        self.assertEqual(selection["serviceId"], svc["id"])
        self.assertEqual(selection["modelName"], "")
        self.assertEqual(selection["effectiveModel"], "gpt-4o")
        self.assertEqual(selection["imageInputMode"], "openai_image_url")
        self.assertEqual(selection["host"], "word")

    def test_format_review_selection_custom_parameters(self):
        """测试格式审查覆盖模型名称、Token参数与显式关闭图片输入模式。"""
        svc = self._create_service()
        selection = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="vision-model-1",
            temperature=0.3,
            max_output_tokens=4096,
            context_window_tokens=64000,
            image_input_mode="disabled",
        )
        self.assertEqual(selection["modelName"], "vision-model-1")
        self.assertEqual(selection["effectiveModel"], "vision-model-1")
        self.assertEqual(selection["temperature"], 0.3)
        self.assertEqual(selection["maxOutputTokens"], 4096)
        self.assertEqual(selection["contextWindowTokens"], 64000)
        self.assertEqual(selection["imageInputMode"], "disabled")
        self.assertEqual(selection["imageSemanticReadiness"]["code"], "disabled")

    def test_format_review_image_authorization_binding_and_stale_invalidation(self):
        """测试图片外发授权绑定到 (serviceHost, modelName, imageInputMode)，修改后自动失效。"""
        svc = self._create_service(base_url="https://api.openai.com/v1")
        self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="vision-model-1",
            image_input_mode="openai_image_url",
        )

        # 授权图片外发
        auth_record = self.store.set_image_external_authorization("word.format_review", True)
        self.assertTrue(auth_record["imageExternalAuthorization"]["authorized"])
        self.assertFalse(auth_record["imageExternalAuthorization"]["stale"])
        self.assertEqual(auth_record["imageExternalAuthorization"]["serviceHost"], "api.openai.com")
        self.assertEqual(auth_record["imageExternalAuthorization"]["modelName"], "vision-model-1")
        self.assertEqual(auth_record["imageExternalAuthorization"]["imageInputMode"], "openai_image_url")

        # 记录视觉能力验证
        valid_record = self.store.record_image_semantic_validation(
            "word.format_review",
            {"validated": True, "errorCode": ""}
        )
        self.assertTrue(valid_record["imageSemanticValidation"]["validated"])
        self.assertFalse(valid_record["imageSemanticValidation"]["stale"])
        self.assertEqual(valid_record["imageSemanticReadiness"]["code"], "ready")

        # 变更服务地址 -> 授权与验证立即标记 stale: True
        self.store.update_service(
            svc["id"],
            name="通用大模型服务",
            service_base_url="https://new-api.openai.com/v1",
            expected_revision=svc["revision"],
        )
        refreshed = self.store.get_task_model_selection("word.format_review")
        self.assertTrue(refreshed["imageExternalAuthorization"]["stale"])
        self.assertTrue(refreshed["imageSemanticValidation"]["stale"])
        self.assertEqual(refreshed["imageSemanticReadiness"]["code"], "authorization_required")

        # 再次保存选择 -> 重新绑定新地址，清除 authorization stale
        rebound = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="vision-model-1",
            image_input_mode="openai_image_url",
        )
        self.assertFalse(rebound["imageExternalAuthorization"]["stale"])
        self.assertEqual(rebound["imageExternalAuthorization"]["serviceHost"], "new-api.openai.com")

        # 变更模型 -> 授权与验证再次失效
        changed_model = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="gpt-4o",
            image_input_mode="openai_image_url",
        )
        self.assertTrue(changed_model["imageExternalAuthorization"]["stale"])
        self.assertTrue(changed_model["imageSemanticValidation"]["stale"])

        # 切换为 disabled -> imageExternalAuthorization 清空为 None
        disabled_sel = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="gpt-4o",
            image_input_mode="disabled",
        )
        self.assertIsNone(disabled_sel["imageExternalAuthorization"])
        self.assertEqual(disabled_sel["imageSemanticReadiness"]["code"], "disabled")

    def test_format_review_format_semantic_validation_lifecycle(self):
        """测试格式语义协议验证记录及服务/模型变更后的失效检查。"""
        svc = self._create_service()
        self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="gpt-4o",
        )
        # 初始未验证
        init_sel = self.store.get_task_model_selection("word.format_review")
        self.assertEqual(init_sel["formatSemanticReadiness"]["code"], "validation_required")

        # 记录验证成功
        validated = self.store.record_format_semantic_validation(
            "word.format_review",
            {
                "success": True,
                "protocolVersion": "format_semantics.v1",
                "operations": {"classify_role": True},
            }
        )
        self.assertTrue(validated["formatSemanticValidation"]["success"])
        self.assertFalse(validated["formatSemanticValidation"]["stale"])
        self.assertEqual(validated["formatSemanticReadiness"]["code"], "ready")

        # 更换模型 -> formatSemanticValidation 变为 stale
        updated = self.store.update_task_model_selection(
            "word.format_review",
            service_id=svc["id"],
            model_name="gpt-4o-mini",
        )
        self.assertTrue(updated["formatSemanticValidation"]["stale"])
        self.assertEqual(updated["formatSemanticReadiness"]["code"], "validation_required")

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for ProviderClient tests")
    def test_resolve_task_auth_for_format_review_direct_service(self):
        """测试 resolve_task_auth 在格式审查激活直连服务时，正确组装 modelConfiguration 与 Token 容量。"""
        svc = self._create_service(base_url="https://api.openai.com/v1", api_key="sk-format-auth-key")
        self.store.activate_direct_service(
            svc["id"],
            "word.format_review",
            task_model_selection={
                "serviceId": svc["id"],
                "modelName": "vision-model-1",
                "temperature": 0.5,
                "maxOutputTokens": 3000,
                "contextWindowTokens": 50000,
                "imageInputMode": "openai_image_url",
            }
        )
        self.store.set_image_external_authorization("word.format_review", True)
        self.store.record_image_semantic_validation(
            "word.format_review",
            {"validated": True}
        )
        self.store.record_format_semantic_validation(
            "word.format_review",
            {"success": True, "protocolVersion": "format_semantics.v1", "operations": {"classify_role": True}}
        )

        client = ProviderClient(direct_service_store=self.store)
        task_auth = client.resolve_task_auth("word.format_review")

        self.assertEqual(task_auth["accessMethod"], ACCESS_DIRECT_MODEL)
        self.assertEqual(task_auth["providerBaseUrl"], "https://api.openai.com/v1")
        self.assertEqual(task_auth["apiKey"], "sk-format-auth-key")
        self.assertEqual(task_auth["modelName"], "vision-model-1")
        self.assertEqual(task_auth["maxOutputTokens"], 3000)
        self.assertEqual(task_auth["contextWindowTokens"], 50000)
        self.assertEqual(task_auth["imageInputMode"], "openai_image_url")
        self.assertIsNotNone(task_auth["imageExternalAuthorization"])
        self.assertFalse(task_auth["imageExternalAuthorization"]["stale"])
        self.assertEqual(task_auth["imageSemanticReadiness"]["code"], "ready")
        self.assertEqual(task_auth["formatSemanticReadiness"]["code"], "ready")

        # 校验 modelConfiguration 字典完整度，供 FormatSemanticContract 和 WordFormatReviewer 使用
        config = task_auth.get("modelConfiguration")
        self.assertIsInstance(config, dict)
        self.assertEqual(config["id"], svc["id"])
        self.assertEqual(config["taskType"], "word.format_review")
        self.assertEqual(config["accessMethod"], ACCESS_DIRECT_MODEL)
        self.assertEqual(config["modelName"], "vision-model-1")
        self.assertEqual(config["maxOutputTokens"], 3000)
        self.assertEqual(config["imageInputMode"], "openai_image_url")
        self.assertTrue(config["imageExternalAuthorization"]["authorized"])

        from app.services.word.format_semantics import FormatSemanticContract
        self.assertEqual(FormatSemanticContract.output_budget(task_auth), 3000)

    def test_direct_service_delete_protection_includes_format_review(self):
        """测试被 word.format_review 引用的直连服务禁止删除并披露引用。"""
        svc = self._create_service()
        self.store.activate_direct_service(
            svc["id"],
            "word.format_review",
            task_model_selection={"serviceId": svc["id"]}
        )
        with self.assertRaises(DirectServiceError) as ctx:
            self.store.delete_service(svc["id"], expected_revision=svc["revision"])
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")
        sanitized = self.store.get_service(svc["id"])
        self.assertIn("word.format_review", sanitized.get("referencedTasks", []))

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for ProviderClient tests")
    def test_validate_task_model_selection_for_format_review(self):
        """测试 validate_task_model_selection 路由到格式语义验证并记录结果。"""
        svc = self._create_service(base_url="https://api.openai.com/v1", api_key="sk-format-auth-key")
        self.store.activate_direct_service(
            svc["id"],
            "word.format_review",
            task_model_selection={"serviceId": svc["id"], "modelName": "vision-model-1"},
        )
        client = ProviderClient(direct_service_store=self.store)
        called = {}

        def mock_validate(trace_id, task_auth):
            called["trace_id"] = trace_id
            called["task_auth"] = task_auth
            return {
                "success": True,
                "protocolVersion": "format_semantics.v1",
                "operations": {"classify_role": True},
                "correctionCount": 0,
                "visualCapability": {
                    "validated": False,
                    "mode": "contract_only",
                    "reason": "synthetic_image_files_omitted",
                },
            }

        client._validate_format_semantic_direct = mock_validate

        res = client.validate_task_model_selection(
            "word.format_review",
            {
                "serviceId": svc["id"],
                "modelName": "vision-model-1",
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            },
            trace_id="test-trace-1",
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["taskType"], "word.format_review")
        self.assertEqual(res["promptVersion"], "format_semantics.v1")
        self.assertEqual(res["formatSemanticValidation"]["protocolVersion"], "format_semantics.v1")
        self.assertEqual(called["trace_id"], "test-trace-1")
        self.assertEqual(called["task_auth"]["modelName"], "vision-model-1")
        self.assertEqual(called["task_auth"]["modelConfiguration"]["modelName"], "vision-model-1")

        # 检查验证结果已持久化并使 formatSemanticReadiness 就绪
        sel = self.store.get_task_model_selection("word.format_review")
        self.assertIsNotNone(sel["formatSemanticValidation"])
        self.assertFalse(sel["formatSemanticValidation"]["stale"])
        self.assertEqual(sel["formatSemanticReadiness"]["code"], "ready")


if __name__ == "__main__":
    unittest.main()
