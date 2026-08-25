import json
import unittest
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from app.core.config import AppSettings
from app.core.errors import AdapterError
from app.services.model_configurations import ACCESS_DIRECT_MODEL, ModelConfigurationStore
from app.services.model_configurations import ACCESS_WORKFLOW_PLATFORM
from app.services.provider_client import ProviderClient, get_last_provider_debug
from app.services.system_prompts import SystemPromptStore


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


class DirectModelProviderTests(unittest.TestCase):
    def test_system_prompt_manifest_exposes_all_eight_verified_tasks(self) -> None:
        metadata = SystemPromptStore().list_metadata()

        self.assertEqual(len(metadata), 8)
        self.assertEqual(
            {item["taskType"] for item in metadata},
            {
                "word.smart_write",
                "word.smart_imitation",
                "word.document_review",
                "word.format_review",
                "excel.analysis",
                "excel.formula_assistant",
                "ppt.slide_assistant",
                "ppt.structure_review",
            },
        )

    def _client(self, root: Path, context_window=40000):
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        store = ModelConfigurationStore(config_path, root / "provider_api_keys")
        configuration = store.create_configuration(
            "word.smart_write",
            "直连测试",
            ACCESS_DIRECT_MODEL,
            service_base_url="http://1.1.1.1:1111/one-api/v1",
            model_name="deepseek-v4-flash",
            temperature=0.2,
            max_output_tokens=1200 if context_window > 2000 else 100,
            context_window_tokens=context_window,
        )
        store.replace_api_key(configuration["id"], "direct-secret")
        store.activate_configuration(configuration["id"])
        return ProviderClient(
            AppSettings(timeout_seconds=75), model_configuration_store=store
        )

    def _workflow_format_client(self, root: Path):
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        store = ModelConfigurationStore(config_path, root / "provider_api_keys")
        configuration = store.create_configuration(
            "word.format_review",
            "格式语义工作流",
            ACCESS_WORKFLOW_PLATFORM,
            service_base_url="https://workflow.example/v1",
        )
        store.replace_api_key(configuration["id"], "workflow-secret")
        store.activate_configuration(configuration["id"])
        return ProviderClient(
            AppSettings(timeout_seconds=75), model_configuration_store=store
        ), store, configuration["id"]

    def _direct_format_client(self, root: Path):
        config_path = root / "adapter.json"
        config_path.write_text("{}\n", encoding="utf-8")
        store = ModelConfigurationStore(config_path, root / "provider_api_keys")
        configuration = store.create_configuration(
            "word.format_review",
            "格式语义直连",
            ACCESS_DIRECT_MODEL,
            service_base_url="https://format-model.example/v1",
            model_name="format-role-model",
            max_output_tokens=1024,
            context_window_tokens=40000,
        )
        store.replace_api_key(configuration["id"], "format-secret")
        return (
            ProviderClient(AppSettings(timeout_seconds=75), model_configuration_store=store),
            store,
            configuration["id"],
        )

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_uses_chat_completions_and_only_returns_final_content(
        self, urlopen
    ) -> None:
        urlopen.return_value = FakeResponse(
            {
                "id": "chatcmpl-1",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "内部推理不得显示",
                            "content": "<think>隐藏思考</think>最终结果",
                        }
                    }
                ],
            }
        )
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            result = client.post_task(
                "word.smart_write", "trace-direct", {}, "请改写这段文字"
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://1.1.1.1:1111/one-api/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer direct-secret")
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 1200)
        self.assertFalse(payload["stream"])
        self.assertEqual([item["role"] for item in payload["messages"]], ["system", "user"])
        self.assertEqual(result["answer"], "最终结果")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_format_semantics_caps_direct_output_and_input_budget(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"schemaVersion":"format_semantics.v1","operation":"classify_role","snapshotBinding":{},"items":[]}',
                        }
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            configuration = store.create_configuration(
                "word.format_review",
                "格式语义预算",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="format-role-model",
                max_output_tokens=8192,
                context_window_tokens=40000,
            )
            store.replace_api_key(configuration["id"], "format-secret")
            store.activate_configuration(configuration["id"])
            client = ProviderClient(
                AppSettings(timeout_seconds=75), model_configuration_store=store
            )
            client.format_semantics(
                "classify_role",
                "trace-format-budget",
                {},
                "只返回 JSON。",
                task_auth=client.resolve_task_auth("word.format_review"),
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["max_tokens"], 4096)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_format_semantics_resolves_known_model_output_capability(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"schemaVersion":"format_semantics.v1","operation":"classify_role","snapshotBinding":{},"items":[]}'
                        },
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            configuration = store.create_configuration(
                "word.format_review",
                "能力表直连",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="deepseek-v4-flash",
                max_output_tokens=None,
                context_window_tokens=40000,
            )
            store.replace_api_key(configuration["id"], "format-secret")
            store.activate_configuration(configuration["id"])
            client = ProviderClient(
                AppSettings(timeout_seconds=75), model_configuration_store=store
            )
            client.format_semantics(
                "classify_role",
                "trace-format-capability",
                {"candidate_json": "{}"},
                "只返回 JSON。",
                task_auth=client.resolve_task_auth("word.format_review"),
            )

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["max_tokens"], 4096)
        debug = get_last_provider_debug()
        capability = debug["validation"]["modelCapability"]
        self.assertEqual(capability["modelName"], "deepseek-v4-flash")
        self.assertEqual(capability["maxOutputTokens"], 384000)
        self.assertEqual(capability["tableVersion"], "2026-08-22")
        self.assertRegex(capability["tableSha256"], r"^[0-9a-f]{64}$")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_workflow_format_semantics_uses_fixed_inputs_and_result_json(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "answer": "这段自由文本不得被解析",
                "data": {
                    "outputs": {
                        "result_json": json.dumps(
                            {
                                "schemaVersion": "format_semantics.v1",
                                "operation": "classify_role",
                                "snapshotBinding": {},
                                "items": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                },
            }
        )
        with TemporaryDirectory() as tmp:
            client, _store, _configuration_id = self._workflow_format_client(Path(tmp))
            result = client.format_semantics(
                "classify_role",
                "trace-workflow-format",
                {"candidate_json": '{"candidates":[]}'},
                "不得读取这段提示词作为结果",
                task_auth=client.resolve_task_auth("word.format_review"),
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://workflow.example/v1/chat-messages")
        self.assertEqual(
            payload["inputs"],
            {
                "contract_version": "format_semantics.v1",
                "operation": "classify_role",
                "candidate_json": '{"candidates":[]}',
            },
        )
        self.assertNotIn("query", payload["inputs"])
        self.assertEqual(result["result_json"]["operation"], "classify_role")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_workflow_format_semantics_requires_result_json(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {"answer": '{"schemaVersion":"format_semantics.v1","items":[]}'}
        )
        with TemporaryDirectory() as tmp:
            client, _store, _configuration_id = self._workflow_format_client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.format_semantics(
                    "classify_role",
                    "trace-workflow-missing-result",
                    {"candidate_json": '{"candidates":[]}'},
                    "固定结果变量",
                    task_auth=client.resolve_task_auth("word.format_review"),
                )

        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_RESULT_JSON_MISSING")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_workflow_format_validation_runs_all_four_operations(self, urlopen) -> None:
        def response_for_request(req, timeout):
            del timeout
            request_payload = json.loads(req.data.decode("utf-8"))
            operation = request_payload["inputs"]["operation"]
            candidates = json.loads(request_payload["inputs"]["candidate_json"])["candidates"]
            block_id = next(iter(candidates))
            items = {
                "classify_role": [{"blockId": block_id, "role": "heading", "level": 1, "confidence": 0.9}],
                "associate_caption": [{"blockId": block_id, "targetBlockId": "figure-1", "status": "associated", "confidence": 0.9}],
                "suggest_table_caption": [{"blockId": block_id, "suggestion": "合成表格题注"}],
                "suggest_figure_caption": [{"blockId": block_id, "suggestion": "合成图题正文"}],
            }[operation]
            return FakeResponse({
                "data": {
                    "outputs": {
                        "result_json": json.dumps({
                            "schemaVersion": "format_semantics.v1",
                            "operation": operation,
                            "snapshotBinding": {
                                "contentSha256": "synthetic-content",
                                "structureSha256": "synthetic-structure",
                                "formatSha256": "synthetic-format",
                            },
                            "items": items,
                        })
                    }
                }
            })

        urlopen.side_effect = response_for_request
        with TemporaryDirectory() as tmp:
            client, _store, configuration_id = self._workflow_format_client(Path(tmp))
            result = client.validate_model_configuration(
                configuration_id, "trace-workflow-validation"
            )

        self.assertEqual(result["formatSemanticValidation"]["success"], True)
        self.assertEqual(
            result["formatSemanticValidation"]["operations"],
            {
                "classify_role": True,
                "associate_caption": True,
                "suggest_table_caption": True,
                "suggest_figure_caption": True,
            },
        )
        self.assertEqual(urlopen.call_count, 4)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_uses_formal_contract_and_exposes_identity(
        self, urlopen
    ) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "schemaVersion": "format_semantics.v1",
                                    "operation": "classify_role",
                                    "snapshotBinding": {
                                        "contentSha256": "synthetic-content",
                                        "structureSha256": "synthetic-structure",
                                        "formatSha256": "synthetic-format",
                                    },
                                    "items": [
                                        {
                                            "blockId": "synthetic-1",
                                            "role": "heading",
                                            "level": 1,
                                            "confidence": 0.95,
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            client, store, configuration_id = self._direct_format_client(Path(tmp))
            result = client.validate_model_configuration(
                configuration_id, "trace-direct-format-validation"
            )

        request = urlopen.call_args.args[0]
        request_text = request.data.decode("utf-8")
        payload = json.loads(request_text)
        user_content = payload["messages"][1]["content"]
        self.assertEqual(request.full_url, "https://format-model.example/v1/chat/completions")
        self.assertEqual(payload["model"], "format-role-model")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        semantic_schema = payload["response_format"]["json_schema"]["schema"]
        self.assertFalse(semantic_schema["additionalProperties"])
        self.assertEqual(
            semantic_schema["properties"]["schemaVersion"]["const"],
            "format_semantics.v1",
        )
        self.assertEqual(
            semantic_schema["properties"]["operation"]["const"],
            "classify_role",
        )
        self.assertEqual(
            set(semantic_schema["required"]),
            set(semantic_schema["properties"]),
        )
        role_item_schema = semantic_schema["properties"]["items"]["items"]
        self.assertEqual(
            set(role_item_schema["required"]),
            set(role_item_schema["properties"]),
        )
        attributes_schema = role_item_schema["properties"]["attributes"]
        self.assertEqual(
            set(attributes_schema["required"]),
            set(attributes_schema["properties"]),
        )
        self.assertIn("format_semantics.v1", user_content)
        self.assertIn("允许的响应字段", user_content)
        self.assertIn("snapshotBinding", user_content)
        self.assertIn("synthetic-1", user_content)
        self.assertNotIn("项目机密正文", request_text)
        self.assertNotIn("format-secret", request_text)
        self.assertEqual(
            result["formatSemanticValidation"]["operations"],
            {"classify_role": True},
        )
        self.assertEqual(result["configurationId"], configuration_id)
        self.assertEqual(result["configurationName"], "格式语义直连")
        self.assertEqual(result["configurationRevision"], 2)
        self.assertFalse(result["isCurrent"])
        self.assertEqual(result["currentConfigurationId"], "")
        self.assertEqual(store.list_for_task("word.format_review")["activeConfigurationId"], "")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_corrects_undeclared_fields_once(self, urlopen) -> None:
        binding = {
            "contentSha256": "synthetic-content",
            "structureSha256": "synthetic-structure",
            "formatSha256": "synthetic-format",
        }
        invalid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": binding,
            "items": [{
                "blockId": "synthetic-1",
                "role": "heading",
                "level": 1,
                "confidence": 0.95,
            }],
            "reason": "附加解释",
        }
        valid = dict(invalid)
        valid.pop("reason")
        urlopen.side_effect = [
            FakeResponse({"choices": [{"message": {"content": json.dumps(invalid)}}]}),
            FakeResponse({"choices": [{"message": {"content": json.dumps(valid)}}]}),
        ]

        with TemporaryDirectory() as tmp:
            client, _store, configuration_id = self._direct_format_client(Path(tmp))
            result = client.validate_model_configuration(
                configuration_id, "trace-direct-format-correction"
            )

        self.assertTrue(result["formatSemanticValidation"]["success"])
        self.assertEqual(urlopen.call_count, 2)
        second_payload = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertIn("纠正要求", second_payload["messages"][1]["content"])
        self.assertEqual(second_payload["response_format"]["type"], "json_schema")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_falls_back_when_schema_extension_is_unsupported(
        self, urlopen
    ) -> None:
        valid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": {
                "contentSha256": "synthetic-content",
                "structureSha256": "synthetic-structure",
                "formatSha256": "synthetic-format",
            },
            "items": [{
                "blockId": "synthetic-1",
                "role": "heading",
                "level": 1,
                "confidence": 0.95,
            }],
        }
        unsupported = HTTPError(
            "https://format-model.example/v1/chat/completions",
            400,
            "Bad Request",
            {},
            BytesIO(b'{"error":{"message":"response_format json_schema is not supported"}}'),
        )
        urlopen.side_effect = [
            unsupported,
            FakeResponse({
                "choices": [{"message": {"content": json.dumps(valid)}}]
            }),
        ]

        with TemporaryDirectory() as tmp:
            client, _store, configuration_id = self._direct_format_client(Path(tmp))
            result = client.validate_model_configuration(
                configuration_id, "trace-direct-format-schema-fallback"
            )

        self.assertTrue(result["formatSemanticValidation"]["success"])
        self.assertEqual(urlopen.call_count, 2)
        first_payload = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        second_payload = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertIn("response_format", first_payload)
        self.assertNotIn("response_format", second_payload)
        self.assertIn("允许的响应字段", second_payload["messages"][1]["content"])

    def _reject_json_schema_with_502(self, urlopen, valid_payload):
        def fake_urlopen(req, timeout=None):
            payload = json.loads(req.data.decode("utf-8"))
            if "response_format" in payload:
                raise HTTPError(
                    req.full_url,
                    502,
                    "Bad Gateway",
                    {},
                    BytesIO(b"<html>Bad Gateway</html>"),
                )
            return FakeResponse({
                "choices": [{"message": {"content": json.dumps(valid_payload)}}]
            })

        urlopen.side_effect = fake_urlopen

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_falls_back_when_schema_extension_returns_502(
        self, urlopen
    ) -> None:
        valid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": {
                "contentSha256": "synthetic-content",
                "structureSha256": "synthetic-structure",
                "formatSha256": "synthetic-format",
            },
            "items": [{
                "blockId": "synthetic-1",
                "role": "heading",
                "level": 1,
                "confidence": 0.95,
            }],
        }
        self._reject_json_schema_with_502(urlopen, valid)

        with TemporaryDirectory() as tmp:
            client, _store, configuration_id = self._direct_format_client(Path(tmp))
            result = client.validate_model_configuration(
                configuration_id, "trace-direct-format-schema-502"
            )

        self.assertTrue(result["formatSemanticValidation"]["success"])
        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertGreaterEqual(len(payloads), 2)
        self.assertTrue(any("response_format" in payload for payload in payloads))
        self.assertTrue(any("response_format" not in payload for payload in payloads))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_falls_back_when_cleared_advanced_options_still_502(
        self, urlopen
    ) -> None:
        valid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": {
                "contentSha256": "synthetic-content",
                "structureSha256": "synthetic-structure",
                "formatSha256": "synthetic-format",
            },
            "items": [{
                "blockId": "synthetic-1",
                "role": "heading",
                "level": 1,
                "confidence": 0.95,
            }],
        }
        self._reject_json_schema_with_502(urlopen, valid)

        with TemporaryDirectory() as tmp:
            client, store, configuration_id = self._direct_format_client(Path(tmp))
            store.update_configuration(
                configuration_id,
                name="格式语义直连",
                access_method=ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="glm-5.2",
                temperature=None,
                max_output_tokens=None,
                context_window_tokens=40000,
            )
            result = client.validate_model_configuration(
                configuration_id, "trace-direct-format-cleared-advanced"
            )

        self.assertTrue(result["formatSemanticValidation"]["success"])
        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in urlopen.call_args_list
        ]
        self.assertTrue(all("temperature" not in payload for payload in payloads))
        self.assertTrue(any("response_format" in payload for payload in payloads))
        self.assertTrue(any("response_format" not in payload for payload in payloads))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_reports_field_after_one_failed_correction(
        self, urlopen
    ) -> None:
        invalid = {
            "schemaVersion": "format_semantics.v1",
            "operation": "classify_role",
            "snapshotBinding": {
                "contentSha256": "synthetic-content",
                "structureSha256": "synthetic-structure",
                "formatSha256": "synthetic-format",
            },
            "items": [{
                "blockId": "synthetic-1",
                "role": "heading",
                "level": 1,
                "confidence": 0.95,
                "analysis": "不得泄露的解释",
            }],
        }
        response = FakeResponse({
            "choices": [{"message": {"content": json.dumps(invalid, ensure_ascii=False)}}]
        })
        urlopen.side_effect = [response, response]

        with TemporaryDirectory() as tmp:
            client, _store, configuration_id = self._direct_format_client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.validate_model_configuration(
                    configuration_id, "trace-direct-format-correction-failed"
                )

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(raised.exception.code, "FORMAT_SEMANTIC_RESPONSE_INVALID")
        self.assertEqual(
            raised.exception.message,
            "模型返回了协议未定义的字段：items[0].analysis。",
        )
        self.assertNotIn("不得泄露的解释", raised.exception.message)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_format_validation_rejects_legacy_and_invalid_contract_responses(
        self, urlopen
    ) -> None:
        invalid_responses = [
            (
                "legacy-array",
                [{"paragraphIndex": 1, "role": "body", "confidence": 0.9}],
                "FORMAT_SEMANTIC_RESPONSE_INVALID",
            ),
            (
                "wrong-schema",
                {
                    "schemaVersion": "format_semantics.v0",
                    "operation": "classify_role",
                    "snapshotBinding": {
                        "contentSha256": "synthetic-content",
                        "structureSha256": "synthetic-structure",
                        "formatSha256": "synthetic-format",
                    },
                    "items": [],
                },
                "FORMAT_SEMANTIC_RESPONSE_INVALID",
            ),
            (
                "wrong-operation",
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": "associate_caption",
                    "snapshotBinding": {
                        "contentSha256": "synthetic-content",
                        "structureSha256": "synthetic-structure",
                        "formatSha256": "synthetic-format",
                    },
                    "items": [],
                },
                "FORMAT_SEMANTIC_RESPONSE_INVALID",
            ),
            (
                "wrong-binding",
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": "classify_role",
                    "snapshotBinding": {
                        "contentSha256": "other-content",
                        "structureSha256": "synthetic-structure",
                        "formatSha256": "synthetic-format",
                    },
                    "items": [],
                },
                "FORMAT_SEMANTIC_BINDING_INVALID",
            ),
            (
                "out-of-range-block",
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": "classify_role",
                    "snapshotBinding": {
                        "contentSha256": "synthetic-content",
                        "structureSha256": "synthetic-structure",
                        "formatSha256": "synthetic-format",
                    },
                    "items": [
                        {
                            "blockId": "not-requested",
                            "role": "heading",
                            "level": 1,
                            "confidence": 0.95,
                        }
                    ],
                },
                "FORMAT_SEMANTIC_CANDIDATE_OUT_OF_RANGE",
            ),
            (
                "missing-result-item",
                {
                    "schemaVersion": "format_semantics.v1",
                    "operation": "classify_role",
                    "snapshotBinding": {
                        "contentSha256": "synthetic-content",
                        "structureSha256": "synthetic-structure",
                        "formatSha256": "synthetic-format",
                    },
                    "items": [],
                },
                "FORMAT_SEMANTIC_RESPONSE_INCOMPLETE",
            ),
        ]
        for name, response_payload, expected_code in invalid_responses:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                urlopen.return_value = FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(response_payload, ensure_ascii=False),
                                }
                            }
                        ]
                    }
                )
                client, _store, configuration_id = self._direct_format_client(Path(tmp))
                with self.assertRaises(AdapterError) as raised:
                    client.validate_model_configuration(
                        configuration_id, "trace-direct-format-{0}".format(name)
                    )
                self.assertEqual(raised.exception.code, expected_code)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_format_semantics_rejects_invalid_operation_and_over_budget_prompt(self, urlopen) -> None:
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            auth = client.resolve_task_auth("word.smart_write")
            with self.assertRaises(AdapterError) as invalid_operation:
                client.format_semantics(
                    "rewrite_document",
                    "trace-format-invalid-operation",
                    {},
                    "只返回 JSON。",
                    task_auth=auth,
                )
            with self.assertRaises(AdapterError) as over_budget:
                client.format_semantics(
                    "classify_role",
                    "trace-format-over-budget",
                    {},
                    "x" * 8200,
                    task_auth=auth,
                )

        self.assertEqual(invalid_operation.exception.code, "FORMAT_SEMANTIC_OPERATION_NOT_ALLOWED")
        self.assertEqual(over_budget.exception.code, "FORMAT_SEMANTIC_INPUT_OVER_BUDGET")
        urlopen.assert_not_called()

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_rejects_reasoning_only_response(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 1200,
                    "total_tokens": 1320,
                },
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "reasoning_content": "只有推理",
                            "content": "<think>思考",
                        },
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.post_task("word.smart_write", "trace-no-final", {}, "改写")
        self.assertEqual(raised.exception.code, "MODEL_FINAL_CONTENT_TOKEN_LIMIT")
        debug = get_last_provider_debug()
        self.assertEqual(debug["response"]["finishReason"], "length")
        self.assertEqual(debug["response"]["contentType"], "string")
        self.assertTrue(debug["response"]["reasoningContentPresent"])
        self.assertEqual(debug["response"]["usage"]["completionTokens"], 1200)
        self.assertNotIn("只有推理", json.dumps(debug, ensure_ascii=False))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_redacts_unrecognized_finish_reason(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "secret-fragment\ncontrol",
                        "message": {"content": None},
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.post_task("word.smart_write", "trace-redacted-finish", {}, "改写")
        self.assertEqual(raised.exception.code, "MODEL_FINAL_CONTENT_MISSING")
        debug = get_last_provider_debug()
        self.assertEqual(debug["response"]["finishReason"], "other")
        self.assertNotIn("secret-fragment", json.dumps(debug, ensure_ascii=False))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_maps_mid_stream_disconnect_to_retryable_error(
        self, urlopen
    ) -> None:
        urlopen.side_effect = IncompleteRead(b"{\"choices\": [")
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.post_task("word.smart_write", "trace-disconnect", {}, "改写")
        self.assertEqual(raised.exception.code, "PROVIDER_MID_STREAM_DISCONNECT")
        self.assertEqual(raised.exception.status_code, 502)

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_rejects_over_budget_before_network(self, urlopen) -> None:
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp), context_window=1000)
            with self.assertRaises(AdapterError) as raised:
                client.post_task(
                    "word.smart_write", "trace-budget", {}, "长文本" * 1000
                )
        self.assertEqual(raised.exception.code, "MODEL_INPUT_OVER_BUDGET")
        urlopen.assert_not_called()

    def test_runtime_with_model_store_never_falls_back_to_global_url_or_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(config_path, root / "provider_api_keys")
            client = ProviderClient(
                AppSettings(provider_base_url="https://legacy.example/v1"),
                model_configuration_store=store,
            )

            auth = client.resolve_task_auth("word.smart_write")

            self.assertEqual(auth["providerBaseUrl"], "")
            self.assertEqual(auth["apiKey"], "")
            self.assertFalse(client.is_task_configured("word.smart_write"))

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_full_document_review_uses_versioned_strict_json_contract(
        self, urlopen
    ) -> None:
        strict_answer = json.dumps(
            {
                "schemaVersion": "word.document_review.full.chunk.v1",
                "chunkId": "chunk-1",
                "summary": "未发现问题。",
                "enumerationStatus": "complete",
                "issues": [],
            },
            ensure_ascii=False,
        )
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": strict_answer}}
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "adapter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            store = ModelConfigurationStore(
                config_path, root / "provider_api_keys"
            )
            configuration = store.create_configuration(
                "word.document_review",
                "全篇审查直连",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://model.example/v1",
                model_name="review-model",
                max_output_tokens=2048,
                context_window_tokens=40000,
            )
            store.replace_api_key(configuration["id"], "direct-secret")
            store.activate_configuration(configuration["id"])
            client = ProviderClient(
                AppSettings(timeout_seconds=75), model_configuration_store=store
            )
            auth = client.resolve_task_auth("word.document_review")

            answer = client.full_document_review_chunk(
                "系统应尽快完成联调。",
                "trace-full-review",
                "chunk-1",
                "technical_solution",
                "重点检查可验收性。",
                auth,
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(answer, strict_answer)
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"][
                "properties"
            ]["schemaVersion"]["const"],
            "word.document_review.full.chunk.v2",
        )
        self.assertIn("单分片全篇审查", payload["messages"][0]["content"])
        self.assertNotIn("系统应尽快完成联调", payload["messages"][0]["content"])
        self.assertEqual(
            get_last_provider_debug()["taskType"], "word.document_review.full"
        )


if __name__ == "__main__":
    unittest.main()
