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


@pytest.mark.skipif(not (HAS_FASTAPI and HAS_PYDANTIC), reason="fastapi and pydantic required")
def test_fastapi_ppt_material_outline_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import ppt as ppt_api
    from app.services.ppt.material_store import PptMaterialStore
    from app.services.ppt.material_outline import PptMaterialOutlineCoordinator

    temp_dir = Path(tempfile.mkdtemp(prefix="fastapi_ppt_test_"))
    try:
        store = PptMaterialStore(base_dir=temp_dir / "ppt", word_base_dir=temp_dir / "word", excel_base_dir=temp_dir / "excel")
        coord = PptMaterialOutlineCoordinator(store=store)

        orig_store = getattr(ppt_api, "ppt_material_store", None)
        orig_coord = getattr(ppt_api, "ppt_material_outline", None)
        ppt_api.ppt_material_store = store
        ppt_api.ppt_material_outline = coord

        client = TestClient(app)

        # 1. Reusable sources
        res = client.get("/materials/reusable-sources")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "sources" in data["data"]

        # 2. Import material
        docx_b64 = base64.b64encode(build_docx()).decode("ascii")
        res = client.post("/ppt/materials/import", json={
            "documentSessionId": "sess_fastapi_ppt_1",
            "documentIdentity": "full:/test/deck.pptx",
            "fileName": "项目建设成果.docx",
            "contentBase64": docx_b64,
        })
        assert res.status_code == 200
        mat_id = res.json()["data"]["materialId"]
        assert mat_id

        # 3. Get catalog
        res = client.get("/ppt/materials/catalog?documentSessionId=sess_fastapi_ppt_1")
        assert res.status_code == 200
        catalog = res.json()["data"]
        assert len(catalog["documents"]) == 1

        # 4. Clone from source to another session
        res = client.post("/ppt/materials/clone-from-source", json={
            "sourceSessionId": "sess_fastapi_ppt_1",
            "targetDocumentSessionId": "sess_fastapi_ppt_2",
            "targetDocumentIdentity": "full:/test/deck2.pptx",
        })
        assert res.status_code == 200
        assert res.json()["data"]["totalDocuments"] == 1

        # 5. Detect conflicts
        res = client.get("/ppt/material-outline/conflicts?documentSessionId=sess_fastapi_ppt_1")
        assert res.status_code == 200
        res_post = client.post("/ppt/material-outline/conflicts", json={
            "documentSessionId": "sess_fastapi_ppt_1",
            "userFacts": "【事实】预算为500万元",
        })
        assert res_post.status_code == 200

        # 6. Start job
        sample_provider_response = json.dumps({
            "schemaVersion": "ppt.material_outline.v1",
            "audience": "高管",
            "slideCount": 3,
            "instruction": "",
            "slides": [
                {"pageIndex": 1, "pageRole": "cover", "title": "封面", "keyPoints": [], "missingItems": [], "fragmentIds": [1]},
                {"pageIndex": 2, "pageRole": "content", "title": "内容", "keyPoints": [], "missingItems": [], "fragmentIds": [2]},
                {"pageIndex": 3, "pageRole": "backcover", "title": "封底", "keyPoints": [], "missingItems": [], "fragmentIds": []},
            ],
        })
        with patch.object(coord, "_call_provider_model", return_value=sample_provider_response):
            res = client.post("/ppt/material-outline/jobs", json={
                "documentSessionId": "sess_fastapi_ppt_1",
                "clientJobId": "fastapi_job_ppt_1",
                "audience": "高管",
                "slideCount": 3,
            })
            assert res.status_code == 200
            job_id = res.json()["data"]["jobId"]
            assert job_id == "fastapi_job_ppt_1"

            # Query job
            res_query = client.get(f"/ppt/material-outline/jobs/{job_id}?documentSessionId=sess_fastapi_ppt_1")
            assert res_query.status_code == 200
            assert res_query.json()["taskType"] == "ppt.material_outline"

        # 7. Update material
        res = client.put(f"/ppt/materials/{mat_id}", json={
            "documentSessionId": "sess_fastapi_ppt_1",
            "fileName": "项目建设成果_更新.docx",
            "contentBase64": docx_b64,
        })
        assert res.status_code == 200

        # 8. Delete material
        res = client.delete(f"/ppt/materials/{mat_id}?documentSessionId=sess_fastapi_ppt_1")
        assert res.status_code == 200

        # 9. Bind document
        res = client.post("/ppt/materials/bind-document", json={
            "oldDocumentSessionId": "sess_fastapi_ppt_2",
            "newDocumentIdentity": "full:/test/deck2_renamed.pptx",
            "newDocumentSessionId": "sess_fastapi_ppt_2_renamed",
        })
        assert res.status_code == 200

        # 10. Oversized payload returns 413
        oversized = "a" * (65 * 1024)
        res = client.post("/ppt/material-outline/jobs", json={
            "documentSessionId": "sess_fastapi_ppt_1",
            "clientJobId": "fastapi_job_oversized",
            "instruction": oversized,
        })
        assert res.status_code == 413

    finally:
        if orig_store is not None:
            ppt_api.ppt_material_store = orig_store
        if orig_coord is not None:
            ppt_api.ppt_material_outline = orig_coord
        shutil.rmtree(temp_dir, ignore_errors=True)


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for standalone tests")
class StandalonePptMaterialOutlineTestCase(unittest.TestCase):
    def setUp(self):
        import standalone_adapter
        from app.services.ppt.material_store import PptMaterialStore
        from app.services.ppt.material_outline import PptMaterialOutlineCoordinator

        self.temp_dir = Path(tempfile.mkdtemp(prefix="standalone_ppt_test_"))
        self.store = PptMaterialStore(base_dir=self.temp_dir / "ppt", word_base_dir=self.temp_dir / "word", excel_base_dir=self.temp_dir / "excel")
        self.coordinator = PptMaterialOutlineCoordinator(store=self.store)

        self.orig_store = getattr(standalone_adapter, "PPT_MATERIAL_STORE", None)
        self.orig_coord = getattr(standalone_adapter, "PPT_MATERIAL_OUTLINE_COORDINATOR", None)
        standalone_adapter.PPT_MATERIAL_STORE = self.store
        standalone_adapter.PPT_MATERIAL_OUTLINE_COORDINATOR = self.coordinator

    def tearDown(self):
        import standalone_adapter
        if self.orig_store is not None:
            standalone_adapter.PPT_MATERIAL_STORE = self.orig_store
        if self.orig_coord is not None:
            standalone_adapter.PPT_MATERIAL_OUTLINE_COORDINATOR = self.orig_coord
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

    def test_standalone_ppt_material_and_outline_lifecycle(self):
        # 1. Import material
        docx_b64 = base64.b64encode(build_docx()).decode("ascii")
        res = self._invoke("do_POST", "/ppt/materials/import", {
            "documentSessionId": "sess_std_ppt_1",
            "documentIdentity": "full:/test/std.pptx",
            "fileName": "建设成果.docx",
            "contentBase64": docx_b64,
        })
        self.assertEqual(res["status"], 200)
        mat_id = res["body"]["data"]["materialId"]
        self.assertTrue(mat_id)

        # 2. Catalog
        res = self._invoke("do_GET", "/ppt/materials/catalog?documentSessionId=sess_std_ppt_1")
        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["body"]["data"]["documents"]), 1)

        # 3. Clone from source
        res = self._invoke("do_POST", "/ppt/materials/clone-from-source", {
            "sourceSessionId": "sess_std_ppt_1",
            "targetDocumentSessionId": "sess_std_ppt_2",
            "targetDocumentIdentity": "full:/test/std2.pptx",
        })
        self.assertEqual(res["status"], 200)

        # 4. Conflicts
        res = self._invoke("do_GET", "/ppt/material-outline/conflicts?documentSessionId=sess_std_ppt_1")
        self.assertEqual(res["status"], 200)
        res_post = self._invoke("do_POST", "/ppt/material-outline/conflicts", {
            "documentSessionId": "sess_std_ppt_1",
            "userFacts": "【事实】预算为500万元",
        })
        self.assertEqual(res_post["status"], 200)

        # 5. Start job
        sample_provider_response = json.dumps({
            "schemaVersion": "ppt.material_outline.v1",
            "audience": "高管",
            "slideCount": 3,
            "instruction": "",
            "slides": [
                {"pageIndex": 1, "pageRole": "cover", "title": "封面", "keyPoints": [], "missingItems": [], "fragmentIds": [1]},
                {"pageIndex": 2, "pageRole": "content", "title": "内容", "keyPoints": [], "missingItems": [], "fragmentIds": [2]},
                {"pageIndex": 3, "pageRole": "backcover", "title": "封底", "keyPoints": [], "missingItems": [], "fragmentIds": []},
            ],
        })
        with patch.object(self.coordinator, "_call_provider_model", return_value=sample_provider_response):
            res = self._invoke("do_POST", "/ppt/material-outline/jobs", {
                "documentSessionId": "sess_std_ppt_1",
                "clientJobId": "std_job_ppt_1",
                "audience": "高管",
                "slideCount": 3,
            })
            self.assertEqual(res["status"], 200)

            # Query job
            res_query = self._invoke("do_GET", "/ppt/material-outline/jobs/std_job_ppt_1?documentSessionId=sess_std_ppt_1")
            self.assertEqual(res_query["status"], 200)
            self.assertEqual(res_query["body"]["taskType"], "ppt.material_outline")

            # Cancel job
            res_cancel = self._invoke("do_POST", "/ppt/material-outline/jobs/std_job_ppt_1/cancel", {
                "documentSessionId": "sess_std_ppt_1",
            })
            self.assertEqual(res_cancel["status"], 200)

        # 6. Update material
        res = self._invoke("do_PUT", f"/ppt/materials/{mat_id}", {
            "documentSessionId": "sess_std_ppt_1",
            "fileName": "建设成果_更新.docx",
            "contentBase64": docx_b64,
        })
        self.assertEqual(res["status"], 200)

        # 7. Delete material
        res = self._invoke("do_DELETE", f"/ppt/materials/{mat_id}?documentSessionId=sess_std_ppt_1")
        self.assertEqual(res["status"], 200)

        # 8. Bind document
        res = self._invoke("do_POST", "/ppt/materials/bind-document", {
            "oldDocumentSessionId": "sess_std_ppt_2",
            "newDocumentIdentity": "full:/test/std2_renamed.pptx",
            "newDocumentSessionId": "sess_std_ppt_2_renamed",
        })
        self.assertEqual(res["status"], 200)

        # 9. Oversized payload returns 413
        oversized = "a" * (65 * 1024)
        res = self._invoke("do_POST", "/ppt/material-outline/jobs", {
            "documentSessionId": "sess_std_ppt_1",
            "clientJobId": "std_job_oversized",
            "instruction": oversized,
        })
        self.assertEqual(res["status"], 413)


