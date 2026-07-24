import csv
import io
import threading
import unittest
import warnings
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.writing_policy import imports as writing_policy_imports
from app.services.writing_policy.imports import (
    CSV_MIME,
    IMPORT_COLUMNS,
    XLSX_MIME,
    ImportPreviewStore,
    apply_import_preview,
    build_import_preview,
    export_csv,
    generate_csv_template,
    generate_xlsx_template,
    parse_csv,
    parse_import_file,
    parse_xlsx,
    validate_import_rows,
)
from app.services.writing_policy.models import (
    MAX_CELL_CHARS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    MAX_XLSX_EXPANDED_BYTES,
    WritingPolicyError,
)
from app.services.writing_policy.store import WritingPolicyStore


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def csv_bytes(rows, headers=IMPORT_COLUMNS, encoding="utf-8-sig"):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode(encoding)


EXPECTED_CSV_EXPORT_MARKER = "#AI-WPS-WRITING-POLICY-EXPORT:1"


def marked_csv_bytes(rows, marker=EXPECTED_CSV_EXPORT_MARKER):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([marker])
    writer.writerow(IMPORT_COLUMNS)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def exported_dict_rows(content):
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    marker = next(reader)
    if marker != [EXPECTED_CSV_EXPORT_MARKER]:
        raise AssertionError("missing versioned AI-WPS CSV export marker")
    headers = next(reader)
    return [dict(zip(headers, values)) for values in reader]


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


class WritingPolicyImportTemplateTests(unittest.TestCase):
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
        first_record = next(
            csv.reader(io.StringIO(first_csv.decode("utf-8-sig")))
        )
        self.assertEqual(tuple(first_record), IMPORT_COLUMNS)
        self.assertNotEqual(first_record, [EXPECTED_CSV_EXPORT_MARKER])
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


