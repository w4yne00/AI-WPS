import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from io import BytesIO
import threading
import unittest
import zipfile
from unittest.mock import patch


CONTENT_TYPES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" />
</Types>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p>
      <w:pPr><w:outlineLvl w:val="0" /></w:pPr>
      <w:r><w:t>第一章 范围</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="0" /><w:numId w:val="1" /></w:numPr></w:pPr>
      <w:r><w:t>保留原文事实</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>责任部门</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>完成时间</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>信息化处</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:r><w:drawing><a:blip r:embed="rId8" /></w:drawing></w:r>
    </w:p>
  </w:body>
</w:document>""".encode("utf-8")


def build_docx(extra_parts=None, document_xml=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("word/document.xml", document_xml or DOCUMENT_XML)
        for name, content in (extra_parts or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def upload_payload(content, file_name="资料.docx", mime_type=""):
    return {
        "fileName": file_name,
        "mimeType": mime_type,
        "sizeBytes": len(content),
        "contentBase64": base64.b64encode(content).decode("ascii"),
        "documentSessionId": "doc-session-1",
    }


class WordMaterialImportApiTests(unittest.TestCase):
    def setUp(self):
        from app.api.word import material_import_service
        material_import_service._session_catalogs.clear()
        material_import_service._materials.clear()

    def test_import_and_view_keeps_source_and_shows_located_reading(self):
        """Dropping heading level, table columns, source location, or unread
        disclosure, or returning a rewritten file, would hide what was read.
        """
        from fastapi.testclient import TestClient

        from app.main import app

        content = build_docx({"word/embeddings/oleObject1.bin": b"not-readable"})
        source_hash = hashlib.sha256(content).hexdigest()
        client = TestClient(app)

        imported = client.post("/word/materials", json=upload_payload(content))

        self.assertEqual(imported.status_code, 200, imported.text)
        body = imported.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertEqual(hashlib.sha256(content).hexdigest(), source_hash)
        self.assertTrue(data["sourceFileUnchanged"])
        self.assertTrue(data["targetDocumentUnchanged"])
        self.assertFalse(data["understandsAllContent"])
        self.assertNotIn("contentBase64", data)
        self.assertFalse(data["limits"]["productConfirmed"])
        self.assertTrue(data["limits"]["characterCountMethod"])
        self.assertGreater(data["limits"]["fileByteLimit"], 0)
        self.assertEqual(data["limits"]["readableCharacterCount"], 24)

        heading = next(block for block in data["blocks"] if block["kind"] == "heading")
        self.assertEqual(heading["text"], "第一章 范围")
        self.assertEqual(heading["level"], 1)
        listed = next(block for block in data["blocks"] if block["kind"] == "list_item")
        self.assertEqual(listed["text"], "保留原文事实")
        table = next(block for block in data["blocks"] if block["kind"] == "table")
        self.assertEqual(
            table["rows"],
            [["责任部门", "完成时间"], ["信息化处", ""]],
        )
        fragment = next(
            item for item in data["fragments"] if item["text"] == "第一章 范围"
        )
        self.assertEqual(fragment["source"]["part"], "word/document.xml")
        self.assertEqual(fragment["source"]["blockIndex"], 0)
        unread = {item["kind"]: item for item in data["unreadRegions"]}
        self.assertGreaterEqual(unread["image"]["count"], 1)
        self.assertGreaterEqual(unread["embedded_attachment"]["count"], 1)
        self.assertIn("未读取", data["disclosure"])
        self.assertNotIn("已理解全部", data["disclosure"])

        viewed = client.get("/word/materials/{0}".format(data["materialId"]))

        self.assertEqual(viewed.status_code, 200, viewed.text)
        viewed_data = viewed.json()["data"]
        self.assertEqual(viewed_data["materialId"], data["materialId"])
        self.assertEqual(viewed_data["blocks"], data["blocks"])
        self.assertEqual(viewed_data["fragments"], data["fragments"])
        self.assertEqual(viewed_data["unreadRegions"], data["unreadRegions"])

    def test_rejects_corrupt_wrong_type_and_over_limit_without_partial_reading(self):
        """Accepting a bad file, or returning a shortened reading, would hide
        that the import did not keep the source intact.
        """
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.ppt import docx_security

        client = TestClient(app)
        corrupt = client.post(
            "/word/materials",
            json=upload_payload(b"this is not a docx", file_name="损坏.docx"),
        )
        wrong_type = client.post(
            "/word/materials",
            json=upload_payload(b"%PDF-1.4", file_name="资料.pdf", mime_type="application/pdf"),
        )
        oversized_text = "甲" * 100001
        over_text = client.post(
            "/word/materials",
            json=upload_payload(
                build_docx(document_xml=_paragraph_document(oversized_text)),
                file_name="超限.docx",
            ),
        )
        with patch.object(docx_security, "DOCX_MAX_PACKAGE_BYTES", 32):
            over_bytes = client.post(
                "/word/materials",
                json=upload_payload(build_docx(), file_name="过大.docx"),
            )

        for response, code in (
            (corrupt, "MATERIAL_FILE_REJECTED"),
            (wrong_type, "MATERIAL_FILE_TYPE_REJECTED"),
            (over_text, "MATERIAL_TEXT_OVER_LIMIT"),
            (over_bytes, "MATERIAL_FILE_TOO_LARGE"),
        ):
            body = response.json()
            self.assertGreaterEqual(response.status_code, 400, response.text)
            self.assertFalse(body["success"])
            self.assertEqual(body["errors"][0]["code"], code)
            self.assertEqual(body["taskType"], "word.material_composer")
            self.assertNotIn("blocks", body.get("data") or {})
            self.assertNotIn(oversized_text[:20], response.text)

    def test_preserves_line_breaks_and_tabs(self):
        from fastapi.testclient import TestClient
        from app.main import app
        content = _paragraph_document("<w:tab/>甲<w:br/>乙<w:tab/>丙<w:br/>".replace("<w:br/>", "</w:t><w:br/><w:t>").replace("<w:tab/>", "</w:t><w:tab/><w:t>"))
        response = TestClient(app).post("/word/materials", json=upload_payload(build_docx(document_xml=content)))
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["blocks"][0]["text"], "\t甲\n乙\t丙\n")
        self.assertEqual(data["limits"]["readableCharacterCount"], 7)

    def test_reads_content_controls_in_order_with_distinct_sources(self):
        from fastapi.testclient import TestClient
        from app.main import app
        paragraph = "<w:p><w:r><w:t>{0}</w:t></w:r></w:p>"
        body = (paragraph.format("前") + "<w:sdt><w:sdtContent>" + paragraph.format("中")
                + "<w:sdt><w:sdtContent>" + paragraph.format("内")
                + "</w:sdtContent></w:sdt></w:sdtContent></w:sdt>" + paragraph.format("后"))
        xml = _paragraph_document("").replace(b"<w:p><w:r><w:t></w:t></w:r></w:p>", body.encode("utf-8"))
        response = TestClient(app).post("/word/materials", json=upload_payload(build_docx(document_xml=xml)))
        self.assertEqual(response.status_code, 200)
        blocks = response.json()["data"]["blocks"]
        self.assertEqual([b["text"] for b in blocks], ["前", "中", "内", "后"])
        self.assertEqual(len({b["blockId"] for b in blocks}), 4)
        self.assertNotEqual(blocks[1]["source"], blocks[2]["source"])

    def test_rejects_expanding_tables_before_allocating_large_grids(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.word import material_import
        client = TestClient(app)
        def upload_table(span, rows, tables=1):
            row = '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="{0}"/></w:tcPr><w:p><w:r><w:t>甲</w:t></w:r></w:p></w:tc></w:tr>'.format(span)
            body = ("<w:tbl>" + row * rows + "</w:tbl>") * tables
            xml = _paragraph_document("").replace(b"<w:p><w:r><w:t></w:t></w:r></w:p>", body.encode("utf-8"))
            return client.post("/word/materials", json=upload_payload(build_docx(document_xml=xml)))
        self.assertEqual(upload_table(2, 2).json()["data"]["blocks"][0]["rows"], [["甲", ""], ["甲", ""]])
        response = upload_table(100000, 1)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["errors"][0]["code"], "MATERIAL_TABLE_OVER_LIMIT")
        with patch.object(material_import, "MATERIAL_IMPORT_MAX_TABLE_CELLS", 3):
            self.assertEqual(upload_table(2, 2).status_code, 413)
            self.assertEqual(upload_table(2, 1, tables=2).status_code, 413)

    def test_standalone_import_and_view_matches_public_reading(self):
        """A standalone-only miss would make the installed adapter hide the reading."""
        import standalone_adapter

        content = build_docx({"word/embeddings/oleObject1.bin": b"not-readable"})
        uploaded = _invoke_standalone(
            standalone_adapter,
            "do_POST",
            "/word/materials",
            upload_payload(content),
        )
        material_id = uploaded["body"]["data"]["materialId"]
        viewed = _invoke_standalone(
            standalone_adapter,
            "do_GET",
            "/word/materials/{0}".format(material_id),
        )

        self.assertEqual(uploaded["status"], 200, json.dumps(uploaded, ensure_ascii=False))
        self.assertEqual(uploaded["body"]["data"]["blocks"][0]["text"], "第一章 范围")
        self.assertEqual(viewed["status"], 200)
        self.assertEqual(viewed["body"]["data"]["materialId"], material_id)
        self.assertFalse(viewed["body"]["data"]["understandsAllContent"])

    def test_multi_material_count_limit_rejected(self):
        from app.core.errors import AdapterError
        from app.services.word.material_import import WordMaterialImportService

        service = WordMaterialImportService()
        session_id = "doc-test-count"
        content = build_docx(document_xml=_paragraph_document("测试正文"))
        for i in range(5):
            service.import_material(upload_payload(content, file_name="doc_{0}.docx".format(i)))
        # Adjust session id for upload payload
        payload_6 = upload_payload(content, file_name="doc_6.docx")
        payload_6["documentSessionId"] = session_id
        # Also ensure previous 5 had session_id
        service = WordMaterialImportService()
        for i in range(5):
            p = upload_payload(content, file_name="doc_{0}.docx".format(i))
            p["documentSessionId"] = session_id
            service.import_material(p)

        with self.assertRaises(AdapterError) as ctx:
            service.import_material(payload_6)
        self.assertEqual(ctx.exception.code, "MATERIAL_COUNT_OVER_LIMIT")
        self.assertEqual(ctx.exception.status_code, 400)
        catalog = service.get_catalog(session_id)
        self.assertEqual(catalog["totalDocuments"], 5)

    def test_concurrent_imports_cannot_exceed_session_limit_or_repeat_fragment_ids(self):
        from app.core.errors import AdapterError
        from app.services.word import material_import

        service = material_import.WordMaterialImportService()
        content = build_docx(document_xml=_paragraph_document("测试正文"))
        for i in range(4):
            service.import_material(upload_payload(content, file_name="doc_{0}.docx".format(i)))

        both_reading = threading.Barrier(2)
        real_read = material_import._read_document

        def paused_read(*args, **kwargs):
            try:
                both_reading.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
            return real_read(*args, **kwargs)

        def import_one(index):
            try:
                return service.import_material(upload_payload(content, file_name="extra_{0}.docx".format(index)))
            except AdapterError as exc:
                return exc.code

        with patch.object(material_import, "_read_document", side_effect=paused_read):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(import_one, (1, 2)))

        self.assertEqual(sum(isinstance(outcome, dict) for outcome in outcomes), 1)
        self.assertEqual(outcomes.count("MATERIAL_COUNT_OVER_LIMIT"), 1)
        catalog = service.get_session_catalog("doc-session-1")
        self.assertEqual(catalog["totalDocuments"], 5)
        fragment_ids = [item["fragmentId"] for item in catalog["fragmentsList"]]
        self.assertEqual(len(fragment_ids), len(set(fragment_ids)))

    def test_multi_material_cumulative_text_limit_rejected(self):
        from app.core.errors import AdapterError
        from app.services.word.material_import import WordMaterialImportService

        service = WordMaterialImportService()
        session_id = "doc-test-cumulative-text"
        doc_60k = build_docx(document_xml=_paragraph_document("中" * 60000))
        doc_45k = build_docx(document_xml=_paragraph_document("华" * 45000))

        p1 = upload_payload(doc_60k, file_name="part1.docx")
        p1["documentSessionId"] = session_id
        service.import_material(p1)

        p2 = upload_payload(doc_45k, file_name="part2.docx")
        p2["documentSessionId"] = session_id
        with self.assertRaises(AdapterError) as ctx:
            service.import_material(p2)
        self.assertEqual(ctx.exception.code, "MATERIAL_TEXT_OVER_LIMIT")
        self.assertEqual(ctx.exception.status_code, 413)

        catalog = service.get_catalog(session_id)
        self.assertEqual(catalog["totalDocuments"], 1)
        self.assertEqual(catalog["totalCharacters"], 60000)

    def test_long_paragraph_and_table_cell_keep_all_original_text_in_bounded_fragments(self):
        from app.services.word.material_import import WordMaterialImportService

        paragraph_text = "甲" * 5000
        cell_text = "乙" * 5000
        xml = ("<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
               "<w:body><w:p><w:r><w:t>{0}</w:t></w:r></w:p>"
               "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>{1}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
               "</w:body></w:document>").format(paragraph_text, cell_text).encode("utf-8")
        imported = WordMaterialImportService().import_material(upload_payload(build_docx(document_xml=xml)))
        paragraphs = [f for f in imported["fragments"] if f["kind"] == "paragraph"]
        cells = [f for f in imported["fragments"] if f["kind"] == "table_cell"]

        self.assertEqual("".join(f["text"] for f in paragraphs), paragraph_text)
        self.assertEqual("".join(f["text"] for f in cells), cell_text)
        self.assertTrue(all(len(f["text"]) < 1000 for f in paragraphs + cells))
        self.assertEqual(imported["limits"]["readableCharacterCount"], 10000)
        ids = [f["fragmentId"] for f in imported["fragments"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_multi_material_catalog_aggregation_and_toc(self):
        from app.services.word.material_import import WordMaterialImportService

        service = WordMaterialImportService()
        session_id = "doc-test-toc"
        xml_1 = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:outlineLvl w:val="0" /></w:pPr><w:r><w:t>第一章 总则</w:t></w:r></w:p>
    <w:p><w:r><w:t>正文1</w:t></w:r></w:p>
  </w:body>
</w:document>""".encode("utf-8")
        xml_2 = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:outlineLvl w:val="0" /></w:pPr><w:r><w:t>第二章 建设方案</w:t></w:r></w:p>
    <w:p><w:r><w:t>正文2</w:t></w:r></w:p>
  </w:body>
