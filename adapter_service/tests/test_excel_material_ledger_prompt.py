import json
import pytest
from app.services.system_prompts import SystemPromptStore


def test_excel_material_ledger_prompt_registered():
    store = SystemPromptStore()
    item = store.load("excel.material_ledger")
    assert item is not None
    prompt = item["content"]
    assert "excel.material_ledger.v1" in prompt
    assert "一行一项" in prompt
    assert "缺项" in prompt
    assert "疑似重复" in prompt


def test_excel_material_ledger_schema_parse():
    sample_json = {
        "schemaVersion": "excel.material_ledger.v1",
        "rows": [
            {
                "values": {
                    "工作事项": "系统架构设计编制",
                    "责任部门": "技术部",
                    "完成时间": "2026年10月",
                    "交付物验收": "设计方案",
                },
                "missingFields": [],
                "isDuplicate": False,
                "duplicateOfIndex": None,
                "duplicateReason": "",
                "fragmentIds": [1, 2],
            },
            {
                "values": {
                    "工作事项": "安全加固整改",
                    "责任部门": "运维部",
                    "完成时间": "",
                    "交付物验收": "整改报告",
                },
                "missingFields": ["完成时间"],
                "isDuplicate": True,
                "duplicateOfIndex": 0,
                "duplicateReason": "与第一项范围存在交叠",
                "fragmentIds": [3],
            },
        ],
    }
    raw = json.dumps(sample_json)
    data = json.loads(raw)
    assert data["schemaVersion"] == "excel.material_ledger.v1"
    assert len(data["rows"]) == 2
    assert data["rows"][1]["missingFields"] == ["完成时间"]
    assert data["rows"][1]["isDuplicate"] is True
