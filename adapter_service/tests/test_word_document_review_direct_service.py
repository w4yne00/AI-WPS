import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_PROVIDER_API = HAS_PYDANTIC and importlib.util.find_spec("fastapi") is not None
if HAS_PYDANTIC:
    from pydantic import ValidationError
    from app.services.provider_client import ProviderClient
    from app.services.word.full_document_review import FullDocumentReviewService
if HAS_PROVIDER_API:
    from app.api.provider import TaskModelSelectionUpdateRequest

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

    def _seed_legacy_direct_configuration(
        self,
        configuration_id,
        api_key_ref,
        api_key,
        *,
        active=False,
        service_base_url="https://api.openai.com/v1",
        model_name="gpt-4o",
        temperature=0.2,
        max_output_tokens=4096,
        context_window_tokens=64000,
    ):
        payload = (
            json.loads(self.config_path.read_text(encoding="utf-8"))
            if self.config_path.exists()
            else {}
        )
        configurations = payload.setdefault("modelConfigurations", {})
        configurations[configuration_id] = {
            "id": configuration_id,
            "host": "word",
            "taskType": "word.document_review",
            "name": "旧文档审查直连",
            "note": "迁移保留",
            "accessMethod": ACCESS_DIRECT_MODEL,
            "serviceBaseUrl": service_base_url,
            "modelName": model_name,
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "contextWindowTokens": context_window_tokens,
            "apiKeyRef": api_key_ref,
            "configVersion": 3,
        }
        if active:
            payload.setdefault("activeModelConfigurations", {})[
                "word.document_review"
            ] = configuration_id
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")
        self.key_dir.mkdir(parents=True, exist_ok=True)
        (self.key_dir / api_key_ref).write_text(api_key + "\n", encoding="utf-8")

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

    @unittest.skipUnless(HAS_PROVIDER_API, "fastapi and pydantic are required for API validation tests")
    def test_task_model_selection_api_accepts_unlimited_and_unbounded_token_values(self):
        valid = TaskModelSelectionUpdateRequest.parse_obj(
            {"maxOutputTokens": 16384, "contextWindowTokens": 2000000}
        )
        self.assertEqual(valid.max_output_tokens, 16384)
        self.assertEqual(valid.context_window_tokens, 2000000)

        for field, value in (
            ("maxOutputTokens", 0),
            ("maxOutputTokens", 200000),
            ("contextWindowTokens", 0),
            ("contextWindowTokens", 4000000),
        ):
            with self.subTest(field=field, value=value):
                parsed = TaskModelSelectionUpdateRequest.parse_obj({field: value})
                self.assertEqual(
                    parsed.max_output_tokens if field == "maxOutputTokens" else parsed.context_window_tokens,
                    value,
                )
        for field in ("maxOutputTokens", "contextWindowTokens"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    TaskModelSelectionUpdateRequest.parse_obj({field: -1})
        with self.assertRaises(ValidationError):
            TaskModelSelectionUpdateRequest.parse_obj(
                {"maxOutputTokens": 2048, "contextWindowTokens": 1000}
            )

    def test_task_model_selection_store_normalizes_unlimited_and_rejects_invalid_token_budget(self):
        svc = self._create_service()
        unlimited = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=0,
            context_window_tokens=0,
        )
        self.assertIsNone(unlimited["maxOutputTokens"])
        self.assertIsNone(unlimited["contextWindowTokens"])

        large = self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=200000,
            context_window_tokens=4000000,
        )
        self.assertEqual(large["maxOutputTokens"], 200000)
        self.assertEqual(large["contextWindowTokens"], 4000000)

        invalid_inputs = (
            {"max_output_tokens": -1},
            {"context_window_tokens": -1},
            {"max_output_tokens": 2048, "context_window_tokens": 1000},
        )
        for values in invalid_inputs:
            with self.subTest(values=values):
                with self.assertRaises(DirectServiceError):
                    self.store.update_task_model_selection(
                        "word.document_review", service_id=svc["id"], **values
                    )

    def test_full_review_readiness_rejects_persisted_negative_input_budget(self):
        svc = self._create_service()
        self.store.update_task_model_selection(
            "word.document_review",
            service_id=svc["id"],
            max_output_tokens=2048,
            context_window_tokens=64000,
        )
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        selection = payload["taskModelSelections"]["word.document_review"]
        selection["contextWindowTokens"] = 1000
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")

        stored = self.store.get_task_model_selection("word.document_review")
        self.assertFalse(stored["fullDocumentReviewReady"])
        self.assertEqual(
            stored["fullDocumentReviewReadiness"]["code"],
            "token_budget_invalid",
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

    def test_resolved_direct_selection_is_atomic_during_service_switch(self):
        service_a = self._create_service(
            name="服务 A", default_model="gpt-4o", api_key="sk-service-a"
        )
        service_b = self._create_service(
            name="服务 B", default_model="gpt-4o-mini", api_key="sk-service-b"
        )
        self.store.activate_direct_service(
            service_a["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": service_a["id"],
                "modelName": "gpt-4o",
            },
        )
        resolver = getattr(self.store, "resolve_active_task_selection", None)
        if resolver is None:
            self.fail("DirectServiceStore must provide one atomic resolved-selection read")

        snapshot_started = threading.Event()
        release_snapshot = threading.Event()
        switch_finished = threading.Event()
        original_get_service = self.store.get_service
        resolved = {}
        failures = []

        def blocking_get_service(service_id, include_secret=False):
            result = original_get_service(service_id, include_secret=include_secret)
            if service_id == service_a["id"] and threading.current_thread().name == "selection-reader":
                snapshot_started.set()
                release_snapshot.wait(timeout=2)
            return result

        def read_snapshot():
            try:
                resolved.update(
                    resolver("word.document_review", include_secret=True) or {}
                )
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        def switch_service():
            try:
                self.store.activate_direct_service(
                    service_b["id"],
                    "word.document_review",
                    task_model_selection={
                        "serviceId": service_b["id"],
                        "modelName": "gpt-4o-mini",
                    },
                )
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)
            finally:
                switch_finished.set()

        self.store.get_service = blocking_get_service
        reader = threading.Thread(target=read_snapshot, name="selection-reader")
        switcher = threading.Thread(target=switch_service, name="selection-switcher")
        try:
            reader.start()
            self.assertTrue(snapshot_started.wait(timeout=1))
            switcher.start()
            self.assertFalse(
                switch_finished.wait(timeout=0.05),
                "activation must wait until the resolved snapshot releases the store lock",
            )
            release_snapshot.set()
            reader.join(timeout=2)
            switcher.join(timeout=2)
        finally:
            self.store.get_service = original_get_service
            release_snapshot.set()

        self.assertEqual(failures, [])
        self.assertEqual(resolved["activeServiceId"], service_a["id"])
        self.assertEqual(resolved["directService"]["id"], service_a["id"])
        self.assertEqual(
            resolved["taskModelSelection"]["serviceId"], service_a["id"]
        )

        current = resolver("word.document_review", include_secret=True)
        self.assertEqual(current["activeServiceId"], service_b["id"])
        self.assertEqual(current["directService"]["id"], service_b["id"])
        self.assertEqual(
            current["taskModelSelection"]["serviceId"], service_b["id"]
        )

    def test_resolved_direct_selection_rejects_mismatched_active_service(self):
        service_a = self._create_service(name="一致性服务 A", api_key="sk-consistent-a")
        service_b = self._create_service(name="一致性服务 B", api_key="sk-consistent-b")
        self.store.activate_direct_service(
            service_a["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": service_a["id"],
                "modelName": "gpt-4o",
            },
        )
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["taskModelSelections"]["word.document_review"]["serviceId"] = service_b["id"]
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

        resolver = getattr(self.store, "resolve_active_task_selection", None)
        if resolver is None:
            self.fail("DirectServiceStore must provide one atomic resolved-selection read")
        with self.assertRaises(DirectServiceError) as ctx:
            resolver("word.document_review", include_secret=True)
        self.assertEqual(ctx.exception.code, "DIRECT_SERVICE_SELECTION_MISMATCH")

    @unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for ProviderClient tests")
    def test_resolve_task_auth_uses_atomic_store_snapshot(self):
        service = self._create_service()
        self.store.activate_direct_service(
            service["id"],
            "word.document_review",
            task_model_selection={
                "serviceId": service["id"],
                "modelName": "gpt-4o",
                "maxOutputTokens": 4096,
                "contextWindowTokens": 64000,
            },
        )
        snapshot = {
            "activeServiceId": service["id"],
            "directService": service,
            "taskModelSelection": self.store.get_task_model_selection(
                "word.document_review"
            ),
        }

        self.store.resolve_active_task_selection = (
            lambda task_type, include_secret=False: snapshot
        )

        def forbid_split_read(*_args, **_kwargs):
            raise AssertionError("provider must not split the resolved selection read")

        self.store.get_service = forbid_split_read
        self.store.get_task_model_selection = forbid_split_read

        task_auth = ProviderClient(
            direct_service_store=self.store
        ).resolve_task_auth("word.document_review")

        self.assertEqual(task_auth["directService"]["id"], service["id"])
        self.assertEqual(
            task_auth["taskModelSelection"]["serviceId"], service["id"]
        )

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
        svc = self.store.replace_api_key(
            svc["id"],
            "sk-doc-review-auth-rotated",
            expected_revision=svc["revision"],
        )
        client = ProviderClient(direct_service_store=self.store)

        called = {}

        class StreamingResponse:
            headers = {"Content-Type": "text/event-stream"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                content = '{"summary":"审查完成","issues":[]}'
                event = json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {"content": content},
                                "finish_reason": "stop",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                yield ("data: " + event + "\n\n").encode("utf-8")

        def streaming_response(request, timeout=None):
            payload = json.loads(request.data.decode("utf-8"))
            called["model"] = payload["model"]
            called["query"] = payload["messages"][1]["content"]
            called["stream"] = payload["stream"]
            return StreamingResponse()

        with patch("urllib.request.urlopen", side_effect=streaming_response):
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
        self.assertEqual(res["streamingCapability"], "validated")
        self.assertEqual(called["model"], "custom-doc-model")
        self.assertTrue(called["stream"])
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

    def test_legacy_direct_configurations_migrate_by_endpoint_and_key(self):
        """ADR-0130：相同 endpoint + key 合并，参数保留，验证成功后清理旧 key。"""
        svc = self._create_service(api_key="sk-shared-migration")
        self._seed_legacy_direct_configuration(
            "legacy_doc_a", "legacy_doc_key_a", "sk-shared-migration"
        )
        self._seed_legacy_direct_configuration(
            "legacy_doc_b",
            "legacy_doc_key_b",
            "sk-shared-migration",
            active=True,
            temperature=0.35,
            max_output_tokens=4096,
            context_window_tokens=96000,
        )

        migrated = self.store.list_services()
        self.assertEqual(migrated["directServiceCount"], 1)
        self.assertEqual(migrated["legacyDirectMigration"]["status"], "pending_manual")
        self.assertEqual(
            migrated["legacyDirectMigration"]["code"],
            "DIRECT_SERVICE_MIGRATION_PENDING_PROFILES",
        )
        selection = self.store.get_task_model_selection("word.document_review")
        self.assertEqual(selection["serviceId"], svc["id"])
        self.assertEqual(selection["temperature"], 0.35)
        self.assertEqual(selection["maxOutputTokens"], 4096)
        self.assertEqual(selection["contextWindowTokens"], 96000)
        self.assertTrue(selection["limitedReviewReady"])
        self.assertTrue(selection["fullDocumentReviewReady"])

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_doc_a", payload.get("legacyDirectPending", {}))
        self.assertNotIn("legacy_doc_a", payload.get("modelConfigurations", {}))
        self.assertNotIn("legacy_doc_b", payload.get("modelConfigurations", {}))
        self.assertTrue((self.key_dir / "legacy_doc_key_a").exists())
        self.assertFalse((self.key_dir / "legacy_doc_key_b").exists())

    def test_legacy_direct_migration_over_capacity_preserves_original_data(self):
        for index in range(5):
            self.store.create_service(
                name=f"现有服务 {index}",
                service_base_url=f"https://existing-{index}.example.com/v1",
            )
        self._seed_legacy_direct_configuration(
            "legacy_doc_over_limit",
            "legacy_doc_over_limit_key",
            "sk-over-limit",
            active=True,
            service_base_url="https://sixth.example.com/v1",
        )

        result = self.store.list_services()
        self.assertEqual(result["directServiceCount"], 5)
        self.assertEqual(result["legacyDirectMigration"]["status"], "restricted")
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("legacy_doc_over_limit", payload["modelConfigurations"])
        self.assertEqual(
            payload["activeModelConfigurations"]["word.document_review"],
            "legacy_doc_over_limit",
        )
        self.assertTrue((self.key_dir / "legacy_doc_over_limit_key").exists())

    def test_legacy_direct_migration_preserves_but_does_not_activate_invalid_budget(self):
        self._seed_legacy_direct_configuration(
            "legacy_doc_invalid_budget",
            "legacy_doc_invalid_budget_key",
            "sk-invalid-budget",
            active=True,
            max_output_tokens=2048,
            context_window_tokens=1000,
        )

        result = self.store.list_services()
        self.assertEqual(result["legacyDirectMigration"]["status"], "completed")
        selection = self.store.get_task_model_selection("word.document_review")
        self.assertEqual(selection["maxOutputTokens"], 2048)
        self.assertEqual(selection["contextWindowTokens"], 1000)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "word.document_review", payload.get("activeModelConfigurations", {})
        )


if __name__ == "__main__":
    unittest.main()
