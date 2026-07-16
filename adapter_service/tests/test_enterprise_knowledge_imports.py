import csv
import io
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.services.enterprise_knowledge import imports as knowledge_imports
from app.services.enterprise_knowledge.imports import (
    CSV_MIME,
    IMPORT_COLUMNS,
    XLSX_MIME,
    generate_csv_template,
    generate_xlsx_template,
    parse_csv,
    parse_import_file,
    parse_xlsx,
    validate_import_rows,
)
from app.services.enterprise_knowledge.models import (
    MAX_CELL_CHARS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    MAX_XLSX_EXPANDED_BYTES,
    KnowledgeError,
)


def csv_bytes(rows, headers=IMPORT_COLUMNS, encoding="utf-8-sig"):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode(encoding)


def row_values(**overrides):
    values = {
        "类型": "术语",
        "适用范围": "全局",
        "名称": "系统",
        "标准写法/规则": "卫星互联网运营管理平台",
        "别名/禁用写法": "别名:卫星网管平台|禁用:卫星网管系统",
        "推荐示例": "",
        "不推荐示例": "",
        "关键词": "运营|网管",
        "优先级": "高",
        "始终应用": "否",
        "启用": "是",
        "备注": "统一平台名称",
    }
    values.update(overrides)
    return [values[column] for column in IMPORT_COLUMNS]


def rebuild_zip(content, replacements=None, additions=None):
    replacements = replacements or {}
    additions = additions or {}
    source = io.BytesIO(content)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as old_archive:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for info in old_archive.infolist():
                data = old_archive.read(info.filename)
                if info.filename in replacements:
                    data = replacements[info.filename]
                copied = zipfile.ZipInfo(info.filename, (1980, 1, 1, 0, 0, 0))
                copied.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(copied, data)
            for name, data in additions.items():
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(info, data)
    return target.getvalue()


def relocated_workbook_bytes():
    with zipfile.ZipFile(io.BytesIO(generate_xlsx_template())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    content_types = parts["[Content_Types].xml"].replace(
        b"/xl/workbook.xml", b"/custom/book.xml"
    ).replace(b"/xl/worksheets/sheet1.xml", b"/custom/sheets/data.xml")
    root_rels = parts["_rels/.rels"].replace(
        b'Target="xl/workbook.xml"', b'Target="custom/book.xml"'
    )
    workbook_rels = parts["xl/_rels/workbook.xml.rels"].replace(
        b'Target="worksheets/sheet1.xml"', b'Target="sheets/data.xml"'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", root_rels),
            ("custom/book.xml", parts["xl/workbook.xml"]),
            ("custom/_rels/book.xml.rels", workbook_rels),
            ("custom/sheets/data.xml", parts["xl/worksheets/sheet1.xml"]),
        ):
            archive.writestr(name, data)
    return output.getvalue()


def mark_first_zip_member_encrypted(content):
    payload = bytearray(content)
    local_offset = payload.find(b"PK\x03\x04")
    central_offset = payload.find(b"PK\x01\x02")
    if local_offset < 0 or central_offset < 0:
        raise AssertionError("test ZIP lacks expected headers")
    local_flags = int.from_bytes(payload[local_offset + 6 : local_offset + 8], "little")
    central_flags = int.from_bytes(
        payload[central_offset + 8 : central_offset + 10], "little"
    )
    payload[local_offset + 6 : local_offset + 8] = (local_flags | 1).to_bytes(2, "little")
    payload[central_offset + 8 : central_offset + 10] = (central_flags | 1).to_bytes(
        2, "little"
    )
    return bytes(payload)


def corrupt_zip_member(content, member_name):
    payload = bytearray(content)
    offset = 0
    encoded_name = member_name.encode("utf-8")
    while True:
        offset = payload.find(b"PK\x01\x02", offset)
        if offset < 0:
            raise AssertionError("test ZIP member was not found")
        name_length = int.from_bytes(payload[offset + 28 : offset + 30], "little")
        extra_length = int.from_bytes(payload[offset + 30 : offset + 32], "little")
        comment_length = int.from_bytes(payload[offset + 32 : offset + 34], "little")
        name_start = offset + 46
        name_end = name_start + name_length
        if bytes(payload[name_start:name_end]) == encoded_name:
            payload[offset + 16] ^= 0x01
            return bytes(payload)
        offset = name_end + extra_length + comment_length


def workbook_with_unsafe_second_sheet(marker):
    base = generate_xlsx_template()
    with zipfile.ZipFile(io.BytesIO(base)) as archive:
        content_types = archive.read("[Content_Types].xml")
        workbook = archive.read("xl/workbook.xml")
        workbook_rels = archive.read("xl/_rels/workbook.xml.rels")
    second_sheet = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b'<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>'
        + marker
        + b'</worksheet>'
    )
    return rebuild_zip(
        base,
        replacements={
            "[Content_Types].xml": content_types.replace(
                b"</Types>",
                b'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            ),
            "xl/workbook.xml": workbook.replace(
                b"</sheets>",
                b'<sheet name="Second" sheetId="2" r:id="rId2"/></sheets>',
            ),
            "xl/_rels/workbook.xml.rels": workbook_rels.replace(
                b"</Relationships>",
                b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>',
            ),
        },
        additions={"xl/worksheets/sheet2.xml": second_sheet},
    )


def shared_string_workbook_bytes():
    content_types = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""
    root_rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Import" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    workbook_rels = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""
    strings = list(IMPORT_COLUMNS) + row_values()
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{0}" uniqueCount="{0}">{1}</sst>'.format(
            len(strings),
            "".join("<si><t>{0}</t></si>".format(value) for value in strings),
        )
    ).encode("utf-8")

    def excel_column(index):
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    cells = []
    for row_index in range(2):
        row_cells = []
        for column_index in range(len(IMPORT_COLUMNS)):
            shared_index = row_index * len(IMPORT_COLUMNS) + column_index
            row_cells.append(
                '<c r="{0}{1}" t="s"><v>{2}</v></c>'.format(
                    excel_column(column_index + 1), row_index + 1, shared_index
                )
            )
        cells.append('<row r="{0}">{1}</row>'.format(row_index + 1, "".join(row_cells)))
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>{0}</sheetData></worksheet>'.format("".join(cells))
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", root_rels),
            ("xl/workbook.xml", workbook),
            ("xl/_rels/workbook.xml.rels", workbook_rels),
            ("xl/sharedStrings.xml", shared_strings),
            ("xl/worksheets/sheet1.xml", sheet),
        ):
            archive.writestr(name, data)
    return output.getvalue()