class WritingPolicyImportParsingTests(unittest.TestCase):
    def assert_error_code(self, code, callback):
        with self.assertRaises(WritingPolicyError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertTrue(raised.exception.message)

    def test_parse_import_file_dispatches_csv_and_xlsx(self):
        csv_rows = parse_import_file("writing_policy.CSV", CSV_MIME, generate_csv_template())
        xlsx_rows = parse_import_file(
            "writing_policy.XLSX", XLSX_MIME, generate_xlsx_template()
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
            self.assertTrue(parse_import_file("writing_policy.csv", mime_type, csv_content))
        for mime_type in (XLSX_MIME, "application/octet-stream", ""):
            self.assertTrue(
                parse_import_file("writing_policy.xlsx", mime_type, xlsx_content)
            )
        for file_name, mime_type, content in (
            ("writing_policy.csv", XLSX_MIME, csv_content),
            ("writing_policy.xlsx", CSV_MIME, xlsx_content),
            ("writing_policy.xlsx", "text/plain", xlsx_content),
            ("writing_policy.csv", "application/pdf", csv_content),
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
            lambda: parse_import_file("writing_policy.xls", "application/vnd.ms-excel", b"x"),
        )
        self.assert_error_code(
            "import_file_too_large",
            lambda: parse_import_file(
                "writing_policy.csv", CSV_MIME, b"x" * (MAX_IMPORT_BYTES + 1)
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
        with self.assertRaises(WritingPolicyError) as raised:
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
            getattr(writing_policy_imports, "MAX_XLSX_WORKSHEET_ELEMENTS", 0),
            185100,
        )
        self.assertGreaterEqual(
            getattr(writing_policy_imports, "MAX_XLSX_WORKSHEET_DEPTH", 0), 6
        )
        with patch.object(
            writing_policy_imports, "MAX_XLSX_WORKSHEET_ELEMENTS", 10, create=True
        ):
            self.assert_error_code(
                "unsafe_xlsx",
                lambda: parse_xlsx(generate_xlsx_template(), "too-many-elements.xlsx"),
            )
        depth = getattr(writing_policy_imports, "MAX_XLSX_WORKSHEET_DEPTH", 32) + 1
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
            getattr(writing_policy_imports, "MAX_XLSX_SHARED_STRING_ITEMS", 0),
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
            writing_policy_imports, "MAX_XLSX_SHARED_STRING_DEPTH", 0
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
            writing_policy_imports, "MAX_XLSX_SHARED_STRING_ELEMENTS", 0
        )
        self.assertGreater(
            element_limit,
            getattr(writing_policy_imports, "MAX_XLSX_SHARED_STRING_ITEMS", 0),
        )
        extra_elements = b"<x/>" * 80
        payload = extend_shared_strings_workbook(
            b"<si>" + extra_elements + b"</si>"
        )
        with patch.object(
            writing_policy_imports, "MAX_XLSX_SHARED_STRING_ELEMENTS", 60, create=True
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
            with self.assertRaises(WritingPolicyError):
                parse_xlsx(payload, "bad.xlsx")


class WritingPolicyImportValidationTests(unittest.TestCase):
    def parse_rows(self, *rows):
        return parse_csv(csv_bytes(list(rows)), "writing_policy.csv")

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
                writing_policy_imports.csv_safe_cell(value),
                "'" + value,
            )
        for value in ("'=already-safe", "'普通文本", "''双引号"):
            self.assertEqual(
                writing_policy_imports.csv_safe_cell(value),
                "'" + value,
            )
        for value in ("普通文本", "1+1", ""):
            self.assertEqual(writing_policy_imports.csv_safe_cell(value), value)
        for value in (
            "=1+1",
            "+cmd",
            "-2+3",
            "@SUM(A1:A2)",
            "'=原始单引号公式文本",
            "'普通文本",
            "''双单引号",
            "普通文本",
            "",
        ):
            self.assertEqual(
                writing_policy_imports.csv_restore_cell(
                    writing_policy_imports.csv_safe_cell(value)
                ),
                value,
            )

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

    def test_valid_items_retain_source_rows_for_preview_without_changing_payloads(self):
        content = csv_bytes(
            [
                [],
                row_values(),
                row_values(**{"标准写法/规则": "第二个标准名称", "别名/禁用写法": ""}),
            ]
        )
        result = validate_import_rows(parse_csv(content, "rows.csv"))

        self.assertEqual([entry["rowNumber"] for entry in result["itemRows"]], [3, 4])
        self.assertEqual(
            [entry["item"] for entry in result["itemRows"]], result["items"]
        )

    def test_versioned_export_marker_restores_values_and_tracks_physical_rows(self):
        protected = row_values(
            **{
                "标准写法/规则": "'=本系统公式文本",
                "备注": "''本系统单引号文本",
            }
        )
        rows = parse_csv(marked_csv_bytes([protected]), "marked.csv")
        self.assertEqual(getattr(rows[0], "_sourceRow"), 3)
        self.assertEqual(rows[0]["标准写法/规则"], "=本系统公式文本")
        self.assertEqual(rows[0]["备注"], "'本系统单引号文本")

        result = validate_import_rows(rows)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["itemRows"][0]["rowNumber"], 3)
        self.assertEqual(result["items"][0]["preferredText"], "=本系统公式文本")
        self.assertEqual(result["items"][0]["note"], "'本系统单引号文本")

    def test_plain_csv_preserves_formula_quote_and_double_quote_prefixes(self):
        rows = parse_csv(
            csv_bytes(
                [
                    row_values(
                        **{
                            "标准写法/规则": "'=外部安全文本",
                            "备注": "''外部双单引号文本",
                        }
                    ),
                    row_values(
                        **{
                            "标准写法/规则": "''外部双单引号标准写法",
                            "别名/禁用写法": "",
                            "备注": "'=外部安全备注",
                        }
                    ),
                ]
            ),
            "external.csv",
        )
        self.assertEqual([getattr(row, "_sourceRow") for row in rows], [2, 3])

        result = validate_import_rows(rows)
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            [item["preferredText"] for item in result["items"]],
            ["'=外部安全文本", "''外部双单引号标准写法"],
        )
        self.assertEqual(
            [item["note"] for item in result["items"]],
            ["''外部双单引号文本", "'=外部安全备注"],
        )

    def test_xlsx_preserves_formula_quote_and_double_quote_prefixes(self):
        for value in ("'=外部安全文本", "''外部双单引号文本"):
            with self.subTest(value=value):
                base = generate_xlsx_template()
                with zipfile.ZipFile(io.BytesIO(base)) as archive:
                    sheet = archive.read("xl/worksheets/sheet1.xml")
                payload = rebuild_zip(
                    base,
                    replacements={
                        "xl/worksheets/sheet1.xml": sheet.replace(
                            "卫星互联网运营管理平台".encode("utf-8"),
                            value.encode("utf-8"),
                            1,
                        )
                    },
                )
                rows = parse_xlsx(payload, "external.xlsx")
                self.assertEqual(getattr(rows[0], "_sourceRow"), 2)
                result = validate_import_rows(rows)
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["items"][0]["preferredText"], value)

    def test_approximate_or_extra_column_export_markers_do_not_trigger_restore(self):
        near_markers = (
            EXPECTED_CSV_EXPORT_MARKER + " ",
            EXPECTED_CSV_EXPORT_MARKER.lower(),
            "#AI-WPS-WRITING-POLICY-EXPORT:2",
        )
        for marker in near_markers:
            with self.subTest(marker=marker):
                with self.assertRaises(WritingPolicyError) as raised:
                    parse_csv(marked_csv_bytes([row_values()], marker=marker), "near.csv")
                self.assertEqual(raised.exception.code, "invalid_import_headers")

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([EXPECTED_CSV_EXPORT_MARKER, "extra"])
        writer.writerow(IMPORT_COLUMNS)
        writer.writerow(row_values())
        with self.assertRaises(WritingPolicyError) as raised:
            parse_csv(output.getvalue().encode("utf-8-sig"), "extra.csv")
        self.assertEqual(raised.exception.code, "invalid_import_headers")


