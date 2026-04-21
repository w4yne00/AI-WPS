from fastapi.testclient import TestClient

from app.main import app


def test_word_format_preview_returns_change_plan() -> None:
    client = TestClient(app)
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
            "headings": [
                {
                    "level": 1,
                    "text": "Heading"
                }
            ]
        },
        "options": {
            "templateId": "general-office",
            "trackChanges": True
        }
    }

    response = client.post("/word/format-preview", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["taskType"] == "word.format_preview"
    assert body["data"]["summary"]["changeCount"] >= 1
    assert body["data"]["summary"]["templateId"] == "general-office"
    assert any(change["targetStyle"] == "Body" for change in body["data"]["changes"])