@pytest.mark.parametrize('runtime', ['fastapi', 'standalone'])
def test_source_image_endpoint_checks_session_and_version(tmp_path, runtime):
    from urllib.parse import urlencode
    from tests.test_word_material_document import document, p, PNG
    from app.services.ppt.material_store import PptMaterialStore
    store = PptMaterialStore(tmp_path / 'ppt', tmp_path / 'word', tmp_path / 'excel')
    raw = document(p('图示') + '<w:p><w:r><w:drawing><a:blip r:embed="rId1"/></w:drawing></w:r></w:p>', {
        'word/_rels/document.xml.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/a.png"/></Relationships>', 'word/media/a.png': PNG})
    imported = store.import_request({'documentSessionId': 'a', 'fileName': '图.docx', 'contentBase64': base64.b64encode(raw).decode()})
    catalog, images = store.prepare_full_catalog('a')
    query = {'documentSessionId': 'a', 'materialId': imported['materialId'], 'imageId': images[0]['imageId'], 'updatedAt': catalog['documents'][0]['updatedAt']}
    if runtime == 'fastapi':
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api import ppt
        target, name = ppt, 'ppt_material_store'
        def get(url):
            response = TestClient(app).get(url)
            return response.status_code, response.json()
    else:
        import standalone_adapter
        target, name = standalone_adapter, 'PPT_MATERIAL_STORE'
        def get(url):
            result = StandalonePptMaterialOutlineTestCase()._invoke('do_GET', url)
            return result['status'], result['body']
    with patch.object(target, name, store):
        status, body = get('/ppt/materials/image?' + urlencode(query))
        assert status == 200
        assert base64.b64decode(body['data']['imageDataUri'].split(',')[1]) == PNG
        query['documentSessionId'] = 'other'
        assert get('/ppt/materials/image?' + urlencode(query))[0] == 409
        query['documentSessionId'] = 'a'
        query['updatedAt'] = 'stale'
        assert get('/ppt/materials/image?' + urlencode(query))[0] == 409
