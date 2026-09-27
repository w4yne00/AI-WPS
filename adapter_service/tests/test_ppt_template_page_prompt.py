import json
import pytest
from app.services.system_prompts import SystemPromptStore
from app.services.workflow_profiles import SUPPORTED_WORKFLOW_TASKS


def test_ppt_template_page_prompt_registered():
    store = SystemPromptStore()
    item = store.load("ppt.template_page")
    assert item is not None
    prompt = item["content"]
    assert "ppt.template_page.v1" in prompt
    assert "keyPoints" in prompt
    assert "speakerNotes" in prompt
    assert "fragmentIds" in prompt
    assert "missingItems" in prompt


def test_ppt_template_page_in_supported_tasks():
    assert "ppt.template_page" in SUPPORTED_WORKFLOW_TASKS


def test_ppt_template_page_schema_parse():
    sample_json = {
        "schemaVersion": "ppt.template_page.v1",
        "pageIndex": 3,
        "pageRole": "content",
        "title": "系统总体架构与核心技术原则",
        "keyPoints": [
          "分层解耦：采用服务化解耦架构，支撑各模块独立演进与灰度发布",
          "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
          "弹性伸缩：基于动态容器编排与流量调度，保障突发高并发场景平稳可用"
        ],
        "speakerNotes": "各位领导，本页展示的是系统总体架构设计。我们严格遵循分层解耦、安全可控与弹性伸缩三大原则...",
        "fragmentIds": [1, 2],
        "missingItems": []
    }
    raw = json.dumps(sample_json)
    data = json.loads(raw)
    assert data["schemaVersion"] == "ppt.template_page.v1"
    assert len(data["keyPoints"]) == 3
    assert "speakerNotes" in data
    assert data["fragmentIds"] == [1, 2]