</w:document>""".encode("utf-8")

        p1 = upload_payload(build_docx(document_xml=xml_1), file_name="file1.docx")
        p1["documentSessionId"] = session_id
        res1 = service.import_material(p1)
        self.assertIn("catalogSummary", res1)

        p2 = upload_payload(build_docx(document_xml=xml_2), file_name="file2.docx")
        p2["documentSessionId"] = session_id
        res2 = service.import_material(p2)
        self.assertIn("catalogSummary", res2)

        catalog = service.get_catalog(session_id)
        self.assertEqual(catalog["totalDocuments"], 2)
        self.assertEqual(len(catalog["documents"]), 2)
        titles = [item["sectionTitle"] for item in catalog["toc"]]
        self.assertIn("第一章 总则", titles)
        self.assertIn("第二章 建设方案", titles)


def _invoke_standalone(module, method, path, payload=None, headers=None):
    captured = {}
    handler = object.__new__(module.Handler)
    handler.path = path
    raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    handler.headers = {"Content-Length": str(len(raw))}
    handler.headers.update(headers or {})
    handler.rfile = BytesIO(raw)
    handler._write = lambda status, body: captured.update(status=status, body=body)
    getattr(handler, method)()
    return captured


def _paragraph_document(text):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>{0}</w:t></w:r></w:p></w:body></w:document>"
    ).format(text).encode("utf-8")
