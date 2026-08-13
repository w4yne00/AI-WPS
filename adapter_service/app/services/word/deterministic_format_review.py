import hashlib
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
from app.core.runtime_paths import resolve_runtime_paths
from app.services.document_normalizer import body_paragraphs
from app.services.long_task_coordinator import (
    LongTaskCoordinator,
    get_long_task_coordinator,
)
from app.services.word.format_reviewer import WordFormatReviewer


TASK_TYPE = "word.format_review.deterministic"
MAX_REVIEW_CHARACTERS = 20_000
MAX_PARAGRAPHS = 200
MAX_SNAPSHOT_BYTES = 512 * 1024
FORMAT_SNAPSHOT_SCHEMA_VERSION = "word.format_review.snapshot.v2"
MAX_FORMAT_BLOCKS = 10_000
MAX_FORMAT_BATCHES = 1024
MAX_FORMAT_BATCH_BYTES = 2 * 1024 * 1024
MAX_FORMAT_SNAPSHOT_BYTES = 16 * 1024 * 1024
SNAPSHOT_TTL_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
FORMAT_BLOCK_TYPES = {"paragraph", "heading", "listItem", "table", "caption", "context"}
FORMAT_SCOPES = {"in_scope", "context"}


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
        self._lock = threading.Lock()
        self._snapshot_mutation_lock = threading.Lock()

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
            "editSequence": self._optional_scalar(payload.get("editSequence")),
            "batches": [],
            "snapshotBytes": 0,
            "reviewCharacterCount": 0,
            "blockCount": 0,
            "coverage": {"inScopeBlockCount": 0, "contextBlockCount": 0},
        }
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
        if total_characters > 120000:
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_TOO_LARGE",
                "格式审查最多支持 120,000 个审查字符，未保留部分快照。",
                status_code=413,
            )
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
        metrics = self._format_metrics(blocks)
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
        if any(payload.get(key) != value for key, value in expected.items()):
            self._remove_snapshot(snapshot_id)
            raise AdapterError(
                "DETERMINISTIC_FORMAT_REVIEW_SNAPSHOT_MISMATCH",
                "格式审查快照首遍指标不一致，已清理暂存数据，请停止编辑后重试。",
                status_code=409,
            )
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
        self._remove_snapshot(snapshot_id)
        return self.coordinator.submit(
            job_id=job_id,
            trace_id=trace_id,
            task_type=TASK_TYPE,
            runner=self._run,
            snapshot={
                "request": request,
                "snapshotId": snapshot_id,
                "selectionMode": record.get("selectionMode", request.selection_mode),
                "contentSha256": record.get("contentSha256", ""),
                "structureSha256": record.get("structureSha256", ""),
                "formatSha256": record.get("formatSha256", ""),
            },
            failure_code="DETERMINISTIC_FORMAT_REVIEW_JOB_FAILED",
            failure_message="确定性格式审查后台任务执行失败，请稍后重试。",
            public_metadata={"runningMessage": "正在执行确定性格式审查。"},
        )

    def get_job(self, job_id: str) -> Optional[Dict]:
        self._require_enabled()
        if not SAFE_ID.fullmatch(str(job_id or "")):
            return None
        return self.coordinator.get(job_id, task_type=TASK_TYPE)

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
            result = self.reviewer.review(request, trace_id="")
            issues = result.get("issues", [])
            summary = result.setdefault("summary", {})
            summary.update(
                {
                    "executionStatus": "completed",
                    "complianceStatus": "violations_found" if issues else "passed",
                    "coverageStatus": "complete",
                    "semanticStatus": "not_needed",
                    "readOnly": True,
                }
            )
            structure = request.content.document_structure or {}
            if structure.get("formatSnapshotSchemaVersion") == FORMAT_SNAPSHOT_SCHEMA_VERSION:
                summary.update(
                    {
                        "snapshotVerification": "two_pass_verified",
                        "snapshotContentSha256": snapshot.get("contentSha256", ""),
                        "snapshotStructureSha256": snapshot.get("structureSha256", ""),
                        "snapshotFormatSha256": snapshot.get("formatSha256", ""),
                        "scope": snapshot.get("selectionMode", "document"),
                        "coverage": deepcopy(structure.get("coverage", {})),
                    }
                )
            return result
        finally:
            self._remove_snapshot(snapshot.get("snapshotId", ""))

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
            if block_type == "table":
                normalized_item["rows"] = cls._normalize_table_rows(item.get("rows", []))
                normalized_item["nestedTables"] = item.get("nestedTables", []) if isinstance(item.get("nestedTables", []), list) else []
            seen.add(block_id)
            normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _normalize_format_facts(value: object) -> Dict:
        if not isinstance(value, dict):
            return {}
        allowed = {
            "styleName", "fontName", "fontSize", "bold", "italic", "underline",
            "alignment", "lineSpacing", "firstLineIndent", "spaceBefore", "spaceAfter",
            "leftIndent", "rightIndent", "segments", "dataStatus"
        }
        return {
            key: deepcopy(value[key])
            for key in allowed
            if key in value
        }

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
    def _format_metrics(cls, blocks: List[Dict]) -> Dict:
        in_scope = [block for block in blocks if block.get("scope") == "in_scope"]
        text_values = [block.get("text", "") for block in in_scope]
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
        return {
            "characterCount": sum(
                len(value.encode("utf-16-le")) // 2 for value in text_values
            ),
            "contentSha256": hashlib.sha256("\n".join(text_values).encode("utf-8")).hexdigest(),
            "structureSha256": hashlib.sha256(json.dumps(structure, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "formatSha256": hashlib.sha256(json.dumps(formats, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "coverage": {
                "inScopeBlockCount": len(in_scope),
                "contextBlockCount": len(blocks) - len(in_scope),
                "paragraphCount": sum(1 for block in in_scope if block["blockType"] in {"paragraph", "heading", "listItem"}),
                "tableCount": sum(1 for block in in_scope if block["blockType"] == "table"),
                "captionCount": sum(1 for block in in_scope if block["blockType"] == "caption"),
            },
        }

    @staticmethod
    def _merge_coverage(current: object, increment: Dict) -> Dict:
        result = dict(current) if isinstance(current, dict) else {}
        for key, value in increment.items():
            result[key] = int(result.get(key, 0) or 0) + int(value or 0)
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
            "structureSha256": batch.get("structureSha256", ""),
            "formatSha256": batch.get("formatSha256", ""),
            "idempotent": idempotent,
        }

    @classmethod
    def _request_from_blocks(cls, record: Dict, blocks: List[Dict], metrics: Dict) -> Dict:
        paragraphs = []
        for block in blocks:
            if block.get("scope") != "in_scope" or block.get("blockType") not in {"paragraph", "heading", "listItem", "caption"}:
                continue
            facts = block.get("format", {})
            paragraph = {
                "index": int(block.get("paragraphIndex", len(paragraphs) + 1) or len(paragraphs) + 1),
                "text": block.get("text", ""),
                "styleName": facts.get("styleName"),
                "fontName": facts.get("fontName"),
                "fontSize": facts.get("fontSize"),
                "alignment": facts.get("alignment"),
                "outlineLevel": block.get("headingLevel", facts.get("outlineLevel", 0)),
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
        document_structure = {
            "formatSnapshotSchemaVersion": FORMAT_SNAPSHOT_SCHEMA_VERSION,
            "formatBlocks": deepcopy(blocks),
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
                "headings": [],
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

    def _remove_snapshot(self, snapshot_id: str) -> None:
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
