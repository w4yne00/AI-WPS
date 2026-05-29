import importlib.util
import unittest
from pathlib import Path

from app.core.config import load_settings
from app.services.provider_client import ProviderClient


HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None


class ReviewModeContractTests(unittest.TestCase):
    def test_task_api_key_status_exposes_only_current_word_tasks(self) -> None:
        client = ProviderClient(load_settings())

        status = client.build_task_api_key_status()

        self.assertEqual(
            list(status.keys()),
            ["word.smart_write", "word.document_review", "word.format_review"],
        )
        self.assertEqual(status["word.smart_write"]["apiKeyRef"], "word_smart_write")
        self.assertEqual(status["word.document_review"]["apiKeyRef"], "word_document_review")
        self.assertEqual(status["word.format_review"]["apiKeyRef"], "word_format_review")

    def test_route_diagnostics_reports_new_version_and_current_tasks(self) -> None:
        client = ProviderClient(load_settings())

        diagnostics = client.build_route_diagnostics()

        self.assertEqual(diagnostics["version"], "0.12.9-alpha")
        self.assertEqual(
            list(diagnostics["taskApiKeys"].keys()),
            ["word.smart_write", "word.document_review", "word.format_review"],
        )

    def test_executable_code_no_longer_references_deleted_word_routes(self) -> None:
        roots = [
            Path("adapter_service/app"),
            Path("formal-plugin-kit/wps-ai-assistant_1.0.0"),
        ]
        deleted_tokens = [
            "/word/proofread",
            "/word/technical-review",
            "/word/format-preview",
            "/word/rewrite",
            "word.proofread",
            "word.technical_review",
            "word.smart_format",
            "runProofread",
            "runTechnicalReview",
            "runFormatPreview",
            "applyFormatChanges",
        ]

        offenders = []
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in {".py", ".js", ".html", ".xml"}:
                    continue
                text = path.read_text(encoding="utf-8")
                for token in deleted_tokens:
                    if token in text:
                        offenders.append(f"{path}:{token}")

        self.assertEqual(offenders, [])


class DocumentReviewProviderTests(unittest.TestCase):
    def test_document_review_prompt_and_parser_accept_markdown_json(self) -> None:
        provider_module = __import__(
            "app.services.provider_client",
            fromlist=["build_document_review_prompt", "parse_document_review_answer"],
        )

        prompt = provider_module.build_document_review_prompt(
            text="系统能够高效处理相关数据。",
            document_type="technical_solution",
            review_prompt="重点检查表达逻辑。",
        )
        parsed = provider_module.parse_document_review_answer(
            """
            ```json
            {
              "summary": "发现一项问题。",
              "issues": [
                {
                  "category": "语言逻辑表达",
                  "severity": "高",
                  "location": "第 1 段",
                  "originalText": "高效处理相关数据",
                  "problem": "表述过于笼统。",
                  "suggestion": "补充处理对象、性能指标或边界条件。",
                  "suggestedRewrite": "系统支持对业务数据进行批量处理。"
                }
              ]
            }
            ```
            """
        )

        self.assertIn("技术方案", prompt)
        self.assertIn("重点检查表达逻辑。", prompt)
        self.assertIn("typo、expression、logic、fluency、professional", prompt)
        self.assertEqual(parsed["summary"], "发现一项问题。")
        self.assertEqual(parsed["issues"][0]["category"], "logic")
        self.assertEqual(parsed["issues"][0]["severity"], "high")
        self.assertEqual(parsed["issues"][0]["suggestedRewrite"], "系统支持对业务数据进行批量处理。")
