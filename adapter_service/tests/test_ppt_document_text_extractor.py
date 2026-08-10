import zipfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.core.errors import AdapterError
from app.services.ppt.document_text_extractor import extract_staged_document_text


class PptDocumentTextExtractorTests(unittest.TestCase):
    def test_extracts_utf8_markdown_without_changing_structure(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.md"
            path.write_text("# 标题\n\n- 要点一\n- 要点二\n", encoding="utf-8")
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="md")
            )

        self.assertEqual(result, "# 标题\n\n- 要点一\n- 要点二")

    def test_extracts_docx_headings_numbered_paragraphs_and_tables(self):
        document_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>项目概述</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>完成接口联调</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>事项</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>状态</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  </w:body>
</w:document>'''.encode("utf-8")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.docx"
            with zipfile.ZipFile(str(path), "w") as archive:
                archive.writestr("word/document.xml", document_xml)
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="docx")
            )

        self.assertIn("# 项目概述", result)
        self.assertIn("- 完成接口联调", result)
        self.assertIn("事项 | 状态", result)

    def test_rejects_invalid_docx(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.docx"
            path.write_bytes(b"not-a-docx")
            with self.assertRaises(AdapterError) as raised:
                extract_staged_document_text(
                    SimpleNamespace(path=path, extension="docx")
                )

        self.assertEqual(raised.exception.code, "PPT_DOCUMENT_EXTRACT_FAILED")


if __name__ == "__main__":
    unittest.main()
