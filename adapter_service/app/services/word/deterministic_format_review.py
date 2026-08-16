import base64
import binascii
import hashlib
import inspect
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import ValidationError

from app.core.errors import AdapterError
from app.core.features import deterministic_format_review_enabled
from app.core.models import WordDocumentRequest
from app.core.outline_level import normalize_outline_level
from app.core.runtime_paths import resolve_runtime_paths
from app.services.document_normalizer import body_paragraphs
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    LongTaskCancelled,
    get_long_task_coordinator,
)
from app.services.word.format_reviewer import (
    WordFormatReviewer,
    build_format_review_model_identity,
)
from app.services.word.format_issue_support import (
    build_format_issue_anchor,
    normalize_paragraph_index,
)
from app.services.word.image_semantics import (
    ImageAssetStore,
    collect_image_inventory,
    select_image_export_groups,
)


TASK_TYPE = "word.format_review.deterministic"
MAX_REVIEW_CHARACTERS = 20_000
MAX_PARAGRAPHS = 200
MAX_SNAPSHOT_BYTES = 512 * 1024
FORMAT_SNAPSHOT_SCHEMA_VERSION = "word.format_review.snapshot.v2"
FORMAT_REPORT_SCHEMA_VERSION = "word.format_review.report.v1"
FORMAT_REPORT_EXPORT_SCHEMA_VERSION = "word.format_review.export.v1"
REPORT_RESULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_ISSUE_PAGE_SIZE = 20
MAX_ISSUE_PAGE_SIZE = 100
MAX_FORMAT_BLOCKS = 10_000
MAX_FORMAT_BATCHES = 1024
MAX_FORMAT_BATCH_BYTES = 2 * 1024 * 1024
MAX_FORMAT_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_FORMAT_TABLE_CELLS = 50_000
MAX_FORMAT_SEGMENTS = 50_000
MAX_FORMAT_UNSUPPORTED_OBJECTS = 5_000
MAX_FORMAT_STANDARD_CHARACTERS = 60_000
MAX_FORMAT_LARGE_CHARACTERS = 120_000
SNAPSHOT_TTL_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
FORMAT_BLOCK_TYPES = {"paragraph", "heading", "listItem", "table", "caption", "context", "image", "unknown"}
FORMAT_SCOPES = {"in_scope", "context"}
FORMAT_ISSUE_STATUSES = {"open", "processed", "ignored"}
FORMAT_ANCHOR_VERIFICATIONS = {"verified", "unverified"}
FORMAT_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
FORMAT_RULE_PROPERTY_PATHS = {
    "page_setup": "documentStructure.pageSetup",
    "font_name": "format.fontName",
    "font_size": "format.fontSize",
    "style_name": "format.styleName",
    "alignment": "format.alignment",
    "line_spacing": "format.lineSpacing",
    "first_line_indent": "format.firstLineIndent",
    "structure.heading_hierarchy": "structure.headingLevel",
    "structure.table_semantics": "table.semanticRole",
    "structure.caption_association": "caption.association",
    "structure.caption_placement": "caption.placement",
    "structure.role_confirmation": "structure.role",
}
FORMAT_RULE_UNITS = {
    "font_size": "pt",
    "line_spacing": "multiple",
    "first_line_indent": "twips",
}


def _report_model_access_method(value: object) -> str:
    labels = {
        "workflow_platform": "平台工作流",
        "direct_model": "模型直连",
    }
    return labels.get(str(value or ""), "未记录")


def _report_semantic_reason(value: object) -> str:
    labels = {
        "no_candidates": "没有需要模型确认的模糊候选，无需调用模型。",
        "provider_not_configured": "未配置可用的模型配置。",
        "format_semantic_protocol_not_ready": "模型语义协议尚未就绪。",
        "model_capability_unknown": "模型能力状态未知，未继续调用。",
        "provider_request_failed": "模型请求失败。",
        "format_semantic_response_invalid": "模型响应无法解析或不符合协议。",
        "format_semantic_candidate_out_of_range": "模型返回了不在候选范围内的结果。",
        "format_semantic_low_confidence": "模型结果置信度低于接受阈值。",
        "format_semantic_zero_accepted": "模型已调用但没有接受任何结果。",
        "ai_budget_limited": "候选数量超过本轮模型处理上限。",
        "semantic_phase_timeout": "语义增强处理超时。",
    }
    return labels.get(str(value or ""), "")


def _report_issue_position(issue: Dict) -> str:
    if issue.get("ruleId") == "page_setup":
        return "页面"
    try:
        paragraph_index = int(issue.get("paragraphIndex"))
    except (TypeError, ValueError):
        paragraph_index = 0
    if paragraph_index > 0 and issue.get("anchorVerification") == "verified":
        return "P{0}".format(paragraph_index)
    return "位置待确认"


def _report_issue_role(issue: Dict) -> str:
    role = str(issue.get("role") or "")
    if issue.get("ruleId") == "structure.heading_hierarchy" or role == "heading":
        return "标题"
    return {
        "body": "正文",
        "table": "表格",
        "page_setup": "页面设置",
    }.get(role, role or "未标注")


