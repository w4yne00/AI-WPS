import unittest
from pathlib import Path
import sys
import os
import importlib.util
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import AppSettings, load_settings, save_provider_base_url, save_task_api_key_ref, task_routes_to_dict
from app.services.provider_client import (
    ProviderClient,
    build_document_review_prompt,
    build_provider_request_payload,
    build_route_request_payload,
    build_rewrite_prompt,
    build_smart_write_prompt,
    extract_answer,
    get_last_provider_debug,
    get_default_document_review_prompt,
    get_route_api_key_path,
    save_local_api_key,
    save_route_api_key,
    clear_local_api_key,
    clear_route_api_key,
    parse_document_review_answer,
    record_provider_debug,
    reset_provider_debug,
)
from app.services.template_loader import TemplateLoader


class EnterpriseProviderTests(unittest.TestCase):
    def test_load_settings_reads_provider_fields(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "servicePort": 19100,
              "providerType": "enterprise-chat-api",
              "providerBaseUrl": "https://aibot.chinasatnet.com.cn/v1",
              "providerApiKeyEnv": "ENTERPRISE_AI_API_KEY",
              "providerChatPath": "/chat-messages",
              "providerMode": "blocking"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.service_port, 19100)
        self.assertEqual(settings.provider_type, "enterprise-chat-api")
        self.assertEqual(settings.provider_base_url, "https://aibot.chinasatnet.com.cn/v1")
        self.assertEqual(settings.provider_api_key_env, "ENTERPRISE_AI_API_KEY")
        self.assertEqual(settings.provider_chat_path, "/chat-messages")
        self.assertEqual(settings.provider_mode, "blocking")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_reads_task_api_key_refs(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "taskApiKeyRefs": {
                "word.format_review": "format_key"
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.task_api_key_refs["word.format_review"], "format_key")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_reads_task_routes(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerType": "enterprise-dify-workflow",
              "providerChatPath": "/workflows/run",
              "taskRoutes": {
                "word.document_review": {
                  "taskId": "word.document_review",
                  "enabled": true
                },
                "word.format_review": {
                  "taskId": "word.format_review",
                  "enabled": false
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.task_routes["word.document_review"].task_id, "word.document_review")
        self.assertTrue(settings.task_routes["word.document_review"].enabled)
        self.assertFalse(settings.task_routes["word.format_review"].enabled)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_reads_task_route_transport_fields(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerType": "enterprise-dify-workflow",
              "providerBaseUrl": "https://aibot.example/v1",
              "taskRoutes": {
                "word.document_review": {
                  "taskId": "word.document_review",
                  "path": "/workflows/run",
                  "apiKeyRef": "document_review",
                  "payloadStyle": "workflow",
                  "responseMode": "blocking",
                  "outputKey": "result",
                  "enabled": true
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)
        route = settings.task_routes["word.document_review"]

        self.assertEqual(route.path, "/workflows/run")
        self.assertEqual(route.api_key_ref, "document_review")
        self.assertEqual(route.payload_style, "workflow")
        self.assertEqual(route.response_mode, "blocking")
        self.assertEqual(route.output_key, "result")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_does_not_inject_default_task_routes_into_old_config(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "目标机旧配置",
              "providerBaseUrl": "https://aibot.example/v1"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "目标机旧配置")
        self.assertEqual(settings.task_routes, {})

        config_file.unlink()
        tmp_dir.rmdir()

    def test_load_settings_preserves_user_task_route_over_default_route(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerBaseUrl": "https://aibot.example/v1",
              "taskRoutes": {
                "word.smart_write": {
                  "taskId": "word.smart_write",
                  "path": "/chat-messages",
                  "apiKeyRef": "custom_smart_write",
                  "payloadStyle": "chat",
                  "responseMode": "blocking",
                  "outputKey": "answer",
                  "enabled": true
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)
        route = settings.task_routes["word.smart_write"]

        self.assertEqual(route.path, "/chat-messages")
        self.assertEqual(route.api_key_ref, "custom_smart_write")
        self.assertEqual(route.payload_style, "chat")
        self.assertEqual(route.output_key, "answer")
        self.assertNotIn("word.document_review", settings.task_routes)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_provider_client_resolves_default_task_route(self) -> None:
        client = ProviderClient(load_settings())

        route = client.resolve_task_route("word.smart_write")

        self.assertEqual(route.task_id, "word.smart_write")
        self.assertTrue(route.enabled)

    def test_task_routes_to_dict_exposes_safe_summary(self) -> None:
        settings = load_settings()
        settings.task_routes = {
            "word.document_review": type(
                "Route",
                (),
                {
                    "task_id": "word.document_review",
                    "enabled": True,
                    "path": "/workflows/run",
                    "api_key_ref": "document_review",
                    "payload_style": "workflow",
                    "response_mode": "blocking",
                    "output_key": "result",
                },
            )()
        }

        summary = task_routes_to_dict(settings)

        self.assertEqual(summary["word.document_review"]["taskId"], "word.document_review")
        self.assertTrue(summary["word.document_review"]["enabled"])
        self.assertEqual(summary["word.document_review"]["path"], "/workflows/run")
        self.assertEqual(summary["word.document_review"]["apiKeyRef"], "document_review")
        self.assertEqual(summary["word.document_review"]["payloadStyle"], "workflow")
        self.assertNotIn("apiKey", summary["word.document_review"])

    def test_build_route_request_payload_uses_unified_chat_query_shape(self) -> None:
        settings = load_settings()
        settings.provider_mode = "blocking"
        settings.provider_chat_path = "/chat-messages"
        route = type(
            "Route",
            (),
            {
                "task_id": "word.document_review",
                "payload_style": "workflow",
                "response_mode": "streaming",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {"task_id": "word.document_review", "document_text": "正文"},
            "检查正文",
        )

        self.assertEqual(payload["query"], "检查正文")
        self.assertEqual(payload["inputs"], {"query": "检查正文"})
        self.assertEqual(payload["response_mode"], "streaming")
        self.assertEqual(payload["conversation_id"], "")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_route_request_payload_ignores_custom_start_variables(self) -> None:
        settings = load_settings()
        settings.provider_mode = "blocking"
        route = type(
            "Route",
            (),
            {
                "task_id": "word.rewrite",
                "payload_style": "chat",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {
                "task_id": "word.rewrite",
                "source_text": "原文",
                "text": "原文",
                "mode": "rewrite",
                "rewrite_mode": "rewrite",
            },
            "请改写原文",
        )

        self.assertEqual(payload["query"], "请改写原文")
        self.assertEqual(payload["inputs"], {"query": "请改写原文"})
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)
        self.assertEqual(payload["conversation_id"], "")

    def test_build_route_request_payload_keeps_legacy_chat_fields_when_requested(self) -> None:
        settings = load_settings()
        route = type(
            "Route",
            (),
            {
                "task_id": "word.rewrite",
                "payload_style": "legacy-chat",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {"task_id": "word.rewrite", "source_text": "原文"},
            "请改写原文",
        )

        self.assertEqual(payload["inputs"], {"query": "请改写原文"})
        self.assertEqual(payload["query"], "请改写原文")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_route_request_payload_does_not_send_smart_write_workflow_inputs(self) -> None:
        settings = load_settings()
        route = type(
            "Route",
            (),
            {
                "task_id": "word.smart_write",
                "payload_style": "workflow",
                "response_mode": "blocking",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {
                "source_text": "原文",
                "write_action": "rewrite",
                "style": "formal",
                "focus": "default",
                "length": "same",
                "user_prompt": "补充要求",
                "selection_mode": "selection",
                "trace_id": "trace-smart",
            },
            "内部提示词",
        )

        self.assertEqual(payload["query"], "内部提示词")
        self.assertEqual(payload["inputs"], {"query": "内部提示词"})
        self.assertNotIn("input_data", payload)
        self.assertNotIn("source_text", payload["inputs"])
        self.assertNotIn("write_action", payload["inputs"])
        self.assertNotIn("user_prompt", payload["inputs"])

    def test_rewrite_sends_full_prompt_as_unified_query_only(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type: str, trace_id: str, input_data: dict, query: str) -> dict:
                self.captured_input_data = input_data
                self.captured_query = query
                return {"answer": "这是改写后的文本。"}

        client = CapturingProviderClient()

        result = client.rewrite(
            "原文内容",
            "rewrite",
            "trace-001",
            user_instruction="更正式",
            style="formal",
            focus="risk",
            length="same",
        )

        self.assertEqual(result["rewrittenText"], "这是改写后的文本。")
        self.assertEqual(client.captured_input_data, {})
        self.assertIn("待处理内容：\n原文内容", client.captured_query)
        self.assertIn("不要原样返回待处理内容", client.captured_query)

    def test_smart_write_sends_full_prompt_as_unified_query_only(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str, key_base_path=None) -> bool:
                return True

            def post_task(self, task_type: str, trace_id: str, input_data: dict, query: str) -> dict:
                self.captured_input_data = input_data
                self.captured_query = query
                return {"data": {"outputs": {"result": "智能编写后的文本。"}}}

        client = CapturingProviderClient()

        result = client.smart_write(
            "原文内容",
            "rewrite",
            "trace-smart",
            user_prompt="更正式",
            style="formal",
            focus="risk",
            length="same",
            selection_mode="selection",
        )

        self.assertEqual(result["rewrittenText"], "智能编写后的文本。")
        self.assertEqual(client.captured_input_data, {})
        self.assertIn("待处理原文：\n原文内容", client.captured_query)
        self.assertIn("不允许原样返回原文", client.captured_query)

    def test_route_api_key_uses_ref_file_before_default_key(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "env-secret"
        try:
            save_route_api_key("document_review", "route-secret", tmp_dir)
            client = ProviderClient(load_settings())
            client.settings.provider_base_url = "https://aibot.example/v1"
            self.assertEqual(client.get_api_key("document_review", tmp_dir), "route-secret")
            clear_route_api_key("document_review", tmp_dir)
            self.assertEqual(client.get_api_key("document_review", tmp_dir), "env-secret")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous
            if default_key.exists():
                default_key.unlink()
            route_key = tmp_dir / "provider_api_keys" / "document_review"
            if route_key.exists():
                route_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_task_api_key_overrides_unified_key_for_matching_task(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        try:
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            settings.task_api_key_refs = {"word.format_review": "format_review"}
            client = ProviderClient(settings)
            self.assertEqual(client.get_api_key_for_task("word.format_review", tmp_dir), "default-secret")
            save_route_api_key("format_review", "format-secret", tmp_dir)
            self.assertEqual(client.get_api_key_for_task("word.format_review", tmp_dir), "format-secret")
            self.assertEqual(client.get_api_key_for_task("word.smart_write", tmp_dir), "default-secret")
        finally:
            clear_route_api_key("format_review", tmp_dir)
            if default_key.exists():
                default_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_named_task_configuration_uses_unified_env_or_default_key(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "env-secret"
        try:
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            client = ProviderClient(settings)

            self.assertTrue(client.is_task_configured("word.smart_write", tmp_dir))
            save_route_api_key("word_smart_write", "smart-secret", tmp_dir)
            self.assertTrue(client.is_task_configured("word.smart_write", tmp_dir))
            self.assertEqual(client.get_auth_source_for_task("word.smart_write", tmp_dir), "task-file")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous
            clear_route_api_key("word_smart_write", tmp_dir)
            if default_key.exists():
                default_key.unlink()
            route_key = get_route_api_key_path("word_smart_write", tmp_dir)
            if route_key.exists():
                route_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_route_diagnostics_exposes_unified_chat_endpoint_without_secret(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        try:
            save_local_api_key("smart-secret", tmp_dir / "provider_api_key")
            settings = load_settings()
            settings.provider_base_url = "https://aibot.example/v1"
            client = ProviderClient(settings)

            diagnostics = client.build_route_diagnostics(key_base_path=tmp_dir)
            self.assertEqual(diagnostics["url"], "https://aibot.example/v1/chat-messages")
            self.assertEqual(diagnostics["path"], "/chat-messages")
            self.assertEqual(diagnostics["payloadStyle"], "chat")
            self.assertTrue(diagnostics["configured"])
            self.assertEqual(diagnostics["authSource"], "file")
            self.assertIn("word.format_review", diagnostics["taskApiKeys"])
            self.assertEqual(diagnostics["routes"], {})
            self.assertNotIn("smart-secret", str(diagnostics))
        finally:
            clear_local_api_key(tmp_dir / "provider_api_key")
            clear_route_api_key("word_smart_write", tmp_dir)
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_provider_debug_records_sanitized_request_and_response(self) -> None:
        full_prompt = "请改写这段很长的原文，包含不应该完整暴露在调试接口里的内容。"
        reset_provider_debug()

        record_provider_debug(
            {
                "traceId": "trace-debug",
                "taskType": "word.smart_write",
                "url": "https://aibot.example/v1/chat-messages",
                "request": {
                    "body": build_provider_request_payload(load_settings(), {}, full_prompt),
                },
                "response": {
                    "status": 200,
                    "body": {
                        "answer": "# 标题\n\n1. 第一项\n2. 第二项\n\n**重点内容**",
                        "conversation_id": "conv-1",
                    },
                },
            }
        )

        debug = get_last_provider_debug()

        self.assertEqual(debug["traceId"], "trace-debug")
        self.assertEqual(debug["taskType"], "word.smart_write")
        self.assertEqual(debug["request"]["bodyKeys"], ["conversation_id", "files", "inputs", "query", "response_mode", "user"])
        self.assertEqual(debug["request"]["inputsKeys"], ["query"])
        self.assertEqual(debug["request"]["queryLength"], len(full_prompt))
        self.assertIn("queryPreview", debug["request"])
        self.assertEqual(debug["response"]["status"], 200)
        self.assertEqual(debug["response"]["bodyKeys"], ["answer", "conversation_id"])
        self.assertEqual(debug["response"]["answerLength"], len("# 标题\n\n1. 第一项\n2. 第二项\n\n**重点内容**"))
        self.assertEqual(
            debug["response"]["answerFormat"],
            {
                "containsMarkdown": True,
                "containsHeading": True,
                "containsOrderedList": True,
                "containsUnorderedList": False,
                "containsBold": True,
                "containsParagraphBreak": True,
            },
        )
        self.assertNotIn("Authorization", str(debug))
        self.assertNotIn(full_prompt, str(debug))

    def test_provider_debug_records_sanitized_error(self) -> None:
        reset_provider_debug()

        record_provider_debug(
            {
                "traceId": "trace-error",
                "taskType": "word.smart_write",
                "url": "https://aibot.example/v1/chat-messages",
                "request": {
                    "body": build_provider_request_payload(load_settings(), {}, "请改写原文"),
                },
                "error": {
                    "type": "HTTPError",
                    "status": 400,
                    "message": "Bad Request: missing query",
                },
            }
        )

        debug = get_last_provider_debug()

        self.assertEqual(debug["error"]["type"], "HTTPError")
        self.assertEqual(debug["error"]["status"], 400)
        self.assertIn("Bad Request", debug["error"]["message"])
        self.assertNotIn("请改写原文", str(debug))

    def test_smart_write_mock_records_debug_skip_reason(self) -> None:
        settings = load_settings()
        settings.provider_base_url = ""
        client = ProviderClient(settings)
        reset_provider_debug()

        result = client.smart_write("待改写原文", "rewrite", "trace-mock-debug")
        debug = get_last_provider_debug()

        self.assertEqual(result["provider"], "mock")
        self.assertEqual(debug["traceId"], "trace-mock-debug")
        self.assertEqual(debug["taskType"], "word.smart_write")
        self.assertEqual(debug["provider"], "mock")
        self.assertEqual(debug["skipReason"], "provider_not_configured")
        self.assertFalse(debug["providerBaseUrlConfigured"])
        self.assertEqual(debug["authSource"], "none")
        self.assertGreater(debug["request"]["queryLength"], len("待改写原文"))
        self.assertNotIn("待改写原文", str(debug))

    def test_record_skipped_debug_records_format_review_skip_reason(self) -> None:
        settings = load_settings()
        settings.provider_base_url = "https://aibot.example/v1"
        client = ProviderClient(settings)
        reset_provider_debug()

        client.record_skipped_debug(
            "word.format_review",
            "trace-format-skip",
            "格式审查未读取到正文段落，未调用 Dify。",
            "no_paragraphs",
            provider="local",
        )
        debug = get_last_provider_debug()

        self.assertEqual(debug["traceId"], "trace-format-skip")
        self.assertEqual(debug["taskType"], "word.format_review")
        self.assertEqual(debug["provider"], "local")
        self.assertEqual(debug["skipReason"], "no_paragraphs")
        self.assertTrue(debug["providerBaseUrlConfigured"])
        self.assertIn("request", debug)

    def test_load_settings_defaults_provider_base_url_to_empty(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "仅配置名称"
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.provider_base_url, "")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_updates_config_file(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "servicePort": 19100,
              "providerType": "enterprise-chat-api",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("https://new.example/v1", config_file)
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_base_url, "https://new.example/v1")
        self.assertEqual(settings.service_port, 19100)

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_task_api_key_ref_updates_config_file(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_task_api_key_ref("word.format_review", "format_key", config_file)
        settings = load_settings(config_file)

        self.assertEqual(settings.task_api_key_refs["word.format_review"], "format_key")
        self.assertEqual(settings.provider_base_url, "https://old.example/v1")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_updates_provider_name(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "旧名称",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("https://new.example/v1", config_file, provider_name="新名称")
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "新名称")
        self.assertEqual(settings.provider_base_url, "https://new.example/v1")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_save_provider_base_url_allows_empty_url_and_updates_name(self) -> None:
        tmp_dir = Path("tmp-test-config")
        tmp_dir.mkdir(exist_ok=True)
        config_file = tmp_dir / "adapter.json"
        config_file.write_text(
            """
            {
              "providerName": "旧名称",
              "providerBaseUrl": "https://old.example/v1"
            }
            """,
            encoding="utf-8",
        )

        save_provider_base_url("", config_file, provider_name="自定义供应商")
        settings = load_settings(config_file)

        self.assertEqual(settings.provider_name, "自定义供应商")
        self.assertEqual(settings.provider_base_url, "")

        config_file.unlink()
        tmp_dir.rmdir()

    def test_provider_requires_key_and_base_url_to_be_configured(self) -> None:
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "secret"
        try:
            empty_url_client = ProviderClient(load_settings())
            empty_url_client.settings.provider_base_url = ""
            self.assertFalse(empty_url_client.is_configured())

            configured_client = ProviderClient(load_settings())
            configured_client.settings.provider_base_url = "https://new.example/v1"
            self.assertTrue(configured_client.is_configured())
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous

    def test_default_provider_client_refreshes_settings_before_task_configuration(self) -> None:
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "secret"
        try:
            with patch(
                "app.services.provider_client.load_settings",
                side_effect=[
                    AppSettings(provider_base_url=""),
                    AppSettings(provider_base_url="https://aibot.example/v1"),
                ],
            ):
                client = ProviderClient()

                self.assertTrue(client.is_task_configured("word.smart_write"))
                self.assertEqual(client.settings.provider_base_url, "https://aibot.example/v1")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous

    def test_template_loader_resolves_default_root_from_package_base(self) -> None:
        previous_cwd = Path.cwd()
        os.chdir(ROOT)
        try:
            loader = TemplateLoader()
            template_ids = {item["id"] for item in loader.list_templates()}
        finally:
            os.chdir(previous_cwd)

        self.assertIn("general-office", template_ids)
        self.assertIn("technical-file-format-requirements", template_ids)

    def test_build_rewrite_prompt_includes_user_instruction(self) -> None:
        prompt = build_rewrite_prompt(
            text="项目进展总体正常，但风险项较多。",
            mode="rewrite",
            user_instruction="请突出风险和下一步计划，压缩到200字以内。",
            style="formal",
            focus="risk",
            length="concise",
        )

        self.assertIn("保留原意，不编造事实", prompt)
        self.assertIn("不要原样返回待处理内容", prompt)
        self.assertIn("用户附加要求", prompt)
        self.assertIn("请突出风险和下一步计划，压缩到200字以内。", prompt)
        self.assertIn("项目进展总体正常，但风险项较多。", prompt)

    def test_build_smart_write_prompt_requires_changed_output(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目进展总体正常。",
            action="rewrite",
            user_prompt="更正式",
            style="formal",
            focus="risk",
            length="same",
        )

        self.assertIn("企业办公文档智能编写助手", prompt)
        self.assertIn("不允许原样返回原文", prompt)
        self.assertIn("待处理原文：\n项目进展总体正常。", prompt)

    def test_build_smart_write_prompt_uses_soetech_option_text(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目已经完成初步建设。",
            action="rewrite",
            user_prompt="语言适合技术方案正文",
            style="standard",
            focus="acceptance",
            length="expanded",
        )

        self.assertIn("国企技术方案常用的正式、准确、克制表达", prompt)
        self.assertIn("交付物、验收标准、问题闭环、证据材料", prompt)
        self.assertIn("不编造事实", prompt)
        self.assertIn("语言适合技术方案正文", prompt)

    def test_build_smart_write_prompt_preserves_legacy_option_aliases(self) -> None:
        prompt = build_smart_write_prompt(
            text="项目进展总体正常。",
            action="rewrite",
            style="formal",
            focus="next_step",
            length="default",
        )

        self.assertIn("国企技术方案常用的正式、准确、克制表达", prompt)
        self.assertIn("解决措施、实施路径、责任分工、时间节点", prompt)
        self.assertIn("保持与原文相近的篇幅", prompt)

    def test_extract_answer_reads_enterprise_chat_response(self) -> None:
        body = {
            "event": "message",
            "conversation_id": "abc",
            "message_id": "msg-1",
            "answer": "这是改写后的文档内容。",
        }

        self.assertEqual(extract_answer(body), "这是改写后的文档内容。")

    def test_extract_answer_reads_workflow_outputs(self) -> None:
        body = {
            "data": {
                "outputs": {
                    "result": "{\"issues\":[]}"
                }
            }
        }

        self.assertEqual(extract_answer(body, output_key="result"), "{\"issues\":[]}")

    def test_default_document_review_prompt_changes_by_document_type(self) -> None:
        solution_prompt = get_default_document_review_prompt("technical_solution")
        acceptance_prompt = get_default_document_review_prompt("contract_acceptance")
        test_outline_prompt = get_default_document_review_prompt("test_outline")

        self.assertIn("架构边界", solution_prompt)
        self.assertIn("验收证据", acceptance_prompt)
        self.assertIn("测试范围", test_outline_prompt)
        self.assertNotEqual(acceptance_prompt, solution_prompt)
        self.assertNotEqual(test_outline_prompt, solution_prompt)

    def test_document_review_prompt_and_parser_use_markdown_json(self) -> None:
        prompt = build_document_review_prompt(
            "这是一个技术文挡。",
            "technical_solution",
            "重点检查错别字和表达逻辑。",
        )
        parsed = parse_document_review_answer(
            """
            ```json
            {
              "summary": "发现一项问题。",
              "issues": [
                {
                  "category": "错别字",
                  "severity": "高",
                  "location": "第 1 段",
                  "originalText": "文挡",
                  "problem": "疑似错别字。",
                  "suggestion": "改为“文档”。",
                  "suggestedRewrite": "文档"
                }
              ]
            }
            ```
            """
        )

        self.assertIn("重点检查错别字和表达逻辑。", prompt)
        self.assertIn("typo、expression、logic、fluency、professional", prompt)
        self.assertEqual(parsed["summary"], "发现一项问题。")
        self.assertEqual(parsed["issues"][0]["category"], "typo")
        self.assertEqual(parsed["issues"][0]["severity"], "high")

    @unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is required for model parsing")
    def test_document_structure_is_accepted_in_word_request(self) -> None:
        from app.core.models import WordDocumentRequest

        request = WordDocumentRequest.parse_obj(
            {
                "documentId": "doc-structure",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "一、总体要求\n正文内容",
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "一、总体要求",
                            "styleName": "Heading 1",
                            "fontName": "黑体",
                            "fontSize": 12,
                            "outlineLevel": 1,
                        }
                    ],
                    "headings": [{"level": 1, "text": "一、总体要求"}],
                    "documentStructure": {
                        "doc_name": "安全运行方案.docx",
                        "template_id": "technical-file-format-requirements",
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "一、总体要求",
                                "style_name": "Heading 1",
                                "font_family": "黑体",
                            }
                        ],
                        "capabilities": {
                            "paragraph_style_extracted": True,
                            "table_extracted": False,
                        },
                    },
                },
            }
        )

        self.assertEqual(request.content.document_structure["doc_name"], "安全运行方案.docx")
        self.assertTrue(request.content.document_structure["capabilities"]["paragraph_style_extracted"])

    @unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is required for model parsing")
    def test_word_request_coerces_host_object_shaped_values(self) -> None:
        from app.core.models import WordDocumentRequest

        payload = {
            "scene": "word",
            "selectionMode": "unexpected",
            "content": {
                "plainText": {"bad": "host-object"},
                "paragraphs": [
                    {
                        "index": "1",
                        "text": {"bad": "host-object"},
                        "styleName": {"bad": "style-object"},
                        "fontName": {"bad": "font-object"},
                        "fontSize": {"bad": "size-object"},
                        "outlineLevel": {"bad": "level-object"},
                        "lineSpacing": {"bad": "spacing-object"},
                        "bold": -1,
                        "italic": "0",
                        "underline": -4142,
                    }
                ],
                "headings": {"bad": "not-list"},
                "documentStructure": "not-dict",
            },
        }

        if hasattr(WordDocumentRequest, "model_validate"):
            request = WordDocumentRequest.model_validate(payload)
        else:
            request = WordDocumentRequest.parse_obj(payload)

        self.assertEqual(request.document_id, "unnamed.docx")
        self.assertEqual(request.selection_mode, "document")
        self.assertEqual(request.content.plain_text, "")
        self.assertEqual(len(request.content.paragraphs), 1)
        paragraph = request.content.paragraphs[0]
        self.assertEqual(paragraph.index, 1)
        self.assertEqual(paragraph.text, "")
        self.assertEqual(paragraph.style_name, "")
        self.assertIsNone(paragraph.font_size)
        self.assertTrue(paragraph.bold)
        self.assertFalse(paragraph.italic)
        self.assertEqual(paragraph.underline, -4142)
        self.assertEqual(request.content.headings, [])
        self.assertEqual(request.content.document_structure, {})

    def test_build_provider_request_payload_uses_unified_chat_sys_query_shape(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-dify-chat"
        settings.provider_chat_path = "/chat-messages"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.document_review", "taskType": "word.document_review"},
            query="请审校文档。",
        )

        self.assertEqual(payload["inputs"], {"query": "请审校文档。"})
        self.assertEqual(payload["query"], "请审校文档。")
        self.assertEqual(payload["conversation_id"], "")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

    def test_build_provider_request_payload_ignores_input_data_for_chat_message_shape(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-chat-api"
        settings.provider_chat_path = "/chat-messages"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.rewrite", "taskType": "word.rewrite"},
            query="请改写。",
        )

        self.assertEqual(payload["inputs"], {"query": "请改写。"})
        self.assertEqual(payload["query"], "请改写。")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertEqual(payload["conversation_id"], "")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)

if __name__ == "__main__":
    unittest.main()
