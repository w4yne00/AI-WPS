import json
import sqlite3
import stat
import threading
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.enterprise_knowledge.models import KnowledgeError
from app.services.enterprise_knowledge.store import EnterpriseKnowledgeStore


def term_payload(preferred_text, aliases=None, forbidden=None, **overrides):
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
        "note": "测试备注",
    }
    payload.update(overrides)
    return payload


def style_payload(scope, name, **overrides):
    payload = {
        "type": "style",
        "scope": scope,
        "name": name,
        "ruleText": "先给出结论，再说明依据。",
        "positiveExample": "总体方案已完成。",
        "negativeExample": "经过大量工作，终于完成总体方案。",
        "contextKeywords": ["汇报", "进展"],
        "alwaysApply": False,
        "priority": "medium",
        "enabled": True,
        "note": "测试备注",
    }
    payload.update(overrides)
    return payload


class EnterpriseKnowledgeStoreTests(unittest.TestCase):
    def make_store(self, root):
        return EnterpriseKnowledgeStore(Path(root) / "enterprise_knowledge.db")

    def test_initializes_three_tables_and_json_list_columns(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            store.create_item(
                term_payload(
                    "卫星互联网运营管理平台",
                    ["卫星网管平台"],
                    ["卫星网管系统"],
                )
            )

            with sqlite3.connect(str(db_path)) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                row = connection.execute(
                    "SELECT aliases, forbidden_variants, context_keywords "
                    "FROM knowledge_terms"
                ).fetchone()

            self.assertTrue(
                {"knowledge_terms", "style_rules", "knowledge_imports"}.issubset(
                    table_names
                )
            )
            self.assertEqual(json.loads(row[0]), ["卫星网管平台"])
            self.assertEqual(json.loads(row[1]), ["卫星网管系统"])
            self.assertEqual(json.loads(row[2]), ["平台", "运营"])

    def test_store_enforces_private_permissions_for_new_and_existing_paths(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_db_path = root / "new-runtime" / "enterprise_knowledge.db"
            EnterpriseKnowledgeStore(new_db_path)

            self.assertEqual(
                stat.S_IMODE(new_db_path.parent.stat().st_mode), 0o700
            )
            self.assertEqual(stat.S_IMODE(new_db_path.stat().st_mode), 0o600)

            existing_parent = root / "existing-runtime"
            existing_parent.mkdir(mode=0o755)
            existing_db_path = existing_parent / "enterprise_knowledge.db"
            sqlite3.connect(str(existing_db_path)).close()
            existing_parent.chmod(0o755)
            existing_db_path.chmod(0o644)

            EnterpriseKnowledgeStore(existing_db_path)

            self.assertEqual(
                stat.S_IMODE(existing_parent.stat().st_mode), 0o700
            )
            self.assertEqual(stat.S_IMODE(existing_db_path.stat().st_mode), 0o600)

    def test_corrupt_json_list_columns_raise_identifiable_error(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            created = store.create_item(term_payload("标准名称", ["旧名称"]))

            corrupt_values = ("{not-json", '{"value":"not-a-list"}', '["有效",1]')
            for corrupt_value in corrupt_values:
                with self.subTest(corrupt_value=corrupt_value):
                    with sqlite3.connect(str(db_path)) as connection:
                        connection.execute(
                            "UPDATE knowledge_terms SET aliases = ? WHERE id = ?",
                            (corrupt_value, created["id"]),
                        )
                    with self.assertRaises(KnowledgeError) as raised:
                        store.get_item(created["id"])
                    self.assertEqual(
                        raised.exception.code, "knowledge_data_corrupt"
                    )

    def test_term_crud_preserves_id_and_uses_utc_z_timestamps(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            created = store.create_item(
                term_payload("卫星互联网运营管理平台", ["卫星网管平台"])
            )

            self.assertEqual(created["type"], "term")
            self.assertEqual(created["scope"], "global")
            self.assertEqual(created["aliases"], ["卫星网管平台"])
            self.assertTrue(created["createdAt"].endswith("Z"))
            self.assertTrue(created["updatedAt"].endswith("Z"))
            self.assertEqual(store.get_item(created["id"]), created)

            updated = store.update_item(
                created["id"],
                {
                    "preferredText": "卫星互联网运营平台",
                    "aliases": ["卫星网管平台", "运营平台"],
                    "enabled": False,
                },
            )
            self.assertEqual(updated["id"], created["id"])
            self.assertEqual(updated["createdAt"], created["createdAt"])
            self.assertEqual(updated["preferredText"], "卫星互联网运营平台")
            self.assertFalse(updated["enabled"])

            deleted = store.delete_item(created["id"])
            self.assertEqual(deleted["id"], created["id"])
            with self.assertRaises(KnowledgeError) as raised:
                store.get_item(created["id"])
            self.assertEqual(raised.exception.code, "knowledge_item_not_found")

    def test_term_tokens_conflict_across_preferred_aliases_and_forbidden_variants(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            store.create_item(
                term_payload(
                    "Satellite Platform",
                    ["Legacy Name"],
                    ["Wrong Name"],
                )
            )

            conflicting_payloads = (
                term_payload("ＳＡＴＥＬＬＩＴＥ   platform"),
                term_payload("Another Name", [" legacy   NAME "]),
                term_payload("Third Name", forbidden=["wrong name"]),
                term_payload("Fourth Name", ["Satellite Platform"]),
                term_payload("Fifth Name", forbidden=["Legacy Name"]),
            )
            for payload in conflicting_payloads:
                with self.subTest(payload=payload):
                    with self.assertRaises(KnowledgeError) as raised:
                        store.create_item(payload)
                    self.assertEqual(raised.exception.code, "term_text_conflict")

    def test_term_create_rejects_normalized_overlap_inside_one_item(self):
        payloads = (
            term_payload("Satellite Platform", ["ＳＡＴＥＬＬＩＴＥ   platform"]),
            term_payload("标准名称", ["旧名称"], [" 旧名称 "]),
            term_payload("标准名称", forbidden=[" 标准名称 "]),
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                with TemporaryDirectory() as tmp:
                    store = self.make_store(tmp)
                    with self.assertRaises(KnowledgeError) as raised:
                        store.create_item(payload)
                    self.assertEqual(raised.exception.code, "term_text_conflict")

    def test_term_update_rejects_normalized_overlap_inside_one_item(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            created = store.create_item(term_payload("标准名称", ["旧名称"]))

            with self.assertRaises(KnowledgeError) as raised:
                store.update_item(
                    created["id"],
                    {"forbiddenVariants": [" 旧名称 "]},
                )
            self.assertEqual(raised.exception.code, "term_text_conflict")
            self.assertEqual(store.get_item(created["id"])["forbiddenVariants"], [])

    def test_atomic_apply_rejects_internal_overlap_and_rolls_back_import(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)

            with self.assertRaises(KnowledgeError) as raised:
                store.apply_items_atomically(
                    [
                        term_payload("可写入名称"),
                        term_payload("冲突名称", ["旧名称"], [" 旧名称 "]),
                    ],
                    {"fileName": "terms.csv", "format": "csv", "rowCount": 2},
                )
            self.assertEqual(raised.exception.code, "term_text_conflict")
            self.assertEqual(store.summary()["totalCount"], 0)
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 0)

    def test_term_update_checks_conflicts_but_ignores_own_tokens(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            first = store.create_item(term_payload("标准名称", ["旧名称"]))
            second = store.create_item(term_payload("另一名称", ["另一个别名"]))

            unchanged = store.update_item(first["id"], {"note": "更新备注"})
            self.assertEqual(unchanged["preferredText"], "标准名称")
            with self.assertRaises(KnowledgeError) as raised:
                store.update_item(second["id"], {"aliases": [" 旧名称 "]})
            self.assertEqual(raised.exception.code, "term_text_conflict")

    def test_terms_are_global_only_and_unknown_scopes_are_rejected(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            with self.assertRaises(KnowledgeError) as term_error:
                store.create_item(
                    term_payload("任务术语", scope="word.smart_write")
                )
            self.assertEqual(term_error.exception.code, "invalid_knowledge_scope")

            with self.assertRaises(KnowledgeError) as style_error:
                store.create_item(style_payload("word.unknown", "未知范围规则"))
            self.assertEqual(style_error.exception.code, "invalid_knowledge_scope")

    def test_style_name_is_unique_within_scope_but_task_can_override_global(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            global_style = store.create_item(style_payload("global", "结论先行"))
            task_style = store.create_item(
                style_payload("word.smart_write", "结论先行")
            )

            self.assertNotEqual(global_style["id"], task_style["id"])
            with self.assertRaises(KnowledgeError) as raised:
                store.create_item(style_payload("word.smart_write", "  结论先行  "))
            self.assertEqual(raised.exception.code, "style_name_conflict")

    def test_search_matches_term_and_style_business_fields(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            term = store.create_item(
                term_payload("卫星互联网运营管理平台", ["卫星网管平台"])
            )
            style = store.create_item(
                style_payload(
                    "word.smart_write",
                    "结论先行",
                    ruleText="汇报材料先写项目结论。",
                )
            )

            term_results = store.list_items("global", "term", "网管")
            style_results = store.list_items(
                "word.smart_write", "style", "项目结论"
            )
            missing_results = store.list_items("global", "term", "不存在")

            self.assertEqual([item["id"] for item in term_results], [term["id"]])
            self.assertEqual([item["id"] for item in style_results], [style["id"]])
            self.assertEqual(missing_results, [])

    def test_enabled_items_returns_global_terms_and_relevant_styles_only(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            enabled_term = store.create_item(term_payload("启用术语"))
            store.create_item(term_payload("停用术语", enabled=False))
            global_style = store.create_item(style_payload("global", "全局规则"))
            task_style = store.create_item(
                style_payload("word.smart_write", "编写规则")
            )
            store.create_item(
                style_payload("word.document_review", "审查规则")
            )
            store.create_item(
                style_payload("word.smart_write", "停用规则", enabled=False)
            )

            terms, styles = store.enabled_items("word.smart_write")

            self.assertEqual([item["id"] for item in terms], [enabled_term["id"]])
            self.assertEqual(
                {item["id"] for item in styles},
                {global_style["id"], task_style["id"]},
            )

    def test_apply_items_rolls_back_every_row_and_import_record_on_failure(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            valid = term_payload("标准名称", ["旧名称"])
            conflict = term_payload("旧名称")

            with self.assertRaises(KnowledgeError) as raised:
                store.apply_items_atomically(
                    [valid, conflict],
                    {"fileName": "terms.csv", "format": "csv", "rowCount": 2},
                )
            self.assertEqual(raised.exception.code, "term_text_conflict")
            self.assertEqual(store.summary()["totalCount"], 0)
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 0)

    def test_atomic_apply_loads_existing_term_token_owners_once_for_large_batch(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            store.create_item(term_payload("已有标准名称", ["已有别名"]))
            items = [
                term_payload(
                    "批量标准名称%d" % index,
                    ["批量别名%d" % index],
                    ["批量禁用写法%d" % index],
                )
                for index in range(500)
            ]
            original_loader = store._load_term_token_owners

            with patch.object(
                store,
                "_load_term_token_owners",
                wraps=original_loader,
            ) as load_owners:
                result = store.apply_items_atomically(
                    items,
                    {
                        "fileName": "large-terms.csv",
                        "format": "csv",
                        "rowCount": len(items),
                    },
                )

            self.assertEqual(load_owners.call_count, 1)
            self.assertEqual(len(result["items"]), len(items))
            self.assertEqual(store.summary()["termCount"], len(items) + 1)

    def test_atomic_apply_uses_loaded_owners_for_batch_conflict_and_rolls_back(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            store.create_item(term_payload("已有标准名称", ["已有别名"]))
            original_loader = store._load_term_token_owners

            with patch.object(
                store,
                "_load_term_token_owners",
                wraps=original_loader,
            ) as load_owners:
                with self.assertRaises(KnowledgeError) as raised:
                    store.apply_items_atomically(
                        [
                            term_payload("批次名称一", ["批次共享别名"]),
                            term_payload("批次名称二", forbidden=[" 批次共享别名 "]),
                        ],
                        {
                            "fileName": "conflict.csv",
                            "format": "csv",
                            "rowCount": 2,
                        },
                    )

            self.assertEqual(raised.exception.code, "term_text_conflict")
            self.assertEqual(load_owners.call_count, 1)
            self.assertEqual(store.summary()["termCount"], 1)
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 0)

    def test_apply_items_and_record_import_share_stable_transaction_contracts(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            result = store.apply_items_atomically(
                [
                    term_payload("标准名称"),
                    style_payload("global", "结论先行"),
                ],
                {"fileName": "knowledge.csv", "format": "csv", "rowCount": 2},
            )
            manual_import = store.record_import(
                {"fileName": "manual.csv", "format": "csv", "rowCount": 4},
                {"createdCount": 1, "updatedCount": 2, "conflictCount": 1, "errorCount": 0},
            )

            self.assertEqual(len(result["items"]), 2)
            self.assertEqual(result["import"]["createdCount"], 2)
            self.assertEqual(result["import"]["result"], "success")
            self.assertEqual(manual_import["updatedCount"], 2)
            self.assertTrue(manual_import["importedAt"].endswith("Z"))
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 2)

    def test_summary_reports_counts_latest_update_and_empty_ready_state(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            empty_summary = store.summary()
            self.assertEqual(
                empty_summary,
                {
                    "status": "ready",
                    "totalCount": 0,
                    "enabledCount": 0,
                    "termCount": 0,
                    "styleCount": 0,
                    "updatedAt": "",
                },
            )

            store.create_item(term_payload("标准名称"))
            store.create_item(style_payload("global", "结论先行", enabled=False))
            summary = store.summary()

            self.assertEqual(summary["totalCount"], 2)
            self.assertEqual(summary["enabledCount"], 1)
            self.assertEqual(summary["termCount"], 1)
            self.assertEqual(summary["styleCount"], 1)
            self.assertEqual(summary["status"], "ready")
            self.assertTrue(summary["updatedAt"].endswith("Z"))

    def test_apply_preview_creates_preimport_backup_and_rotates_to_three(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(tmp)

            for index in range(5):
                result = store.apply_preview(
                    [term_payload("名称%d" % index)],
                    {
                        "fileName": "terms-%d.csv" % index,
                        "format": "csv",
                        "rowCount": 1,
                    },
                )
                self.assertEqual(result["createdCount"], 1)

            backups = list(root.glob("enterprise_knowledge.db.backup-*"))
            self.assertEqual(len(backups), 3)
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in backups))
            for backup in backups:
                with sqlite3.connect(str(backup)) as connection:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM knowledge_terms"
                    ).fetchone()[0]
                self.assertLess(count, 5)

    def test_backup_name_collision_keeps_distinct_preimport_snapshots(self):
        class FrozenDatetime:
            @classmethod
            def now(cls, timezone_value):
                del timezone_value
                return real_datetime(2026, 7, 16, 12, 0, 0, 123456)

            @classmethod
            def strptime(cls, value, pattern):
                return real_datetime.strptime(value, pattern)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(tmp)
            with patch(
                "app.services.enterprise_knowledge.store.datetime",
                FrozenDatetime,
            ):
                store.apply_preview(
                    [term_payload("名称一")],
                    {"fileName": "one.csv", "format": "csv", "rowCount": 1},
                )
                store.apply_preview(
                    [term_payload("名称二")],
                    {"fileName": "two.csv", "format": "csv", "rowCount": 1},
                )

            backups = sorted(root.glob("enterprise_knowledge.db.backup-*"))
            self.assertEqual(len(backups), 2)
            with sqlite3.connect(str(backups[-1])) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_terms"
                ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_apply_preview_without_item_writes_does_not_create_backup(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)

            result = store.apply_preview(
                [],
                {"fileName": "skipped.csv", "format": "csv", "rowCount": 1},
                stats={"conflictCount": 1},
            )

            self.assertEqual(result["createdCount"], 0)
            self.assertEqual(result["updatedCount"], 0)
            self.assertEqual(
                list(Path(tmp).glob("enterprise_knowledge.db.backup-*")), []
            )

    def test_failed_preview_apply_rolls_back_updates_import_record_and_new_backup(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)
            first = store.create_item(term_payload("标准名称", ["第一别名"]))
            store.create_item(term_payload("另一个名称", ["第二别名"]))

            with self.assertRaises(KnowledgeError) as raised:
                store.apply_preview(
                    [
                        {
                            "action": "update",
                            "existingItemId": first["id"],
                            "item": term_payload(
                                "标准名称", ["第一别名"], note="不应保留"
                            ),
                        },
                        {
                            "action": "create",
                            "item": term_payload("冲突名称", ["第二别名"]),
                        },
                    ],
                    {"fileName": "bad.csv", "format": "csv", "rowCount": 2},
                )

            self.assertEqual(raised.exception.code, "term_text_conflict")
            self.assertEqual(store.get_item(first["id"])["note"], "测试备注")
            self.assertEqual(store.summary()["termCount"], 2)
            self.assertEqual(
                list(Path(tmp).glob("enterprise_knowledge.db.backup-*")), []
            )
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 0)

    def test_apply_preview_serializes_concurrent_backup_and_write_cycles(self):
        with TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            barrier = threading.Barrier(4)
            failures = []

            def apply(index):
                barrier.wait()
                try:
                    store.apply_preview(
                        [term_payload("并发名称%d" % index)],
                        {
                            "fileName": "concurrent-%d.csv" % index,
                            "format": "csv",
                            "rowCount": 1,
                        },
                    )
                except Exception as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=apply, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(failures, [])
            self.assertEqual(store.summary()["termCount"], 4)
            self.assertEqual(
                len(list(Path(tmp).glob("enterprise_knowledge.db.backup-*"))), 3
            )

    def test_database_snapshot_bytes_is_consistent_private_and_removes_temp_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(tmp)
            store.create_item(term_payload("标准名称"))

            snapshot = store.database_snapshot_bytes()

            snapshot_path = root / "downloaded.db"
            snapshot_path.write_bytes(snapshot)
            snapshot_path.chmod(0o600)
            with sqlite3.connect(str(snapshot_path)) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_terms"
                ).fetchone()[0]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(count, 1)
            self.assertEqual(integrity, "ok")
            self.assertEqual(list(root.glob(".enterprise-knowledge-snapshot-*")), [])

    def test_database_snapshot_removes_temp_file_when_sqlite_backup_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(tmp)
            with patch.object(
                store,
                "_backup_database_to",
                side_effect=sqlite3.OperationalError("backup failed"),
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    store.database_snapshot_bytes()

            self.assertEqual(list(root.glob(".enterprise-knowledge-snapshot-*")), [])

    def test_post_commit_backup_rotation_error_keeps_successful_import_semantics(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "enterprise_knowledge.db"
            store = EnterpriseKnowledgeStore(db_path)

            with patch.object(
                store,
                "_rotate_backups",
                side_effect=OSError("temporary rotation failure"),
            ):
                with self.assertLogs(
                    "app.services.enterprise_knowledge.store", level="WARNING"
                ) as captured:
                    result = store.apply_preview(
                        [term_payload("轮换失败仍写入")],
                        {
                            "fileName": "rotation.csv",
                            "format": "csv",
                            "rowCount": 1,
                        },
                    )

            self.assertEqual(result["createdCount"], 1)
            self.assertEqual(store.summary()["termCount"], 1)
            self.assertIn("备份轮换失败", " ".join(captured.output))
            with sqlite3.connect(str(db_path)) as connection:
                import_count = connection.execute(
                    "SELECT COUNT(*) FROM knowledge_imports"
                ).fetchone()[0]
            self.assertEqual(import_count, 1)
            self.assertEqual(
                len(list(Path(tmp).glob("enterprise_knowledge.db.backup-*"))), 1
            )


if __name__ == "__main__":
    unittest.main()