def _report_sha256(report: Dict) -> str:
    payload = {key: value for key, value in report.items() if key != "reportSha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _sanitize_export_value(value: object) -> object:
    blocked = {
        "blocks", "formatBlocks", "request", "fullSnapshot", "rawAnswer",
        "rawResponse", "modelResponse", "apiKey", "apiKeyRef", "localPath",
        "tempPath", "stagingPath", "slotPath", "imageAsset", "imageAssets", "imageFiles", "errorDetail",
    }
    blocked_names = {
        re.sub(r"[^a-z0-9]", "", key.casefold()) for key in blocked
    } | {"fulltext", "documenttext", "snapshottext", "modelrawresponse"}
    if isinstance(value, dict):
        return {
            key: _sanitize_export_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
            and re.sub(r"[^a-z0-9]", "", str(key).casefold()) not in blocked_names
        }
    if isinstance(value, list):
        return [_sanitize_export_value(item) for item in value]
    return value


def _short_report_value(value: object, limit: int = 400) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text[:limit]


def _model_dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if hasattr(value, "dict"):
        return value.dict(by_alias=True)
    return deepcopy(value)


def _disabled_error() -> AdapterError:
    return AdapterError(
        "DETERMINISTIC_FORMAT_REVIEW_DISABLED",
        "确定性格式审查功能尚未启用。",
        status_code=403,
    )


class DeterministicFormatReviewService:
    """Feature-gated, read-only snapshot and background review protocol."""

    def __init__(
        self,
        staging_root: Optional[Path] = None,
        reviewer: Optional[WordFormatReviewer] = None,
        coordinator: Optional[LongTaskCoordinator] = None,
        wall_clock=time.time,
    ) -> None:
        self._configured_staging_root = Path(staging_root) if staging_root else None
        self.reviewer = reviewer or WordFormatReviewer()
        self.coordinator = coordinator or get_long_task_coordinator()
        self._wall_clock = wall_clock
        self._snapshots: Dict[str, Dict] = {}
        self._reports: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._snapshot_mutation_lock = threading.Lock()
        self.image_asset_store = ImageAssetStore(self.staging_root / "image-assets")
        self._cleanup_expired()

    @property
    def staging_root(self) -> Path:
        if self._configured_staging_root is not None:
            return self._configured_staging_root
        configured = os.environ.get("AI_WPS_FORMAT_REVIEW_DIR", "").strip()
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_STORAGE_INVALID",
                    "确定性格式审查暂存目录必须是绝对路径。",
                    status_code=500,
                )
            return path
        return resolve_runtime_paths().var_dir / "format-review"

    def create_snapshot(self, request: WordDocumentRequest) -> Dict:
        self._require_enabled()
        if not isinstance(request, WordDocumentRequest):
            if not isinstance(request, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                    "确定性格式审查快照请求格式无效。",
                )
            if "content" not in request:
                return self._create_incremental_session(request)
            if hasattr(WordDocumentRequest, "model_validate"):
                try:
                    request = WordDocumentRequest.model_validate(request)
                except ValidationError as exc:
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                        "确定性格式审查正文快照请求格式无效。",
                        status_code=422,
                    ) from exc
            else:
                try:
                    request = WordDocumentRequest.parse_obj(request)
                except ValidationError as exc:
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                        "确定性格式审查正文快照请求格式无效。",
                        status_code=422,
                    ) from exc
        return self._create_legacy_snapshot(request)

    def _create_legacy_snapshot(self, request: WordDocumentRequest) -> Dict:
        paragraphs = body_paragraphs(request)
        if len(paragraphs) > MAX_PARAGRAPHS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "确定性格式审查首版最多读取 200 个正文段落。",
                status_code=413,
            )
        review_text = "\n".join(paragraph.text for paragraph in paragraphs)
        if len(review_text) > MAX_REVIEW_CHARACTERS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "确定性格式审查首版最多读取 20,000 个审查字符。",
                status_code=413,
            )

        snapshot_id = "format-snapshot-" + uuid.uuid4().hex
        snapshot_token = secrets.token_urlsafe(24)
        request_data = _model_dump(request)
        content_sha256 = hashlib.sha256(review_text.encode("utf-8")).hexdigest()
        record = {
            "schemaVersion": FORMAT_SNAPSHOT_SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "snapshotTokenSha256": hashlib.sha256(snapshot_token.encode("utf-8")).hexdigest(),
            "createdAt": self._wall_clock(),
            "status": "staged",
            "legacy": True,
            "request": request_data,
            "contentSha256": content_sha256,
            "reviewCharacterCount": len(review_text),
            "paragraphCount": len(paragraphs),
        }
        path = self._snapshot_dir(snapshot_id)
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "确定性格式审查快照不得超过 512 KB。",
                status_code=413,
            )
        self._ensure_staging_root()
        try:
            path.mkdir(mode=0o700)
            self._write_private_json(path / "snapshot.json", record)
        except OSError as exc:
            shutil.rmtree(str(path), ignore_errors=True)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_WRITE_FAILED",
                "确定性格式审查快照暂存失败，请检查本地磁盘。",
                status_code=503,
            ) from exc

        with self._lock:
            self._snapshots[snapshot_id] = {"path": path, **record}
        return {
            "snapshotId": snapshot_id,
            "snapshotToken": snapshot_token,
            "status": "staged",
            "reviewCharacterCount": record["reviewCharacterCount"],
            "paragraphCount": record["paragraphCount"],
            "contentSha256": content_sha256,
        }

    def _create_incremental_session(self, payload: Dict) -> Dict:
        self._require_object(payload, {"documentId", "selectionMode"})
        document_id = self._required_string(payload, "documentId", 160).strip()
        selection_mode = str(payload.get("selectionMode") or "document").strip()
        if not document_id or selection_mode not in {"document", "selection"}:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_INVALID",
                "格式审查文档标识或范围无效。",
            )
        document_identity = self._normalize_identity(payload.get("documentIdentity"), document_id)
        snapshot_id = "format-snapshot-" + uuid.uuid4().hex
        upload_token = secrets.token_urlsafe(32)
        now = self._wall_clock()
        record = {
            "schemaVersion": FORMAT_SNAPSHOT_SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "snapshotTokenSha256": hashlib.sha256(upload_token.encode("utf-8")).hexdigest(),
            "createdAt": now,
            "expiresAt": now + SNAPSHOT_TTL_SECONDS,
            "status": "uploading",
            "legacy": False,
            "documentIdSha256": hashlib.sha256(document_id.encode("utf-8")).hexdigest(),
            "documentIdentity": document_identity,
            "selectionMode": selection_mode,
            "templateId": str(payload.get("templateId") or "technical-file-format-requirements"),
            "scope": self._normalize_scope(payload.get("scope"), selection_mode),
            "pageSetup": self._normalize_page_setup(payload.get("pageSetup")),
            "sourceCoverage": self._normalize_source_coverage(payload.get("coverage")),
            "editSequence": self._optional_scalar(payload.get("editSequence")),
            "batches": [],
            "imageGroups": [],
            "imageAssets": [],
            "snapshotBytes": 0,
            "reviewCharacterCount": 0,
            "blockCount": 0,
            "coverage": {"inScopeBlockCount": 0, "contextBlockCount": 0},
        }
        self._enforce_complexity(self._format_metrics([], record["sourceCoverage"]), 0)
        path = self._snapshot_dir(snapshot_id)
        self._ensure_staging_root()
        try:
            path.mkdir(mode=0o700)
            self._write_private_json(path / "snapshot.json", record)
        except OSError as exc:
            shutil.rmtree(str(path), ignore_errors=True)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_WRITE_FAILED",
                "确定性格式审查快照暂存失败，请检查本地磁盘。",
                status_code=503,
            ) from exc
        with self._lock:
            self._snapshots[snapshot_id] = {"path": path, **record}
        return {
            "snapshotId": snapshot_id,
            "sessionId": snapshot_id,
            "snapshotToken": upload_token,
            "uploadToken": upload_token,
            "status": "uploading",
            "selectionMode": selection_mode,
            "scope": deepcopy(record["scope"]),
            "stagingExpiresAt": record["expiresAt"],
            "maxReviewCharacters": 120000,
            "maxBatchBytes": MAX_FORMAT_BATCH_BYTES,
            "maxSnapshotBytes": MAX_FORMAT_SNAPSHOT_BYTES,
        }

    def upload_batch(self, snapshot_id: str, sequence: int, payload: Dict) -> Dict:
        with self._snapshot_mutation_lock:
            return self._upload_batch_unlocked(snapshot_id, sequence, payload)

    def _upload_batch_unlocked(self, snapshot_id: str, sequence: int, payload: Dict) -> Dict:
        self._require_enabled()
        if not SAFE_ID.fullmatch(str(snapshot_id or "")) or type(sequence) is not int or sequence < 0:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_SEQUENCE_INVALID",
                "格式快照批次序号无效。",
                status_code=409,
            )
        self._require_object(payload, {
            "uploadToken", "batchId", "blocks", "characterCount",
            "contentSha256", "structureSha256", "formatSha256",
        })
        record = self._load_snapshot(snapshot_id)
        if record.get("status") != "uploading" or record.get("legacy"):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_STATE_INVALID",
                "格式快照状态不允许上传批次。",
                status_code=409,
            )
        self._verify_token(record, payload.get("uploadToken"))
        batch_id = self._required_string(payload, "batchId", 96).strip()
        if not SAFE_ID.fullmatch(batch_id):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_INVALID",
                "格式快照批次编号无效。",
            )
        blocks = self._normalize_format_blocks(payload.get("blocks"))
        candidate_range = self._normalize_range(payload.get("range"))
        candidate_edit_sequence = self._optional_scalar(payload.get("editSequence"))
        batches = record.get("batches", [])
        if sequence < len(batches):
            existing = batches[sequence]
            if (
                existing.get("batchId") == batch_id
                and existing.get("blocks") == blocks
                and existing.get("range", {}) == candidate_range
                and existing.get("editSequence") == candidate_edit_sequence
                and all(
                    existing.get(key) == payload.get(key)
                    for key in ("contentSha256", "structureSha256", "formatSha256", "characterCount")
                )
            ):
                return self._batch_response(record, existing, idempotent=True)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_IDEMPOTENCY_CONFLICT",
                "同一格式审查批次编号不能绑定不同格式事实。",
                status_code=409,
            )
        if sequence != len(batches):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_SEQUENCE_INVALID",
                "格式审查快照批次序号必须连续上传。",
                status_code=409,
            )
        if sequence >= MAX_FORMAT_BATCHES:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                "格式审查批次数量超过安全上限，未保留部分快照。",
                status_code=413,
            )
        existing_block_ids = {
            block.get("blockId")
            for existing_batch in batches
            for block in existing_batch.get("blocks", [])
        }
        if existing_block_ids.intersection(block.get("blockId") for block in blocks):
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                "格式审查语义单元不能在多个批次中重复出现，已清理快照。",
                status_code=409,
            )
        if int(record.get("blockCount", 0)) + len(blocks) > MAX_FORMAT_BLOCKS:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                "格式审查语义单元数量超过安全上限，未保留部分快照。",
                status_code=413,
            )
        serialized = json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_FORMAT_BATCH_BYTES:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_TOO_LARGE",
                "格式审查单批次超过 2 MB 限制。",
                status_code=413,
            )
        metrics = self._format_metrics(blocks)
        for key in ("characterCount", "contentSha256", "structureSha256", "formatSha256"):
            if payload.get(key) != metrics[key]:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BATCH_HASH_MISMATCH",
                    "格式审查批次字符数、结构哈希或格式指纹校验失败。",
                    status_code=409,
                )
        total_characters = int(record.get("reviewCharacterCount", 0)) + metrics["characterCount"]
        all_blocks = [
            block
            for existing_batch in batches
            for block in existing_batch.get("blocks", [])
        ] + blocks
        all_metrics = self._format_metrics(all_blocks, record.get("sourceCoverage"))
        try:
            capacity = self.classify_capacity(all_metrics["characterCount"], raise_error=True)
            self._enforce_complexity(all_metrics, int(record.get("snapshotBytes", 0) or 0))
        except AdapterError:
            self._remove_snapshot(snapshot_id)
            raise
        batch = {
            "sequence": sequence,
            "batchId": batch_id,
            "blocks": blocks,
            "characterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "range": self._normalize_range(payload.get("range")),
            "editSequence": candidate_edit_sequence,
        }
        batch_edit_sequence = candidate_edit_sequence
        if record.get("editSequence") != batch_edit_sequence:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_CHANGED",
                "检测到格式抽取期间文档编辑状态变化，已清理快照。",
                status_code=409,
            )
        batch["editSequence"] = batch_edit_sequence
        batch_bytes = len(json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        snapshot_bytes = int(record.get("snapshotBytes", 0) or 0) + batch_bytes
        if snapshot_bytes > MAX_FORMAT_SNAPSHOT_BYTES:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                "格式审查快照累计字节数超过安全上限，未保留部分快照。",
                status_code=413,
            )
        record["batches"] = batches + [batch]
        record["reviewCharacterCount"] = total_characters
        record["blockCount"] = int(record.get("blockCount", 0)) + len(blocks)
        record["coverage"] = self._merge_coverage(record.get("coverage"), metrics["coverage"])
        record["capacityTier"] = capacity["tier"]
        record["snapshotBytes"] = snapshot_bytes
        record["expiresAt"] = self._wall_clock() + SNAPSHOT_TTL_SECONDS
        self._persist_snapshot_record(snapshot_id, record, batch)
        return self._batch_response(record, batch, idempotent=False)

    def commit_snapshot(self, snapshot_id: str, payload: Dict) -> Dict:
        with self._snapshot_mutation_lock:
            return self._commit_snapshot_unlocked(snapshot_id, payload)

    def _commit_snapshot_unlocked(self, snapshot_id: str, payload: Dict) -> Dict:
        self._require_enabled()
        if not SAFE_ID.fullmatch(str(snapshot_id or "")):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_NOT_FOUND",
                "确定性格式审查快照不存在或已过期。",
                status_code=404,
            )
        self._require_object(payload, {
            "uploadToken", "batchCount", "reviewCharacterCount",
            "contentSha256", "structureSha256", "formatSha256", "verification",
        })
        record = self._load_snapshot(snapshot_id)
        if record.get("status") != "uploading" or record.get("legacy"):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_STATE_INVALID",
                "格式审查快照状态不允许提交。",
                status_code=409,
            )
        self._verify_token(record, payload.get("uploadToken"))
        blocks = [block for batch in record.get("batches", []) for block in batch.get("blocks", [])]
        metrics = self._format_metrics(blocks, record.get("sourceCoverage"))
        if metrics["coverage"]["inScopeBlockCount"] == 0:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SCOPE_INVALID",
                "格式审查快照至少需要一个范围内语义单元，已清理快照。",
                status_code=409,
            )
        expected = {
            "batchCount": len(record.get("batches", [])),
            "blockCount": len(blocks),
            "reviewCharacterCount": metrics["characterCount"],
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
        }
        if any(payload.get(key) != value for key, value in expected.items()) or (
            "coverage" in payload and payload.get("coverage") != metrics["coverage"]
        ):
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_MISMATCH",
                "格式审查快照首遍指标不一致，已清理暂存数据，请停止编辑后重试。",
                status_code=409,
            )
        try:
            capacity = self.classify_capacity(metrics["characterCount"], raise_error=True)
            self._enforce_complexity(metrics, int(record.get("snapshotBytes", 0) or 0))
        except AdapterError:
            self._remove_snapshot(snapshot_id)
            raise
        verification = payload.get("verification")
        if not isinstance(verification, dict) or any(
            verification.get(key) != value for key, value in expected.items()
        ) or verification.get("coverage") != metrics["coverage"]:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_MISMATCH",
                "格式审查快照两遍结构、对象、覆盖或格式指纹不一致，已清理暂存数据。",
                status_code=409,
            )
        if verification.get("documentIdentity") != record.get("documentIdentity") or \
                verification.get("editSequence") != record.get("editSequence"):
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_CHANGED",
                "检测到文档身份或编辑状态变化，已安全中止格式审查并清理快照。",
                status_code=409,
            )
        request = self._request_from_blocks(record, blocks, metrics)
        record["status"] = "committed"
        record["committedAt"] = self._wall_clock()
        record["request"] = request
        record["contentSha256"] = metrics["contentSha256"]
        record["structureSha256"] = metrics["structureSha256"]
        record["formatSha256"] = metrics["formatSha256"]
        record["verification"] = {
            "status": "verified",
            "documentIdentity": deepcopy(record.get("documentIdentity")),
            "editSequence": record.get("editSequence"),
        }
        self._persist_snapshot_record(snapshot_id, record)
        return {
            "snapshotId": snapshot_id,
            "snapshotToken": payload.get("uploadToken"),
            "status": "committed",
            "selectionMode": record.get("selectionMode", "document"),
            "reviewCharacterCount": metrics["characterCount"],
            "blockCount": len(blocks),
            "coverage": deepcopy(metrics["coverage"]),
            "contentSha256": metrics["contentSha256"],
            "structureSha256": metrics["structureSha256"],
            "formatSha256": metrics["formatSha256"],
            "verificationStatus": "verified",
            "capacityTier": capacity["tier"],
            "complexity": deepcopy(metrics["complexity"]),
        }

    def allocate_image_group(self, snapshot_id: str, payload: Dict) -> Dict:
        with self._snapshot_mutation_lock:
            self._require_enabled()
            record = self._load_snapshot(snapshot_id)
            self._verify_token(record, payload.get("uploadToken") if isinstance(payload, dict) else None)
            if record.get("status") != "committed" or record.get("legacy"):
                raise AdapterError(
                    "IMAGE_ASSET_SNAPSHOT_STATE_INVALID",
                    "图片导出组只能绑定已验证的格式审查快照。",
                    status_code=409,
                )
            binding = self._image_document_binding(record, payload)
            if binding != {"documentIdentity": record.get("documentIdentity", {}), "editSequence": record.get("editSequence")}:
                raise AdapterError(
                    "IMAGE_EXPORT_DOCUMENT_CHANGED",
                    "检测到文档身份或编辑状态变化，已停止图片导出。",
                    status_code=409,
                )
            task_auth = self._snapshot_task_auth()
            policy = self.reviewer._image_semantic_policy(task_auth) if hasattr(self.reviewer, "_image_semantic_policy") else {"allowed": False, "reason": "image_semantics_disabled"}
            if not policy.get("allowed"):
                return {"snapshotId": snapshot_id, "status": "disabled", "reason": policy.get("reason", "image_semantics_disabled"), "groups": []}
            blocks = [block for batch in record.get("batches", []) for block in batch.get("blocks", [])]
            request = self._request_from_blocks(record, blocks, self._format_metrics(blocks, record.get("sourceCoverage")))
            candidates = self.reviewer._figure_caption_candidates(
                WordDocumentRequest.model_validate(request) if hasattr(WordDocumentRequest, "model_validate") else WordDocumentRequest.parse_obj(request)
            )
            existing_ids = {
                str(item.get("imageId"))
                for item in record.get("imageAssets", [])
                if isinstance(item, dict)
            }
            candidates = [item for item in candidates if item.get("imageId") not in existing_ids]
            try:
                remaining_calls = max(0, min(16, int(payload.get("remainingCalls", 16))))
            except (TypeError, ValueError):
                remaining_calls = 0
            groups = select_image_export_groups(candidates, remaining_calls)
            if not groups:
                return {"snapshotId": snapshot_id, "status": "no_candidates", "reason": "no_confirmed_missing_caption_group", "groups": []}
            selected = groups[0]
            allocated = self.image_asset_store.allocate_group(snapshot_id, selected, binding)
            record.setdefault("imageGroups", []).append({"groupId": allocated["groupId"], "status": "allocated"})
            try:
                self._persist_snapshot_record(snapshot_id, record)
            except Exception:
                self.image_asset_store.delete_group(allocated["groupId"])
                raise
            return {"snapshotId": snapshot_id, "status": "allocated", "policy": policy, "group": allocated}

    def commit_image_group(self, snapshot_id: str, group_id: str, payload: Dict) -> Dict:
        with self._snapshot_mutation_lock:
            self._require_enabled()
            record = self._load_snapshot(snapshot_id)
            self._verify_token(record, payload.get("uploadToken") if isinstance(payload, dict) else None)
            if record.get("status") != "committed" or record.get("legacy"):
                raise AdapterError(
                    "IMAGE_ASSET_SNAPSHOT_STATE_INVALID",
                    "图片导出组只能绑定已验证的格式审查快照。",
                    status_code=409,
                )
            binding = self._image_document_binding(record, payload)
            allocated_group = self.image_asset_store.get_group(group_id)
            if not allocated_group or allocated_group.get("snapshotId") != snapshot_id:
                raise AdapterError(
                    "IMAGE_ASSET_GROUP_NOT_FOUND",
                    "图片导出对象组不存在或与当前快照不匹配。",
                    status_code=404,
                )
            committed = self.image_asset_store.commit_group(group_id, binding)
            record["imageAssets"] = record.get("imageAssets", []) + deepcopy(committed.get("assets", []))
            for item in record.get("imageGroups", []):
                if isinstance(item, dict) and item.get("groupId") == group_id:
                    item["status"] = "committed"
            try:
                self._persist_snapshot_record(snapshot_id, record)
            except Exception:
                self.image_asset_store.delete_group(group_id)
                raise
            return {
                "snapshotId": snapshot_id,
                "groupId": group_id,
                "status": "committed",
                "assets": [
                    {key: value for key, value in asset.items() if key not in {"slotPath"}}
                    for asset in committed.get("assets", [])
                ],
            }

    def start_job(self, payload: dict, trace_id: str) -> Dict:
        self._require_enabled()
        if not isinstance(payload, dict):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_JOB_REQUEST_INVALID",
                "确定性格式审查任务请求格式无效。",
            )
        snapshot_id = str(payload.get("snapshotId") or "").strip()
        snapshot_token = payload.get("snapshotToken")
        if not SAFE_ID.fullmatch(snapshot_id) or not isinstance(snapshot_token, str):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照凭证无效或已过期。",
                status_code=403,
            )
        record = self._load_snapshot(snapshot_id)
        expected = record.get("snapshotTokenSha256", "")
        if not secrets.compare_digest(
            expected, hashlib.sha256(snapshot_token.encode("utf-8")).hexdigest()
        ):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照凭证无效或已过期。",
                status_code=403,
            )
        client_job_id = str(payload.get("clientJobId") or "").strip()
        job_id = client_job_id if SAFE_ID.fullmatch(client_job_id) else trace_id
        existing = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if existing is not None:
            self._remove_snapshot(snapshot_id)
            return existing
        if hasattr(WordDocumentRequest, "model_validate"):
            request = WordDocumentRequest.model_validate(record["request"])
        else:
            request = WordDocumentRequest.parse_obj(record["request"])
        snapshot_task_auth = getattr(self.reviewer, "snapshot_task_auth", None)
        task_auth = None
        if callable(snapshot_task_auth):
            try:
                task_auth = deepcopy(snapshot_task_auth())
            except Exception:
                task_auth = {"authSnapshotStatus": "unavailable"}
        image_assets = deepcopy(record.get("imageAssets", []))
        self._remove_snapshot(snapshot_id, cleanup_images=False)
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type=TASK_TYPE,
            runner=self._run,
            snapshot={
                "jobId": job_id,
                "traceId": trace_id,
                "request": request,
                "taskAuth": task_auth,
                "snapshotId": snapshot_id,
                "selectionMode": record.get("selectionMode", request.selection_mode),
                "contentSha256": record.get("contentSha256", ""),
                "structureSha256": record.get("structureSha256", ""),
                "formatSha256": record.get("formatSha256", ""),
                "committedAt": record.get("committedAt", self._wall_clock()),
                "reviewCharacterCount": record.get("reviewCharacterCount", 0),
                "sourceCoverage": deepcopy(record.get("sourceCoverage", {})),
                "imageAssets": image_assets,
            },
            failure_code="DETERMINISTIC_FORMAT_REVIEW_JOB_FAILED",
            failure_message="确定性格式审查后台任务执行失败，请稍后重试。",
            public_metadata={"runningMessage": "正在执行确定性格式审查。"},
            allow_running_cancel=True,
        )

    def get_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        if not SAFE_ID.fullmatch(str(job_id or "")):
            return None
        job = self.coordinator.get(job_id, task_type=TASK_TYPE)
        if job is None:
            return None
        if job.get("status") == "completed":
            report = self._get_report(job_id)
            job["reportAvailable"] = isinstance(report, dict)
            if isinstance(report, dict):
                job["issueCount"] = report.get("issueCount", 0)
                job["duplicateGroupCount"] = report.get("duplicateGroupCount", 0)
                job["summary"] = deepcopy(report.get("summary", {}))
                job["coverage"] = deepcopy(report.get("coverage", {}))
        return job

    def cancel_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        job = self.coordinator.request_cancel(job_id, task_type=TASK_TYPE)
        if job is None:
            return None
        if job.get("status") == "cancelled":
            job["result"] = None
            job["reportAvailable"] = False
            job["cancelledSummary"] = {
                "executionStatus": "cancelled",
                "complianceStatus": "not_assessable",
                "coverageStatus": "not_available",
                "semanticStatus": "not_run",
                "issueCount": 0,
                "issuesRetained": False,
            }
        return job

    def get_report(self, job_id: str) -> Dict:
        report = self._require_report(job_id)
        return self._public_report(report)

    def list_issues(
        self,
        job_id: str,
        page_size: Optional[int] = None,
        cursor: str = "",
        rule_id: str = "",
        severity: str = "",
        data_status: str = "",
        status: str = "",
        duplicate_group_id: str = "",
        sort: str = "source",
    ) -> Dict:
        report = self._require_report(job_id)
        size = DEFAULT_ISSUE_PAGE_SIZE if page_size is None else page_size
        if type(size) is not int or not 0 < size <= MAX_ISSUE_PAGE_SIZE:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_PAGE_SIZE_INVALID",
                "问题分页大小必须是 1 到 100 之间的整数。",
            )
        if severity and severity not in {"info", "warning", "error"}:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_FILTER_INVALID",
                "问题严重程度筛选值无效。",
            )
        if status and status not in FORMAT_ISSUE_STATUSES:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_STATUS_INVALID",
                "问题处理状态无效。",
            )
        if data_status and data_status not in {"verified", "insufficient", "not_assessable"}:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_FILTER_INVALID",
                "问题数据状态筛选值无效。",
            )
        if sort not in {"source", "severity", "rule"}:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_SORT_INVALID",
                "问题排序方式无效。",
            )
        if not isinstance(cursor, str) or len(cursor) > 256:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        issues = []
        for index, issue in enumerate(report.get("issues", [])):
            item = deepcopy(issue)
            item.setdefault("status", "open")
            item["_sourceOrder"] = index
            if rule_id and item.get("ruleId") != rule_id:
                continue
            if severity and item.get("severity") != severity:
                continue
            if data_status and item.get("dataStatus") != data_status:
                continue
            if status and item.get("status") != status:
                continue
            if duplicate_group_id and item.get("duplicateGroupId") != duplicate_group_id:
                continue
            issues.append(item)
        if sort == "severity":
            issues.sort(key=lambda item: (
                FORMAT_SEVERITY_ORDER.get(item.get("severity"), 99),
                item.get("_sourceOrder", 0), item.get("issueId", ""),
            ))
        elif sort == "rule":
            issues.sort(key=lambda item: (
                item.get("ruleId", ""), item.get("_sourceOrder", 0), item.get("issueId", ""),
            ))
        else:
            issues.sort(key=lambda item: (item.get("_sourceOrder", 0), item.get("issueId", "")))
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
                    "DETERMINISTIC_FORMAT_REVIEW_ISSUES_CURSOR_INVALID",
                    "问题分页游标已失效，请从第一页重新读取。",
                )
            offset = matching_index + 1
        selected = issues[offset:offset + size]
        for item in selected:
            item.pop("_sourceOrder", None)
        next_cursor = ""
        if offset + size < len(issues) and selected:
            next_cursor = self._encode_issue_cursor(selected[-1]["issueId"])
        group_ids = {item.get("duplicateGroupId") for item in issues if item.get("duplicateGroupId")}
        groups = [
            {
                "duplicateGroupId": group_id,
                "issueIds": [item.get("issueId", "") for item in report.get("issues", [])
                             if item.get("duplicateGroupId") == group_id],
                "count": sum(1 for item in report.get("issues", []) if item.get("duplicateGroupId") == group_id),
            }
            for group_id in sorted(group_ids)
            if sum(1 for item in report.get("issues", []) if item.get("duplicateGroupId") == group_id) > 1
        ]
        return {
            "items": _sanitize_export_value(selected),
            "total": len(issues),
            "pageSize": size,
            "page": (offset // size) + 1,
            "nextCursor": next_cursor,
            "hasMore": bool(next_cursor),
            "duplicateGroups": groups,
            "filters": {
                "ruleId": rule_id,
                "severity": severity,
                "dataStatus": data_status,
                "status": status,
                "duplicateGroupId": duplicate_group_id,
            },
            "sort": sort,
        }

    def update_issue(
        self,
        job_id: str,
        issue_id: str,
        status: Optional[str] = None,
        anchor_verification: Optional[str] = None,
    ) -> Dict:
        report = self._require_report(job_id)
        if status is not None and status not in FORMAT_ISSUE_STATUSES:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUE_STATUS_INVALID",
                "问题处理状态无效。",
            )
        if anchor_verification is not None and anchor_verification not in FORMAT_ANCHOR_VERIFICATIONS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ANCHOR_VERIFICATION_INVALID",
                "格式问题锚点验证状态无效。",
            )
        for issue in report.get("issues", []):
            if issue.get("issueId") != issue_id:
                continue
            if status is not None:
                issue["status"] = status
            if anchor_verification is not None:
                issue["anchorVerification"] = anchor_verification
                source_anchor = issue.setdefault("sourceAnchor", {})
                source_anchor["verification"] = anchor_verification
            self._refresh_report_counts(report)
            self._save_report(job_id, report)
            return _sanitize_export_value(issue)
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_ISSUE_NOT_FOUND",
            "格式问题不存在或报告已过期。",
            status_code=404,
        )

    def export_report(self, job_id: str, output_format: str) -> object:
        report = _sanitize_export_value(self._require_report(job_id))
        if output_format == "json":
            report.pop("reportExpiresAt", None)
            report.pop("reportSha256", None)
            report["exportSchemaVersion"] = FORMAT_REPORT_EXPORT_SCHEMA_VERSION
            return report
        if output_format != "markdown":
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_REPORT_FORMAT_INVALID",
                "格式审查报告仅支持 json 或 markdown 格式。",
            )
        summary = report.get("summary", {})
        attempted = "已尝试" if summary.get("aiAttempted") else "未尝试"
        candidate_count = int(summary.get("aiCandidateCount", 0) or 0)
        call_count = int(summary.get("aiCallCount", 0) or 0)
        accepted_count = int(summary.get("aiAcceptedCount", 0) or 0)
        reason_text = _report_semantic_reason(summary.get("aiFallbackReason"))
        model_lines = [
            "- 模型配置：{0}".format(summary.get("modelConfigurationName") or "未记录"),
            "- 配置 ID：{0}".format(summary.get("modelConfigurationId") or "未记录"),
            "- 配置修订：{0}".format(summary.get("modelConfigurationVersion") or "未记录"),
            "- 接入方式：{0}".format(_report_model_access_method(summary.get("accessMethod"))),
            "- 模型调用事实：{0}，候选 {1}、调用 {2}、接受 {3}".format(
                attempted, candidate_count, call_count, accepted_count
            ),
        ]
        if reason_text:
            model_lines.append("- 语义增强降级原因：{0}".format(reason_text))
        lines = [
            "# 格式审查报告", "", "导出版本：{0}".format(FORMAT_REPORT_EXPORT_SCHEMA_VERSION),
            "", "## 四维状态",
            "- 执行状态：{0}".format(summary.get("executionStatus", "")),
            "- 合规状态：{0}".format(summary.get("complianceStatus", "")),
            "- 覆盖状态：{0}".format(summary.get("coverageStatus", "")),
            "- 语义增强状态：{0}".format(summary.get("semanticStatus", "")),
            "", "## 模型调用诊断",
            *model_lines,
            "", "## 统计",
            "- 问题数量：{0}".format(report.get("issueCount", 0)),
            "- 重复问题组：{0}".format(report.get("duplicateGroupCount", 0)),
            "- 审查字符：{0}".format(report.get("coverage", {}).get("reviewCharacterCount", 0)),
            "", report.get("disclaimer", ""), "",
        ]
        for index, issue in enumerate(report.get("issues", []), 1):
            lines.extend([
                "## {0}. {1}".format(index, issue.get("message", "格式问题")),
                "- 问题编号：{0}".format(issue.get("issueId", "")),
                "- 规则：{0}".format(issue.get("ruleId", "")),
                "- 位置：{0}".format(_report_issue_position(issue)),
                "- 角色：{0}".format(_report_issue_role(issue)),
                "- 锚点：{0}".format(issue.get("anchorId", "")),
                "- 属性路径：{0}".format(issue.get("propertyPath", "")),
                "- 当前值：{0}".format(issue.get("currentValue", "")),
                "- 期望值：{0}".format(issue.get("expectedValue", "")),
                "- 证据：{0}".format(json.dumps(issue.get("evidence", []), ensure_ascii=False)),
                "- 规则版本：{0}".format(issue.get("ruleVersion", "")),
                "- 状态：{0}".format(issue.get("status", "open")),
                "- 锚点验证：{0}".format(issue.get("anchorVerification", "unverified")),
                "- 建议：{0}".format(issue.get("suggestion", "")), "",
            ])
            if issue.get("ruleId") == "structure.heading_hierarchy":
                lines.insert(
                    len(lines) - 1,
                    "- 当前标题级别：{0}".format(issue.get("currentLevel", issue.get("currentValue", ""))),
                )
                lines.insert(
                    len(lines) - 1,
                    "- 前一有效标题级别：{0}".format(
                        issue.get("previousLevel") if issue.get("previousLevel") is not None else "无"
                    ),
                )
        return "\n".join(lines)

    def delete_report(self, job_id: str) -> Dict:
        self._require_report(job_id)
        with self._lock:
            self._reports.pop(job_id, None)
        try:
            self.report_path(job_id).unlink(missing_ok=True)
        except OSError:
            pass
        return {"jobId": job_id, "status": "deleted"}

    def delete_snapshot(self, snapshot_id: str, payload: dict) -> Dict:
        with self._snapshot_mutation_lock:
            return self._delete_snapshot_unlocked(snapshot_id, payload)

    def _delete_snapshot_unlocked(self, snapshot_id: str, payload: dict) -> Dict:
        self._require_enabled()
        if not SAFE_ID.fullmatch(str(snapshot_id or "")):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_NOT_FOUND",
                "确定性格式审查快照不存在或已过期。",
                status_code=404,
            )
        record = self._load_snapshot(snapshot_id)
        token = payload.get("snapshotToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not secrets.compare_digest(
            record.get("snapshotTokenSha256", ""),
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        ):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照凭证无效或已过期。",
                status_code=403,
            )
        self._remove_snapshot(snapshot_id)
        return {"snapshotId": snapshot_id, "status": "deleted"}

    def _run(self, snapshot: Dict, progress) -> Dict:
        progress("extracting")
        request = snapshot["request"]
        try:
            if self.coordinator.is_cancel_requested(snapshot.get("jobId", ""), TASK_TYPE):
                raise LongTaskCancelled()
            review_kwargs = {"trace_id": snapshot.get("traceId", "") or ""}
            try:
                review_parameters = inspect.signature(self.reviewer.review).parameters
            except (TypeError, ValueError):
                review_parameters = {}
            if "semantic_state" in review_parameters:
                review_kwargs.update({
                    "semantic_state": snapshot.setdefault("semanticState", {}),
                    "max_semantic_batches": 1,
                })
            if snapshot.get("taskAuth") is not None:
                review_kwargs["task_auth"] = snapshot["taskAuth"]
            if "image_assets" in review_parameters:
                review_kwargs["image_assets"] = deepcopy(snapshot.get("imageAssets", []))
            if "image_asset_cleanup" in review_parameters:
                review_kwargs["image_asset_cleanup"] = self.image_asset_store.delete_group
            result = self.reviewer.review(request, **review_kwargs)
            if self.coordinator.is_cancel_requested(snapshot.get("jobId", ""), TASK_TYPE):
                raise LongTaskCancelled()
            if isinstance(result, dict) and result.get("_semanticComplete") is False:
                snapshot["semanticState"] = deepcopy(result.get("_semanticState", {}))
                progress("provider_processing")
                return LongTaskContinuation(snapshot, phase="provider_processing")
            report = self._build_report(result, snapshot)
            self._save_report(snapshot["jobId"], report)
            summary = report["summary"]
            return {
                "summary": deepcopy(summary),
                "issueCount": report.get("issueCount", 0),
                "duplicateGroupCount": report.get("duplicateGroupCount", 0),
                "coverage": deepcopy(report.get("coverage", {})),
                "reportAvailable": True,
            }
        finally:
            self._remove_snapshot(snapshot.get("snapshotId", ""))
            self.image_asset_store.cleanup_snapshot(snapshot.get("snapshotId", ""))

    def _build_report(self, result: Dict, snapshot: Dict) -> Dict:
        result = result if isinstance(result, dict) else {}
        request = snapshot["request"]
        summary = deepcopy(result.get("summary", {}))
        model_identity = build_format_review_model_identity(snapshot.get("taskAuth"))
        if any(
            model_identity.get(key)
            for key in ("modelConfigurationName", "modelConfigurationId", "modelConfigurationVersion", "accessMethod")
        ):
            summary.update(model_identity)
        structure = request.content.document_structure or {}
        coverage = deepcopy(structure.get("coverage", {}) or {})
        if not coverage:
            coverage = deepcopy(snapshot.get("sourceCoverage", {}) or {})
        header_footer = coverage.get("headerFooter", {})
        coverage_status = "partial" if (
            coverage.get("formatDataStatus") in {"insufficient", "partial"}
            or int(coverage.get("unsupportedObjectCount", 0) or 0) > 0
            or int(coverage.get("formatDataInsufficientBlockCount", 0) or 0) > 0
            or any(
                isinstance(item, dict) and item.get("status") == "unavailable"
                for item in header_footer.values()
            )
        ) else "complete"
        issues = []
        seen_heading_issues = set()
        for issue in result.get("issues", []):
            if not isinstance(issue, dict):
                continue
            if issue.get("ruleId") == "structure.heading_hierarchy":
                paragraph_index = issue.get("paragraphIndex")
                heading_key = (
                    (paragraph_index, issue.get("currentLevel", issue.get("currentValue")))
                    if paragraph_index is not None
                    else (
                        paragraph_index,
                        issue.get("currentLevel", issue.get("currentValue")),
                        issue.get("previousLevel"),
                        issue.get("message", ""),
                    )
                )
                if heading_key in seen_heading_issues:
                    continue
                seen_heading_issues.add(heading_key)
            issues.append(self._enrich_issue(issue, request, snapshot, coverage_status))
        groups = {}
        for issue in issues:
            groups.setdefault(issue["duplicateGroupId"], []).append(issue)
        duplicate_groups = []
        for group_id, members in sorted(groups.items()):
            for issue in members:
                issue["duplicateGroupSize"] = len(members)
            if len(members) > 1:
                duplicate_groups.append({
                    "duplicateGroupId": group_id,
                    "issueIds": [item["issueId"] for item in members],
                    "count": len(members),
                })
        semantic_status = str(summary.get("semanticStatus") or "not_needed")
        unresolved_semantic_roles = any(
            issue.get("ruleId") == "structure.role_confirmation"
            for issue in issues
        )
        summary.update({
            "executionStatus": "completed",
            "complianceStatus": (
                "not_assessable" if coverage_status != "complete"
                or unresolved_semantic_roles
                else ("violations_found" if issues else "passed")
            ),
            "coverageStatus": coverage_status,
            "semanticStatus": semantic_status,
            "readOnly": True,
            "issueCount": len(issues),
            "zeroIssuesNotSufficient": coverage_status != "complete" or unresolved_semantic_roles or semantic_status in {"partial", "not_ready", "degraded"},
        })
        if structure.get("formatSnapshotSchemaVersion") == FORMAT_SNAPSHOT_SCHEMA_VERSION:
            summary.update({
                "snapshotVerification": "two_pass_verified",
                "snapshotContentSha256": snapshot.get("contentSha256", ""),
                "snapshotStructureSha256": snapshot.get("structureSha256", ""),
                "snapshotFormatSha256": snapshot.get("formatSha256", ""),
                "scope": snapshot.get("selectionMode", "document"),
                "capacityTier": self.classify_capacity(snapshot.get("reviewCharacterCount", 0))["tier"],
                "complexity": deepcopy(self._format_metrics(
                    structure.get("formatBlocks", []), snapshot.get("sourceCoverage")
                ).get("complexity", {})),
            })
        report = {
            "schemaVersion": FORMAT_REPORT_SCHEMA_VERSION,
            "reviewMode": "deterministic",
            "snapshot": {
                "snapshotId": snapshot.get("snapshotId", ""),
                "contentSha256": snapshot.get("contentSha256", ""),
                "structureSha256": snapshot.get("structureSha256", ""),
                "formatSha256": snapshot.get("formatSha256", ""),
                "committedAt": snapshot.get("committedAt", self._wall_clock()),
            },
            "summary": summary,
            "coverage": coverage,
            "issues": issues,
            "issueCount": len(issues),
            "duplicateGroups": duplicate_groups,
            "duplicateGroupCount": len(duplicate_groups),
            "disclaimer": "覆盖完整仅表示声明范围未被静默截断，不承诺检出全部格式问题。",
        }
        self._refresh_report_counts(report)
        return report

    def _enrich_issue(
        self, issue: Dict, request: WordDocumentRequest, snapshot: Dict, coverage_status: str
    ) -> Dict:
        allowed_fields = {
            "ruleId", "category", "severity", "paragraphIndex", "role", "source",
            "currentLevel", "previousLevel",
            "templateHash", "ruleVersion", "rulePackSha256", "message", "currentValue",
            "expectedValue", "suggestion", "unit", "tolerance", "evidence", "dataStatus",
            "status",
        }
        item = {key: deepcopy(value) for key, value in issue.items() if key in allowed_fields}
        rule_id = str(item.get("ruleId") or "unknown")
        paragraph_index = normalize_paragraph_index(item.get("paragraphIndex"))
        blocks = (request.content.document_structure or {}).get("formatBlocks", []) or []
        block = next(
            (candidate for candidate in blocks
             if isinstance(candidate, dict) and paragraph_index is not None
             and int(candidate.get("paragraphIndex", 0) or 0) == paragraph_index),
            None,
        )
        block_index = blocks.index(block) if block in blocks else -1
        block_text = str((block or {}).get("text", ""))
        anchor_id = str((block or {}).get("blockId") or "structure:{0}".format(rule_id))
        anchor_verification = "verified" if block is not None and block_text else "unverified"
        property_path = FORMAT_RULE_PROPERTY_PATHS.get(rule_id, "format.{0}".format(rule_id))
        current_value = item.get("currentValue", "")
        expected_value = item.get("expectedValue", "")
        range_data = deepcopy((block or {}).get("range", {}))
        neighbor_ids = [
            str(candidate.get("blockId", ""))
            for candidate in blocks[max(0, block_index - 1):block_index + 2]
            if isinstance(candidate, dict) and candidate.get("blockId")
        ]
        adjacent_hash = hashlib.sha256(
            json.dumps(neighbor_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source_anchor = {
            "anchorId": anchor_id,
            "blockId": anchor_id,
            "location": "table" if (block or {}).get("blockType") == "table" else "body",
            "paragraphIndex": paragraph_index,
            "range": range_data,
            "textSha256": hashlib.sha256(block_text.encode("utf-8")).hexdigest(),
            "text": block_text[:240],
            "adjacentBlockIds": neighbor_ids,
            "adjacentStructureSha256": adjacent_hash,
            "verification": anchor_verification,
        }
        if rule_id == "structure.heading_hierarchy":
            hierarchy_anchor = build_format_issue_anchor(request, paragraph_index)
            anchor_id = hierarchy_anchor["anchorId"]
            source_anchor = hierarchy_anchor["sourceAnchor"]
            anchor_verification = hierarchy_anchor["anchorVerification"]
        semantic_identity = {
            "snapshot": snapshot.get("contentSha256", ""),
            "ruleId": rule_id,
            "anchorId": anchor_id,
            "propertyPath": property_path,
            "currentValue": current_value,
            "expectedValue": expected_value,
        }
        issue_id = "format-issue-" + hashlib.sha256(
            json.dumps(semantic_identity, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        group_identity = {
            "ruleId": rule_id,
            "propertyPath": property_path,
            "currentValue": current_value,
            "expectedValue": expected_value,
        }
        duplicate_group_id = "format-group-" + hashlib.sha256(
            json.dumps(group_identity, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            evidence = [{
                "kind": "deterministic_format_fact",
                "propertyPath": property_path,
                "currentValue": str(current_value)[:400],
                "expectedValue": str(expected_value)[:400],
                "anchorId": anchor_id,
            }]
        item.update({
            "issueId": issue_id,
            "ruleId": rule_id,
            "category": item.get("category") or "format",
            "severity": item.get("severity") or "warning",
            "paragraphIndex": paragraph_index,
            "anchorId": anchor_id,
            "sourceAnchor": source_anchor,
            "propertyPath": property_path,
            "unit": item.get("unit") or FORMAT_RULE_UNITS.get(rule_id, ""),
            "evidence": evidence,
            "dataStatus": item.get("dataStatus") or ("verified" if coverage_status == "complete" else "insufficient"),
            "duplicateGroupId": duplicate_group_id,
            "duplicateGroupSize": 1,
            "anchorVerification": anchor_verification,
            "status": item.get("status") or "open",
            "ruleVersion": item.get("ruleVersion") or "",
            "currentValue": _short_report_value(current_value),
            "expectedValue": _short_report_value(expected_value),
            "message": _short_report_value(item.get("message", "格式问题"), 800),
            "suggestion": _short_report_value(item.get("suggestion", ""), 1000),
        })
        return _sanitize_export_value(item)

    @staticmethod
    def _refresh_report_counts(report: Dict) -> None:
        issues = report.get("issues", [])
        report["issueCount"] = len(issues)
        report["severityCounts"] = {
            severity: sum(1 for issue in issues if issue.get("severity") == severity)
            for severity in ("error", "warning", "info")
        }
        report["statusCounts"] = {
            status: sum(1 for issue in issues if issue.get("status", "open") == status)
            for status in ("open", "processed", "ignored")
        }
        group_sizes = {}
        for issue in issues:
            group_id = issue.get("duplicateGroupId")
            if group_id:
                group_sizes[group_id] = group_sizes.get(group_id, 0) + 1
        report["duplicateGroupCount"] = sum(1 for count in group_sizes.values() if count > 1)

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
                "DETERMINISTIC_FORMAT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        if not SAFE_ID.fullmatch(issue_id):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_ISSUES_CURSOR_INVALID",
                "问题分页游标无效。",
            )
        return issue_id

    def _require_report(self, job_id: str) -> Dict:
        self._require_enabled()
        report = self._get_report(job_id)
        if not isinstance(report, dict):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_REPORT_NOT_FOUND",
                "格式审查报告不存在或已过期。",
                status_code=404,
            )
        return report

    def _save_report(self, job_id: str, report: Dict) -> None:
        stored = deepcopy(report)
        stored["reportExpiresAt"] = report.get(
            "reportExpiresAt", self._wall_clock() + REPORT_RESULT_TTL_SECONDS
        )
        stored["reportSha256"] = _report_sha256(stored)
        self._ensure_staging_root()
        with self._lock:
            self._reports[job_id] = stored
        self._write_private_json(self.report_path(job_id), stored)

    def _get_report(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            report = self._reports.get(job_id)
        path = self.report_path(job_id)
        if not isinstance(report, dict) and path.exists():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                report = None
        if not isinstance(report, dict):
            return None
        if report.get("reportSha256") != _report_sha256(report) or self._wall_clock() >= float(report.get("reportExpiresAt", 0) or 0):
            with self._lock:
                self._reports.pop(job_id, None)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        with self._lock:
            self._reports[job_id] = report
        return deepcopy(report)

    @staticmethod
    def _public_report(report: Dict) -> Dict:
        public = _sanitize_export_value(report)
        public.pop("issues", None)
        public.pop("reportExpiresAt", None)
        public.pop("reportSha256", None)
        public["issuesEndpoint"] = "issues"
        return public

    def _require_enabled(self) -> None:
        if not deterministic_format_review_enabled():
            raise _disabled_error()
        self._cleanup_expired()

    def _ensure_staging_root(self) -> None:
        try:
            self.staging_root.mkdir(parents=True, exist_ok=True)
            os.chmod(str(self.staging_root), 0o700)
        except OSError as exc:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_STORAGE_UNAVAILABLE",
                "确定性格式审查暂存目录不可用。",
                status_code=503,
            ) from exc

    def snapshot_path(self, snapshot_id: str) -> Path:
        return self._snapshot_dir(snapshot_id)

    def report_path(self, job_id: str) -> Path:
        if not SAFE_ID.fullmatch(str(job_id or "")):
            return self.staging_root / "report-invalid.json"
        return self.staging_root / "report-{0}.json".format(job_id)

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        if not SAFE_ID.fullmatch(str(snapshot_id or "")):
            return self.staging_root / "invalid-snapshot"
        return self.staging_root / str(snapshot_id)

    @staticmethod
    def _write_private_json(path: Path, value: Dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=".format-review-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(path))
            os.chmod(str(path), 0o600)
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    def _persist_snapshot_record(
        self, snapshot_id: str, record: Dict, batch: Optional[Dict] = None
    ) -> None:
        path = self._snapshot_dir(snapshot_id)
        persisted_record = deepcopy(record)
        persisted_record.pop("path", None)
        self._ensure_staging_root()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(str(path), 0o700)
        if batch is not None:
            self._write_private_json(
                path / "batch-{0}.json".format(int(batch["sequence"])), batch
            )
        self._write_private_json(path / "snapshot.json", persisted_record)
        with self._lock:
            self._snapshots[snapshot_id] = {"path": path, **persisted_record}

    @staticmethod
    def _required_string(payload: Dict, key: str, max_length: int) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value or len(value) > max_length:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照字段无效。",
            )
        return value

    @staticmethod
    def _optional_scalar(value: object) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        raise AdapterError(
            "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_INVALID",
            "文档编辑状态标识格式无效。",
        )

    @staticmethod
    def _require_object(payload: object, required: set) -> None:
        if not isinstance(payload, dict) or not required.issubset(set(payload)):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照请求缺少必要字段。",
            )

    @staticmethod
    def _normalize_identity(value: object, document_id: str) -> Dict:
        if value is None:
            return {"documentIdSha256": hashlib.sha256(document_id.encode("utf-8")).hexdigest()}
        if not isinstance(value, dict) or set(value) - {"documentIdSha256", "documentId", "hostDocumentId"}:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_DOCUMENT_INVALID",
                "文档身份快照格式无效。",
            )
        normalized = {
            key: str(value[key])
            for key in ("documentIdSha256", "documentId", "hostDocumentId")
            if key in value and value[key] is not None
        }
        if not normalized:
            normalized["documentIdSha256"] = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        return normalized

    @staticmethod
    def _normalize_scope(value: object, selection_mode: str) -> Dict:
        if value is None:
            return {
                "mode": selection_mode,
                "expandedToSemanticUnits": selection_mode == "selection",
                "contextOnly": [],
            }
        if not isinstance(value, dict) or set(value) - {
            "mode", "expandedToSemanticUnits", "selectedTextSha256", "contextOnly"
        }:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SCOPE_INVALID",
                "格式审查范围扩展信息格式无效。",
            )
        normalized = {
            "mode": str(value.get("mode") or selection_mode),
            "expandedToSemanticUnits": bool(value.get("expandedToSemanticUnits")),
            "contextOnly": list(value.get("contextOnly") or []),
        }
        if "selectedTextSha256" in value:
            normalized["selectedTextSha256"] = str(value["selectedTextSha256"])
        if normalized["mode"] != selection_mode or not isinstance(normalized["contextOnly"], list):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SCOPE_INVALID",
                "格式审查范围模式与文档请求不一致。",
            )
        return normalized

    @staticmethod
    def _normalize_range(value: object) -> Dict:
        if value is None:
            return {}
        if not isinstance(value, dict) or set(value) - {
            "start", "end", "area", "paragraphIndex", "tableId", "cellId"
        }:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_RANGE_INVALID",
                "格式审查原文范围格式无效。",
            )
        normalized = {}
        for key, item in value.items():
            if key in {"start", "end", "paragraphIndex"}:
                if type(item) is not int or item < 0:
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_RANGE_INVALID",
                        "格式审查原文范围索引无效。",
                    )
                normalized[key] = item
            elif not isinstance(item, str) or len(item) > 160:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_RANGE_INVALID",
                    "格式审查原文范围标识无效。",
                )
            else:
                normalized[key] = item
        if "start" in normalized and "end" in normalized and normalized["end"] < normalized["start"]:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_RANGE_INVALID",
                "格式审查原文范围顺序无效。",
            )
        return normalized

    @classmethod
    def _normalize_format_blocks(cls, value: object) -> List[Dict]:
        if not isinstance(value, list) or not value or len(value) > MAX_FORMAT_BLOCKS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BATCH_INVALID",
                "格式审查批次必须包含有限的语义单元。",
            )
        normalized = []
        seen = set()
        for item in value:
            if not isinstance(item, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查语义单元格式无效。",
                )
            block_id = item.get("blockId")
            block_type = item.get("blockType")
            if not isinstance(block_id, str) or not SAFE_ID.fullmatch(block_id) or block_id in seen:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查语义单元标识必须安全且唯一。",
                )
            if block_type not in FORMAT_BLOCK_TYPES:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查语义单元类型不受支持。",
                )
            scope = item.get("scope", "in_scope")
            if scope not in FORMAT_SCOPES:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_SCOPE_INVALID",
                    "格式审查语义单元范围标识无效。",
                )
            text = item.get("text", "")
            if not isinstance(text, str) or len(text) > 120000:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查语义单元文本无效。",
                )
            normalized_item = {
                "blockId": block_id,
                "blockType": block_type,
                "scope": scope,
                "text": text,
                "paragraphIndex": int(item.get("paragraphIndex", 0) or 0),
                "range": cls._normalize_range(item.get("range", item.get("sourceRange"))),
                "format": cls._normalize_format_facts(item.get("format", item)),
            }
            for key in ("headingLevel", "listLabel", "tableId", "tableIndex", "captionFor"):
                if key in item:
                    normalized_item[key] = item[key]
            if "unsupportedObjects" in item:
                normalized_item["unsupportedObjects"] = cls._normalize_source_coverage({
                    "unsupportedObjects": item.get("unsupportedObjects")
                }).get("unsupportedObjects", [])
            if "images" in item:
                normalized_item["images"] = cls._normalize_image_facts(item.get("images"))
            if block_type == "image":
                normalized_item["image"] = cls._normalize_image_facts([item])[0]
            if block_type == "table":
                normalized_item["rows"] = cls._normalize_table_rows(item.get("rows", []))
                normalized_item["nestedTables"] = item.get("nestedTables", []) if isinstance(item.get("nestedTables", []), list) else []
            has_outline_fact = (
                "headingLevel" in item
                or "outlineLevel" in item
                or "outlineLevel" in normalized_item["format"]
            )
            if has_outline_fact:
                raw_level = item.get(
                    "headingLevel",
                    item.get("outlineLevel", normalized_item["format"].get("outlineLevel")),
                )
                outline_level = normalize_outline_level(raw_level)
                normalized_item["outlineLevel"] = outline_level
                normalized_item["format"]["outlineLevel"] = outline_level
                if block_type == "heading":
                    if outline_level == 0:
                        normalized_item["blockType"] = "paragraph"
                        normalized_item.pop("headingLevel", None)
                    elif outline_level is None:
                        normalized_item["blockType"] = "unknown"
                        normalized_item.pop("headingLevel", None)
                    else:
                        normalized_item["headingLevel"] = outline_level
            seen.add(block_id)
            normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _normalize_image_facts(value: object) -> List[Dict]:
        if not isinstance(value, list) or len(value) > 64:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                "格式审查图片对象数量无效。",
            )
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查图片对象格式无效。",
                )
            image_id = str(item.get("imageId") or item.get("pictureId") or item.get("objectId") or "").strip()
            if not image_id or len(image_id) > 160:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式审查图片对象标识无效。",
                )
            nearby = item.get("nearbyText", item.get("contextText", item.get("adjacentText", "")))
            if isinstance(nearby, list):
                nearby = " ".join(str(part) for part in nearby)
            normalized.append({
                "imageId": image_id,
                "groupId": str(item.get("groupId") or item.get("imageGroupId") or image_id)[:160],
                "fingerprint": str(item.get("fingerprint") or item.get("objectFingerprint") or "")[:256],
                "captionStatus": str(item.get("captionStatus") or item.get("figureCaptionStatus") or "unknown")[:32],
                "associationStatus": str(item.get("associationStatus") or "missing")[:32],
                "supported": item.get("supported", item.get("supportedType", True)) is not False,
                "altText": str(item.get("altText") or item.get("alternativeText") or "")[:2000],
                "nearbyText": str(nearby or "")[:4000],
            })
        return normalized

    @staticmethod
    def _normalize_format_facts(value: object) -> Dict:
        if not isinstance(value, dict):
            return {}
        allowed = {
            "styleName", "fontName", "fontSize", "bold", "italic", "underline",
            "strikeThrough", "superscript", "subscript", "allCaps", "smallCaps",
            "color", "highlight", "characterSpacing", "characterScale", "alignment",
            "lineSpacing", "firstLineIndent", "spaceBefore", "spaceAfter", "leftIndent",
            "rightIndent", "outlineLevel", "segments", "dataStatus"
        }
        normalized = {
            key: deepcopy(value[key])
            for key in allowed
            if key in value
        }
        if "segments" in normalized:
            normalized["segments"] = DeterministicFormatReviewService._normalize_format_segments(
                normalized["segments"]
            )
        if "dataStatus" in normalized and normalized["dataStatus"] not in {
            "verified", "insufficient", "context_only"
        }:
            normalized["dataStatus"] = "insufficient"
        if normalized.get("dataStatus") == "insufficient" and value.get("insufficientReason"):
            normalized["insufficientReason"] = str(value["insufficientReason"])[:120]
        return normalized

    @staticmethod
    def _normalize_format_segments(value: object) -> List[Dict]:
        if not isinstance(value, list) or len(value) > MAX_FORMAT_SEGMENTS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                "格式区段数量超过安全上限。",
                status_code=413,
            )
        segments = []
        previous_end = 0
        for segment in value:
            if not isinstance(segment, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式区段格式无效。",
                )
            start = segment.get("start")
            end = segment.get("end")
            if (
                type(start) is not int or type(end) is not int
                or start < 0 or end <= start or start < previous_end
            ):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_BLOCK_INVALID",
                    "格式区段范围无效或未按顺序排列。",
                )
            segments.append({
                "start": start,
                "end": end,
                "format": DeterministicFormatReviewService._normalize_format_facts(
                    segment.get("format", {})
                ),
            })
            previous_end = end
        return segments

    @classmethod
    def _normalize_source_coverage(cls, value: object) -> Dict:
        if value in (None, {}):
            return {}
        if not isinstance(value, dict):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                "格式审查覆盖统计格式无效。",
            )
        result = {}
        header_footer = value.get("headerFooter")
        if header_footer is not None:
            if not isinstance(header_footer, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                    "页眉页脚覆盖统计格式无效。",
                )
            result["headerFooter"] = {
                area: deepcopy(header_footer[area])
                for area in ("header", "footer")
                if isinstance(header_footer.get(area), dict)
            }
        objects = value.get("unsupportedObjects", [])
        if not isinstance(objects, list) or len(objects) > 64:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                "不支持对象统计格式无效。",
            )
        normalized_objects = []
        for item in objects:
            if not isinstance(item, dict):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                    "不支持对象统计格式无效。",
                )
            count = item.get("count", 0)
            if type(count) is not int or count < 0:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_COVERAGE_INVALID",
                    "不支持对象数量必须是非负整数。",
                )
            normalized_objects.append({
                "type": str(item.get("type") or "unknown")[:64],
                "count": count,
                "status": str(item.get("status") or "not_supported")[:32],
                **({"reason": str(item["reason"])[:120]} if item.get("reason") else {}),
            })
        if normalized_objects:
            result["unsupportedObjects"] = normalized_objects
        return result

    @classmethod
    def _normalize_table_rows(cls, value: object) -> List[Dict]:
        if value in (None, []):
            return []
        if not isinstance(value, list) or len(value) > MAX_FORMAT_BLOCKS:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TABLE_INVALID",
                "格式审查表格行数超出限制。",
            )
        rows = []
        for row_index, row in enumerate(value, 1):
            if not isinstance(row, dict) or not isinstance(row.get("cells", []), list):
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_TABLE_INVALID",
                    "格式审查表格行或单元格格式无效。",
                )
            cells = []
            for column_index, cell in enumerate(row.get("cells", []), 1):
                if not isinstance(cell, dict):
                    raise AdapterError(
                        "DETERMINISTIC_FORMAT_REVIEW_TABLE_INVALID",
                        "格式审查表格单元格格式无效。",
                    )
                cells.append({
                    "cellId": str(cell.get("cellId") or "cell-{0}-{1}".format(row_index, column_index)),
                    "rowIndex": int(cell.get("rowIndex", row_index) or row_index),
                    "columnIndex": int(cell.get("columnIndex", column_index) or column_index),
                    "rowSpan": int(cell.get("rowSpan", 1) or 1),
                    "columnSpan": int(cell.get("columnSpan", 1) or 1),
                    "text": str(cell.get("text") or ""),
                    "format": cls._normalize_format_facts(cell.get("format", {})),
                })
            rows.append({"rowIndex": int(row.get("rowIndex", row_index) or row_index), "cells": cells})
        return rows

    @classmethod
    def classify_capacity(cls, review_character_count: object, raise_error: bool = False) -> Dict:
        if type(review_character_count) is not int or review_character_count < 0:
            error = AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "格式审查字符数必须是非负整数。",
                status_code=413,
            )
            if raise_error:
                raise error
            return {"tier": "rejected", "accepted": False, "requiresConfirmation": False}
        if review_character_count > MAX_FORMAT_LARGE_CHARACTERS:
            error = AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "格式审查超过 120,000 个审查字符，未保留部分快照。",
                status_code=413,
            )
            if raise_error:
                raise error
            return {"tier": "rejected", "accepted": False, "requiresConfirmation": False}
        return {
            "tier": "standard" if review_character_count <= MAX_FORMAT_STANDARD_CHARACTERS else "large",
            "accepted": True,
            "requiresConfirmation": False,
        }

    @classmethod
    def _format_metrics(cls, blocks: List[Dict], source_coverage: Optional[Dict] = None) -> Dict:
        in_scope = [block for block in blocks if block.get("scope") == "in_scope"]
        text_values = [block.get("text", "") for block in in_scope]
        format_segment_count = 0
        table_cell_count = 0
        insufficient_blocks = 0
        unsupported_objects = []

        def count_table(table: Dict) -> None:
            nonlocal table_cell_count, format_segment_count, insufficient_blocks
            for row in table.get("rows", []) if isinstance(table.get("rows", []), list) else []:
                for cell in row.get("cells", []) if isinstance(row, dict) and isinstance(row.get("cells", []), list) else []:
                    table_cell_count += 1
                    cell_format = cell.get("format", {}) if isinstance(cell, dict) else {}
                    segments = cell_format.get("segments", []) if isinstance(cell_format, dict) else []
                    format_segment_count += len(segments) if isinstance(segments, list) else 0
                    if isinstance(cell_format, dict) and cell_format.get("dataStatus") == "insufficient":
                        insufficient_blocks += 1
            for nested in table.get("nestedTables", []) if isinstance(table.get("nestedTables", []), list) else []:
                if isinstance(nested, dict):
                    count_table(nested)

        for block in blocks:
            facts = block.get("format", {}) if isinstance(block.get("format", {}), dict) else {}
            segments = facts.get("segments", [])
            format_segment_count += len(segments) if isinstance(segments, list) else 0
            if facts.get("dataStatus") == "insufficient":
                insufficient_blocks += 1
            if block.get("blockType") == "table":
                table_cell_count += 0
                count_table(block)
            for item in block.get("unsupportedObjects", []) if isinstance(block.get("unsupportedObjects", []), list) else []:
                if isinstance(item, dict):
                    unsupported_objects.append(deepcopy(item))

        source_coverage = source_coverage if isinstance(source_coverage, dict) else {}
        for item in source_coverage.get("unsupportedObjects", []) if isinstance(source_coverage.get("unsupportedObjects", []), list) else []:
            if isinstance(item, dict):
                unsupported_objects.append(deepcopy(item))
        unsupported_object_count = sum(int(item.get("count", 0) or 0) for item in unsupported_objects)
        unsupported_by_type = {}
        for item in unsupported_objects:
            object_type = str(item.get("type") or "unknown")
            unsupported_by_type[object_type] = unsupported_by_type.get(object_type, 0) + int(item.get("count", 0) or 0)
        structure = [
            {
                "blockId": block["blockId"],
                "blockType": block["blockType"],
                "scope": block["scope"],
                "paragraphIndex": block.get("paragraphIndex", 0),
                "range": block.get("range", {}),
                "tableId": block.get("tableId", ""),
                "tableIndex": block.get("tableIndex", 0),
                "headingLevel": block.get("headingLevel", 0),
                "listLabel": block.get("listLabel", ""),
                "captionFor": block.get("captionFor", ""),
                "rows": cls._table_structure_rows(block.get("rows", [])),
                "nestedTables": [
                    cls._table_structure_projection(table)
                    for table in block.get("nestedTables", [])
                    if isinstance(table, dict)
                ],
            }
            for block in blocks
        ]
        formats = [
            {
                "blockId": block["blockId"],
                "scope": block["scope"],
                "format": block.get("format", {}),
                "segments": block.get("format", {}).get("segments", []),
                "table": cls._table_format_projection(block)
                if block.get("blockType") == "table" else None,
            }
            for block in blocks
        ]
        character_count = sum(
                len(value.encode("utf-16-le")) // 2 for value in text_values
            )
        capacity = cls.classify_capacity(character_count)
        coverage = {
                "inScopeBlockCount": len(in_scope),
                "contextBlockCount": len(blocks) - len(in_scope),
                "paragraphCount": sum(1 for block in in_scope if block["blockType"] in {"paragraph", "heading", "listItem"}),
                "tableCount": sum(1 for block in in_scope if block["blockType"] == "table"),
                "captionCount": sum(1 for block in in_scope if block["blockType"] == "caption"),
                "tableCellCount": table_cell_count,
                "formatSegmentCount": format_segment_count,
                "formatDataStatus": "insufficient" if insufficient_blocks else "verified",
                "formatDataInsufficientBlockCount": insufficient_blocks,
                "unsupportedObjectCount": unsupported_object_count,
                "unsupportedObjectsByType": unsupported_by_type,
            }
        image_inventory = collect_image_inventory({"formatBlocks": blocks})
        coverage.update({
            key: value for key, value in image_inventory.items() if key != "images"
        })
        if isinstance(source_coverage.get("headerFooter"), dict):
            coverage["headerFooter"] = deepcopy(source_coverage["headerFooter"])
        if unsupported_objects:
            coverage["unsupportedObjects"] = unsupported_objects
        return {
            "characterCount": character_count,
            "contentSha256": hashlib.sha256("\n".join(text_values).encode("utf-8")).hexdigest(),
            "structureSha256": hashlib.sha256(json.dumps(structure, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "formatSha256": hashlib.sha256(json.dumps(formats, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "coverage": coverage,
            "capacityTier": capacity["tier"],
            "complexity": {
                "blockCount": len(blocks),
                "tableCellCount": table_cell_count,
                "formatSegmentCount": format_segment_count,
                "unsupportedObjectCount": unsupported_object_count,
            },
        }

    @staticmethod
    def _enforce_complexity(metrics: Dict, snapshot_bytes: int) -> None:
        limits = {
            "blockCount": MAX_FORMAT_BLOCKS,
            "tableCellCount": MAX_FORMAT_TABLE_CELLS,
            "formatSegmentCount": MAX_FORMAT_SEGMENTS,
            "unsupportedObjectCount": MAX_FORMAT_UNSUPPORTED_OBJECTS,
        }
        for dimension, limit in limits.items():
            actual = int(metrics.get("complexity", {}).get(dimension, 0) or 0)
            if actual > limit:
                raise AdapterError(
                    "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                    "格式审查{0}超过安全上限（实际 {1}，上限 {2}）。".format(dimension, actual, limit),
                    status_code=413,
                )
        if snapshot_bytes > MAX_FORMAT_SNAPSHOT_BYTES:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_COMPLEX",
                "格式审查累计快照字节数超过安全上限（实际 {0}，上限 {1}）。".format(
                    snapshot_bytes, MAX_FORMAT_SNAPSHOT_BYTES
                ),
                status_code=413,
            )

    @staticmethod
    def _merge_coverage(current: object, increment: Dict) -> Dict:
        result = dict(current) if isinstance(current, dict) else {}
        additive = {
            "inScopeBlockCount", "contextBlockCount", "paragraphCount", "tableCount",
            "captionCount", "tableCellCount", "formatSegmentCount",
            "formatDataInsufficientBlockCount", "unsupportedObjectCount",
            "imageCount", "supportedImageCount", "missingFigureCaptionCount",
            "textEvidenceOnlyCount", "notAssessableCount", "pixelExportCount",
            "pixelUploadCount", "pixelInspectedCount",
        }
        for key, value in increment.items():
            if key in additive:
                result[key] = int(result.get(key, 0) or 0) + int(value or 0)
            else:
                result[key] = deepcopy(value)
        return result

    @classmethod
    def _batch_response(cls, record: Dict, batch: Dict, idempotent: bool) -> Dict:
        return {
            "snapshotId": record["snapshotId"],
            "sequence": batch["sequence"],
            "status": "uploaded",
            "reviewCharacterCount": record.get("reviewCharacterCount", 0),
            "blockCount": record.get("blockCount", 0),
            "coverage": deepcopy(record.get("coverage", {})),
            "capacityTier": record.get("capacityTier", "standard"),
            "structureSha256": batch.get("structureSha256", ""),
            "formatSha256": batch.get("formatSha256", ""),
            "idempotent": idempotent,
        }

    @classmethod
    def _request_from_blocks(cls, record: Dict, blocks: List[Dict], metrics: Dict) -> Dict:
        paragraphs = []
        headings = []
        for block in blocks:
            if block.get("scope") != "in_scope" or block.get("blockType") not in {"paragraph", "heading", "listItem", "caption"}:
                continue
            facts = block.get("format", {})
            heading_level = normalize_outline_level(block.get("headingLevel", facts.get("outlineLevel", 0)))
            paragraph = {
                "index": normalize_paragraph_index(block.get("paragraphIndex")) or 0,
                "text": block.get("text", ""),
                "styleName": facts.get("styleName"),
                "fontName": facts.get("fontName"),
                "fontSize": facts.get("fontSize"),
                "alignment": facts.get("alignment"),
                "outlineLevel": heading_level,
                "lineSpacing": facts.get("lineSpacing"),
                "firstLineIndent": facts.get("firstLineIndent"),
                "spaceBefore": facts.get("spaceBefore"),
                "spaceAfter": facts.get("spaceAfter"),
                "leftIndent": facts.get("leftIndent"),
                "rightIndent": facts.get("rightIndent"),
                "bold": facts.get("bold"),
                "italic": facts.get("italic"),
                "underline": facts.get("underline"),
            }
            paragraphs.append(paragraph)
            if block.get("blockType") == "heading" and heading_level and heading_level > 0:
                headings.append({
                    "level": heading_level,
                    "text": block.get("text", ""),
                    "paragraphIndex": normalize_paragraph_index(paragraph["index"]),
                })
        document_structure = {
            "formatSnapshotSchemaVersion": FORMAT_SNAPSHOT_SCHEMA_VERSION,
            "formatBlocks": deepcopy(blocks),
            "contentFingerprint": metrics["contentSha256"],
            "formatFingerprint": metrics["formatSha256"],
            "structureFingerprint": metrics["structureSha256"],
            "coverage": deepcopy(metrics["coverage"]),
            "scope": deepcopy(record.get("scope", {})),
            "page_setup": deepcopy(record.get("pageSetup", {})),
            "verification": "two_pass_verified",
        }
        return {
            "documentId": "format-snapshot-" + str(record.get("documentIdSha256", ""))[:24],
            "scene": "word",
            "selectionMode": record.get("selectionMode", "document"),
            "content": {
                "plainText": "\n".join(item["text"] for item in paragraphs),
                "paragraphs": paragraphs,
                "headings": headings,
                "documentStructure": document_structure,
            },
            "options": {"templateId": record.get("templateId") or "technical-file-format-requirements"},
        }

    def _verify_token(self, record: Dict, token: object) -> None:
        if not isinstance(token, str) or not secrets.compare_digest(
            record.get("snapshotTokenSha256", ""),
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        ):
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照凭证无效或已过期。",
                status_code=403,
            )

    @staticmethod
    def _image_document_binding(record: Dict, payload: Dict) -> Dict:
        if not isinstance(payload, dict):
            raise AdapterError("IMAGE_EXPORT_DOCUMENT_CHANGED", "图片导出文档绑定信息无效。")
        return {
            "documentIdentity": deepcopy(payload.get("documentIdentity")),
            "editSequence": str(payload.get("editSequence")) if payload.get("editSequence") is not None else None,
        }

    def _snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.reviewer, "snapshot_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver())
        except Exception:
            return {"authSnapshotStatus": "unavailable"}

    @staticmethod
    def _normalize_page_setup(value: object) -> Dict:
        if value in (None, {}):
            return {}
        if not isinstance(value, dict) or set(value) - {
            "paperSize", "marginTop", "marginBottom", "marginLeft", "marginRight"
        }:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_PAGE_SETUP_INVALID",
                "格式审查页面设置事实格式无效。",
            )
        return {key: deepcopy(value[key]) for key in value}

    @staticmethod
    def _table_structure_rows(rows: object) -> List[Dict]:
        if not isinstance(rows, list):
            return []
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = []
            for cell in row.get("cells", []):
                if not isinstance(cell, dict):
                    continue
                cells.append({
                    "cellId": cell.get("cellId", ""),
                    "rowIndex": cell.get("rowIndex", 0),
                    "columnIndex": cell.get("columnIndex", 0),
                    "rowSpan": cell.get("rowSpan", 1),
                    "columnSpan": cell.get("columnSpan", 1),
                })
            normalized.append({"rowIndex": row.get("rowIndex", 0), "cells": cells})
        return normalized

    @classmethod
    def _table_structure_projection(cls, table: Dict) -> Dict:
        return {
            "tableId": table.get("tableId", ""),
            "tableIndex": table.get("tableIndex", 0),
            "rows": cls._table_structure_rows(table.get("rows", [])),
            "nestedTables": [
                cls._table_structure_projection(item)
                for item in table.get("nestedTables", [])
                if isinstance(item, dict)
            ],
        }

    @classmethod
    def _table_format_projection(cls, block: Dict) -> Dict:
        def project(table: Dict) -> Dict:
            rows = []
            for row in table.get("rows", []) if isinstance(table.get("rows", []), list) else []:
                if not isinstance(row, dict):
                    continue
                rows.append({
                    "rowIndex": row.get("rowIndex", 0),
                    "cells": [
                        {
                            "cellId": cell.get("cellId", ""),
                            "format": cell.get("format", {}),
                        }
                        for cell in row.get("cells", [])
                        if isinstance(cell, dict)
                    ],
                })
            return {
                "tableId": table.get("tableId", ""),
                "rows": rows,
                "nestedTables": [
                    project(item)
                    for item in table.get("nestedTables", [])
                    if isinstance(item, dict)
                ],
            }

        return project(block)

    def _load_snapshot(self, snapshot_id: str) -> Dict:
        with self._lock:
            cached = self._snapshots.get(snapshot_id)
        path = cached.get("path") if cached else self._snapshot_dir(snapshot_id)
        snapshot_file = path / "snapshot.json" if path.is_dir() else path
        if not snapshot_file.exists():
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_NOT_FOUND",
                "确定性格式审查快照不存在或已过期。",
                status_code=404,
            )
        try:
            record = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_INVALID",
                "确定性格式审查快照不可读取。",
                status_code=409,
            ) from exc
        record["path"] = path
        return record

    def _remove_snapshot(self, snapshot_id: str, cleanup_images: bool = True) -> None:
        if not snapshot_id:
            return
        with self._lock:
            record = self._snapshots.pop(snapshot_id, None)
        path = record.get("path") if record else self._snapshot_dir(snapshot_id)
        try:
            if path.is_dir():
                shutil.rmtree(str(path), ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        if cleanup_images:
            self.image_asset_store.cleanup_snapshot(snapshot_id)

    def _cleanup_expired(self) -> None:
        now = self._wall_clock()
        with self._lock:
            records = list(self._snapshots.items())
        for snapshot_id, record in records:
            if now - float(record.get("createdAt", now)) > SNAPSHOT_TTL_SECONDS:
                self._remove_snapshot(snapshot_id)

        root = self.staging_root
        if not root.exists() or not root.is_dir():
            return
        try:
            children = list(root.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_file() or not child.name.startswith("report-"):
                continue
            job_id = child.name[len("report-"):-len(".json")] if child.name.endswith(".json") else ""
            try:
                report = json.loads(child.read_text(encoding="utf-8"))
                expired = (
                    not isinstance(report, dict)
                    or report.get("reportSha256") != _report_sha256(report)
                    or now >= float(report.get("reportExpiresAt", 0) or 0)
                )
                if expired:
                    child.unlink(missing_ok=True)
                    with self._lock:
                        self._reports.pop(job_id, None)
            except (OSError, ValueError, TypeError):
                continue
        for child in children:
            if not child.is_dir() or not SAFE_ID.fullmatch(child.name):
                continue
            try:
                record = json.loads((child / "snapshot.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            expires_at = float(record.get("expiresAt", 0) or 0)
            if expires_at and now >= expires_at:
                self._remove_snapshot(child.name)


deterministic_format_review_service = DeterministicFormatReviewService()
