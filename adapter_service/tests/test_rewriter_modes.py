import sys
import unittest
import importlib.util
from pathlib import Path

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.rewriter import WordRewriter


class FakeProviderClient:
    def rewrite(self, text, mode, trace_id, user_instruction="", style="default", focus="default", length="default"):
        return {
            "rewrittenText": "[{0}] {1}".format(mode, text),
            "provider": "fake-provider",
        }

    def smart_write(
        self,
        text,
        action,
        trace_id,
        user_prompt="",
        style="default",
        focus="default",
        length="default",
        selection_mode="selection",
    ):
        return {
            "rewrittenText": "[smart:{0}:{1}] {2}".format(action, selection_mode, text),
            "provider": "fake-provider",
        }


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for WordDocumentRequest parsing")
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

    def test_smart_write_uses_selected_action_and_selection_mode(self) -> None:
        request = WordDocumentRequest.parse_obj(
            {
                "documentId": "doc-001",
                "scene": "word",
                "selectionMode": "selection",
                "content": {
                    "plainText": "需要智能编写的内容",
                    "paragraphs": [{"index": 1, "text": "需要智能编写的内容"}],
                    "headings": [],
                },
                "options": {
                    "rewriteAction": "summarize",
                    "userInstruction": "提炼为两句话",
                },
            }
        )
        rewriter = WordRewriter(provider_client=FakeProviderClient())

        result = rewriter.smart_write(request, trace_id="trace-smart")

        self.assertEqual(result["rewriteMode"], "summarize")
        self.assertEqual(result["provider"], "fake-provider")
        self.assertTrue(result["rewrittenText"].startswith("[smart:summarize:selection]"))


if __name__ == "__main__":
    unittest.main()
