import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from .models import (
    WRITING_POLICY_SCOPES,
    MAX_DATABASE_BACKUPS,
    PRIORITIES,
    RULE_TYPES,
    TASK_SCOPES,
    WRITING_POLICY_SCENES,
    WritingPolicyError,
    normalize_key,
)


logger = logging.getLogger(__name__)

_PRESET_ENTRY_ID_RE = re.compile(r"^(term|rule)\.[a-z0-9][a-z0-9.-]{2,95}$")
_PACK_ID_RE = re.compile(r"^[a-z][a-z0-9.-]{2,63}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _json_list(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _read_json_list(value: str) -> List[str]:
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        raise WritingPolicyError(
            "writing_policy_data_corrupt", "写作规范库中的列表数据已损坏。"
        )
    if not isinstance(loaded, list) or any(
        not isinstance(item, str) for item in loaded
    ):
        raise WritingPolicyError(
            "writing_policy_data_corrupt", "写作规范库中的列表数据已损坏。"
        )
    return list(loaded)


def _json_object(value: Dict[str, object]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _read_json_object(value: str) -> Dict[str, object]:
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        raise WritingPolicyError(
            "writing_policy_data_corrupt", "写作规范库中的对象数据已损坏。"
        )
    if not isinstance(loaded, dict):
        raise WritingPolicyError(
            "writing_policy_data_corrupt", "写作规范库中的对象数据已损坏。"
        )
    return dict(loaded)


class WritingPolicyStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._write_lock = threading.RLock()
        self.db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db_path.parent.chmod(0o700)
        if self.db_path.exists():
            self.db_path.chmod(0o600)
        self._initialize_schema()
        self.db_path.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        self.db_path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writing_policy_terms (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK (scope = 'global'),
                    category TEXT NOT NULL,
                    preferred_text TEXT NOT NULL,
                    preferred_normalized TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    forbidden_variants TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    context_keywords TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS style_rules (
                    id TEXT PRIMARY KEY,
                    item_type TEXT NOT NULL DEFAULT 'style',
                    scope TEXT NOT NULL,
                    task_types TEXT NOT NULL DEFAULT '[]',
                    scene_ids TEXT NOT NULL DEFAULT '[]',
                    name TEXT NOT NULL,
                    name_normalized TEXT NOT NULL,
                    rule_text TEXT NOT NULL,
                    positive_example TEXT NOT NULL,
                    negative_example TEXT NOT NULL,
                    context_keywords TEXT NOT NULL,
                    always_apply INTEGER NOT NULL CHECK (always_apply IN (0, 1)),
                    priority TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS writing_policy_imports (
                    id TEXT PRIMARY KEY,
                    imported_at TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    format TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    created_count INTEGER NOT NULL,
                    updated_count INTEGER NOT NULL,
                    conflict_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    result TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preset_overrides (
                    preset_entry_id TEXT PRIMARY KEY,
                    pack_id TEXT NOT NULL,
                    item_type TEXT NOT NULL CHECK (item_type = 'term'),
                    operation TEXT NOT NULL
                        CHECK (operation IN ('override', 'disabled')),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preset_rule_overrides (
                    preset_entry_id TEXT PRIMARY KEY,
                    pack_id TEXT NOT NULL,
                    item_type TEXT NOT NULL
                        CHECK (item_type IN ('style', 'anti_template')),
                    operation TEXT NOT NULL
                        CHECK (operation IN ('override', 'disabled')),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_writing_policy_terms_scope
                    ON writing_policy_terms(scope);
                CREATE INDEX IF NOT EXISTS idx_writing_policy_terms_enabled
                    ON writing_policy_terms(enabled);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_writing_policy_terms_preferred_normalized
                    ON writing_policy_terms(preferred_normalized);
                CREATE INDEX IF NOT EXISTS idx_style_rules_scope
                    ON style_rules(scope);
                CREATE INDEX IF NOT EXISTS idx_style_rules_enabled
                    ON style_rules(enabled);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_style_rules_scope_name_normalized
                    ON style_rules(scope, name_normalized);
                CREATE INDEX IF NOT EXISTS idx_preset_overrides_item_type
                    ON preset_overrides(item_type);
                CREATE INDEX IF NOT EXISTS idx_preset_rule_overrides_item_type
                    ON preset_rule_overrides(item_type);
                """
            )
            self._migrate_rule_scope_columns(connection)

    @staticmethod
    def _migrate_rule_scope_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(style_rules)")
        }
        additions = (
            ("item_type", "TEXT NOT NULL DEFAULT 'style'"),
            ("task_types", "TEXT NOT NULL DEFAULT '[]'"),
            ("scene_ids", "TEXT NOT NULL DEFAULT '[]'"),
        )
        for name, definition in additions:
            if name not in columns:
                connection.execute(
                    "ALTER TABLE style_rules ADD COLUMN %s %s"
                    % (name, definition)
                )
        rows = connection.execute(
            "SELECT id, scope FROM style_rules WHERE task_types = '[]'"
        ).fetchall()
        for row in rows:
            task_types = (
                TASK_SCOPES
                if row["scope"] == "global"
                else (row["scope"],)
            )
            connection.execute(
                "UPDATE style_rules SET task_types = ? WHERE id = ?",
                (_json_list(task_types), row["id"]),
            )
        connection.execute(
            "UPDATE style_rules SET scene_ids = ? WHERE scene_ids = '[]'",
            (_json_list(WRITING_POLICY_SCENES),),
        )

    def summary(self) -> Dict[str, object]:
        with self._connect() as connection:
            term_row = connection.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(enabled), 0) AS enabled, "
                "MAX(updated_at) AS updated_at FROM writing_policy_terms"
            ).fetchone()
            style_row = connection.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(enabled), 0) AS enabled, "
                "MAX(updated_at) AS updated_at FROM style_rules"
            ).fetchone()

        term_count = int(term_row["total"])
        style_count = int(style_row["total"])
        timestamps = [
            value
            for value in (term_row["updated_at"], style_row["updated_at"])
            if value
        ]
        return {
            "status": "ready",
            "totalCount": term_count + style_count,
            "enabledCount": int(term_row["enabled"]) + int(style_row["enabled"]),
            "termCount": term_count,
            "styleCount": style_count,
            "updatedAt": max(timestamps) if timestamps else "",
        }

    def list_items(
        self, scope: str, item_type: str, query: str = ""
    ) -> List[Dict[str, object]]:
        organization_rules = scope == "organization" and item_type in RULE_TYPES
        if not organization_rules:
            self._validate_scope(scope)
        normalized_query = normalize_key(str(query or ""))
        with self._connect() as connection:
            if item_type == "term":
                rows = connection.execute(
                    "SELECT * FROM writing_policy_terms WHERE scope = ? "
                    "ORDER BY preferred_normalized, id",
                    (scope,),
                ).fetchall()
                items = [self._term_from_row(row) for row in rows]
            elif item_type in RULE_TYPES:
                if organization_rules:
                    rows = connection.execute(
                        "SELECT * FROM style_rules WHERE item_type = ? "
                        "ORDER BY name_normalized, id",
                        (item_type,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM style_rules "
                        "WHERE scope = ? AND item_type = ? "
                        "ORDER BY name_normalized, id",
                        (scope, item_type),
                    ).fetchall()
                items = [self._style_from_row(row) for row in rows]
            else:
                raise WritingPolicyError(
                    "invalid_writing_policy_type",
                    "规范条目类型必须为 term、style 或 anti_template。",
                )

        if not normalized_query:
            return items
        return [
            item
            for item in items
            if normalized_query in self._searchable_text(item)
        ]

    def get_item(self, item_id: str) -> Dict[str, object]:
        with self._connect() as connection:
            return self._get_item(connection, item_id)

    def create_item(self, payload: Dict[str, object]) -> Dict[str, object]:
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self._create_item(connection, payload)

    def update_item(
        self, item_id: str, payload: Dict[str, object]
    ) -> Dict[str, object]:
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self._update_item(connection, item_id, payload)

    def delete_item(self, item_id: str) -> Dict[str, object]:
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = self._get_item(connection, item_id)
                table = (
                    "writing_policy_terms"
                    if existing["type"] == "term"
                    else "style_rules"
                )
                connection.execute("DELETE FROM %s WHERE id = ?" % table, (item_id,))
                return existing

    def list_preset_operations(
        self, item_type: Optional[str] = None
    ) -> List[Dict[str, object]]:
        if item_type is not None and item_type not in ("term",) + RULE_TYPES:
            raise WritingPolicyError(
                "invalid_writing_policy_type",
                "预置规范操作类型无效。",
            )
        with self._connect() as connection:
            term_rows = []
            rule_rows = []
            if item_type in (None, "term"):
                term_rows = connection.execute(
                    "SELECT * FROM preset_overrides "
                    + (
                        "ORDER BY preset_entry_id"
                        if item_type is None
                        else "WHERE item_type = ? ORDER BY preset_entry_id"
                    ),
                    (() if item_type is None else (item_type,)),
                ).fetchall()
            if item_type in (None,) + RULE_TYPES:
                rule_rows = connection.execute(
                    "SELECT * FROM preset_rule_overrides "
                    + (
                        "ORDER BY preset_entry_id"
                        if item_type is None
                        else "WHERE item_type = ? ORDER BY preset_entry_id"
                    ),
                    (() if item_type is None else (item_type,)),
                ).fetchall()
        operations = [
            self._preset_operation_from_row(row) for row in term_rows + rule_rows
        ]
        return sorted(operations, key=lambda item: item["presetEntryId"])

    def get_preset_operation(self, preset_entry_id: str) -> Dict[str, object]:
        with self._connect() as connection:
            for table in ("preset_overrides", "preset_rule_overrides"):
                row = connection.execute(
                    "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
                    (preset_entry_id,),
                ).fetchone()
                if row is not None:
                    return self._preset_operation_from_row(row)
        raise WritingPolicyError(
            "writing_policy_preset_operation_not_found",
            "未找到指定预置规范操作。",
        )

    @staticmethod
    def _preset_operation_table(item_type: str) -> str:
        return (
            "preset_overrides"
            if item_type == "term"
            else "preset_rule_overrides"
        )

    def upsert_preset_operation(
        self,
        preset_entry_id: str,
        pack_id: str,
        item_type: str,
        operation: str,
        payload: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        clean_id = self._validate_preset_entry_id(preset_entry_id, item_type)
        clean_pack_id = str(pack_id or "").strip()
        if not _PACK_ID_RE.fullmatch(clean_pack_id):
            raise WritingPolicyError(
                "invalid_writing_policy_pack",
                "预置规范包标识无效。",
            )
        if operation not in ("override", "disabled"):
            raise WritingPolicyError(
                "invalid_preset_operation",
                "预置操作必须为 override 或 disabled。",
            )
        if operation == "override":
            if not isinstance(payload, dict):
                raise WritingPolicyError(
                    "invalid_writing_policy_item",
                    "预置规范覆盖必须包含规范内容。",
                )
            if item_type == "term":
                clean_payload = dict(self._validate_term(payload), type="term")
            elif item_type in RULE_TYPES:
                clean_payload = dict(
                    self._validate_style(dict(payload, type=item_type)),
                    type=item_type,
                )
            else:
                raise WritingPolicyError(
                    "invalid_writing_policy_type",
                    "预置规范操作类型无效。",
                )
        else:
            if item_type not in ("term",) + RULE_TYPES:
                raise WritingPolicyError(
                    "invalid_writing_policy_type",
                    "预置规范操作类型无效。",
                )
            clean_payload = {}

        table = self._preset_operation_table(item_type)
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT created_at FROM %s "
                    "WHERE preset_entry_id = ?" % table,
                    (clean_id,),
                ).fetchone()
                now = _utc_now()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO %s (
                            preset_entry_id, pack_id, item_type, operation,
                            payload, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """ % table,
                        (
                            clean_id,
                            clean_pack_id,
                            item_type,
                            operation,
                            _json_object(clean_payload),
                            now,
                            now,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE %s SET
                            pack_id = ?, item_type = ?, operation = ?,
                            payload = ?, updated_at = ?
                        WHERE preset_entry_id = ?
                        """ % table,
                        (
                            clean_pack_id,
                            item_type,
                            operation,
                            _json_object(clean_payload),
                            now,
                            clean_id,
                        ),
                    )
                row = connection.execute(
                    "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
                    (clean_id,),
                ).fetchone()
                return self._preset_operation_from_row(row)

    def restore_preset_operation(
        self, preset_entry_id: str
    ) -> Dict[str, object]:
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for table in ("preset_overrides", "preset_rule_overrides"):
                    row = connection.execute(
                        "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
                        (preset_entry_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    existing = self._preset_operation_from_row(row)
                    connection.execute(
                        "DELETE FROM %s WHERE preset_entry_id = ?" % table,
                        (preset_entry_id,),
                    )
                    return existing
        raise WritingPolicyError(
            "writing_policy_preset_operation_not_found",
            "未找到指定预置规范操作。",
        )

    def enabled_items(
        self, task_scope: str, scene_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        self._validate_scope(task_scope)
        if task_scope == "global":
            raise WritingPolicyError(
                "invalid_writing_policy_scope",
                "任务匹配必须使用具体 Word 任务。",
            )
        if scene_id is not None and scene_id not in WRITING_POLICY_SCENES:
            raise WritingPolicyError(
                "invalid_writing_policy_scene",
                "规范场景无效。",
            )
        with self._connect() as connection:
            term_rows = connection.execute(
                "SELECT * FROM writing_policy_terms "
                "WHERE scope = 'global' AND enabled = 1 "
                "ORDER BY preferred_normalized, id"
            ).fetchall()
            style_rows = connection.execute(
                "SELECT * FROM style_rules WHERE enabled = 1 "
                "ORDER BY name_normalized, id"
            ).fetchall()
        styles = [self._style_from_row(row) for row in style_rows]
        styles = [
            item
            for item in styles
            if task_scope in item["taskTypes"]
            and (scene_id is None or scene_id in item["sceneIds"])
        ]
        return (
            [self._term_from_row(row) for row in term_rows],
            styles,
        )

    def apply_items_atomically(
        self,
        items: Sequence[Dict[str, object]],
        import_meta: Dict[str, object],
    ) -> Dict[str, object]:
        return self.apply_preview(items, import_meta)

    def apply_preview(
        self,
        operations: Sequence[Dict[str, object]],
        import_meta: Dict[str, object],
        stats: Optional[Dict[str, int]] = None,
    ) -> Dict[str, object]:
        normalized_operations = self._normalize_import_operations(operations)
        backup_path = None
        with self._write_lock:
            backup_path = self._create_preimport_backup()
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    has_terms = any(
                        operation.get("item", {}).get("type") == "term"
                        for operation in normalized_operations
                        if operation["action"]
                        in ("create", "update", "preset_override")
                    )
                    term_token_owners = (
                        self._load_term_token_owners(connection)
                        if has_terms
                        else None
                    )
                    changed_items = []
                    created_count = 0
                    updated_count = 0
                    modified_count = 0
                    disabled_count = 0
                    restored_count = 0
                    deleted_count = 0
                    for operation in normalized_operations:
                        action = operation["action"]
                        item = operation.get("item")
                        if action in ("update", "delete"):
                            self._assert_import_item_current(connection, operation)
                        elif action in (
                            "preset_override",
                            "preset_disable",
                            "preset_restore",
                        ):
                            self._assert_preset_import_current(connection, operation)
                        item_owners = (
                            term_token_owners
                            if item is not None and item.get("type") == "term"
                            else None
                        )
                        if action == "create":
                            changed_items.append(
                                self._create_item(
                                    connection,
                                    item,
                                    term_token_owners=item_owners,
                                )
                            )
                            created_count += 1
                        elif action == "update":
                            changed_items.append(
                                self._update_item(
                                    connection,
                                    operation["existingItemId"],
                                    item,
                                    term_token_owners=item_owners,
                                )
                            )
                            updated_count += 1
                            modified_count += 1
                        elif action == "delete":
                            existing = self._get_item(
                                connection, operation["existingItemId"]
                            )
                            if term_token_owners is not None and existing["type"] == "term":
                                for token in self._normalized_term_tokens(existing):
                                    if (
                                        term_token_owners.get(token)
                                        == operation["existingItemId"]
                                    ):
                                        del term_token_owners[token]
                            table = (
                                "writing_policy_terms"
                                if existing["type"] == "term"
                                else "style_rules"
                            )
                            connection.execute(
                                "DELETE FROM %s WHERE id = ?" % table,
                                (operation["existingItemId"],),
                            )
                            changed_items.append(existing)
                            deleted_count += 1
                        elif action in ("preset_override", "preset_disable"):
                            changed_items.append(
                                self._apply_preset_import_operation(
                                    connection,
                                    operation,
                                )
                            )
                            if action == "preset_override":
                                modified_count += 1
                            else:
                                disabled_count += 1
                        elif action == "preset_restore":
                            changed_items.append(
                                self._restore_preset_import_operation(
                                    connection,
                                    operation,
                                )
                            )
                            restored_count += 1
                    counts = {
                        "createdCount": created_count,
                        "updatedCount": updated_count,
                        "modifiedCount": modified_count,
                        "disabledCount": disabled_count,
                        "restoredCount": restored_count,
                        "deletedCount": deleted_count,
                        "conflictCount": int((stats or {}).get("conflictCount", 0)),
                        "errorCount": int((stats or {}).get("errorCount", 0)),
                    }
                    import_record = self._record_import(
                        connection,
                        import_meta,
                        dict(
                            counts,
                            updatedCount=(
                                modified_count
                                + disabled_count
                                + restored_count
                                + deleted_count
                            ),
                        ),
                    )
            except Exception:
                if backup_path is not None:
                    try:
                        backup_path.unlink()
                    except FileNotFoundError:
                        pass
                raise

            if backup_path is not None:
                try:
                    self._rotate_backups()
                except OSError as exc:
                    logger.warning(
                        "写作规范库导入后备份轮换失败，将在后续导入重试：%s",
                        exc,
                    )
            return dict(counts, items=changed_items, **{"import": import_record})

    def record_import(
        self, import_meta: Dict[str, object], stats: Dict[str, int]
    ) -> Dict[str, object]:
        with self._write_lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self._record_import(connection, import_meta, stats)

    def export_csv(self, scope: str) -> bytes:
        from .imports import export_csv

        return export_csv(self, scope)

    def validate_item(self, payload: Dict[str, object]) -> Dict[str, object]:
        item_type = payload.get("type")
        if item_type == "term":
            return dict(self._validate_term(payload), type="term")
        if item_type in RULE_TYPES:
            return dict(self._validate_style(payload), type=item_type)
        raise WritingPolicyError(
            "invalid_writing_policy_type",
            "规范条目类型必须为 term、style 或 anti_template。",
        )

    def database_snapshot_bytes(self) -> bytes:
        with self._write_lock:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".writing-policies-snapshot-",
                suffix=".db",
                dir=str(self.db_path.parent),
            )
            os.close(descriptor)
            snapshot_path = Path(raw_path)
            snapshot_path.chmod(0o600)
            try:
                self._backup_database_to(snapshot_path)
                snapshot_path.chmod(0o600)
                return snapshot_path.read_bytes()
            finally:
                try:
                    snapshot_path.unlink()
                except FileNotFoundError:
                    pass

    def _create_preimport_backup(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = None
        descriptor = None
        for collision_index in range(1000):
            suffix = "" if collision_index == 0 else "-%d" % collision_index
            candidate = self.db_path.with_name(
                self.db_path.name + ".backup-" + timestamp + suffix
            )
            try:
                descriptor = os.open(
                    str(candidate),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                backup_path = candidate
                break
            except FileExistsError:
                continue
        if backup_path is None or descriptor is None:
            raise WritingPolicyError(
                "writing_policy_backup_unavailable", "无法创建导入前规范库备份。"
            )
        os.close(descriptor)
        try:
            self._backup_database_to(backup_path)
            backup_path.chmod(0o600)
            return backup_path
        except Exception:
            try:
                backup_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def _backup_database_to(self, target_path: Path) -> None:
        with self._connect() as source:
            with sqlite3.connect(str(target_path), timeout=30.0) as target:
                source.backup(target)
        Path(target_path).chmod(0o600)

    def _rotate_backups(self) -> None:
        backup_paths = list(
            self.db_path.parent.glob(self.db_path.name + ".backup-*")
        )
        backup_paths.sort(key=self._backup_sort_key, reverse=True)
        for stale_path in backup_paths[MAX_DATABASE_BACKUPS:]:
            stale_path.unlink()

    @staticmethod
    def _backup_sort_key(path: Path) -> Tuple[int, float, int, str]:
        match = re.search(r"\.backup-(\d{8}T\d{12}Z)(?:-(\d+))?$", path.name)
        if match:
            try:
                parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S%fZ")
                collision_index = int(match.group(2) or 0)
                return (
                    1,
                    parsed.replace(tzinfo=timezone.utc).timestamp(),
                    collision_index,
                    path.name,
                )
            except ValueError:
                pass
        return (0, path.stat().st_mtime, 0, path.name)

    @staticmethod
    def _normalize_import_operations(
        operations: Sequence[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        normalized = []
        for entry in operations:
            if not isinstance(entry, dict):
                raise WritingPolicyError(
                    "invalid_import_operation", "导入写入项必须为对象。"
                )
            if "action" not in entry:
                normalized.append({"action": "create", "item": dict(entry)})
                continue
            action = entry.get("action")
            item = entry.get("item")
            if action in ("create", "update"):
                if not isinstance(item, dict):
                    raise WritingPolicyError(
                        "invalid_import_operation", "导入写入操作无效。"
                    )
                operation = {"action": action, "item": dict(item)}
                if action == "update":
                    existing_item_id = str(entry.get("existingItemId") or "")
                    if not existing_item_id:
                        raise WritingPolicyError(
                            "invalid_import_operation", "导入更新项缺少目标条目。"
                        )
                    operation["existingItemId"] = existing_item_id
                    if "expectedItem" in entry:
                        operation["expectedItem"] = dict(entry["expectedItem"])
                normalized.append(operation)
                continue
            if action == "delete":
                existing_item_id = str(entry.get("existingItemId") or "")
                if not existing_item_id:
                    raise WritingPolicyError(
                        "invalid_import_operation", "导入删除项缺少目标条目。"
                    )
                normalized.append(
                    {
                        "action": "delete",
                        "existingItemId": existing_item_id,
                        "itemType": str(entry.get("itemType") or ""),
                        **(
                            {"expectedItem": dict(entry["expectedItem"])}
                            if "expectedItem" in entry
                            else {}
                        ),
                    }
                )
                continue
            if action in (
                "preset_override",
                "preset_disable",
                "preset_restore",
            ):
                preset_entry_id = str(entry.get("presetEntryId") or "")
                item_type = str(entry.get("itemType") or "")
                if not preset_entry_id or item_type not in ("term",) + RULE_TYPES:
                    raise WritingPolicyError(
                        "invalid_import_operation", "预置导入操作缺少目标信息。"
                    )
                operation = {
                    "action": action,
                    "presetEntryId": preset_entry_id,
                    "itemType": item_type,
                }
                if "expectedPresetOperation" in entry:
                    expected = entry["expectedPresetOperation"]
                    operation["expectedPresetOperation"] = (
                        None if expected is None else dict(expected)
                    )
                if action in ("preset_override", "preset_disable"):
                    pack_id = str(entry.get("packId") or "")
                    if not pack_id:
                        raise WritingPolicyError(
                            "invalid_import_operation", "预置导入操作缺少规范包。"
                        )
                    operation["packId"] = pack_id
                if action == "preset_override":
                    if not isinstance(item, dict):
                        raise WritingPolicyError(
                            "invalid_import_operation", "预置覆盖缺少规范内容。"
                        )
                    operation["item"] = dict(item)
                normalized.append(operation)
                continue
            if action not in ("create", "update"):
                raise WritingPolicyError(
                    "invalid_import_operation", "导入写入操作无效。"
                )
        return normalized

    def _assert_import_item_current(
        self,
        connection: sqlite3.Connection,
        operation: Dict[str, object],
    ) -> None:
        if "expectedItem" not in operation:
            return
        try:
            current = self._get_item(connection, operation["existingItemId"])
        except WritingPolicyError:
            raise WritingPolicyError(
                "import_preview_stale",
                "规范库已在预览后发生变化，请重新预览。",
            )
        if current != operation["expectedItem"]:
            raise WritingPolicyError(
                "import_preview_stale",
                "规范库已在预览后发生变化，请重新预览。",
            )

    def _assert_preset_import_current(
        self,
        connection: sqlite3.Connection,
        operation: Dict[str, object],
    ) -> None:
        if "expectedPresetOperation" not in operation:
            return
        table = self._preset_operation_table(str(operation["itemType"]))
        row = connection.execute(
            "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
            (operation["presetEntryId"],),
        ).fetchone()
        current = None if row is None else self._preset_operation_from_row(row)
        if current != operation["expectedPresetOperation"]:
            raise WritingPolicyError(
                "import_preview_stale",
                "规范库已在预览后发生变化，请重新预览。",
            )

    def _apply_preset_import_operation(
        self,
        connection: sqlite3.Connection,
        operation: Dict[str, object],
    ) -> Dict[str, object]:
        item_type = str(operation["itemType"])
        preset_entry_id = self._validate_preset_entry_id(
            operation["presetEntryId"],
            item_type,
        )
        pack_id = str(operation["packId"])
        if not _PACK_ID_RE.fullmatch(pack_id):
            raise WritingPolicyError(
                "invalid_writing_policy_pack",
                "预置规范包标识无效。",
            )
        if operation["action"] == "preset_override":
            item = dict(operation["item"])
            if item_type == "term":
                payload = dict(self._validate_term(item), type="term")
            else:
                payload = dict(
                    self._validate_style(dict(item, type=item_type)),
                    type=item_type,
                )
            stored_operation = "override"
        else:
            payload = {}
            stored_operation = "disabled"
        table = self._preset_operation_table(item_type)
        existing = connection.execute(
            "SELECT created_at FROM %s WHERE preset_entry_id = ?" % table,
            (preset_entry_id,),
        ).fetchone()
        now = _utc_now()
        if existing is None:
            connection.execute(
                """
                INSERT INTO %s (
                    preset_entry_id, pack_id, item_type, operation,
                    payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                % table,
                (
                    preset_entry_id,
                    pack_id,
                    item_type,
                    stored_operation,
                    _json_object(payload),
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE %s SET
                    pack_id = ?, item_type = ?, operation = ?,
                    payload = ?, updated_at = ?
                WHERE preset_entry_id = ?
                """
                % table,
                (
                    pack_id,
                    item_type,
                    stored_operation,
                    _json_object(payload),
                    now,
                    preset_entry_id,
                ),
            )
        row = connection.execute(
            "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
            (preset_entry_id,),
        ).fetchone()
        return self._preset_operation_from_row(row)

    def _restore_preset_import_operation(
        self,
        connection: sqlite3.Connection,
        operation: Dict[str, object],
    ) -> Dict[str, object]:
        item_type = str(operation["itemType"])
        preset_entry_id = self._validate_preset_entry_id(
            operation["presetEntryId"],
            item_type,
        )
        table = self._preset_operation_table(item_type)
        row = connection.execute(
            "SELECT * FROM %s WHERE preset_entry_id = ?" % table,
            (preset_entry_id,),
        ).fetchone()
        if row is None:
            raise WritingPolicyError(
                "writing_policy_preset_operation_not_found",
                "未找到指定预置规范操作。",
            )
        existing = self._preset_operation_from_row(row)
        connection.execute(
            "DELETE FROM %s WHERE preset_entry_id = ?" % table,
            (preset_entry_id,),
        )
        return existing

    def _create_item(
        self,
        connection: sqlite3.Connection,
        payload: Dict[str, object],
        term_token_owners: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        if not isinstance(payload, dict):
            raise WritingPolicyError("invalid_writing_policy_item", "规范条目必须为对象。")
        item_type = payload.get("type")
        item_id = str(uuid.uuid4())
        now = _utc_now()
        if item_type == "term":
            clean = self._validate_term(payload)
            self._ensure_term_tokens_available(
                connection,
                clean,
                token_owners=term_token_owners,
            )
            connection.execute(
                """
                INSERT INTO writing_policy_terms (
                    id, scope, category, preferred_text, preferred_normalized,
                    aliases, forbidden_variants, definition, context_keywords,
                    priority, enabled, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id,) + self._term_values(clean, now, include_created=True),
            )
            if term_token_owners is not None:
                for token in self._normalized_term_tokens(clean):
                    term_token_owners[token] = item_id
        elif item_type in RULE_TYPES:
            clean = self._validate_style(payload)
            self._ensure_style_name_available(connection, clean)
            connection.execute(
                """
                INSERT INTO style_rules (
                    id, item_type, scope, task_types, scene_ids,
                    name, name_normalized, rule_text,
                    positive_example, negative_example, context_keywords,
                    always_apply, priority, enabled, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id,) + self._style_values(clean, now, include_created=True),
            )
        else:
            raise WritingPolicyError(
                "invalid_writing_policy_type",
                "规范条目类型必须为 term、style 或 anti_template。",
            )
        return self._get_item(connection, item_id)

    def _update_item(
        self,
        connection: sqlite3.Connection,
        item_id: str,
        payload: Dict[str, object],
        term_token_owners: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        existing = self._get_item(connection, item_id)
        requested_type = payload.get("type")
        if requested_type is not None and requested_type != existing["type"]:
            raise WritingPolicyError(
                "invalid_writing_policy_type", "规范条目类型不能在修改时变更。"
            )
        merged = dict(existing)
        merged.update(payload)
        merged["type"] = existing["type"]
        if "scope" in payload and "taskTypes" not in payload:
            merged.pop("taskTypes", None)
        if existing["type"] == "term":
            clean = self._validate_term(merged)
            if term_token_owners is None:
                self._ensure_term_tokens_available(connection, clean, item_id)
            else:
                for token in self._normalized_term_tokens(existing):
                    if term_token_owners.get(token) == item_id:
                        del term_token_owners[token]
                self._ensure_term_tokens_available(
                    connection,
                    clean,
                    token_owners=term_token_owners,
                )
            connection.execute(
                """
                UPDATE writing_policy_terms SET
                    scope = ?, category = ?, preferred_text = ?,
                    preferred_normalized = ?, aliases = ?,
                    forbidden_variants = ?, definition = ?,
                    context_keywords = ?, priority = ?, enabled = ?, note = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                self._term_values(clean, _utc_now()) + (item_id,),
            )
            if term_token_owners is not None:
                for token in self._normalized_term_tokens(clean):
                    term_token_owners[token] = item_id
        else:
            clean = self._validate_style(merged)
            self._ensure_style_name_available(connection, clean, item_id)
            connection.execute(
                """
                UPDATE style_rules SET
                    item_type = ?, scope = ?, task_types = ?, scene_ids = ?,
                    name = ?, name_normalized = ?, rule_text = ?,
                    positive_example = ?, negative_example = ?,
                    context_keywords = ?, always_apply = ?, priority = ?,
                    enabled = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                self._style_values(clean, _utc_now()) + (item_id,),
            )
        return self._get_item(connection, item_id)

    def _record_import(
        self,
        connection: sqlite3.Connection,
        import_meta: Dict[str, object],
        stats: Dict[str, int],
    ) -> Dict[str, object]:
        record = {
            "id": str(uuid.uuid4()),
            "importedAt": _utc_now(),
            "fileName": str(import_meta.get("fileName") or ""),
            "format": str(import_meta.get("format") or ""),
            "rowCount": self._non_negative_int(import_meta.get("rowCount", 0)),
            "createdCount": self._non_negative_int(stats.get("createdCount", 0)),
            "updatedCount": self._non_negative_int(stats.get("updatedCount", 0)),
            "conflictCount": self._non_negative_int(stats.get("conflictCount", 0)),
            "errorCount": self._non_negative_int(stats.get("errorCount", 0)),
            "result": str(import_meta.get("result") or "success"),
        }
        connection.execute(
            """
            INSERT INTO writing_policy_imports (
                id, imported_at, file_name, format, row_count, created_count,
                updated_count, conflict_count, error_count, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["importedAt"],
                record["fileName"],
                record["format"],
                record["rowCount"],
                record["createdCount"],
                record["updatedCount"],
                record["conflictCount"],
                record["errorCount"],
                record["result"],
            ),
        )
        return record

    def _get_item(
        self, connection: sqlite3.Connection, item_id: str
    ) -> Dict[str, object]:
        row = connection.execute(
            "SELECT * FROM writing_policy_terms WHERE id = ?", (item_id,)
        ).fetchone()
        if row is not None:
            return self._term_from_row(row)
        row = connection.execute(
            "SELECT * FROM style_rules WHERE id = ?", (item_id,)
        ).fetchone()
        if row is not None:
            return self._style_from_row(row)
        raise WritingPolicyError("writing_policy_item_not_found", "未找到指定规范条目。")

    def _get_preset_operation(
        self,
        connection: sqlite3.Connection,
        preset_entry_id: str,
    ) -> Dict[str, object]:
        row = connection.execute(
            "SELECT * FROM preset_overrides WHERE preset_entry_id = ?",
            (preset_entry_id,),
        ).fetchone()
        if row is None:
            raise WritingPolicyError(
                "writing_policy_preset_operation_not_found",
                "未找到指定预置规范操作。",
            )
        return self._preset_operation_from_row(row)

    @staticmethod
    def _validate_preset_entry_id(
        preset_entry_id: object, item_type: str
    ) -> str:
        clean = str(preset_entry_id or "").strip()
        if item_type not in ("term",) + RULE_TYPES or not _PRESET_ENTRY_ID_RE.fullmatch(clean):
            raise WritingPolicyError(
                "invalid_preset_entry_id",
                "预置规范条目标识无效。",
            )
        expected_prefix = "term." if item_type == "term" else "rule."
        if not clean.startswith(expected_prefix):
            raise WritingPolicyError(
                "invalid_writing_policy_type",
                "预置条目标识与规范类型不一致。",
            )
        return clean

    def _ensure_term_tokens_available(
        self,
        connection: sqlite3.Connection,
        item: Dict[str, object],
        exclude_id: Optional[str] = None,
        token_owners: Optional[Dict[str, str]] = None,
    ) -> None:
        incoming = self._normalized_term_tokens(item)
        owners = (
            token_owners
            if token_owners is not None
            else self._load_term_token_owners(connection, exclude_id)
        )
        if incoming.intersection(owners):
            raise WritingPolicyError(
                "term_text_conflict",
                "标准写法、别名或禁用写法与已有术语冲突。",
            )

    def _load_term_token_owners(
        self,
        connection: sqlite3.Connection,
        exclude_id: Optional[str] = None,
    ) -> Dict[str, str]:
        rows = connection.execute(
            "SELECT id, preferred_text, aliases, forbidden_variants "
            "FROM writing_policy_terms WHERE id != ?",
            (exclude_id or "",),
        ).fetchall()
        owners = {}
        for row in rows:
            tokens = {
                normalize_key(value)
                for value in (
                    [row["preferred_text"]]
                    + _read_json_list(row["aliases"])
                    + _read_json_list(row["forbidden_variants"])
                )
                if normalize_key(value)
            }
            for token in tokens:
                owners[token] = row["id"]
        return owners

    @staticmethod
    def _normalized_term_tokens(item: Dict[str, object]) -> set:
        return {
            normalize_key(value)
            for value in (
                [item["preferredText"]]
                + item["aliases"]
                + item["forbiddenVariants"]
            )
            if normalize_key(value)
        }

    def _ensure_style_name_available(
        self,
        connection: sqlite3.Connection,
        item: Dict[str, object],
        exclude_id: Optional[str] = None,
    ) -> None:
        row = connection.execute(
            "SELECT id FROM style_rules "
            "WHERE scope = ? AND name_normalized = ? AND id != ? LIMIT 1",
            (item["scope"], normalize_key(item["name"]), exclude_id or ""),
        ).fetchone()
        if row is not None:
            raise WritingPolicyError(
                "style_name_conflict", "当前范围已存在同名文体规则。"
            )

    def _validate_term(self, payload: Dict[str, object]) -> Dict[str, object]:
        scope = self._clean_text(payload.get("scope", "global"))
        self._validate_scope(scope)
        if scope != "global":
            raise WritingPolicyError(
                "invalid_writing_policy_scope", "首版术语仅允许使用 global 范围。"
            )
        clean = {
            "scope": scope,
            "category": self._clean_text(payload.get("category", "")),
            "preferredText": self._required_text(
                payload.get("preferredText"), "标准写法不能为空。"
            ),
            "aliases": self._clean_list(payload.get("aliases", []), "aliases"),
            "forbiddenVariants": self._clean_list(
                payload.get("forbiddenVariants", []), "forbiddenVariants"
            ),
            "definition": self._clean_text(payload.get("definition", "")),
            "contextKeywords": self._clean_list(
                payload.get("contextKeywords", []), "contextKeywords"
            ),
            "priority": self._validate_priority(payload.get("priority", "medium")),
            "enabled": self._validate_bool(payload.get("enabled", True), "enabled"),
            "note": self._clean_text(payload.get("note", "")),
        }
        self._ensure_term_fields_disjoint(clean)
        return clean

    @staticmethod
    def _ensure_term_fields_disjoint(item: Dict[str, object]) -> None:
        preferred = {normalize_key(item["preferredText"])}
        aliases = {normalize_key(value) for value in item["aliases"]}
        forbidden = {
            normalize_key(value) for value in item["forbiddenVariants"]
        }
        if (
            preferred.intersection(aliases)
            or preferred.intersection(forbidden)
            or aliases.intersection(forbidden)
        ):
            raise WritingPolicyError(
                "term_text_conflict",
                "同一术语的标准写法、别名和禁用写法不能重复。",
            )

    def _validate_style(self, payload: Dict[str, object]) -> Dict[str, object]:
        item_type = str(payload.get("type") or "style")
        if item_type not in RULE_TYPES:
            raise WritingPolicyError(
                "invalid_writing_policy_type",
                "规则类型必须为 style 或 anti_template。",
            )
        scope = self._clean_text(payload.get("scope", "global")) or "global"
        self._validate_scope(scope)
        raw_task_types = payload.get("taskTypes")
        if raw_task_types is None:
            task_types = list(TASK_SCOPES if scope == "global" else (scope,))
        else:
            task_types = self._clean_list(raw_task_types, "taskTypes")
            if not task_types or any(value not in TASK_SCOPES for value in task_types):
                raise WritingPolicyError(
                    "invalid_writing_policy_scope",
                    "规则任务范围必须从三个 Word 任务中选择。",
                )
        scene_ids = self._clean_list(
            payload.get("sceneIds", WRITING_POLICY_SCENES),
            "sceneIds",
        )
        if not scene_ids or any(value not in WRITING_POLICY_SCENES for value in scene_ids):
            raise WritingPolicyError(
                "invalid_writing_policy_scene",
                "规则场景范围无效。",
            )
        compatibility_scope = (
            task_types[0] if len(task_types) == 1 else "global"
        )
        return {
            "type": item_type,
            "scope": compatibility_scope,
            "taskTypes": task_types,
            "sceneIds": scene_ids,
            "name": self._required_text(payload.get("name"), "规则名称不能为空。"),
            "ruleText": self._required_text(
                payload.get("ruleText"), "规则正文不能为空。"
            ),
            "positiveExample": self._clean_text(
                payload.get("positiveExample", "")
            ),
            "negativeExample": self._clean_text(
                payload.get("negativeExample", "")
            ),
            "contextKeywords": self._clean_list(
                payload.get("contextKeywords", []), "contextKeywords"
            ),
            "alwaysApply": self._validate_bool(
                payload.get("alwaysApply", False), "alwaysApply"
            ),
            "priority": self._validate_priority(payload.get("priority", "medium")),
            "enabled": self._validate_bool(payload.get("enabled", True), "enabled"),
            "note": self._clean_text(payload.get("note", "")),
        }

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if scope not in WRITING_POLICY_SCOPES:
            raise WritingPolicyError(
                "invalid_writing_policy_scope", "规范条目的适用范围无效。"
            )

    @staticmethod
    def _validate_priority(value: object) -> str:
        priority = str(value or "")
        if priority not in PRIORITIES:
            raise WritingPolicyError(
                "invalid_writing_policy_priority", "优先级必须为 high、medium 或 low。"
            )
        return priority

    @staticmethod
    def _validate_bool(value: object, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise WritingPolicyError(
                "invalid_writing_policy_item", "%s 必须为布尔值。" % field_name
            )
        return value

    @staticmethod
    def _clean_text(value: object) -> str:
        return str(value or "").strip()

    def _required_text(self, value: object, message: str) -> str:
        clean = self._clean_text(value)
        if not clean:
            raise WritingPolicyError("invalid_writing_policy_item", message)
        return clean

    def _clean_list(self, value: object, field_name: str) -> List[str]:
        if not isinstance(value, (list, tuple)):
            raise WritingPolicyError(
                "invalid_writing_policy_item", "%s 必须为列表。" % field_name
            )
        result = []
        seen = set()
        for raw in value:
            clean = self._clean_text(raw)
            key = normalize_key(clean)
            if clean and key not in seen:
                result.append(clean)
                seen.add(key)
        return result

    @staticmethod
    def _non_negative_int(value: object) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            raise WritingPolicyError("invalid_import_record", "导入统计必须为整数。")
        if result < 0:
            raise WritingPolicyError("invalid_import_record", "导入统计不能为负数。")
        return result

    @staticmethod
    def _term_values(
        item: Dict[str, object], timestamp: str, include_created: bool = False
    ) -> Tuple[object, ...]:
        values = (
            item["scope"],
            item["category"],
            item["preferredText"],
            normalize_key(item["preferredText"]),
            _json_list(item["aliases"]),
            _json_list(item["forbiddenVariants"]),
            item["definition"],
            _json_list(item["contextKeywords"]),
            item["priority"],
            int(item["enabled"]),
            item["note"],
        )
        return values + ((timestamp, timestamp) if include_created else (timestamp,))

    @staticmethod
    def _style_values(
        item: Dict[str, object], timestamp: str, include_created: bool = False
    ) -> Tuple[object, ...]:
        values = (
            item["type"],
            item["scope"],
            _json_list(item["taskTypes"]),
            _json_list(item["sceneIds"]),
            item["name"],
            normalize_key(item["name"]),
            item["ruleText"],
            item["positiveExample"],
            item["negativeExample"],
            _json_list(item["contextKeywords"]),
            int(item["alwaysApply"]),
            item["priority"],
            int(item["enabled"]),
            item["note"],
        )
        return values + ((timestamp, timestamp) if include_created else (timestamp,))

    @staticmethod
    def _term_from_row(row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": row["id"],
            "type": "term",
            "scope": row["scope"],
            "category": row["category"],
            "preferredText": row["preferred_text"],
            "aliases": _read_json_list(row["aliases"]),
            "forbiddenVariants": _read_json_list(row["forbidden_variants"]),
            "definition": row["definition"],
            "contextKeywords": _read_json_list(row["context_keywords"]),
            "priority": row["priority"],
            "enabled": bool(row["enabled"]),
            "note": row["note"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _style_from_row(row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": row["id"],
            "type": row["item_type"],
            "scope": row["scope"],
            "taskTypes": _read_json_list(row["task_types"]),
            "sceneIds": _read_json_list(row["scene_ids"]),
            "name": row["name"],
            "ruleText": row["rule_text"],
            "positiveExample": row["positive_example"],
            "negativeExample": row["negative_example"],
            "contextKeywords": _read_json_list(row["context_keywords"]),
            "alwaysApply": bool(row["always_apply"]),
            "priority": row["priority"],
            "enabled": bool(row["enabled"]),
            "note": row["note"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _preset_operation_from_row(
        self, row: sqlite3.Row
    ) -> Dict[str, object]:
        try:
            payload = _read_json_object(row["payload"])
            if row["operation"] == "override":
                if row["item_type"] == "term":
                    expected_fields = {
                        "type",
                        "scope",
                        "category",
                        "preferredText",
                        "aliases",
                        "forbiddenVariants",
                        "definition",
                        "contextKeywords",
                        "priority",
                        "enabled",
                        "note",
                    }
                    if set(payload) != expected_fields or payload.get("type") != "term":
                        raise WritingPolicyError(
                            "writing_policy_data_corrupt",
                            "预置术语覆盖数据字段无效。",
                        )
                    payload = dict(self._validate_term(payload), type="term")
                elif row["item_type"] in RULE_TYPES:
                    payload = dict(
                        self._validate_style(payload),
                        type=row["item_type"],
                    )
                else:
                    raise WritingPolicyError(
                        "writing_policy_data_corrupt",
                        "预置规则覆盖类型无效。",
                    )
            elif payload:
                raise WritingPolicyError(
                    "writing_policy_data_corrupt",
                    "预置停用记录不应包含覆盖内容。",
                )
        except WritingPolicyError as error:
            if error.code == "writing_policy_data_corrupt":
                raise
            raise WritingPolicyError(
                "writing_policy_data_corrupt",
                "预置规范操作数据已损坏。",
            )
        return {
            "id": row["preset_entry_id"],
            "presetEntryId": row["preset_entry_id"],
            "packId": row["pack_id"],
            "itemType": row["item_type"],
            "operation": row["operation"],
            "payload": payload,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _searchable_text(item: Dict[str, object]) -> str:
        values = []
        for key, value in item.items():
            if key in ("id", "createdAt", "updatedAt", "enabled", "alwaysApply"):
                continue
            if isinstance(value, list):
                values.extend(str(entry) for entry in value)
            else:
                values.append(str(value))
        return normalize_key(" ".join(values))
