import unittest
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import load_settings, save_provider_base_url
from app.services.provider_client import (
    ProviderClient,
    build_rewrite_prompt,
    build_typo_prompt,
    extract_answer,
    parse_typo_issues,
)


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
        self.assertIn("用户附加要求", prompt)
        self.assertIn("请突出风险和下一步计划，压缩到200字以内。", prompt)
        self.assertIn("项目进展总体正常，但风险项较多。", prompt)

    def test_extract_answer_reads_enterprise_chat_response(self) -> None:
        body = {
            "event": "message",
            "conversation_id": "abc",
            "message_id": "msg-1",
            "answer": "这是改写后的文档内容。",
        }

        self.assertEqual(extract_answer(body), "这是改写后的文档内容。")

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


if __name__ == "__main__":
    unittest.main()
