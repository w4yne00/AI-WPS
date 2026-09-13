import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
if HAS_PYDANTIC:
    from app.services.provider_client import ProviderClient
    from app.services.word.full_document_review import FullDocumentReviewService

from app.services.model_configurations import (
    ACCESS_DIRECT_MODEL,
    ACCESS_WORKFLOW_PLATFORM,
)
from app.services.direct_services import (
    DirectServiceError,
    DirectServiceStore,
)


class WordDocumentReviewDirectServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "adapter.json"
        self.key_dir = Path(self.tmp.name) / "keys"
        self.store = DirectServiceStore(self.config_path, self.key_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_service(
        self,
        name="文档审查模型直连服务",
        default_model="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key="sk-doc-review-secret",
    ):
        svc = self.store.create_service(
            name=name,
            service_base_url=base_url,
            default_model=default_model,
        )
        self.store.replace_api_key(
            svc["id"], api_key, expected_revision=svc["revision"]
        )
        self.store.update_model_list(
            svc["id"],
            ["gpt-4o", "gpt-4o-mini", "review-model-custom"],
            expected_revision=svc["revision"] + 1,
        )
        return self.store.get_service(svc["id"], include_secret=True)

    def test_document_review_selection_defaults_and_model_inheritance(self):
        """测试文档审查选择直连服务时，默认继承服务模型，host 为 word。"""
        svc = self._create_service()
        selection = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
        )
        self.assertEqual(selection["taskType"], "word.document_review")
        self.assertEqual(selection["serviceId"], svc["id"])
        self.assertEqual(selection["modelName"], "")
        self.assertEqual(selection["effectiveModel"], "gpt-4o")
        self.assertEqual(selection["host"], "word")
        self.assertIn("limitedReviewReady", selection)
        self.assertIn("fullDocumentReviewReady", selection)
        self.assertIn("fullDocumentReviewReadiness", selection)

    def test_document_review_selection_custom_parameters(self):
        """测试文档审查覆盖模型名称与 Token/温度参数。"""
        svc = self._create_service()
        selection = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            model_name="review-model-custom",
            temperature=0.2,
            max_output_tokens=4096,
            context_window_tokens=128000,
        )
        self.assertEqual(selection["modelName"], "review-model-custom")
        self.assertEqual(selection["effectiveModel"], "review-model-custom")
        self.assertEqual(selection["temperature"], 0.2)
        self.assertEqual(selection["maxOutputTokens"], 4096)
        self.assertEqual(selection["contextWindowTokens"], 128000)
        self.assertTrue(selection["contextWindowTokensExplicit"])
        self.assertTrue(selection["limitedReviewReady"])
        self.assertTrue(selection["fullDocumentReviewReady"])
        self.assertEqual(selection["fullDocumentReviewReadiness"]["code"], "ready")

    def test_document_review_full_review_readiness_gates(self):
        """测试全篇审查就绪度门禁规则（显式容量、显式输出Token、Token>=2048、配置完整性）。"""
        svc = self._create_service()

        # 1. 默认选择：maxOutputTokens 与 contextWindowTokens 均为 None -> 显式输出 Token 缺失
        sel1 = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
        )
        self.assertTrue(sel1["limitedReviewReady"])
        self.assertFalse(sel1["fullDocumentReviewReady"])
        self.assertEqual(
            sel1["fullDocumentReviewReadiness"]["code"],
            "explicit_output_tokens_required",
        )

        # 2. 设置了 maxOutputTokens 但未显式设置 contextWindowTokens -> 显式上下文容量缺失
        sel2 = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=4096,
        )
        self.assertTrue(sel2["limitedReviewReady"])
        self.assertFalse(sel2["fullDocumentReviewReady"])
        self.assertEqual(
            sel2["fullDocumentReviewReadiness"]["code"],
            "explicit_context_tokens_required",
        )

        # 3. 设置了 contextWindowTokens 但 maxOutputTokens < 2048 -> 输出 Token 太小
        sel3 = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=1024,
            context_window_tokens=64000,
        )
        self.assertTrue(sel3["limitedReviewReady"])
        self.assertFalse(sel3["fullDocumentReviewReady"])
        self.assertEqual(
            sel3["fullDocumentReviewReadiness"]["code"],
            "output_tokens_too_small",
        )

        # 4. 全部显式且 maxOutputTokens >= 2048 -> ready
        sel4 = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=2048,
            context_window_tokens=64000,
        )
        self.assertTrue(sel4["limitedReviewReady"])
        self.assertTrue(sel4["fullDocumentReviewReady"])
        self.assertEqual(
            sel4["fullDocumentReviewReadiness"]["code"],
            "ready",
        )

        # 5. 清除 API Key -> configuration_incomplete
        self.store.clear_api_key(svc["id"], expected_revision=svc["revision"])
        sel5 = self.store.get_task_model_selection("word.document_review")
        self.assertFalse(sel5["limitedReviewReady"])
        self.assertFalse(sel5["fullDocumentReviewReady"])
        self.assertEqual(
            sel5["fullDocumentReviewReadiness"]["code"],
            "configuration_incomplete",
        )

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for ProviderClient tests")
    def test_resolve_task_auth_for_document_review_direct_service(self):
        """测试 resolve_task_auth 在文档审查激活直连服务时，正确组装 modelConfiguration 与 serviceName。"""
        svc = self._create_service(
            base_url="https://api.openai.com/v1", api_key="sk-doc-review-auth"
        )
        self.store.activate_direct_service(
            svc["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": svc["id"],
                "modelName": "gpt-4o",
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "contextWindowTokens": 64000,
            },
        )
        client = ProviderClient(direct_service_store=self.store)
        task_auth = client.resolve_task_auth("word.document_review")

        self.assertEqual(task_auth["accessMethod"], ACCESS_DIRECT_MODEL)
        self.assertEqual(task_auth["providerBaseUrl"], "https://api.openai.com/v1")
        self.assertEqual(task_auth["apiKey"], "sk-doc-review-auth")
        self.assertEqual(task_auth["modelName"], "gpt-4o")
        self.assertEqual(task_auth["maxOutputTokens"], 4096)
        self.assertEqual(task_auth["contextWindowTokens"], 64000)
        self.assertTrue(task_auth["contextWindowTokensExplicit"])
        self.assertEqual(task_auth["serviceName"], svc["name"])

        # 校验 modelConfiguration 字典完整度，供 FullDocumentReviewService 冻结快照使用
        config = task_auth.get("modelConfiguration")
        self.assertIsInstance(config, dict)
        self.assertEqual(config["id"], svc["id"])
        self.assertEqual(config["taskType"], "word.document_review")
        self.assertEqual(config["accessMethod"], ACCESS_DIRECT_MODEL)
        self.assertEqual(config["modelName"], "gpt-4o")
        self.assertEqual(config["maxOutputTokens"], 4096)
        self.assertEqual(config["contextWindowTokens"], 64000)
        self.assertTrue(config["contextWindowTokensExplicit"])
        self.assertEqual(config["configVersion"], svc["revision"])

    def test_direct_service_delete_protection_includes_document_review(self):
        """测试被 word.document_review 引用的直连服务禁止删除并披露引用。"""
        svc = self._create_service()
        self.store.activate_direct_service(
            svc["id"],
            "word.document_review",
            task_model_selection={"serviceId": svc["id"]},
        )
        with self.assertRaises(DirectServiceError) as ctx:
            self.store.delete_service(svc["id"], expected_revision=svc["revision"])
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_IN_USE")
        sanitized = self.store.get_service(svc["id"])
        self.assertIn("word.document_review", sanitized.get("referencedTasks", []))

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for ProviderClient tests")
    def test_validate_task_model_selection_for_document_review_custom_model(self):
        """测试 validate_task_model_selection 使用 probe 验证文档审查自定义模型。"""
        svc = self._create_service(
            base_url="https://api.openai.com/v1", api_key="sk-doc-review-auth"
        )
        self.store.activate_direct_service(
            svc["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": svc["id"],
                "modelName": "custom-doc-model",
                "customModel": True,
            },
        )
        client = ProviderClient(direct_service_store=self.store)

        called = {}

        def mock_post_task(task_type, trace_id, input_data, query, **kwargs):
            called["task_type"] = task_type
            called["trace_id"] = trace_id
            called["query"] = query
            called["task_auth"] = kwargs.get("task_auth")
            return {
                "answer": '{"summary":"审查完成","issues":[]}',
                "conversation_id": "conv-test",
            }

        client.post_task = mock_post_task

        res = client.validate_task_model_selection(
            "word.document_review",
            {
                "serviceId": svc["id"],
                "modelName": "custom-doc-model",
                "customModel": True,
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "contextWindowTokens": 40000,
            },
            trace_id="trace-validate-doc",
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["taskType"], "word.document_review")
        self.assertEqual(res["modelName"], "custom-doc-model")
        self.assertTrue(res["customModel"])
        self.assertTrue(res["customModelValidated"])
        self.assertEqual(called["task_type"], "word.document_review")
        self.assertIn("请审查", called["query"])

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for FullDocumentReviewService tests")
    def test_full_document_review_auth_identity_freezes_service_and_key_fingerprint(self):
        """测试全篇审查快照 authIdentity 冻结直连服务 revision 与 API Key 指纹。"""
        svc = self._create_service(api_key="sk-full-freeze-test-key")
        self.store.activate_direct_service(
            svc["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": svc["id"],
                "modelName": "gpt-4o",
                "temperature": 0.2,
                "maxOutputTokens": 4096,
                "contextWindowTokens": 64000,
            },
        )
        client = ProviderClient(direct_service_store=self.store)
        task_auth = client.resolve_task_auth("word.document_review")

        auth_id = FullDocumentReviewService._auth_identity(task_auth)
        self.assertEqual(auth_id["apiKeyRef"], svc["id"])
        self.assertTrue(bool(auth_id["keyFingerprint"]))
        self.assertEqual(
            auth_id["configuration"]["modelConfigurationVersion"],
            svc["revision"],
        )
        self.assertEqual(
            auth_id["configuration"]["maxOutputTokens"],
            4096,
        )
        self.assertEqual(
            auth_id["configuration"]["contextWindowTokens"],
            64000,
        )

    def test_configuration_migration_regression(self):
        """测试配置迁移回归：未激活直连时保持工作流平台配置回退，激活直连后切换。"""
        svc = self._create_service()

        # 初始未激活直连
        sel = self.store.get_task_model_selection("word.document_review")
        self.assertEqual(sel["serviceId"], "")

        if HAS_PYDANTIC:
            client = ProviderClient(direct_service_store=self.store)
            # 无任何配置时为 False
            self.assertFalse(client.is_task_configured("word.document_review"))

        # 激活直连
        self.store.activate_direct_service(
            svc["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": svc["id"],
                "modelName": "gpt-4o",
                "maxOutputTokens": 2048,
                "contextWindowTokens": 32000,
            },
        )
        activated_sel = self.store.get_task_model_selection("word.document_review")
        self.assertEqual(activated_sel["serviceId"], svc["id"])
        self.assertTrue(activated_sel["fullDocumentReviewReady"])

        if HAS_PYDANTIC:
            client = ProviderClient(direct_service_store=self.store)
            task_auth = client.resolve_task_auth("word.document_review")
            self.assertEqual(task_auth["accessMethod"], ACCESS_DIRECT_MODEL)
            self.assertEqual(task_auth["modelName"], "gpt-4o")


if __name__ == "__main__":
    unittest.main()
