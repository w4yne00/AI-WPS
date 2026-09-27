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
from app.services.excel.material_store import ExcelMaterialStore
from app.services.excel.material_ledger import ExcelMaterialLedgerCoordinator
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
      <w:r><w:t>第一章 建设任务</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>信息化部负责基础网络改造，于2026年10月完成，交付验收报告。安全组负责安全审计整改，交付整改台账。</w:t></w:r>
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
def ledger_setup():
    temp_dir = Path(tempfile.mkdtemp(prefix="ai_wps_test_ledger_"))
    store = ExcelMaterialStore(base_dir=temp_dir / "excel", word_base_dir=temp_dir / "word")
    coordinator = ExcelMaterialLedgerCoordinator(store=store)

    raw_bytes = build_docx()
    store.import_material(
        session_id="excel_test_sess",
        doc_identity="full:/test/doc.xlsx",
        file_name="建设任务.docx",
        content_base64=base64.b64encode(raw_bytes).decode("ascii"),
    )

    yield store, coordinator
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel_material_ledger_header_mapping_and_rows(ledger_setup):
    store, coordinator = ledger_setup

    sample_provider_response = json.dumps({
        "schemaVersion": "excel.material_ledger.v1",
        "rows": [
            {
                "values": {
                    "工作事项": "基础网络改造",
                    "责任部门": "信息化部",
                    "完成时间": "2026年10月",
                    "交付物验收": "验收报告",
                },
                "missingFields": [],
                "isDuplicate": False,
                "duplicateOfIndex": None,
                "duplicateReason": "",
                "fragmentIds": [1],
            },
            {
                "values": {
                    "工作事项": "安全审计整改",
                    "责任部门": "安全组",
                    "完成时间": "",
                    "交付物验收": "整改台账",
                },
                "missingFields": ["完成时间"],
                "isDuplicate": True,
                "duplicateOfIndex": 0,
                "duplicateReason": "与第一项网络任务同属安全配套",
                "fragmentIds": [1],
            },
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=sample_provider_response):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_job_1",
            "headers": ["工作事项", "责任部门", "完成时间", "交付物验收"],
            "instruction": "按章节提取任务",
        })
        job_id = res["jobId"]
        job = coordinator.wait_job(job_id, "excel_test_sess")
        assert job["status"] == "completed"
        result = job["result"]
        assert result["headers"] == ["工作事项", "责任部门", "完成时间", "交付物验收"]
        assert len(result["rows"]) == 2
        # Check first row
        row1 = result["rows"][0]
        assert row1["values"]["工作事项"] == "基础网络改造"
        assert row1["missingFields"] == []
        assert row1["isDuplicate"] is False
        # Check second row (missing field and duplicate not merged)
        row2 = result["rows"][1]
        assert row2["values"]["工作事项"] == "安全审计整改"
        assert row2["values"]["完成时间"] == ""
        assert row2["missingFields"] == ["完成时间"]
        assert row2["isDuplicate"] is True
        assert row2["duplicateOfIndex"] == 0
        assert "安全配套" in row2["duplicateReason"]
        assert len(row2["sources"]) > 0
        assert row2["sources"][0]["fileName"] == "建设任务.docx"
        # Check basis materials
        assert len(result["basisMaterials"]) == 1
        assert result["basisMaterials"][0]["fileName"] == "建设任务.docx"


def test_excel_material_ledger_empty_materials_rejected():
    temp_dir = Path(tempfile.mkdtemp())
    store = ExcelMaterialStore(base_dir=temp_dir / "excel", word_base_dir=temp_dir / "word")
    coordinator = ExcelMaterialLedgerCoordinator(store=store)

    with pytest.raises(AdapterError) as exc_info:
        coordinator.submit_job({
            "documentSessionId": "empty_session",
            "clientJobId": "job_empty",
            "headers": ["工作事项"],
        })
    assert exc_info.value.code in ("MATERIAL_NOT_FOUND", "EMPTY_MATERIAL")
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel_material_ledger_invalid_fragment_rejected(ledger_setup):
    store, coordinator = ledger_setup

    invalid_fragment_response = json.dumps({
        "schemaVersion": "excel.material_ledger.v1",
        "rows": [
            {
                "values": {"工作事项": "伪造任务"},
                "missingFields": [],
                "isDuplicate": False,
                "duplicateOfIndex": None,
                "duplicateReason": "",
                "fragmentIds": [99999],  # Does not exist
            }
        ],
    })

    with patch.object(coordinator, "_call_provider_model", return_value=invalid_fragment_response):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_job_invalid",
            "headers": ["工作事项"],
        })
        job = coordinator.wait_job(res["jobId"], "excel_test_sess")
        assert job["status"] == "failed"
        err_msg = str(job.get("error", ""))
        assert "出处" in err_msg or "片段" in err_msg or "MATERIAL_LEDGER_INVALID_SOURCE" in err_msg


def test_excel_material_ledger_cancel_job(ledger_setup):
    import time
    store, coordinator = ledger_setup

    def slow_call(*args, **kwargs):
        time.sleep(2.0)
        return "{}"

    with patch.object(coordinator, "_call_provider_model", side_effect=slow_call):
        res = coordinator.submit_job({
            "documentSessionId": "excel_test_sess",
            "clientJobId": "client_cancel",
            "headers": ["工作事项"],
        })
        job_id = res["jobId"]
        cancelled = coordinator.cancel_job(job_id, "excel_test_sess")
        assert cancelled["cancelRequested"] is True or cancelled["status"] == "cancelled"
        terminal = coordinator.wait_job(job_id, "excel_test_sess")
        assert terminal["status"] in ("cancelled", "failed")
