import json
import pytest
from app.services.system_prompts import SystemPromptStore
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


def test_ppt_material_outline_prompt_registered():
    store = SystemPromptStore()
    item = store.load("ppt.material_outline")
    assert item is not None
    prompt = item["content"]
    assert "ppt.material_outline.v1" in prompt
    assert "汇报对象" in prompt
    assert "页数" in prompt
    assert "pageRole" in prompt
    assert "missingItems" in prompt


def test_ppt_material_outline_in_supported_tasks():
    assert "ppt.material_outline" in SUPPORTED_WORKFLOW_TASKS


def test_ppt_material_outline_schema_parse():
    sample_json = {
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管汇报",
        "slideCount": 2,
        "instruction": "重点汇报一期成果",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "系统建设阶段汇报",
                "keyPoints": ["汇报主题与目标", "汇报部门与日期"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "一期建设核心成效",
                "keyPoints": ["业务网点全覆盖", "零故障稳定运行"],
                "missingItems": ["预算执行情况未提及"],
                "fragmentIds": [2, 3],
            },
        ],
    }
    raw = json.dumps(sample_json)
    data = json.loads(raw)
    assert data["schemaVersion"] == "ppt.material_outline.v1"
    assert len(data["slides"]) == 2
    assert data["slides"][0]["pageRole"] == "cover"
    assert data["slides"][1]["missingItems"] == ["预算执行情况未提及"]