def extend_shared_strings_workbook(insertion):
    base = shared_string_workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(base)) as archive:
        shared_strings = archive.read("xl/sharedStrings.xml")
    return rebuild_zip(
        base,
        replacements={
            "xl/sharedStrings.xml": shared_strings.replace(
                b"</sst>", insertion + b"</sst>"
            )
        },
    )


class EnterpriseKnowledgeImportTemplateTests(unittest.TestCase):
    def test_generated_templates_are_deterministic_and_share_headers(self):
        first_csv = generate_csv_template()
        first_xlsx = generate_xlsx_template()
        self.assertTrue(first_csv.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(first_csv, generate_csv_template())
        self.assertEqual(first_xlsx, generate_xlsx_template())

        csv_rows = parse_csv(first_csv, "template.csv")
        xlsx_rows = parse_xlsx(first_xlsx, "template.xlsx")
        self.assertEqual(tuple(csv_rows[0].keys()), IMPORT_COLUMNS)
        self.assertEqual(tuple(xlsx_rows[0].keys()), IMPORT_COLUMNS)
        self.assertEqual(csv_rows, xlsx_rows)
        self.assertIn("字面 | 写作 \\|", csv_rows[0]["备注"])
        self.assertIn("反斜杠写作 \\\\", csv_rows[0]["备注"])

    def test_generated_xlsx_has_fixed_zip_times_and_no_macro_parts(self):
        with zipfile.ZipFile(io.BytesIO(generate_xlsx_template())) as archive:
            self.assertTrue(archive.infolist())
            self.assertTrue(
                all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
            )
            self.assertNotIn("xl/vbaProject.bin", archive.namelist())

    def test_parser_supports_excel_shared_strings(self):
        rows = parse_xlsx(shared_string_workbook_bytes(), "shared.xlsx")
        self.assertEqual(rows[0]["标准写法/规则"], "卫星互联网运营管理平台")

    def test_parser_follows_root_office_document_relationship_to_first_sheet(self):
        rows = parse_xlsx(relocated_workbook_bytes(), "relocated.xlsx")
        self.assertEqual(rows[0]["标准写法/规则"], "卫星互联网运营管理平台")

    def test_shared_and_inline_rich_text_exclude_phonetic_runs(self):
        shared = shared_string_workbook_bytes()
        with zipfile.ZipFile(io.BytesIO(shared)) as archive:
            shared_strings = archive.read("xl/sharedStrings.xml")
        shared = rebuild_zip(
            shared,
            replacements={
                "xl/sharedStrings.xml": shared_strings.replace(
                    "<si><t>类型</t></si>".encode("utf-8"),
                    "<si><t>类型</t><rPh><t>leixing</t></rPh></si>".encode(
                        "utf-8"
                    ),
                    1,
                )
            },
        )
        inline = generate_xlsx_template()
        with zipfile.ZipFile(io.BytesIO(inline)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
        inline = rebuild_zip(
            inline,
            replacements={
                "xl/worksheets/sheet1.xml": sheet.replace(
                    "<is><t>类型</t></is>".encode("utf-8"),
                    "<is><r><t>类</t></r><rPh><t>lei</t></rPh><r><t>型</t></r></is>".encode(
                        "utf-8"
                    ),
                    1,
                )
            },
        )
        self.assertEqual(parse_xlsx(shared, "shared.xlsx")[0]["类型"], "术语")
        self.assertEqual(parse_xlsx(inline, "inline.xlsx")[0]["类型"], "术语")


class EnterpriseKnowledgeImportParsingTests(unittest.TestCase):
    def assert_error_code(self, code, callback):
        with self.assertRaises(KnowledgeError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertTrue(raised.exception.message)

    def test_parse_import_file_dispatches_csv_and_xlsx(self):
        csv_rows = parse_import_file("knowledge.CSV", CSV_MIME, generate_csv_template())
        xlsx_rows = parse_import_file(
            "knowledge.XLSX", XLSX_MIME, generate_xlsx_template()
        )
        self.assertEqual(csv_rows, xlsx_rows)

    def test_parse_import_file_validates_extension_and_mime_compatibility(self):
        csv_content = generate_csv_template()
        xlsx_content = generate_xlsx_template()
        for mime_type in (
            CSV_MIME,
            "text/csv; charset=utf-8",
            "text/plain",
            "application/octet-stream",
            "",
        ):
            self.assertTrue(parse_import_file("knowledge.csv", mime_type, csv_content))
        for mime_type in (XLSX_MIME, "application/octet-stream", ""):
            self.assertTrue(
                parse_import_file("knowledge.xlsx", mime_type, xlsx_content)
            )
        for file_name, mime_type, content in (
            ("knowledge.csv", XLSX_MIME, csv_content),
            ("knowledge.xlsx", CSV_MIME, xlsx_content),
            ("knowledge.xlsx", "text/plain", xlsx_content),
            ("knowledge.csv", "application/pdf", csv_content),
        ):
            self.assert_error_code(
                "import_mime_mismatch",
                lambda file_name=file_name, mime_type=mime_type, content=content: parse_import_file(
                    file_name, mime_type, content
                ),
            )

    def test_rejects_unsupported_type_and_files_over_five_megabytes(self):
        self.assert_error_code(
            "unsupported_import_type",
            lambda: parse_import_file("knowledge.xls", "application/vnd.ms-excel", b"x"),
        )
        self.assert_error_code(
            "import_file_too_large",
            lambda: parse_import_file(
                "knowledge.csv", CSV_MIME, b"x" * (MAX_IMPORT_BYTES + 1)
            ),
        )

    def test_csv_requires_utf8_exact_headers_and_consistent_columns(self):
        self.assert_error_code(
            "invalid_import_encoding",
            lambda: parse_csv("类型".encode("gbk"), "bad.csv"),
        )
        wrong_headers = list(IMPORT_COLUMNS)
        wrong_headers[-1] = "其它"
        self.assert_error_code(
            "invalid_import_headers",
            lambda: parse_csv(csv_bytes([row_values()], wrong_headers), "bad.csv"),
        )
        malformed = csv_bytes([row_values()[:-1]])
        self.assert_error_code(
            "invalid_import_row", lambda: parse_csv(malformed, "bad.csv")
        )

    def test_csv_rejects_row_and_cell_budgets_with_chinese_errors(self):
        too_many_rows = [row_values(**{"标准写法/规则": "名称%d" % index}) for index in range(MAX_IMPORT_ROWS + 1)]
        self.assert_error_code(
            "import_row_limit_exceeded",
            lambda: parse_csv(csv_bytes(too_many_rows), "too-many.csv"),
        )
        long_cell = row_values(**{"标准写法/规则": "字" * (MAX_CELL_CHARS + 1)})
        with self.assertRaises(KnowledgeError) as raised:
            parse_csv(csv_bytes([long_cell]), "long.csv")
        self.assertEqual(raised.exception.code, "import_cell_too_long")
        self.assertIn("第 2 行", raised.exception.message)

    def test_xlsx_rejects_macros_external_links_and_unsafe_paths(self):
        base = generate_xlsx_template()
        macro = rebuild_zip(base, additions={"xl/vbaProject.bin": b"macro"})
        external_rels = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="https://example.invalid/book.xlsx" TargetMode="External"/>
</Relationships>"""
        external = rebuild_zip(base, additions={"xl/externalLinks/_rels/externalLink1.xml.rels": external_rels})
        with zipfile.ZipFile(io.BytesIO(base)) as archive:
            workbook_rels = archive.read("xl/_rels/workbook.xml.rels")
        relationship_traversal = rebuild_zip(
            base,
            replacements={
                "xl/_rels/workbook.xml.rels": workbook_rels.replace(
                    b'Target="worksheets/sheet1.xml"', b'Target="../outside.xml"'
                )
            },
        )
        traversal = rebuild_zip(base, additions={"../outside.xml": b"unsafe"})
        absolute = rebuild_zip(base, additions={"/outside.xml": b"unsafe"})
        for payload in (macro, external, relationship_traversal, traversal, absolute):
            self.assert_error_code(
                "unsafe_xlsx",
                lambda payload=payload: parse_import_file("bad.xlsx", XLSX_MIME, payload),
            )

    def test_xlsx_rejects_duplicate_encrypted_backslash_and_drive_members(self):
        base = generate_xlsx_template()
        duplicate = rebuild_zip(base, additions={"[Content_Types].xml": b"duplicate"})
        encrypted = mark_first_zip_member_encrypted(base)
        backslash = rebuild_zip(base, additions={"xl\\shadow.xml": b"unsafe"})
        drive_path = rebuild_zip(base, additions={"C:\\outside.xml": b"unsafe"})
        for payload in (duplicate, encrypted, backslash, drive_path):
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

    def test_xlsx_rejects_formulas_merged_cells_and_doctype(self):
        base = generate_xlsx_template()
        with zipfile.ZipFile(io.BytesIO(base)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
        formula = rebuild_zip(
            base,
            replacements={
                "xl/worksheets/sheet1.xml": sheet.replace(
                    b"</c>", b"<f>1+1</f></c>", 1
                )
            },
        )
        merged = rebuild_zip(
            base,
            replacements={
                "xl/worksheets/sheet1.xml": sheet.replace(
                    b"</worksheet>", b'<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>'
                )
            },
        )
        doctype = rebuild_zip(
            base,
            replacements={
                "xl/worksheets/sheet1.xml": b'<!DOCTYPE x [<!ENTITY y "z">]>' + sheet
            },
        )
        for payload in (formula, merged, doctype):
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

    def test_xlsx_rejects_formula_or_merge_cells_in_non_first_sheet(self):
        formula = workbook_with_unsafe_second_sheet(b"<f>1+1</f>")
        merged = workbook_with_unsafe_second_sheet(
            b'<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>'
        )
        for payload in (formula, merged):
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

    def test_xlsx_enforces_worksheet_element_and_depth_budgets_before_dom_parse(self):
        self.assertGreaterEqual(
            getattr(knowledge_imports, "MAX_XLSX_WORKSHEET_ELEMENTS", 0),
            185100,
        )
        self.assertGreaterEqual(
            getattr(knowledge_imports, "MAX_XLSX_WORKSHEET_DEPTH", 0), 6
        )
        with patch.object(
            knowledge_imports, "MAX_XLSX_WORKSHEET_ELEMENTS", 10, create=True
        ):
            self.assert_error_code(
                "unsafe_xlsx",
                lambda: parse_xlsx(generate_xlsx_template(), "too-many-elements.xlsx"),
            )
        depth = getattr(knowledge_imports, "MAX_XLSX_WORKSHEET_DEPTH", 32) + 1
        deeply_nested = workbook_with_unsafe_second_sheet(
            (b"<x>" * depth) + (b"</x>" * depth)
        )
        self.assert_error_code(
            "unsafe_xlsx",
            lambda: parse_xlsx(deeply_nested, "too-deep.xlsx"),
        )

    def test_shared_strings_rejects_more_than_template_cell_budget(self):
        item_limit = (MAX_IMPORT_ROWS + 1) * len(IMPORT_COLUMNS)
        self.assertEqual(
            getattr(knowledge_imports, "MAX_XLSX_SHARED_STRING_ITEMS", 0),
            item_limit,
        )
        extra_count = item_limit - (len(IMPORT_COLUMNS) * 2) + 1
        extra_items = "".join(
            "<si><t>额外字符串%d</t></si>" % index
            for index in range(extra_count)
        ).encode("utf-8")
        payload = extend_shared_strings_workbook(extra_items)
        self.assert_error_code(
            "unsafe_xlsx",
            lambda: parse_xlsx(payload, "too-many-shared-strings.xlsx"),
        )

    def test_shared_strings_rejects_excessive_xml_depth(self):
        depth_limit = getattr(
            knowledge_imports, "MAX_XLSX_SHARED_STRING_DEPTH", 0
        )
        self.assertGreaterEqual(depth_limit, 4)
        nested = (
            b"<si>"
            + (b"<x>" * depth_limit)
            + "<t>深层文本</t>".encode("utf-8")
            + (b"</x>" * depth_limit)
            + b"</si>"
        )
        payload = extend_shared_strings_workbook(nested)
        self.assert_error_code(
            "unsafe_xlsx",
            lambda: parse_xlsx(payload, "deep-shared-strings.xlsx"),
        )

    def test_shared_strings_rejects_excessive_element_count(self):
        element_limit = getattr(
            knowledge_imports, "MAX_XLSX_SHARED_STRING_ELEMENTS", 0
        )
        self.assertGreater(
            element_limit,
            getattr(knowledge_imports, "MAX_XLSX_SHARED_STRING_ITEMS", 0),
        )
        extra_elements = b"<x/>" * 80
        payload = extend_shared_strings_workbook(
            b"<si>" + extra_elements + b"</si>"
        )
        with patch.object(
            knowledge_imports, "MAX_XLSX_SHARED_STRING_ELEMENTS", 60, create=True
        ):
            self.assert_error_code(
                "unsafe_xlsx",
                lambda: parse_xlsx(payload, "many-shared-elements.xlsx"),
            )

    def test_xlsx_limits_cell_references_rows_and_shared_string_indexes(self):
        base = generate_xlsx_template()
        with zipfile.ZipFile(io.BytesIO(base)) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
        invalid_references = (
            sheet.replace(b'r="A2"', b'r="AAAAAAAA2"', 1),
            sheet.replace(b'r="A2"', b'r="M2"', 1),
            sheet.replace(b'r="A2"', b'r="A5002"', 1),
            sheet.replace(b'<row r="2">', b'<row r="999999999999">', 1),
        )
        for invalid_sheet in invalid_references:
            payload = rebuild_zip(
                base,
                replacements={"xl/worksheets/sheet1.xml": invalid_sheet},
            )
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

        shared = shared_string_workbook_bytes()
        with zipfile.ZipFile(io.BytesIO(shared)) as archive:
            shared_sheet = archive.read("xl/worksheets/sheet1.xml")
        for invalid_index in (b"-1", b"999999999999"):
            payload = rebuild_zip(
                shared,
                replacements={
                    "xl/worksheets/sheet1.xml": shared_sheet.replace(
                        b"<v>12</v>", b"<v>" + invalid_index + b"</v>", 1
                    )
                },
            )
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

    def test_xlsx_rejects_external_link_and_unsafe_relationship_targets(self):
        base = generate_xlsx_template()
        with zipfile.ZipFile(io.BytesIO(base)) as archive:
            workbook_rels = archive.read("xl/_rels/workbook.xml.rels")
        replacements = (
            (
                b"/worksheet\"",
                b"/externalLink\"",
            ),
            (
                b'Target="worksheets/sheet1.xml"',
                b'Target="file:///tmp/sheet1.xml"',
            ),
            (
                b'Target="worksheets/sheet1.xml"',
                b'Target="//server/share/sheet1.xml"',
            ),
            (
                b'Target="worksheets/sheet1.xml"',
                b'Target="\\\\server\\share\\sheet1.xml"',
            ),
            (
                b'Target="worksheets/sheet1.xml"',
                b'Target="worksheets\\sheet1.xml"',
            ),
        )
        for source, target in replacements:
            payload = rebuild_zip(
                base,
                replacements={
                    "xl/_rels/workbook.xml.rels": workbook_rels.replace(
                        source, target
                    )
                },
            )
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bad.xlsx")
            )

    def test_xlsx_rejects_suspicious_compression_and_expanded_budget(self):
        base = generate_xlsx_template()
        compressed_bomb = rebuild_zip(
            base, additions={"xl/media/repeated.bin": b"0" * (1024 * 1024)}
        )
        expanded_bomb = rebuild_zip(
            base,
            additions={"xl/media/large.bin": b"A" * (MAX_XLSX_EXPANDED_BYTES + 1)},
        )
        for payload in (compressed_bomb, expanded_bomb):
            self.assert_error_code(
                "unsafe_xlsx", lambda payload=payload: parse_xlsx(payload, "bomb.xlsx")
            )

    def test_xlsx_reads_every_member_and_rejects_noncanonical_or_duplicate_paths(self):
        base = generate_xlsx_template()
        with_extra = rebuild_zip(
            base, additions={"xl/media/unreferenced.bin": b"0123456789abcdef"}
        )
        corrupt = corrupt_zip_member(with_extra, "xl/media/unreferenced.bin")
        dot_segment = rebuild_zip(base, additions={"xl/./extra.xml": b"x"})
        empty_segment = rebuild_zip(base, additions={"xl//extra.xml": b"x"})
        normalized_duplicate = rebuild_zip(
            base,
            additions={
                "xl/Case.xml": b"first",
                "xl/case.xml": b"second",
            },
        )
        for payload in (corrupt, dot_segment, empty_segment, normalized_duplicate):
            with self.assertRaises(KnowledgeError):
                parse_xlsx(payload, "bad.xlsx")


class EnterpriseKnowledgeImportValidationTests(unittest.TestCase):
    def parse_rows(self, *rows):
        return parse_csv(csv_bytes(list(rows)), "knowledge.csv")

    def test_maps_chinese_term_row_to_stable_payload(self):
        result = validate_import_rows(self.parse_rows(row_values()))
        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["items"][0],
            {
                "type": "term",
                "scope": "global",
                "category": "系统",
                "preferredText": "卫星互联网运营管理平台",
                "aliases": ["卫星网管平台"],
                "forbiddenVariants": ["卫星网管系统"],
                "definition": "",
                "contextKeywords": ["运营", "网管"],
                "priority": "high",
                "enabled": True,
                "note": "统一平台名称",
            },
        )

    def test_list_escaping_preserves_pipe_backslash_and_chinese_colon(self):
        row = row_values(
            **{
                "别名/禁用写法": r"别名:平台\|一期|别名：系统：A|内容别名:正文|禁用:路径\\名称",
                "关键词": r"接口\|协议|路径\\名称",
            }
        )
        result = validate_import_rows(self.parse_rows(row))
        self.assertEqual(result["errors"], [])
        item = result["items"][0]
        self.assertEqual(
            item["aliases"], ["平台|一期", "系统：A", "内容别名:正文"]
        )
        self.assertEqual(item["forbiddenVariants"], [r"路径\名称"])
        self.assertEqual(item["contextKeywords"], ["接口|协议", r"路径\名称"])

    def test_list_escaping_rejects_unknown_and_dangling_escapes(self):
        rows = self.parse_rows(
            row_values(**{"关键词": r"运营\q"}),
            row_values(
                **{
                    "标准写法/规则": "另一个名称",
                    "别名/禁用写法": "别名:悬空\\",
                }
            ),
        )
        result = validate_import_rows(rows)
        self.assertEqual(result["items"], [])
        self.assertEqual([error["row"] for error in result["errors"]], [2, 3])
        self.assertTrue(all("转义" in error["message"] for error in result["errors"]))

    def test_csv_formula_like_import_is_preserved_and_export_helper_quotes_it(self):
        formula_like = "=SUM(A1:A2)"
        row = row_values(**{"标准写法/规则": formula_like})
        parsed = self.parse_rows(row)
        result = validate_import_rows(parsed)
        self.assertEqual(result["items"][0]["preferredText"], formula_like)
        for value in ("=1+1", " +cmd", "-2+3", "\t@SUM(A1:A2)"):
            self.assertEqual(
                knowledge_imports.csv_safe_cell(value),
                "'" + value,
            )
        for value in ("普通文本", "1+1", "'=already-safe", ""):
            self.assertEqual(knowledge_imports.csv_safe_cell(value), value)

    def test_maps_chinese_style_scope_priority_and_booleans(self):
        row = row_values(
            **{
                "类型": "风格",
                "适用范围": "智能编写",
                "名称": "结论先行",
                "标准写法/规则": "先给出结论，再说明依据。",
                "别名/禁用写法": "",
                "推荐示例": "总体方案已完成。",
                "不推荐示例": "经过大量工作终于完成。",
                "关键词": "汇报|进展",
                "优先级": "中",
                "始终应用": "是",
                "启用": "否",
                "备注": "进展材料使用",
            }
        )
        result = validate_import_rows(self.parse_rows(row))
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["items"][0],
            {
                "type": "style",
                "scope": "word.smart_write",
                "name": "结论先行",
                "ruleText": "先给出结论，再说明依据。",
                "positiveExample": "总体方案已完成。",
                "negativeExample": "经过大量工作终于完成。",
                "contextKeywords": ["汇报", "进展"],
                "alwaysApply": True,
                "priority": "medium",
                "enabled": False,
                "note": "进展材料使用",
            },
        )

    def test_accepts_all_document_scopes_and_low_priority(self):
        rows = []
        for index, scope in enumerate(("全局", "智能仿写", "文档审查")):
            rows.append(
                row_values(
                    **{
                        "类型": "风格",
                        "适用范围": scope,
                        "名称": "规则%d" % index,
                        "标准写法/规则": "规则正文%d" % index,
                        "别名/禁用写法": "",
                        "优先级": "低",
                    }
                )
            )
        result = validate_import_rows(self.parse_rows(*rows))
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            [item["scope"] for item in result["items"]],
            ["global", "word.smart_imitation", "word.document_review"],
        )
        self.assertTrue(all(item["priority"] == "low" for item in result["items"]))

    def test_reports_required_scope_boolean_priority_and_unused_field_errors(self):
        rows = self.parse_rows(
            row_values(**{"标准写法/规则": ""}),
            row_values(**{"标准写法/规则": "名称2", "适用范围": "智能编写"}),
            row_values(**{"标准写法/规则": "名称3", "启用": "开"}),
            row_values(**{"标准写法/规则": "名称4", "优先级": "最高"}),
            row_values(
                **{
                    "类型": "风格",
                    "名称": "规则",
                    "标准写法/规则": "规则正文",
                    "别名/禁用写法": "不应填写",
                }
            ),
        )
        result = validate_import_rows(rows)
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["errors"]), 5)
        self.assertEqual([error["row"] for error in result["errors"]], [2, 3, 4, 5, 6])
        self.assertTrue(all(error["message"].startswith("第 ") for error in result["errors"]))

    def test_detects_normalized_duplicate_terms_and_styles(self):
        rows = self.parse_rows(
            row_values(),
            row_values(**{"标准写法/规则": " 卫星互联网运营管理平台 ", "别名/禁用写法": ""}),
            row_values(
                **{
                    "类型": "风格",
                    "适用范围": "文档审查",
                    "名称": "结论先行",
                    "标准写法/规则": "规则一",
                    "别名/禁用写法": "",
                }
            ),
            row_values(
                **{
                    "类型": "风格",
                    "适用范围": "文档审查",
                    "名称": " 结论先行 ",
                    "标准写法/规则": "规则二",
                    "别名/禁用写法": "",
                }
            ),
        )
        result = validate_import_rows(rows)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual([error["row"] for error in result["errors"]], [3, 5])
        self.assertTrue(all(error["code"] == "duplicate_import_row" for error in result["errors"]))

    def test_reports_actual_source_line_after_blank_csv_row(self):
        content = csv_bytes([[], row_values(**{"启用": "开"})])
        result = validate_import_rows(parse_csv(content, "blank-line.csv"))
        self.assertEqual(result["errors"][0]["row"], 3)
        self.assertIn("第 3 行", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
