import json
import unittest
from http.client import IncompleteRead
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.config import AppSettings
from app.core.errors import AdapterError
from app.services.model_configurations import ACCESS_DIRECT_MODEL, ModelConfigurationStore
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
    def test_format_review_roles_uses_frozen_direct_auth_snapshot(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"snapshotBinding":{},"candidates":[]}',
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
                "格式语义直连",
                ACCESS_DIRECT_MODEL,
                service_base_url="https://format-model.example/v1",
                model_name="format-role-model",
                max_output_tokens=1024,
                context_window_tokens=40000,
            )
            store.replace_api_key(configuration["id"], "format-secret")
            store.activate_configuration(configuration["id"])
            client = ProviderClient(
                AppSettings(timeout_seconds=75), model_configuration_store=store
            )
            frozen_auth = client.resolve_task_auth("word.format_review")
            client.format_review_roles(
                "trace-format-role",
                {"operation": "classify_role"},
                "只返回 JSON。",
                task_auth=frozen_auth,
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://format-model.example/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer format-secret")
        self.assertEqual(payload["model"], "format-role-model")
        self.assertEqual(payload["max_tokens"], 1024)
        self.assertEqual(payload["messages"][1]["content"], "只返回 JSON。")

    @patch("app.services.provider_client.urllib_request.urlopen")
    def test_direct_request_rejects_reasoning_only_response(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            {
                "choices": [
                    {"message": {"reasoning_content": "只有推理", "content": "<think>思考"}}
                ]
            }
        )
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            with self.assertRaises(AdapterError) as raised:
                client.post_task("word.smart_write", "trace-no-final", {}, "改写")
        self.assertEqual(raised.exception.code, "MODEL_FINAL_CONTENT_MISSING")

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