def import_term(preferred_text, aliases=None, forbidden=None, **overrides):
    payload = {
        "type": "term",
        "scope": "global",
        "category": "系统",
        "preferredText": preferred_text,
        "aliases": list(aliases or []),
        "forbiddenVariants": list(forbidden or []),
        "definition": "统一名称说明",
        "contextKeywords": ["平台", "运营"],
        "priority": "high",
        "enabled": True,
        "note": "导入测试",
    }
    payload.update(overrides)
    return payload


def import_style(scope, name, **overrides):
    payload = {
        "type": "style",
        "scope": scope,
        "name": name,
        "ruleText": "先给出结论，再说明依据。",
        "positiveExample": "总体方案已完成。",
        "negativeExample": "经过大量工作终于完成。",
        "contextKeywords": ["汇报", "进展"],
        "alwaysApply": False,
        "priority": "medium",
        "enabled": True,
        "note": "导入测试",
    }
    payload.update(overrides)
    return payload


class WritingPolicyImportLifecycleTests(unittest.TestCase):
    def test_preview_token_is_secret_single_use_and_expires_on_monotonic_clock(self):
        clock = FakeClock()
        items = [import_term("标准名称")]
        with patch(
            "app.services.writing_policy.imports.secrets.token_urlsafe",
            return_value="preview-secret",
        ) as token_urlsafe:
            previews = ImportPreviewStore(clock=clock)
            preview = previews.create(
                "terms.csv",
                items,
                conflicts=[],
                stats={"newCount": 1},
                file_meta={"format": "csv", "rowCount": 1},
            )

        token_urlsafe.assert_called_once_with(24)
        self.assertEqual(preview["previewToken"], "preview-secret")
        self.assertEqual(previews.get("preview-secret")["items"], items)
        self.assertEqual(previews.consume("preview-secret")["items"], items)
        with self.assertRaises(WritingPolicyError) as consumed:
            previews.consume("preview-secret")
        self.assertEqual(consumed.exception.code, "import_preview_not_found")

        second = previews.create("terms.csv", items, conflicts=[])
        clock.advance(600)
        with self.assertRaises(WritingPolicyError) as expired:
            previews.get(second["previewToken"])
        self.assertEqual(expired.exception.code, "import_preview_expired")

    def test_preview_store_is_defensive_bounded_and_never_caches_upload_content(self):
        clock = FakeClock()
        previews = ImportPreviewStore(clock=clock, max_entries=20)
        source_item = import_term("名称0")
        first = previews.create(
            "terms.csv",
            [source_item],
            conflicts=[],
            file_meta={
                "format": "csv",
                "rowCount": 1,
                "contentBase64": "must-not-be-cached",
                "rawBytes": b"must-not-be-cached",
            },
        )
        source_item["preferredText"] = "外部修改"
        cached = previews.get(first["previewToken"])
        self.assertEqual(cached["items"][0]["preferredText"], "名称0")
        self.assertNotIn("contentBase64", repr(previews._entries))
        self.assertNotIn("must-not-be-cached", repr(previews._entries))

        tokens = [first["previewToken"]]
        for index in range(1, 21):
            clock.advance(1)
            tokens.append(
                previews.create(
                    "terms-%d.csv" % index,
                    [import_term("名称%d" % index)],
                    conflicts=[],
                )["previewToken"]
            )
        self.assertEqual(previews.live_count(), 20)
        with self.assertRaises(WritingPolicyError) as evicted:
            previews.get(tokens[0])
        self.assertEqual(evicted.exception.code, "import_preview_not_found")

    def test_concurrent_preview_consume_has_exactly_one_winner(self):
        previews = ImportPreviewStore()
        token = previews.create(
            "terms.csv", [import_term("标准名称")], conflicts=[]
        )["previewToken"]
        barrier = threading.Barrier(8)
        successes = []
        failures = []

        def consume():
            barrier.wait()
            try:
                successes.append(previews.consume(token))
            except WritingPolicyError as exc:
                failures.append(exc.code)

        threads = [threading.Thread(target=consume) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(successes), 1)
        self.assertEqual(failures, ["import_preview_not_found"] * 7)

    def test_preview_classifies_create_update_and_database_conflicts_with_rows(self):
        with TemporaryDirectory() as tmp:
            store = WritingPolicyStore(Path(tmp) / "writing_policies.db")
            existing_term = store.create_item(
                import_term("标准名称", ["已有别名"], ["已有禁用写法"])
            )
            existing_style = store.create_item(
                import_style("word.smart_write", "结论先行")
            )
            validated = {
                "items": [
                    import_term("新增名称"),
                    import_term("标准名称", ["已有别名", "新别名"]),
                    import_term("冲突名称", ["已有禁用写法"]),
                    import_style(
                        "word.smart_write",
                        "结论先行",
                        ruleText="更新后的规则。",
                    ),
                ],
                "itemRows": [
                    {"rowNumber": 2, "item": import_term("新增名称")},
                    {
                        "rowNumber": 3,
                        "item": import_term("标准名称", ["已有别名", "新别名"]),
                    },
                    {
                        "rowNumber": 4,
                        "item": import_term("冲突名称", ["已有禁用写法"]),
                    },
                    {
                        "rowNumber": 5,
                        "item": import_style(
                            "word.smart_write",
                            "结论先行",
                            ruleText="更新后的规则。",
                        ),
                    },
                ],
                "errors": [
                    {"row": 6, "code": "invalid_import_row", "message": "第 6 行：字段无效。"}
                ],
                "rowCount": 5,
            }
            previews = ImportPreviewStore()

            result = build_import_preview(
                store,
                validated,
                {"fileName": "writing_policy.csv", "format": "csv", "rowCount": 5},
                preview_store=previews,
            )

            self.assertEqual(
                {
                    key: result[key]
                    for key in ("newCount", "updateCount", "conflictCount", "errorCount")
                },
                {"newCount": 1, "updateCount": 2, "conflictCount": 1, "errorCount": 1},
            )
            conflict = result["conflicts"][0]
            self.assertEqual(conflict["rowNumber"], 4)
            self.assertEqual(conflict["incomingName"], "冲突名称")
            self.assertEqual(conflict["existingItemId"], existing_term["id"])
            self.assertEqual(conflict["allowedDecisions"], ["keep_existing", "skip"])
            self.assertIn("第 4 行", conflict["message"])
            cached = previews.get(result["previewToken"])
            self.assertEqual(
                [operation["action"] for operation in cached["items"]],
                ["create", "update", "update"],
            )
            self.assertEqual(cached["items"][1]["existingItemId"], existing_term["id"])
            self.assertEqual(cached["items"][2]["existingItemId"], existing_style["id"])

    def test_apply_consumes_preview_and_atomically_creates_updates_and_records_import(self):
        with TemporaryDirectory() as tmp:
            store = WritingPolicyStore(Path(tmp) / "writing_policies.db")
            existing = store.create_item(import_term("标准名称", ["旧别名"]))
            validated = {
                "items": [
                    import_term("标准名称", ["新别名"], note="已更新"),
                    import_style("global", "结论先行"),
                    import_term("冲突名称", ["旧别名"]),
                ],
                "itemRows": [
                    {"rowNumber": 2, "item": import_term("标准名称", ["新别名"], note="已更新")},
                    {"rowNumber": 3, "item": import_style("global", "结论先行")},
                    {"rowNumber": 4, "item": import_term("冲突名称", ["旧别名"])},
                ],
                "errors": [],
                "rowCount": 3,
            }
            previews = ImportPreviewStore()
            preview = build_import_preview(
                store,
                validated,
                {"fileName": "writing_policy.csv", "format": "csv", "rowCount": 3},
                preview_store=previews,
            )

            result = apply_import_preview(
                store,
                preview["previewToken"],
                [{"rowNumber": 4, "decision": "keep_existing"}],
                preview_store=previews,
            )

            self.assertEqual(result["createdCount"], 1)
            self.assertEqual(result["updatedCount"], 1)
            self.assertEqual(result["conflictCount"], 1)
            self.assertEqual(store.get_item(existing["id"])["aliases"], ["新别名"])
            self.assertEqual(store.summary()["totalCount"], 2)
            with self.assertRaises(WritingPolicyError) as reused:
                apply_import_preview(
                    store,
                    preview["previewToken"],
                    [],
                    preview_store=previews,
                )
            self.assertEqual(reused.exception.code, "import_preview_not_found")

    def test_apply_rejects_term_overwrite_decision_after_consuming_token(self):
        with TemporaryDirectory() as tmp:
            store = WritingPolicyStore(Path(tmp) / "writing_policies.db")
            store.create_item(import_term("标准名称", ["已有别名"]))
            validated = {
                "items": [import_term("冲突名称", ["已有别名"])],
                "itemRows": [
                    {"rowNumber": 2, "item": import_term("冲突名称", ["已有别名"])}
                ],
                "errors": [],
                "rowCount": 1,
            }
            previews = ImportPreviewStore()
            preview = build_import_preview(
                store,
                validated,
                {"fileName": "terms.csv", "format": "csv", "rowCount": 1},
                preview_store=previews,
            )

            with self.assertRaises(WritingPolicyError) as invalid:
                apply_import_preview(
                    store,
                    preview["previewToken"],
                    [{"rowNumber": 2, "decision": "overwrite"}],
                    preview_store=previews,
                )
            self.assertEqual(invalid.exception.code, "invalid_import_decision")
            with self.assertRaises(WritingPolicyError) as consumed:
                previews.get(preview["previewToken"])
            self.assertEqual(consumed.exception.code, "import_preview_not_found")

    def test_export_csv_filters_scope_escapes_lists_and_blocks_formulas(self):
        with TemporaryDirectory() as tmp:
            store = WritingPolicyStore(Path(tmp) / "writing_policies.db")
            store.create_item(
                import_term(
                    "标准|名称\\一期",
                    ["别名|甲", "路径\\乙"],
                    ["禁用|名称"],
                    category="=危险分类",
                    contextKeywords=["关键|词", "路径\\词"],
                )
            )
            store.create_item(import_style("global", "全局规则"))
            store.create_item(import_style("word.smart_write", "编写规则"))

            exported = export_csv(store, "global")
            self.assertTrue(exported.startswith(b"\xef\xbb\xbf"))
            rows = exported_dict_rows(exported)
            self.assertEqual(len(rows), 2)
            term_row = next(row for row in rows if row["类型"] == "术语")
            self.assertEqual(term_row["名称"], "'=危险分类")
            self.assertEqual(term_row["标准写法/规则"], r"标准|名称\一期")

            validation = validate_import_rows(parse_csv(exported, "export.csv"))
            exported_term = next(item for item in validation["items"] if item["type"] == "term")
            self.assertEqual(exported_term["aliases"], ["别名|甲", r"路径\乙"])
            self.assertEqual(exported_term["forbiddenVariants"], ["禁用|名称"])
            self.assertEqual(exported_term["contextKeywords"], ["关键|词", r"路径\词"])

            task_rows = exported_dict_rows(export_csv(store, "word.smart_write"))
            self.assertEqual([row["名称"] for row in task_rows], ["编写规则"])

    def test_export_csv_formula_escaping_round_trips_every_business_field(self):
        with TemporaryDirectory() as tmp:
            store = WritingPolicyStore(Path(tmp) / "writing_policies.db")
            term = import_term(
                "=标准写法",
                ["+别名首项", "'原始单引号别名"],
                ["-禁用首项", "'原始单引号禁用写法"],
                category="'原始单引号分类",
                contextKeywords=["@关键词首项", "'原始单引号关键词"],
                note="'原始单引号术语备注",
            )
            style = import_style(
                "global",
                "+规则名称",
                ruleText="-规则正文",
                positiveExample="@推荐示例",
                negativeExample="=不推荐示例",
                contextKeywords=["+风格关键词首项", "'原始单引号风格关键词"],
                note="=风格备注",
            )
            store.create_item(term)
            store.create_item(style)

            exported = export_csv(store, "global")
            exported_rows = exported_dict_rows(exported)
            term_csv = next(row for row in exported_rows if row["类型"] == "术语")
            style_csv = next(row for row in exported_rows if row["类型"] == "风格")
            self.assertEqual(term_csv["名称"], "''原始单引号分类")
            self.assertEqual(term_csv["标准写法/规则"], "'=标准写法")
            self.assertEqual(term_csv["关键词"].startswith("'@"), True)
            self.assertEqual(term_csv["备注"], "''原始单引号术语备注")
            self.assertEqual(style_csv["名称"], "'+规则名称")
            self.assertEqual(style_csv["标准写法/规则"], "'-规则正文")
            self.assertEqual(style_csv["推荐示例"], "'@推荐示例")
            self.assertEqual(style_csv["不推荐示例"], "'=不推荐示例")
            self.assertEqual(style_csv["关键词"].startswith("'+"), True)
            self.assertEqual(style_csv["备注"], "'=风格备注")

            validated = validate_import_rows(parse_csv(exported, "export.csv"))
            self.assertEqual(validated["errors"], [])
            round_trip_term = next(
                item for item in validated["items"] if item["type"] == "term"
            )
            round_trip_style = next(
                item for item in validated["items"] if item["type"] == "style"
            )
            for key in (
                "category",
                "preferredText",
                "aliases",
                "forbiddenVariants",
                "contextKeywords",
                "priority",
                "enabled",
                "note",
            ):
                self.assertEqual(round_trip_term[key], term[key], key)
            for key in (
                "scope",
                "name",
                "ruleText",
                "positiveExample",
                "negativeExample",
                "contextKeywords",
                "alwaysApply",
                "priority",
                "enabled",
                "note",
            ):
                self.assertEqual(round_trip_style[key], style[key], key)


if __name__ == "__main__":
    unittest.main()
