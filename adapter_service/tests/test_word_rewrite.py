from fastapi.testclient import TestClient

from app.main import app


def test_word_rewrite_returns_rewritten_text() -> None:
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
            "trackChanges": True
        }
    }

    response = client.post("/word/rewrite", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["taskType"] == "word.rewrite"
    assert body["data"]["rewriteMode"] == "continue"
    assert body["data"]["rewrittenText"]
    assert "Text content changed" in body["data"]["diffHints"]
