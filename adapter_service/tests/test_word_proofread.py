from fastapi.testclient import TestClient

from app.main import app


def test_word_proofread_returns_detected_issues() -> None:
    client = TestClient(app)
    payload = {
        "documentId": "doc-001",
        "scene": "word",
        "selectionMode": "document",
        "content": {
            "plainText": "Title\nBody  with  double spaces。\nSecond body ，with punctuation.",
            "paragraphs": [
                {
                    "index": 1,
                    "text": "Title",
                    "styleName": "Heading 2",
                    "fontName": "SimHei",
                    "fontSize": 16,
                    "alignment": "center",
                    "outlineLevel": 2
                },
                {
                    "index": 2,
                    "text": "Body  with  double spaces。",
                    "styleName": "Body",
                    "fontName": "SimSun",
                    "fontSize": 12,
                    "alignment": "left",
                    "outlineLevel": 0
                },
                {
                    "index": 3,
                    "text": "Second body ，with punctuation.",
                    "styleName": "Body",
                    "fontName": "KaiTi",
                    "fontSize": 14,
                    "alignment": "left",
                    "outlineLevel": 0
                }
            ],
            "headings": [
                {
                    "level": 2,
                    "text": "Title"
                }
            ]
        },
        "options": {
            "templateId": "general-office",
            "trackChanges": True
        }
    }

    response = client.post("/word/proofread", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["taskType"] == "word.proofread"
    assert len(body["data"]["issues"]) >= 4
    assert {issue["ruleId"] for issue in body["data"]["issues"]} >= {
        "heading_hierarchy",
        "font_consistency",
        "font_size_consistency",
        "double_space"
    }


def test_word_proofread_uses_company_template_rules() -> None:
    client = TestClient(app)
    payload = {
        "documentId": "doc-002",
        "scene": "word",
        "selectionMode": "document",
        "content": {
            "plainText": "技术文件正文",
            "paragraphs": [
                {
                    "index": 1,
                    "text": "技术文件正文",
                    "styleName": "Normal",
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

    response = client.post("/word/proofread", json=payload)

    assert response.status_code == 200
    issues = response.json()["data"]["issues"]
    rule_ids = {issue["ruleId"] for issue in issues}
    assert {"template_font", "template_font_size", "template_line_spacing"} <= rule_ids
