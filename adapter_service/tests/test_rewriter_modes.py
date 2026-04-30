import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.models import WordDocumentRequest
from app.services.word.rewriter import WordRewriter


class FakeProviderClient:
    def rewrite(self, text, mode, trace_id, user_instruction="", style="default", focus="default", length="default"):
        return {
            "rewrittenText": "[{0}] {1}".format(mode, text),
            "provider": "fake-provider",
        }


class RewriterModeTests(unittest.TestCase):
    def test_selection_request_can_use_continue_mode(self) -> None:
        request = WordDocumentRequest.parse_obj(
            {
                "documentId": "doc-001",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "选中的一句话",
                    "paragraphs": [{"index": 1, "text": "选中的一句话"}],
                    "headings": [],
                },
                "options": {
                    "rewriteAction": "continue",
                },
            }
        )
        rewriter = WordRewriter(provider_client=FakeProviderClient())

        result = rewriter.rewrite(request, trace_id="trace-1", mode=request.options.rewrite_action)

        self.assertEqual(result["rewriteMode"], "continue")
        self.assertEqual(result["provider"], "fake-provider")
        self.assertTrue(result["rewrittenText"].startswith("[continue]"))

    def test_selection_request_can_use_rewrite_mode(self) -> None:
        request = WordDocumentRequest.parse_obj(
            {
                "documentId": "doc-001",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "只改写这一段",
                    "paragraphs": [{"index": 1, "text": "只改写这一段"}],
                    "headings": [],
                },
                "options": {
                    "rewriteAction": "rewrite",
                },
            }
        )
        rewriter = WordRewriter(provider_client=FakeProviderClient())

        result = rewriter.rewrite(request, trace_id="trace-2", mode=request.options.rewrite_action)

        self.assertEqual(result["rewriteMode"], "rewrite")
        self.assertEqual(result["provider"], "fake-provider")
        self.assertTrue(result["rewrittenText"].startswith("[rewrite]"))


if __name__ == "__main__":
    unittest.main()
