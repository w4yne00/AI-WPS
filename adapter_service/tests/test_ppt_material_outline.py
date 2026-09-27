import base64
import json
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import zipfile
import pytest

from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.material_outline import PptMaterialOutlineCoordinator
from app.services.long_task_coordinator import get_long_task_coordinator


CONTENT_TYPES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" />
</Types>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:outlineLvl w:val="0" /></w:pPr>
      <w:r><w:t>第一章 项目建设成果</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>新一代系统一期已全面上线运行，覆盖12个网点。二期规划于2027年启动，建设智能风控。</w:t></w:r>
    </w:p>
  </w:body>
</w:document>""".encode("utf-8")


def build_docx(document_xml=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("word/document.xml", document_xml or DOCUMENT_XML)
    return output.getvalue()


@pytest.fixture
def outline_setup():
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_ppt_outline_"))
    store = PptMaterialStore(base_dir=temp_dir / "ppt", word_base_dir=temp_dir / "word", excel_base_dir=temp_dir / "excel")
    coordinator = PptMaterialOutlineCoordinator(store=store)

    raw_bytes = build_docx()
    store.import_material(
        session_id="ppt_test_sess",
        doc_identity="full:/test/deck.pptx",
        file_name="项目建设成果.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    yield store, coordinator
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_ppt_material_outline_submission_validation(outline_setup):
    store, coordinator = outline_setup
    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({})
    assert exc_info.value.code == "REQUEST_VALIDATION_FAILED"

    # Missing slideCount or invalid range
    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "audience": "高管汇报",
            "slideCount": 2,  # min is 3
        })
    assert exc_info.value.code == "REQUEST_VALIDATION_FAILED"


def test_ppt_material_outline_generation_and_roles(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "突出成效与规划",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目建设阶段汇报",
                "keyPoints": ["汇报主题与目标", "汇报部门与日期"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "一期建设核心成效",
                "keyPoints": ["业务网点全覆盖", "系统零故障稳定运行"],
                "missingItems": ["具体投资预算未提及"],
                "fragmentIds": [2],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "致谢与Q&A",
                "keyPoints": ["Q&A 交流环节"],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_1",
            "audience": "公司高管",
            "slideCount": 3,
            "instruction": "突出成效与规划",
        })
        assert res["jobId"] is not None
        job_id = res["jobId"]

        job = coordinator.wait_job(job_id, document_session_id="ppt_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["schemaVersion"] == "ppt.material_outline.v1"
        assert result["slideCount"] == 3
        assert len(result["slides"]) == 3
        assert result["slides"][0]["pageRole"] == "cover"
        assert result["slides"][1]["pageRole"] == "content"
        assert len(result["slides"][1]["sources"]) >= 1
        assert result["slides"][1]["sources"][0]["fileName"] == "项目建设成果.docx"
        assert "二期规划" in result["slides"][1]["sources"][0]["text"]
        assert result["slides"][1]["missingItems"] == ["具体投资预算未提及"]
        assert result["slides"][2]["pageRole"] == "backcover"
        assert "basisMaterials" in result
        assert len(result["basisMaterials"]) == 1


def test_ppt_material_outline_slide_count_mismatch_rejected(outline_setup):
    store, coordinator = outline_setup

    # Model returned 2 slides when 3 requested
    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "突出成效与规划",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目建设阶段汇报",
                "keyPoints": ["汇报主题与目标"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "一期建设核心成效",
                "keyPoints": ["业务网点全覆盖"],
                "missingItems": [],
                "fragmentIds": [1],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_mismatch",
            "audience": "公司高管",
            "slideCount": 3,
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "failed"
        assert "页数不匹配" in job["error"]["message"]


def test_ppt_material_outline_invalid_fragment_id_rejected(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "公司高管",
        "slideCount": 3,
        "instruction": "",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "封面",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [9999],  # Non-existent fragment ID!
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "正文",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "封底",
                "keyPoints": [],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_client_job_invalid_frag",
            "audience": "公司高管",
            "slideCount": 3,
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "failed"
        assert "出处" in job["error"]["message"]


def test_ppt_material_outline_job_id_conflict(outline_setup):
    store, coordinator = outline_setup
    payload = {
        "documentSessionId": "ppt_test_sess",
        "clientJobId": "ppt_job_dup",
        "audience": "受众A",
        "slideCount": 3,
    }
    with patch.object(coordinator, "_call_provider_model", return_value="{}"):
        coordinator.submit_job(payload)
        # Same job id with different slide count
        payload2 = dict(payload, slideCount=5)
        with pytest.raises(AdapterError) as exc_info:
            coordinator.submit_job(payload2)
        assert exc_info.value.code == "MATERIAL_OUTLINE_JOB_CONFLICT"


def test_ppt_material_outline_with_user_facts(outline_setup):
    store, coordinator = outline_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "ppt.material_outline.v1",
        "audience": "技术评审",
        "slideCount": 3,
        "instruction": "包含补充事实",
        "slides": [
            {
                "pageIndex": 1,
                "pageRole": "cover",
                "title": "项目汇报",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": ["user-fact"],
            },
            {
                "pageIndex": 2,
                "pageRole": "content",
                "title": "架构内容",
                "keyPoints": ["要点"],
                "missingItems": [],
                "fragmentIds": [1],
            },
            {
                "pageIndex": 3,
                "pageRole": "backcover",
                "title": "结束",
                "keyPoints": [],
                "missingItems": [],
                "fragmentIds": [],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "ppt_test_sess",
            "clientJobId": "ppt_job_user_facts",
            "audience": "技术评审",
            "slideCount": 3,
            "userFacts": "【事实】预算为500万元",
        })
        job = coordinator.wait_job(res["jobId"], document_session_id="ppt_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["slides"][0]["sources"][0]["sourceType"] == "user"
        assert result["slides"][0]["sources"][0]["fileName"] == "用户补充事实"
        assert "500万元" in result["slides"][0]["sources"][0]["text"]

