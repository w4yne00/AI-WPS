import importlib.util

import unittest

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient

    from app.main import app


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class WordRewriteApiTests(unittest.TestCase):
    def test_word_rewrite_returns_rewritten_text(self) -> None:
        client = TestClient(app)
        payload = {
            "documentId": "doc-001",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "Need a clearer project update.",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "Need a clearer project update.",
                        "styleName": "Body",
                        "fontName": "SimSun",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": []
            },
            "options": {
                "templateId": "general-office",
                "trackChanges": True,
                "rewriteAction": "continue"
            }
        }

        response = client.post("/word/rewrite", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.rewrite")
        self.assertEqual(body["data"]["rewriteMode"], "continue")
        self.assertTrue(body["data"]["rewrittenText"])
        self.assertIn("Text content changed", body["data"]["diffHints"])

    def test_word_rewrite_respects_explicit_rewrite_action(self) -> None:
        client = TestClient(app)
        payload = {
            "documentId": "doc-001",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "只改写这一段内容。",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "只改写这一段内容。",
                        "styleName": "Body",
                        "fontName": "SimSun",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": []
            },
            "options": {
                "templateId": "general-office",
                "trackChanges": True,
                "rewriteAction": "rewrite"
            }
        }

        response = client.post("/word/rewrite", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.rewrite")
        self.assertEqual(body["data"]["rewriteMode"], "rewrite")

    def test_word_smart_write_returns_workflow_ready_result(self) -> None:
        client = TestClient(app)
        payload = {
            "documentId": "doc-001",
            "scene": "word",
            "selectionMode": "selection",
            "content": {
                "plainText": "请将这段内容整理得更适合正式材料。",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "请将这段内容整理得更适合正式材料。",
                        "styleName": "Body",
                        "fontName": "SimSun",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": []
            },
            "options": {
                "templateId": "general-office",
                "trackChanges": True,
                "rewriteAction": "rewrite",
                "rewriteStyle": "formal",
                "focusPoint": "conclusion",
                "lengthMode": "same",
                "userInstruction": "只输出正文"
            }
        }

        response = client.post("/word/smart-write", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.smart_write")
        self.assertEqual(body["data"]["rewriteMode"], "rewrite")
        self.assertTrue(body["data"]["rewrittenText"])
        self.assertIn("Text content changed", body["data"]["diffHints"])
