import importlib.util
import unittest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and HAS_PYDANTIC

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app

if HAS_PYDANTIC:
    from app.core.models import WordDocumentRequest
    from app.services.word.formatter import WordFormatter


def parse_word_request(payload):
    if hasattr(WordDocumentRequest, "model_validate"):
        return WordDocumentRequest.model_validate(payload)
    return WordDocumentRequest.parse_obj(payload)


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for formatter tests")
class WordFormatterUnitTests(unittest.TestCase):
    def test_formatter_returns_template_properties_for_technical_roles(self) -> None:
        request = parse_word_request(
            {
                "documentId": "doc-003",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "1 总则\n正文\n表1 参数",
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "1 总则",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 12,
                            "alignment": "left",
                            "outlineLevel": 0
                        },
                        {
                            "index": 2,
                            "text": "正文内容",
                            "styleName": "Body",
                            "fontName": "楷体",
                            "fontSize": 14,
                            "alignment": "left",
                            "outlineLevel": 0,
                            "lineSpacing": 1.0,
                            "firstLineIndent": 0
                        },
                        {
                            "index": 3,
                            "text": "表1 参数说明",
                            "styleName": "Normal",
                            "fontName": "宋体",
                            "fontSize": 12,
                            "alignment": "left",
                            "outlineLevel": 0
                        }
                    ],
                    "headings": [],
                    "documentStructure": {"page_setup": {"marginTop": 72}}
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True
                }
            }
        )

        data = WordFormatter().preview(request, trace_id="")

        self.assertEqual(data["summary"]["templateId"], "technical-file-format-requirements")
        self.assertEqual(data["summary"]["provider"], "local")
        self.assertTrue(any(change["paragraphIndex"] == 0 and change["role"] == "page_setup" for change in data["changes"]))
        heading = next(change for change in data["changes"] if change["paragraphIndex"] == 1)
        self.assertEqual(heading["role"], "heading1")
        self.assertEqual(heading["targetStyle"], "heading 1")
        self.assertEqual(heading["targetProperties"]["fontName"], "黑体")
        caption = next(change for change in data["changes"] if change["paragraphIndex"] == 3)
        self.assertEqual(caption["role"], "caption")
        self.assertEqual(caption["targetProperties"]["alignment"], "center")


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
class WordFormatPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_word_format_preview_returns_change_plan(self) -> None:
        payload = {
            "documentId": "doc-001",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "Heading\nBody",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "Heading",
                        "styleName": "Heading 1",
                        "fontName": "SimSun",
                        "fontSize": 14,
                        "alignment": "center",
                        "outlineLevel": 1
                    },
                    {
                        "index": 2,
                        "text": "Body paragraph",
                        "styleName": "Body",
                        "fontName": "KaiTi",
                        "fontSize": 14,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": [{"level": 1, "text": "Heading"}]
            },
            "options": {
                "templateId": "general-office",
                "trackChanges": True
            }
        }

        response = self.client.post("/word/format-preview", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["taskType"], "word.format_preview")
        self.assertGreaterEqual(body["data"]["summary"]["changeCount"], 1)
        self.assertEqual(body["data"]["summary"]["templateId"], "general-office")
        self.assertTrue(any(change["targetStyle"] == "Body" for change in body["data"]["changes"]))

    def test_word_format_preview_uses_company_template_style_names(self) -> None:
        payload = {
            "documentId": "doc-002",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "正文",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "正文",
                        "styleName": "Body",
                        "fontName": "楷体",
                        "fontSize": 14,
                        "alignment": "left",
                        "outlineLevel": 0,
                        "lineSpacing": 1.0
                    }
                ],
                "headings": []
            },
            "options": {
                "templateId": "technical-file-format-requirements",
                "trackChanges": True
            }
        }

        response = self.client.post("/word/format-preview", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["summary"]["templateId"], "technical-file-format-requirements")
        self.assertTrue(any(change["targetStyle"] == "Normal" for change in body["data"]["changes"]))

    def test_word_format_preview_returns_template_properties_for_technical_roles(self) -> None:
        payload = {
            "documentId": "doc-003",
            "scene": "word",
            "selectionMode": "document",
            "content": {
                "plainText": "1 总则\n正文\n表1 参数",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "1 总则",
                        "styleName": "Normal",
                        "fontName": "宋体",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    },
                    {
                        "index": 2,
                        "text": "正文内容",
                        "styleName": "Body",
                        "fontName": "楷体",
                        "fontSize": 14,
                        "alignment": "left",
                        "outlineLevel": 0,
                        "lineSpacing": 1.0,
                        "firstLineIndent": 0
                    },
                    {
                        "index": 3,
                        "text": "表1 参数说明",
                        "styleName": "Normal",
                        "fontName": "宋体",
                        "fontSize": 12,
                        "alignment": "left",
                        "outlineLevel": 0
                    }
                ],
                "headings": [],
                "documentStructure": {
                    "page_setup": {
                        "marginTop": 72,
                        "marginBottom": 72,
                        "marginLeft": 90,
                        "marginRight": 90
                    }
                }
            },
            "options": {
                "templateId": "technical-file-format-requirements",
                "trackChanges": True
            }
        }

        response = self.client.post("/word/format-preview", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn(
            data["summary"]["provider"],
            ("local", "enterprise-dify-chat/file", "enterprise-dify-chat/env", "enterprise-dify-chat/task-file"),
        )
        self.assertTrue(any(change["paragraphIndex"] == 0 and change["role"] == "page_setup" for change in data["changes"]))
        heading = next(change for change in data["changes"] if change["paragraphIndex"] == 1)
        self.assertEqual(heading["role"], "heading1")
        self.assertEqual(heading["targetStyle"], "heading 1")
        self.assertEqual(heading["targetProperties"]["fontName"], "黑体")
        caption = next(change for change in data["changes"] if change["paragraphIndex"] == 3)
        self.assertEqual(caption["role"], "caption")
        self.assertEqual(caption["targetProperties"]["alignment"], "center")
