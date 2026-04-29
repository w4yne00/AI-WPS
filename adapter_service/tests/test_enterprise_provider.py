import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import load_settings
from app.services.provider_client import extract_answer, build_rewrite_prompt


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


if __name__ == "__main__":
    unittest.main()
