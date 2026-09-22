import base64
import hashlib
import json
from io import BytesIO
import unittest
import zipfile


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


def _invoke_standalone(module, method, path, payload=None):
    captured = {}
    handler = object.__new__(module.Handler)
    handler.path = path
    raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    handler.headers = {"Content-Length": str(len(raw))}
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

