import json
import pytest
from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.template_page import (
    PptTemplatePageCoordinator,
    evaluate_template_page_capacity,
)


def test_evaluate_template_page_capacity():
    # Normal case
    normal_points = [
        "分层解耦：采用服务化解耦架构，支撑各模块独立演进与灰度发布",
        "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
        "弹性伸缩：基于动态容器编排与流量调度，保障突发高并发场景平稳可用",
    ]
    res = evaluate_template_page_capacity(normal_points)
    assert res["is_overflow"] is False
    assert res["total_characters"] > 0
    assert res["estimated_lines"] <= 8
    assert res["point_count"] == 3

    # Overflow by point count (> 4)
    too_many_points = ["要点1", "要点2", "要点3", "要点4", "要点5"]
    assert evaluate_template_page_capacity(too_many_points)["is_overflow"] is True

    # Overflow by total characters (> 260)
    huge_point = ["非常非常长的文本内容" * 30]
    assert evaluate_template_page_capacity(huge_point)["is_overflow"] is True


@pytest.fixture
def page_setup(tmp_path):
    store = PptMaterialStore(tmp_path)
    coord = PptTemplatePageCoordinator(store=store)
    return {"store": store, "coord": coord, "tmp_path": tmp_path}


def test_ppt_template_page_submission_validation(page_setup):
    coord = page_setup["coord"]
    # Missing session
    with pytest.raises(AdapterError) as exc:
        coord.submit_job({"clientJobId": "cjob1"})
    assert exc.value.status_code == 422

    # Invalid clientJobId
    with pytest.raises(AdapterError) as exc2:
        coord.submit_job({"documentSessionId": "sess_1", "clientJobId": "??invalid!!"})
    assert exc2.value.status_code == 422


def test_ppt_template_page_generation_lifecycle(page_setup, monkeypatch):
    coord = page_setup["coord"]
    store = page_setup["store"]

    # Seed material in store
    cat = {
        "totalDocuments": 1,
        "totalCharacters": 500,
        "documents": [{"materialId": "mat_1", "fileName": "总体建设方案.docx", "characterCount": 500}],
        "blocks": [
            {"materialId": "mat_1", "blockId": 1, "kind": "heading", "text": "第一章 总体架构"},
            {"materialId": "mat_1", "blockId": 2, "kind": "paragraph", "text": "架构必须分层解耦并达到等保三级。"},
        ],
        "fragments": {
            "1": {
                "fragmentId": 1,
                "materialId": "mat_1",
                "blockId": 2,
                "fileName": "总体建设方案.docx",
                "heading": "第一章 总体架构",
                "text": "架构必须分层解耦并达到等保三级。",
            }
        },
    }
    monkeypatch.setattr(store, "get_catalog", lambda s: cat)

    # Mock provider response
    mock_model_output = {
        "schemaVersion": "ppt.template_page.v1",
        "title": "总体架构设计与安全原则",
        "keyPoints": [
            "分层解耦：采用业务域服务化解耦架构，支撑各模块独立演进与灰度发布",
            "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
        ],
        "speakerNotes": "各位领导，本页展示的是系统总体架构设计。我们严格遵循分层解耦与安全可控原则...",
        "fragmentIds": [1],
        "missingItems": [],
    }

    class DummyProvider:
        def resolve_task_auth(self, *args, **kwargs):
            return {"providerBaseUrl": "http://mock", "apiKey": "mock_key"}

        def post_task(self, *args, **kwargs):
            return {"answer": json.dumps(mock_model_output)}

    coord.provider = DummyProvider()

    req = {
        "documentSessionId": "sess_ppt_test",
        "clientJobId": "cjob_page_1",
        "pageIndex": 3,
        "pageRole": "content",
        "outlineTitle": "总体架构设计",
        "outlineKeyPoints": ["分层解耦", "安全可控"],
        "outlineFragmentIds": [1],
        "instruction": "重点强调安全合规",
        "userFacts": "",
    }

    job = coord.submit_job(req)
    assert job["jobId"]
    assert job["taskType"] == "ppt.template_page"

    # Wait or check completed job
    retrieved = coord.get_job(job["jobId"], "sess_ppt_test")
    assert retrieved["status"] == "completed"
    res = retrieved["result"]
    assert res["schemaVersion"] == "ppt.template_page.v1"
    assert res["title"] == "总体架构设计与安全原则"
    assert len(res["keyPoints"]) == 2
    assert "speakerNotes" in res
    assert len(res["sources"]) == 1
    assert res["sources"][0]["fileName"] == "总体建设方案.docx"
    assert res["estimatedLines"] > 0
    assert res["totalCharacters"] > 0
    assert len(res["basisMaterials"]) == 1


def test_ppt_template_page_fake_fragment_id_rejected(page_setup, monkeypatch):
    coord = page_setup["coord"]
    store = page_setup["store"]
    monkeypatch.setattr(store, "get_catalog", lambda s: {"fragments": {}})

    fake_output = {
        "schemaVersion": "ppt.template_page.v1",
        "title": "架构页",
        "keyPoints": ["要点一"],
        "speakerNotes": "讲稿",
        "fragmentIds": [9999],  # does not exist
        "missingItems": [],
    }

    class DummyProvider:
        def resolve_task_auth(self, *args, **kwargs):
            return {"providerBaseUrl": "http://mock", "apiKey": "mock_key"}

        def post_task(self, *args, **kwargs):
            return {"answer": json.dumps(fake_output)}

    coord.provider = DummyProvider()

    req = {
        "documentSessionId": "sess_ppt_test",
        "clientJobId": "cjob_fake",
        "pageIndex": 2,
        "outlineTitle": "测试",
        "outlineKeyPoints": ["要点"],
    }

    job = coord.submit_job(req)
    retrieved = coord.get_job(job["jobId"], "sess_ppt_test")
    assert retrieved["status"] == "failed"
    assert "出处片段编号不存在" in retrieved["error"]["message"]
