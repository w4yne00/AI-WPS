import unittest
from pathlib import Path
import sys
import os
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import load_settings, save_provider_base_url, task_routes_to_dict
from app.services.provider_client import (
    ProviderClient,
    build_document_proofread_payload,
    build_provider_request_payload,
    build_route_request_payload,
    build_rewrite_prompt,
    build_smart_write_prompt,
    build_typo_prompt,
    extract_answer,
    get_default_technical_review_prompt,
    save_route_api_key,
    clear_route_api_key,
    parse_document_proofread_issues,
    parse_typo_issues,
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
                "word.proofread": {
                  "taskId": "word.proofread",
                  "enabled": true
                },
                "word.technical_review": {
                  "taskId": "word.technical_review",
                  "enabled": false
                }
              }
            }
            """,
            encoding="utf-8",
        )

        settings = load_settings(config_file)

        self.assertEqual(settings.task_routes["word.proofread"].task_id, "word.proofread")
        self.assertTrue(settings.task_routes["word.proofread"].enabled)
        self.assertFalse(settings.task_routes["word.technical_review"].enabled)

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
                "word.proofread": {
                  "taskId": "word.proofread",
                  "path": "/workflows/run",
                  "apiKeyRef": "proofread",
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
        route = settings.task_routes["word.proofread"]

        self.assertEqual(route.path, "/workflows/run")
        self.assertEqual(route.api_key_ref, "proofread")
        self.assertEqual(route.payload_style, "workflow")
        self.assertEqual(route.response_mode, "blocking")
        self.assertEqual(route.output_key, "result")

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
            "word.proofread": type(
                "Route",
                (),
                {
                    "task_id": "word.proofread",
                    "enabled": True,
                    "path": "/workflows/run",
                    "api_key_ref": "proofread",
                    "payload_style": "workflow",
                    "response_mode": "blocking",
                    "output_key": "result",
                },
            )()
        }

        summary = task_routes_to_dict(settings)

        self.assertEqual(summary["word.proofread"]["taskId"], "word.proofread")
        self.assertTrue(summary["word.proofread"]["enabled"])
        self.assertEqual(summary["word.proofread"]["path"], "/workflows/run")
        self.assertEqual(summary["word.proofread"]["apiKeyRef"], "proofread")
        self.assertEqual(summary["word.proofread"]["payloadStyle"], "workflow")
        self.assertNotIn("apiKey", summary["word.proofread"])

    def test_build_route_request_payload_uses_route_payload_style(self) -> None:
        settings = load_settings()
        settings.provider_mode = "blocking"
        route = type(
            "Route",
            (),
            {
                "task_id": "word.proofread",
                "payload_style": "workflow",
                "response_mode": "streaming",
            },
        )()

        payload = build_route_request_payload(
            settings,
            route,
            {"task_id": "word.proofread", "document_text": "正文"},
            "检查正文",
        )

        self.assertEqual(payload["response_mode"], "streaming")
        self.assertEqual(payload["inputs"]["task_id"], "word.proofread")
        self.assertEqual(payload["inputs"]["query"], "检查正文")
        self.assertNotIn("query", payload)

    def test_build_route_request_payload_uses_dify_chat_fields(self) -> None:
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
        self.assertEqual(payload["inputs"]["task_id"], "word.rewrite")
        self.assertEqual(payload["inputs"]["text"], "原文")
        self.assertEqual(payload["inputs"]["mode"], "rewrite")
        self.assertEqual(payload["inputs"]["query"], "请改写原文")
        self.assertEqual(payload["inputs"]["prompt"], "请改写原文")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)
        self.assertNotIn("mode", payload)
        self.assertNotIn("conversation_id", payload)

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

        self.assertEqual(payload["input_data"]["task_id"], "word.rewrite")
        self.assertEqual(payload["mode"], "blocking")

    def test_build_route_request_payload_uses_strict_smart_write_workflow_inputs(self) -> None:
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

        self.assertEqual(payload["inputs"]["source_text"], "原文")
        self.assertEqual(payload["inputs"]["write_action"], "rewrite")
        self.assertEqual(payload["inputs"]["user_prompt"], "补充要求")
        self.assertNotIn("query", payload["inputs"])
        self.assertNotIn("query", payload)

    def test_rewrite_sends_source_text_in_dify_chat_inputs(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str) -> bool:
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
        self.assertEqual(client.captured_input_data["source_text"], "原文内容")
        self.assertEqual(client.captured_input_data["text"], "原文内容")
        self.assertEqual(client.captured_input_data["mode"], "rewrite")
        self.assertEqual(client.captured_input_data["rewrite_mode"], "rewrite")
        self.assertEqual(client.captured_input_data["user_instruction"], "更正式")
        self.assertIn("待处理内容：\n原文内容", client.captured_query)

    def test_smart_write_sends_workflow_start_variables(self) -> None:
        class CapturingProviderClient(ProviderClient):
            def __init__(self) -> None:
                super().__init__(load_settings())
                self.settings.provider_base_url = "https://aibot.example/v1"
                self.captured_input_data = {}
                self.captured_query = ""

            def is_task_configured(self, task_type: str) -> bool:
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
        self.assertEqual(client.captured_input_data["source_text"], "原文内容")
        self.assertEqual(client.captured_input_data["write_action"], "rewrite")
        self.assertEqual(client.captured_input_data["style"], "formal")
        self.assertEqual(client.captured_input_data["focus"], "risk")
        self.assertEqual(client.captured_input_data["length"], "same")
        self.assertEqual(client.captured_input_data["user_prompt"], "更正式")
        self.assertEqual(client.captured_input_data["selection_mode"], "selection")
        self.assertIn("待处理原文：\n原文内容", client.captured_query)

    def test_route_api_key_uses_ref_file_before_default_key(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        previous = os.environ.get("ENTERPRISE_AI_API_KEY")
        os.environ["ENTERPRISE_AI_API_KEY"] = "env-secret"
        try:
            save_route_api_key("proofread", "route-secret", tmp_dir)
            client = ProviderClient(load_settings())
            client.settings.provider_base_url = "https://aibot.example/v1"
            self.assertEqual(client.get_api_key("proofread", tmp_dir), "route-secret")
            clear_route_api_key("proofread", tmp_dir)
            self.assertEqual(client.get_api_key("proofread", tmp_dir), "env-secret")
        finally:
            if previous is None:
                os.environ.pop("ENTERPRISE_AI_API_KEY", None)
            else:
                os.environ["ENTERPRISE_AI_API_KEY"] = previous
            if default_key.exists():
                default_key.unlink()
            route_key = tmp_dir / "provider_api_keys" / "proofread"
            if route_key.exists():
                route_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

    def test_task_route_api_key_does_not_fall_back_to_default_for_named_ref(self) -> None:
        tmp_dir = Path("tmp-test-route-keys")
        tmp_dir.mkdir(exist_ok=True)
        default_key = tmp_dir / "provider_api_key"
        default_key.write_text("default-secret", encoding="utf-8")
        route = type("Route", (), {"api_key_ref": "smart_write"})()
        try:
            client = ProviderClient(load_settings())
            self.assertEqual(client.get_task_api_key(route, tmp_dir), "")
            save_route_api_key("smart_write", "smart-secret", tmp_dir)
            self.assertEqual(client.get_task_api_key(route, tmp_dir), "smart-secret")
        finally:
            clear_route_api_key("smart_write", tmp_dir)
            if default_key.exists():
                default_key.unlink()
            route_dir = tmp_dir / "provider_api_keys"
            if route_dir.exists():
                route_dir.rmdir()
            tmp_dir.rmdir()

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

    def test_typo_prompt_and_parser_use_json_array(self) -> None:
        prompt = build_typo_prompt("这是一个技术文挡。")

        self.assertIn("只返回 JSON", prompt)
        self.assertIn("这是一个技术文挡。", prompt)

        issues = parse_typo_issues(
            """
            [
              {"original": "文挡", "suggestion": "文档", "reason": "错别字"}
            ]
            """
        )

        self.assertEqual(
            issues,
            [{"original": "文挡", "suggestion": "文档", "reason": "错别字"}],
        )

    def test_default_technical_review_prompt_changes_by_document_type(self) -> None:
        solution_prompt = get_default_technical_review_prompt("technical_solution")
        acceptance_prompt = get_default_technical_review_prompt("contract_acceptance")
        test_outline_prompt = get_default_technical_review_prompt("test_outline")

        self.assertIn("架构边界", solution_prompt)
        self.assertIn("验收证据", acceptance_prompt)
        self.assertIn("测试范围", test_outline_prompt)
        self.assertNotEqual(acceptance_prompt, solution_prompt)
        self.assertNotEqual(test_outline_prompt, solution_prompt)

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

    def test_document_proofread_payload_sends_dify_user_inputs(self) -> None:
        payload = build_document_proofread_payload(
            document_text="一、总体要求\n正文内容",
            document_structure={
                "doc_name": "安全运行方案.docx",
                "template_id": "technical-file-format-requirements",
                "paragraphs": [{"index": 1, "text": "一、总体要求"}],
            },
            template_type="技术文件格式及书写要求",
            template_version="v1",
            trace_id="trace-proofread",
            local_rule_findings=[
                {
                    "ruleId": "template_font",
                    "category": "format",
                    "paragraphIndex": 1,
                    "message": "字体不符合模板。",
                }
            ],
            task_id="word.proofread",
        )

        input_data = payload["input_data"]
        self.assertEqual(input_data["task_id"], "word.proofread")
        self.assertEqual(input_data["taskType"], "word.proofread")
        self.assertEqual(input_data["document_text"], "一、总体要求\n正文内容")
        self.assertEqual(input_data["document_structure"]["doc_name"], "安全运行方案.docx")
        self.assertEqual(input_data["template_type"], "技术文件格式及书写要求")
        self.assertTrue(input_data["check_scope"]["check_expression"])
        self.assertEqual(input_data["local_rule_findings"][0]["category"], "format")
        self.assertIn("结构化 JSON", payload["query"])

    def test_build_provider_request_payload_uses_workflow_inputs(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-dify-workflow"
        settings.provider_chat_path = "/workflows/run"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.proofread", "taskType": "word.proofread"},
            query="请审校文档。",
        )

        self.assertEqual(payload["inputs"]["task_id"], "word.proofread")
        self.assertEqual(payload["inputs"]["taskType"], "word.proofread")
        self.assertEqual(payload["inputs"]["query"], "请审校文档。")
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertNotIn("input_data", payload)

    def test_build_provider_request_payload_keeps_chat_message_shape(self) -> None:
        settings = load_settings()
        settings.provider_type = "enterprise-chat-api"
        settings.provider_chat_path = "/chat-messages"
        settings.provider_mode = "blocking"

        payload = build_provider_request_payload(
            settings=settings,
            input_data={"task_id": "word.rewrite", "taskType": "word.rewrite"},
            query="请改写。",
        )

        self.assertEqual(payload["input_data"]["task_id"], "word.rewrite")
        self.assertEqual(payload["query"], "请改写。")
        self.assertEqual(payload["mode"], "blocking")
        self.assertNotIn("inputs", payload)

    def test_parse_document_proofread_issues_supports_quality_categories(self) -> None:
        issues = parse_document_proofread_issues(
            """
            {
              "issues": [
                {
                  "category": "typo",
                  "severity": "warning",
                  "paragraphIndex": 2,
                  "original": "文挡",
                  "suggestion": "文档",
                  "message": "疑似错别字",
                  "reason": "应使用“文档”。",
                  "confidence": 0.93
                },
                {
                  "category": "heading_consistency",
                  "severity": "info",
                  "paragraphIndex": 5,
                  "message": "章节命名不统一",
                  "suggestion": "统一使用“安全能力设计”。"
                }
              ]
            }
            """
        )

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["category"], "typo")
        self.assertEqual(issues[0]["original"], "文挡")
        self.assertEqual(issues[1]["category"], "heading_consistency")


if __name__ == "__main__":
    unittest.main()
