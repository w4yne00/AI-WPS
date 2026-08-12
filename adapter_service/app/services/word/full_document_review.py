import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from app.core.errors import AdapterError
from app.core.features import full_document_review_enabled
from app.core.runtime_paths import resolve_runtime_paths
from app.services.long_task_coordinator import (
    LongTaskCancelled,
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.model_configurations import ACCESS_DIRECT_MODEL
from app.services.provider_client import ProviderClient


TASK_TYPE = "word.document_review.full"
CHUNK_SCHEMA_VERSION = "word.document_review.full.chunk.v1"
REPORT_SCHEMA_VERSION = "word.document_review.full.report.v1"
REPORT_RESULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_ISSUE_PAGE_SIZE = 20
MAX_ISSUE_PAGE_SIZE = 100
MAX_REVIEW_CHARACTERS = 120000
SINGLE_CHUNK_MAX_REVIEW_CHARACTERS = 20000
STANDARD_REVIEW_CHARACTERS = 60000
REVIEW_CHUNK_TARGET_CHARACTERS = 18000
REVIEW_CHUNK_HARD_LIMIT = 20000
REVIEW_CALL_LIMITS = {
    "single_chunk": 8,
    "standard": 16,
    "large": 24,
}
MAX_REVIEW_BLOCKS = 5000
DEFAULT_STAGING_TTL_SECONDS = 10 * 60
LARGE_SNAPSHOT_CONFIRMATION_TTL_SECONDS = 30 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_CATEGORIES = {"typo", "expression", "logic", "fluency", "professional"}
_SEVERITIES = {"high", "medium", "low"}
_ENUMERATION_STATUSES = {"complete", "limited"}
_ISSUE_STATUSES = {"open", "processed", "ignored"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_EXCLUDED_REGIONS = (
    "headers",
    "footers",
    "footnotes",
    "endnotes",
    "comments",
    "revisions",
    "textBoxes",
    "shapes",
    "images",
    "formulas",
    "charts",
    "attachments",
    "hiddenText",
)


def classify_review_capacity(review_character_count: int) -> Dict:
    """Return the user-visible capacity gate for a frozen review snapshot."""
    if type(review_character_count) is not int or review_character_count <= 0:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_CHARACTER_COUNT_INVALID",
            "全篇审查字符数必须是正整数。",
        )
    if review_character_count > MAX_REVIEW_CHARACTERS:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_TOO_LARGE",
            "全篇审查最多支持 120,000 审查字符，请缩小正文或表格范围。",
            status_code=413,
        )
    if review_character_count <= SINGLE_CHUNK_MAX_REVIEW_CHARACTERS:
        return {
            "tier": "single_chunk",
            "label": "单分片",
            "reviewCharacterCount": review_character_count,
            "initialChunkCount": 1,
            "estimatedCallCount": 1,
            "callLimit": REVIEW_CALL_LIMITS["single_chunk"],
            "requiresConfirmation": False,
        }
    if review_character_count <= STANDARD_REVIEW_CHARACTERS:
        tier = "standard"
        label = "标准全篇"
        call_limit = REVIEW_CALL_LIMITS[tier]
        requires_confirmation = False
    else:
        tier = "large"
        label = "大型文档"
        call_limit = REVIEW_CALL_LIMITS[tier]
        requires_confirmation = True
    chunk_count = (review_character_count + REVIEW_CHUNK_TARGET_CHARACTERS - 1) // REVIEW_CHUNK_TARGET_CHARACTERS
    return {
        "tier": tier,
        "label": label,
        "reviewCharacterCount": review_character_count,
        "initialChunkCount": chunk_count,
        "estimatedCallCount": chunk_count + (1 if chunk_count > 1 else 0),
        "callLimit": call_limit,
        "requiresConfirmation": requires_confirmation,
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _report_sha256(report: Dict) -> str:
    payload = {
        key: value for key, value in report.items() if key != "reportSha256"
    }
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _review_character_count(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _full_review_disabled() -> AdapterError:
    return AdapterError(
        "FULL_DOCUMENT_REVIEW_DISABLED",
        "全篇审查功能尚未启用。",
        status_code=403,
    )


class FullDocumentReviewService:
    def __init__(
        self,
        staging_root: Optional[Path] = None,
        provider_client: Optional[ProviderClient] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
        wall_clock=time.time,
        staging_ttl_seconds: int = DEFAULT_STAGING_TTL_SECONDS,
    ) -> None:
        self._configured_staging_root = (
            Path(staging_root) if staging_root is not None else None
        )
        self.provider_client = provider_client or ProviderClient()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._wall_clock = wall_clock
        self._sessions: Dict[str, Dict] = {}
        self._reports: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = None
        self._staging_ttl_seconds = max(int(staging_ttl_seconds), 1)
        self._last_cleanup_at = 0.0
        self._cleanup_expired(force=True)

    @property
    def staging_root(self) -> Path:
        if self._configured_staging_root is not None:
            return self._configured_staging_root
        configured = os.environ.get("AI_WPS_FULL_DOCUMENT_REVIEW_DIR", "").strip()
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_STORAGE_INVALID",
                    "全篇审查暂存目录必须是绝对路径。",
                    status_code=500,
                )
            return path
        return resolve_runtime_paths().var_dir / "word-full-document-review"

    def snapshot_path(self, snapshot_id: str) -> Path:
        return self.staging_root / str(snapshot_id)

    def _report_path(self, job_id: str) -> Path:
        if not _SAFE_ID.fullmatch(str(job_id or "")):
            return self.staging_root / "report-invalid"
        return self.staging_root / "report-{0}.json".format(job_id)

    def create_session(self, payload: Dict) -> Dict:
        self._require_enabled()
        self._require_object(payload, {
            "documentId", "documentType", "reviewPrompt", "writingPolicyScene", "coverage"
        })
        document_id = self._required_string(
            payload, "documentId", "FULL_DOCUMENT_REVIEW_DOCUMENT_INVALID", 160
        ).strip()
        document_type = self._optional_string(
            payload, "documentType", "technical_solution", 120
        ).strip()
        review_prompt = self._optional_string(payload, "reviewPrompt", "", 4000).strip()
        writing_policy_scene = self._optional_string(
            payload, "writingPolicyScene", "auto", 80
        ).strip() or "auto"
        coverage = payload.get("coverage")
        if not document_id or len(document_id) > 160:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_DOCUMENT_INVALID",
                "缺少有效的 Word 文档标识。",
            )
        if (
            not isinstance(coverage, dict)
            or set(coverage) - {"includedRegions", "excludedRegions"}
            or not self._string_list(coverage.get("includedRegions"))
            or not self._string_list(coverage.get("excludedRegions", []), allow_empty=True)
            or "body" not in coverage["includedRegions"]
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_COVERAGE_INVALID",
                "全篇审查必须声明普通正文覆盖范围。",
            )
        included_regions = ["body"]
        if "tables" in coverage["includedRegions"]:
            included_regions.append("tables")
        session_id = "full-review-{0}".format(secrets.token_hex(16))
        upload_token = secrets.token_urlsafe(32)
        now = self._wall_clock()
        session = {
            "sessionId": session_id,
            "snapshotId": session_id,
            "status": "uploading",
            "documentIdSha256": _sha256_text(document_id),
            "documentType": document_type or "technical_solution",
            "reviewPrompt": review_prompt,
            "writingPolicyScene": writing_policy_scene,
            "coverage": {
                "includedRegions": included_regions,
                "excludedRegions": list(_EXCLUDED_REGIONS),
            },
            "uploadTokenSha256": _sha256_text(upload_token),
            "createdAt": now,
            "expiresAt": now + self._staging_ttl_seconds,
            "batches": [],
        }
        self._ensure_root()
        path = self.snapshot_path(session_id)
        path.mkdir(mode=0o700)
        self._write_private_json(path / "session.json", self._safe_session(session))
        with self._lock:
            self._sessions[session_id] = session
        return {
            "sessionId": session_id,
            "uploadToken": upload_token,
            "status": "uploading",
            "maxReviewCharacters": MAX_REVIEW_CHARACTERS,
            "stagingExpiresAt": session["expiresAt"],
            "capacityTiers": [
                classify_review_capacity(limit)
                for limit in (
                    SINGLE_CHUNK_MAX_REVIEW_CHARACTERS,
                    STANDARD_REVIEW_CHARACTERS,
                    MAX_REVIEW_CHARACTERS,
                )
            ],
        }

    def upload_batch(self, session_id: str, sequence: int, payload: Dict) -> Dict:
        self._require_enabled()
        self._require_object(
            payload,
            {
                "uploadToken",
                "blocks",
                "characterCount",
                "contentSha256",
                "structureSha256",
                "batchId",
                "range",
                "editSequence",
            },
        )
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                    "全篇审查快照不存在或已过期。",
                    status_code=404,
                )
            if session.get("status") != "uploading":
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照状态不允许当前操作。",
                    status_code=409,
                )
            self._verify_upload_token(session, payload)
            batch_id = self._optional_string(payload, "batchId", "", 96).strip()
            if sequence < len(session["batches"]):
                existing = session["batches"][sequence]
                if batch_id and existing.get("batchId") == batch_id:
                    if existing.get("contentSha256") != payload.get("contentSha256"):
                        raise AdapterError(
                            "FULL_DOCUMENT_REVIEW_BATCH_IDEMPOTENCY_CONFLICT",
                            "同一全篇审查批次编号不能绑定不同正文。",
                            status_code=409,
                        )
                    return {
                        "sessionId": session_id,
                        "sequence": sequence,
                        "status": "uploaded",
                        "reviewCharacterCount": sum(
                            item["characterCount"] for item in session["batches"]
                        ),
                        "tableCount": session.get("tableCount", 0),
                        "cellCount": session.get("cellCount", 0),
                        "structureSha256": existing.get("structureSha256", ""),
                        "idempotent": True,
                    }
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_SEQUENCE_INVALID",
                    "全篇审查正文批次序号不连续。",
                    status_code=409,
                )
            if sequence != len(session["batches"]):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_SEQUENCE_INVALID",
                    "全篇审查正文批次序号不连续。",
                    status_code=409,
                )
            existing_batches = deepcopy(session["batches"])
        blocks = payload.get("blocks")
        if not isinstance(blocks, list) or not blocks or len(blocks) > MAX_REVIEW_BLOCKS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_BATCH_INVALID", "正文批次不能为空。"
            )
        previous_index = max(
            [
                item.get("paragraphIndex", 0)
                for batch in existing_batches
                for item in batch.get("blocks", [])
            ]
            or [0]
        )
        normalized_blocks = self._normalize_review_blocks(blocks, previous_index)
        seen_ids = {
            item["blockId"]
            for batch in existing_batches
            for item in batch["blocks"]
        }
        for item in normalized_blocks:
            if item["blockId"] in seen_ids:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "正文内容块标识必须在整份快照内唯一。",
                )
            seen_ids.add(item["blockId"])
        batch_range = self._normalize_range(payload.get("range"))
        current_ids = {item["blockId"] for item in normalized_blocks}
        for key in ("start", "end"):
            if isinstance(batch_range.get(key), str) and batch_range[key] not in current_ids:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_RANGE_INVALID", "正文原文范围未落在当前批次内。"
                )
        batch_text = "\n".join(self._block_texts(normalized_blocks))
        character_count = sum(_review_character_count(text) for text in self._block_texts(normalized_blocks))
        expected_hash = _sha256_text(batch_text)
        expected_structure_hash = self._structure_sha256(normalized_blocks)
        total_count = character_count + sum(
            batch["characterCount"] for batch in existing_batches
        )
        if (
            self._request_int(
                payload.get("characterCount"),
                "FULL_DOCUMENT_REVIEW_BATCH_INVALID",
                "正文批次字符数格式无效。",
            )
            != character_count
            or self._required_string(
                payload, "contentSha256", "FULL_DOCUMENT_REVIEW_BATCH_INVALID", 64
            ) != expected_hash
            or (
                "structureSha256" in payload
                and self._required_string(
                    payload, "structureSha256", "FULL_DOCUMENT_REVIEW_BATCH_INVALID", 64
                ) != expected_structure_hash
            )
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_BATCH_HASH_MISMATCH",
                "正文批次字符数或哈希校验失败。",
                status_code=409,
            )
        if total_count > MAX_REVIEW_CHARACTERS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TOO_LARGE",
                "当前单分片全篇审查最多支持 20,000 审查字符。",
                status_code=413,
            )
        batch = {
            "sequence": sequence,
            "batchId": self._optional_string(payload, "batchId", "", 96).strip(),
            "blocks": normalized_blocks,
            "characterCount": character_count,
            "contentSha256": expected_hash,
            "structureSha256": expected_structure_hash,
            "range": batch_range,
            "editSequence": payload.get("editSequence"),
        }
        with self._lock:
            if (
                session.get("status") != "uploading"
                or sequence != len(session["batches"])
            ):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_SEQUENCE_INVALID",
                    "全篇审查正文批次已被其他请求更新。",
                    status_code=409,
                )
            session["status"] = "uploading_batch"
        try:
            self._write_private_json(
                self.snapshot_path(session_id) / "batch-{0}.json".format(sequence),
                batch,
            )
        except Exception:
            with self._lock:
                if session.get("status") == "uploading_batch":
                    session["status"] = "uploading"
            raise
        with self._lock:
            session["batches"].append(batch)
            if session.get("editSequence") is None:
                session["editSequence"] = payload.get("editSequence")
            session["tableCount"] = session.get("tableCount", 0) + self._count_tables(normalized_blocks)
            session["cellCount"] = session.get("cellCount", 0) + self._count_cells(normalized_blocks)
            session["expiresAt"] = self._wall_clock() + self._staging_ttl_seconds
            session["status"] = "uploading"
            refreshed_session = self._safe_session(session)
        self._write_private_json(
            self.snapshot_path(session_id) / "session.json", refreshed_session
        )
        return {
            "sessionId": session_id,
            "sequence": sequence,
            "status": "uploaded",
            "reviewCharacterCount": total_count,
            "tableCount": session.get("tableCount", 0),
            "cellCount": session.get("cellCount", 0),
            "structureSha256": expected_structure_hash,
            "idempotent": False,
        }

    def _normalize_review_blocks(
        self, blocks: List[Dict], previous_paragraph_index: int = 0
    ) -> List[Dict]:
        normalized = []
        for item in blocks:
            if not isinstance(item, dict):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BATCH_INVALID", "正文内容块格式无效。"
                )
            block_id = self._required_string(
                item, "blockId", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 96
            ).strip()
            block_type = self._required_string(
                item, "blockType", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 32
            ).strip()
            if not _SAFE_ID.fullmatch(block_id) or block_type not in {
                "paragraph", "heading", "listItem", "table"
            }:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "全篇审查只接受带唯一标识的正文、标题、列表和结构化表格。",
                )
            paragraph_index = self._request_int(
                item.get("paragraphIndex", len(normalized) + 1),
                "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                "正文内容块序号格式无效。",
            )
            if paragraph_index <= previous_paragraph_index:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "正文内容块序号必须是严格递增的正整数。",
                )
            previous_paragraph_index = paragraph_index
            if block_type == "table":
                table_id = self._required_string(
                    item, "tableId", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 96
                ).strip()
                if not _SAFE_ID.fullmatch(table_id):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格标识格式无效。"
                    )
                normalized_table = {
                    "blockId": block_id,
                    "blockType": block_type,
                    "paragraphIndex": paragraph_index,
                    "tableId": table_id,
                    "tableIndex": self._positive_int(item.get("tableIndex", len(normalized) + 1)),
                    "rows": self._normalize_table_rows(item.get("rows")),
                    "nestedTables": self._normalize_nested_tables(item.get("nestedTables", [])),
                    "range": self._normalize_range(item.get("range", item.get("sourceRange"))),
                }
                self._validate_table_relationships(normalized_table)
                normalized.append(normalized_table)
                continue
            text = self._required_string(
                item, "text", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", MAX_REVIEW_CHARACTERS
            )
            if not text:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", "正文内容块不能为空。"
                )
            normalized_item = {
                "blockId": block_id,
                "blockType": block_type,
                "paragraphIndex": paragraph_index,
                "text": text,
                "range": self._normalize_range(item.get("range", item.get("sourceRange"))),
            }
            if "headingLevel" in item:
                normalized_item["headingLevel"] = self._request_int(
                    item["headingLevel"],
                    "FULL_DOCUMENT_REVIEW_BLOCK_INVALID",
                    "标题层级格式无效。",
                )
            if "listLabel" in item:
                normalized_item["listLabel"] = self._required_string(
                    item, "listLabel", "FULL_DOCUMENT_REVIEW_BLOCK_INVALID", 120
                )
            normalized.append(normalized_item)
        return normalized

    def _normalize_table_rows(self, rows: object) -> List[Dict]:
        if not isinstance(rows, list) or not rows or len(rows) > MAX_REVIEW_BLOCKS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "结构化表格必须包含有效行。"
            )
        normalized = []
        for row_index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not isinstance(row.get("cells"), list):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格行或单元格格式无效。"
                )
            actual_row_index = self._positive_int(row.get("rowIndex", row_index))
            cells = []
            for column_index, cell in enumerate(row["cells"], 1):
                if not isinstance(cell, dict):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格单元格格式无效。"
                    )
                cell_id = self._required_string(
                    cell, "cellId", "FULL_DOCUMENT_REVIEW_TABLE_INVALID", 96
                ).strip()
                if not _SAFE_ID.fullmatch(cell_id):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "单元格标识格式无效。"
                    )
                text = self._required_string(
                    cell, "text", "FULL_DOCUMENT_REVIEW_TABLE_INVALID", MAX_REVIEW_CHARACTERS
                )
                cells.append({
                    "cellId": cell_id,
                    "rowIndex": self._positive_int(cell.get("rowIndex", actual_row_index)),
                    "columnIndex": self._positive_int(cell.get("columnIndex", column_index)),
                    "rowSpan": self._positive_int(cell.get("rowSpan", 1)),
                    "columnSpan": self._positive_int(cell.get("columnSpan", 1)),
                    "mergeId": self._optional_string(cell, "mergeId", "", 96),
                    "text": text,
                    "nestedTableIds": self._string_list_values(cell.get("nestedTableIds", [])),
                    "range": self._normalize_range(cell.get("range", cell.get("sourceRange"))),
                })
            normalized.append({"rowIndex": actual_row_index, "cells": cells})
        return normalized

    def _normalize_nested_tables(self, tables: object) -> List[Dict]:
        if not isinstance(tables, list) or len(tables) > MAX_REVIEW_BLOCKS:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "嵌套表格集合格式无效。"
            )
        normalized = []
        for table in tables:
            if not isinstance(table, dict):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "嵌套表格格式无效。"
                )
            table_id = self._required_string(
                table, "tableId", "FULL_DOCUMENT_REVIEW_TABLE_INVALID", 96
            ).strip()
            if not _SAFE_ID.fullmatch(table_id):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "嵌套表格标识格式无效。"
                )
            normalized.append({
                "tableId": table_id,
                "parentCellId": self._optional_string(table, "parentCellId", "", 96),
                "rows": self._normalize_table_rows(table.get("rows")),
                "nestedTables": self._normalize_nested_tables(table.get("nestedTables", [])),
            })
        return normalized

    def _validate_table_relationships(self, table: Dict) -> None:
        nested_tables = table.get("nestedTables", [])
        nested_ids = [nested.get("tableId", "") for nested in nested_tables]
        if len(nested_ids) != len(set(nested_ids)):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "嵌套表格标识必须唯一。"
            )
        cell_ids = {
            cell.get("cellId", "")
            for row in table.get("rows", [])
            for cell in row.get("cells", [])
        }
        referenced_ids = {
            nested_id
            for row in table.get("rows", [])
            for cell in row.get("cells", [])
            for nested_id in cell.get("nestedTableIds", [])
        }
        if not referenced_ids.issubset(set(nested_ids)):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID",
                "表格单元格引用的嵌套表格不存在于当前结构中。",
            )
        for nested in nested_tables:
            parent_cell_id = nested.get("parentCellId", "")
            if parent_cell_id and parent_cell_id not in cell_ids:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_TABLE_INVALID",
                    "嵌套表格的父单元格不存在于当前结构中。",
                )
            self._validate_table_relationships(nested)

    @staticmethod
    def _normalize_range(value: object) -> Dict:
        if value is None:
            return {}
        if not isinstance(value, dict) or set(value) - {"start", "end", "area"}:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_RANGE_INVALID", "正文原文范围格式无效。"
            )
        normalized = {}
        for key in ("start", "end"):
            if key in value:
                if not (
                    (type(value[key]) is int and value[key] >= 0)
                    or (isinstance(value[key], str) and _SAFE_ID.fullmatch(value[key]))
                ):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_RANGE_INVALID", "正文原文范围格式无效。"
                    )
                normalized[key] = value[key]
        if "area" in value:
            if not isinstance(value["area"], str) or not value["area"]:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_RANGE_INVALID", "正文原文范围格式无效。"
                )
            normalized["area"] = value["area"]
        if (
            "start" in normalized
            and "end" in normalized
            and type(normalized["start"]) is int
            and type(normalized["end"]) is int
            and normalized["end"] < normalized["start"]
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_RANGE_INVALID", "正文原文范围格式无效。"
            )
        return normalized

    @staticmethod
    def _positive_int(value: object) -> int:
        if type(value) is not int or value <= 0:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格跨度必须是正整数。"
            )
        return value

    @staticmethod
    def _string_list_values(value: object) -> List[str]:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and 0 < len(item) <= 96 for item in value
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_TABLE_INVALID", "表格关系标识格式无效。"
            )
        return list(value)

    @classmethod
    def _block_texts(cls, blocks: List[Dict]) -> List[str]:
        values = []
        for block in blocks:
            if block["blockType"] != "table":
                values.append(block["text"])
            else:
                values.extend(cls._table_texts(block))
        return values

    @classmethod
    def _structure_sha256(cls, blocks: List[Dict]) -> str:
        return _sha256_text(
            json.dumps(
                [cls._structure_projection(block) for block in blocks],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    @classmethod
    def _structure_projection(cls, block: Dict) -> Dict:
        projection = {
            "blockId": block["blockId"],
            "blockType": block["blockType"],
            "paragraphIndex": int(block.get("paragraphIndex", 0)),
            "headingLevel": int(block.get("headingLevel", 0) or 0),
            "listLabel": str(block.get("listLabel", "") or ""),
        }
        if block["blockType"] != "table":
            return projection

        def project_table(table: Dict) -> Dict:
            return {
                "tableId": str(table.get("tableId", "")),
                "tableIndex": int(table.get("tableIndex", 0) or 0),
                "rows": [
                    {
                        "rowIndex": int(row.get("rowIndex", 0)),
                        "cells": [
                            {
                                "cellId": str(cell.get("cellId", "")),
                                "rowIndex": int(cell.get("rowIndex", 0)),
                                "columnIndex": int(cell.get("columnIndex", 0)),
                                "rowSpan": int(cell.get("rowSpan", 1)),
                                "columnSpan": int(cell.get("columnSpan", 1)),
                                "mergeId": str(cell.get("mergeId", "") or ""),
                                "nestedTableIds": list(cell.get("nestedTableIds", [])),
                            }
                            for cell in row.get("cells", [])
                        ],
                    }
                    for row in table.get("rows", [])
                ],
                "nestedTables": [project_table(nested) for nested in table.get("nestedTables", [])],
            }

        projection["table"] = project_table(block)
        return projection

    @classmethod
    def _table_texts(cls, table: Dict) -> List[str]:
        values = []
        for row in table.get("rows", []):
            for cell in row.get("cells", []):
                values.append(cell["text"])
        for nested in table.get("nestedTables", []):
            values.extend(cls._table_texts(nested))
        return values

    @classmethod
    def _count_tables(cls, blocks: List[Dict]) -> int:
        def count_table(table: Dict) -> int:
            return 1 + sum(count_table(nested) for nested in table.get("nestedTables", []))

        return sum(count_table(block) for block in blocks if block["blockType"] == "table")

    @classmethod
    def _count_cells(cls, blocks: List[Dict]) -> int:
        def count_table(table: Dict) -> int:
            return sum(len(row.get("cells", [])) for row in table.get("rows", [])) + sum(
                count_table(nested) for nested in table.get("nestedTables", [])
            )

        return sum(
            count_table(block)
            for block in blocks if block["blockType"] == "table"
        )

    def commit_snapshot(self, session_id: str, payload: Dict) -> Dict:
        self._require_enabled()
        self._require_object(payload, {
            "uploadToken", "batchCount", "reviewCharacterCount", "contentSha256",
            "verificationSha256", "verification", "structureSha256"
        })
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                    "全篇审查快照不存在或已过期。",
                    status_code=404,
                )
            if session.get("status") != "uploading":
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照状态不允许当前操作。",
                    status_code=409,
                )
            self._verify_upload_token(session, payload)
            snapshot_data = deepcopy(session)
        blocks = [
            item for batch in snapshot_data["batches"] for item in batch["blocks"]
        ]
        source_text = "\n".join(self._block_texts(blocks))
        character_count = sum(_review_character_count(text) for text in self._block_texts(blocks))
        digest = _sha256_text(source_text)
        structure_digest = self._structure_sha256(blocks)
        table_count = sum(self._count_tables(batch["blocks"]) for batch in snapshot_data["batches"])
        cell_count = sum(self._count_cells(batch["blocks"]) for batch in snapshot_data["batches"])
        verification = payload.get("verification")
        verification_valid = self._verification_matches(
            verification,
            batch_count=len(snapshot_data["batches"]),
            block_count=len(blocks),
            table_count=table_count,
            cell_count=cell_count,
            character_count=character_count,
            digest=digest,
            structure_digest=structure_digest,
            edit_sequence=snapshot_data.get("editSequence"),
        )
        if "tables" in snapshot_data.get("coverage", {}).get("includedRegions", []):
            verification_valid = verification_valid and isinstance(verification, dict) and (
                verification.get("structureSha256") == structure_digest
            )
        legacy_verification_valid = (
            self._required_string(
                payload, "verificationSha256", "FULL_DOCUMENT_REVIEW_COMMIT_INVALID", 64
            ) == digest
            if "verification" not in payload
            else True
        )
        valid = (
            self._request_int(
                payload.get("batchCount"),
                "FULL_DOCUMENT_REVIEW_COMMIT_INVALID",
                "快照批次数格式无效。",
            )
            == len(snapshot_data["batches"])
            and self._request_int(
                payload.get("reviewCharacterCount"),
                "FULL_DOCUMENT_REVIEW_COMMIT_INVALID",
                "快照字符数格式无效。",
            )
            == character_count
            and self._required_string(
                payload, "contentSha256", "FULL_DOCUMENT_REVIEW_COMMIT_INVALID", 64
            ) == digest
            and (
                "structureSha256" not in payload
                or self._required_string(
                    payload, "structureSha256", "FULL_DOCUMENT_REVIEW_COMMIT_INVALID", 64
                ) == structure_digest
            )
            and legacy_verification_valid
            and verification_valid
            and 0 < character_count <= MAX_REVIEW_CHARACTERS
        )
        if not valid:
            with self._lock:
                if (
                    session.get("status") != "uploading"
                    or session.get("batches") != snapshot_data.get("batches")
                ):
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                        "全篇审查快照已被其他请求更新。",
                        status_code=409,
                    )
                session["status"] = "invalidating"
            self._remove_snapshot(session_id)
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_SNAPSHOT_MISMATCH",
                "两遍正文校验不一致，本次全篇审查快照已删除，请重新发起。",
                status_code=409,
            )
        capacity = classify_review_capacity(character_count)
        snapshot_token = secrets.token_urlsafe(32)
        confirmation_token = secrets.token_urlsafe(32) if capacity["requiresConfirmation"] else ""
        with self._lock:
            if (
                session.get("status") != "uploading"
                or session.get("batches") != snapshot_data.get("batches")
            ):
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照已被其他请求更新。",
                    status_code=409,
                )
            self._verify_upload_token(session, payload)
            previous_session = deepcopy(session)
            session["status"] = "committing"
        committed_session = deepcopy(previous_session)
        committed_session.update({
            "status": "awaiting_confirmation" if capacity["requiresConfirmation"] else "committed",
            "uploadTokenSha256": "",
            "snapshotTokenSha256": _sha256_text(snapshot_token),
            "sourceText": source_text,
            "blocks": blocks,
            "reviewCharacterCount": character_count,
            "contentSha256": digest,
            "structureSha256": structure_digest,
            "blockCount": len(blocks),
            "tableCount": table_count,
            "cellCount": cell_count,
            "capacity": capacity,
            "confirmationTokenSha256": _sha256_text(confirmation_token) if confirmation_token else "",
            "confirmationExpiresAt": self._wall_clock() + LARGE_SNAPSHOT_CONFIRMATION_TTL_SECONDS if confirmation_token else None,
            "committedAt": self._wall_clock(),
        })
        try:
            self._write_private_json(
                self.snapshot_path(session_id) / "snapshot.json",
                self._safe_snapshot(committed_session),
            )
        except Exception:
            with self._lock:
                if session.get("status") == "committing":
                    session.clear()
                    session.update(previous_session)
            raise
        with self._lock:
            session.clear()
            session.update(committed_session)
        return {
            "snapshotId": session_id,
            "status": committed_session["status"],
            "reviewCharacterCount": character_count,
            "contentSha256": digest,
            "structureSha256": structure_digest,
            "chunkCount": capacity["initialChunkCount"],
            "capacity": capacity,
            "tableCount": table_count,
            "cellCount": cell_count,
            "snapshotToken": snapshot_token,
            "confirmationToken": confirmation_token,
        }

    def delete_snapshot(
        self, session_id: str, payload: Optional[Dict] = None, require_token: bool = True
    ) -> Dict:
        self._require_enabled()
        payload = {} if payload is None else payload
        self._require_object(payload, {"uploadToken", "snapshotToken"})
        with self._lock:
            session = self._sessions.get(session_id)
        if session is not None and require_token:
            if session.get("status") == "uploading":
                self._verify_upload_token(session, payload)
            else:
                self._verify_snapshot_token(session, payload)
        self._remove_snapshot(session_id)
        return {"snapshotId": session_id, "status": "deleted"}

    def start_job(self, payload: Dict, trace_id: str) -> Dict:
        self._require_enabled()
        self._require_object(
            payload,
            {
                "snapshotId",
                "snapshotToken",
                "clientJobId",
                "confirmLarge",
                "confirmationToken",
            },
        )
        snapshot_id = self._required_string(
            payload, "snapshotId", "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND", 96
        ).strip()
        snapshot_token = self._required_string(
            payload, "snapshotToken", "FULL_DOCUMENT_REVIEW_SNAPSHOT_TOKEN_INVALID", 256
        )
        task_auth = self.provider_client.resolve_task_auth("word.document_review")
        self._require_full_review_ready(task_auth)
        requested_job_id = self._optional_string(payload, "clientJobId", "", 96).strip()
        if requested_job_id and not _SAFE_ID.fullmatch(requested_job_id):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_JOB_ID_INVALID",
                "全篇审查客户端任务编号格式无效。",
            )
        job_id = (
            requested_job_id
            if _SAFE_ID.fullmatch(requested_job_id)
            else "full-review-job-{0}".format(secrets.token_hex(16))
        )
        with self._lock:
            session = self._sessions.get(snapshot_id)
            if session is None:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                    "全篇审查快照不存在或已过期。",
                    status_code=404,
                )
            if session.get("status") not in {"committed", "awaiting_confirmation"}:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                    "全篇审查快照状态不允许当前操作。",
                    status_code=409,
                )
            self._verify_snapshot_token(session, {"snapshotToken": snapshot_token})
            if session.get("status") == "awaiting_confirmation":
                if payload.get("confirmLarge") is not True:
                    raise AdapterError(
                        "FULL_DOCUMENT_REVIEW_CONFIRMATION_REQUIRED",
                        "大型全篇审查需要用户确认字符数、初始分片和调用上限。",
                        status_code=409,
                    )
                self._verify_confirmation_token(session, payload)
                session["confirmationTokenSha256"] = ""
            session["status"] = "submitting"
            session["submittedJobId"] = job_id
            snapshot = {
                "snapshotId": snapshot_id,
                "jobId": job_id,
                "traceId": trace_id,
                "sourceText": session["sourceText"],
                "blocks": deepcopy(session["blocks"]),
                "documentType": session["documentType"],
                "reviewPrompt": session["reviewPrompt"],
                "coverage": deepcopy(session["coverage"]),
                "reviewCharacterCount": session["reviewCharacterCount"],
                "contentSha256": session["contentSha256"],
                "capacity": deepcopy(session["capacity"]),
                "tableCount": session.get("tableCount", 0),
                "cellCount": session.get("cellCount", 0),
                "committedAt": session["committedAt"],
                "taskAuth": task_auth,
            }
        try:
            job = self.coordinator.submit(
                job_id=job_id,
                trace_id=trace_id,
                task_type=TASK_TYPE,
                runner=self._run_job,
                snapshot=snapshot,
                failure_code="FULL_DOCUMENT_REVIEW_JOB_FAILED",
                failure_message="全篇审查任务失败，未生成报告。",
                safe_failure_codes={
                    "FULL_DOCUMENT_REVIEW_RESULT_INVALID",
                    "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
                    "MODEL_CONFIG_INCOMPLETE",
                    "MODEL_DIRECT_REQUIRED",
                },
                public_metadata={
                    "reviewMode": "full",
                    "snapshotId": snapshot_id,
                    "chunkCount": snapshot["capacity"]["initialChunkCount"],
                    "capacity": deepcopy(snapshot["capacity"]),
                },
                allow_running_cancel=True,
            )
            if job.get("snapshotId") != snapshot_id:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_JOB_ID_CONFLICT",
                    "客户端任务编号已绑定到其他全篇审查快照。",
                    status_code=409,
                )
        except Exception:
            with self._lock:
                if session.get("status") == "submitting":
                    session["status"] = (
                        "awaiting_confirmation"
                        if session.get("capacity", {}).get("requiresConfirmation")
                        else "committed"
                    )
                    session.pop("submittedJobId", None)
            raise
        with self._lock:
            session["status"] = "submitted"
        return job

    def get_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if job is None:
            return None
        job.pop("result", None)
        result = self._get_report(job_id) if job.get("status") == "completed" else None
        job["reportAvailable"] = bool(
            job.get("status") == "completed" and isinstance(result, dict)
        )
        if isinstance(result, dict):
            job["coverage"] = result.get("coverage", {})
            job["enumerationStatus"] = result.get("enumerationStatus", "")
            job["issueCount"] = result.get("issueCount", 0)
            job["categoryCounts"] = deepcopy(result.get("categoryCounts", {}))
            job["severityCounts"] = deepcopy(result.get("severityCounts", {}))
            job["statusCounts"] = deepcopy(result.get("statusCounts", {}))
        return job

    def cancel_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        job = self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)
        if job and job.get("status") == "cancelled":
            snapshot_id = str(job.get("snapshotId", ""))
            if snapshot_id:
                self._remove_snapshot(snapshot_id)
        return job

    def get_report(self, job_id: str) -> Dict:
        self._require_enabled()
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if job is None:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_JOB_NOT_FOUND",
                "全篇审查任务不存在或已过期。",
                status_code=404,
            )
        report = self._get_report(job_id)
        if job.get("status") != "completed":
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REPORT_NOT_AVAILABLE",
                "全篇审查尚未生成可用的结构化报告。",
                status_code=409,
            )
        if not isinstance(report, dict):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_RESULT_NOT_FOUND",
                "全篇审查结果不存在或已删除。",
                status_code=404,
            )
        return self._public_report(report)

    def list_issues(
        self,
        job_id: str,
        page_size: Optional[int] = None,
        cursor: str = "",
        severity: str = "",
        category: str = "",
        location: str = "",
        status: str = "",
        sort: str = "source",
    ) -> Dict:
        report = self._require_report(job_id)
        size = DEFAULT_ISSUE_PAGE_SIZE if page_size is None else page_size
        if type(size) is not int or not 0 < size <= MAX_ISSUE_PAGE_SIZE:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_PAGE_SIZE_INVALID",
                "问题分页大小必须是 1 到 100 之间的整数。",
            )
        if severity and severity not in _SEVERITIES:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_FILTER_INVALID",
                "问题严重程度筛选值无效。",
            )
        if category and category not in _CATEGORIES:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_FILTER_INVALID",
                "问题类别筛选值无效。",
            )
        if status and status not in _ISSUE_STATUSES:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_STATUS_INVALID",
                "问题处理状态无效。",
            )
        if sort not in {"source", "severity"}:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_SORT_INVALID",
                "问题排序方式无效。",
            )
        if not isinstance(cursor, str) or len(cursor) > 256:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        issues = []
        for index, issue in enumerate(report.get("issues", [])):
            item = deepcopy(issue)
            item.setdefault("status", "open")
            item["_sourceOrder"] = index
            if severity and item.get("severity") != severity:
                continue
            if category and item.get("category") != category:
                continue
            if location and item.get("location", "body") != location:
                continue
            if status and item.get("status") != status:
                continue
            issues.append(item)
        if sort == "severity":
            issues.sort(key=lambda item: (
                _SEVERITY_ORDER.get(item.get("severity"), 99),
                item.get("_sourceOrder", 0),
                item.get("issueId", ""),
            ))
        else:
            issues.sort(key=lambda item: (
                item.get("_sourceOrder", 0), item.get("issueId", "")
            ))
        offset = 0
        if cursor:
            cursor_issue_id = self._decode_issue_cursor(cursor)
            matching_index = next(
                (index for index, item in enumerate(issues)
                 if item.get("issueId") == cursor_issue_id),
                None,
            )
            if matching_index is None:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_ISSUES_CURSOR_INVALID",
                    "问题分页游标已失效，请从第一页重新读取。",
                )
            offset = matching_index + 1
        selected = issues[offset : offset + size]
        for item in selected:
            item.pop("_sourceOrder", None)
        next_cursor = ""
        if offset + size < len(issues) and selected:
            next_cursor = self._encode_issue_cursor(selected[-1]["issueId"])
        return {
            "items": selected,
            "total": len(issues),
            "pageSize": size,
            "page": (offset // size) + 1,
            "nextCursor": next_cursor,
            "hasMore": bool(next_cursor),
            "filters": {
                "severity": severity,
                "category": category,
                "location": location,
                "status": status,
            },
            "sort": sort,
        }

    def update_issue_status(self, job_id: str, issue_id: str, status: str) -> Dict:
        if not _SAFE_ID.fullmatch(str(issue_id or "")):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_NOT_FOUND",
                "全篇审查问题不存在或已过期。",
                status_code=404,
            )
        if status not in _ISSUE_STATUSES:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUE_STATUS_INVALID",
                "问题处理状态无效。",
            )
        report = self._require_report(job_id)
        for issue in report.get("issues", []):
            if issue.get("issueId") == issue_id:
                issue["status"] = status
                self._refresh_report_counts(report)
                self._save_report(job_id, report)
                return deepcopy(issue)
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_ISSUE_NOT_FOUND",
            "全篇审查问题不存在或已过期。",
            status_code=404,
        )

    def delete_result(self, job_id: str) -> Dict:
        self._require_report(job_id)
        with self._lock:
            self._reports.pop(job_id, None)
        report_path = self._report_path(job_id)
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"jobId": job_id, "status": "deleted"}

    def _run_job(self, snapshot: Dict, progress) -> Dict:
        job_id = str(snapshot.get("jobId", ""))
        call_count = 0
        call_limit = int(snapshot.get("capacity", {}).get("callLimit", 0) or 0)

        def call_provider(chunk: Dict, correction: bool = False) -> str:
            nonlocal call_count
            if call_count >= call_limit:
                raise AdapterError(
                    "FULL_DOCUMENT_REVIEW_CALL_LIMIT_EXCEEDED",
                    "全篇审查已达到当前容量档位的模型调用上限，未继续发起模型请求。",
                    status_code=409,
                )
            call_count += 1
            return self.provider_client.full_document_review_chunk(
                chunk["sourceText"],
                snapshot.get("traceId", ""),
                chunk["chunkId"],
                snapshot["documentType"],
                snapshot["reviewPrompt"],
                snapshot["taskAuth"],
                correction=correction,
                blocks=chunk["blocks"],
            )

        try:
            parsed_chunks = []
            chunks = self._build_review_chunks(snapshot)
            for chunk in chunks:
                self._raise_if_cancelled(job_id)
                progress("provider_processing")
                answer = call_provider(chunk)
                self._raise_if_cancelled(job_id)
                try:
                    parsed = self._parse_strict_result(answer, snapshot, chunk)
                except AdapterError:
                    self._raise_if_cancelled(job_id)
                    corrected = call_provider(chunk, correction=True)
                    self._raise_if_cancelled(job_id)
                    parsed = self._parse_strict_result(corrected, snapshot, chunk)
                parsed_chunks.append(parsed)
            self._raise_if_cancelled(job_id)
            progress("parsing")
            report = self._build_report(snapshot, parsed_chunks)
            self._save_report(job_id, report)
            return report
        finally:
            self._remove_snapshot(str(snapshot.get("snapshotId", "")))

    @classmethod
    def _build_review_chunks(cls, snapshot: Dict) -> List[Dict]:
        chunks = []
        current = []
        current_count = 0
        expanded_blocks = []
        for block in snapshot["blocks"]:
            block_count = sum(
                _review_character_count(text) for text in cls._block_texts([block])
            )
            if block["blockType"] != "table" and block_count > REVIEW_CHUNK_HARD_LIMIT:
                text = block.get("text", "")
                for offset in range(0, len(text), REVIEW_CHUNK_HARD_LIMIT):
                    fragment = deepcopy(block)
                    fragment["blockId"] = "{0}-part-{1}".format(
                        block["blockId"], offset // REVIEW_CHUNK_HARD_LIMIT + 1
                    )
                    fragment["text"] = text[offset : offset + REVIEW_CHUNK_HARD_LIMIT]
                    expanded_blocks.append(fragment)
            else:
                expanded_blocks.append(block)
        for block in expanded_blocks:
            block_count = sum(
                _review_character_count(text) for text in cls._block_texts([block])
            )
            if current and current_count + block_count > REVIEW_CHUNK_HARD_LIMIT:
                chunks.append(cls._make_review_chunk(len(chunks) + 1, current))
                current = []
                current_count = 0
            current.append(block)
            current_count += block_count
        if current:
            chunks.append(cls._make_review_chunk(len(chunks) + 1, current))
        return chunks

    @classmethod
    def _make_review_chunk(cls, number: int, blocks: List[Dict]) -> Dict:
        return {
            "chunkId": "chunk-{0}".format(number),
            "blocks": deepcopy(blocks),
            "sourceText": "\n".join(cls._block_texts(blocks)),
        }

    def _parse_strict_result(
        self, answer: object, snapshot: Dict, chunk: Optional[Dict] = None
    ) -> Dict:
        chunk = chunk or {
            "chunkId": "chunk-1",
            "blocks": snapshot["blocks"],
        }
        try:
            payload = json.loads(answer) if isinstance(answer, str) else None
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            self._invalid_result()
        if set(payload) != {
            "schemaVersion",
            "chunkId",
            "summary",
            "enumerationStatus",
            "issues",
        }:
            self._invalid_result()
        if (
            payload.get("schemaVersion") != CHUNK_SCHEMA_VERSION
            or payload.get("chunkId") != chunk["chunkId"]
            or not isinstance(payload.get("summary"), str)
            or len(payload.get("summary", "")) > 4000
            or payload.get("enumerationStatus") not in _ENUMERATION_STATUSES
            or not isinstance(payload.get("issues"), list)
            or len(payload.get("issues", [])) > 200
        ):
            self._invalid_result()
        blocks = self._review_anchor_blocks(chunk["blocks"])
        normalized_issues = []
        for item in payload["issues"]:
            required = {
                "category",
                "severity",
                "anchorId",
                "originalText",
                "problem",
                "suggestion",
                "suggestedRewrite",
            }
            if not isinstance(item, dict) or set(item) != required:
                self._invalid_result()
            if not all(
                isinstance(item.get(field), str)
                for field in required
            ):
                self._invalid_result()
            anchor_id = item["anchorId"]
            original_text = item["originalText"]
            if (
                item.get("category") not in _CATEGORIES
                or item.get("severity") not in _SEVERITIES
                or not 0 < len(anchor_id) <= 96
                or anchor_id not in blocks
                or not 0 < len(original_text) <= 1000
                or original_text not in blocks[anchor_id]["text"]
                or not item["problem"].strip()
                or len(item["problem"]) > 2000
                or not item["suggestion"].strip()
                or len(item["suggestion"]) > 3000
                or len(item["suggestedRewrite"]) > 4000
            ):
                self._invalid_result()
            issue_id = "issue-{0}".format(
                _sha256_text(
                    "|".join(
                        [
                            snapshot["contentSha256"],
                            str(item["category"]),
                            anchor_id,
                            original_text,
                            str(item["problem"]),
                        ]
                    )
                )[:24]
            )
            normalized_issues.append({
                "issueId": issue_id,
                "location": blocks[anchor_id].get("location", "body"),
                **item,
            })
        return {**payload, "issues": normalized_issues}

    @classmethod
    def _review_anchor_blocks(cls, blocks: List[Dict]) -> Dict[str, Dict]:
        anchors = {}

        def add_table_cells(table: Dict) -> None:
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    anchors[cell["cellId"]] = {**cell, "location": "table"}
            for nested in table.get("nestedTables", []):
                add_table_cells(nested)

        for block in blocks:
            anchors[block["blockId"]] = {
                "text": "\n".join(cls._block_texts([block])),
                "location": (
                    "table"
                    if block["blockType"] == "table"
                    else "chapter" if block["blockType"] == "heading" else "body"
                ),
            }
            if block["blockType"] != "table":
                continue
            add_table_cells(block)
        return anchors

    @staticmethod
    def _invalid_result() -> None:
        raise AdapterError(
            "FULL_DOCUMENT_REVIEW_RESULT_INVALID",
            "模型返回结果不符合版本化全篇审查 JSON 契约，未生成报告。",
            status_code=502,
        )

    @staticmethod
    def _build_report(snapshot: Dict, parsed_chunks: List[Dict]) -> Dict:
        paragraph_count = len(snapshot["blocks"])
        issues = []
        summaries = []
        enumeration_status = "complete"
        for parsed in parsed_chunks:
            summaries.append(parsed["summary"])
            issues.extend(parsed["issues"])
            if parsed["enumerationStatus"] != "complete":
                enumeration_status = "limited"
        unique_issues = {}
        for issue in issues:
            unique_issues[issue["issueId"]] = issue
        report = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "reviewMode": "full",
            "snapshot": {
                "snapshotId": snapshot["snapshotId"],
                "contentSha256": snapshot["contentSha256"],
                "committedAt": snapshot["committedAt"],
            },
            "capacity": deepcopy(snapshot["capacity"]),
            "summary": "\n".join(summary for summary in summaries if summary),
            "coverage": {
                "status": "complete",
                "reviewedCharacterCount": snapshot["reviewCharacterCount"],
                "reviewedParagraphCount": sum(
                    1 for block in snapshot["blocks"] if block["blockType"] != "table"
                ),
                "reviewedTableCount": snapshot.get("tableCount", 0),
                "reviewedCellCount": snapshot.get("cellCount", 0),
                "includedRegions": snapshot["coverage"]["includedRegions"],
                "excludedRegions": snapshot["coverage"]["excludedRegions"],
            },
            "enumerationStatus": enumeration_status,
            "disclaimer": "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部问题。",
            "issues": [
                {**issue, "status": issue.get("status", "open"),
                 "location": issue.get("location", "body")}
                for issue in unique_issues.values()
            ],
        }
        FullDocumentReviewService._refresh_report_counts(report)
        return report

    @staticmethod
    def _refresh_report_counts(report: Dict) -> None:
        issues = report.get("issues", [])
        report["issueCount"] = len(issues)
        report["categoryCounts"] = {
            category: sum(1 for issue in issues if issue.get("category") == category)
            for category in sorted(_CATEGORIES)
        }
        report["severityCounts"] = {
            severity: sum(1 for issue in issues if issue.get("severity") == severity)
            for severity in ("high", "medium", "low")
        }
        report["statusCounts"] = {
            status: sum(1 for issue in issues if issue.get("status", "open") == status)
            for status in ("open", "processed", "ignored")
        }

    def _require_report(self, job_id: str) -> Dict:
        self._require_enabled()
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        report = self._get_report(job_id)
        if job is None or job.get("status") != "completed" or not isinstance(report, dict):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REPORT_NOT_AVAILABLE",
                "全篇审查尚未生成可用的结构化报告。",
                status_code=404,
            )
        return report

    def _save_report(self, job_id: str, report: Dict) -> None:
        stored = deepcopy(report)
        stored["reportExpiresAt"] = report.get(
            "reportExpiresAt", self._wall_clock() + REPORT_RESULT_TTL_SECONDS
        )
        stored["reportSha256"] = _report_sha256(stored)
        with self._lock:
            self._reports[job_id] = stored
        self._ensure_root()
        self._write_private_json(self._report_path(job_id), stored)

    def _get_report(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            report = self._reports.get(job_id)
        if isinstance(report, dict):
            if report.get("reportSha256") != _report_sha256(report):
                with self._lock:
                    self._reports.pop(job_id, None)
                return None
            if self._wall_clock() >= float(report.get("reportExpiresAt", 0)):
                with self._lock:
                    self._reports.pop(job_id, None)
                return None
            return deepcopy(report)
        path = self._report_path(job_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            return None
        if (
            not isinstance(report, dict)
            or report.get("reportSha256") != _report_sha256(report)
            or self._wall_clock() >= float(report.get("reportExpiresAt", 0))
        ):
            return None
        with self._lock:
            self._reports[job_id] = report
        return deepcopy(report)

    def _public_report(self, report: Dict) -> Dict:
        public = deepcopy(report)
        public.pop("issues", None)
        public.pop("reportExpiresAt", None)
        public.pop("reportSha256", None)
        public["issuesEndpoint"] = "issues"
        return public

    def export_report(self, job_id: str, output_format: str) -> object:
        report = self._require_report(job_id)
        if output_format == "json":
            report.pop("reportExpiresAt", None)
            report.pop("reportSha256", None)
            return report
        if output_format != "markdown":
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REPORT_FORMAT_INVALID",
                "全篇审查报告仅支持 json 或 markdown 格式。",
            )
        lines = ["# 全篇审查报告", "", report.get("summary") or "审查已完成。", ""]
        lines.append("## 覆盖与统计")
        lines.append("- 审查字符：{0}".format(report.get("coverage", {}).get("reviewedCharacterCount", 0)))
        lines.append("- 问题数量：{0}".format(report.get("issueCount", 0)))
        lines.append("- 问题枚举：{0}".format(report.get("enumerationStatus", "limited")))
        lines.append("")
        for index, issue in enumerate(report.get("issues", []), 1):
            lines.extend([
                "## {0}. {1}".format(index, issue.get("problem", "审查问题")),
                "- 问题编号：{0}".format(issue.get("issueId", "")),
                "- 状态：{0}".format(issue.get("status", "open")),
                "- 严重程度：{0}".format(issue.get("severity", "")),
                "- 原文锚点：{0}".format(issue.get("anchorId", "")),
                "- 原文：{0}".format(issue.get("originalText", "")),
                "- 建议：{0}".format(issue.get("suggestion", "")),
            ])
            if issue.get("suggestedRewrite"):
                lines.append("- 建议改写：{0}".format(issue["suggestedRewrite"]))
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _encode_issue_cursor(issue_id: str) -> str:
        return base64.urlsafe_b64encode(issue_id.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_issue_cursor(cursor: str) -> str:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            issue_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        if not _SAFE_ID.fullmatch(issue_id):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        return issue_id

    @staticmethod
    def _require_full_review_ready(task_auth: Dict) -> None:
        if str(task_auth.get("accessMethod", "")) != ACCESS_DIRECT_MODEL:
            raise AdapterError(
                "MODEL_DIRECT_REQUIRED",
                "全篇审查只支持模型直连配置。",
                status_code=409,
            )
        if not str(task_auth.get("providerBaseUrl", "")).strip() or not str(
            task_auth.get("apiKey", "")
        ).strip() or not str(task_auth.get("modelName", "")).strip():
            raise AdapterError(
                "MODEL_CONFIG_INCOMPLETE",
                "全篇审查模型配置不完整。",
                status_code=409,
            )
        if not task_auth.get("contextWindowTokensExplicit", False):
            raise AdapterError(
                "MODEL_CONTEXT_TOKENS_REQUIRED",
                "全篇审查要求显式上下文容量。",
                status_code=409,
            )
        if task_auth.get("maxOutputTokens") is None:
            raise AdapterError(
                "MODEL_OUTPUT_TOKENS_REQUIRED",
                "全篇审查要求显式最大输出 Token。",
                status_code=409,
            )
        if int(task_auth.get("maxOutputTokens") or 0) < 2048:
            raise AdapterError(
                "MODEL_OUTPUT_TOKENS_TOO_SMALL",
                "全篇审查至少需要 2048 输出 Token。",
                status_code=409,
            )

    def _require_enabled(self) -> None:
        if not full_document_review_enabled():
            raise _full_review_disabled()
        self._cleanup_expired()

    def _require_session(self, session_id: str, status: str) -> Dict:
        if not _SAFE_ID.fullmatch(str(session_id or "")):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                "全篇审查快照不存在或已过期。",
                status_code=404,
            )
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_SNAPSHOT_NOT_FOUND",
                "全篇审查快照不存在或已过期。",
                status_code=404,
            )
        if session.get("status") != status:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_SNAPSHOT_STATE_INVALID",
                "全篇审查快照状态不允许当前操作。",
                status_code=409,
            )
        return session

    @staticmethod
    def _verify_upload_token(session: Dict, payload: Dict) -> None:
        token = payload.get("uploadToken")
        expected = str(session.get("uploadTokenSha256", ""))
        if not isinstance(token, str) or not token or not expected or not secrets.compare_digest(
            _sha256_text(token), expected
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_UPLOAD_TOKEN_INVALID",
                "全篇审查上传凭证无效或已过期。",
                status_code=403,
            )

    @staticmethod
    def _verify_snapshot_token(session: Dict, payload: Dict) -> None:
        token = payload.get("snapshotToken")
        expected = str(session.get("snapshotTokenSha256", ""))
        if not isinstance(token, str) or not token or not expected or not secrets.compare_digest(
            _sha256_text(token), expected
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_SNAPSHOT_TOKEN_INVALID",
                "全篇审查快照凭证无效或已过期。",
                status_code=403,
            )

    @staticmethod
    def _verify_confirmation_token(session: Dict, payload: Dict) -> None:
        token = payload.get("confirmationToken")
        expected = str(session.get("confirmationTokenSha256", ""))
        if not isinstance(token, str) or not token or not expected or not secrets.compare_digest(
            _sha256_text(token), expected
        ):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_CONFIRMATION_TOKEN_INVALID",
                "大型全篇审查确认凭证无效或已过期。",
                status_code=403,
            )

    @staticmethod
    def _verification_matches(
        verification: object,
        batch_count: int,
        block_count: int,
        table_count: int,
        cell_count: int,
        character_count: int,
        digest: str,
        structure_digest: str,
        edit_sequence: object = None,
    ) -> bool:
        if verification is None:
            return True
        if not isinstance(verification, dict):
            return False
        expected = {
            "batchCount": batch_count,
            "blockCount": block_count,
            "tableCount": table_count,
            "cellCount": cell_count,
            "reviewCharacterCount": character_count,
            "contentSha256": digest,
        }
        if "structureSha256" in verification:
            expected["structureSha256"] = structure_digest
        for key, value in expected.items():
            if verification.get(key) != value:
                return False
        if "editSequence" in verification and verification.get("editSequence") != edit_sequence:
            return False
        return True

    @staticmethod
    def _request_int(value: object, code: str, message: str) -> int:
        if type(value) is not int:
            raise AdapterError(code, message)
        return value

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self.coordinator.is_cancel_requested(job_id, task_type=TASK_TYPE):
            raise LongTaskCancelled()

    @staticmethod
    def _require_object(payload: object, allowed_fields) -> None:
        if not isinstance(payload, dict) or set(payload) - set(allowed_fields):
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REQUEST_INVALID",
                "全篇审查请求字段或类型无效。",
            )

    @staticmethod
    def _required_string(payload: Dict, field: str, code: str, max_length: int) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value or len(value) > max_length:
            raise AdapterError(code, "全篇审查请求字段 {0} 无效。".format(field))
        return value

    @staticmethod
    def _optional_string(
        payload: Dict, field: str, default: str, max_length: int
    ) -> str:
        value = payload.get(field, default)
        if not isinstance(value, str) or len(value) > max_length:
            raise AdapterError(
                "FULL_DOCUMENT_REVIEW_REQUEST_INVALID",
                "全篇审查请求字段 {0} 无效。".format(field),
            )
        return value

    @staticmethod
    def _string_list(value: object, allow_empty: bool = False) -> bool:
        return bool(isinstance(value, list) and (value or allow_empty) and all(
            isinstance(item, str) and 0 < len(item) <= 80 for item in value
        ))

    def _cleanup_expired(self, force: bool = False) -> None:
        now = self._wall_clock()
        if not force and now - self._last_cleanup_at < 60:
            return
        self._last_cleanup_at = now
        root = self.staging_root
        if not root.exists() or not root.is_dir():
            return
        try:
            children = list(root.iterdir())
        except OSError:
            return
        for report_path in children:
            if not report_path.is_file() or not report_path.name.startswith("report-"):
                continue
            try:
                with report_path.open("r", encoding="utf-8") as handle:
                    report = json.load(handle)
                if not isinstance(report, dict):
                    report_path.unlink()
                    self._reports.pop(report_path.stem[len("report-"):], None)
                    continue
                expiry = float(report.get("reportExpiresAt", 0))
                if report.get("reportSha256") != _report_sha256(report) or (
                    expiry and now >= expiry
                ):
                    report_path.unlink()
                    self._reports.pop(report_path.stem[len("report-"):], None)
            except (OSError, ValueError, TypeError):
                continue
        for child in children:
            if (
                child.is_symlink()
                or not child.is_dir()
                or not _SAFE_ID.fullmatch(child.name)
            ):
                continue
            try:
                session = self._sessions.get(child.name)
                session_file = child / "session.json"
                if session is None and session_file.exists():
                    try:
                        with session_file.open("r", encoding="utf-8") as handle:
                            session = json.load(handle)
                    except (OSError, ValueError):
                        session = None
                if isinstance(session, dict) and session.get("status") != "awaiting_confirmation":
                    snapshot_file = child / "snapshot.json"
                    if snapshot_file.exists():
                        try:
                            with snapshot_file.open("r", encoding="utf-8") as handle:
                                snapshot_metadata = json.load(handle)
                            if snapshot_metadata.get("status") == "awaiting_confirmation":
                                session = snapshot_metadata
                        except (OSError, ValueError):
                            pass
                expiry = None
                if isinstance(session, dict):
                    expiry = session.get("confirmationExpiresAt") if session.get("status") == "awaiting_confirmation" else session.get("expiresAt")
                expired = (
                    now >= float(expiry)
                    if expiry is not None
                    else now - child.stat().st_mtime > self._staging_ttl_seconds
                )
            except OSError:
                continue
            if expired:
                try:
                    self._remove_snapshot(child.name)
                except OSError:
                    continue

    def start_periodic_cleanup(self, interval_seconds: float = 60.0) -> None:
        if self._cleanup_thread is not None:
            return
        interval = max(float(interval_seconds), 0.05)

        def cleanup_loop() -> None:
            while not self._cleanup_stop.wait(interval):
                try:
                    self._cleanup_expired(force=True)
                except Exception:
                    continue

        self._cleanup_thread = threading.Thread(
            target=cleanup_loop, name="word-full-review-cleanup", daemon=True
        )
        self._cleanup_thread.start()

    def stop_periodic_cleanup(self) -> None:
        self._cleanup_stop.set()

    def _ensure_root(self) -> None:
        root = self.staging_root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(str(root), 0o700)

    @staticmethod
    def _write_private_json(path: Path, payload: Dict) -> None:
        descriptor = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(str(path), 0o600)

    @staticmethod
    def _safe_session(session: Dict) -> Dict:
        return {
            key: value
            for key, value in session.items()
            if key
            not in {
                "uploadTokenSha256",
                "snapshotTokenSha256",
                "confirmationTokenSha256",
                "documentIdSha256",
                "batches",
            }
        }

    @staticmethod
    def _safe_snapshot(session: Dict) -> Dict:
        return {
            key: value
            for key, value in session.items()
            if key not in {
                "uploadTokenSha256",
                "snapshotTokenSha256",
                "confirmationTokenSha256",
                "documentIdSha256",
                "batches",
            }
        }

    def _remove_snapshot(self, snapshot_id: str) -> None:
        if not _SAFE_ID.fullmatch(str(snapshot_id or "")):
            return
        with self._lock:
            self._sessions.pop(snapshot_id, None)
        path = self.snapshot_path(snapshot_id)
        if path.exists():
            shutil.rmtree(str(path))


full_document_review_service = FullDocumentReviewService()
full_document_review_service.start_periodic_cleanup()
