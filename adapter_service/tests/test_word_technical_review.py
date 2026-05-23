import importlib.util
import unittest

from app.services.provider_client import (
    build_technical_review_prompt,
    parse_technical_review_answer,
)

HAS_API_DEPS = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("pydantic") is not None

if HAS_API_DEPS:
    from fastapi.testclient import TestClient
    from app.main import app


@unittest.skipUnless(HAS_API_DEPS, "fastapi and pydantic are required for API tests")
def test_word_technical_review_returns_structured_issues() -> None:
    client = TestClient(app)
    payload = {
        "documentId": "doc-technical-001",
        "scene": "word",
        "selectionMode": "selection",
        "content": {
            "plainText": "系统支持多种接口，能够高效处理相关数据。",
            "paragraphs": [
                {
                    "index": 1,
                    "text": "系统支持多种接口，能够高效处理相关数据。",
                    "styleName": "Body",
                    "fontName": "SimSun",
                    "fontSize": 12,
                    "alignment": "left",
                    "outlineLevel": 0,
                }
            ],
            "headings": [],
        },
        "options": {
            "technicalDocumentType": "technical_solution",
            "technicalReviewPrompt": "重点检查接口描述是否明确。",
        },
    }

    response = client.post("/word/technical-review", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["taskType"] == "word.technical_review"
    assert body["data"]["documentType"] == "technical_solution"
    assert body["data"]["reviewPrompt"] == "重点检查接口描述是否明确。"
    assert body["data"]["provider"] == "mock"
    assert body["data"]["issues"]


def test_technical_review_prompt_includes_custom_focus_and_schema() -> None:
    prompt = build_technical_review_prompt(
        text="接口支持数据同步。",
        document_type="contract_acceptance",
        review_prompt="重点检查验收标准是否可执行。",
    )

    assert "合同验收文档" in prompt
    assert "重点检查验收标准是否可执行。" in prompt
    assert "summary 和 issues" in prompt
    assert "accuracy、terminology、design、requirement" in prompt


def test_parse_technical_review_answer_normalizes_fields() -> None:
    parsed = parse_technical_review_answer(
        """
        {
          "summary": "发现一项问题。",
          "issues": [
            {
              "category": "术语专业性",
              "severity": "高",
              "location": "第 2 节",
              "originalText": "后端代理",
              "problem": "术语与全文不一致。",
              "suggestion": "统一为本地 adapter 服务。",
              "suggestedRewrite": "本地 adapter 服务"
            }
          ]
        }
        """
    )

    assert parsed["summary"] == "发现一项问题。"
    assert parsed["issues"][0]["category"] == "terminology"
    assert parsed["issues"][0]["severity"] == "high"
    assert parsed["issues"][0]["suggestedRewrite"] == "本地 adapter 服务"
