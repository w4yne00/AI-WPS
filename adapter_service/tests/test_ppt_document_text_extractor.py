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
                archive.writestr(
                    "[Content_Types].xml",
                    "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\" />",
                )
                archive.writestr("word/document.xml", document_xml)
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="docx")
            )

        self.assertIn("# 项目概述", result)
        self.assertIn("- 完成接口联调", result)
        self.assertIn("事项 | 状态", result)

    def test_resolves_numeric_style_ids_from_styles_xml(self):
        document_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="2" /></w:pPr><w:r><w:t>数字样式标题</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="normal" /><w:outlineLvl w:val="0" /></w:pPr><w:r><w:t>正文</w:t></w:r></w:p>
  </w:body>
</w:document>'''.encode("utf-8")
        styles_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 1" /></w:style>
</w:styles>'''.encode("utf-8")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.docx"
            with zipfile.ZipFile(str(path), "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\" />")
                archive.writestr("word/document.xml", document_xml)
                archive.writestr("word/styles.xml", styles_xml)
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="docx")
            )

        self.assertIn("# 数字样式标题", result)
        self.assertIn("# 正文", result)

    def test_resolves_heading_name_through_controlled_style_inheritance(self):
        document_xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:pPr><w:pStyle w:val="derived" /></w:pPr><w:r><w:t>继承标题</w:t></w:r></w:p></w:body>
</w:document>'''.encode("utf-8")
        styles_xml = '''<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="base"><w:name w:val="Heading 2" /></w:style>
  <w:style w:type="paragraph" w:styleId="derived"><w:basedOn w:val="base" /></w:style>
</w:styles>'''.encode("utf-8")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.docx"
            with zipfile.ZipFile(str(path), "w") as archive:
                archive.writestr(
                    "[Content_Types].xml",
                    "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\" />",
                )
                archive.writestr("word/document.xml", document_xml)
                archive.writestr("word/styles.xml", styles_xml)
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="docx")
            )

        self.assertIn("## 继承标题", result)

    def test_uses_outline_level_only_for_the_allowed_range(self):
        paragraphs = "".join(
            '<w:p><w:pPr><w:outlineLvl w:val="{0}" /></w:pPr><w:r><w:t>级别{0}</w:t></w:r></w:p>'.format(value)
            for value in (0, 5, 6, 9, -1, "invalid")
        )
        document_xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{0}</w:body></w:document>'.format(
                paragraphs
            )
        ).encode("utf-8")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.docx"
            with zipfile.ZipFile(str(path), "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\" />")
                archive.writestr("word/document.xml", document_xml)
            result = extract_staged_document_text(
                SimpleNamespace(path=path, extension="docx")
            )

        lines = [line for line in result.splitlines() if line]
        self.assertEqual(lines[0], "# 级别0")
        self.assertEqual(lines[1], "###### 级别5")
        for label in ("级别6", "级别9", "级别-1", "级别invalid"):
            matching = [line for line in lines if line == label]
            self.assertEqual(matching, [label])

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
