import csv
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.writing_policy.roundtrip import (
    ROUNDTRIP_COLUMNS,
    apply_roundtrip_preview,
    build_roundtrip_preview,
    export_roundtrip_csv,
    export_roundtrip_xlsx,
)
from app.services.writing_policy.imports import ImportPreviewStore
from app.services.writing_policy.imports import (
    CSV_MIME,
    XLSX_MIME,
    parse_import_file,
    validate_import_rows,
)
from app.services.writing_policy.models import WritingPolicyError
from app.services.writing_policy.service import WritingPolicyService
from app.services.writing_policy.store import WritingPolicyStore


def _csv_rows(content):
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    marker = next(reader)
    if marker != ["#AI-WPS-WRITING-POLICY-EXPORT:1"]:
        raise AssertionError("missing round-trip export marker")
    headers = next(reader)
    return headers, [dict(zip(headers, row)) for row in reader]


def _xlsx_inline_rows(content):
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")
    from xml.etree import ElementTree

    root = ElementTree.fromstring(sheet)
    rows = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values = []
        for cell in row.findall("x:c", namespace):
            values.append(
                "".join(
                    node.text or ""
                    for node in cell.findall(".//x:is//x:t", namespace)
                )
            )
        rows.append(values)
    return rows


class WritingPolicyRoundTripExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = WritingPolicyStore(
            Path(self.temp_dir.name) / "writing-policies.db"
        )
        self.service = WritingPolicyService(self.store)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csv_and_xlsx_share_metadata_complete_contract_for_both_scopes(self):
        custom = self.store.create_item(
            {
                "type": "style",
                "taskTypes": [
                    "word.smart_write",
                    "word.document_review",
                ],
                "sceneIds": ["yangqi", "cybersecurity"],
                "name": "组织结论先行",
                "ruleText": "先写结论，再写依据。",
                "positiveExample": "",
                "negativeExample": "",
                "contextKeywords": ["汇报"],
                "alwaysApply": False,
                "priority": "high",
                "enabled": True,
                "note": "组织维护",
            }
        )
        self.service.put_preset_operation(
            "term.cyber.001",
            "override",
            {"preferredText": "组织网络安全"},
        )

        effective_csv = export_roundtrip_csv(self.service, "effective")
        organization_csv = export_roundtrip_csv(self.service, "organization")
        effective_headers, effective_rows = _csv_rows(effective_csv)
        organization_headers, organization_rows = _csv_rows(organization_csv)
        xlsx_rows = _xlsx_inline_rows(
            export_roundtrip_xlsx(self.service, "organization")
        )

        self.assertEqual(tuple(effective_headers), ROUNDTRIP_COLUMNS)
        self.assertEqual(tuple(organization_headers), ROUNDTRIP_COLUMNS)
        self.assertEqual(tuple(xlsx_rows[1]), ROUNDTRIP_COLUMNS)
        self.assertEqual(xlsx_rows[2:], [
            [row[column] for column in ROUNDTRIP_COLUMNS]
            for row in organization_rows
        ])

        overridden = next(
            row for row in organization_rows
            if row["关联预置ID"] == "term.cyber.001"
        )
        self.assertEqual(overridden["规范包ID"], "cybersecurity-terminology")
        self.assertTrue(overridden["规范包名称"])
        self.assertTrue(overridden["来源"])
        self.assertTrue(overridden["来源版本"])
        self.assertTrue(overridden["规范包版本"])
        self.assertEqual(overridden["层级"], "组织")
        self.assertEqual(overridden["覆盖状态"], "覆盖")

        exported_custom = next(
            row for row in organization_rows if row["稳定ID"] == custom["id"]
        )
        self.assertEqual(
            exported_custom["任务范围"],
            "word.smart_write|word.document_review",
        )
        self.assertEqual(
            exported_custom["场景范围"],
            "yangqi|cybersecurity",
        )
        self.assertEqual(exported_custom["覆盖状态"], "组织自定义")
        self.assertTrue(
            any(row["稳定ID"] == custom["id"] for row in effective_rows)
        )

    def test_term_definition_survives_export_modify_and_import(self):
        term = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "定义保真术语",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "不能在往返时丢失的术语定义。",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "organization"))
        row = next(dict(value) for value in rows if value["稳定ID"] == term["id"])
        self.assertEqual(row["定义/说明"], "不能在往返时丢失的术语定义。")
        row["备注"] = "仅修改备注"

        previews = ImportPreviewStore()
        preview = build_roundtrip_preview(
            self.service,
            [row],
            {
                "fileName": "definition.csv",
                "format": "csv",
                "rowCount": 1,
                "sha256": "e" * 64,
            },
            previews,
        )
        apply_roundtrip_preview(
            self.store,
            preview["previewToken"],
            "e" * 64,
            previews,
        )

        updated = self.store.get_item(term["id"])
        self.assertEqual(updated["definition"], "不能在往返时丢失的术语定义。")
        self.assertEqual(updated["note"], "仅修改备注")


class WritingPolicyRoundTripPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = WritingPolicyStore(
            Path(self.temp_dir.name) / "writing-policies.db"
        )
        self.service = WritingPolicyService(self.store)
        self.previews = ImportPreviewStore()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preview_classifies_explicit_operations_and_never_deletes_missing_rows(self):
        deleted_item = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "待删除组织术语",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        untouched_item = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "缺行仍保留术语",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        self.service.put_preset_operation(
            "term.cyber.003",
            "override",
            {"preferredText": "待恢复预置术语"},
        )
        _, effective_rows = _csv_rows(
            export_roundtrip_csv(self.service, "effective")
        )
        _, organization_rows = _csv_rows(
            export_roundtrip_csv(self.service, "organization")
        )

        modified = next(
            dict(row) for row in effective_rows
            if row["关联预置ID"] == "term.cyber.001"
        )
        modified["标准写法/规则"] = "组织覆盖后的网络安全"
        disabled = next(
            dict(row) for row in effective_rows
            if row["关联预置ID"] == "term.cyber.002"
        )
        disabled["操作"] = "停用"
        restored = next(
            dict(row) for row in organization_rows
            if row["关联预置ID"] == "term.cyber.003"
        )
        restored["操作"] = "恢复"
        deleted = next(
            dict(row) for row in organization_rows
            if row["稳定ID"] == deleted_item["id"]
        )
        deleted["操作"] = "删除"
        created = dict(deleted)
        created.update(
            {
                "操作": "新增",
                "稳定ID": "",
                "名称": "组织",
                "标准写法/规则": "新增组织术语",
            }
        )

        preview = build_roundtrip_preview(
            self.service,
            [modified, disabled, restored, deleted, created],
            {
                "fileName": "roundtrip.csv",
                "format": "csv",
                "rowCount": 5,
                "sha256": "a" * 64,
            },
            self.previews,
        )

        self.assertEqual(
            {
                key: preview[key]
                for key in (
                    "newCount",
                    "modifyCount",
                    "disableCount",
                    "restoreCount",
                    "deleteCount",
                    "conflictCount",
                    "errorCount",
                )
            },
            {
                "newCount": 1,
                "modifyCount": 1,
                "disableCount": 1,
                "restoreCount": 1,
                "deleteCount": 1,
                "conflictCount": 0,
                "errorCount": 0,
            },
        )
        self.assertEqual(
            [change["action"] for change in preview["changes"]],
            ["modify", "disable", "restore", "delete", "new"],
        )
        self.assertIsNotNone(self.store.get_item(untouched_item["id"]))
        self.assertIsNotNone(self.store.get_item(deleted_item["id"]))
        self.assertEqual(
            self.store.get_preset_operation("term.cyber.003")["operation"],
            "override",
        )

    def test_standard_parser_accepts_csv_and_xlsx_roundtrip_contract(self):
        csv_rows = parse_import_file(
            "roundtrip.csv",
            CSV_MIME,
            export_roundtrip_csv(self.service, "effective"),
        )
        xlsx_rows = parse_import_file(
            "roundtrip.xlsx",
            XLSX_MIME,
            export_roundtrip_xlsx(self.service, "effective"),
        )

        self.assertEqual(csv_rows, xlsx_rows)
        self.assertTrue(csv_rows)
        self.assertEqual(tuple(csv_rows[0]), ROUNDTRIP_COLUMNS)
        validated = validate_import_rows(csv_rows)
        self.assertEqual(validated["schema"], "roundtrip")
        self.assertEqual(validated["rowCount"], len(csv_rows))
        self.assertEqual(validated["rows"][0]["rowNumber"], 3)

    def test_empty_organization_export_still_uses_roundtrip_schema(self):
        for file_name, mime_type, content in (
            (
                "empty.csv",
                CSV_MIME,
                export_roundtrip_csv(self.service, "organization"),
            ),
            (
                "empty.xlsx",
                XLSX_MIME,
                export_roundtrip_xlsx(self.service, "organization"),
            ),
        ):
            with self.subTest(file_name=file_name):
                rows = parse_import_file(file_name, mime_type, content)
                validated = validate_import_rows(rows)
                self.assertEqual(validated["schema"], "roundtrip")
                self.assertEqual(validated["rowCount"], 0)

    def test_preview_separates_database_conflicts_from_row_errors(self):
        self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "已有组织术语",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "effective"))
        template = next(dict(row) for row in rows if row["类型"] == "术语")
        conflict = dict(template)
        conflict.update(
            {
                "操作": "新增",
                "稳定ID": "",
                "关联预置ID": "",
                "规范包ID": "",
                "规范包名称": "",
                "来源": "组织维护",
                "来源版本": "",
                "规范包版本": "",
                "层级": "组织",
                "覆盖状态": "组织自定义",
                "标准写法/规则": "已有组织术语",
            }
        )
        invalid = dict(conflict)
        invalid["标准写法/规则"] = "非法操作行"
        invalid["操作"] = "静默删除"

        preview = build_roundtrip_preview(
            self.service,
            [conflict, invalid],
            {
                "fileName": "unsafe.csv",
                "format": "csv",
                "rowCount": 2,
                "sha256": "d" * 64,
            },
            self.previews,
        )

        self.assertEqual(preview["conflictCount"], 1)
        self.assertEqual(preview["errorCount"], 1)
        self.assertEqual(
            preview["conflicts"][0]["code"],
            "term_text_conflict",
        )
        self.assertEqual(
            preview["errors"][0]["code"],
            "invalid_roundtrip_operation",
        )
        with self.assertRaises(WritingPolicyError) as blocked:
            apply_roundtrip_preview(
                self.store,
                preview["previewToken"],
                "d" * 64,
                self.previews,
            )
        self.assertEqual(blocked.exception.code, "import_preview_has_errors")

    def test_preview_reports_storage_validation_errors_before_confirmation(self):
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "effective"))
        invalid = next(dict(row) for row in rows if row["类型"] == "术语")
        invalid["标准写法/规则"] = ""

        preview = build_roundtrip_preview(
            self.service,
            [invalid],
            {
                "fileName": "invalid.csv",
                "format": "csv",
                "rowCount": 1,
                "sha256": "f" * 64,
            },
            self.previews,
        )

        self.assertEqual(preview["modifyCount"], 0)
        self.assertEqual(preview["errorCount"], 1)
        self.assertEqual(
            preview["errors"][0]["code"],
            "invalid_writing_policy_item",
        )

    def test_explicit_delete_then_create_can_reuse_deleted_term_text(self):
        existing = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "删除后复用",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "原定义",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "organization"))
        deleted = next(
            dict(row) for row in rows if row["稳定ID"] == existing["id"]
        )
        deleted["操作"] = "删除"
        created = dict(deleted)
        created.update(
            {
                "操作": "新增",
                "稳定ID": "",
                "定义/说明": "新定义",
            }
        )

        preview = build_roundtrip_preview(
            self.service,
            [deleted, created],
            {
                "fileName": "replace.csv",
                "format": "csv",
                "rowCount": 2,
                "sha256": "1" * 64,
            },
            self.previews,
        )
        self.assertEqual(preview["deleteCount"], 1)
        self.assertEqual(preview["newCount"], 1)
        self.assertEqual(preview["conflictCount"], 0)

        result = apply_roundtrip_preview(
            self.store,
            preview["previewToken"],
            "1" * 64,
            self.previews,
        )
        self.assertEqual(result["deletedCount"], 1)
        self.assertEqual(result["createdCount"], 1)
        items = self.store.list_items("global", "term")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["definition"], "新定义")


class WritingPolicyRoundTripApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "writing-policies.db"
        self.store = WritingPolicyStore(self.db_path)
        self.service = WritingPolicyService(self.store)
        self.previews = ImportPreviewStore()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_apply_checks_digest_creates_backup_and_commits_all_operation_types(self):
        deleted = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "删除目标",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        self.service.put_preset_operation(
            "term.cyber.003",
            "override",
            {"preferredText": "恢复目标"},
        )
        baseline = self.service._find_preset_item("term.cyber.001")
        override_payload = self.service._preset_term_payload(baseline)
        override_payload["preferredText"] = "事务内覆盖"
        created_payload = dict(override_payload)
        created_payload["preferredText"] = "事务内新增"
        token = self.previews.create(
            "roundtrip.csv",
            [
                {
                    "action": "preset_override",
                    "presetEntryId": "term.cyber.001",
                    "packId": "cybersecurity-terminology",
                    "itemType": "term",
                    "item": override_payload,
                },
                {
                    "action": "preset_disable",
                    "presetEntryId": "term.cyber.002",
                    "packId": "cybersecurity-terminology",
                    "itemType": "term",
                },
                {
                    "action": "preset_restore",
                    "presetEntryId": "term.cyber.003",
                    "itemType": "term",
                },
                {
                    "action": "delete",
                    "existingItemId": deleted["id"],
                    "itemType": "term",
                },
                {"action": "create", "item": created_payload},
            ],
            [],
            stats={
                "newCount": 1,
                "modifyCount": 1,
                "disableCount": 1,
                "restoreCount": 1,
                "deleteCount": 1,
                "conflictCount": 0,
                "errorCount": 0,
            },
            file_meta={
                "fileName": "roundtrip.csv",
                "format": "csv",
                "rowCount": 5,
                "sha256": "b" * 64,
            },
        )["previewToken"]

        with self.assertRaises(WritingPolicyError) as mismatch:
            apply_roundtrip_preview(
                self.store,
                token,
                "c" * 64,
                self.previews,
            )
        self.assertEqual(mismatch.exception.code, "import_digest_mismatch")
        self.assertEqual(self.previews.live_count(), 1)

        result = apply_roundtrip_preview(
            self.store,
            token,
            "b" * 64,
            self.previews,
        )

        self.assertEqual(result["createdCount"], 1)
        self.assertEqual(result["modifiedCount"], 1)
        self.assertEqual(result["disabledCount"], 1)
        self.assertEqual(result["restoredCount"], 1)
        self.assertEqual(result["deletedCount"], 1)
        self.assertEqual(self.previews.live_count(), 0)
        self.assertEqual(
            self.store.get_preset_operation("term.cyber.001")["payload"][
                "preferredText"
            ],
            "事务内覆盖",
        )
        self.assertEqual(
            self.store.get_preset_operation("term.cyber.002")["operation"],
            "disabled",
        )
        with self.assertRaises(WritingPolicyError):
            self.store.get_preset_operation("term.cyber.003")
        with self.assertRaises(WritingPolicyError):
            self.store.get_item(deleted["id"])
        self.assertEqual(
            self.store.list_items("global", "term")[0]["preferredText"],
            "事务内新增",
        )
        backups = list(
            self.db_path.parent.glob(self.db_path.name + ".backup-*")
        )
        self.assertEqual(len(backups), 1)

    def test_any_write_error_rolls_back_the_entire_import_transaction(self):
        valid_item = {
            "type": "term",
            "scope": "global",
            "category": "组织",
            "preferredText": "不得残留的事务条目",
            "aliases": [],
            "forbiddenVariants": [],
            "definition": "",
            "contextKeywords": [],
            "priority": "medium",
            "enabled": True,
            "note": "",
        }
        with self.assertRaises(WritingPolicyError):
            self.store.apply_preview(
                [
                    {"action": "create", "item": valid_item},
                    {
                        "action": "update",
                        "existingItemId": "missing-item",
                        "item": dict(
                            valid_item,
                            preferredText="触发回滚",
                        ),
                    },
                ],
                {
                    "fileName": "rollback.csv",
                    "format": "csv",
                    "rowCount": 2,
                },
            )

        self.assertEqual(self.store.list_items("global", "term"), [])
        with self.store._connect() as connection:
            import_count = connection.execute(
                "SELECT COUNT(*) FROM writing_policy_imports"
            ).fetchone()[0]
        self.assertEqual(import_count, 0)

    def test_apply_rejects_item_changed_after_preview_without_overwriting_it(self):
        existing = self.store.create_item(
            {
                "type": "term",
                "scope": "global",
                "category": "组织",
                "preferredText": "并发检查术语",
                "aliases": [],
                "forbiddenVariants": [],
                "definition": "",
                "contextKeywords": [],
                "priority": "medium",
                "enabled": True,
                "note": "",
            }
        )
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "organization"))
        modified = next(
            dict(row) for row in rows if row["稳定ID"] == existing["id"]
        )
        modified["备注"] = "导入版本"
        preview = build_roundtrip_preview(
            self.service,
            [modified],
            {
                "fileName": "stale.csv",
                "format": "csv",
                "rowCount": 1,
                "sha256": "2" * 64,
            },
            self.previews,
        )
        self.store.update_item(existing["id"], {"note": "人工并发修改"})

        with self.assertRaises(WritingPolicyError) as stale:
            apply_roundtrip_preview(
                self.store,
                preview["previewToken"],
                "2" * 64,
                self.previews,
            )

        self.assertEqual(stale.exception.code, "import_preview_stale")
        self.assertEqual(
            self.store.get_item(existing["id"])["note"],
            "人工并发修改",
        )

    def test_apply_rejects_preset_operation_changed_after_preview(self):
        _, rows = _csv_rows(export_roundtrip_csv(self.service, "effective"))
        modified = next(
            dict(row)
            for row in rows
            if row["关联预置ID"] == "term.cyber.001"
        )
        modified["标准写法/规则"] = "导入覆盖值"
        preview = build_roundtrip_preview(
            self.service,
            [modified],
            {
                "fileName": "stale-preset.csv",
                "format": "csv",
                "rowCount": 1,
                "sha256": "3" * 64,
            },
            self.previews,
        )
        self.service.put_preset_operation("term.cyber.001", "disabled", None)

        with self.assertRaises(WritingPolicyError) as stale:
            apply_roundtrip_preview(
                self.store,
                preview["previewToken"],
                "3" * 64,
                self.previews,
            )

        self.assertEqual(stale.exception.code, "import_preview_stale")
        self.assertEqual(
            self.store.get_preset_operation("term.cyber.001")["operation"],
            "disabled",
        )


if __name__ == "__main__":
    unittest.main()
