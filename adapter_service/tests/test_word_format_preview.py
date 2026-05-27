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


class RecordingSmartFormatProvider:
    def __init__(self) -> None:
        self.queries = []

    def is_task_configured(self, task_type: str) -> bool:
        return task_type == "word.smart_format"

    def get_auth_source_for_task(self, task_type: str) -> str:
        return "task-file"

    def post_task(self, task_type: str, trace_id: str, input_data: dict, query: str) -> dict:
        self.queries.append(query)
        if '"paragraphIndex": 121' in query:
            return {
                "answer": '{"paragraphs":[{"paragraphIndex":121,"role":"caption","confidence":0.99}]}'
            }
        return {"answer": '{"paragraphs":[]}'}


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

    def test_formatter_classifies_all_paragraphs_in_long_document(self) -> None:
        paragraphs = [
            {
                "index": index,
                "text": "正文段落 {0}".format(index),
                "styleName": "Body",
                "fontName": "宋体",
                "fontSize": 12,
                "alignment": "justify",
                "outlineLevel": 0,
                "lineSpacing": 1.25,
                "firstLineIndent": 640,
            }
            for index in range(1, 122)
        ]
        request = parse_word_request(
            {
                "documentId": "long-document.docx",
                "scene": "word",
                "selectionMode": "document",
                "content": {
                    "plainText": "\n".join(item["text"] for item in paragraphs),
                    "paragraphs": paragraphs,
                    "headings": [],
                    "documentStructure": {
                        "page_setup": {
                            "marginTop": 1440,
                            "marginBottom": 1440,
                            "marginLeft": 1800,
                            "marginRight": 1800,
                        }
                    },
                },
                "options": {
                    "templateId": "technical-file-format-requirements",
                    "trackChanges": True,
                },
            }
        )
        provider = RecordingSmartFormatProvider()

        data = WordFormatter(provider_client=provider).preview(request, trace_id="trace-format-long")

        self.assertEqual(len(provider.queries), 2)
        tail_change = next(change for change in data["changes"] if change["paragraphIndex"] == 121)
        self.assertEqual(tail_change["role"], "caption")
        self.assertEqual(tail_change["targetStyle"], "caption")
        self.assertEqual(data["summary"]["paragraphCount"], 121)
        self.assertEqual(data["summary"]["aiClassifiedParagraphCount"], 1)
        self.assertEqual(data["summary"]["localFallbackParagraphCount"], 120)
        self.assertEqual(data["summary"]["aiBatchCount"], 2)


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
