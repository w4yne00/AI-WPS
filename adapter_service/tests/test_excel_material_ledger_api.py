import base64
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pytest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

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
      <w:r><w:t>信息化部负责基础网络改造，于2026年10月完成，交付验收报告。</w:t></w:r>
    </w:p>
  </w:body>
</w:document>""".encode("utf-8")


def build_docx(document_xml=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("word/document.xml", document_xml or DOCUMENT_XML)
    return output.getvalue()


@pytest.mark.skipif(not (HAS_FASTAPI and HAS_PYDANTIC), reason="fastapi and pydantic required")
def test_fastapi_excel_material_ledger_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import excel as excel_api
    from app.services.excel.material_store import ExcelMaterialStore
    from app.services.excel.material_ledger import ExcelMaterialLedgerCoordinator

    temp_dir = Path(tempfile.mkdtemp(prefix="fastapi_excel_test_"))
    try:
        store = ExcelMaterialStore(base_dir=temp_dir / "excel", word_base_dir=temp_dir / "word")
        coord = ExcelMaterialLedgerCoordinator(store=store)

        orig_store = getattr(excel_api, "excel_material_store", None)
        orig_coord = getattr(excel_api, "excel_material_ledger", None)
        excel_api.excel_material_store = store
        excel_api.excel_material_ledger = coord

        client = TestClient(app)

        # 1. Reusable sources
        res = client.get("/materials/reusable-sources")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "sources" in data["data"]

        # 2. Import material
        docx_b64 = base64.b64encode(build_docx()).decode("ascii")
        res = client.post("/excel/materials/import", json={
            "documentSessionId": "sess_fastapi_1",
            "documentIdentity": "full:/test/doc.xlsx",
            "fileName": "建设任务.docx",
            "contentBase64": docx_b64,
        })
        assert res.status_code == 200
        mat_id = res.json()["data"]["materialId"]
        assert mat_id

        # 3. Get catalog
        res = client.get("/excel/materials/catalog?documentSessionId=sess_fastapi_1")
        assert res.status_code == 200
        catalog = res.json()["data"]
        assert len(catalog["documents"]) == 1

        # 4. Clone from source to another session
        res = client.post("/excel/materials/clone-from-source", json={
            "sourceSessionId": "sess_fastapi_1",
            "targetDocumentSessionId": "sess_fastapi_2",
            "targetDocumentIdentity": "full:/test/doc2.xlsx",
        })
        assert res.status_code == 200
        assert res.json()["data"]["totalDocuments"] == 1

        # 5. Detect conflicts
        res = client.get("/excel/material-ledger/conflicts?documentSessionId=sess_fastapi_1")
        assert res.status_code == 200
        assert "conflicts" in res.json()["data"] or isinstance(res.json()["data"], list)

        # 6. Submit job & Query & Cancel
        sample_model_response = json.dumps({
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
                }
            ],
        })

        with patch.object(coord, "_call_provider_model", return_value=sample_model_response):
            res = client.post("/excel/material-ledger/jobs", json={
                "documentSessionId": "sess_fastapi_1",
                "clientJobId": "fastapi_job_001",
                "headers": ["工作事项", "责任部门", "完成时间", "交付物验收"],
                "instruction": "提取任务",
            })
            assert res.status_code == 200
            job_data = res.json()["data"]
            job_id = job_data["jobId"]

            # Query job
            res = client.get(f"/excel/material-ledger/jobs/{job_id}?documentSessionId=sess_fastapi_1")
            assert res.status_code == 200

            # Cancel job
            res = client.post(f"/excel/material-ledger/jobs/{job_id}/cancel", json={
                "documentSessionId": "sess_fastapi_1",
            })
            assert res.status_code == 200

        # 7. Update material
        res = client.put(f"/excel/materials/{mat_id}", json={
            "documentSessionId": "sess_fastapi_1",
            "fileName": "建设任务_v2.docx",
            "contentBase64": docx_b64,
        })
        assert res.status_code == 200

        # 8. Delete material
        res = client.delete(f"/excel/materials/{mat_id}?documentSessionId=sess_fastapi_1")
        assert res.status_code == 200

        # 9. Bind document
        res = client.post("/excel/materials/bind-document", json={
            "oldDocumentSessionId": "sess_fastapi_2",
            "newDocumentIdentity": "full:/test/doc2_renamed.xlsx",
            "newDocumentSessionId": "sess_fastapi_2_renamed",
        })
        assert res.status_code == 200

        # 10. Oversized payload returns 413
        oversized = "a" * (65 * 1024)
        res = client.post("/excel/material-ledger/jobs", json={
            "documentSessionId": "sess_fastapi_1",
            "clientJobId": "fastapi_job_oversized",
            "instruction": oversized,
        })
        assert res.status_code == 413

    finally:
        if orig_store is not None:
            excel_api.excel_material_store = orig_store
        if orig_coord is not None:
            excel_api.excel_material_ledger = orig_coord
        shutil.rmtree(temp_dir, ignore_errors=True)


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone tests")
class StandaloneExcelMaterialLedgerTestCase(unittest.TestCase):
    def setUp(self):
        import standalone_adapter
        from app.services.excel.material_store import ExcelMaterialStore
        from app.services.excel.material_ledger import ExcelMaterialLedgerCoordinator

        self.temp_dir = Path(tempfile.mkdtemp(prefix="standalone_excel_test_"))
        self.store = ExcelMaterialStore(base_dir=self.temp_dir / "excel", word_base_dir=self.temp_dir / "word")
        self.coordinator = ExcelMaterialLedgerCoordinator(store=self.store)

        self.orig_store = getattr(standalone_adapter, "EXCEL_MATERIAL_STORE", None)
        self.orig_coord = getattr(standalone_adapter, "EXCEL_MATERIAL_LEDGER_COORDINATOR", None)
        standalone_adapter.EXCEL_MATERIAL_STORE = self.store
        standalone_adapter.EXCEL_MATERIAL_LEDGER_COORDINATOR = self.coordinator

    def tearDown(self):
        import standalone_adapter
        if self.orig_store is not None:
            standalone_adapter.EXCEL_MATERIAL_STORE = self.orig_store
        if self.orig_coord is not None:
            standalone_adapter.EXCEL_MATERIAL_LEDGER_COORDINATOR = self.orig_coord
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _invoke(self, method, path, payload=None, headers=None):
        import standalone_adapter

        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = path
        req_headers = {"Content-Length": str(len(raw))}
        if headers:
            req_headers.update(headers)
        handler.headers = req_headers
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)
        getattr(handler, method)()
        return captured

    def test_standalone_excel_material_and_ledger_lifecycle(self):
        # 1. Reusable sources
        res = self._invoke("do_GET", "/materials/reusable-sources")
        self.assertEqual(res["status"], 200)
        self.assertIn("sources", res["body"]["data"])

        # 2. Import material
        docx_b64 = base64.b64encode(build_docx()).decode("ascii")
        res = self._invoke("do_POST", "/excel/materials/import", {
            "documentSessionId": "sess_std_1",
            "documentIdentity": "full:/test/std.xlsx",
            "fileName": "建设任务.docx",
            "contentBase64": docx_b64,
        })
        self.assertEqual(res["status"], 200)
        mat_id = res["body"]["data"]["materialId"]
        self.assertTrue(mat_id)

        # 3. Catalog
        res = self._invoke("do_GET", "/excel/materials/catalog?documentSessionId=sess_std_1")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["body"]["data"]["documents"]), 1)

        # 4. Clone from source
        res = self._invoke("do_POST", "/excel/materials/clone-from-source", {
            "sourceSessionId": "sess_std_1",
            "targetDocumentSessionId": "sess_std_2",
            "targetDocumentIdentity": "full:/test/std2.xlsx",
        })
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["data"]["totalDocuments"], 1)

        # 5. Conflicts
        res = self._invoke("do_GET", "/excel/material-ledger/conflicts?documentSessionId=sess_std_1")
        self.assertEqual(res["status"], 200)

        # 6. Submit job & Query & Cancel
        sample_model_response = json.dumps({
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
                }
            ],
        })

        with patch.object(self.coordinator, "_call_provider_model", return_value=sample_model_response):
            res = self._invoke("do_POST", "/excel/material-ledger/jobs", {
                "documentSessionId": "sess_std_1",
                "clientJobId": "std_job_001",
                "headers": ["工作事项", "责任部门", "完成时间", "交付物验收"],
                "instruction": "提取任务",
            })
            self.assertEqual(res["status"], 200)
            job_id = res["body"]["data"]["jobId"]

            # Query
            res = self._invoke("do_GET", f"/excel/material-ledger/jobs/{job_id}?documentSessionId=sess_std_1")
            self.assertEqual(res["status"], 200)

            # Cancel
            res = self._invoke("do_POST", f"/excel/material-ledger/jobs/{job_id}/cancel", {
                "documentSessionId": "sess_std_1",
            })
            self.assertEqual(res["status"], 200)

        # 7. Update
        res = self._invoke("do_PUT", f"/excel/materials/{mat_id}", {
            "documentSessionId": "sess_std_1",
            "fileName": "建设任务_v2.docx",
            "contentBase64": docx_b64,
        })
        self.assertEqual(res["status"], 200)

        # 8. Delete
        res = self._invoke("do_DELETE", f"/excel/materials/{mat_id}?documentSessionId=sess_std_1")
        self.assertEqual(res["status"], 200)

        # 9. Bind document
        res = self._invoke("do_POST", "/excel/materials/bind-document", {
            "oldDocumentSessionId": "sess_std_2",
            "newDocumentIdentity": "full:/test/std2_renamed.xlsx",
            "newDocumentSessionId": "sess_std_2_renamed",
        })
        self.assertEqual(res["status"], 200)

        # 10. Oversized payload returns 413
        oversized_headers = {"Content-Length": str(65 * 1024)}
        res = self._invoke("do_POST", "/excel/material-ledger/jobs", {}, headers=oversized_headers)
        self.assertEqual(res["status"], 413)

    def test_standalone_busy_guard_blocks_mutations_during_ledger_run(self):
        import threading
        # Import one material first
        docx_b64 = base64.b64encode(build_docx()).decode("ascii")
        res = self._invoke("do_POST", "/excel/materials/import", {
            "documentSessionId": "sess_busy_test",
            "documentIdentity": "full:/test/busy.xlsx",
            "fileName": "建设任务.docx",
            "contentBase64": docx_b64,
        })
        self.assertEqual(res["status"], 200)
        mat_id = res["body"]["data"]["materialId"]

        # Mock provider call to pause so job stays in running state
        started = threading.Event()
        finish = threading.Event()

        def slow_call(*args, **kwargs):
            started.set()
            finish.wait(timeout=5)
            return json.dumps({
                "schemaVersion": "excel.material_ledger.v1",
                "rows": [],
            })

        with patch.object(self.coordinator, "_call_provider_model", side_effect=slow_call):
            submit_res = self._invoke("do_POST", "/excel/material-ledger/jobs", {
                "documentSessionId": "sess_busy_test",
                "clientJobId": "job_busy_001",
                "headers": ["工作事项"],
            })
            self.assertEqual(submit_res["status"], 200)
            self.assertTrue(started.wait(timeout=2))

            # Attempt to update material while job is running -> 409 MATERIAL_COMPOSER_BUSY
            update_res = self._invoke("do_PUT", f"/excel/materials/{mat_id}", {
                "documentSessionId": "sess_busy_test",
                "fileName": "更新.docx",
                "contentBase64": docx_b64,
            })
            self.assertEqual(update_res["status"], 409)
            self.assertEqual(update_res["body"]["errors"][0]["code"], "MATERIAL_COMPOSER_BUSY")

            # Attempt to delete material while job is running -> 409 MATERIAL_COMPOSER_BUSY
            delete_res = self._invoke("do_DELETE", f"/excel/materials/{mat_id}?documentSessionId=sess_busy_test")
            self.assertEqual(delete_res["status"], 409)
            self.assertEqual(delete_res["body"]["errors"][0]["code"], "MATERIAL_COMPOSER_BUSY")

            finish.set()
            terminal = self.coordinator.wait_job("job_busy_001", "sess_busy_test")
            self.assertEqual(terminal["status"], "completed")

