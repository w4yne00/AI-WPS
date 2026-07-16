import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from .models import (
    KNOWLEDGE_SCOPES,
    PRIORITIES,
    KnowledgeError,
    normalize_key,
)


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
        raise KnowledgeError(
            "knowledge_data_corrupt", "企业知识库中的列表数据已损坏。"
        )
    if not isinstance(loaded, list) or any(
        not isinstance(item, str) for item in loaded
    ):
        raise KnowledgeError(
            "knowledge_data_corrupt", "企业知识库中的列表数据已损坏。"
        )
    return list(loaded)


class EnterpriseKnowledgeStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
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
                CREATE TABLE IF NOT EXISTS knowledge_terms (
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
                    scope TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS knowledge_imports (
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

                CREATE INDEX IF NOT EXISTS idx_knowledge_terms_scope
                    ON knowledge_terms(scope);
                CREATE INDEX IF NOT EXISTS idx_knowledge_terms_enabled
                    ON knowledge_terms(enabled);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_terms_preferred_normalized
                    ON knowledge_terms(preferred_normalized);
                CREATE INDEX IF NOT EXISTS idx_style_rules_scope
                    ON style_rules(scope);
                CREATE INDEX IF NOT EXISTS idx_style_rules_enabled
                    ON style_rules(enabled);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_style_rules_scope_name_normalized
                    ON style_rules(scope, name_normalized);
                """
            )

    def summary(self) -> Dict[str, object]:
        with self._connect() as connection:
            term_row = connection.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(enabled), 0) AS enabled, "
                "MAX(updated_at) AS updated_at FROM knowledge_terms"
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
        self._validate_scope(scope)
        normalized_query = normalize_key(str(query or ""))
        with self._connect() as connection:
            if item_type == "term":
                rows = connection.execute(
                    "SELECT * FROM knowledge_terms WHERE scope = ? "
                    "ORDER BY preferred_normalized, id",
                    (scope,),
                ).fetchall()
                items = [self._term_from_row(row) for row in rows]
            elif item_type == "style":
                rows = connection.execute(
                    "SELECT * FROM style_rules WHERE scope = ? "
                    "ORDER BY name_normalized, id",
                    (scope,),
                ).fetchall()
                items = [self._style_from_row(row) for row in rows]
            else:
                raise KnowledgeError(
                    "invalid_knowledge_type", "知识条目类型必须为 term 或 style。"
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._create_item(connection, payload)

    def update_item(
        self, item_id: str, payload: Dict[str, object]
    ) -> Dict[str, object]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_item(connection, item_id)
            requested_type = payload.get("type")
            if requested_type is not None and requested_type != existing["type"]:
                raise KnowledgeError(
                    "invalid_knowledge_type", "知识条目类型不能在修改时变更。"
                )
            merged = dict(existing)
            merged.update(payload)
            merged["type"] = existing["type"]
            if existing["type"] == "term":
                clean = self._validate_term(merged)
                self._ensure_term_tokens_available(connection, clean, item_id)
                connection.execute(
                    """
                    UPDATE knowledge_terms SET
                        scope = ?, category = ?, preferred_text = ?,
                        preferred_normalized = ?, aliases = ?,
                        forbidden_variants = ?, definition = ?,
                        context_keywords = ?, priority = ?, enabled = ?, note = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    self._term_values(clean, _utc_now()) + (item_id,),
                )
            else:
                clean = self._validate_style(merged)
                self._ensure_style_name_available(connection, clean, item_id)
                connection.execute(
                    """
                    UPDATE style_rules SET
                        scope = ?, name = ?, name_normalized = ?, rule_text = ?,
                        positive_example = ?, negative_example = ?,
                        context_keywords = ?, always_apply = ?, priority = ?,
                        enabled = ?, note = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    self._style_values(clean, _utc_now()) + (item_id,),
                )
            return self._get_item(connection, item_id)

    def delete_item(self, item_id: str) -> Dict[str, object]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_item(connection, item_id)
            table = (
                "knowledge_terms" if existing["type"] == "term" else "style_rules"
            )
            connection.execute("DELETE FROM %s WHERE id = ?" % table, (item_id,))
            return existing

    def enabled_items(
        self, task_scope: str
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        self._validate_scope(task_scope)
        with self._connect() as connection:
            term_rows = connection.execute(
                "SELECT * FROM knowledge_terms "
                "WHERE scope = 'global' AND enabled = 1 "
                "ORDER BY preferred_normalized, id"
            ).fetchall()
            style_rows = connection.execute(
                "SELECT * FROM style_rules "
                "WHERE enabled = 1 AND scope IN ('global', ?) "
                "ORDER BY CASE WHEN scope = ? THEN 0 ELSE 1 END, "
                "name_normalized, id",
                (task_scope, task_scope),
            ).fetchall()
        return (
            [self._term_from_row(row) for row in term_rows],
            [self._style_from_row(row) for row in style_rows],
        )

    def apply_items_atomically(
        self,
        items: Sequence[Dict[str, object]],
        import_meta: Dict[str, object],
    ) -> Dict[str, object]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            created = []
            has_terms = any(
                isinstance(item, dict) and item.get("type") == "term"
                for item in items
            )
            term_token_owners = (
                self._load_term_token_owners(connection) if has_terms else None
            )
            for item in items:
                item_owners = (
                    term_token_owners
                    if isinstance(item, dict) and item.get("type") == "term"
                    else None
                )
                created.append(
                    self._create_item(
                        connection,
                        item,
                        term_token_owners=item_owners,
                    )
                )
            import_record = self._record_import(
                connection,
                import_meta,
                {
                    "createdCount": len(created),
                    "updatedCount": 0,
                    "conflictCount": 0,
                    "errorCount": 0,
                },
            )
            return {"items": created, "import": import_record}

    def record_import(
        self, import_meta: Dict[str, object], stats: Dict[str, int]
    ) -> Dict[str, object]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._record_import(connection, import_meta, stats)

    def _create_item(
        self,
        connection: sqlite3.Connection,
        payload: Dict[str, object],
        term_token_owners: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        if not isinstance(payload, dict):
            raise KnowledgeError("invalid_knowledge_item", "知识条目必须为对象。")
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
                INSERT INTO knowledge_terms (
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
        elif item_type == "style":
            clean = self._validate_style(payload)
            self._ensure_style_name_available(connection, clean)
            connection.execute(
                """
                INSERT INTO style_rules (
                    id, scope, name, name_normalized, rule_text,
                    positive_example, negative_example, context_keywords,
                    always_apply, priority, enabled, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id,) + self._style_values(clean, now, include_created=True),
            )
        else:
            raise KnowledgeError(
                "invalid_knowledge_type", "知识条目类型必须为 term 或 style。"
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
            INSERT INTO knowledge_imports (
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
            "SELECT * FROM knowledge_terms WHERE id = ?", (item_id,)
        ).fetchone()
        if row is not None:
            return self._term_from_row(row)
        row = connection.execute(
            "SELECT * FROM style_rules WHERE id = ?", (item_id,)
        ).fetchone()
        if row is not None:
            return self._style_from_row(row)
        raise KnowledgeError("knowledge_item_not_found", "未找到指定知识条目。")

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
            raise KnowledgeError(
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
            "FROM knowledge_terms WHERE id != ?",
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
            raise KnowledgeError(
                "style_name_conflict", "当前范围已存在同名风格规则。"
            )

    def _validate_term(self, payload: Dict[str, object]) -> Dict[str, object]:
        scope = self._clean_text(payload.get("scope", "global"))
        self._validate_scope(scope)
        if scope != "global":
            raise KnowledgeError(
                "invalid_knowledge_scope", "首版术语仅允许使用 global 范围。"
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
            raise KnowledgeError(
                "term_text_conflict",
                "同一术语的标准写法、别名和禁用写法不能重复。",
            )

    def _validate_style(self, payload: Dict[str, object]) -> Dict[str, object]:
        scope = self._clean_text(payload.get("scope", ""))
        self._validate_scope(scope)
        return {
            "scope": scope,
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
        if scope not in KNOWLEDGE_SCOPES:
            raise KnowledgeError(
                "invalid_knowledge_scope", "知识条目的适用范围无效。"
            )

    @staticmethod
    def _validate_priority(value: object) -> str:
        priority = str(value or "")
        if priority not in PRIORITIES:
            raise KnowledgeError(
                "invalid_knowledge_priority", "优先级必须为 high、medium 或 low。"
            )
        return priority

    @staticmethod
    def _validate_bool(value: object, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise KnowledgeError(
                "invalid_knowledge_item", "%s 必须为布尔值。" % field_name
            )
        return value

    @staticmethod
    def _clean_text(value: object) -> str:
        return str(value or "").strip()

    def _required_text(self, value: object, message: str) -> str:
        clean = self._clean_text(value)
        if not clean:
            raise KnowledgeError("invalid_knowledge_item", message)
        return clean

    def _clean_list(self, value: object, field_name: str) -> List[str]:
        if not isinstance(value, (list, tuple)):
            raise KnowledgeError(
                "invalid_knowledge_item", "%s 必须为列表。" % field_name
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
            raise KnowledgeError("invalid_import_record", "导入统计必须为整数。")
        if result < 0:
            raise KnowledgeError("invalid_import_record", "导入统计不能为负数。")
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
            item["scope"],
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
            "type": "style",
            "scope": row["scope"],
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
